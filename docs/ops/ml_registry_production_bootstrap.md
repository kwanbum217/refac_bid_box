# 운영 환경 ml_registry 재생성 및 드리프트 감시 부트스트랩 런북

> **작성일**: 2026-09-18
> **상태**: 확정 (Active)
> **대상 환경**: 운영 서버 (Production), 로컬 개발/스테이징
> **관련 모듈**: `src/ml/monitoring.py`, `src/tasks/scheduled_tasks.py`, `src/tasks/retrain_task.py`, `src/ml/promotion.py`, `src/app/core/config.py`
> **관련 스크립트**: `scripts/generate_drift_baseline.py`, `scripts/promote_model.py`, `scripts/sync_model_files.py`, `scripts/db_readonly_query.py`
> **단일 진실 원천(SSoT)**: `AGENTS.md`, `docs/context/CURRENT_STATE.md`

---

## 1. 개요 및 배경

본 문서는 운영 환경에 `ml_registry/` 디렉터리가 존재하지 않는 상태에서, PSI 드리프트 감시 및 주간 재학습 승격 판정이 정상 동작하도록 기준선(Baseline)을 안전하게 재생성하는 운영 표준 절차서(Runbook)입니다.

### 1.1 ml_registry 부재 원인

1. **Git 미추적 정책**: `ml_registry/` 디렉터리는 학습 및 모니터링 런타임 아티팩트를 보관하는 경로로, `.gitignore:198`에 등재되어 버전 관리 대상에서 제외되어 있습니다.
2. **설정 기본값**: `src/app/core/config.py:202`의 `MODEL_REGISTRY_DIR` 기본값은 `"ml_registry"`입니다.
3. **컨테이너 마운트**: `docker-compose.yml:95, 160` 및 `docker-compose.prod.yml`에서 호스트의 `./ml_registry` 경로를 컨테이너 내부 `/app/ml_registry`로 볼륨 마운트합니다.
4. **결과**: Git 저장소를 새로 clone 하여 배포한 운영 호스트에는 `ml_registry/` 디렉터리가 존재하지 않거나 빈 디렉터리 상태로 초기화됩니다. 가중치 배포 도구인 `scripts/sync_model_files.py`는 `data/model_files/`, `data/model_backups/`, `data/model_metrics/`만을 번들링하므로 `ml_registry/`는 포함되지 않습니다.

---

## 2. ml_registry 부재 시 발생하는 구체적 장애 및 코드 근거

운영 환경에 `ml_registry/`가 없으면 시스템 기동 자체는 실패하지 않으나, 백그라운드 모니터링 및 재학습 경로에서 다음과 같은 기능 마비가 발생합니다.

### 2.1 PSI 드리프트 모니터링 무력화 (`drift_monitor_task`)

- **코드 근거**:
  - `src/app/core/config.py:80`: `ML_DRIFT_MONITOR_ENABLED` 기본값은 `True`입니다.
  - `src/tasks/scheduled_tasks.py:622-623`: `drift_monitor_task` 함수는 기본적으로 `registry_dir="ml_registry"`를 탐색합니다.
  - `src/tasks/scheduled_tasks.py:645-649`: 매일 04:00에 `CATEGORY_MODEL_NAMES`의 전 카테고리(`Servc`, `Thng`, `Cnstwk`)를 순회하며 `baseline_dir = Path(registry_dir) / model_name / "baseline"` 경로의 아티팩트를 로드합니다.
  - `src/ml/monitoring.py:208-218`: `load_baseline_distributions`는 `baseline_dir / "feature_distributions_v1.json"` 파일이 없으면 `None`을 반환합니다.
  - `src/tasks/scheduled_tasks.py:652-678`: `if not baseline_dist:` 분기에서 "baseline 분포 아티팩트가 없습니다" 로그를 남기고, `retrain_logs` 테이블에 `status="INSUFFICIENT_DATA"` 및 `baseline_version="-"`로 기록한 뒤 카테고리를 건너뜁니다 (`results[category] = {"status": "skipped", "reason": "no_baseline"}`).
