# 2026-09-21 주간 재학습 도래 대비 런북 대조 및 점검 체크리스트

- 작성일: 2026-09-20
- 작성자: 워커 (builder / task_733176231ffd)
- 대상 기준 시각: 2026-09-21 03:00 KST (첫 주간 자동 재학습 도래)
- 대조 대상:
  - 검증 런북: docs/ops/weekly_retrain_verification.md
  - 환경 설정: docker-compose.yml, docker-compose.prod.yml
  - 태스크 및 크론: src/tasks/worker.py, src/tasks/scheduled_tasks.py, src/tasks/retrain_task.py
  - 모델 승격 및 레지스트리: src/ml/promotion.py, src/ml/model_registry.py, scripts/promote_model.py, scripts/retrain_servc_from_parquet.py
  - DB 모델 및 질의 도구: src/app/models/predictions.py, src/app/models/chatbot.py, scripts/db_readonly_query.py

---

## 1. 개요 및 목적

본 문서는 2026-09-21 03:00 KST에 도래하는 첫 주간 정기 자동 재학습을 앞두고, 기존 검증 런북(docs/ops/weekly_retrain_verification.md)의 기재 내용이 현재 코드베이스 및 크론 설정과 정확히 일치하는지 전수 대조한 결과 보고서입니다.

재학습 실행이나 큐 등록(enqueue), 컨테이너 조작을 일절 수행하지 않은 상태에서 코드와 설정만을 정밀 정적 분석하였으며, 도래 시각 이후 코디네이터가 즉시 수행할 수 있는 실재 명령어 기반의 점검 체크리스트를 제공합니다.

---

## 2. 런북 vs 코드 전수 대조 결과표

검증 런북(docs/ops/weekly_retrain_verification.md)의 주요 절차 및 기재 내용을 현재 코드베이스와 대조한 결과는 다음과 같습니다.

