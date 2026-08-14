# integrate/arq-worker-cutover 잔존 파일 회수 판정 보고서

> **작성일**: 2026-08-14
> **작업 브랜치**: `kwanbum217/p7-arq-file-triage`
> **대상 브랜치**: `integrate/arq-worker-cutover`
> **범위**: 브랜치 고유 파일 3건 및 차이 테스트 파일 1건의 회수 가치 개별 정밀 판정
> **판정 요약**: 4건 전량 **폐기 권고** (회수 권고 0건, 폐기 권고 4건, 판단 보류 0건)

---

## 1. 개요 및 배경

폐기 예정 브랜치인 `integrate/arq-worker-cutover`(12개 커밋, 마지막 2026-08-05)는 Arq 워커 분리 및 Docker Compose 배선 작업을 진행했던 브랜치로, 대다수의 핵심 기능이 이미 `main` 브랜치에 반영되었습니다.

`docs/ops/phase7_gate_and_stale_branch_audit_20260814.md`의 코디네이터 검증 결과에 따라, `main` 최신 트리와 차이가 있는 4건의 파일에 대해 개별 내용 대조 및 코드베이스 영향도 조사를 수행하여 회수 가치 여부를 판정합니다.

> [!NOTE]
> `data/model_files/quantum_leap_v25_pro/preprocess.py`는 `src/ml/features.py` 단일화 규칙을 위반하고 서빙 시 train/serve skew를 유발하므로 코디네이터 검증에서 이미 **병합 금지**로 확정되어 본 판정 범위에서 제외되었습니다.

---

## 2. 종합 판정 요약

| 번호 | 대상 파일 | 브랜치 상태 | main 브랜치 현황 | 최종 판정 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `data/model_files/quantum_leap_v25_pro/champion_summary.json` | 76,527건 노트북 프로파일 요약 | 784,266건 재학습 승격본 `metadata.json` 운용 중 | **폐기 권고** |
| 2 | `.harness/pipeline.yaml` | Linux Amd64 단일 환경, `pip install` 기반 Harness CI 명세 | GitHub Actions(`.github/workflows/ci.yml`) 표준 CI 운용 중 | **폐기 권고** |
| 3 | `docs/ops/harness_ci_guide.md` | 초기 Harness 연동 및 `hc.exe` 제거 안내 (2026-07-31) | `docs/ops/cross_platform_guide.md` 등에 내용 온전 반영 | **폐기 권고** |
| 4 | `tests/test_worker_compose.py` | 15줄 초기 단순 검증 1건 | 58줄 4개 함수 정밀 검증으로 고도화 완료 | **폐기 권고** |

---

## 3. 대상별 정밀 분석 및 판정 근거

### 3.1. `data/model_files/quantum_leap_v25_pro/champion_summary.json`

#### 1) 브랜치 내용 vs main `metadata.json` 대조

- **브랜치 내용**:
  - `aggregate`: `avg_r2` (0.8705), `avg_mae` (0.7073), `training_rows` (76,527)
  - `acceptance`: `pass_all` (true), `reason` ("Notebook heuristic was wrapped into BIDBOX bundle format and profiled against the supplied 2025 goods dataset.")
  - `sectors`: IT/SW, 의료/장비, 건설/용역, 일반/물품 4개 섹터별 통계(`r2`, `mae`, `win_rate`, `base_delta`, `dataset_rows`, `median_rate`, `q10_rate`, `q75_rate`)
  - `price_floors`: `small`, `mid`, `large`
- **main 현황 (`metadata.json`)**:
  - 2026-08-06 04:46 승격된 최신 재학습 모델 메타데이터(`version`: "v_20260806_043408_749")
  - `training_rows`: 784,266 (78.4만 건)
  - `source_metrics`: `rmse` (4.7659), `mape` (3.4815), `r2` (0.3583)
  - `interval`: Conformal Prediction 신뢰구간 보정 파라미터(`conformal_scale`: 1.138442 등) 완비

#### 2) 코드베이스 사용처 및 미참조 필드 확인

- `src/ml/model_registry.py`의 `_load_champion_metrics(model_dir)`:
  - `champion_summary.json`이 없으면 `validation_label: "요약 없음"`, `validation_type: "missing_summary"`를 정상 반환하며 서빙에 아무런 영향을 주지 않습니다.
  - 해당 함수는 `aggregate` 및 `acceptance`의 기본 지표만 읽으며, `sectors` 하위의 상세 지표(`win_rate`, `base_delta`, `median_rate`, `q10_rate`, `q75_rate`)나 `price_floors`는 코드베이스 전체에서 전혀 참조되지 않습니다.
- **데이터 정합성 결함 위험**:
  - 브랜치에 남은 `champion_summary.json`은 7.6만 건 시절의 과거 노트북 프로파일 데이터입니다.
  - 이를 78.4만 건으로 재학습 승격된 현행 `quantum_leap_v25_pro` 디렉토리에 배치할 경우, 78.4만 건 모델에 대해 7.6만 건 평가 요약이 바인딩되어 통계 불일치를 초래합니다.

#### 3) 결론: 폐기 권고
과거 레거시 평가 산출물이며 현행 승격 모델 메타데이터와 불일치하므로 회수하지 않고 폐기합니다.

---

### 3.2. `.harness/pipeline.yaml`

#### 1) 설정 내용 분석