- **장애 현상**:
  - 운영 DB에 실제 입찰·낙찰 데이터가 충분히 누적되어 있어도 기준 분포가 없어 다차원 PSI 계산(`check_dataset_drift`)과 알림 발신(`notify_drift_detected`)이 일절 수행되지 않습니다.
  - 전 카테고리가 매일 `INSUFFICIENT_DATA` 및 `no_baseline` 상태로 스킵되어 데이터 드리프트를 전혀 감지할 수 없습니다.

### 2.2 주간 재학습 승격 판정 거부 (`run_retrain_pipeline_task`)

- **코드 근거**:
  - `src/tasks/retrain_task.py:68-110`: `_load_champion_metrics(model_name, registry_dir="ml_registry")` 함수는 서빙본 사이드카 지표가 없을 때 `registry_dir / model_name` 디렉터리에서 이전 champion 버전을 탐색합니다. `ml_registry`가 없으면 `(NO_CHAMPION, {})`를 반환합니다.
  - `src/tasks/retrain_task.py:204-235`: `champion_metrics`가 비어 있으면 모델 간 성능 비교(`compare_champion_vs_challenger`)를 수행하지 못하고, `recommendation="REJECT_CHALLENGER"` 및 "비교 대상 champion 지표가 없습니다. 최초 승격은 지표 확인 후 수동으로 수행하십시오." 사유로 승격이 자동 거부됩니다.
- **장애 현상**:
  - 매주 월요일 03:00 정기 재학습이 수행되어도 챌린저 모델의 승격 추천이 무조건 기각 처리됩니다.

### 2.3 모델 승격 및 롤백 CLI 상태 점검 실패 (`scripts/promote_model.py`)

- **코드 근거**:
  - `src/ml/promotion.py:40`: `REGISTRY_ROOT = PROJECT_ROOT / "ml_registry"`
  - `scripts/promote_model.py:84-88`: `_registry_models(registry_dir)`는 `registry_dir`가 없으면 빈 리스트를 반환합니다.
  - `scripts/promote_model.py:99-101`: `uv run python scripts/promote_model.py status` 실행 시 "레지스트리에 학습 아티팩트가 없습니다: ml_registry"를 출력하며 **종료 코드 1**로 실패합니다.
  - `scripts/promote_model.py:193-197`: 판정 파일 생성(`create-verdict`) 및 승격(`promote`) 시 소스 디렉터리가 없어 처리가 차단됩니다.

---

## 3. 레짐 전환(2026-05-26)과 --start-at 필수 지정 근거

기준선(Baseline) 생성 시 `--start-at` 옵션을 2026-05-26 이후로 지정해야 하는 이유는 제도적 규정 변경에 따른 통계적 왜곡을 방지하기 위함입니다.

1. **제도적 레짐 시프트 (Regime Shift)**:
   - 2026-05-26 대한민국 조달청의 공공조달 적격심사 기준 개정으로 낙찰하한율이 **2%p 일괄 상향**되었습니다.
   - 코드 상에 `src/ml/features.py:48`의 `REGIME_SHIFT_DATE = datetime(2026, 5, 26)`로 명시되어 있습니다.
2. **과거 데이터 혼입 위험성**:
   - 2026-05-26 이전의 낙찰률 및 기초금액 대비 투찰 분포는 현행 규정과 전혀 다른 이질적인 통계 모집단입니다.
   - 이전 데이터가 baseline 분포에 포함되면 현재 운영 데이터의 정상적인 낙찰률 변화가 거대한 가짜 드리프트(False Positive PSI >= 0.2)로 감지되거나, 실제 중요한 데이터 드리프트가 희석되어 감지되지 않습니다.
3. **기계적 안전 장치 (`scripts/generate_drift_baseline.py`)**:
   - `scripts/generate_drift_baseline.py:178-185`: `--write` 플래그 사용 시 `--start-at` 인자가 누락되면 "구간 인자를 생략하면 전체 이력이 되어 레짐 전환 이전 구간이 섞인 baseline 이 만들어질 수 있습니다"라는 오류 메시지와 함께 **종료 코드 2**로 즉시 실행을 거부합니다.
   - 따라서 모든 baseline 생성 절차는 `--start-at 2026-05-26` 이상의 날짜를 반드시 명시해야 합니다.