| 런북 절 | 런북 기재 내용 | 코드 실제 구현 및 상태 | 일치 여부 | 판정 요약 |
| --- | --- | --- | :---: | --- |
| 1절 (두 경로 비교) | 주간 자동 재학습 진입점: `src/tasks/scheduled_tasks.py::weekly_retrain_task` -> `src/tasks/retrain_task.py::run_retrain_pipeline_task` | `src/tasks/scheduled_tasks.py:519`에서 `run_retrain_pipeline_task` 호출 확인 | 일치 | 진입점 및 호출 흐름 정상 |
| 1절 (두 경로 비교) | 데이터셋 출처: MySQL DB (`build_training_dataset`), 저장 위치: `data/feature_store/dataset_Servc.parquet` 및 `ml_registry` | `src/tasks/retrain_task.py:184-189`, `src/ml/dataset.py:284-285`에서 Parquet 저장 및 `src/ml/trainer.py:107` 레지스트리 기록 확인 | 일치 | 데이터셋 빌드 및 저장 경로 정상 |
| 1절 (두 경로 비교) | 승격 여부: 자동 승격하지 않음 (챌린저 등록 및 권고 기록, 알림 발신) | `run_retrain_pipeline_task` 내 `promote()` 호출 부재, `retrain_logs` 기록 및 알림만 발신 | 일치 | 자동 승격 차단 원칙 준수 |
| 2.1절 (확인 시점) | 02:00 KST 선행 야간 수집 (`nightly_schedule_task`) 성공 확인 | `src/tasks/worker.py:403-405`에 `hour=2, minute=0` 크론 등록 확인 | 일치 | 선행 작업 크론 설정 일치 |
| 2.1절 (확인 시점) | 03:00 KST 주간 재학습 트리거 (`trigger_source="weekly_schedule"`, `category_code="Servc"`) | `src/tasks/worker.py:406-413`에 `weekday="mon", hour=3, minute=0` 등록 확인, `docker-compose.yml:150`에 `ML_WEEKLY_RETRAIN_CATEGORIES=Servc` 지정 확인 | 일치 | 실행 시각 및 인자 일치 |
| 2.2절 (이력 조회) | `scripts/db_readonly_query.py`로 `retrain_logs` 조회 (id, trigger_source, champion_version, challenger_version, status, created_at) | `src/app/models/predictions.py:47-58` `RetrainLog` 컬럼과 질의문 완벽 일치. 단, `created_at`은 UTC로 저장됨 (시차 주의 필요) | 부분 일치 (주의 필요) | 쿼리 동작 정상이나 시간대 표기 안내 누락 |
| 2.3절 (알림 확인) | `notify_retrain_result` 알림 발신 (트리거 출처, 카테고리, 표본 수, 챌린저 vs 챔피언 지표 비교) | `src/tasks/retrain_task.py:261-272`에서 `notify_retrain_result` 호출 확인 | 일치 | 알림 페이로드 구성 일치 |
| 2.4절 (저장소 확인) | `ls -l data/feature_store/dataset_Servc.parquet` 파일 수정 시각 및 행 수(92.5만 이상) 점검 | `data/feature_store/`는 `.gitignore:198` 대상으로 재학습 실행 시 `build_training_dataset`에 의해 동적 생성/갱신됨 | 일치 | 검증 절차 유효 |
| 2.5절 (승격 미발생 확인) | 서빙 모델 메타데이터 확인: `load_serving_metrics("servc_institution_v1")` 또는 `ml_registry/servc_institution_v1/serving_models.json` 확인 | **불일치**: `ml_registry/servc_institution_v1/serving_models.json` 파일은 존재하지 않는 가상 경로임. 실제 서빙본은 `data/model_files/`와 `LIVE` 포인터로 관리되며 `scripts/promote_model.py status`로 확인해야 함 | **불일치** | 유령 경로 기재 (수정 권고 대상) |
| 3절 (신선도 가드) | `scripts/retrain_servc_from_parquet.py` 신선도 가드: `--max-parquet-age-days`(기본 14일, 0 이하 거부 exit 2), 초과 시 exit 1 차단, `--allow-stale-parquet` 우회 | `scripts/retrain_servc_from_parquet.py:45-97` 코드 구현과 완벽 일치 (옵션 및 종료 코드 일치 확인) | 일치 | 신선도 가드 사양 완벽 부합 |
| 4절 (실패 판단 순서) | `PipelineExecution` 테이블에서 02:00 선행 야간 스케줄 상태 점검 및 단계별 트리아지 | `src/app/models/chatbot.py:186-235` `PipelineExecution` 모델 실재 확인, `nightly_schedule` 기록 정상 연동 | 일치 (단, started_at은 UTC) | 트리아지 절차 유효 |

---

## 3. 런북과 코드의 어긋남(Discrepancy) 상세 분석표

대조 과정에서 발견된 런북과 코드 간의 어긋남 및 주의 지점입니다. 런북 문서를 직접 수정하지 않고 본 보고서에 상세 내역, 판정 및 권고 조치를 정리합니다.

