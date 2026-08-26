# integrate/arq-worker-cutover 통합 브랜치 감사 및 최종 판정 보고서

> **작성일**: 2026-08-26
> **작성자**: Orca Task Runner (`task_49975ee8d7ea`)
> **대상 브랜치**: `integrate/arq-worker-cutover` (마지막 커밋: `602072f`, 2026-08-05)
> **기준 베이스**: `45faa8f` (Merge Base) 및 `main` 최신 트랙
> **감사 범위**: `main` 대비 트리 고유 파일 4건 및 브랜치 변경 파일 35건 전수 정밀 대조
> **최종 판정**: 전량 **폐기 권고 (안전 삭제)** — 회수 권고 0건, 폐기 권고 35건, 판단 보류 0건

---

## 1. 개요 및 배경

`integrate/arq-worker-cutover`는 2026-08-05 Arq 비동기 워커 스택 분리, Compose 배선, 수동 재학습 API 연동, MySQL 8 DDL 호환성 확보 및 초기 홈 UI/SSR 개선을 목적으로 분기되었던 통합 브랜치입니다.

본 저장소의 다른 미병합 브랜치(`feat/codex-task-routing`, `feat/phase8-predict-tail`, `feat/phase8-predict-gc` 등)는 2026-08-14 판정 문서가 완료되었으나, 본 브랜치는 2026-08-14 당시 4건의 파일에 대한 부분 점검(`docs/ops/arq_branch_file_triage_20260814.md`)만 수행된 채 브랜치 전체(12개 커밋 및 35개 변경 파일)에 대한 종합 판정 문서가 누락되어 있었습니다.

2026-08-05 이후 `main` 브랜치에는 수백 건의 커밋이 진행되었으며, Arq 워커 정식 안착, 비즈니스 태스크 E2E 실측 완료, SSR/Jinja2/jQuery 프론트엔드 확정(2026-08-25), MLOps 재학습 레지스트리 고도화가 이미 완료되었습니다. 이에 본 보고서에서는 브랜치 고유 파일과 merge base 이후의 변경 파일 35건을 전수 대조하여 회수 대상과 폐기 대상을 확정합니다.

---

## 2. 조사 방법론 및 고유 파일 추출

`git diff main...integrate/arq-worker-cutover`는 merge base 기준 차이이므로 현재 `main` 최신 상태를 정확히 반영하지 못합니다. 따라서 두 가지 교차 검증 방식을 결합하여 전수 감사를 수행했습니다.

1. **트리 고유 파일 추출 (`comm` + `git ls-tree`)**:
   `comm -23 <(git ls-tree -r integrate/arq-worker-cutover --name-only | sort) <(git ls-tree -r main --name-only | sort)` 명령을 통해 `main` 트리에 물리적으로 존재하지 않는 파일 4건을 특정.
2. **머지 베이스 이후 변경 파일 전수 대조 (35건)**:
   `git diff --name-only 45faa8f integrate/arq-worker-cutover`를 통해 12개 커밋에 포함된 35개 수정 파일의 각 패치 청크를 추출하고 `main` 최신 코드베이스와의 라인 단위/의미 단위 일치 여부를 검증.

---

## 3. 트리 고유 파일 4건 정밀 판정

`main` 트리에 없는 고유 파일 4건의 상태 및 판정 결과는 다음과 같습니다.

| 번호 | 고유 파일 경로 | 브랜치 내 역할 및 상태 | main 현황 및 차이점 | 최종 판정 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `data/model_files/quantum_leap_v25_pro/preprocess.py` | 노트북 기반 레거시 전처리 스크립트 | `src/ml/features.py` 단일화 원칙에 위배되며 train/serve skew 유발 | **폐기 권고 (병합 금지)** |
| 2 | `data/model_files/quantum_leap_v25_pro/champion_summary.json` | 76,527건 노트북 표본 기준 과거 프로파일 | 784,266건 재학습 정식 승격본 `metadata.json` 운용 중 | **폐기 권고 (병합 금지)** |
| 3 | `.harness/pipeline.yaml` | Linux Amd64 단일 환경 `pip install` 기반 구형 CI 명세 | GitHub Actions(`.github/workflows/ci.yml`) 표준 CI로 대체 완료 | **폐기 권고** |
| 4 | `docs/ops/harness_ci_guide.md` | 초기 Harness 연동 가이드 문서 | `docs/ops/cross_platform_guide.md` 및 공식 가이드에 내용 흡수 완료 | **폐기 권고** |

