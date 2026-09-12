# 다중 에이전트 셋업 가이드

> **작성일**: 2026-07-31
> **수정일**: 2026-08-15
> **버전**: v1.2
> **목적**: opencode, Cursor, Codex, Claude Code, Antigravity 등 서로 다른 AI 코딩 에이전트를 돌아가며 사용해도, 세션 시작 시 동일한 프로젝트 규칙이 자동으로 로드되고 Orca로 섹션 협업을 조율하도록 하는 아키텍처를 설명합니다.

---

## 1. 핵심 원칙: 단일 진실 원천 (Single Source of Truth)

본 프로젝트는 **규칙을 한 곳(`AGENTS.md`)에서만 편집**하고, 각 에이전트가 요구하는 파일명은 `AGENTS.md`를 가리키는 얇은 진입점(thin pointer / 간접 참조)으로만 둡니다. 진입점 자체에 규칙 내용을 복사하지 않습니다.

```text
                 AGENTS.md  (정본, 유일한 편집 대상, 단일 자동 로드)
                      |
    +--------+--------+--------+--------+
    |        |        |        |        |
  Codex   opencode Antigravity Claude  Cursor
  (직접)  (직접)    (직접)    Code     .mdc
                              thin     간접참조
                              pointer
```

---

## 2. 에이전트별 자동 로드 매핑