| 번호 | 구분 | 런북의 진술 | 코드의 실제 | 어느 쪽이 맞는지 판정 | 권고 조치 |
| :---: | --- | --- | --- | :---: | --- |
| 1 | 서빙 모델 확인 경로 (2.5절) | `ml_registry/servc_institution_v1/serving_models.json`을 확인하여 현행 champion 버전 유지 여부 확인 | `ml_registry/` 디렉터리 내에는 `serving_models.json` 파일이 존재하지 않음. 서빙 모델은 `data/model_files/servc_institution_v1/LIVE` 및 `data/model_files/servc_institution_v1/generations/{generation_id}/metadata.json`에 저장되며, 실측 사이드카는 `data/model_metrics/servc_institution_v1.json`에 위치함 | **코드 실제가 맞음** (런북의 기재 오류) | 런북 참조 시 해당 JSON 파일을 직접 찾지 말고, 공식 점검 CLI인 `uv run python scripts/promote_model.py status --model servc_institution_v1`을 사용하거나 `cat data/model_files/servc_institution_v1/LIVE` 포인터를 확인할 것 |
| 2 | 시각 컬럼 시간대 표기 (2.2절, 4절) | 03:00 KST 주간 재학습 직후 `retrain_logs` 및 `pipeline_executions` 조회 지시 (시간대 언급 없음) | 워커 프로세스는 `TZ=Asia/Seoul`(KST)로 실행되나, MySQL DB의 시각 컬럼(`created_at`, `started_at`)은 `utcnow()`를 통해 **UTC**로 기록됨. 03:00 KST에 실행된 작업은 DB에 **전일 18:00 UTC**로 기록됨 | **코드 실제가 맞음** (런북 설명 미흡) | 코디네이터 점검 시 DB 시각이 9시간 앞선(UTC 기준) 전일 18:00대로 조회됨을 인지하고 당황하지 않도록 체크리스트에 시간대 명시 |
| 3 | Feature Store 디렉터리 존재성 (1.1절, 2.4절) | 기본 feature store 파일 `data/feature_store/dataset_Servc.parquet`이 2026-08-03 시점 파일로 존재한다고 기술 | `data/feature_store/` 디렉터리는 `.gitignore` 대상이며 신규 클론이나 격리 워크트리 환경에는 사전 존재하지 않을 수 있음. 주간 재학습 파이프라인의 `build_training_dataset`이 실행되면서 디렉터리를 생성하고 파일을 기록함 | **코드 실제와 운영 환경의 차이** | 최초 재학습 도래 전에는 파일이 없을 수 있으며, 03:00 KST 재학습 완료 후에 정상 생성되는지 확인하는 것으로 절차 정립 |

---

## 4. 자동 승격 차단 메커니즘 및 코드 근거

시스템 설계 원칙상 주간 자동 재학습은 모델을 **자동으로 승격하지 않습니다**. 이 원칙이 코드베이스 상에서 구체적으로 어떻게 강제되고 있는지 파일 경로와 행 번호로 증명합니다.

### 4.1 파이프라인 실행 경로에서의 호출 배제

1. **스케줄 태스크 진입점 (`src/tasks/scheduled_tasks.py:494-555`)**:
   - `weekly_retrain_task` 함수는 `settings.weekly_retrain_categories`에 지정된 카테고리를 순회하며 `run_retrain_pipeline_task`를 호출(519-523행)합니다.
   - 반환된 결과를 취합하여 `outcome` 딕셔너리를 반환할 뿐, `promote` 모듈을 임포트하거나 호출하는 코드가 일절 존재하지 않습니다.
2. **재학습 파이프라인 내부 (`src/tasks/retrain_task.py:163-282`)**:
   - 215-218행: `metadata = await asyncio.to_thread(category_trainer.train_and_register, df_train)`
     - 카테고리 전용 트레이너를 통해 모델을 학습하고 `ml_registry/{model_name}/{version}` 디렉터리에 챌린저 아티팩트(`model.bin`, `metadata.json`)를 등록합니다.
   - 221-235행: 현행 champion 지표와 비교하여 `verdict` 권고안(`recommendation`)을 산출합니다.
   - 239-244행: 만약 표본 부족으로 홀드아웃 분리에 실패(`holdout_is_overfit=True`)한 경우, 지표 왜곡을 막기 위해 권고안을 무조건 `REJECT_CHALLENGER`로 강제합니다.
   - 245-252행: 판정 결과를 `RetrainLog` 테이블에 기록합니다.
   - 260-272행: 슬랙/웹훅 알림을 전송합니다.
     - **260행 주석**: `# 승격이 수동이므로 권고가 사람에게 닿아야 고리가 이어집니다.`
     - 파이프라인 전체에서 `promote()` 함수는 전혀 호출되지 않으며, `status="success"`로 종료되더라도 서빙 모델은 그대로 유지됩니다.

### 4.2 승격 모듈 자체의 기계적 검증 게이트 (`src/ml/promotion.py`)

설령 누군가가 의도적으로 또는 스크립트 오류로 `promote()`를 호출하더라도, 다음과 같은 다중 안전 게이트에 의해 자동 승격이 원천 차단됩니다.

