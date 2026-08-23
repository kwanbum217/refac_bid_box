# refac_bid_box AI Agent Skills & Context Index

> **작성일**: 2026-07-31
> **수정일**: 2026-08-14
> **버전**: v0.2.0
> **용도**: Coordinator 및 Standalone 에이전트용 **선택형 프로젝트 컨텍스트 & 스킬 인덱스**입니다.
> **주의**: Orca 워커(Worker Plane)는 본 문서를 읽지 않으며, 코디네이터가 주입한 `ORCA_TASK_CAPSULE_V2`의 허용 파일 목록만 참조합니다.

---

## 1. 프로젝트 현재 상태 (Single Source of Truth)

현재 프로젝트의 최신 운영 메트릭, 게이트 상태, 활성 우선순위 및 기각된 접근 방식은 다음 정본 문서를 참조합니다:

- **운영 정본**: [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md)
- **규칙 정본**: [`AGENTS.md`](AGENTS.md)
- **리팩토링 설계서**: [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md) (필요 시 선택 조회)

---

## 2. 작업 유형별 참조 문서 매핑

작업 성격에 따라 필요한 문서만 선택하여 참조하십시오:

| 작업 유형 | 참조 문서 |
| --- | --- |
| 프로젝트 최신 상태·지표 | [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) |
| 데이터 마이그레이션 | [`docs/migration/db_migration_runbook.md`](docs/migration/db_migration_runbook.md) |
| ML 가중치·ChromaDB 보존 | [`docs/migration/ml_weights_verification.md`](docs/migration/ml_weights_verification.md) |
| 레이턴시·성능 측정 | [`docs/ops/latency_gate_protocol.md`](docs/ops/latency_gate_protocol.md) |
| 환경 변수 | [`docs/ops/environment_variables.md`](docs/ops/environment_variables.md) |
| 크로스 플랫폼 대응 | [`docs/ops/cross_platform_guide.md`](docs/ops/cross_platform_guide.md) |
| 브랜치/Git 작업 | [`docs/ops/git_branching_strategy.md`](docs/ops/git_branching_strategy.md) |
| 다중 에이전트 환경 | [`docs/ops/multi_agent_setup.md`](docs/ops/multi_agent_setup.md) |
| Orca 오케스트레이션 | [`docs/ops/orca_orchestration_playbook.md`](docs/ops/orca_orchestration_playbook.md) |
| 문서 전체 인덱스 | [`docs/README.md`](docs/README.md) |

다른 섹션과 같은 파일·브랜치·작업 트리를 다루거나, 병합·검증·공유 자원 대기가 있으면 작업 전 [`.agents/skills/orca-section-coordination/SKILL.md`](.agents/skills/orca-section-coordination/SKILL.md)를 읽고 Orca Run·Task로 등록합니다. 겹치는 것이 없는 독립 작업은 대상이 아닙니다.

---

## 3. 서비스 품질 우선 원칙

refac_bid_box는 **완성도 있는 서비스를 목표로 하는 프로젝트**입니다. 발표나 학습 목적이 아니라 실제 서비스 품질이 최우선 기준이며, **최적화와 고도화가 최우선 사항**입니다.

따라서 LLM 에이전트는 핵심 로직을 담당자에게 미루지 않고 **끝까지 완성합니다.** 특징 엔지니어링, 모델 선택, 하이퍼파라미터, 승격 기준, 분할 전략을 포함한 ML 설계 결정을 직접 내리고 근거를 문서로 남깁니다.

| 구분 | 기준 |
| --- | --- |
| **결정 주체** | LLM 이 판단하고 실행합니다. 결정마다 근거(측정값, 비교표)를 남깁니다 |
| **근거 요구** | 성능 주장에는 반드시 실측이 따릅니다. 추정치로 "개선됨" 이라 쓰지 않습니다 |
| **완료 기준** | 운영 경로에 연결되고 실측으로 확인되어야 완료입니다. 모듈만 만든 것은 미완입니다 |
| **담당자 확인** | 되돌리기 어려운 변경(스키마, 데이터 삭제, 외부 발신)과 비용이 큰 선택만 사전 확인 |

품질 판단 기준의 우선순위입니다.

1. **정확성** — 잘못된 결과를 내지 않을 것. 성능보다 앞섭니다
2. **데이터 무손실(G1)** — 협상 대상이 아닙니다
3. **레이턴시·처리량** — 최적화는 상시 과제입니다
4. **유지보수성** — 위 셋을 해치지 않는 선에서