---

## 4. 재생성 실행 절차 (단계별 실행 표)

운영 환경에서 `ml_registry`를 구성하고 드리프트 감시를 정상화하는 단계별 절차입니다. 모든 명령은 사전에 `--help`로 인자와 동작을 검증한 공식 CLI만 사용합니다.

| 단계 | 단계명 | 실행 위치 | 목적 및 실행 명령 | 성공 판정 기준 |
| --- | --- | :---: | --- | --- |
| Step 0 | 가중치 번들 동기화 검증 | 운영 서버 | 서빙 가중치 및 사이드카 지표 무결성 점검<br>`uv run python scripts/sync_model_files.py verify --input dist/model_files_bundle.tar.gz` | 종료 코드 0 |
| Step 1 | 디렉터리 구조 확인 | 운영 서버 | `ml_registry/` 디렉터리 생성 및 컨테이너 볼륨 연동 준비<br>(필요 시 디렉터리 생성 및 권한 점검) | 디렉터리 존재 및 쓰기 가능 |
| Step 2 | Servc (용역) baseline Dry-run | 운영 서버 | 용역 표본 수 및 특징 수 사전 검증 (파일 쓰기 없음)<br>`uv run python scripts/generate_drift_baseline.py --category Servc --start-at 2026-05-26 --baseline-version b_20260906_servc_post_regime` | 종료 코드 0, 표본 100건 이상 |
| Step 3 | Servc (용역) baseline 실제 생성 | 운영 서버 | 용역 아티팩트 원자적 기록 (`--write`)<br>`uv run python scripts/generate_drift_baseline.py --category Servc --start-at 2026-05-26 --baseline-version b_20260906_servc_post_regime --write` | 종료 코드 0, `feature_distributions_v1.json` 생성 |
| Step 4 | Thng (물품) baseline Dry-run | 운영 서버 | 물품 표본 수 및 특징 수 사전 검증 (파일 쓰기 없음)<br>`uv run python scripts/generate_drift_baseline.py --category Thng --start-at 2026-05-26 --baseline-version b_20260915_thng_post_regime` | 종료 코드 0, 표본 100건 이상 |
| Step 5 | Thng (물품) baseline 실제 생성 | 운영 서버 | 물품 아티팩트 원자적 기록 (`--write`)<br>`uv run python scripts/generate_drift_baseline.py --category Thng --start-at 2026-05-26 --baseline-version b_20260915_thng_post_regime --write` | 종료 코드 0, `feature_distributions_v1.json` 생성 |
| Step 6 | Cnstwk (공사) baseline Dry-run | 운영 서버 | 공사 표본 수 및 특징 수 사전 검증 (파일 쓰기 없음)<br>`uv run python scripts/generate_drift_baseline.py --category Cnstwk --start-at 2026-05-26 --baseline-version b_20260918_cnstwk_post_regime` | 종료 코드 0, 표본 100건 이상 |
| Step 7 | Cnstwk (공사) baseline 실제 생성 | 운영 서버 | 공사 아티팩트 원자적 기록 (`--write`)<br>`uv run python scripts/generate_drift_baseline.py --category Cnstwk --start-at 2026-05-26 --baseline-version b_20260918_cnstwk_post_regime --write` | 종료 코드 0, `feature_distributions_v1.json` 생성 |
| Step 8 | 레지스트리 상태 점검 | 운영 서버 | 서빙본 및 레지스트리 baseline 상태 대조<br>`uv run python scripts/promote_model.py status` | 종료 코드 0, 모델 목록 정상 출력 |
| Step 9 | 드리프트 감시 이력 확인 | 운영 서버 | DB `retrain_logs` 조회로 감시 정상 작동 판정<br>`uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, champion_version, challenger_version, status, created_at FROM retrain_logs ORDER BY id DESC LIMIT 5"` | 최신 로그 `status` 가 `STABLE` 또는 `DRIFT_DETECTED` 확인 |

---

## 5. 단계별 세부 실행 가이드