---

## 4. 브랜치 변경 파일 35건 전수 대조 및 파일별 판정

머지 베이스(`45faa8f`) 대비 브랜치에서 수정된 35개 파일 전체의 변경 내역 및 `main` 반영 상태 대조 결과입니다.

| 번호 | 대상 파일 경로 | 브랜치 변경 핵심 내용 | main 브랜치 반영 현황 | 판정 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `.env.example` | `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED`, `ML_WEEKLY_RETRAIN_ENABLED` 추가 | `main`에 완전 반영 완료 | **폐기 권고** |
| 2 | `Makefile` | `make up` 안내 문구에 Arq 워커 명시 | `main`의 최신 Makefile에 상위 호환 반영 완료 | **폐기 권고** |
| 3 | `README.md` | Phase 7 상태 문구 및 컷오버 조건 갱신 | `main`에서 후속 Phase 진행 상태로 갱신 완료 | **폐기 권고** |
| 4 | `docker-compose.yml` | `worker` (Arq) 서비스 정의 및 환경변수 주입 | `main`에 Compose 기본 워커 서비스로 고도화 반영 완료 | **폐기 권고** |
| 5 | `docs/README.md` | 문서 인덱스 정정일/버전 표기 갱신 | `main` 최신 문서 체계로 누적 반영 완료 | **폐기 권고** |
| 6 | `docs/changelogs/work_log.md` | 2026-08-05 당시 커밋 12개에 대한 작업 로그 | `main`의 `work_log.md`가 2026-08-26 현재까지 최신 유지 | **폐기 권고** |
| 7 | `docs/design/REFACTORING_DESIGN.md` | 로컬 Ollama 12초 SLO 및 Arq 워커 설계 반영 | `main` 설계 문서에 상위 호환 반영 완료 | **폐기 권고** |
| 8 | `docs/handoff/2026-08-04_phase7_handoff.md` | Phase 7 인수인계 문서 내 12초 SLO 타겟 갱신 | `main` 인수인계 문서에 반영 완료 | **폐기 권고** |
| 9 | `docs/ops/cross_platform_guide.md` | Arq 워커 컨테이너 기동 및 환경변수 가이드 | `main` 크로스플랫폼 가이드에 완전 반영 완료 | **폐기 권고** |
| 10 | `docs/ops/environment_variables.md` | 워커 스케줄 플래그 2종 환경변수 설명 추가 | `main` 환경변수 가이드에 완전 반영 완료 | **폐기 권고** |
| 11 | `docs/ops/latency_benchmark.md` | 컷오버 보고서 참조 링크 및 상태 설명 갱신 | `main` 벤치마크 가이드에 완전 반영 완료 | **폐기 권고** |
| 12 | `docs/ops/phase7_cutover_report_20260804.md` | 로컬 Ollama SSE 첫 토큰 12초 목표 결정 내역 | `main` 컷오버 보고서에 완전 반영 완료 | **폐기 권고** |
| 13 | `migrations/versions/0001_django_baseline.py` | `automation_requests.request_id`를 `String(36)`으로 수정 (MySQL 8 호환) | `main`과 100% 동일하게 반영 완료 (diff 0) | **폐기 권고** |
| 14 | `scripts/benchmark_latency.py` | `FIRST_TOKEN_TARGET_MS = 12_000.0` 상수 정의 | `main`에 `HostLoadMonitor` 등과 함께 고도화 반영 완료 | **폐기 권고** |
| 15 | `src/app/api/ui.py` | `_result_analysis_prompt`, `result_id` 쿼리 파라미터, `initial_message` 주입 | `main`에 완전 반영 완료 | **폐기 권고** |
| 16 | `src/app/api/v1/automation.py` | `/run/retrain` 수동 재학습 확인 엔드포인트 추가 | `main`에 완전 반영 완료 | **폐기 권고** |
| 17 | `src/app/models/chatbot.py` | MariaDB/MySQL Dialect별 `request_id` 타입 호환 처리 | `main` 모델에 완전 반영 완료 | **폐기 권고** |
| 18 | `src/app/services/action_catalog.py` | `model_retrain` (`pipeline`, `retrain_only`) 카탈로그 등록 | `main`과 100% 동일하게 반영 완료 (diff 0) | **폐기 권고** |
| 19 | `src/app/services/automation_orchestrator.py` | `RUN_MODE_TASKS`에 `"retrain_only": "manual_retrain_task"` 매핑 | `main` 오케스트레이터 아키텍처에 완전 수용 완료 | **폐기 권고** |
| 20 | `src/app/services/home_context.py` | `DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES`에 `"Frgcpt"`(외자) 추가 | `main`에 완전 반영 완료 | **폐기 권고** |
| 21 | `src/app/templates/bids/result_detail.html` | AI 분석 시작하기 버튼 링크에 `?result_id={{ result.id }}` 추가 | `main`과 100% 동일하게 반영 완료 (diff 0) | **폐기 권고** |
| 22 | `src/app/templates/chatbot/chat.html` | `initial_message` 존재 시 자동 전송 자바스크립트 바인딩 | `main` 템플릿에 완전 반영 완료 | **폐기 권고** |
| 23 | `src/app/templates/index.html` | 홈 화면 3열 카드 그리드, 외자 브리핑 패널, 슬라이드 스크롤 | `main` SSR/Jinja2 홈 템플릿에 완전 반영 완료 | **폐기 권고** |
| 24 | `src/tasks/automation_tasks.py` | `_step_retrain`, `manual_retrain_task`, `STEP_RUNNERS["retrain"]` 구현 | `main` Arq 태스크 모듈에 완전 반영 완료 | **폐기 권고** |
| 25 | `src/tasks/run_mode_matrix.py` | `RUN_MODE_STEP_ORDER`에 `"retrain_only": ("retrain",)` 추가 | `main` 매트릭스에 완전 반영 완료 | **폐기 권고** |
| 26 | `src/tasks/worker.py` | `WorkerSettings.functions`에 `manual_retrain_task` 등록 | `main` 워커 설정에 완전 반영 완료 | **폐기 권고** |
| 27 | `tests/test_alembic_setup.py` | `test_baseline_uses_mysql_compatible_request_id_type` 테스트 추가 | `main`과 100% 동일하게 반영 완료 (diff 0) | **폐기 권고** |
| 28 | `tests/test_automation_api.py` | `test_manual_retrain_requires_confirmation` 테스트 추가 | `main`과 100% 동일하게 반영 완료 (diff 0) | **폐기 권고** |
| 29 | `tests/test_automation_bundle_parity.py` | `test_manual_retrain_runs_only_retrain_step` 테스트 추가 | `main` 테스트 스위트에 완전 반영 완료 | **폐기 권고** |
| 30 | `tests/test_benchmark_latency.py` | `test_first_token_target_matches_local_ollama_operating_slo` 테스트 추가 | `main`의 고도화된 벤치마크 테스트에 수용 완료 | **폐기 권고** |
| 31 | `tests/test_chatbot_core.py` | `model_retrain` capability 및 `run_mode` 검증 테스트 추가 | `main` 테스트 스위트에 완전 반영 완료 | **폐기 권고** |
| 32 | `tests/test_home_list_parity.py` | `test_index_page_default_sections_include_foreign_procurement` 테스트 추가 | `main` 테스트 스위트에 완전 반영 완료 | **폐기 권고** |
| 33 | `tests/test_model_schema_parity.py` | `test_request_id_uses_varchar_on_mysql`, `MariaDBDialect` 테스트 추가 | `main` 스키마 검증 스위트에 완전 반영 완료 | **폐기 권고** |
| 34 | `tests/test_ui_ssr.py` | `test_chat_page_transfers_result_context` 테스트 추가 | `main` SSR UI 테스트 스위트에 완전 반영 완료 | **폐기 권고** |
| 35 | `tests/test_worker_compose.py` | `test_default_compose_includes_arq_worker_with_disabled_schedules` 추가 | `main`에서 다중 검증 함수(58줄)로 고도화 완료 | **폐기 권고** |