1. **모듈 원칙 선언 (`src/ml/promotion.py:10-12`)**:
   - `승격은 되돌리기 어려운 변경이므로 자동으로 일어나지 않습니다. 호출부가 명시적으로 부르고, 직전 서빙본을 백업한 뒤 교체합니다.`
2. **운영 쌍대검정 판정 파일 결속 강제 (`src/ml/promotion.py:239-260`)**:
   - `check_promotion_criteria` 함수는 승격 대상 버전에 대해 `read_paired_verdict(model_name, version, registry_dir)`를 호출합니다(250행).
   - 신규 재학습된 챌린저 버전에는 `paired_verdict.json` 파일이 존재하지 않으므로, 252행에 의해 `운영 쌍대검정 미판정. paired_verdict.json 이 없습니다` 사유가 등록되어 승격이 거부됩니다.
3. **쌍대검정 기각 시 force 우회 불가 (`src/ml/promotion.py:427-431`)**:
   - `_promote_unlogged` 함수에서 운영 쌍대검정이 기각된 모델은 `--force` 플래그를 주더라도 `PromotionRejected` 예외를 발생시키며 승격되지 않습니다.
4. **증거 해시 결속 검증 (`src/ml/promotion.py:126-163`, `433-437`)**:
   - `champion_checksum`, `challenger_checksum`, `sample_hash`, `code_commit`, `decided_at` 필드가 실제 모델 아티팩트 해시와 일치하는지 SHA-256 매니페스트로 검증합니다.
5. **서빙 슬롯 불변 세대 디렉터리 및 원자적 교체 (`src/ml/promotion.py:487-515`)**:
   - 승격이 승인될 경우에도 기존 서빙본을 `data/model_backups/`로 스냅샷 백업한 뒤, `generations/{generation_id}` 디렉터리를 만들고 `LIVE` 포인터 파일의 원자적 `os.replace`로만 서빙을 전환하여 무중단 및 즉시 롤백(`scripts/promote_model.py rollback`)을 보장합니다.
6. **전체 코드베이스 호출부 전수 확인**:
   - `promote(` 함수가 호출되는 곳은 `src/ml/promotion.py:326`(정의부) 외에 운영 수동 CLI인 `scripts/promote_model.py:169`가 유일합니다.

---

## 5. 크론 등록 위치, 실행 주기 및 시간대 함정

### 5.1 크론 등록 위치 및 설정

| 스케줄 태스크 | 크론 등록 파일 및 행 | 크론 주기 및 시각 | 의존 환경 변수 및 설정 |
| --- | --- | --- | --- |
| 선행 야간 데이터 수집 (`nightly_schedule_task`) | `src/tasks/worker.py:403-405` | 매일 02:00 (hour=2, minute=0) | `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=true` |
| 주간 정기 재학습 (`weekly_retrain_task`) | `src/tasks/worker.py:406-413` | 매주 월요일 03:00 (weekday="mon", hour=3, minute=0) | `ML_WEEKLY_RETRAIN_ENABLED=true`<br>`ML_WEEKLY_RETRAIN_CATEGORIES=Servc` |
| PSI 데이터 드리프트 감시 (`drift_monitor_task`) | `src/tasks/worker.py:414-420` | 매일 04:00 (hour=4, minute=0) | `ML_DRIFT_MONITOR_ENABLED=true` |
| 정기 백업 (`backup_schedule_task`) | `src/tasks/worker.py:489-496` | 매일 03:00 (hour=3, minute=0) | 격리된 백업 전용 워커에서 실행 |

- **환경별 활성화 여부**:
  - 개발 환경 (`docker-compose.yml:149-152`): `ML_WEEKLY_RETRAIN_ENABLED=true`, `ML_WEEKLY_RETRAIN_CATEGORIES=Servc`, `TZ=Asia/Seoul`
  - 운영 환경 (`docker-compose.prod.yml:141, 227`): `ML_WEEKLY_RETRAIN_ENABLED=false` (기본값 비활성 격리)

### 5.2 시간대(Timezone) 9시간 시차 함정

워커 프로세스와 데이터베이스의 시간대 처리 방식이 달라 같은 사건이 다른 시각으로 기록됩니다.

