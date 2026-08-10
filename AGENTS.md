# refac_bid_box — Agent Guidelines (정본)

> **작성일**: 2026-07-31
> **버전**: v0.1.0
> 본 파일은 모든 AI 코딩 에이전트가 공유하는 **단일 진실 원천(Single Source of Truth)** 입니다.
> 규칙을 편집할 때는 반드시 이 파일만 수정합니다. 상세한 다중 에이전트 매핑은 [`docs/ops/multi_agent_setup.md`](docs/ops/multi_agent_setup.md)를 참조하십시오.

@SKILLS.md

---

## 0. 스킬 시스템 구축 현황 (완료)

**5개 CLI 동기화 다중 에이전트 스킬 시스템과 Orca 섹션 조율 규약이 구축되었습니다.**

- **인수인계 문서**: [`docs/handoff/2026-07-31_skill_system_handoff.md`](docs/handoff/2026-07-31_skill_system_handoff.md)
- **정합성 검증 스크립트**: [`scripts/validate_agent_rules.py`](scripts/validate_agent_rules.py)
- **작업 완료**: Phase 0~7 대응 스킬·상시 스킬 및 Orca 섹션 조율 스킬 합계 **12개** 구축 (`.agents/skills/`, `.claude/skills/`, `.opencode/skills/`, `.cursor/rules/`, `.antigravity/rules.md`)

---

## 1. 프로젝트 개요

refac_bid_box는 기존 `bid_box`(Django 5.1.6 모놀리식)를 리팩토링하는 저장소입니다. 공공조달 입찰 데이터 수집·분석, 하이브리드 RAG 챗봇, AI 낙찰가 예측, 재학습 MLOps를 통합합니다.

본 저장소는 **완성도 있는 서비스를 목표로 합니다.** 학습이나 발표 목적이 아니라 실제 서비스 품질이 판단 기준이며, **최적화와 고도화가 최우선 사항**입니다. 상세는 [`SKILLS.md`](SKILLS.md)의 서비스 품질 우선 원칙을 참조하십시오.

**3대 리팩토링 목표:**

| 목표 | 핵심 |
| --- | --- |
| G1. 데이터 무손실 | DB 행 수·스키마 100% 보존, 모델 가중치·벡터DB 무결성 |
| G2. 크로스 플랫폼 | macOS/Windows 동일 환경 (Docker + Makefile) |
| G3. 스택 최적화 | 레이턴시·정합성 개선, 비동기화, train/serve skew 해결 |

G3 는 일회성 과업이 아니라 상시 과제입니다. 기능이 동작하는 것으로 완료가 아니며, 실측으로 성능을 확인해야 완료입니다.

---

## 2. 기술 스택 (확정)

| 영역 | 기술 | 비고 |
| --- | --- | --- |
| 백엔드 | FastAPI (ASGI) | 비동기 I/O, Pydantic v2, Swagger 자동화 |
| DB | MySQL 8 (Docker) | 이중화(SQLite fallback) 제거, 스키마 100% 보존 |
| 캐시/브로커 | Redis | 파일/locmem 캐시 대체 |
| 태스크 큐 | Arq (asyncio + Redis) | 경량 비동기 태스크 큐 |
| ML | LightGBM, CatBoost, scikit-learn | 기존 스택 유지 |
| 벡터DB | ChromaDB (유지) | 원본 `bidding_kb` 1개 컬렉션 스냅샷 보존 최우선 (G1) |
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

## 4. Orca 다중 섹션 조율 규칙

둘 이상의 에이전트 또는 섹션이 관여하거나, 작업 사이에 병합·검증·공유 자원 의존성이 있으면 반드시 `orca-section-coordination` 스킬을 먼저 사용합니다.

1. 작업 묶음은 Orca Run으로 만들거나 기존 Run에 바인딩하고, 각 섹션을 Task로 등록합니다.
2. 선행 작업·병합·검증·공유 자원(Docker/DB/대량 색인/ML 학습)은 Task 의존성으로 명시합니다.
3. 다음 섹션은 선행 Task의 검증된 `worker_done` 전에는 시작하지 않습니다. 터미널 출력이나 구두 보고만으로 완료·병합·시작 가능을 선언하지 않습니다.
4. 워커는 검증 결과·변경 파일·차단 사유를 포함한 `worker_done`으로 종료합니다. 코디네이터는 해당 기록을 확인한 뒤에만 후속 Task를 Dispatch합니다.
5. 하나의 브랜치·작업 트리·공유 자원에 대한 동시 쓰기 작업은 금지합니다. 독립 작업만 병렬로 Dispatch합니다.
6. Orca 런타임을 사용할 수 없으면 조율 작업을 시작하지 말고, 준비 상태 또는 차단 원인을 사용자에게 보고합니다.

