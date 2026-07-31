# refac_bid_box — Agent Guidelines (정본)

> **작성일**: 2026-07-31
> **버전**: v0.1.0
> 본 파일은 모든 AI 코딩 에이전트가 공유하는 **단일 진실 원천(Single Source of Truth)** 입니다.
> 규칙을 편집할 때는 반드시 이 파일만 수정합니다. 상세한 다중 에이전트 매핑은 [`docs/ops/multi_agent_setup.md`](docs/ops/multi_agent_setup.md)를 참조하십시오.

@SKILLS.md

---

## 0. 스킬 시스템 구축 현황 (완료)

**5개 CLI 동기화 다중 에이전트 스킬 시스템 구축이 완료되었습니다.**

- **인수인계 문서**: [`docs/handoff/2026-07-31_skill_system_handoff.md`](docs/handoff/2026-07-31_skill_system_handoff.md)
- **정합성 검증 스크립트**: [`scripts/validate_agent_rules.py`](scripts/validate_agent_rules.py)
- **작업 완료**: Phase 0~7 대응 8개 스킬 구축 (`.agents/skills/`, `.claude/skills/`, `.opencode/skills/`, `.cursor/rules/`, `.antigravity/rules.md`)

---

## 1. 프로젝트 개요

refac_bid_box는 기존 `bid_box`(Django 5.1.6 모놀리식)를 리팩토링하는 저장소입니다. 공공조달 입찰 데이터 수집·분석, 하이브리드 RAG 챗봇, AI 낙찰가 예측, 재학습 MLOps를 통합합니다.

**3대 리팩토링 목표:**

| 목표 | 핵심 |
| --- | --- |
| G1. 데이터 무손실 | DB 행 수·스키마 100% 보존, 모델 가중치·벡터DB 무결성 |
| G2. 크로스 플랫폼 | macOS/Windows 동일 환경 (Docker + Makefile) |
| G3. 스택 최적화 | 레이턴시·정합성 개선, 비동기화, train/serve skew 해결 |

---

## 2. 기술 스택 (확정)

| 영역 | 기술 | 비고 |
| --- | --- | --- |
| 백엔드 | FastAPI (ASGI) | 비동기 I/O, Pydantic v2, Swagger 자동화 |
| DB | MySQL 8 (Docker) | 이중화(SQLite fallback) 제거, 스키마 100% 보존 |
| 캐시/브로커 | Redis | 파일/locmem 캐시 대체 |
| 태스크 큐 | Arq (asyncio + Redis) | 경량 비동기 태스크 큐 |
| ML | LightGBM, CatBoost, scikit-learn | 기존 스택 유지 |
| 벡터DB | ChromaDB (유지) | 19개 컬렉션 데이터 보존 최우선 (G1) |
| LLM | Google Gemini | 의도 분류, 요약, RAG |
| 패키지 관리 | uv + pyproject.toml | pip 대체 |
| 컨테이너 | Docker + docker-compose | 크로스 플랫폼 표준 (G2) |


---

## 3. 코딩 규칙

1. **언어**: 대화 응답과 아티팩트는 한국어(존댓말). 코드/변수명/환경변수명은 영어.
2. **이모지 금지**: 코드 주석, 커밋 메시지, 문서에 이모지 사용 불가.
3. **경로**: 파일 참조는 항상 **프로젝트 루트 기준** 상대 경로로 작성.
4. **의존성**: 새 라이브러리 추가 전 반드시 사전 합의. `pyproject.toml`에 기록.
5. **데이터 보존**: 기존 DB 테이블명·컬럼명·타입 변경 금지.
6. **특징 단일화**: 학습·추론 특징 생성은 `src/ml/features.py` 단일 함수만 사용.
7. **간결한 코드**: 불필요한 주석 회피, 코드가 의도를 드러내도록 작성.

---

## 4. 커뮤니케이션 규칙

- 응답은 한국어 존댓말로 작성.
- 복잡한 변경이나 설계 결정은 사전에 제안하고 합의 후 진행.
- 파일 경로는 `file_path:line_number` 형식으로 참조 (클릭 가능).

---

## 5. Git 규칙

- `main` 브랜치에 직접 push 금지. 항상 브랜치 → PR.
- 커밋 메시지: `type: subject` 형식 (예: `feat: add retraining trainer`).
  - type: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`
- 상세는 [`docs/ops/git_branching_strategy.md`](docs/ops/git_branching_strategy.md).

---

## 6. 금지 행위 (절대)

1. 코드 주석, 커밋 메시지, 문서 내 이모지 사용
2. 영어로 대화 응답이나 아티팩트 작성 (코드/변수명 제외)
3. 사전 허가 없이 새로운 Python 라이브러리 추가
4. `.env` 파일의 실제 값을 코드나 문서에 노출
5. 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반)
6. 학습·추론 특징 생성 로직을 분리하여 작성 (train/serve skew 유발)
7. `main` 브랜치에 직접 push
8. 마이그레이션 검증 없이 다음 Phase 진행

---

## 7. 문서화 표준

마크다운 위계(`#`/`##`/`###`), 구분선(`---`), 표 우선, Mermaid 다이어그램, 메타데이터 블록(`>`)을 준수합니다. 상세는 [`SKILLS.md`](SKILLS.md)의 DOCUMENTATION & FORMATTING RULES 섹션을 참조하십시오.

---

## 8. 스킬 인덱스 (Phase 0~7)

| 스킬명 | Phase | globs / 경로 | 핵심 기능 |
| --- | --- | --- | --- |
| `foundation-setup` | Phase 0 | `.agents/skills/foundation-setup/` | uv, Makefile, Docker, CI, 린터 설정 |
| `data-preservation` | Phase 1 | `.agents/skills/data-preservation/` | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| `infrastructure-setup` | Phase 2 | `.agents/skills/infrastructure-setup/` | DB ORM 이식, Redis 캐시, 비동기 태스크 큐 |
| `application-migration` | Phase 3 | `.agents/skills/application-migration/` | 백엔드 API 이식, 거대 모듈 분할, async/await |
| `inference-rag-opt` | Phase 4 | `.agents/skills/inference-rag-opt/` | 싱글톤 로드, 가중치 외부화, RAG 캐싱 |
| `retraining-pipeline` | Phase 5 | `.agents/skills/retraining-pipeline/` | 단일 특징 features.py, trainer, ml_registry, PSI 모니터링 |
| `frontend-streaming` | Phase 6 | `.agents/skills/frontend-streaming/` | SSE/WebSocket 스트리밍, HTMX 동적 UI |
| `validation-cutover` | Phase 7 | `.agents/skills/validation-cutover/` | E2E, P95 레이턴시 벤치마크, 크로스플랫폼 컷오버 |
| `git-workflow` | 공통 | `.agents/skills/git-workflow/` | 커밋 메시지 컨벤션, pre-commit 검증, main push 금지, PR 워크플로우 |