### 5.1 Step 0: 사전 가중치 번들 동기화 검증 (운영 서버)

운영 서버에 배포된 모델 가중치(`data/model_files`), 백업(`data/model_backups`), 실측 지표 사이드카(`data/model_metrics`) 번들의 무결성을 확인합니다.

```bash
uv run python scripts/sync_model_files.py verify --input dist/model_files_bundle.tar.gz
```

### 5.2 Step 1: 디렉터리 준비 (운영 서버)

`ml_registry/` 디렉터리가 존재하는지 확인합니다. Docker Compose 기동 환경인 경우 호스트의 `./ml_registry`가 컨테이너 내 `/app/ml_registry`로 마운트되므로 호스트 상에 디렉터리가 준비되어 있어야 합니다.

### 5.3 Step 2 & 3: 용역(Servc) Baseline 생성 (운영 서버)

- **대상 모델**: `servc_institution_v1`
- **식별자 규약**: `b_20260906_servc_post_regime`

1. **사전 확인 (Dry-run)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Servc \
     --start-at 2026-05-26 \
     --baseline-version b_20260906_servc_post_regime
   ```
   - 출력된 원시 행 수, 특징 수, 표본 수(100건 이상)를 확인합니다.

2. **실제 기록 (`--write`)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Servc \
     --start-at 2026-05-26 \
     --baseline-version b_20260906_servc_post_regime \
     --write
   ```
   - 정상 완료 시 `ml_registry/servc_institution_v1/baseline/` 디렉터리에 `feature_distributions_v1.json`과 `metadata.json`이 생성됩니다.

### 5.4 Step 4 & 5: 물품(Thng) Baseline 생성 (운영 서버)

- **대상 모델**: `quantum_leap_v25_pro`
- **식별자 규약**: `b_20260915_thng_post_regime`

1. **사전 확인 (Dry-run)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Thng \
     --start-at 2026-05-26 \
     --baseline-version b_20260915_thng_post_regime
   ```

2. **실제 기록 (`--write`)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Thng \
     --start-at 2026-05-26 \
     --baseline-version b_20260915_thng_post_regime \
     --write
   ```
   - 정상 완료 시 `ml_registry/quantum_leap_v25_pro/baseline/` 디렉터리에 아티팩트가 생성됩니다.

### 5.5 Step 6 & 7: 공사(Cnstwk) Baseline 생성 (운영 서버)

- **대상 모델**: `cnstwk_institution_v1`
- **식별자 규약**: `b_20260918_cnstwk_post_regime`

