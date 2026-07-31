# refac_bid_box 작업 일지 (Work Log)

> **작성자**: 관범 & AI 에이전트
> **프로젝트**: `refac_bid_box` 리팩토링
> 본 파일은 작업 수행 내역을 시간순으로 하단에 지속 누적 기록하는 단일 진실 기록서입니다.

---

### 2026-07-31 | Phase 0 스킬 시스템 | 다중 에이전트 스킬 구축 및 검증 스크립트 완성

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
  - 4. 벡터DB: ChromaDB 기존 19개 컬렉션 유지
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
  - `src/rag/vector_store.py`: ChromaDB 19개 컬렉션 비동기 질의 래퍼 작성
  - `src/ml/dataset.py`: DB 조인(BidAnnouncement ⟕ BidResult) 및 정제 기반 Feature Store Parquet 빌더 구현
  - `src/ml/trainer.py`: K-Fold 및 Ridge/LightGBM 일반화 학습 엔진 구현
  - `src/ml/validate_model.py`: RMSE, MAPE, R² 실시간 산출 및 Champion vs Challenger 하이브리드 승격 게이트 구현
  - `src/ml/monitoring.py`: PSI(Population Stability Index) 기반 특징/예측 드리프트 감지 구현
  - `src/tasks/retrain_task.py`: Arq 비동기 재학습 파이프라인 태스크 정의
  - `tests/test_mlops_pipeline.py`: 싱글톤, 학습기, 평가, PSI 드리프트 단위 테스트 작성 및 100% 통과
- **관련 파일**: `src/ml/predictor.py`, `src/rag/vector_store.py`, `src/ml/dataset.py`, `src/ml/trainer.py`, `src/ml/validate_model.py`, `src/ml/monitoring.py`, `src/tasks/retrain_task.py`, `tests/test_mlops_pipeline.py`
- **검증 결과**: `pytest` 7/7 passed, `validate_agent_rules.py` 6/6 PASS