- Harness Cloud CI/CD 파이프라인 명세(`refac_bid_box_ci`)입니다.
- 실행 환경이 `os: Linux`, `arch: Amd64` 단일 플랫폼으로 제한되어 있습니다.
- 의존성 설치 시 `uv sync`를 사용하지 않고 `pip install uv ruff bandit ...` 형태로 패키지를 임의 나열하여 `pyproject.toml` 단일 관리 원칙에 어긋납니다.

#### 2) main CI 구성과의 대조

- `main` 브랜치는 `.github/workflows/ci.yml`을 통해 공식 CI를 운영하고 있습니다.
- main의 GitHub Actions 파이프라인은 다음 항목을 완전하게 수행합니다:
  - `uv sync` 기반 완전 격리 의존성 설치
  - Ruff 린트 및 Bandit 보안 정적 분석
  - 다중 에이전트 규칙 정합성 검증 (`scripts/validate_agent_rules.py`)
  - Node 22 기반 프론트엔드 의존성, 테스트, 빌드 검증
  - macOS(`macos-latest`) 및 Windows(`windows-latest`) 매트릭스 기반 크로스 플랫폼 단위/통합 테스트 (G2 크로스 플랫폼 검증 완비)

#### 3) 결론: 폐기 권고
`main`의 GitHub Actions 파이프라인이 저장소의 공식 표준이며 기능적·플랫폼적으로 완전한 상위 호환을 제공하므로 폐기합니다.

---

### 3.3. `docs/ops/harness_ci_guide.md`

#### 1) 문서 내용 및 main 문서군과의 대조

- 2026-07-31 작성된 초기 가이드로, 레거시 `hc.exe`(46MB Windows 바이너리) 제거와 `.harness/pipeline.yaml` 연동을 기술하고 있습니다.
- 이 문서의 핵심 가치였던 "플랫폼 종속 바이너리 제거(G2)" 및 "크로스 플랫폼 원칙"은 이미 `main`의 아래 정본 문서들에 온전히 흡수되어 있습니다:
  - `docs/ops/cross_platform_guide.md`
  - `docs/design/REFACTORING_DESIGN.md` (3.8절)
  - `SKILLS.md` 및 `.agents/skills/inference-rag-opt/SKILL.md`
- 또한 본 문서가 링크하는 `.harness/pipeline.yaml` 자체가 폐기 대상이므로 문서 유지의 실익이 없습니다.

#### 2) 결론: 폐기 권고
핵심 기술 내용이 공식 문서들에 이미 완전 이관되었고 연동 대상 설정 파일이 폐기되므로 본 문서도 함께 폐기합니다.

---

### 3.4. `tests/test_worker_compose.py`

#### 1) 브랜치 버전 vs main 버전 상세 비교

| 검증 항목 | 브랜치 버전 (15줄) | main 버전 (58줄) |
| :--- | :--- | :--- |
| `worker:` 서비스 정의 존재 | `assert "  worker:\n" in compose` | `_worker_service()` 추출 함수로 명확히 격리 검증 |
| Arq 실행 커맨드 계약 | `assert 'command: ["arq", ...]' in compose` | `assert 'command: ["arq", ...]' in worker` |
| 정기 스케줄 비활성화 | `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false`<br>`ML_WEEKLY_RETRAIN_ENABLED=false` | 위 2개 항목 + `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true` 검증 포함 |
| 공용 서비스 및 에셋 마운트 | 미검증 | `DATABASE_URL`, `DB_PASSWORD`, `SECRET_KEY`, `REDIS_URL`, `CHROMA_DB_PATH`, 3개 볼륨 마운트 검증 |
| 의존 서비스 헬스체크 대기 | 미검증 | 7개 서비스 healthy 조건, `redis-cli ping`, health 엔드포인트 응답 검증 |
| CORS 환경변수 전달 계약 | 미검증 | `CORS_ALLOWED_ORIGINS`, `CORS_DEV_ALLOW_ALL` 전달 개수 고정 검증 |

#### 2) 연관 테스트 커버리지

- `main`에는 `tests/test_worker_compose.py` 외에도 `tests/test_app_compose_workers.py`가 추가되어 Uvicorn 워커 수, exec 형태 배열 커맨드, 컨테이너 진입점 계약까지 철저하게 상호 보완 검증하고 있습니다.
- 브랜치 버전의 단 1개 테스트 함수(`test_default_compose_includes_arq_worker_with_disabled_schedules`)는 `main` 버전의 1번, 2번 함수에 의해 100% 포섭(super-seeded)되었습니다.

#### 3) 결론: 폐기 권고
`main`의 테스트 코드가 브랜치 버전을 완전히 포함하는 고도화된 상위 호환이므로 브랜치 버전을 회수할 이유가 없으며 폐기합니다.

---

## 4. 최종 결론 및 후속 조치

1. **회수 자산 없음**: `integrate/arq-worker-cutover` 브랜치에 남아 있는 고유 파일 4건 중 회수할 가치가 있는 유효 자산은 0건입니다.
2. **브랜치 폐기 안전성 확인**: 본 브랜치를 삭제하더라도 `main`의 데이터 무손실(G1), 크로스 플랫폼(G2), 스택 최적화(G3)에 어떠한 유실도 발생하지 않습니다.
3. **후속 권고**: 코디네이터는 본 판정 보고서를 바탕으로 `integrate/arq-worker-cutover` 브랜치를 안전하게 삭제할 수 있습니다.
