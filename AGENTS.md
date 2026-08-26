# refac_bid_box — Agent Guidelines (정본)

> **작성일**: 2026-07-31
> **수정일**: 2026-08-23
> **버전**: v0.2.0
> 본 파일은 모든 AI 코딩 에이전트가 공유하는 **단일 진실 원천(Single Source of Truth)** 입니다.
> 규칙을 편집할 때는 반드시 이 파일만 수정합니다. 상세한 다중 에이전트 매핑은 [`docs/ops/multi_agent_setup.md`](docs/ops/multi_agent_setup.md)를 참조하십시오.

---

## 0. 에이전트 부트스트랩 모드 (Agent Bootstrap Modes)

모든 에이전트는 본 `AGENTS.md`를 단일 진실 원천으로 자동 로드한 후, 자신의 역할(Role)에 맞는 최소 문맥만 선택하여 시작합니다.

### 0.1 Coordinator 모드
- 프로젝트 현재 운영 상태 정본: [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md)를 읽습니다.
- 현재 작업에 필요한 스킬 1개만 선택적으로 로드합니다 (예: `.agents/skills/project-orchestrator/SKILL.md`).
- Orca 다중 Task/섹션 작업일 때만 [`.agents/skills/orca-section-coordination/SKILL.md`](.agents/skills/orca-section-coordination/SKILL.md)를 읽습니다.
- 과거 인수인계 문서(handoff)나 전체 설계서([`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md))는 현재 Task의 근거가 부족할 때만 선택 조회합니다.

### 0.2 Orca Worker 모드
- 코디네이터가 주입한 **`ORCA_TASK_CAPSULE_V2`가 해당 작업 문맥의 정본**입니다.
- Capsule에 명시되지 않은 `README.md`, `SKILLS.md`, 전체 설계서, 과거 handoff를 재독하지 않습니다.
- 사양(`ground_truth`)에 명시된 이미 확인된 사실은 재조사하지 않습니다.
- 허용 범위(`allowed_read_files`, `allowed_write_files`) 밖의 문맥이나 수정이 필요하면 즉시 질문(`ask`) 또는 에스컬레이션(`escalation`)합니다.

### 0.3 Reviewer 모드
- Task Capsule, 변경 파일 목록, `git diff`, acceptance criteria, 테스트 결과 요약만 좁게 검토합니다. 프로젝트 전체를 탐색하지 않습니다.

### 0.4 Standalone 모드
- Orca 조율 외 단독 에이전트로 전체 프로젝트 작업을 수행할 때만 선택형 컨텍스트 인덱스인 [`SKILLS.md`](SKILLS.md)를 참조합니다.

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
| 검색 엔진 | Meilisearch | Compose 필수 서비스. `MEILI_ENABLED`로 제어, 공고·낙찰 목록 읽기 모델 전용 |
| 태스크 큐 | Arq (asyncio + Redis) | 경량 비동기 태스크 큐 |
| ML | LightGBM, CatBoost, scikit-learn | 기존 스택 유지 |
| 벡터DB | ChromaDB (유지) | 원본 `bidding_kb` 1개 컬렉션 스냅샷 보존 최우선 (G1) |
| LLM | Ollama gemma4:e2b (기본), Google Gemini (대체/선택) | 의도 분류, 요약, RAG |
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

다른 섹션과 **같은 파일·브랜치·작업 트리**를 다루거나, 작업 사이에 병합·검증·공유 자원 의존성이 있으면 반드시 `orca-section-coordination` 스킬을 먼저 사용합니다.

**같은 프로젝트에서 동시에 일한다는 사실만으로는 조율 대상이 아닙니다.** 격리 작업 트리에서 자기 브랜치의 새 파일만 만들고 검증까지 마치는 작업은 겹치는 것이 없으므로 제외합니다. 겹치는 것이 생기는 시점(병합, 공유 자원 점유)에 등록합니다.

1. 작업 묶음은 Orca Run으로 만들거나 기존 Run에 바인딩하고, 각 섹션을 Task로 등록합니다.
2. 선행 작업·병합·검증·공유 자원(Docker/DB/대량 색인/ML 학습)은 Task 의존성으로 명시합니다.
3. 다음 섹션은 선행 Task의 검증된 `worker_done` 전에는 시작하지 않습니다. 터미널 출력이나 구두 보고만으로 완료·병합·시작 가능을 선언하지 않습니다.
4. 워커는 검증 결과·변경 파일·차단 사유를 포함한 `worker_done`으로 종료합니다. 코디네이터는 해당 기록을 확인한 뒤에만 후속 Task를 Dispatch합니다.
5. 하나의 브랜치·작업 트리·공유 자원에 대한 동시 쓰기 작업은 금지합니다. 독립 작업만 병렬로 Dispatch합니다.
5.1. **동시 쓰기 워커는 3대를 넘기지 않습니다.** 작업 트리가 서로 겹치지 않아도 적용됩니다. 워커 풀은 여러 개지만 코디네이터는 하나이므로, 검증이 병목이 되면 미검증 병합 위험이 커집니다. 읽기 전용 워커(`allowed_write_files` 가 빈 목록)는 상한에 포함하지 않습니다. `scripts/orca_taskctl.py dispatch` 가 이 상한을 기계로 강제하며 초과 시 워커를 기동하지 않고 종료 코드 1 로 거부합니다. 상한을 의도적으로 올릴 때만 `--max-write-workers` 를 쓰고, `--skip-concurrency-check` 는 습관적으로 쓰지 않습니다.
6. 섹션이 끝나고 산출물이 병합되면 그 자리에서 워커·워크트리를 해제하고 병합 완료 브랜치를 정리합니다. 활성 Dispatch 가 소유한 트리, 미병합 브랜치, 다른 섹션의 미커밋 변경은 건드리지 않습니다. 정리 여부는 `worker_done` 또는 인수인계에 남깁니다.
7. Orca 런타임을 사용할 수 없으면 조율 작업을 시작하지 말고, 준비 상태 또는 차단 원인을 사용자에게 보고합니다. 진행 중이던 작업은 중단하지 않되 상태 선언을 멈춥니다.

## 5. 커뮤니케이션 규칙

- 응답은 한국어 존댓말로 작성.
- 복잡한 변경이나 설계 결정은 사전에 제안하고 합의 후 진행.
- 파일 경로는 `file_path:line_number` 형식으로 참조 (클릭 가능).
- 코디네이터의 기본값은 Codex `gpt-5.6-terra` + effort `medium`입니다. 기본값을 벗어나 모델 또는 effort를 변경하기 전에는 사용자에게 `MODEL_CHANGE_NOTICE`로 대상 작업, 변경 전·후 설정, 사유, 사용량 영향, 기본값 복귀 시점을 알립니다. `gpt-5.6-sol` + `high`는 데이터 무손실·컷오버·복잡한 병합의 최종 판정에만 쓰며 사용자 승인 후에만 적용합니다. 상세 매트릭스는 [`docs/ops/orca_orchestration_playbook.md`](docs/ops/orca_orchestration_playbook.md) 4.2.1절을 따릅니다.
- Gemini 워커의 기본값은 Antigravity `gemini-3.7-flash-medium`입니다. `flash-high`는 데이터 무손실 영향, 복잡한 구현·회귀 분석, 독립 교차검토처럼 high 위험도 Task에만 사용하며, Task Capsule과 사용자 대화에 `WORKER_MODEL_NOTICE`(대상, Medium에서의 변경, 사유, 사용량 영향, 복귀 시점)를 남깁니다. `flash-low`는 읽기 전용 조사·초안·경량 계측에만 사용하고, 빌더·리뷰어 Task에는 배정하지 않습니다.

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
10. **4장 적용 대상인** 섹션 작업을 Run·Task·`worker_done` 기록 없이 완료·병합·인수인계되었다고 표현 (겹치는 파일·자원·순서가 없는 독립 작업은 대상이 아님)

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