1. **워커 컨테이너 로컬 시각 (KST, Asia/Seoul, UTC+9)**:
   - `docker-compose.yml:152`에 `TZ=Asia/Seoul`이 지정되어 있습니다.
   - Arq 워커의 크론 판정 엔진은 컨테이너 로컬 시간대를 따르므로, `weekly_retrain_task`는 **한국 시각(KST) 월요일 새벽 03:00:00**에 정확히 발화합니다.
   - 컨테이너 표준 출력 로그(워커 로그)에 찍히는 시각도 KST 기준 `03:00:xx`입니다.
2. **데이터베이스 시각 컬럼 (UTC, 협정 세계시)**:
   - MySQL DB의 시각 컬럼(`pipeline_executions.started_at`, `pipeline_executions.created_at`, `retrain_logs.created_at`)은 Python의 `utcnow()` (`src/app/core/timeutil.py`) 함수를 통해 **UTC**로 기록됩니다.
   - `KST = UTC + 9시간`이므로, 월요일 03:00 KST는 **일요일 18:00 UTC**입니다.
3. **시간대 대조 요약표**:

| 작업명 | 컨테이너 로컬 발화 시각 (KST) | DB 저장 시각 (UTC) | 시차 |
| --- | :---: | :---: | :---: |
| 선행 야간 수집 (`nightly_schedule_task`) | 매일 02:00 KST | 전일 17:00 UTC | -9시간 |
| 주간 정기 재학습 (`weekly_retrain_task`) | 월요일 03:00 KST | **일요일 18:00 UTC** | **-9시간** |
| 드리프트 감시 (`drift_monitor_task`) | 매일 04:00 KST | 전일 19:00 UTC | -9시간 |

> 주의: 도래 시각(2026-09-21 03:00 KST) 이후 DB를 조회할 때 `WHERE created_at >= '2026-09-21 03:00:00'` 조건으로 질의하면 레코드가 조회되지 않습니다. DB 기준으로는 `2026-09-20 18:00:00` 전후를 확인해야 합니다.

---

## 6. 도래 후 코디네이터 점검 체크리스트

2026-09-21 03:00 KST가 도래한 후, 코디네이터가 터미널에서 순서대로 실행하여 주간 재학습 정상 수행 여부 및 무승격 상태를 검증하는 점검 체크리스트입니다.
모든 명령어는 실재하는 CLI 및 옵션으로 검증되었습니다.

### Step 1: 02:00 KST 선행 야간 수집 성공 여부 확인

주간 재학습이 최신 개찰 데이터를 반영하려면 선행 야간 수집이 성공해야 합니다.

```bash
# 실행 명령 (DB 읽기 전용 질의)
uv run python scripts/db_readonly_query.py --sql "SELECT id, execution_id, pipeline_name, status, started_at, created_at FROM pipeline_executions ORDER BY id DESC LIMIT 5"
```

- **판정 기준**:
  - `execution_id`가 `nightly_schedule-*` 형태인 레코드 확인
  - `status`가 `success`인지 확인
  - `started_at` 시각이 `2026-09-20 17:00:xx` (UTC, 즉 2026-09-21 02:00 KST) 전후인지 확인

### Step 2: 03:00 KST 주간 재학습 실행 이력 및 판정 결과 확인

재학습 파이프라인이 정상 트리거되어 새 챌린저가 발급되고 판정 권고가 남았는지 확인합니다.

```bash
# 실행 명령 (DB 읽기 전용 질의)
uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, champion_version, challenger_version, status, created_at FROM retrain_logs ORDER BY id DESC LIMIT 5"
```

- **판정 기준**:
  - 최신 행의 `trigger_source`가 `weekly_schedule`로 기록되었는지 확인
  - `champion_version`이 현재 서빙 버전(`v_20260915_133523_756`)과 일치하는지 확인
  - `challenger_version`에 새로운 버전 식별자(예: `v_20260921_*`)가 발급되었는지 확인
  - `status`에 판정 결과(`REJECT_CHALLENGER` 또는 `PROCEED_CHALLENGER`)가 정상 기록되었는지 확인
  - `created_at`이 `2026-09-20 18:00:xx` (UTC, 즉 2026-09-21 03:00 KST) 전후인지 확인