---

## 5. 핵심 영역별 분석 상세

### 5.1 Arq 비동기 워커 및 자동화 파이프라인
- **브랜치 작업**: Arq 워커 Compose 배선, 수동 재학습 엔드포인트(`/api/v1/automation/run/retrain`), `retrain_only` 파이프라인 모드, `manual_retrain_task` 등록.
- **main 현황**: Arq 워커가 Compose 기본 스택(`worker` 서비스)으로 상시 기동 중이며, 2026-08-26 business-task E2E 실측까지 완료되었습니다. 모든 태스크/API/오케스트레이터 연동이 `main`에 완전 정착되어 있습니다.

### 5.2 MySQL 8 / MariaDB 스키마 호환성
- **브랜치 작업**: MySQL 8에는 네이티브 UUID DDL 타입이 지원되지 않아 `automation_requests.request_id` 컬럼을 `VARCHAR(36)`으로 호환 정의하고, Alembic baseline 마이그레이션 및 DDL 컴파일 테스트 추가.
- **main 현황**: `migrations/versions/0001_django_baseline.py`, `tests/test_alembic_setup.py`, `tests/test_model_schema_parity.py` 모두 `main`에 100% 동일하게 반영되어 diff가 0입니다.

### 5.3 UI 및 낙찰 상세-챗봇 연동
- **브랜치 작업**: 낙찰 결과 상세 화면(`result_detail.html`)에서 챗봇 링크 클릭 시 `result_id`를 쿼리 파라미터로 전달하고, 챗봇 페이지에서 해당 공고의 메타데이터(공고명, 수요기관, 낙찰금액, 낙찰률 등)를 기반으로 초기 분석 프롬프트를 자동 생성/전송하는 기능. 홈 화면 3열 카드 배치 및 외자 공고 패널 추가.
- **main 현황**: `src/app/api/ui.py`, `chat.html`, `index.html`, `test_ui_ssr.py` 등에 온전히 반영되어 작동 중입니다. 프론트엔드 아키텍처 방침(2026-08-25 SSR+Jinja2+jQuery 확정)과 완벽히 부합합니다.