| 에이전트 | 자동 로드 파일 | 진입점 방식 | 근거 |
| :--- | :--- | :--- | :--- |
| **Codex CLI** | `AGENTS.md` | 정본 직접 | [OpenAI 공식](https://learn.chatgpt.com/docs/agent-configuration/agents-md) — 작업 전 AGENTS.md를 항상 읽음 |
| **opencode CLI** | `AGENTS.md` | instructions 단일 지정 | [OpenCode config](https://opencode.ai/docs/config/) — `instructions: ["AGENTS.md"]` |
| **Antigravity CLI** | `AGENTS.md` | 정본 직접 | [Google 공식 best practices](https://antigravity.google/docs/cli/best-practices) — workspace root의 AGENTS.md 권장 |
| **Claude Code CLI** | `CLAUDE.md` | thin pointer (`@AGENTS.md`) | Claude Code는 CLAUDE.md를 항상 읽음; import로 AGENTS.md 주입 |
| **Grok CLI** | `AGENTS.md` + `.grok/rules/*.md` | 정본 직접 + 규칙 디렉터리 | Grok 은 `AGENTS.md` 와 `.grok/rules/` 를 세션 시작 시 자동 로드. 코디네이터 캐시 접두부는 `.grok/rules/bidbox-orca-coordinator.md` |
| **Cursor CLI** | `.cursor/rules/*.mdc` | 간접 참조 | [Cursor Rules](https://cursor.com/docs/rules) — `00-core-guidelines.mdc`가 AGENTS.md 참조 |

> 참고: `AGENTS.md`는 60,000개 이상의 오픈소스 프로젝트가 채택한 [교차 도구 표준](https://agents.md/)입니다. Codex, opencode, Antigravity 3개 CLI가 이를 직접 읽습니다.

---

## 3. 각 진입점의 역할과 동작

### 3.1 AGENTS.md (정본)

- 프로젝트 규칙의 **유일한 편집 대상**이자 모든 에이전트의 **단일 자동 로드 정본**입니다.
- 비협상 원칙(G1/G2/G3), 코딩 규칙, 절대 금지 행위, Orca 다중 섹션 조율 규칙을 정의합니다.
- 역할별 부트스트랩 모드(Coordinator, Orca Worker, Reviewer, Standalone)를 정의하여 불필요한 전체 문서 재독을 방지합니다.

### 3.1.1 에이전트 부트스트랩 모드 상세 절차

모든 에이전트는 본 `AGENTS.md`를 단일 진실 원천으로 자동 로드한 후, 자신의 역할(Role)에 맞는 최소 문맥만 선택하여 시작합니다.

#### Coordinator 모드
- 프로젝트 현재 운영 상태 정본: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)를 읽습니다.
- 현재 작업에 필요한 스킬 1개만 선택적으로 로드합니다 (예: `.agents/skills/project-orchestrator/SKILL.md`).
- Orca 다중 Task/섹션 작업일 때만 [`.agents/skills/orca-section-coordination/SKILL.md`](../../.agents/skills/orca-section-coordination/SKILL.md)를 읽습니다.
- Grok 가 코디네이터일 때는 [`grok_coordinator_operating_prompt.md`](grok_coordinator_operating_prompt.md)를 운영 절차로 따르고, 캐시 접두부는 [`.grok/rules/bidbox-orca-coordinator.md`](../../.grok/rules/bidbox-orca-coordinator.md)입니다.
- 과거 인수인계 문서(handoff)나 전체 설계서([`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md))는 현재 Task의 근거가 부족할 때만 선택 조회합니다.

#### Orca Worker 모드
- 코디네이터가 주입한 **`ORCA_TASK_CAPSULE_V2`가 해당 작업 문맥의 정본**입니다.
- Capsule에 명시되지 않은 `README.md`, `SKILLS.md`, 전체 설계서, 과거 handoff를 재독하지 않습니다.
- 사양(`ground_truth`)에 명시된 이미 확인된 사실은 재조사하지 않습니다.
- 허용 범위(`allowed_read_files`, `allowed_write_files`) 밖의 문맥이나 수정이 필요하면 즉시 질문(`ask`) 또는 에스컬레이션(`escalation`)합니다.

#### Reviewer 모드
- Task Capsule, 변경 파일 목록, `git diff`, acceptance criteria, 테스트 결과 요약만 좁게 검토합니다. 프로젝트 전체를 탐색하지 않습니다.

#### Standalone 모드
- Orca 조율 외 단독 에이전트로 전체 프로젝트 작업을 수행할 때만 선택형 컨텍스트 인덱스인 [`SKILLS.md`](../../SKILLS.md)를 참조합니다.

### 3.2 SKILLS.md (선택형 컨텍스트 & 스킬 인덱스)

- Coordinator 및 Standalone 에이전트용 선택형 참조 인덱스입니다.
- 프로젝트 현재 상태([`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)) 안내, 작업 유형별 참조 문서 매핑, 서비스 품질 우선 원칙, 문서화 표준을 제공합니다.
- Orca 워커는 본 문서를 읽지 않으며, 코디네이터가 주입한 `ORCA_TASK_CAPSULE_V2`의 허용 파일 목록만 따릅니다.

### 3.3 CLAUDE.md (thin pointer)

- Claude Code는 `CLAUDE.md`를 자동 읽습니다.
- 본 파일은 `@AGENTS.md` import 한 줄만 포함하며, Claude Code가 import를 확장해 AGENTS.md 전체를 주입합니다.
- 규칙을 직접 적지 않습니다 (드리프트 방지).

### 3.4 opencode.json (opencode 전용)

- opencode CLI는 `opencode.json`의 `instructions` 배열을 통해 자동 로드 대상을 지정합니다.
- 본 프로젝트에서는 `["AGENTS.md"]`로 단일화하여 Cerebras 및 소형 컨텍스트 모델의 토큰 오버헤드를 방지합니다.

### 3.5 .cursor/rules/00-core-guidelines.mdc (Cursor 전용)

- Cursor는 루트 마크다운을 파일명으로 자동 인식하지 않으므로 `.cursor/rules/*.mdc` 독점 포맷을 사용합니다.
- `00-core-guidelines.mdc`(`alwaysApply: true`)가 항상 로드되며 AGENTS.md를 참조합니다.
- 정본 규칙을 복사하지 않고, 핵심 요약 + 정본 링크만 제공합니다.

---

## 4. 규칙 편집 워크플로우

### 4.1 규칙 변경 시

1. **`AGENTS.md`만 편집합니다.**
2. 핵심 규칙(비협상 원칙, 코딩 규칙, 금지 행위) 변경 시 `SKILLS.md` 및 요약본(`.antigravity/rules.md`, `.cursor/rules/00-core-guidelines.mdc`)의 정합성을 확인합니다.
3. `python scripts/validate_agent_rules.py`로 정합성을 검증합니다.

### 4.2 절대 하면 안 되는 행위

- `CLAUDE.md`에 규칙 내용을 직접 적기 (단일 소스 붕괴).
- `.cursor/rules/*.mdc`에 정본(AGENTS.md)과 다른 규칙을 적기.
- `AGENTS.md`와 `SKILLS.md`에 상충하는 코딩 규칙을 적기.

---

## 5. Orca 섹션 조율 규약

두 섹션 이상의 작업, 작업 간 병합·검증 의존성, 공유 자원 사용이 있으면 모든 에이전트는 `.agents/skills/orca-section-coordination/SKILL.md`를 먼저 읽습니다. 코디네이터는 Orca Run에 각 섹션을 Task로 등록하고, 의존성·공유 자원 소유자·완료 기준을 명시합니다.

| 단계 | Orca 기록 | 다음 단계 조건 |
| :--- | :--- | :--- |
| 계획 | Run + Task | 의존성·소유자·검증 기준 등록 |
| 실행 | Dispatch | 독립 Task만 병렬 실행 |
| 완료 | `worker_done` + 파일 아티팩트 | 컴팩트 요약(3문장)과 검증 결과 확인 |
| 후속 작업 | 의존 Task Dispatch | 선행 Task의 검증 완료 |
| 병합 | 별도 Git Task | 테스트·규칙 검증·사용자 승인 확인 |

터미널 출력, 채팅의 구두 보고, 단순 프로세스 종료는 완료·병합·후속 작업 시작의 근거가 아닙니다. Orca 런타임을 이용할 수 없으면 조율 작업을 시작하지 않고 차단 원인을 보고합니다.

### 5.1 Task Capsule v2 생명주기

워커 사양과 완료 보고는 [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)의
`ORCA_TASK_CAPSULE_V2` 계약을 따릅니다.

| 원칙 | 내용 |
| :--- | :--- |
| 워커 부트스트랩 | 자동 로드된 `AGENTS.md` + 주입된 Capsule + `allowed_read_files`만 사용. `README.md`·`SKILLS.md`·전체 설계서·과거 handoff 재독 금지 |
| 탐색 제한 | `search_scope` 기본 `deny_by_default`. 허용 glob 외 저장소 grep 금지 |
| 아티팩트 전달 | 상세 분석·벤치마크 표는 파일 아티팩트로 커밋 |
| 컴팩트 `worker_done` | `--body`는 3문장 이내 요약, `reportPath`/아티팩트 목록으로 상세 분리 |
| 모델 라우팅 | Antigravity Gemini Flash Medium이 기본 워커입니다. Flash High는 high 위험도 Task에만 `WORKER_MODEL_NOTICE`와 함께 승격하며, OpenCode 무료는 결정론적·병렬 조사 전용이고 병합·판정은 코디네이터가 맡습니다 |

`opencode.json`은 `instructions: ["AGENTS.md"]` 단일 자동 로드이며 `SKILLS.md`
중복 주입을 하지 않습니다. `AGENTS.md`에 `@SKILLS.md` 자동 import도 존재하지
않습니다.

### 5.2 Orca 다중 섹션 조율 규칙 상세

`AGENTS.md` 4장의 각 조율 규칙에 대한 상세 실행 지침 및 배경 설명입니다.

#### 5.2.1 조율 대상 기준 및 제외 원칙
다른 섹션과 **같은 파일·브랜치·작업 트리**를 다루거나, 작업 사이에 병합·검증·공유 자원 의존성이 있으면 반드시 `orca-section-coordination` 스킬을 먼저 사용합니다.

**같은 프로젝트에서 동시에 일한다는 사실만으로는 조율 대상이 아닙니다.** 격리 작업 트리에서 자기 브랜치의 새 파일만 만들고 검증까지 마치는 작업은 겹치는 것이 없으므로 제외합니다. 겹치는 것이 생기는 시점(병합, 공유 자원 점유)에 등록합니다.

#### 5.2.2 동시 쓰기 워커 상한 (규칙 5.1)
**동시 쓰기 워커는 3대를 넘기지 않습니다.** 작업 트리가 서로 겹치지 않아도 적용됩니다. 워커 풀은 여러 개지만 코디네이터는 하나이므로, 검증이 병목이 되면 미검증 병합 위험이 커집니다. 읽기 전용 워커(`allowed_write_files` 가 빈 목록)는 상한에 포함하지 않습니다. `scripts/orca_taskctl.py dispatch` 가 이 상한을 기계로 강제하며 초과 시 워커를 기동하지 않고 종료 코드 1 로 거부합니다. 상한을 의도적으로 올릴 때만 `--max-write-workers` 를 쓰고, `--skip-concurrency-check` 는 습관적으로 쓰지 않습니다.

#### 5.2.3 완료 세션 회수 절차 (규칙 6)
**완료 세션은 그 자리에서 회수합니다.** `worker_done` 을 ack 하고 Task 가 `completed` 가 되면 병합을 기다리지 말고 워커 터미널을 회수합니다(`worker-release`, 남은 창은 `terminal close --terminal`, `--tab` 금지). 워크트리와 브랜치는 로컬 `main` 병합이 확인된 뒤에만 제거합니다. 미병합 브랜치와 활성 Dispatch 트리는 건드리지 않습니다. `scripts/orca_taskctl.py dispatch` 는 완료됐는데도 워커 터미널이 남은 세션이 있으면 기동을 거부합니다. 검사 명령은 `python3 scripts/orca_settled_session_audit.py` 입니다. 정리 여부는 인수인계에 "회수했다/하지 않았다"로 남깁니다.

#### 5.2.4 병렬 검증 원칙 (규칙 8)
**검증은 완료 순서대로 병렬로 실행합니다.** 워커가 끝나는 대로 그 Task 의 Level 1 게이트와 리뷰어 Dispatch 를 시작하고 다른 워커의 완료를 기다리지 않습니다. 검증은 읽기 전용이고 워크트리가 서로 다르므로 동시 쓰기 상한과 무관합니다. `main` 병합만 직렬입니다. 상세는 [`.agents/skills/orca-section-coordination/SKILL.md`](../../.agents/skills/orca-section-coordination/SKILL.md) 4.3 절.

#### 5.2.5 워커 감시 및 차단 대응 (규칙 9)
**Dispatch 한 워커는 감시 대상입니다.** 지시가 필요 없는 상시 의무이며, 진행·완료·차단을 보고하기 전에 `python3 scripts/orca_worker_watch.py` 로 워커별 커밋 수·미커밋 수와 터미널 차단 신호를 확인합니다. 종료 코드 1 은 사람 개입이 필요한 차단이 있다는 뜻이므로 조치 전에는 다음 Task 를 Dispatch 하지 않습니다. 워커가 신뢰 대화창, 설문, 권한 요청, 인증 정체에 막혀 있는 것을 사용자가 먼저 발견하면 코디네이터 실패로 간주합니다.

### 5.3 모델 운영 및 배정 규칙

- 코디네이터의 기본값은 Codex `gpt-5.6-terra` + effort `medium`입니다. 기본값을 벗어나 모델 또는 effort를 변경하기 전에는 사용자에게 `MODEL_CHANGE_NOTICE`로 대상 작업, 변경 전·후 설정, 사유, 사용량 영향, 기본값 복귀 시점을 알립니다. `gpt-5.6-sol` + `high`는 데이터 무손실·컷오버·복잡한 병합의 최종 판정에만 쓰며 사용자 승인 후에만 적용합니다. 상세 매트릭스는 [`docs/ops/orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 4.2.1절을 따릅니다.
- 워커 모델 배정의 실행 정본은 [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py)의 `TIER_POLICY`이며, 문서는 그 사본을 두지 않습니다. 리뷰어는 빌더와 다른 계열을 배정해야 한다는 불변조건을 준수하고, 모델은 풀 등록 전에 해당 CLI로 직접 probe합니다. 기본값을 벗어나면 `WORKER_MODEL_NOTICE`를 남깁니다. 상세 근거와 가용성 실측은 [`docs/ops/orca_worker_model_pool.md`](orca_worker_model_pool.md)를 참조하십시오.

---

## 6. 신규 에이전트 추가 체크리스트

새로운 에이전트를 도입할 때의 진입점 추가 절차입니다.

| 단계 | 확인 사항 |
| :--- | :--- |
| 1 | 해당 에이전트가 `AGENTS.md`를 네이티브로 읽는가? → 그러면 진입점 추가 불필요 |
| 2 | 별도 파일명을 요구하는가? (예: `FOO.md`) → thin pointer(`@AGENTS.md`) 또는 symlink 생성 |
| 3 | 독점 포맷인가? (예: Cursor `.mdc`) → 해당 포맷에 맞춰 AGENTS.md 참조 파일 생성 |
| 4 | 본 가이드 §2 매핑 테이블에 신규 에이전트 행 추가 |

---

## 7. 관련 파일 인덱스

| 파일 | 역할 |
| :--- | :--- |
| `AGENTS.md` | 규칙 정본 (단일 진실 원천) |
| `SKILLS.md` | 시작 시퀀스, 문서 규칙, 워크플로우 체크리스트 |
| `CLAUDE.md` | Claude Code thin pointer (`@AGENTS.md`) |
| `opencode.json` | opencode instructions 설정 |
| `.antigravity/rules.md` | Antigravity 핵심 규칙 요약본 (12,000자 캡 준수) |
| `.cursor/rules/*.mdc` | Cursor 핵심 규칙 (00-core) 및 Phase 0~7 스킬 규칙 (01~08) |
| `.agents/skills/{스킬명}/` | 스킬 정본 (Phase 0~7 8개 스킬) |
| `.claude/skills/{스킬명}/` | Claude Code 전용 스킬 1:1 미러 (생성물) |
| `.opencode/skills/{스킬명}/` | opencode 전용 스킬 1:1 미러 (생성물) |
| `scripts/sync_skill_mirrors.py` | 정본을 두 미러로 복제 (`make sync-skills`) |
| `.agents/skills/orca-section-coordination/` | Orca 기반 다중 섹션 조율 스킬 정본 |
| `scripts/validate_agent_rules.py` | 정합성 자동 검증 스크립트 (pre-commit 연동) |


### 7.1 스킬 미러는 손으로 맞추지 않습니다

정본은 `.agents/skills/` 하나이고 `.claude/skills/` 와 `.opencode/skills/` 는 각 CLI 가
스킬을 탐색하는 고정 경로입니다. 세 트리는 바이트 단위로 같아야 하며
`scripts/validate_agent_rules.py` 검사 5 가 커밋 시점에 강제합니다.

**정본을 고친 뒤에는 복제 도구를 실행하고 결과를 같은 커밋에 담으십시오.**

```bash
python3 scripts/sync_skill_mirrors.py          # 정본 -> 미러 복제
python3 scripts/sync_skill_mirrors.py --check  # 어긋남만 보고 (종료 코드 1)
make sync-skills                               # 같은 동작
```

복제 도구는 내용이 다른 파일과 정본에만 있는 파일을 덮어쓰고, 미러에만 남은 파일과 그
결과로 비게 된 디렉터리를 제거합니다. `--check` 는 파일을 고치지 않습니다.

**심볼릭 링크로 통합하지 않는 이유는 G2 입니다.** Windows 의 Git 은 `core.symlinks` 와
권한이 갖춰지지 않으면 링크를 텍스트 파일로 체크아웃하므로, 그 환경에서 각 CLI 의 스킬
탐색이 오류 없이 조용히 깨집니다. 저장소에 추적되는 심볼릭 링크를 두지 않는 것이 현재
방침이며, 중복 비용(추적 파일 36개, 총 408K)보다 크로스 플랫폼 동일성을 우선합니다.

---

## 8. 참고 자료

- [AGENTS.md 공식 표준](https://agents.md/)
- [OpenAI Codex — AGENTS.md 가이드](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenCode — Config 문서](https://opencode.ai/docs/config/)
- [Google Antigravity — Best Practices](https://antigravity.google/docs/cli/best-practices)
- [Cursor — Rules 문서](https://cursor.com/docs/rules)
- [CLAUDE.md vs AGENTS.md 비교 (2026)](https://agyn.io/blog/claude-md-agents-md-compatibility)
