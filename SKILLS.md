# refac_bid_box AI Agent Skills

## MANDATORY STARTUP SEQUENCE

이 프로젝트에서 작업을 시작하기 전, 아래 순서를 **반드시** 따르십시오.
건너뛰거나 생략하는 것은 허용되지 않습니다.

---

### Step 1: README 읽기

**파일:** [`README.md`](README.md)

README를 처음부터 끝까지 읽고 다음을 파악합니다:

- 프로젝트 목적 및 핵심 기능 (공공조달 입찰 수집·분석, RAG 챗봇, AI 낙찰가 예측, 재학습 MLOps)
- 3대 리팩토링 목표 (데이터 무손실, 크로스 플랫폼, 스택 최적화)
- 기술 스택 및 디렉토리 구조
- 빠른 시작 및 환경 변수

> README는 프로젝트의 **기준선(baseline)** 역할을 합니다. 모든 작업은 이 기준선을 확인한 뒤 시작합니다.

---

### Step 2: 리팩토링 설계서 읽기

**파일:** [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md)

설계서를 읽고 다음을 숙지합니다:

- AS-IS 시스템 분석과 핵심 문제점 (동기 WSGI 병목, DB 이중화, train/serve skew)
- TO-BE 기술 스택 및 근거
- 데이터 무손실 마이그레이션 절차 (5장)
- **재학습 파이프라인 설계 (7장)** — 핵심 추가 영역
- 이행 로드맵 Phase 0~7 (8장)

---

### Step 3: AGENTS.md 읽기

**파일:** [`AGENTS.md`](AGENTS.md)

AGENTS.md를 읽고 다음을 숙지합니다:

- 기술 스택 (FastAPI/Django ASGI, MySQL, Redis, Celery/Arq, LightGBM/CatBoost, ChromaDB)
- 코딩 규칙 (한국어 응답, 이모지 금지, 프로젝트 루트 기준 경로)
- 커뮤니케이션 규칙
- 문서화 표준 (Markdown, Mermaid, 표 우선)

---

### Step 4: 작업 유형별 추가 문서 참조

작업 유형에 따라 아래 문서를 추가로 읽습니다:

| 작업 유형 | 참조 문서 |
| --- | --- |
| 데이터 마이그레이션 | [`docs/migration/db_migration_runbook.md`](docs/migration/db_migration_runbook.md) |
| ML 가중치·ChromaDB 보존 | [`docs/migration/ml_weights_verification.md`](docs/migration/ml_weights_verification.md) |
| 재학습 파이프라인 구현 | [`docs/phase-guides/phase5_retraining_design.md`](docs/phase-guides/phase5_retraining_design.md) |
| 환경 변수 | [`docs/ops/environment_variables.md`](docs/ops/environment_variables.md) |
| 크로스 플랫폼 대응 | [`docs/ops/cross_platform_guide.md`](docs/ops/cross_platform_guide.md) |
| 브랜치/PR 작업 | [`docs/ops/git_branching_strategy.md`](docs/ops/git_branching_strategy.md) |
| 문서 전체 인덱스 | [`docs/README.md`](docs/README.md) |
| 백엔드 결정 (FastAPI vs Django) | [`docs/research/backend_framework_comparison.md`](docs/research/backend_framework_comparison.md) |

단계별 구현 작업은 아래 SKILL 인덱스를 참조합니다.

---

## 담당자 학습형 협업 규칙

refac_bid_box는 최종 프로젝트로, 결과물뿐 아니라 담당자의 발표와 학습이 중요합니다. LLM 에이전트는 모든 코드를 혼자 완성하지 않고, 담당자가 직접 이해하고 설명해야 하는 핵심 로직과 LLM이 맡을 연결·검증 작업을 분리해야 합니다.

| 구분 | 담당자 직접 작성 | LLM 보조 작성 |
| --- | --- | --- |
| **핵심 로직** | 특징 엔지니어링(inst_hist_rate, 임베딩), 모델 학습/평가, 낙찰가 예측 규칙, RAG 검색 로직 | 타입 정리, 예외 처리, 기존 모듈 연결 |
| **데이터 파이프라인** | DB join 설계, 정제 기준, 데이터 품질 판단 | bulk insert, parquet I/O, 스크립트 자동화 |
| **실행/검증** | 마이그레이션 결과 해석, 모델 성능 평가, 발표용 로그 확인 | 테스트 자동화, 실패 원인 분석, 보고서 정리 |

핵심 판단 로직은 20~40줄 이하 단위로 나누어 담당자가 직접 입력할 기회를 먼저 제공합니다.

---

## SKILL 인덱스

각 스킬은 이행 단계별 구현 가이드입니다. 작업 시작 시 해당 단계의 `phase-guides/phaseN_*.md`를 먼저 읽습니다.

