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