### 5.4 레거시 자산 및 단일화 규칙 위반 파일
- **브랜치 잔존 파일**: `preprocess.py`, `champion_summary.json`
- **판정 사유**: 본 저장소의 핵심 원칙인 G1(데이터 무손실) 및 G3(단일 특징 공급원 `src/ml/features.py`)에 위배되며, 7.6만 건 레거시 노트북 프로파일은 현재 78.4만 건 승격 모델 운용 환경에 불일치를 야기하므로 **병합 금지(폐기)** 대상입니다.

---

## 6. 결론 및 후속 조치 권고

1. **회수 대상 없음**: `integrate/arq-worker-cutover` 브랜치의 모든 가치 있는 기능과 수정 사항은 이미 `main` 브랜치에 완전 반영되었거나 상위 호환 형태로 고도화되었습니다.
2. **브랜치 안전 삭제 권고**:
   - 로컬/원격의 `integrate/arq-worker-cutover` 브랜치를 안전하게 삭제(`git branch -D integrate/arq-worker-cutover`)할 것을 권고합니다.
3. **미병합 브랜치 판정 완결**:
   - 본 보고서를 끝으로 저장소 내 모든 미병합 통합/기능 브랜치에 대한 정밀 감사 및 공식 판정 문서화가 100% 완료되었습니다.