측정하지 않은 최적화는 최적화가 아닙니다. 병목은 추측하지 말고 재고, 개선 후 다시 재서 수치로 남깁니다.

---

## 4. 핵심 프로젝트 컨텍스트 (Core Project Context)

refac_bid_box는 **공공조달(G2B/나라장터) 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 + 재학습 MLOps 플랫폼**입니다.

핵심 구조:

| 계층 | 역할 |
| --- | --- |
| `src/app/` | 백엔드 애플리케이션 (FastAPI/Django ASGI) — bids/chatbot/predictions/accounts API |
| `src/ml/` | ML 도메인 — 싱글톤 모델 로드, 통합 특징 함수, 학습기, 레지스트리 |
| `src/tasks/` | 비동기 태스크 (Arq) — G2B 수집, 재학습, KB 업데이트 |
| `src/rag/` | RAG 엔진 — ChromaDB 검색 + Ollama gemma4:e4b (기본) / Gemini (대체) |
| `migrations/` | DB 마이그레이션 (기존 19개 히스토리 보존) |
| `docker/` | Docker 구성 — MySQL + Redis + app + worker |

비협상 원칙 (non-negotiable):

- **데이터 무손실**: 기존 DB 행 수·스키마 100% 보존. 컬럼 타입 변경 금지.
- **Train/Serve 특징 단일화**: 학습·추론 특징 생성은 단일 함수(`features.py`)만 사용. 하드코딩 상수(`DEFAULT_INST_RATE` 등) 제거.
- **크로스 플랫폼**: macOS/Windows 모두 Docker + Makefile로 동일 환경. 플랫폼 종속 바이너리(`hc.exe`) 제거.
- **재학습 게이트**: 신규 모델은 champion을 성능으로 압도할 때만 승격. 즉시 롤백 가능.

---

## 5. 문서화 및 포매팅 규칙 (Documentation & Formatting Rules)

1. **언어 및 어조**: 설명은 **한국어(존댓말/경어체)**. 코드/변수명/환경변수명은 영어.
2. **마크다운 구조**: 제목 `#`, 섹션 `##`, 하위 `###`. 주요 섹션 사이 구분선(`---`). 비교·설정·매핑은 **표(Table)** 우선. 핵심은 굵게.
3. **다이어그램 (Mermaid)**: 아키텍처/프로세스에 적극 활용. 노드 텍스트에 공백/특수문자 시 큰따옴표(`"텍스트"`) 사용. 긴 텍스트는 `<br/>`로 줄바꿈.
4. **메타데이터**: 새 문서 상단에 `>` 인용 블록으로 작성일/버전/상태 명시 (예: `> **작성일**: 2026-07-31`).
5. **금지**: 문서 내 **이모지(Emoji)** 사용 불가.

---

## 6. 스킬 인덱스 (Skill Index)

| 스킬명 | Phase | 경로 | 핵심 기능 |
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
| `project-orchestrator` | 운영 | `.agents/skills/project-orchestrator/` | 도커 컨테이너 통째 시동, 헬스체크, 무손실 검증, 레이턴시 벤치마크 자동화 |
| `git-workflow` | 공통 | `.agents/skills/git-workflow/` | 커밋 메시지 컨벤션, pre-commit 검증, 1인 작업 브랜치 -> main 병합 (PR 없음) |
| `orca-section-coordination` | 공통 | `.agents/skills/orca-section-coordination/` | Orca Run·Task·Dispatch 기반 섹션 의존성, 공유 자원, 완료 검증 조율 |

---

## 7. 세션 작업 체크리스트 (선택형)

독립 작업 세션 시작 시 필요 항목을 확인합니다:

- [ ] `AGENTS.md` 핵심 규칙 확인
- [ ] `docs/context/CURRENT_STATE.md` 최신 운영 상태 및 지표 확인
- [ ] 작업 유형에 맞는 대상 스킬 1개 참조
- [ ] 데이터 무손실 영향 여부 확인 (DB/가중치/ChromaDB 접근 시)
- [ ] macOS/Windows 호환성 영향 여부 확인
- [ ] 다른 섹션과 겹치는 파일·자원·순서가 있으면 Orca Run·Task·의존성·공유 자원 소유자 등록 완료