### Step 3: 주간 재학습 상세 비교 지표 JSON 확인

챌린저 모델의 지표 및 챔피언과의 비교 상세 내용을 확인합니다.

```bash
# 실행 명령 (JSON 포맷 출력)
uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, champion_version, challenger_version, status, metrics_summary FROM retrain_logs WHERE trigger_source = 'weekly_schedule' ORDER BY id DESC LIMIT 1" --format json
```

- **판정 기준**:
  - `metrics_summary` 내에 `challenger_metrics` (r2, rmse, mae 등)와 `champion_metrics`의 비교 데이터 정상 수록 확인

### Step 4: 기본 Feature Store Parquet 갱신 확인

최신 데이터셋이 Parquet 파일로 정상 갱신되었는지 메타데이터를 확인합니다.

```bash
# 파일 갱신 시각 점검
ls -lh data/feature_store/dataset_Servc.parquet

# 데이터셋 행 수 및 컬럼 수 점검 (Python 단기 검증)
uv run python -c "import pandas as pd; df = pd.read_parquet('data/feature_store/dataset_Servc.parquet'); print(f'데이터셋 행 수: {len(df):,}행, 컬럼 수: {len(df.columns)}개')"
```

- **판정 기준**:
  - 파일 수정 시각이 2026-09-21 03:00 KST 전후로 갱신되었는지 확인
  - 행 수가 기존 2026-09-15 시점(925,054행) 이상으로 증가했는지 확인

### Step 5: 자동 승격되지 않았음을 기계적으로 확인

현행 서빙 챔피언 모델이 교체되지 않고 그대로 서빙 중인지 점검합니다.

```bash
# 공식 승격 관리 CLI 상태 점검
uv run python scripts/promote_model.py status --model servc_institution_v1

# 서빙 LIVE 포인터 파일 직접 확인
cat data/model_files/servc_institution_v1/LIVE

# Python API 직접 호출 확인
uv run python -c "from src.ml.promotion import load_serving_metrics; v, m = load_serving_metrics('servc_institution_v1'); print('현재 서빙 버전:', v, m)"
```

- **판정 기준**:
  - `scripts/promote_model.py status` 출력에서 `서빙` 버전이 `v_20260915_133523_756`으로 유지되고 있는지 확인
  - `LIVE` 파일 내용이 `v_20260915_133523_756_*`으로 유지되고 있는지 확인
  - `load_serving_metrics` 반환 버전이 `v_20260915_133523_756`인지 확인

### Step 6: 챌린저 모델 레지스트리 저장 확인

신규 학습된 챌린저 모델 아티팩트가 레지스트리에 정상 저장되었는지 점검합니다.

```bash
# 레지스트리 내 신규 버전 디렉터리 확인
ls -la ml_registry/servc_institution_v1/
```

- **판정 기준**:
  - Step 2의 `challenger_version`과 동일한 디렉터리가 생성되어 있는지 확인
  - 해당 디렉터리 내에 `model.bin`과 `metadata.json` 파일이 존재하는지 확인

---

## 7. 비협상 원칙 및 안전 수칙 준수 보고

1. **재학습 미실행 원칙**: 2026-09-20 현재 재학습 태스크를 실행하거나 Redis 큐에 등록(enqueue)하지 않았습니다.
2. **컨테이너 및 DB 불변**: Docker 컨테이너를 기동, 정지, 재시작하지 않았으며, DB 원본 데이터 및 스키마 변경을 전혀 수행하지 않았습니다.
3. **코드 및 런북 무수정**: 허용된 쓰기 범위(`docs/analysis/weekly_retrain_prep_20260920.md` 및 작업 캡슐 완료 보고서) 외에 어떠한 소스 코드나 기존 런북 문서도 수정하지 않았습니다.
4. **명령 실재성 검증**: 체크리스트에 수록된 모든 명령어는 `--help` 확인 및 실제 읽기 전용 실행을 통해 유효성을 사전 검증하였습니다.