1. **사전 확인 (Dry-run)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Cnstwk \
     --start-at 2026-05-26 \
     --baseline-version b_20260918_cnstwk_post_regime
   ```

2. **실제 기록 (`--write`)**:
   ```bash
   uv run python scripts/generate_drift_baseline.py \
     --category Cnstwk \
     --start-at 2026-05-26 \
     --baseline-version b_20260918_cnstwk_post_regime \
     --write
   ```
   - 정상 완료 시 `ml_registry/cnstwk_institution_v1/baseline/` 디렉터리에 아티팩트가 생성됩니다.

### 5.6 Step 8: 레지스트리 상태 점검 (운영 서버)

생성 완료 후 승격 관리 도구를 통해 서빙 모델과 레지스트리 상태가 정상 출력되는지 확인합니다.

```bash
uv run python scripts/promote_model.py status
```

- 점검 내용:
  - 각 모델별 서빙 버전 및 지표 정상 출력 여부
  - 더 이상 "레지스트리에 학습 아티팩트가 없습니다" 오류로 조기 종료되지 않는지 확인

### 5.7 Step 9: 드리프트 감시 결과 확인 (운영 서버 / DB 읽기 전용)

정기 감시 태스크(`drift_monitor_task`, 매일 04:00 KST) 실행 후, 또는 태스크 수동 트리거 후 DB 기록을 점검합니다.

```bash
uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, champion_version, challenger_version, status, created_at FROM retrain_logs ORDER BY id DESC LIMIT 5"
```

- 점검 내용:
  - `trigger_source`가 `drift_monitor`인 레코드 확인
  - `status`가 더 이상 `INSUFFICIENT_DATA` (사유: baseline 부재)로 스킵되지 않고, `STABLE` 또는 `DRIFT_DETECTED`로 정상 판정되었는지 확인
  - `challenger_version` 컬럼에 각 모델의 baseline 버전(예: `b_20260906_servc_post_regime`)이 기록되었는지 확인

---

## 6. 되돌리기(Rollback) 절차 및 실패 시 판정 방법

### 6.1 원자적 반영에 따른 자동 안전 장치

`scripts/generate_drift_baseline.py:229-246`는 임시 스테이징 디렉터리(`tempfile.mkdtemp(prefix="drift_baseline_staging_")`)에서 연산과 JSON 직렬화를 모두 완료한 후, `ModelTrainer._update_baseline_atomically`를 통해 디렉터리를 원자적으로 교체합니다.
- 데이터 부족, DB 연결 단절, 연산 예외 발생 시 스테이징 디렉터리는 폐기되며 기존 `ml_registry/` 경로는 일절 변경되지 않습니다.

### 6.2 수동 롤백 및 제거 절차

잘못된 구간이나 식별자로 baseline이 기록되어 되돌려야 하는 경우:

1. **특정 모델 baseline 디렉터리 제거**:
   - 운영 호스트에서 해당 모델의 baseline 디렉터리(`ml_registry/{model_name}/baseline/`)를 삭제하거나 백업 경로로 이동합니다.
2. **삭제 후 시스템 안전성 (Fail-safe)**:
   - `src/tasks/scheduled_tasks.py:652-678`의 설계에 따라 baseline 디렉터리가 부재하면 태스크가 예외로 중단되지 않고, 사유 로그와 함께 `INSUFFICIENT_DATA`로 건너뜁니다.
3. **올바른 인자로 재실행**:
   - 올바른 `--start-at`과 `--baseline-version` 인자를 지정하여 4장의 절차를 다시 수행합니다.

### 6.3 실패 판정 방법 (Triage & Diagnostics)

| 점검 항목 | 정상 판정 기준 | 실패/이상 징후 | 대응 절차 |
| --- | --- | --- | --- |
| **명령 종료 코드** | `0` (성공) | `1` (표본 부족 또는 DB 조회 오류)<br>`2` (사용법 오류: `--start-at` 누락 등) | 1인 경우 DB 적재 상태 확인, 2인 경우 명령행 인자 재확인 |
| **아티팩트 무결성** | `feature_distributions_v1.json` 및 `metadata.json` 존재 및 정상 JSON 파싱 | 파일 부재, 빈 파일, JSON 구문 손상 | baseline 디렉터리 삭제 후 `--write` 재실행 |
| **표본 수 기준** | 원시 행 수 및 특징 프레임 >= 100건 (`DEFAULT_MIN_SAMPLES`) | "표본 부족" 거부 메시지 출력 | 대상 카테고리의 2026-05-26 이후 개찰 데이터 누적 현황 확인 |
| **DB 감시 이력** | `retrain_logs`의 `status`가 `STABLE` 또는 `DRIFT_DETECTED` | `status` 가 `INSUFFICIENT_DATA` (사유: `no_baseline`) 지속 | `ml_registry` 디렉터리가 Docker 컨테이너에 정상 마운트되었는지 확인 |

---

## 7. 향후 모델 승격 및 롤백 연계 안내

부트스트랩 이후 새로운 챌린저 모델이 등록되었을 때의 수동 승격 및 롤백 표준 명령입니다.

```bash
# 서빙본 및 챌린저 비교 상태 확인
uv run python scripts/promote_model.py status

# 용역 모델 승격 예행 (dry-run)
uv run python scripts/promote_model.py promote --model servc_institution_v1 --category Servc

# 용역 모델 승격 실제 교체
uv run python scripts/promote_model.py promote --model servc_institution_v1 --category Servc --apply

# 승격 후 문제 발생 시 즉시 직전 서빙본으로 롤백
uv run python scripts/promote_model.py rollback --model servc_institution_v1
```
