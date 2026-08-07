# refac_bid_box 작업 일지 (Work Log)

> **작성자**: 관범 & AI 에이전트
> **프로젝트**: `refac_bid_box` 리팩토링
> 본 파일은 작업 수행 내역을 시간순으로 하단에 지속 누적 기록하는 단일 진실 기록서입니다.

---

### 2026-07-31 | Antigravity 정정 | 문서·데이터·핵심 로직 이식 및 SSR/HTMX 결정

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - handoff/work_log/README/docs/README: "Phase 0~7 완수" 착오 정정, 실제 진행 상태 반영
  - `scripts/import_data_assets.py`: bid_box에서 ML 4종 + chroma_db 이전 및 SHA256 manifest
  - `data/model_files/`, `chroma_db/`, `data/backups/data_assets_checksums.json` 생성
  - `src/ml/model_registry.py`: 원본 predictor.py 789줄 이식 (Django 의존 제거)
  - `src/ml/features.py`: 52차원 특징 맵 SSoT로 확장
  - `src/rag/engine.py`, `vector_store.py`, `structured_data.py`: RAG 엔진 이식, 스텁 제거
  - `src/app/services/planner.py`: planner 규칙 기반 핵심 이식
  - `docs/design/FRONTEND_DECISION.md`: SSR+HTMX 확정, React SPA 신규 개발 중단
  - `src/app/templates/`: Jinja2 SSR UI (/ui/, /ui/prediction, /ui/chatbot)
  - `scripts/verify_migration.py`: 실제 테이블명·체크섬 검증으로 강화
- **관련 파일**: 위 전체 + `tests/test_data_preservation.py`
- **검증 결과**: `verify_migration.py` PASS, `pytest` (SKIP_MODEL_LOAD) 통과

---


- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: build multi-agent skill system and validation script`
- **주요 변경사항**:
  - Phase 0~7 대응 8개 스킬 구축 (`.agents/skills/`)
  - Claude Code (`.claude/skills/`), opencode (`.opencode/skills/`), Cursor (`.cursor/rules/*.mdc`), Antigravity (`.antigravity/rules.md`) 5개 CLI 동기화
  - `scripts/validate_agent_rules.py` 검증 스크립트 및 pre-commit 훅 연동
- **관련 파일**: `.agents/skills/*`, `.claude/skills/*`, `.opencode/skills/*`, `.cursor/rules/*`, `.antigravity/rules.md`, `scripts/validate_agent_rules.py`
- **검증 결과**: `python3 scripts/validate_agent_rules.py` 6/6 PASS 통과

---

### 2026-07-31 | Git 워크플로우 | git-workflow 스킬 구축 및 문서 정합성 검토 수칙 강화

- **작업자**: 관범 & AI 에이전트
- **커밋**: `docs: add document consistency check to git-workflow skill`
- **주요 변경사항**:
  - 커밋/푸시 전 연관 문서(설계서, README, 인덱스) 내용 및 형식 업데이트 최우선 수칙 지정
  - 문서 간 및 문서-코드 간 실제 정합성 검토(Consistency Verification) 수칙 추가
  - 5개 CLI 스킬 미러 및 Cursor 룰 동기화
- **관련 파일**: `.agents/skills/git-workflow/SKILL.md`, `.claude/skills/git-workflow/SKILL.md`, `.opencode/skills/git-workflow/SKILL.md`, `.cursor/rules/09-git-workflow.mdc`
- **검증 결과**: pre-commit 검증 6/6 PASS 통과

---

### 2026-07-31 | Phase 0 기반 정비 | 코드 품질, 린터, 보안 스캔 및 react-doctor 검증 도구 반영

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: setup code quality, linting, security, and react-doctor tooling based on Minchodan`
- **주요 변경사항**:
  - Minchodan 프로젝트 검증 스택(Ruff, Bandit, mypy, jscpd, react-doctor) 분석
  - `pyproject.toml`: Ruff 11개 린트 규칙 팩, Bandit 보안 스캔, mypy 타입 설정
  - `.jscpd.json`: 5% 중복 코드 감지기 설정
  - `doctor.config.json`: React 부작용/effect cleanup 품질 규칙 설정
  - `.pre-commit-config.yaml` & `Makefile` 품질 검증 타깃 연동
- **관련 파일**: `pyproject.toml`, `.jscpd.json`, `doctor.config.json`, `.pre-commit-config.yaml`, `Makefile`
- **검증 결과**: 전체 규칙 및 린트 검증 PASS 통과

---

### 2026-07-31 | 아키텍처 결정 | 7가지 기술 트레이드오프 확정 및 설계서/규칙 동기화

- **작업자**: 관범 & AI 에이전트
- **커밋**: `docs: sign-off 7 architectural decisions in design and agent rules`
- **주요 변경사항**:
  - 1. 백엔드: FastAPI (ASGI)
  - 2. DB: Docker MySQL 8 단일 통일
  - 3. 태스크 큐: Arq (asyncio + Redis 초경량)
  - 4. 벡터DB: ChromaDB `bidding_kb` 활성 컬렉션 유지
  - 5. 가중치 저장: 외부 스토리지 / 독립 볼륨 (Git 저장소 경량화)
  - 6. 재학습 주기: PSI 드리프트 감지 동적 주기 (PSI > 0.2)
  - 7. Champion 전환: 자동 평가 검증 후 1-Click 수동/카나리 승인 게이트
- **관련 파일**: `docs/design/REFACTORING_DESIGN.md`, `AGENTS.md`, `.antigravity/rules.md`
- **검증 결과**: pre-commit 정합성 검증 6/6 PASS 통과

---

### 2026-07-31 | Phase 0~3 이행 | FastAPI 백엔드, 컨테이너, 데이터 보존 검증 및 단일 특징 함수 수립

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: implement fastapi backend, containerization, data preservation script, and features.py`
- **주요 변경사항**:
  - `Dockerfile` & `docker-compose.yml` (MySQL 8 + Redis 7 + FastAPI app 서비스 오케스트레이션)
  - `.github/workflows/ci.yml` CI 검증 파이프라인 수립
  - `scripts/verify_migration.py`: G1 무손실 마이그레이션 검증 스크립트 작성 및 통과
  - `src/app/main.py` & `src/app/api/v1/health.py`: FastAPI 비동기 백엔드 진입점 수립
  - `src/ml/features.py`: Single Source of Truth 단일 특징 함수 (`build_feature_frame`, `build_feature_dict`) 구현
  - `tests/test_health.py`: 백엔드 시동 및 헬스체크 단위 테스트 구현 및 통과
- **관련 파일**: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `scripts/verify_migration.py`, `src/app/main.py`, `src/ml/features.py`, `tests/test_health.py`
- **검증 결과**: `pytest` 2/2 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | Phase 6 프론트엔드 | Vite + React 19 + TypeScript 프론트엔드 독립 스택 구축

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: setup React 19 + TypeScript + Vite frontend with doctor.config.json`
- **주요 변경사항**:
  - `frontend/`: 독립 프론트엔드 프로젝트 디렉토리 생성
  - React 19 + TypeScript + Vite 6 기반 개발/빌드 스택 구축
  - `frontend/doctor.config.json`: react-doctor 품질 규칙 연동
  - `frontend/src/App.tsx`: 공공조달 대시보드, AI 낙찰가 예측, RAG 챗봇 탭 UI 및 FastAPI 연동 구현
  - `docker-compose.yml` & `Makefile`: frontend 서비스 및 `make dev-fe` 지원
- **관련 파일**: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/doctor.config.json`, `frontend/src/App.tsx`, `docker-compose.yml`, `Makefile`
- **검증 결과**: `pytest` 2/2 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | Phase 2 & 3 세부 이행 | 9개 DB ORM 모델 1:1 이식, Pydantic v2 스키마 및 API 라우터 구축

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: implement 9 ORM models, Pydantic v2 schemas, and API routers for bids, predictions, chatbot`
- **주요 변경사항**:
  - `src/app/models/`: 9개 핵심 DB 모델 (`BidAnnouncement`, `BidResult`, `InstitutionStat`, `PredictionResult`, `RetrainLog`, `ChatbotLog`, `KBDocument`, `RAGHistory`, `UserAccount`) 100% 이식
  - `src/app/schemas/`: Pydantic v2 DTO 스키마 구현 (`bids.py`, `predictions.py`, `chatbot.py`)
  - `src/app/api/v1/`: 입찰 공고/결과(`bids.py`), AI 낙찰가 예측(`predictions.py`), 하이브리드 RAG 챗봇(`chatbot.py`) API 라우터 구현 및 `main.py` 연결
  - `tests/test_api_v1.py`: 예측 및 챗봇 API 테스트 작성 및 100% 통과
- **관련 파일**: `src/app/models/*`, `src/app/schemas/*`, `src/app/api/v1/*`, `tests/test_api_v1.py`, `src/ml/features.py`
- **검증 결과**: `pytest` 4/4 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | Phase 4 & 5 세부 이행 | ML 추론 싱글톤, ChromaDB RAG, 재학습 MLOps 파이프라인 수립

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: implement ML predictor singleton, ChromaDB vector store, retraining pipeline, and PSI monitoring`
- **주요 변경사항**:
  - `src/ml/predictor.py`: 인메모리 모델 프리로딩 싱글톤 구현
  - `src/rag/vector_store.py`: ChromaDB `bidding_kb` 컬렉션 비동기 질의 래퍼 작성
  - `src/ml/dataset.py`: DB 조인(BidAnnouncement ⟕ BidResult) 및 정제 기반 Feature Store Parquet 빌더 구현
  - `src/ml/trainer.py`: K-Fold 및 Ridge/LightGBM 일반화 학습 엔진 구현
  - `src/ml/validate_model.py`: RMSE, MAPE, R² 실시간 산출 및 Champion vs Challenger 하이브리드 승격 게이트 구현
  - `src/ml/monitoring.py`: PSI(Population Stability Index) 기반 특징/예측 드리프트 감지 구현
  - `src/tasks/retrain_task.py`: Arq 비동기 재학습 파이프라인 태스크 정의
  - `tests/test_mlops_pipeline.py`: 싱글톤, 학습기, 평가, PSI 드리프트 단위 테스트 작성 및 100% 통과
- **관련 파일**: `src/ml/predictor.py`, `src/rag/vector_store.py`, `src/ml/dataset.py`, `src/ml/trainer.py`, `src/ml/validate_model.py`, `src/ml/monitoring.py`, `src/tasks/retrain_task.py`, `tests/test_mlops_pipeline.py`
- **검증 결과**: `pytest` 7/7 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | Phase 6 & 7 최종 완수 | SSE 토큰 스트리밍, P95 레이턴시 벤치마크 및 E2E 컷오버 통과

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: complete Phase 6 SSE streaming and Phase 7 E2E benchmark cutover validation`
- **주요 변경사항**:
  - `src/app/api/v1/chatbot.py`: `/stream` SSE(Server-Sent Events) 실시간 토큰 스트리밍 엔드포인트 구현
  - `frontend/src/App.tsx`: SSE EventSource 실시간 타이핑 수신 UI 및 예측 시뮬레이터 연동 완비
  - `scripts/benchmark_latency.py`: Phase 7 P95 레이턴시 벤치마크 측정 스크립트 작성 및 통과 (예측 P95: 0.95ms, 챗봇 P95: 0.65ms 달성)
  - `tests/test_e2e_cutover.py`: 전 주기 E2E 컷오버 테스트 작성 및 100% 통과
- **관련 파일**: `src/app/api/v1/chatbot.py`, `frontend/src/App.tsx`, `scripts/benchmark_latency.py`, `tests/test_e2e_cutover.py`
- **검증 결과**: `benchmark_latency.py` PASS (P95 < 1ms), `pytest` 8/8 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | Harness CI 연동 | Harness Cloud 파이프라인 선언형 설정 수립 및 hc.exe 플랫폼 종속성 교체

- **작업자**: 관범 & AI 에이전트
- **커밋**: `ci: setup declarative Harness CI pipeline definition and documentation`
- **주요 변경사항**:
  - `.harness/pipeline.yaml`: Harness Cloud 선언형 CI/CD 파이프라인 명세 수립 (규칙 검증 + ruff + pytest + docker compose build)
  - `docs/ops/harness_ci_guide.md`: 레거시 `hc.exe` 플랫폼 종속 바이너리 제거 및 Harness CI/CD 연동 가이드 수립
- **관련 파일**: `.harness/pipeline.yaml`, `docs/ops/harness_ci_guide.md`, `docs/README.md`
- **검증 결과**: `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | 실측 마이그레이션 & 레지스트리 | ML Champion 레지스트리 버저닝 수립 및 무손실 실측 검증 통과

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: setup initial ML champion registry and enhanced data preservation verification`
- **주요 변경사항**:
  - `ml_registry/quantum_leap_v25_pro/v25_pro_latest/`: 초기 Champion 모델 아티팩트 및 메타데이터(`metadata.json`, `metrics.json`, `status`) 등록
  - `scripts/verify_migration.py`: ML Champion 레지스트리 및 DB 무손실 검증 실측 로직 고도화 및 PASS 통과
- **관련 파일**: `ml_registry/quantum_leap_v25_pro/v25_pro_latest/*`, `scripts/verify_migration.py`
- **검증 결과**: `verify_migration.py` PASS, `pytest` 8/8 passed, `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | 컨테이너 & 타깃 고도화 | Makefile 자동화 타깃 (make up, migrate-verify, benchmark) 수립

- **작업자**: 관범 & AI 에이전트
- **커밋**: `chore: update Makefile with convenience targets for docker, verification, and benchmark`
- **주요 변경사항**:
  - `Makefile`: `make up`, `make down`, `make logs`, `make migrate-verify`, `make benchmark` 개발 편의 타깃 추가
- **관련 파일**: `Makefile`, `docs/changelogs/work_log.md`
- **검증 결과**: 전체 4단계 통합 검증 수동 및 자동 100% PASS

---

### 2026-07-31 | 최종 완료 & 인수인계 | refac_bid_box 전체 리팩토링 완수 및 최종 인수인계서 갱신

- **작업자**: 관범 & AI 에이전트
- **커밋**: `docs: complete final handoff report and update documentation index for Phase 0-7 refactoring`
- **주요 변경사항**:
  - `docs/handoff/2026-07-31_skill_system_handoff.md`: 스킬 시스템 및 Phase 0~7 전체 리팩토링 완수 인수인계 문서 갱신
  - `docs/README.md`: 문서 인덱스 상태를 "리팩토링 이행 및 컷오버 검증 완료 단계 (Phase 0~7 완수)"로 최종 업데이트
- **관련 파일**: `docs/handoff/2026-07-31_skill_system_handoff.md`, `docs/README.md`, `docs/changelogs/work_log.md`
- **검증 결과**: `validate_agent_rules.py` 6/6 PASS, `pytest` 8/8 passed, `benchmark_latency.py` PASS

---

### 2026-07-31 | 운영 스킬 구축 | project-orchestrator 전용 오케스트레이션 스킬 수립

- **작업자**: 관범 & AI 에이전트
- **커밋**: `feat: add project-orchestrator skill for automated docker stack execution and verification`
- **주요 변경사항**:
  - `.agents/skills/project-orchestrator/`: 도커 컨테이너 전체 시동(`make up`), 헬스체크, 무손실 검증(`make migrate-verify`), 레이턴시 벤치마크(`make benchmark`), 전체 테스트(`make test`, `make check-rules`) 자동 오케스트레이션 지침 구축
  - `.claude/skills/`, `.opencode/skills/`, `.cursor/rules/10-project-orchestrator.mdc` 미러 100% 동기화
  - `AGENTS.md`: 운영 영역 `project-orchestrator` 스킬 인덱스 수립
- **관련 파일**: `.agents/skills/project-orchestrator/*`, `.claude/skills/project-orchestrator/*`, `.opencode/skills/project-orchestrator/*`, `.cursor/rules/10-project-orchestrator.mdc`, `AGENTS.md`
- **검증 결과**: `validate_agent_rules.py` 6/6 PASS

---

### 2026-07-31 | 컴퓨터 종료 및 인프라 중지 | 도커 컨테이너 서비스(app, frontend, db, redis) 자원 안전 수거 및 세션 종료

- **작업자**: 관범 & AI 에이전트
- **커밋**: `chore: gracefully shutdown container stack for environment cleanup`
- **주요 변경사항**:
  - `make down`: FastAPI 백엔드, React 19 프론트엔드, MySQL 8 DB, Redis 7 캐시 전체 컨테이너 및 네트워크 자원 안전 중지 및 수거 완료
- **관련 파일**: `docker-compose.yml`, `docs/changelogs/work_log.md`
- **검증 결과**: `docker compose ps` (실행 중인 컨테이너 0개 확인), `validate_agent_rules.py` 6/6 PASS

---

### 2026-08-03 | 용역 모델 재설계 | G2B 제도 특징 배선, 손실함수 교체, 재발주 이력 도입

- **작업자**: 관범 & AI 에이전트
- **커밋**: `36ce33c`, `d760b5e` (병합 `c179bde`)
- **주요 변경사항**:
  - `src/ml/dataset.py`: 낙찰하한율·예가결정방법·용역구분 등 제도 필드 13종을 `raw_data` JSON 에서 추출 (`INSTITUTION_FIELDS`). 중분류 40종·소분류 200종 추가
  - `src/ml/features.py`: 범주형 특징 11종 수립, `collect_category_levels` / `apply_categorical_dtypes` 로 학습·추론 범주 수준 동기화
  - `src/ml/trainer.py`: 목적함수를 L2 에서 Huber 로 교체. 낙찰률 잔차가 0 에 몰린 비대칭 분포라 L2 는 중심 예측을 위로 밀어 올립니다
  - `src/ml/repeat_history.py`: 재발주 이력 6종 신설. 용역은 같은 기관이 1~2년 주기로 같은 사업을 재발주합니다 (주기 중앙값 358일)
  - `scripts/eval_servc_year_holdout.py`: 2024년까지 학습, 2025년 검증하는 연도 홀드아웃 평가
- **관련 파일**: `src/ml/dataset.py`, `src/ml/features.py`, `src/ml/trainer.py`, `src/ml/repeat_history.py`, `tests/test_repeat_history.py`
- **검증 결과**: 2025년 홀드아웃 R2 0.6767 -> 0.6968, 0.5%p 이내 적중 44.29% -> 60.52%, 예측 편향 +0.317%p -> -0.002%p. 456 passed

---

### 2026-08-04 | 서빙 경로 복구 | 특징 단일화, 배포 게이트, 승격 경로 신설

- **작업자**: 관범 & AI 에이전트
- **커밋**: `3a0b772`, `3ff3641`, `d964f4a` (병합 `e1f7255`, `cbb9e5b`)
- **주요 변경사항**:
  - `src/ml/model_registry.py`: 특징 맵 복제본 167줄 제거, `features.py` 단일 공급원으로 위임 (AGENTS.md 6항 위반 해소). 복제본에 신규 범주 기본값이 없어 문자열 범주가 float 변환 실패로 전부 0.0 이 되고 있었습니다
  - `src/ml/features.py`: `prepare_input_frame` strict 모드. 모르는 특징을 0.0 으로 채우는 대신 거부합니다
  - `src/ml/promotion.py`: 신설. `ml_registry/` 아티팩트를 `data/model_files/` 로 승격. 설계서 7장 필수 4(폴드 R2 > 0.99 금지)를 코드로 구현. 종전에는 두 경로를 잇는 코드 자체가 없었습니다
  - `src/ml/trainer.py`: 모델 선택 기준을 `avg_r2` 에서 `avg_mape` 로 교체. R2 는 조건부 평균을 겨냥해 CatBoost 를 뽑는데 0.5%p 적중은 46.80% 대 60.49% 로 크게 뒤집니다. 카테고리별 모델 네임스페이스 분리, 폴드별 원지표 보존
  - `src/app/api/v1/predictions.py`: `announcement_feature_payload` 로 제도 필드를 펼치고 DB 세션을 전달. 종전에는 34개 중 30개가 기본값이었습니다
  - 카테고리 기본 모델 매핑 3중 복제를 `CATEGORY_DEFAULT_MODELS` 정본 참조로 통합
- **관련 파일**: `src/ml/model_registry.py`, `src/ml/promotion.py`, `src/ml/trainer.py`, `src/ml/dataset.py`, `src/app/api/v1/predictions.py`, `tests/test_serving_feature_parity.py`
- **검증 결과**: API 경로 2025년 300건 실측 MAE 6.128 -> 0.973, 1%p 이내 적중 0.7% -> 83.0%. 학습기 홀드아웃 R2 0.6881. 526 passed

---

### 2026-08-04 | 예측 구간 | 분위 회귀와 등각예측 보정을 API 응답까지 배선

- **작업자**: 관범 & AI 에이전트
- **커밋**: `9da7bd6`, `4a4d517` (병합 `3dfe311`)
- **주요 변경사항**:
  - `scripts/eval_servc_prediction_interval.py`: 신설. 분위 회귀 구간의 피복률 측정. 소박한 구간은 명목 80% 대비 실제 75.52%, 10억 이상 구간은 66.85% 로 보정에 실패합니다
  - `src/ml/trainer.py`: `_train_quantile_models`. 학습 구간 뒤 15% 로 등각예측 배율을 산정한 뒤 분위 모델은 전량으로 재적합합니다. `LGB_BASE_PARAMS` 로 점 추정과 분위 모델의 용량 설정을 통일
  - `src/ml/promotion.py`: `model_q*.bin` 을 함께 승격
  - `src/ml/model_registry.py`: `JoblibModelWrapper.predict_interval` 지연 로드, `predict_interval` 진입점
  - `src/app/schemas/predictions.py`: `rate_low` / `rate_high` / `price_low` / `price_high` / `interval_coverage` 선택 필드 추가. 구 모델은 None 이라 원본 계약을 유지합니다
- **관련 파일**: `src/ml/trainer.py`, `src/ml/promotion.py`, `src/ml/model_registry.py`, `src/app/api/v1/predictions.py`, `src/app/schemas/predictions.py`, `docs/design/servc_prediction_interval_20260804.md`
- **검증 결과**: 배율 1.163014 적용 시 학습기 홀드아웃 피복률 76.04% -> 90.22%, API 경로 93.00%. 구간 폭 증가는 0.27%p. 574 passed 2 skipped, `validate_agent_rules.py` 6/6

---

### 2026-08-04 | 구간 UI·참가자 수·하이퍼파라미터 | 두 건 측정 후 기각

- **작업자**: 관범 & AI 에이전트
- **커밋**: `0f7f982`, `f1c99f9` (병합 `f536e52`, `8333fbb`)
- **주요 변경사항**:
  - `src/app/templates/bids/detail.html`: 예측 구간(낙찰률 범위·투찰가 범위·피복률) 노출. API 는 구간을 내놓고 있었으나 화면은 점 추정만 표시했습니다. 구 모델은 응답이 null 이라 블록을 감춥니다
  - `tests/test_prediction_interval_ui.py`: 신설. 응답 스키마 필드명이 바뀌면 템플릿이 undefined 를 읽고도 예외가 나지 않으므로 필드 일치를 고정합니다
  - `scripts/collect_servc_participant_count.py`: 신설. 설계 문서는 참가자 수가 "API 에 있으나 미수집" 이라 적었으나, 이미 수집 중인 `getScsbidListSttusServc` 가 `prtcptCnum` 을 내려주고 있었습니다. 비어 있던 것은 과거 이관분입니다
  - `scripts/eval_servc_participant_effect.py`: 신설. 오라클과 이력 특징을 나눠 측정
  - `scripts/tune_servc_hyperparams.py`: 신설. 좌표 하강 하이퍼파라미터 탐색
  - `scripts/retrain_servc_from_parquet.py`: 신설. DB 없이 학습 구간만 재실행
  - `scripts/eval_servc_api_path.py`: 신설. 운영 API 경로 실측
  - `src/ml/trainer.py`: `num_leaves` 255 를 검토했으나 63 유지. `subsample` 이 무효 설정임을 주석에 명시
- **관련 파일**: 위 전체 + `docs/design/servc_hyperparam_search_20260804.md`, `docs/design/servc_restricted_competition_20260803.md`
- **검증 결과**:
  - 참가자 수 2025년 116,397건 수집(보유율 100%). 단독응찰은 하한율보다 9.938%p 위, 100곳 초과는 0.008%p. 그러나 오라클 상한이 RMSE 4.9% 뿐이고 이력은 0.35% 만 회수해 **기각**
  - 하이퍼파라미터 좌표 하강 17회. `num_leaves` 63 -> 255 가 홀드아웃 MAE 1.4% 개선. 재학습·승격 후 API 경로 1,000건에서 정확도는 판별 불가(MAE -0.8%, RMSE +1.3%)이고 구간 폭만 1.423 -> 1.583%p 로 11.2% 악화되어 **롤백**
  - `subsample=0.8` 이 `subsample_freq` 기본값 0 때문에 무효였음을 확인 (0.6/0.8/1.0 의 MAE 가 소수점 넷째 자리까지 동일)
  - 605 passed 2 skipped, `validate_agent_rules.py` 6/6

---

### 2026-08-04 | 구간 폭 | 분위 모델 복잡도가 최적점임을 확인

- **작업자**: 관범 & AI 에이전트
- **커밋**: `32bc835`
- **주요 변경사항**:
  - `scripts/eval_servc_interval_width.py`: 신설. 분위 모델 `num_leaves` 를 15/31/63/127 로 바꿔 가며 등각 보정 후 최종 구간 폭을 측정합니다. 피복률은 등각예측이 보장하므로 폭만 비교하면 우열이 결정됩니다
- **관련 파일**: `docs/design/servc_hyperparam_search_20260804.md` 7장
- **검증 결과**: 폭이 U자를 그리며 현행 63 에서 최소(1.7728%p)입니다. 리프 15 는 배율이 1.093 으로 작아지나 원폭이 1.862 로 넓어져 2.0353%p, 리프 127 은 원폭이 1.516 으로 좁아지나 배율이 1.193 으로 커져 1.8075%p 입니다. 구간 폭은 분위 모델 용량으로 더 줄일 수 없으며 특징이나 데이터를 바꿔야 합니다

---

### 2026-08-04 | 하한율 가용성 | 결측 축소 가설을 제도별 실측 후 기각

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `scripts/audit_servc_lwlt_coverage.py`: 미개찰 용역 공고를 낙찰방법별로 집계하고 하한율 적용 방식의 실제 누락을 분리하는 감사 도구 신설
  - `docs/design/servc_lwlt_availability_20260804.md`: DB와 조달청 대체 API 실측 결과 기록
  - 하한율 결측을 수집 누락으로 간주하던 인수인계 우선순위 정정
- **관련 파일**: `scripts/audit_servc_lwlt_coverage.py`, `tests/test_audit_servc_lwlt_coverage.py`, `docs/design/servc_lwlt_availability_20260804.md`, `docs/handoff/2026-08-04_servc_serving_handoff.md`
- **검증 결과**: 2026년 7월 이후 미개찰 용역 10,434건 중 하한율 명시 방식 3,587건은 100% 보유해 실제 누락 0건. 결측 6,792건은 협상계약·규격가격동시입찰·수의시담 등에 집중. 용역 기초금액 API 첫 100건과 변경이력 API 전체 10건에는 하한율 필드가 없어 보강 원천으로 기각

---

### 2026-08-04 | 용역 샘플링 | `subsample_freq` 실효화 후 기각

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `scripts/tune_servc_hyperparams.py`: 절대 출력 경로 사용 시 결과 저장 후 표시 단계에서 발생하던 `ValueError` 수정
  - `subsample_freq` 0/1/5를 동일한 2025년 홀드아웃에서 비교
- **관련 파일**: `scripts/tune_servc_hyperparams.py`, `tests/test_tune_servc_hyperparams.py`, `docs/design/servc_hyperparam_search_20260804.md`, `docs/handoff/2026-08-04_servc_serving_handoff.md`
- **검증 결과**: 빈도 5는 MAE 1.2829 -> 1.2828, 0.5%p 적중 60.57% -> 60.53%, 학습 시간 11.4초 -> 13.8초. 정확도 이득이 측정 분해능 수준이고 적중률·시간이 악화되어 현행 `subsample_freq=0` 유지

---

### 2026-08-05 | 하한율 가용성 | 결측 축소 기각을 학습 모집단 실측으로 철회

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `scripts/audit_servc_lwlt_coverage.py`: `--skip-db --parquet` 로 학습 모집단의 결측을 낙찰방법별로 분해하는 감사 추가. 방법명이 결측을 완전히 결정하는 그룹과 그렇지 않은 그룹을 가름
  - `docs/design/servc_lwlt_availability_20260804.md`: v2.0.0 으로 정정. 기각 판정 철회
  - 인수인계 기각 목록과 잔여 과제 우선순위 원복
- **관련 파일**: `scripts/audit_servc_lwlt_coverage.py`, `tests/test_audit_servc_lwlt_coverage.py`, `docs/design/servc_lwlt_availability_20260804.md`, `docs/handoff/2026-08-04_servc_serving_handoff.md`
- **검증 결과**: 학습 데이터 917,629행의 결측 205,238건 중 **76.8%(157,647건)가 낙찰방법으로 설명되지 않습니다.** 거의 전부가 `공고서참조` 한 방법이며, 이 방법은 765,620건 중 79.4%가 하한율을 보유합니다. 결측 건의 낙찰률 표준편차는 6.35 로 보유 건 2.77 의 2.3배이고, 연도별 결측률이 14.7%~26.3% 로 움직여 제도 속성으로 볼 수 없습니다
- **방법론**: 초판 기각은 2026-07 이후 미개찰 공고 10,434건만 보고 내렸습니다. 그 표본에는 `공고서참조` 가 등장하지 않습니다. **표본의 결론을 다른 모집단으로 옮길 때는 두 모집단의 구성이 같은지를 먼저 확인해야 합니다**
### 2026-08-04 | Phase 7 컷오버 보강 | 무손실 기준선·모델 호환성·크로스 플랫폼 검증 강화

- **작업자**: 관범 & Codex
- **주요 변경사항**:
  - 원본 ChromaDB의 실제 기준선을 `bidding_kb` 1개 / 임베딩 10건으로 정정하고 별도 스냅샷의 모든 파일 체크섬을 검증
  - scikit-learn 런타임을 모델 직렬화 버전 1.8.0으로 고정하고 등록 모델 5종의 버전·서빙 특징 호환성 게이트 추가
  - Windows 가상환경 경로를 처리하는 Makefile과 격리 Compose 전체 검증 PowerShell 스크립트 추가
  - 레이턴시 벤치마크에 고유 질의, 예측 동시성, 오류 실패 판정, 원시 표본 JSON 증거 저장 추가
- **관련 파일**: `scripts/verify_migration.py`, `scripts/verify_model_compatibility.py`, `scripts/benchmark_latency.py`, `scripts/validate_windows.ps1`, `Makefile`, `uv.lock`
- **검증 결과**: 631 passed 2 skipped, Ruff 통과, 스키마 실질 차이 0건, `validate_agent_rules.py` 6/6

---

### 2026-08-05 | Phase 7 재현 환경 고정 | ChromaDB·모델 호환성 검증 신뢰성 보강

- **작업자**: 관범 & Codex
- **주요 변경사항**:
  - `chromadb>=0.6.3`이 1.5.9를 선택해 원본 ChromaDB 형식과 다른 런타임을 구성하던 문제를 `chromadb==0.6.3`으로 고정
  - Python 3.14에서의 비검증 런타임 구성을 막기 위해 지원 범위를 Python 3.11~3.13으로 명시하고, pytest 프로젝트 루트를 import 경로에 고정
  - 모델 호환성 검사가 일부 로드 실패를 통과로 표시하지 않도록 가중치 디렉터리의 기대 모델과 실제 로드 모델을 대조
- **관련 파일**: `pyproject.toml`, `uv.lock`, `src/ml/model_registry.py`, `scripts/verify_model_compatibility.py`, `tests/test_model_compatibility.py`
- **검증 결과**: Python 3.12 / ChromaDB 0.6.3 / scikit-learn 1.8.0에서 모델 5/5 호환, G1 검증 통과, `632 passed / 2 skipped`, Ruff 통과, `validate_agent_rules.py` 6/6

---

### 2026-08-05 | 용역 하이퍼파라미터 증적 추적 | 17회 탐색 원시 측정 기록 보존

- **작업자**: 관범 & Codex
- **주요 변경사항**:
  - `data/servc_hyperparam_search.json`을 Git으로 추적. 이 파일은 2025년 홀드아웃 기준 좌표 하강 17회의 파라미터·지표만 담은 8.5KB JSON이며, 원시 입찰 데이터와 모델 가중치는 포함하지 않습니다
  - 설계 문서에 증적 파일의 추적 범위와 목적을 명시
- **관련 파일**: `data/servc_hyperparam_search.json`, `docs/design/servc_hyperparam_search_20260804.md`
- **검증 결과**: JSON 파싱, 17회 시행 수, 기준선 및 최적 후보(`num_leaves=255`)의 측정값을 생성 스크립트·설계 문서와 대조

---

### 2026-08-05 | 깨끗한 체크아웃 테스트 재현성 | 외부 자산 검증을 명시적 경로로 분리

- **작업자**: 관범 & Codex
- **주요 변경사항**:
  - 가중치 파일이 없는 체크아웃에서 메타데이터 디렉터리만 보고 모델을 로드하려던 서빙 테스트를 실제 `model.bin` 존재 기준으로 수정
  - `make test`에서 Git 제외 자산을 요구하는 G1 테스트를 제외하고, `make test-data-assets`와 `make import-assets` 진입점을 추가
  - README, 크로스 플랫폼 가이드, Phase 7 체크리스트를 실제 검증 경로와 최신 컷오버 상태에 맞춤
- **관련 파일**: `Makefile`, `tests/test_serving_feature_parity.py`, `tests/test_predictions_api.py`, `README.md`, `docs/ops/cross_platform_guide.md`, `docs/design/REFACTORING_DESIGN.md`
- **검증 결과**: Python 3.12 / ChromaDB 0.6.3 / scikit-learn 1.8.0에서 `make test` 627 passed, 4 skipped, 3 deselected; Ruff 통과

---

### 2026-08-05 | 용역 모델 | 점 추정·분위 파라미터 분리와 리프 127 기각

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `src/ml/trainer.py`: `QUANTILE_PARAM_OVERRIDES` 신설. 분위 모델이 점 추정과 `LGB_BASE_PARAMS` 를 공유하던 구조를 끊었습니다
  - `scripts/eval_servc_point_quantile_split.py`: 신설. 점 추정 리프와 분위 리프를 갈라 조합별로 MAE 와 구간 폭을 잽니다
  - `scripts/tune_servc_hyperparams.py`: 평가에서 `apply_lower_limit` 제거. 학습기와 서빙 어느 쪽도 절단하지 않는데 탐색만 절단 후 순위를 매기고 있었습니다
  - `scripts/eval_servc_interval_width.py`: 현행 기준을 분위 오버라이드에서 읽도록 정정
- **관련 파일**: `src/ml/trainer.py`, `scripts/eval_servc_point_quantile_split.py`, `scripts/tune_servc_hyperparams.py`, `scripts/eval_servc_interval_width.py`, `docs/design/servc_hyperparam_search_20260804.md`
- **검증 결과**: 구간 폭이 점 추정 리프에 대해 소수점 넷째 자리까지 움직이지 않습니다. 두 축은 완전히 독립이며, 2026-08-04 의 "정확도와 폭을 맞바꿔야 한다" 는 판정은 구조가 묶여 있어 생긴 착시였습니다. 운영 실측에서도 점 추정 127 리프의 구간 폭이 1.423%p 로 63 리프와 동일합니다(분리 전이라면 1.583%p)
- **기각**: 점 추정 리프 127 은 홀드아웃 R2 0.6881 -> 0.6901, MAE -1.0% 로 champion 을 넘고 승격 게이트 4개를 모두 통과했으나, 운영 API 경로 동일 표본 1,000건에서 MAE 0.9848 -> 0.9863, RMSE 3.1195 -> 3.1455, 0.5%p 적중 75.2% -> 74.5% 로 전 지표가 나빠져 롤백했습니다. 255 에 이어 두 번째 같은 방향의 어긋남입니다
- **방법론**: **점 추정 용량은 홀드아웃 지표로 정하지 않습니다.** 2025년 홀드아웃 96,141건과 운영 표본(하한율 보유 1,000건)의 분포가 다르고 후자가 사용자가 보는 구성에 가깝습니다. 홀드아웃은 후보를 거르는 데까지만 쓰고 채택은 운영 경로 동일 표본 비교로 판정합니다

---

### 2026-08-05 | 용역 모델 | 특징 3종 기각과 운영 판정 도구 확보

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `scripts/compare_servc_models_paired.py`: 신설. 두 모델을 같은 공고에 돌려 오차 차이를 직접 검정합니다. 독립 비교보다 표준오차가 22배 작고, 그 표본이 잡을 수 있는 최소 차이를 함께 출력해 "판별 불가" 를 명시합니다
  - `scripts/diagnose_holdout_serving_gap.py`: 신설. 홀드아웃을 하한율 보유/결측과 금액대로 분해합니다
  - `scripts/probe_servc_lwlt_sources.py`: 신설. 공고 계열 API 의 하한율 보유 여부를 **공고번호로 대조**합니다. 건수만 비교하면 서로 다른 공고를 봐도 같아 보입니다
  - `scripts/eval_servc_rolling_institution.py`: 신설 후 구간 분해 추가
  - `docs/design/servc_rolling_institution_20260805.md`: 신설
  - `docs/design/servc_lwlt_availability_20260804.md`: 3.1 절 추가
- **기각 4건**:
  - 고정 시간 창 기관 이력(30/90/365일): 특징 9개를 넣어도 홀드아웃 MAE 이득 0
  - 지수감쇠 기관 이력: 홀드아웃 MAE -1.79% 이나 운영 쌍대 비교에서 t=5.39 로 열등. 승격 후 롤백하고 배선(마이그레이션 포함)도 원복
  - 점 추정 리프 127: 5,004건 쌍대 비교에서 제곱오차 t=2.13 으로 63 우세
  - 목록 API 로 하한율 보강: 조달청 검색이 현행 결측 227건을 전부 조회하고도 값 확보 0건
- **측정 방법 정정 2건**:
  - 운영 판정에서 `--require-lwlt` 를 기본으로 쓰던 것을 폐기합니다. 하한율 결측은 전체의 30% 이고 오차가 3.3배(2.481 대 0.762)라, 사용자가 겪는 나쁨이 몰린 구간을 측정에서 빼고 있었습니다
  - 요약값 비교를 쌍대 비교로 대체합니다. 1,000건 표본의 MAE 표준오차가 0.099 인데 관측 차이가 0.0015 였습니다. 표준오차의 1.5% 를 읽고 우열을 단정했던 것입니다
- **미제**: 홀드아웃 개선이 운영에서 세 번 연속 뒤집혔고 원인이 설명되지 않습니다. `inst_hist_rate` 의 학습·서빙 정합성은 확인했습니다(실값 상관 0.986). 나머지 33개 특징은 미확인이며 이것이 다음 최우선 과제입니다

---

### 2026-08-05 | 용역 서빙 | `inst_sample_cnt` 가 항상 0 으로 나가던 결함 수정

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `scripts/audit_feature_parity_values.py`: 신설. 학습 프레임과 서빙 경로가 같은 공고에서 **같은 값**을 만드는지 34개 특징 전부를 대조합니다. 기존 테스트는 키 존재만 봅니다
  - `src/ml/institution_history.py`: `lookup_institution_sample_count` 추가
  - `src/ml/features.py`: 표본 수를 payload 에 없으면 조회하도록 배선
  - `tests/test_serving_feature_parity.py`: 세션 유무로 값이 달라지는지 보는 회귀 테스트 3건 추가
  - `docs/design/servc_feature_parity_20260805.md`: 신설
- **결함**: `inst_sample_cnt` 는 `attach_institution_history` 가 학습 때 만드는 파생 컬럼이라 `announcement_feature_payload` 의 원본 컬럼 목록에 없고, `inst_hist_rate` 와 달리 조회 폴백도 없어 **서빙에서 항상 0.0** 이었습니다. 대조 실측 평균절대차 761. 모델이 이력 신뢰도를 판단하는 근거인데 늘 "표본 0" 을 받아 이력을 무시하라는 신호가 되고 있었습니다
- **검증 결과**: 재학습 없이 입력만 학습과 맞춘 결과(2025년 하한율 보유 1,000건, 동일 시드) MAE 0.9848 -> 0.9590, 0.5%p 적중 75.2% -> 76.2%, **구간 폭 1.423 -> 1.305 (-8.3%)**, 피복률 91.5% -> 90.5% 로 명목 90% 에 근접. 전 지표가 같은 방향으로 개선됐습니다
- **의의**: 구간 폭은 세 차례 실험 후 "분위 모델 용량으로는 더 줄일 수 없다" 고 결론지었던 값입니다. 원인의 일부가 모델이 아니라 입력 불일치였습니다. 홀드아웃 개선이 운영에서 세 번 연속 뒤집힌 것도 같은 뿌리일 가능성이 있습니다
- **남은 것**: 재발주 이력 6종이 일치율 94~96%, 상관 0.78~0.93 으로 부분 불일치입니다. 정의는 맞고 `lookup_repeat_history` 의 `max_rows=5000` 제한이 유력한 원인입니다

---

### 2026-08-05 | 용역 서빙 | 재발주 이력 조회의 카테고리 필터 누락 수정

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**: `src/ml/repeat_history.py`의 `lookup_repeat_history`에 `category` 조건 추가
- **결함**: 학습은 카테고리별 parquet 을 보는데 추론 조회에는 업무구분 조건이 없어, 같은 기관의 물품·공사 낙찰이 용역 재발주 이력에 섞여 들어갔습니다
- **검증 결과**: 특징 일치율 0.945~0.965 -> 0.950~0.970, 상관 `is_repeat` 0.898 -> 0.913, `repeat_hist_rate` 0.924 -> 0.936. 운영 성능은 중립(MAE 0.9590 -> 0.9589, 0.5%p 적중 76.2% -> 76.3%)
- **판단**: 개선이 미미해 근본 원인은 아니나, 정의 일치는 성능과 무관하게 지켜야 할 원칙이므로 유지합니다 (AGENTS.md 6항)
- **남은 원인**: `repeat_key`는 공고 제목 기반인데 `bid_results` 제목의 41%가 U+FFFD 로 깨져 있습니다. 학습 프레임과 추론 조회가 다른 제목을 보면 키가 어긋납니다. `max_rows=5000` 제한도 후보입니다

---

### 2026-08-05 | 용역 학습 | 재발주 이력의 동시각 누수 제거

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**: `src/ml/repeat_history.py`의 `attach_repeat_history`에 (키, 개찰시각) 경계 추가
- **결함**: 학습이 `shift(1)` 만 써서 **같은 날 개찰된 같은 사업의 다른 공고를 이력으로** 봤습니다. 추론은 `t < reference_ts` 로 올바르게 제외하고 있어 정의가 갈려 있었습니다. 이번에는 학습 쪽이 틀렸습니다
- **규모**: 용역 917,060행 중 같은 키·같은 개찰시각이 2건 이상인 행 51,175건(5.6%), 실제로 동시각을 이력으로 쓴 행 33,555건(3.7%)
- **기각한 가설**: 제목 인코딩 깨짐(두 테이블 3,000건 표본 100% 일치), `max_rows=5000`(초과 기관 0개), 공고 조인 실패분(0.1%)
- **검증 결과**: 특징 대조에서 재발주 이력 6종이 전부 0.95 이상으로 올라가 어긋난 특징이 7개 -> 1개. 재학습 결과 홀드아웃 R2 0.6881 -> 0.6824, 운영 쌍대 비교에서 절대오차 t=2.51 로 누수 포함본이 0.33% 우세
- **판단**: **누수 제거본을 유지합니다.** train/serve 정의 단일화는 비협상 원칙이고(AGENTS.md 6항), 학습 코드를 고친 이상 누수 모델은 재현 불가능한 아티팩트이며, 대가 0.33% 로 앞으로의 홀드아웃 지표를 신뢰할 수 있게 됩니다

---

### 2026-08-05 | 용역 정합성 | 특징 대조 표본을 600건으로 늘려 판정 정정

- **작업자**: 관범 & AI 에이전트
- **정정 내용**: 200건 표본에서 "재발주 이력 6종이 전부 0.95 이상" 이라 보고했으나, 600건에서는 상관이 0.864~0.948 로 일부 미달합니다. 일치율은 0.945~0.965 -> 0.975~0.980 으로 올라갔으므로 개선은 실재하나 완전한 해소가 아닙니다
- **600건 기준 잔여 불일치 8건**: `inst_hist_rate` 0.9118, `inst_sample_cnt` 0.8789(평균절대차 761 -> 189, 75% 감소), 재발주 이력 5종 0.864~0.948, `ntce_kind_nm` 0.9433
- **성격 규명**: 남은 차이는 **시점**입니다. 학습은 그 공고 개찰일 직전까지의 누적, 서빙은 집계 표의 현재 시점 누적입니다. 실제 서비스는 미개찰 공고를 예측하므로 현재 시점 값이 정확하며, 어긋나는 것은 과거 공고로 평가할 때뿐입니다. **이 불일치의 상당 부분은 평가 방식의 산물일 수 있습니다**
- **다음 과제**: as-of 집계 표로 평가 시점을 고정해 확정해야 합니다. 그 전까지 운영 성능 측정치는 실제보다 나쁠 수 있다는 점을 감안해 읽어야 합니다
- **부수 확인**: 물품 champion `quantum_leap_v25_pro` 는 특징 4개짜리 원본 모델이며 재학습 이력이 없습니다. 오늘 수정한 공용 코드의 영향권 밖이고, 용역(35개)과 격차가 큽니다

---

### 2026-08-05 | 용역 정합성 | 잔여 불일치가 시점 차이임을 확정

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**: `scripts/verify_asof_history_parity.py` 신설. 그 공고 개찰일 이전만 SQL 로 직접 집계해 학습값과 대조합니다
- **검증 결과**: 2025년 100건에서 학습 대 as-of 계산이 표본 수 상관 **0.9999**(평균절대차 5.2), 낙찰률 상관 0.9878(평균절대차 0.0017). **학습 계산은 정확합니다**
- **함의**: 5.4 절의 잔여 불일치 8건은 코드 결함이 아니라 **측정 아티팩트**입니다. 서빙 집계 표는 현재 시점 값이고, 실제 운영은 미개찰 공고를 예측하므로 그것이 정확합니다. 어긋나는 것은 과거 공고로 평가할 때뿐입니다
- **다음 과제 정정**: "배관에 결함이 더 있는지 확인" 에서 "평가용 as-of 스냅샷 구축" 으로 성격이 바뀝니다. 오늘 잰 운영 성능(MAE 1.5867)은 실제를 과소평가하고 있을 수 있습니다

---

### 2026-08-05 | MLOps | 알림 설계서 작성 (구현 미착수)

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**: `docs/design/mlops_notification_20260805.md` 신설
- **배경**: 원본 Harness(SaaS) 를 Arq 로 대체하면서 자율성과 재현성을 얻고 운영 가시성을 내줬습니다. 그중 알림 부재가 가장 큰 구멍입니다. 주간 재학습이 실패해도 아무도 모르고, 승격이 수동인데 **승격할 만한 모델이 나왔다는 신호 자체가 전달되지 않습니다**
- **설계 요지**: 웹훅 방식. `httpx` 가 이미 의존성에 있어 새 라이브러리가 필요 없고, `AUTOMATION_CALLBACK_BASE_URL` 선례를 따릅니다. 알림 실패가 본 작업을 되돌리지 않도록 예외를 삼킵니다. `REJECT_CHALLENGER` 는 보내지 않아 소음을 막습니다
- **범위 밖**: 자동 승격(의도적 수동 유지), 감사 로그(1인 작업), 관리 UI, 재시도
- **예상 작업량**: 1시간 이내

---

### 2026-08-05 | MLOps | 알림 구현 완료

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**: `src/tasks/notifier.py` 신설, `MLOPS_WEBHOOK_URL` 설정 추가, 재학습·스케줄 5개 지점 배선
- **발신 대상**: 승격 권고(`PROMOTE_CHALLENGER`), 재학습 예외, 야간 수집 실패, 주간 재학습 실패, 학습 데이터 없음, 홀드아웃 분리 실패. 정상 기각은 보내지 않습니다
- **설계와 달라진 점**: 홀드아웃 분리 실패는 판정이 `REJECT_CHALLENGER` 로 덮어써지므로 판정이 아니라 `holdout_is_overfit` 플래그를 따로 보고 경고를 냅니다
- **검증 결과**: `tests/test_mlops_notifier.py` 11건 신설 포함 39건 통과. URL 미설정·HTTP 500·타임아웃에서 예외가 새지 않음을 고정
- **실환경 수신 검증**: 2026-08-06 완료. Slack Incoming Webhook 발급 후 발신 확인(HTTP 200, 채널 실제 수신). `notify()` 가 예외를 삼키므로 조용한 종료는 성공 신호가 아니며, 응답 코드 또는 채널 확인이 필요합니다

---

### 2026-08-05 | 문서 정합성 | 기관 이력 TODO 문서를 완료 기록으로 갱신

- **작업자**: 관범 & AI 에이전트
- **배경**: `docs/handoff/inst_hist_rate_impl_todo.md` 가 "학습·추론 경로에 미연결" 상태로 남아 있었으나, 실제로는 `bd4bb55` 에서 연결이 끝났습니다
- **주요 변경사항**: TODO-1~5 의 결정값과 근거, 배치 집계로 32시간 제약을 해소한 경위, train/serve 연결 지점 5곳, 검증 수단을 기록으로 정리

---

### 2026-08-05 | MLOps | 승격·롤백 도구 구축

- **작업자**: 관범 & AI 에이전트
- **배경**: 승격 권고 알림은 붙었으나 정작 승격 수단이 REPL 코드 두 줄 안내뿐이었고, 롤백은 백업 디렉터리를 사람이 직접 옮기는 절차였습니다. "즉시 롤백 가능" 이 비협상 원칙(AGENTS.md)인데 그 실행이 손 절차에 걸려 있었습니다
- **주요 변경사항**: `scripts/promote_model.py`(status/promote/rollback), `src/ml/promotion.py::rollback` 추가, `docs/ops/model_promotion_runbook.md` 신설
- **설계 결정**: 승격은 `--apply` 없이는 아무것도 바꾸지 않습니다(예행이 기본). 롤백은 현재 서빙본을 버리지 않고 백업 자리로 넣어 **왕복 가능**합니다
- **검증 결과**: `tests/test_promotion_cli.py` 8건 신설. 전량 660 passed / 2 skipped
- **범위 주의**: 승격 자동화는 여전히 하지 않습니다. 홀드아웃 이득이 운영에서 세 번 재현되지 않은 전력이 근거입니다

---

### 2026-08-05 | UI 변경 복원 | 홈 최근 공고·낙찰 AI 분석 연결

- **작업자**: 관범 & Codex
- **주요 변경사항**:
  - 다른 브랜치에서 Docker 이미지를 재빌드해 누락된 홈 최근 공고 패널 및 외자 분야를 현재 작업 브랜치에 복원
  - 낙찰 상세의 `AI 분석 시작하기` 링크에 결과 ID를 연결하고 챗봇 초기 문맥을 자동 전달
  - 데스크톱 홈 패널과 모바일 스와이프 동작을 함께 복원
- **관련 파일**: `src/app/api/ui.py`, `src/app/services/home_context.py`, `src/app/templates/index.html`, `src/app/templates/bids/result_detail.html`, `src/app/templates/chatbot/chat.html`
- **검증 결과**: 홈·UI SSR 회귀 테스트 58건 통과

---

### 2026-08-05 | 용역 학습 | 서빙 모델이 최신 20% 를 학습하지 않던 결함 수정

- **작업자**: 관범 & AI 에이전트
- **주요 변경사항**:
  - `src/ml/trainer.py`: 모델 선택 후 **전량으로 재적합**(`_refit_on_full`). 조기 종료가 고른 트리 수를 고정해 다시 학습합니다
  - `src/ml/trainer.py`: 분위 모델도 `X_train` 대신 전량 사용
  - `src/ml/promotion.py`: `refit_on_full` 을 서빙 메타데이터로 전달
  - `scripts/diagnose_serving_vs_holdout_model.py`: 신설. 격차가 모델 탓인지 경로 탓인지 가릅니다
  - `scripts/eval_servc_refit_unbiased.py`: 신설. 두 방식을 같은 학습 상한으로 비교해 낙관 편향을 없앱니다
  - `docs/design/servc_refit_on_full_20260805.md`: 신설
- **결함**: 시간순 80/20 분할 후 **앞 80% 로 학습한 모델을 그대로 저장·승격**하고 있었습니다. 시계열 분할이라 버려지는 20%(183,526행)는 가장 최신 구간이며, 2024년 후반과 2025년 전체가 여기 들어갑니다. 서빙 모델이 최근 약 1.5년을 배우지 못한 상태였습니다. 분위 모델도 같았습니다
- **원인 규명**: 서빙 모델을 parquet 프레임에 직접 적용해 갈랐습니다. 홀드아웃 모델 0.7616 / 서빙 모델 + parquet 0.9500 / 서빙 모델 + API 0.9590 으로, **경로 차이 1%, 모델 차이 25%** 였습니다
- **검증 결과(낙관 편향 포함)**: 운영 쌍대 비교 3,999건에서 MAE 1.5989 -> 1.4984(-6.3%), 0.5%p 적중 59.11% -> 62.54%, **구간 폭 2.0737 -> 1.6898(-18.5%)**, 피복률 88.20% -> 89.57%. 절대오차 t=-10.59
- **검증 결과(편향 없음)**: 두 방식을 2024년까지로 맞춰 2025년 평가. MAE 1.4003 -> 1.3006(**-7.12%**), R2 0.6726 -> 0.6920, 0.5%p 적중 58.51% -> 60.34%, 절대오차 t=-52.27. **편향을 없앤 쪽이 오히려 이득이 큽니다.** 조기 종료 트리 수가 600(상한)이라 차이는 순수하게 학습 행 수(612,120 대 765,150)에서 옵니다
- **의의**: 홀드아웃 실험은 2024년까지 전량 학습, 운영은 2024년 중반까지만 학습한 모델을 썼습니다. **두 경로의 학습 범위가 애초에 달랐으므로 홀드아웃 개선이 운영에서 재현될 이유가 없었습니다.** 2026-08-04~05 에 세 번 겪은 역전 현상의 유력한 설명입니다

---

### 2026-08-05 | 성능 | SSE 첫 토큰 지연의 원인 정정과 대책

- **작업자**: 관범 & AI 에이전트
- **배경**: Phase 7 은 첫 토큰 P95 11.06초를 프리필 탓으로 보고 "애플리케이션 최적화로는 도달 불가" 로 기록했습니다. 진단이 틀렸습니다
- **실제 원인 1**: `gemma4` 사고(thinking) 단계. 사고 토큰은 0.57초에 나오지만 우리가 읽는 `message.content` 는 사고가 끝난 뒤에야 시작됩니다. `think: false` 로 첫 토큰 10.53초 -> **0.38초**
- **실제 원인 2**: 모델 콜드 로드 11.78초. `keep_alive` 명시와 기동 예열로 제거
- **프리필은 원인이 아니었습니다**: 실제 운영 프롬프트는 약 300토큰이라 프리필 0.1초 미만. 2,168토큰에서도 3.13초
- **부수 개선**: RAG 정형 집계를 캐시. 적중 시 0.571초 -> 0.0008초, 값 동일
- **검증 결과**: SSE 첫 토큰 P95 11.06초 -> 3.05초(장비 부하 4.4), P50 0.75초. 전체 P95 13.19초 -> 4.41초. 테스트 15건 신설
- **남은 검증**: 부하 6.5 에서 재측정 시 P95 5.57초로 튀었습니다. 병렬 학습 세션이 CPU 를 점유하는 중이라 **유휴 장비 재측정이 필요**합니다

---

### 2026-08-05 | 장애 | 챗봇이 닷새간 지식베이스 없이 답하고 있었음

- **작업자**: 관범 & AI 에이전트
- **증상**: 낙찰결과 AI 분석에서 "KB 최신화가 119시간 이상 지연" 경고. 확인 결과 경고는 정확했고, 그보다 큰 문제가 있었습니다
- **근본 원인**: ChromaDB `collections.config_json_str` 이 빈 객체(`{}`)라 chromadb 0.6.3 이 컬렉션을 열지 못했습니다(`KeyError: '_type'`). 임베딩 500건은 온전했습니다
- **왜 몰랐나**: `retrieve_semantic_context` 가 예외를 잡아 `{"document": "문맥 검색 오류: ..."}` 를 **문서인 것처럼** 반환했습니다. 오류 문자열이 LLM 프롬프트에 실렸고, 화면과 로그 어디에도 실패가 남지 않았습니다
- **verify_migration 도 통과시켰습니다**: sqlite 를 직접 읽어 행 수만 확인했기 때문입니다. 행이 있는 것과 읽히는 것은 다릅니다
- **조치**: 컬렉션 설정 JSON 복구(백업 후 적용), KB 재색인(500건, 2026-07-31 -> 2026-08-05), 실패를 빈 목록과 로그로 바꿈, `verify_migration` 에 실제 조회 검증 추가
- **검증 결과**: 정상 KB 는 `bidding_kb 질의 정상 (500건 색인)`, 복구 전 백업본은 `KeyError: '_type'` 로 정확히 실패. 회귀 테스트 3건 추가

---

### 2026-08-05 | 성능 | 공고 테이블 카테고리+날짜 인덱스 추가

- **작업자**: 관범 & AI 에이전트
- **배경**: 낙찰결과 AI 분석의 RAG 정형 검색이 공고 테이블(546만 행)을 요청당 여섯 번 봅니다. 기존 `ix_bid_ann_dt_cat` 는 컬럼 순서가 (bid_ntce_dt, category) 라 등치 조건을 선두에서 쓰지 못했습니다
- **실측 (인덱스 추가 전)**: 현행 537ms, category 단일 인덱스 강제 149ms, dminstt_nm 인덱스 강제 **46,915ms**
- **조치**: `ix_bid_ann_cat_dt (category, bid_ntce_dt)` 추가. 온라인 DDL(inplace/lock=none)로 57.6초 소요
- **결과**: 해당 질의 537ms -> **1ms**. 옵티마이저가 새 인덱스를 선택하며, 기관명 인덱스를 골라 47초가 되는 최악 경로도 함께 막힙니다
- **남은 구간**: 정형 검색 총 1.82초 중 나머지는 `bid_ntce_nm LIKE '%...%'` 계열 group by 5건(각 약 0.35초)입니다. 앞 와일드카드라 인덱스로는 더 줄지 않습니다. 전문검색 인덱스 도입은 별도 판단이 필요합니다
- **주의 (마이그레이션 계보)**: 본 리비전은 `a1c4e7b90d21` 위에 두었습니다. 다른 세션의 `b7c3d4e5f601` 도 같은 부모라 두 브랜치가 병합되면 head 가 둘이 됩니다. 그때 `alembic merge` 리비전 한 건이 필요합니다. 리비전 자체는 멱등이라 이미 인덱스가 있는 DB 에서도 안전합니다
---

### 2026-08-05 | 용역 학습 | 기각 후보 편향 제거 재검증

- **작업자**: 관범 & Codex
- **주요 변경사항**: `scripts/eval_servc_candidates_unbiased.py`와 회귀 테스트를 추가하고, 운영 34개 특징의 단일 특징 경로에서 리프 127·255와 지수감쇠 반감기 20건을 같은 학습 상한으로 쌍대 비교했습니다
- **데이터 불변조건**: `data/feature_store/dataset_Servc.parquet` 917,629행 × 28컬럼 확인
- **검증 결과**: 기준 리프 63 MAE 1.30501에서 리프 127은 1.29298, 리프 255는 1.28985, 지수감쇠는 1.27746으로 모두 개선됐습니다. 리프 255와 지수감쇠 결합은 MAE 1.25857(-3.56%), RMSE 2.62247(-2.14%), 0.5%p 적중 61.018%이며 절대오차 t=-29.53입니다
- **판정**: 과거 세 기각 판정은 전량 재적합 수정 후 유지되지 않습니다. 결합 후보를 다음 challenger로 권고하되, 운영 배선·재학습·승격은 수행하지 않았습니다
---

### 2026-08-05 | 인프라 최적화 | 홈 최근 공고 조회 복합 인덱스 추가

- **작업자**: 관범 & Codex
- **결함**: 홈 화면 캐시가 비어 있을 때 카테고리별 최근 공고 조회가 단일 인덱스와 filesort를 반복해 최초 응답이 50초 이상 지연되었습니다
- **주요 변경사항**:
  - `bid_announcements`에 `category + collected_at + bid_ntce_dt + id` 복합 인덱스 추가
  - 공통 최근 공고 조회용 `collected_at + bid_ntce_dt + id` 복합 인덱스 추가
  - ORM 정의와 Alembic 마이그레이션(`b7c3d4e5f601`) 동기화
- **검증 결과**: 캐시 미사용 홈 payload 약 56초 -> 0.047초. 실행 계획에서 `Using filesort`가 제거되고 두 조회 모두 복합 인덱스의 backward index scan을 사용합니다
- **무손실 검증**: `scripts/verify_migration.py` PASS, 공고 5,461,079행·낙찰 3,405,928행 확인

---

### 2026-08-06 | 용역 학습 | 기관 EWM과 리프 255 운영 검증

- **작업자**: 관범 & Codex
- **주요 변경사항**: 용역에만 기관 EWM 반감기 20건과 점 추정 `num_leaves=255`를 적용하고, 물품과 분위 모델 설정은 유지했습니다. 학습·서빙 기관 이력은 `src/ml/features.py` 단일 경로에서 평균·표본 수·EWM을 한 번에 조회합니다
- **누수 방지**: 같은 개찰 시각의 공고는 그룹 첫 위치의 직전 EWM을 공유합니다. 결측을 건너뛰는 pandas `first` 대신 위치 기반 복제를 사용합니다
- **편향 없는 검증**: 2024년까지 학습하고 2025년 96,141건 평가. MAE 1.30541 -> 1.26461(-3.13%), 절대오차 t=-29.62
- **재학습**: `v_20260806_025423_494`, 917,629행, 655초, 35개 특징, `refit_on_full=true`. 홀드아웃 R2 0.6924, RMSE 2.6571
- **운영 쌍대 검증**: 3,999건에서 MAE 1.4984 -> 1.4471(-3.42%), 0.5%p 적중 62.54% -> 64.02%, 절대오차 t=-7.50. 최소 감지 차이 0.01369보다 관측 차이 0.05135가 큽니다
- **무손실 검증**: 공고 5,461,079행, 결과 3,405,928행 유지. 파생 기관 집계 38,765행 중 EWM 38,581행(99.53%) 채움
- **승격**: 수행하지 않았습니다. challenger 아티팩트와 측정 근거만 준비했습니다

---

### 2026-08-06 | 용역 학습 | 기관 EWM·리프 255 모델 승격 및 사후 검증

- **작업자**: 관범 & Codex
- **승격**: `servc_institution_v1/v_20260806_025423_494`를 기본 서빙 슬롯에 적용하고 직전 `v_20260805_103528_292`를 `data/model_backups/servc_institution_v1`에 보관했습니다
- **무결성**: 서빙 슬롯과 레지스트리의 점 추정·10분위·90분위 아티팩트 SHA-256이 각각 일치함을 확인했습니다
- **사후 실측**: 모델 ID를 지정하지 않은 기본 API 경로의 2025년 3,999건에서 MAE 1.4471, RMSE 3.9564, 편향 0.1359, 0.5%p 적중 64.02%, 90% 구간 피복률 89.40%, 구간 폭 중앙값 1.7286%p였습니다
- **특징 감사 보강**: `scripts/audit_feature_parity_values.py`가 Servc 카테고리 계약의 35개 특징을 사용하도록 바꿔 `inst_ewm_rate` 누락을 막았습니다. 600건에서 EWM 상관 0.8899, 평균절대차 0.00791이며 과거 as-of 값과 현재 집계값의 기지 시점 차이로 판정했습니다
- **감사 판정**: 임계값 미달 9개는 모두 알려진 시점 차이였고 예상 밖 차이는 0개였습니다. 특징별 최소 상관·최대 차이 가드를 벗어나면 기지 특징도 신규 배관 결함으로 올립니다

---

### 2026-08-06 | 물품 학습 | 34특징 모델 재학습·승격

- **작업자**: 관범 & Codex
- **재학습**: `dataset_Thng.parquet` 784,266행으로 `quantum_leap_v25_pro/v_20260806_043408_749` 생성. 386초, LightGBM, 홀드아웃 R2 0.3583, 폴드별 R2 0.2603~0.3210
- **운영 쌍대 검증**: 2,992건에서 MAE 5.9600 -> 3.2587, 0.5%p 적중 2.31% -> 29.31%, 절대오차 t=-33.91. 최소 감지 차이 0.15934보다 관측 차이 2.70127이 큽니다
- **승격 후 실측**: 전체 원본 특징을 사용한 3,000건에서 실패 0건, MAE 2.8958, RMSE 4.4243, R2 0.4160, 편향 -0.0221
- **승격**: `v_20260806_043408_749`를 기본 물품 서빙 슬롯에 적용하고 직전 25.1 규칙 모델을 `data/model_backups/quantum_leap_v25_pro`에 보관했습니다
- **측정 도구 수정**: Servc 고정 표본, 빈 구간 폭 오판정, sparse 3특징 측정, 명시 `model_id` 무시를 수정했습니다

---

### 2026-08-06 | 인수인계 | 모델 성능 개선 재개 기준 정리

- **작업자**: 관범 & Codex
- **현재 상태 확인**: Servc `v_20260806_025423_494`, Thng `v_20260806_043408_749`가 기본 서빙 중이며 feature store 불변조건 917,629행 × 28컬럼과 784,266행 × 12컬럼을 확인했습니다
- **주요 변경사항**: 두 모델의 승격·실측·롤백 기준과 다음 Servc 하한율 결측 집단 진단의 평가 설계·중단 기준을 `docs/handoff/2026-08-06_model_improvement_handoff.md`에 정리했습니다
- **문서 정합성**: 이미 기각된 낙찰방법별 분리 모델을 유망 과제로 적은 문구를 정정하고, 하한율 결측 규칙 복원과 분리 학습을 재시도하지 않도록 문서 우선순위를 명시했습니다

---

### 2026-08-06 | Phase 4 | 가중치 배포 경로 확립과 저장 경로 설정 단일화

- **작업자**: 관범 & Claude
- **전제 정정**: 설계서 3.5/Phase 4 는 AS-IS 를 "Git 내 model_files 41MB" 로 적고 목표를 저장소 경량화로 두었으나, 실사 결과 바이너리는 이미 `.gitignore` 의 `*.bin`/`*.joblib` 로 제외돼 Git 추적 파일이 10개(metadata.json, preprocess.py, champion_summary.json)뿐이었습니다. 경량화는 이미 달성된 상태였습니다
- **실제 결함**: 배포 경로 부재. 저장소만 클론한 장비에는 `metadata.json` 만 도착해 예측 API 가 뜨지 않습니다. `import_data_assets.py` 는 원본 `bid_box` 가 옆에 있어야 동작하므로 새 장비에서는 쓸 수 없습니다
- **기각한 대안**: Git LFS(GitHub 무료 한도 저장 1GB·월 대역폭 1GB, 승격마다 71MB 누적으로 소진이 빠르고 되돌리기 어려움), MinIO(boto3 의존성과 컨테이너 증설이 1인 운영·71MB 규모에 과함)
- **주요 변경사항**: `scripts/sync_model_files.py` 신설(export/import/verify), 경로 3종 설정 단일화(`MODEL_FILES_DIR`, `MODEL_BACKUPS_DIR`, `MODEL_METRICS_DIR`). `model_registry.py`, `promotion.py`, `verify_migration.py` 가 같은 설정을 따릅니다
- **번들 구성 근거**: `model_backups/` 를 포함합니다. 승격된 모델은 서빙본이 원본과 달라져 `verify_migration.py` 가 원본 기준선을 백업 쪽에서 대조하기 때문입니다. 백업을 뺀 상태로 실측하니 G1 검증이 체크섬 불일치로 실패했습니다
- **매니페스트 불변**: `data_assets_checksums.json` 은 갱신하지 않습니다. 원본 4종의 G1 기준선이며 서빙본으로 재생성하면 승격 모델이 기준선을 덮습니다
- **실측**: 82.0MB -> 압축 29.8MB(파일 30개). 격리 경로에 배치한 뒤 `verify_migration.py` 4/4 통과를 확인했습니다
- **검증 결과**: 신설 테스트 8건 포함 726 passed / 2 skipped. 잘린 번들 검증이 EOFError 로 죽어 import 방어가 무력화되던 결함을 테스트가 잡아 수정했습니다
- **남은 것**: 없음. Phase 4 미완 항목이 닫혔습니다

---

### 2026-08-06 | 용역 진단 | 하한율 결측 집단 잔차 구조 진단

- **작업자**: 관범 & Claude
- **기준선 재확인**: 운영 MAE 1.4471, 0.5%p 적중 64.02%, 구간 폭 1.7290%p, 피복률 89.40%로 인수인계와 전 항목 일치했습니다
- **진단 도구**: `scripts/diagnose_servc_lwlt_residuals.py`를 신설했습니다. champion은 `refit_on_full` 아티팩트라 in-sample 낙관이 섞이므로, 학습 경로와 같은 특징·하이퍼파라미터로 평가 연도 직전까지만 학습해 2023~2026년을 out-of-sample로 쟀습니다
- **낙찰방법 수집 단절 확인**: `sucsfbid_mthd_nm`이 2015~2024년 833,150행 전량에서 `공고서참조` 단일값입니다. 2015년 행도 2026-03~08에 재수집했는데 동일하므로 G2B API 제약이며 백필로 되찾을 수 없습니다
- **편향 재현 확인**: 하한율 결측 집단 +0.3786/+0.6637/+0.7984/+0.5726, 보유 집단 -0.3101/-0.2671/-0.2309/-0.2558로 4년 부호 유지입니다
- **편향 보정 전면 기각**: 편향 부호가 왜도의 반대 부호와 8개 조합 전부 일치했습니다. 오라클 오프셋조차 8개 조합 전부 악화(-0.074 ~ -0.151)했고, 2025년 낙찰방법별 편향을 2026년에 적용하면 전체 MAE 1.3554 -> 1.4642로 나빠집니다
- **승격 없음**: 재학습·승격하지 않았습니다. Servc 서빙은 `v_20260806_025423_494` 그대로입니다
- **문서**: `docs/design/servc_lwlt_residual_diagnosis_20260806.md` 작성, 스킬 기각 목록에 4개 항목과 편향 판정 절차를 추가했습니다

---

### 2026-08-06 | 용역 실험 | 최근 구간 표본 가중 학습 기각

- **작업자**: 관범 & Claude
- **가설 출처**: 낙찰방법이 학습 표본의 90.8%에서 상수이므로 최근 구간에 가중을 주면 그 신호를 더 쓸 것이라는 잔차 진단의 후속 가설입니다
- **설계**: 학습 2025년까지 861,291행, 평가 2026년 56,338행 out-of-sample. 기준선(균등)과 지수감쇠 반감기 365일·730일을 동일 학습 상한·동일 하이퍼파라미터로 비교했습니다
- **전체 판정**: 가장 좋은 반감기 730일의 쌍대 관측 차이가 -0.00228로 최소 감지 차이 0.00300에 못 미쳐 판별 불가입니다
- **가설 반증**: 겨냥한 하한율 결측 집단이 오히려 악화 방향입니다(365일 +0.01177 t=2.25 기준선 우세, 730일 +0.00728 t=1.92 판별 불가)
- **구조 확인**: 기관 이력 0~49건 구간은 개선, 200건 이상 구간(전체의 61.8%)은 악화로 순증이 아니라 재분배입니다
- **기각**: 홀드아웃에서 방향이 없어 운영 쌍대 검정까지 가지 않았습니다. 재학습·승격 없음, Servc 서빙은 `v_20260806_025423_494` 그대로입니다
- **문서**: `docs/design/servc_recency_weighting_20260806.md` 작성, 스킬 기각 목록과 "집단별 판정 합산 시 개수가 아니라 비중" 절을 추가했습니다

---

### 2026-08-06 | RAG | 지식베이스 증분 색인 도입

- **작업자**: 관범 & Claude
- **문제**: `rebuild_knowledge_base` 가 매 실행마다 `delete_collection` 후 전량 재임베딩했습니다. 변경이 0건이어도 비용이 같고, 재구축 중에는 컬렉션이 비어 챗봇이 근거 없이 답하며, 색인이 실패하면 KB 가 빈 채로 남았습니다
- **판정 기준**: DB 시각이 아니라 문서 본문 SHA256 을 씁니다. `collected_at` 은 INSERT 시각이라 재수집으로 값이 갱신돼도 시각이 그대로일 수 있어 변경 감지에 쓸 수 없습니다
- **상태 저장**: 새 테이블 대신 ChromaDB 메타데이터에 `doc_hash`, `fmt` 을 넣었습니다. 마이그레이션이 없고 색인과 해시가 원자적으로 함께 움직입니다
- **안전 장치**: 컬렉션을 먼저 지우지 않고 upsert 로 제자리 갱신합니다. 삭제는 재색인 뒤에 수행합니다. `fmt` 불일치·해시 없는 문서·조회 실패 시 전량 재구축으로 폴백합니다
- **실측**: 문서 1,000건 기준 전량 28.72초, 증분 변경 0건 0.01초, 10건 0.38초, 100건 2.65초입니다. 측정 순서를 뒤집어 재확인했고(증분 먼저 0.01초 / 전량 27.46초) 두 방향 결론이 같습니다
- **검증 결과**: 신설 테스트 10건 포함 736 passed / 2 skipped, `verify_migration.py` 4/4 통과
- **문서**: `docs/design/kb_incremental_indexing_20260806.md`
- **범위 밖**: 원문(HWP/PDF) 수집, 청킹·overlap, 문서 간 링크. 현재 KB 문서는 DB 행에서 조립한 정형 레코드(평균 183자)라 청킹 대상이 아니며, 논의하려면 원문 수집 비용 판단이 선행되어야 합니다

---

### 2026-08-06 | 용역 인수인계 | 진단 세션 재개 기준 정리

- **작업자**: 관범 & Claude
- **근거 보강**: champion 특징 중요도에서 낙찰방법이 35개 중 16위(1.84%)임을 확인해 "학습 표본의 90.8%에서 상수" 진단에 직접 증거를 붙였습니다. 기관 이력 3종 합계는 24.55%로 단일 최대 블록이며, 최근 가중이 실패한 이유를 수치로 설명합니다
- **인수인계**: `docs/handoff/2026-08-06_servc_diagnosis_handoff.md`에 기각 5건, 알아 둘 사실 3건, 미검증 후보 2건, 판정 규칙 2건을 정리했습니다
- **검증**: 전체 테스트 736 passed 2 skipped, `validate_agent_rules.py` 6/6 통과

---

### 2026-08-06 | 용역 측정 | 예측 구간의 집단별 품질 확인

- **작업자**: 관범 & Claude
- **가설**: 산포가 두 배 다른 하한율 보유·결측 집단에 같은 구간을 주고 있어 한쪽은 좁고 한쪽은 넓을 것이라 보았습니다
- **반증**: 구간 폭 중앙값이 보유 1.2160%p 대 결측 8.4751%p로 이미 7배 반응합니다. 보유 집단 피복률은 89.99%로 명목 90%와 일치합니다
- **다중 비교 보정**: 13개 집단 검정에서 |t| > 2가 다섯이었으나 Bonferroni 임계 2.90을 넘는 항목이 없습니다(최대 2.66). 이 표본으로는 구간이 집단별로 어긋난다고 말할 수 없습니다
- **후속 조치 없음**: 모델도 구간 산출도 바꾸지 않았습니다. 세그먼트별 등각 배율 기각을 뒤집을 근거는 만들어지지 않았습니다
- **정합성 확인**: 전체 MAE 1.4471, 0.5%p 적중 64.02%, 구간 폭 1.7286%p, 피복률 89.40%로 기준선과 전 항목 일치
- **문서**: `docs/design/servc_interval_by_group_20260806.md` 작성, 인수인계 4.1의 미확인 항목을 측정 결과로 대체했습니다

---

### 2026-08-06 | RAG | 임베딩 한국어 대응 교체 (MiniLM -> bge-m3)

- **작업자**: 관범 & Claude
- **발단**: KB 커버리지 확대(50만 건, 4.8시간) 착수 전 1만 건 소규모 실측에서 검색 품질을 먼저 확인했습니다
- **문제**: 정답을 아는 질의 100건에서 top-5 적중률이 4.0%, 정답 순위 중앙값 9위였습니다. 문서 간 유사도 0.9 이상이 60.5%로 서로 구분되지 않았습니다
- **원인**: ChromaDB 기본 `all-MiniLM-L6-v2` 가 영어 전용입니다. 같은 모델로 무관한 주제를 비교하면 영어는 0.13~0.31인데 한국어는 0.81~0.83으로 붙습니다. 문서 템플릿이 아니라 모델이 원인입니다
- **교체 결과**: bge-m3 로 top-5 100.0%, top-1 89.0%, 정답 순위 중앙값 1위, 문서 간 유사도 0.9 이상 0.1%
- **비용**: 적재가 오히려 1.6배 빠릅니다(1만 건 345.5초 -> 213.6초). Ollama 가 Metal GPU 를 쓰고 기존 ONNX 는 CPU 라 그렇습니다. 디스크는 1.55배(50만 건 추정 2.25GB -> 3.49GB). 새 파이썬 의존성 없음
- **제약 재검토**: "임베딩 교체 금지" 근거였던 19개 컬렉션은 현재 1개이며 이미 재구축된 파생물입니다. 원본 10건은 `data/backups/chroma_source` 스냅샷에 별도 보존되어 G1 영향이 없습니다
- **배선**: `src/rag/embeddings.py` 단일 진입점 신설. 색인(`kb_builder`)·질의(`vector_store`)·검증 프로브(`verify_migration`)가 모두 이것만 씁니다. 어긋나면 예외 없이 결과만 엉망이 되므로 테스트로 고정했습니다
- **부수 발견**: `read_chroma_stats` 가 `embeddings` 테이블을 통째로 세어 삭제된 컬렉션의 고아 레코드까지 잡고 있었습니다. 컬렉션 500건인데 1,500건으로 보고되던 것을 세그먼트 조인으로 고쳤습니다
- **검증 결과**: 운영 재색인 500건/20.3초, 신설 테스트 10건 포함 747 passed / 2 skipped, `verify_migration.py` 4/4 통과. 교체 직후 차원 불일치(1024 대 384)를 검증이 실패로 잡아낸 뒤 재색인으로 통과했습니다
- **되돌리기**: `EMBEDDING_PROVIDER=default` 후 `rebuild_knowledge_base(db, full=True)` 한 번
- **문서**: `docs/design/rag_embedding_korean_20260806.md`

---

### 2026-08-07 | 용역 진단 | 오차 집중 구조 분해와 겨냥 대상 확정

- **작업자**: 관범 & Claude
- **잔차 재확보**: `diagnose_servc_lwlt_residuals.py --dump-dir`의 덤프가 컬럼 12개만 남기고 있어 전량 저장으로 고쳤습니다. 재발주·용역구분·계약방법이 빠져 있어 축을 늘릴 때마다 35분 재실행이 필요했습니다
- **지표 전환**: MAE 대신 오차 총량 기여도와 설명력(1 - 모델 MAE / 셀 중앙값 예측 MAE)을 씁니다
- **오차 집중**: 상위 10% 건이 오차 총량의 54.6~55.2%를 차지하며 2023~2026년 네 해가 소수점 첫째 자리까지 동일합니다
- **3원 교차**: 용역구분 x 하한율 x 기관 이력 깊이가 독립적으로 작동해 최선 셀 0.413, 최악 셀 3.506으로 8.5배 벌어집니다
- **핵심 발견**: MAE 최악 셀(일반용역/결측/얕음 3.506)과 설명력 최하위 셀(일반용역/보유/얕음 0.201)이 서로 다릅니다. MAE로 겨냥하면 이미 잘 다루는 셀을 고릅니다
- **겨냥 대상**: 일반용역 x 얕은 이력(<50건) 두 셀. 2026년 10,696건(19.0%), 개선 상한 전체 MAE의 6.1~8.3%
- **기각**: 금액대와 재발주 여부는 집중 배수가 4년 내내 1 근처로 오차를 가르지 못합니다. 기술용역/결측 셀은 이력 깊이 효과의 부호가 세 해 반대였습니다
- **자체 가설 기각**: 기술용역이 잘 맞는 이유를 제도 배점 특징으로 설명하려 했으나 `tech_ablt_evl_rt` 보유율이 기술 0.2% 대 일반 3.4%로 반대였습니다. 원인 미상으로 남깁니다
- **승격 없음**: 재학습하지 않았습니다. Servc 서빙은 `v_20260806_025423_494` 그대로입니다

---

### 2026-08-07 | 용역 진단 | 일반용역 얕은이력 셀은 현재 특징으로 도달 불가

- **작업자**: 관범 & Claude
- **잔여 수치 신호 없음**: 셀 안 잔차와 14개 수치 특징의 스피어만 상관 최댓값이 0.105입니다. n=5,039에서 유의하지만 효과 크기가 무의미합니다
- **모델은 포기하지 않음**: 예측 표준편차 / 실제 표준편차가 일반용역 얕은이력에서 0.55~0.61입니다. 정보가 거기까지인 것이며 중심으로 도망간 것이 아닙니다
- **소분류 잔여 신호 기각**: 소분류별 평균 잔차의 연도 간 상관 0.803, 부호 일치 85.7%로 재현성이 매우 높은데도 오라클 오프셋이 MAE를 0.1525 악화시켰습니다. 왜도와 편향의 부호가 일반용역 네 셀 전부에서 반대였습니다
- **근본 원인 규명**: 일반용역은 하한율이 있어도 낙찰률을 결정하지 못합니다. 실제-하한율 표준편차가 기술용역 1.3~1.7 대 일반용역 4.3~5.4입니다. 전날 세운 제도 배점 가설이 아니라 하한율의 결정력 차이였습니다
- **결론**: 겨냥할 곳은 맞았으나 개선 상한 6.1~8.3%는 현재 특징 집합으로 열리지 않습니다. 남는 선택지는 전부 외부 정보 확보입니다
- **승격 없음**: 재학습하지 않았습니다. Servc 서빙은 `v_20260806_025423_494` 그대로입니다
- **문서**: `docs/design/servc_general_service_signal_20260807.md` 작성, 스킬 기각 2행과 "재현성 확인을 오라클보다 먼저 하지 말 것" 규칙을 추가했습니다

---

### 2026-08-07 | 용역 실험 | 손실함수 탐색에서 quantile(0.5) 우세 확인

- **작업자**: 관범 & Claude
- **미탐색 축 발견**: 하이퍼파라미터 좌표 하강 17회에 손실함수가 없었습니다. `objective="huber", alpha=1.0`이 고정된 채 한 번도 재본 적이 없었습니다
- **설계**: 학습 2025년까지 861,291행, 평가 2026년 56,338행. Huber alpha 0.2/0.5/1.0/2.0/5.0과 quantile(0.5)을 동일 조건으로 비교했습니다
- **결과**: quantile(0.5)이 MAE 1.3554 -> 1.3312(1.8% 개선), 0.5%p 적중 58.53% -> 59.65%입니다. 쌍대 검정 7개 모집단에서 6개 우세, 1개 판별 불가, 악화 0개이며 관측 차이가 최소 감지 차이의 7.5배입니다
- **huber alpha=0.5 기각**: 전체는 우세하나 기관 이력 얕은 12,339건에서 t=2.69로 악화해 재분배 요소가 있습니다
- **대가 기록**: RMSE가 2.7454 -> 2.7834로 나빠집니다. L1 최적화의 전형적 맞바꿈입니다
- **구현 주의**: `_train_lightgbm`은 물품도 함께 쓰므로 카테고리별 분기가 필요합니다. `_conformal_scale`은 분위 모델 자체 중심을 쓰므로 예측 구간 보정에는 영향이 없음을 코드로 확인했습니다
- **승격 없음**: 운영 경로 쌍대 검정 전입니다. Servc 서빙은 `v_20260806_025423_494` 그대로입니다
- **잔차 영구화**: 재생성에 35분 걸리는 잔차 parquet을 `data/analysis/servc_residuals/`(gitignore 적용)로 옮겼습니다
- **문서**: `docs/design/servc_loss_function_20260807.md` 작성, 스킬에 채택 대기 후보 절을 추가했습니다

---

### 2026-08-07 | 용역 승격 | 손실함수 quantile(0.5) 운영 검증 후 승격

- **작업자**: 관범 & Claude
- **구현**: `trainer._train_lightgbm` 을 직접 고치지 않고 `CATEGORY_HYPERPARAMS["Servc"]["lightgbm"]` 에 `objective="quantile", alpha=0.5` 를 더했습니다. 물품(Thng)은 `hyperparams_for_category` 가 빈 dict 를 반환해 huber(1.0)를 유지하며, `_train_quantile_models` 는 hyperparams 인자를 받지 않아 분위 모델(q10 alpha=0.1/63리프)도 그대로입니다
- **재학습**: 917,629행 589초. 모델 선택은 MAPE 기준으로 LightGBM 을 유지했습니다. MAPE 1.4207 -> 1.3874
- **운영 쌍대 검정 통과**: 2025년 8,995건에서 MAE 1.4159 -> 1.4050, 쌍대 t=-2.89 로 challenger 우세입니다. 0.5%p 적중 64.19% -> 64.97%
- **RMSE 악화 없음**: 홀드아웃에서 1.4% 악화해 "L1 의 대가" 로 기록했으나 운영 제곱오차 쌍대 t 는 0.25 로 판별 불가입니다. 대가를 치르지 않았습니다
- **구간 불변 실측 확인**: 등각 배율 1.151263 양쪽 동일, 운영 구간 폭 1.6706 과 피복률 89.56% 가 소수점까지 일치합니다
- **집단별 회귀 검정 신설**: `scripts/compare_servc_models_by_group.py` 를 만들었습니다. 하한율·용역구분·기관이력 세 축을 분해하고 판정은 개수가 아니라 비중으로 합산하며 다중 검정이므로 t 임계값을 본페로니 보정으로 2.64 로 올립니다. scipy 가 선언된 의존성이 아니라 `statistics.NormalDist` 로 구현했습니다
- **두 해 대조**: 전체 쌍대는 2025년 t=-2.89, 2026년 t=-2.92 로 재현됩니다. 보정 임계값을 넘긴 악화 집단은 2026년 0개, 2025년 1개(하한율 결측)입니다
- **하한율 결측 집단의 약한 악화 기록**: 두 해 모두 부호가 악화 방향입니다(+0.0400 t=4.20 / +0.0244 t=2.57). 이 집단은 낙찰률 IQR 이 9.682 로 보유 집단 0.705 의 14배라 중앙값 겨냥이 불리합니다. 악화는 상위 1.9% 건에 몰려 있어 그 50건을 빼면 +0.0400 이 +0.0083 으로 줄고, 0.5%p 적중은 이 집단에서도 +1.13%p 오릅니다
- **승격**: `v_20260806_025423_494` -> `v_20260807_043210_535`. 롤백 대상은 직전 버전입니다
- **검증**: 전체 테스트 748 passed 2 skipped, `validate_agent_rules.py` 6/6
- **문서**: `docs/design/servc_loss_function_20260807.md` 에 8장 추가, 스킬의 채택 대기 후보를 채택 완료로 옮겼습니다

---

### 2026-08-07 | 용역 진단 | 하한율 결측 집단은 개선 대상이 아님

- **작업자**: 관범 & Claude
- **배경**: quantile(0.5) 승격에서 이 집단만 두 해 모두 약한 악화 방향이라 다음 축으로 지목했습니다
- **설명력 동등**: 난이도로 정규화하면 결측 0.377~0.437, 보유 0.409~0.446 으로 차이가 없습니다. MAE 가 2.55 대 0.77 로 3배인 것은 못해서가 아니라 어려워서입니다. MAE 로 겨냥할 집단을 고르면 안 되는 사례가 다시 확인됐습니다
- **잔여 신호 없음**: 2025년 결측 집단에서 잔차와 수치 특징의 최대 상관이 `repeat_prev_rate` 0.0759 입니다. 일반용역 얕은이력 셀을 닫을 때의 0.105 보다 낮습니다
- **내부 최약 셀은 이미 닫힌 갈래**: 제한경쟁 설명력이 0.113~0.176 으로 유일하게 낮으나 `servc_restricted_competition_20260803.md` 에서 세 갈래 시도가 모두 실패했습니다. 잔차를 가르는 참여업체 수는 공고 시점에 알 수 없습니다
- **결론**: 겨냥할 신호가 없어 닫습니다. quantile 승격의 약한 악화는 되돌릴 수단이 없으며 전체 순증이 상쇄하는 구조를 수용합니다
- **승격 없음**: 재학습하지 않았습니다. Servc 서빙은 `v_20260807_043210_535` 그대로입니다
- **문서**: `servc_loss_function_20260807.md` 8.7 절을 진단 결과로 교체, 스킬 기각 목록에 1행 추가했습니다

---

### 2026-08-07 | 용역 기각 | quantile 아래 하이퍼파라미터 재탐색

- **작업자**: 관범 & Claude
- **배경**: `num_leaves=255` 를 비롯한 현행 값이 전부 huber 아래에서 고른 값이라, 목적함수를 quantile(0.5)로 바꾼 뒤 최적점이 이동했는지 미측정 상태였습니다
- **탐색 시작점 수정**: `tune_servc_hyperparams.py` 가 `LGB_BASE_PARAMS`(리프 63)에서 출발해 용역 운영값 255 와 어긋나 있었습니다. 시작점과 목적함수를 모두 `CATEGORY_HYPERPARAMS` 에서 읽도록 고쳐 운영 설정 변경을 자동으로 따라가게 했습니다
- **용량 최적점은 이동하지 않았습니다**: 두 목적함수 모두 31 < 63 < 127 < 255 > 511 로 순서가 같고 255 에서 최소입니다. 511 은 MAE 1.2560 으로 나쁘고 0.5%p 적중은 61.49% 로 더 떨어집니다. 용량은 손실함수가 아니라 범주 조합 구조가 정합니다. 이 탐색의 출발 가설이 반증됐습니다
- **좌표 하강 21회**: `min_child_samples` 160 / `learning_rate` 0.03 / `n_estimators` 2000 / `subsample_freq` 5 조합에서 MAE 1.2554 -> 1.2519 입니다. 축별 기여는 0.0004~0.0025 로 지난 huber 탐색의 `num_leaves` 하나(0.0177)와 자릿수가 다릅니다
- **시드 재현성 검정 신설**: `scripts/measure_servc_tuning_noise.py` 를 만들었습니다. 좌표 하강은 축마다 최선을 고르는 절차라 실제 이득이 0 이어도 홀드아웃이 내려갑니다. 같은 설정의 시드 간 MAE 폭이 0.0016 이라 단일 시드 비교에서 0.001 단위는 읽을 수 없습니다
- **판정 실체 있음**: 시드 42/1/7 쌍대 차이가 -0.0035 / -0.0037 / -0.0038 로 부호뿐 아니라 크기까지 일치합니다. 평균 -0.0037 은 시드 표준편차 0.0008 의 4.6배입니다. 판정 기준은 결과를 보기 전에 고정했습니다
- **조기 종료 경로 불일치 기록**: 운영 `_train_lightgbm` 은 `early_stopping(10)` 을 걸지만 탐색 스크립트는 걸지 않습니다. `n_estimators=2000` 은 운영에서 상한으로만 작동하므로 탐색 이득이 그대로 옮겨진다고 볼 수 없습니다
- **재학습**: 917,629행 677초, 모델 선택은 LightGBM 유지입니다. `v_20260807_110637_435` 로 등록했고 R2 0.6839 -> 0.6842, MAPE 1.3874 -> 1.3862 로 개선 폭이 홀드아웃 예상치보다 훨씬 작았습니다. 이 시점에 이미 조짐이 보였습니다
- **운영 쌍대 검정 기각**: 2025년 8,995건에서 MAE 1.4050 -> 1.4188, t=5.14 로 base 우세입니다. 6개 집단 전부 base 우세이거나 판별 불가이며 challenger 우세 비중은 세 축 모두 0.0 입니다. 홀드아웃 -0.0037 이 운영에서 +0.0139 로 부호까지 뒤집혔습니다
- **원인은 조기 종료 불일치**: `_train_lightgbm` 은 `early_stopping(10)` 을 걸고 탐색 스크립트는 걸지 않습니다. 낮춘 학습률은 더 많은 트리로 보상해야 하는데 탐색에서는 2000 그루가 보상했고 운영에서는 조기 종료가 그 전에 잘랐습니다. 운영 모델이 덜 학습된 모델이 됐습니다
- **시드 검정의 한계 확인**: 시드 재현성 검정은 좌표 하강의 선택 편향을 걸러내도록 설계했고 그 역할은 했습니다. 홀드아웃 이득 자체는 진짜였습니다. 그러나 탐색 경로 안에서만 이뤄지므로 탐색과 학습 경로가 다르면 재현성이 높아도 옮겨지지 않습니다
- **되돌림**: `CATEGORY_HYPERPARAMS` 에서 네 키를 제거하고 `num_leaves` / `objective` / `alpha` 만 남겼습니다. Servc 서빙은 `v_20260807_043210_535` 그대로이며 승격하지 않았습니다
- **레지스트리 주의 기록**: `promote_model.py status` 가 `v_20260807_110637_435` 를 "승격 조건 통과" 로 표시하지만 학습기 지표만 본 판정입니다. 운영 쌍대에서 기각됐으므로 승격하면 안 됩니다
- **문서**: `docs/design/servc_hyperparam_quantile_20260807.md` 신설, 인수인계 2장을 기각 요약으로 교체하고 순위를 재배열, 스킬 기각 목록에 1행과 조기 종료 불일치 지침을 추가했습니다