## 5. 커뮤니케이션 규칙

- 응답은 한국어 존댓말로 작성.
- 복잡한 변경이나 설계 결정은 사전에 제안하고 합의 후 진행.
- 파일 경로는 `file_path:line_number` 형식으로 참조 (클릭 가능).

---

## 6. Git 규칙

본 저장소는 **1인 작업**입니다. 리뷰어가 없으므로 Pull Request 절차를 두지 않습니다.

- **Pull Request 를 만들지 않습니다.** 작업 브랜치에서 커밋·푸시한 뒤 담당자 확인을 거쳐 `main` 에 직접 병합합니다.
- `main` 에 곧바로 커밋하지 않습니다. 변경은 항상 작업 브랜치에서 시작합니다.
- 병합은 `git merge --no-ff` 로 수행해 작업 단위를 이력에 남깁니다.
- 병합 전 필수 확인: 테스트 전량 통과, `python scripts/validate_agent_rules.py` 통과.
- 커밋 메시지: `type: subject` 형식 (예: `feat: add retraining trainer`).
  - type: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`
- 상세는 [`docs/ops/git_branching_strategy.md`](docs/ops/git_branching_strategy.md).

---

## 7. 금지 행위 (절대)

1. 코드 주석, 커밋 메시지, 문서 내 이모지 사용
2. 영어로 대화 응답이나 아티팩트 작성 (코드/변수명 제외)
3. 사전 허가 없이 새로운 Python 라이브러리 추가
4. `.env` 파일의 실제 값을 코드나 문서에 노출
5. 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반)
6. 학습·추론 특징 생성 로직을 분리하여 작성 (train/serve skew 유발)
7. `main` 브랜치에서 직접 작업·커밋 (병합은 작업 브랜치를 거칠 것)
8. Pull Request 생성 (1인 작업이므로 불필요)
9. 마이그레이션 검증 없이 다음 Phase 진행
10. Orca로 관리해야 하는 섹션 작업을 Run·Task·`worker_done` 기록 없이 완료·병합·인수인계되었다고 표현

---

## 8. 문서화 표준

마크다운 위계(`#`/`##`/`###`), 구분선(`---`), 표 우선, Mermaid 다이어그램, 메타데이터 블록(`>`)을 준수합니다. 상세는 [`SKILLS.md`](SKILLS.md)의 DOCUMENTATION & FORMATTING RULES 섹션을 참조하십시오.

---

## 9. 스킬 인덱스 (Phase 0~7)

| 스킬명 | Phase | globs / 경로 | 핵심 기능 |
| --- | --- | --- | --- |
| `foundation-setup` | Phase 0 | `.agents/skills/foundation-setup/` | uv, Makefile, Docker, CI, 린터 설정 |
| `data-preservation` | Phase 1 | `.agents/skills/data-preservation/` | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| `infrastructure-setup` | Phase 2 | `.agents/skills/infrastructure-setup/` | DB ORM 이식, Redis 캐시, 비동기 태스크 큐 |
| `application-migration` | Phase 3 | `.agents/skills/application-migration/` | 백엔드 API 이식, 거대 모듈 분할, async/await |
| `inference-rag-opt` | Phase 4 | `.agents/skills/inference-rag-opt/` | 싱글톤 로드, 가중치 외부화, RAG 캐싱 |
| `retraining-pipeline` | Phase 5 | `.agents/skills/retraining-pipeline/` | 단일 특징 features.py, trainer, ml_registry, PSI 모니터링 |
| `servc-model-tuning` | 상시 | `.agents/skills/servc-model-tuning/` | 용역 모델 성능 개선. 기각 목록, 쌍대 검정 기준, 측정 함정 |
| `frontend-streaming` | Phase 6 | `.agents/skills/frontend-streaming/` | SSE/WebSocket 스트리밍, HTMX/React 동적 UI |
| `validation-cutover` | Phase 7 | `.agents/skills/validation-cutover/` | E2E, P95 레이턴시 벤치마크, 크로스플랫폼 컷오버 |
| `project-orchestrator` | 운영 | `.agents/skills/project-orchestrator/` | 도커 컨테이너 통째 시동, 헬스체크, 무손실 검증, 레이턴시 벤치마크 자동 오케스트레이션 |
| `git-workflow` | 공통 | `.agents/skills/git-workflow/` | 커밋 메시지 컨벤션, pre-commit 검증, 1인 작업 브랜치 -> main 병합 워크플로우 (PR 없음) |
| `orca-section-coordination` | 공통 | `.agents/skills/orca-section-coordination/` | Orca Run·Task·Dispatch 기반 섹션 의존성, 공유 자원, 완료 검증, 인수인계 조율 |