| 스킬 | Phase | 경로 | 설명 |
| --- | --- | --- | --- |
| `foundation-setup` | 0 | `docs/phase-guides/phase0_foundation_design.md` | uv, Makefile, Dockerfile, CI, 린터 |
| `data-preservation` | 1 | `docs/phase-guides/phase1_data_preservation_design.md` | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| `infrastructure` | 2 | `docs/phase-guides/phase2_infrastructure_design.md` | ORM 이식, Redis, 태스크 큐 |
| `application-migration` | 3 | `docs/phase-guides/phase3_application_design.md` | 백엔드 이식, 거대 파일 분할, 비동기화 |
| `inference-rag-opt` | 4 | `docs/phase-guides/phase4_inference_rag_design.md` | 싱글톤 로드, 가중치 외부화, RAG 비동기 |
| **`retraining-pipeline`** | **5** | `docs/phase-guides/phase5_retraining_design.md` | **특징 함수, 데이터셋 빌더, 학습기, 레지스트리, 모니터링** |
| `frontend-streaming` | 6 | `docs/phase-guides/phase6_frontend_design.md` | SSE/WebSocket, HTMX (선택) |
| `validation-cutover` | 7 | `docs/phase-guides/phase7_validation_cutover_design.md` | E2E, 벤치마크, 크로스플랫폼 검증 |

---

## CORE PROJECT CONTEXT

refac_bid_box는 **공공조달(G2B/나라장터) 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 + 재학습 MLOps 플랫폼**입니다.

핵심 구조:

| 계층 | 역할 |
| --- | --- |
| `src/app/` | 백엔드 애플리케이션 (FastAPI/Django ASGI) — bids/chatbot/predictions/accounts API |
| `src/ml/` | ML 도메인 — 싱글톤 모델 로드, 통합 특징 함수, 학습기, 레지스트리 |
| `src/tasks/` | 비동기 태스크 (Celery/Arq) — G2B 수집, 재학습, KB 업데이트 |
| `src/rag/` | RAG 엔진 — ChromaDB/Qdrant 검색 + Gemini |
| `migrations/` | DB 마이그레이션 (기존 19개 히스토리 보존) |
| `docker/` | Docker 구성 — MySQL + Redis + app + worker |

비협상 원칙 (non-negotiable):

- **데이터 무손실**: 기존 DB 행 수·스키마 100% 보존. 컬럼 타입 변경 금지.
- **Train/Serve 특징 단일화**: 학습·추론 특징 생성은 단일 함수(`features.py`)만 사용. 하드코딩 상수(`DEFAULT_INST_RATE` 등) 제거.
- **크로스 플랫폼**: macOS/Windows 모두 Docker + Makefile로 동일 환경. 플랫폼 종속 바이너리(`hc.exe`) Git 제거.
- **재학습 게이트**: 신규 모델은 champion을 성능으로 압도할 때만 승격. 즉시 롤백 가능.

---

## DOCUMENTATION & FORMATTING RULES

프로젝트 내 모든 문서(Markdown 등)를 작성하거나 수정할 때, 다음 규칙을 엄격히 준수합니다.

1. **언어 및 어조**
   - 설명은 **한국어(존댓말/경어체)** 로 작성합니다. (코드 블록, 변수명, 환경변수명은 예외)
   - 문장은 간결하고 전문적인 용어를 사용합니다.

2. **문서 구조 및 마크다운**
   - 제목은 `#`, 섹션은 `##`, 하위 섹션은 `###`을 사용합니다.
   - 주요 섹션 사이에는 구분선(`---`)을 삽입합니다.
   - 비교 데이터, 설정값, 매핑 등은 **표(Table)** 를 우선 사용합니다.
   - 핵심 개념, 버전, 수치는 굵게(`**텍스트**`) 처리합니다.

3. **다이어그램 (Mermaid)**
   - 아키텍처, 타임라인, 프로세스 설명 시 `mermaid` 코드 블록을 적극 활용합니다.
   - 노드 텍스트에 공백/특수문자가 포함될 경우 큰따옴표(`"텍스트"`)로 감쌉니다.
   - 긴 텍스트는 `<br/>` 태그로 줄바꿈합니다.

4. **메타데이터 패턴**
   - 새 문서 상단에 작성일/버전/상태를 인용 블록(`>`)으로 명시합니다.
   - 예: `> **작성일**: 2026-07-31`

5. **금지 사항**
   - 문서 내 **이모지(Emoji)** 사용은 어떤 경우에도 허용되지 않습니다.

---

## PROHIBITED ACTIONS

다음 행위는 **절대 금지**입니다:

1. 코드 주석, 커밋 메시지, 문서 내 이모지 사용
2. 영어로 대화 응답이나 아티팩트 작성 (코드/변수명 제외)
3. 사전 허가 없이 새로운 Python 라이브러리 추가 (`pyproject.toml` 변경)
4. `.env` 파일의 실제 값을 코드나 문서에 노출
5. 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반)
6. 학습·추론 특징 생성 로직을 분리하여 작성 (train/serve skew 유발)
7. `main` 브랜치에 직접 push
8. 마이그레이션 검증 없이 다음 Phase 진행

---

## WORKFLOW CHECKLIST

세션 시작 시 다음을 확인합니다:

- [ ] `README.md` 읽기 완료
- [ ] `docs/design/REFACTORING_DESIGN.md` 읽기 완료
- [ ] `AGENTS.md` 읽기 완료
- [ ] 작업 유형에 맞는 추가 문서 참조 완료
- [ ] 현재 Phase와 진행 상황 확인 (`docs/changelogs/`)
- [ ] 데이터 무손실 영향 여부 확인 (DB/가중치/ChromaDB 접근 시)
- [ ] macOS/Windows 호환성 영향 여부 확인
