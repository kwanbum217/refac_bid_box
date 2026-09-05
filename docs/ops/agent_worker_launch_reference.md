# 에이전트 워커 기동 정본 참조

> **작성일**: 2026-08-14
> **수정일**: 2026-09-04
> **작성 근거**: 2026-08-14 세션에서 코디네이터가 각 경로를 직접 실행해 확인한 결과. Task Capsule v2 워커 실행 계약 반영. 1.5 절은 2026-08-20 Run `run_a32b6b614996` 의 모델별 실측 검증 결과. 2026-08-28 dispatch 경로 파일 편집 자동 승인 모드 전환(shift+tab) 자동화 반영. 2026-09-04 Orca 통제면 3대 결함(역할별 고지문 분기 및 커밋 의무 제어, 시도 단위 고유 preamble 수명주기 및 격리 파손 방지, 리뷰어 독립 provider 강제 및 명시 모델 우회 차단) 반영
> **적용 대상**: 이 저장소에서 Orca 워커·코디네이터를 배정하는 모든 에이전트
> **관련 문서**: [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md), [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md), [`.agents/skills/orca-section-coordination/SKILL.md`](../../.agents/skills/orca-section-coordination/SKILL.md)

---

## 0. 이 문서를 만든 이유

**"기동 경로를 찾지 못해 해당 모델을 워커나 코디네이터로 쓸 수 없다" 고 보고하지
마십시오.** 2026-08-14 세션에서 코디네이터가 실제로 쓸 수 있는 워커를 두 번
연속 "사용 불가" 로 잘못 판정했습니다.

| 잘못된 판정 | 실제 |
| --- | --- |
| `orca account list` 가 `unavailable` 이므로 Antigravity·OpenCode 는 워커로 쓸 수 없다 | 자격증명은 **사용량 표시** 용이며 기동과 무관합니다. 두 CLI 모두 워커로 정상 동작합니다 |
| Antigravity 상태바에 `AI: Out of credits` 이므로 오늘 Gemini 는 못 쓴다 | 실제 호출은 성공했습니다. 화면 표시가 실제 상태와 다릅니다 |

두 판정 모두 **화면 표시만 읽고 실제 호출을 시도하지 않아서** 나온 오류입니다.
아래 표의 경로를 먼저 확인하고, 그래도 막히면 실제로 한 번 호출해 본 뒤에
판정하십시오.

---

## 0.5 권한 자동 승인 및 상시 감시기는 기동 절차의 필수 단계입니다

**터미널 부착 경로로 워커를 띄웠다면 반드시 자동 승인 감시기를 붙이고 상시 감시기를 기동하십시오.**
붙이지 않으면 워커는 셸 명령 승인 대화창마다 멈추고, 코디네이터가 손으로 누를
때까지 아무 진행도 하지 않습니다. 2026-08-28 및 2026-09-01 세션에서 이 단계를 빠뜨려 워커
여러 대가 반복해서 정체했습니다.

| 층 | 무엇을 막아 주는가 | 조치 |
| --- | --- | --- |
| `shift+tab` (accept-edits) | **파일 편집 대화창만** 자동 승인 | `taskctl dispatch` 가 자동 전송 (`\x1b[Z`). 실패 시 수동: `orca terminal send --terminal <handle> --text $'\x1b[Z'` |
| `scripts/orca_auto_approve.py` | **셸 명령 승인 대화창** 화이트리스트 자동 승인 | `taskctl dispatch` 가 자동 기동. 실패 시 기본 fail-closed 로 dispatch 중단 (우회 시 `--skip-auto-approve-check` 필요) |
| `scripts/orca_worker_watch.py --watch` | **워커 진척·차단 상시 감시** 및 정체 즉시 감지 | `taskctl dispatch` 성공 시 배경으로 자동 기동. 단일 인스턴스 자동 재사용 |

세 층은 서로를 대체하지 않습니다. `shift+tab` 만 보내고 감시기를 띄우지 않으면
`cat > file`, `mkdir`, `top` 같은 명령에서 그대로 멈춥니다. 반대로 감시기만 띄우면
**파일 편집 대화창이 통째로 남습니다.** 감시기는 파일 편집을 승인하지 않고 보류하며
(`[보류] 파일 편집/생성 승인은 수동 판단 필요`), 그때부터 사람이 매번 손으로
눌러야 합니다. 2026-08-31 세션에서 이 조합으로 워커 한 대의 승인을 사용자가
직접 처리했습니다. 또한 상시 감시기가 없으면 워커가 승인 대기나 네트워크 장애로 정체되어도
코디네이터가 수동 폴링 전까지 인지하지 못합니다.

**`shift+tab` 을 연속으로 보내지 마십시오.** 순환은
`normal -> accept-edits -> plan -> normal` 이라 과전송하면 `plan` 으로 넘어가
워커가 파일을 아예 못 고칩니다. 한 번 보낼 때마다 `detect_antigravity_mode` 로
모드를 확인하십시오. 화면이 스피너면 `unknown` 이 나오는데 이는 판정 불가일 뿐이므로
**키를 더 보내지 말고 잠시 뒤 다시 읽습니다.** `enable_file_edit_auto_approve` 의
`force=True` 는 이 판정 불가 가드를 꺼 버리므로 습관적으로 쓰지 마십시오.

### 0.5.1 단일 감시기 보장 및 생명주기

자동 승인 감시기와 상시 워커 감시기는 각각 단일 인스턴스로 유지되어야 하며, 작업 생명주기에 맞춰 관리됩니다.

| 대상 / 생명주기 | 동작 메커니즘 | 관리 주체 |
| --- | --- | --- |
| 권한 승인 감시기 기동 및 중복 방지 | PID 레지스트리 파일(`orca_auto_approve/<terminal>.pid`)을 조회하여 프로세스 생존(`os.kill(pid, 0)`) 시 기존 감시기 재사용 | `scripts/orca_taskctl.py start_auto_approve` |
| 권한 승인 감시기 부착 실패 거부 | 감시기 기동 실패 시 dispatch 기본 fail-closed 거부 (종료 코드 2, `--skip-auto-approve-check` 로만 우회) | `scripts/orca_taskctl.py cmd_dispatch` |
| 상시 워커 감시기 자동 기동 | 워커 기동 성공 시 배경 프로세스로 `orca_worker_watch.py --watch` 기동 및 PID(`orca_worker_watch/watcher_<hash>.pid`) 기록/재사용 | `scripts/orca_taskctl.py start_worker_watch` |
| 비정상 프로세스 복구 | PID 파일이 손상되었거나 프로세스가 죽어 있으면 새 감시기를 띄우고 PID 갱신 | `scripts/orca_taskctl.py` |
| 명시적 종료 | Task 완료 시 SIGTERM 시그널을 전달하고 PID 파일을 삭제하여 고아 프로세스 방지 | `scripts/orca_taskctl.py finalize` (`stop_auto_approve`, `stop_worker_watch`) |
| 자체 종료 | 대상 터미널 읽기 연속 5회 실패(터미널 종료) 시 감시 대상에서 제외하며, 전체 대상 소진 시 자동 반환 및 PID 파일 정리 | `scripts/orca_auto_approve.py poll_loop` |

`scripts/orca_taskctl.py dispatch --terminal ...` 및 런처 경로는 통합 준비 상태 기계(`prepare_worker_terminal`, `scripts/orca_taskctl.py prepare-worker`)를
실행하여 (1) 워커 메타데이터 등록, (2) 신뢰 확인 대화창 승인, (3) 권한 자동 승인 감시기 부착, (4) 파일 편집 자동 승인 모드 전환(`shift+tab`, `\x1b[Z`)을 단일 절차로 처리합니다.
기동 시점에 기록된 메타데이터를 기반으로 CLI 종류를 판정하므로 화면 오염에 영향을 받지 않으며, Cursor 등 Plan Mode 로 전환되는 CLI 나 미식별 CLI 는 fail-closed 원칙에 따라 전송을 건너뛰고 안내 로그를 남깁니다.
감시기 기동 실패 시 fail-closed 로 즉시 중단되며, 모드 전환 전송에 실패하면 stderr 로 경고 및 수동 복구 명령을 안내합니다.

### 0.5.2 CLI별 `shift+tab` 해석 차이, 메타데이터 판정 및 안전 가드 (fail-closed)

`shift+tab`(`\x1b[Z`) 키 시퀀스는 모든 CLI 에서 동일한 의미를 갖지 않습니다.
특히 **Cursor Agent 에서 `shift+tab` 은 Plan Mode(읽기 전용, 파일 편집 금지) 전환**입니다.
또한 **Antigravity CLI 의 `shift+tab` 은 3단계 순환(normal -> accept-edits -> plan -> normal)** 구조를 가집니다. 이미 `accept-edits` 상태인 워커에 추가로 키를 보내면 오히려 `plan`(읽기 전용) 모드로 빠져 파일 편집이 차단됩니다.

따라서 `scripts/orca_taskctl.py` 의 준비 절차는 다음과 같이 안전 가드를 적용합니다:
1. **메타데이터 우선 판정**: 기동 시점에 기록한 메타데이터(`{terminal}.meta.json`)를 화면 텍스트보다 우선하여 CLI 종류를 식별합니다.
2. **현재 모드 선확인**: 화면 상태줄을 먼저 읽어 이미 `accept-edits` 면 추가 키를 전송하지 않습니다.
3. **Plan 모드 안전 복구**: 워커가 `plan` 모드로 빠진 경우 shift+tab 을 순환 전송하여 `accept-edits` 로 안전하게 복구합니다.
4. **시도 상한 제한**: 최대 3회 시도 상한을 두어 무한 순환을 방지합니다.

| CLI / 에이전트 | `shift+tab` 동작 및 의미 | `taskctl dispatch` 전송 여부 | 비고 |
| --- | --- | :---: | --- |
| **Antigravity** (`agy`) | **Accept-edits mode** (파일 편집·생성 확인 대화창 자동 승인, 3단계 순환) | **안전 순환 전송** (현재 모드 확인 후 필요 시에만 전송) | 첫 파일 편집 시 대화창 차단 방지, 이미 활성 시 키 미전송 |
| **Cursor** (`cursor-agent`) | **Plan Mode** (읽기 전용 계획 수립 모드, 파일 편집 금지) | **차단 (전송 안 함)** | 전송 시 워커가 편집 불가 상태로 빠지므로 절대 전송 금지 |
| **OpenCode Zen** | 탭/포커스 전환 (파일 편집 승인과 무관) | **차단 (전송 안 함)** | 상태줄 조작 안내 표지 |
| **Claude / Codex** | 미지원 또는 터미널 단축키 | **차단 (전송 안 함)** | `worker-start` 감독 경로 사용 |
| **미식별 / 일반 셸** | 미확인 | **차단 (fail-closed)** | 안전을 위해 기본 미전송 (`--enable-file-edit-auto-approve` 로 opt-in 가능) |

### 0.5.3 비감독 Dispatch 영수증 게이트 (fail-closed) 및 워크트리 Capsule 실존 검증

비감독 경로(`--terminal`)로 워커를 기동할 때 터미널 점유 누락과 사양 오독을 막기 위해 두 가지 엄격한 게이트가 적용됩니다:

1. **비감독 영수증 기동 전 기록 및 차단 (fail-closed)**:
   - 기동 직전 preflight 단계에서 `.orca/dispatch_receipts/<task_id>.json` 에 영수증을 먼저 기록합니다.
   - 영수증 기록에 실패하면 워커를 기동하지 않고 **종료 코드 2** 로 즉시 중단합니다. 영수증이 없으면 `orca_settled_session_audit.py` 가 완료 세션의 터미널 점유를 검출하지 못하여 회수 누락이 조용히 지나가기 때문입니다.
   - 우회는 오직 `--skip-dispatch-receipt` 명시 플래그로만 가능하며, 우회 시 경고가 출력됩니다. 기동 실패 시 사전 생성된 임시 영수증 파일은 자동으로 삭제 정리됩니다.

2. **워크트리 내 Capsule 정본 파일 실존 검증 및 자동 배치**:
   - 격리 워크트리에서 워커가 실행될 때, 워크트리 내에 대상 Capsule 파일이 실존하는지 기동 전에 확인합니다.
   - 워크트리에 파일이 없으면 주 저장소의 Capsule 을 자동으로 워크트리에 복사/배치합니다.
   - 자동 배치 후에도 워크트리에 Capsule 파일이 존재하지 않으면 워커가 없는 파일을 열거나 엉뚱한 Capsule 로 넘어가는 사고를 막기 위해 fail-closed(**종료 코드 2**)로 기동을 거부합니다.
   - `rework` 명령 사용 시 `--worktree <path>` 를 지정하면 워크트리에도 새 Capsule 사본이 자동 배치되어 수동 `cp` 없이 안전하게 Dispatch 할 수 있습니다.

---

## 1. 제공자별 기동 경로

| 제공자 | 기동 방법 | Orca 감독 |
| --- | --- | --- |
| Claude | `worker-start --agent claude --model <id> --effort <level>` | 예 |
| Codex | `worker-start --agent codex --model <id> --effort <level>` | 예 |
| Antigravity (Gemini) | `terminal create --command "agy ..."` 또는 런처 뒤 `dispatch` (preamble 대체 자동 지원) | 예 |
| OpenCode Zen (MiMo, DeepSeek) | `terminal create --command "opencode"` 뒤 `dispatch --inject` | 예 |
| Kimi Code (OpenRouter 무료) | `dispatch --return-preamble` 뒤 `kimi -m <alias> -p "<preamble>"` | 예 (Dispatch 계보만) |
| Grok Code (`grok`) | `dispatch --return-preamble` 뒤 `grok --model <id> --always-approve "<preamble>"` | 예 (Dispatch 계보만) |

> **Gemini CLI(`gemini`)는 워커로 쓸 수 없습니다.** 개인 계정 지원이 종료되어
> 인증 단계에서 `IneligibleTierError: UNSUPPORTED_CLIENT` 로 끊깁니다
> ("This client is no longer supported for Gemini Code Assist for individuals").
> 2026-08-26 에 워커 하나가 이 인증 대화창에 걸려 멈춰 있었습니다. Gemini 계열은
> **반드시 Antigravity(`agy`)** 로 띄웁니다. 실패는 조용합니다. 워커가 인증 선택
> 화면에서 대기할 뿐 오류로 종료되지 않으므로 `orca_worker_watch.py` 로 확인합니다.

`worker-start --agent` 는 **claude·codex·cursor 만** 받습니다. 그 밖의 CLI 는
2절의 터미널 부착 경로를 씁니다. 두 경로 모두 Task·Dispatch 계보가 남으므로
`worker_done` 권한도 정상입니다.

**Kimi Code 는 세 번째 경로입니다.** TUI 가 주입된 Enter 로 종료하므로
`dispatch --inject` 를 쓸 수 없고, preamble 을 런치 인자로 넘깁니다. 1.5 절을
보십시오.

### 1.0 같은 모델이 여러 CLI 에 있고 가용성은 CLI 마다 다릅니다

**이 문서에서 가장 혼동하기 쉬운 지점입니다.** 모델 이름이 같아도 어느 CLI 로
부르느냐에 따라 쓸 수 있는지가 갈립니다. 한쪽에서 사라져도 다른 쪽은 멀쩡합니다.

| 실제 모델 | OpenCode Zen 무료 풀 | Kimi Code + OpenRouter |
| --- | --- | --- |
| poolside laguna S 2.1 | `laguna-s-2.1-free` — **2026-08-20 소멸** | `or-free/laguna-s` — **정상** |
| nvidia nemotron 3 ultra | `nemotron-3-ultra-free` | `or-free/nemotron-ultra` |
| deepseek v4 flash | `deepseek-v4-flash-free` | OpenRouter 유료 경로만 |
| poolside laguna XS 2.1 | 없음 | `or-free/laguna-xs` |
| cohere north mini | 없음 | `or-free/north-mini` |

**한 CLI 의 가용성을 다른 CLI 의 근거로 쓰지 마십시오.** 2026-08-20 에 이
세션이 Kimi 로 laguna 가 돌아가는 것을 보고 OpenCode 목록이 틀렸다고
판단했습니다. 둘은 서로 다른 제공자를 거치므로 아무 관계가 없습니다.

판정할 때는 **어느 CLI 로 부를 것인지 먼저 정하고, 그 CLI 로 호출해
확인하십시오.** 모델 이름만으로는 판정할 수 없습니다.

### 1.1 모델 ID

Codex 는 `~/.codex/models_cache.json`, Antigravity 는 `agy models` 로 확인합니다.
**잘못된 ID 를 주면 워커가 기동 직후 죽는데 Orca 는 `dispatched`/`ready` 로
표시합니다** (플레이북 4.2).

| 제공자 | 확인된 ID |
| --- | --- |
| Codex | **2026-08-20 재확인**: `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`. 08-14 에 있던 `gpt-5.6-sol-wm` 은 캐시에서 사라졌다 |
| Antigravity | `gemini-3.8-flash-high`, `-medium`, `-low` (3.7·3.6·3.5 도 동일 3단), `gemini-3.1-pro-high`, `gemini-3.1-pro-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium` |
| OpenCode Zen | `opencode models` 로 조회합니다. 1.3 절 참조 |

Antigravity 는 추론 수준이 모델 ID 에 포함되어 있어 `--effort` 를 따로 주지
않습니다.

### 1.2 Antigravity 의 Claude 계열은 별도 한도입니다

`claude-sonnet-4-6` 와 `claude-opus-4-6-thinking` 은 Antigravity 안에서
제공되므로 **사용자 Claude 구독 한도를 소모하지 않습니다.** Google 계열보다
Antigravity 쪽 허용량이 적지만, 다음 상황에서 쓸 자리가 분명합니다.

| 상황 | 선택 |
| --- | --- |
| Claude 주간 한도가 얼마 남지 않았고 판정 품질이 필요하다 | Antigravity `claude-opus-4-6-thinking` |
| 구현·검증이 절차적이고 양이 많다 | Antigravity `gemini-3.8-flash-high` 또는 Codex |
| 최종 승격·컷오버 판정 | 코디네이터가 직접 (위임하지 않습니다) |

한도가 여러 풀로 나뉘어 있다는 점이 핵심입니다. 한 풀이 마르면 작업 등급을
낮추기 전에 **다른 풀의 같은 등급 모델**을 먼저 확인하십시오.

### 1.3 OpenCode Zen 은 무료 풀과 유료 풀이 나뉩니다

`opencode models` 로 조회합니다. **무료 풀은 예고 없이 바뀝니다.** 아래는
2026-08-20 재확인 결과이며, 붙이기 전에 목록을 다시 조회하십시오.

| 풀 | 상태 | 모델 |
| --- | --- | --- |
| `opencode/` (무료) | 2026-08-20 정상 CLI 로 재확인 | `big-pickle`, `deepseek-v4-flash-free`, `hy3-free`, `mimo-v2.5-free`, `muse-spark-1.2-contributor-free`, `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`. `laguna-s-2.1-free` 는 빠졌다 |
| `opencode-go/` (유료) | **세션 쿠키 미설정** | `deepseek-v4-pro`, `kimi-k3`, `kimi-k2.7-code`, `qwen3.8-max`, `qwen3.7-max`, `glm-5.2`, `grok-4.5`, `minimax-m3`, `gpt-5.6-luna`, `mimo-v2.5-pro` 등 |

**목록에서 빠졌다고 삭제된 것이 아닙니다.** 2026-08-20 에
`deepseek-v4-flash-free` 가 `opencode models` 에서 빠지고 호출이
`Model not found` 로 거부됐습니다. **같은 날 아무 조치 없이 복구됐습니다.**
그 사이 로컬 카탈로그(`~/.cache/opencode/models.json`)에는 계속 있었습니다.

| 신호 | 실제 |
| --- | --- |
| `opencode models` 에 없음 | 일시적일 수 있습니다. 카탈로그를 함께 보십시오 |
| `Model not found` + `Unexpected server error` | 서버측 일시 장애에서도 이 형태가 납니다 |
| 유료 variant 의 `requires explicit opt in` | 중국 호스팅 opt-in 은 **별개 사유**입니다 |

**한 번의 실패로 제외 판정을 내리지 마십시오.** 2026-08-20 에 이 세션이 목록
이탈과 1회 실패만 보고 삭제로 판정해 라우터에서 뺐다가, 재호출이 성공해
되돌렸습니다. 제외는 시간을 두고 반복 확인한 뒤에 합니다.

`laguna-s-2.1-free` 는 OpenCode Zen 무료 풀에서 **실제로 빠졌습니다.** 정상
CLI 로도 `Model not found` 입니다.

**같은 모델이 다른 제공자에 있다는 점을 혼동하지 마십시오.** poolside laguna 는
OpenRouter 를 거쳐 Kimi Code 로 쓸 수 있으며, 이 저장소에는 `or-free/laguna-s`
로 등록되어 있습니다(1.5 절). OpenCode 쪽 소멸은 OpenRouter 쪽 가용성과
무관합니다. 2026-08-20 에 이 세션이 두 경로를 혼동해, Kimi 로 쓰이고 있는 것을
근거로 OpenCode 목록이 틀렸다고 잘못 판단했습니다.

`opencode-ai postinstall` 오류로 CLI 호출이 전부 막힌 일도 같은 날 있었습니다.
증상이 `Model not found` 와 섞이므로, 목록을 근거로 쓰기 전에 **CLI 자체가
정상인지 먼저 확인하십시오.** 조치는 설치 디렉터리에서
`node postinstall.mjs` 입니다.

### 1.4 Cerebras 는 별도 프로바이더입니다

`opencode.json` 에 `cerebras` 프로바이더가 등록되어 있어 OpenCode 무료·유료 풀과
**무관한 별도 한도**를 씁니다. 자격증명은 `.env` 의 `CEREBRAS_API_KEY` 이며
설정 파일에는 `{env:CEREBRAS_API_KEY}` 참조만 들어 있습니다.

| 모델 ID | 컨텍스트 / 출력 |
| --- | --- |
| `cerebras/gemma-4-31b` | 65,536 / 8,192 |
| `cerebras/gpt-oss-120b` | 65,536 / 8,192 |
| `cerebras/zai-glm-4.7` | 65,536 / 8,192 |

**설정 구조가 중요합니다.** `@ai-sdk/openai-compatible` 는 연결 설정을
`options` 안에서 찾습니다. `baseURL` 과 `apiKey` 를 프로바이더 최상위에 두면
프로바이더는 등록되고 모델 목록도 나오지만 **호출 시점에 URL 이 `undefined` 가
됩니다.**

```
Error: "undefined/chat/completions" cannot be parsed as a URL.
```

**`.env` 는 읽히지 않습니다.** `{env:CEREBRAS_API_KEY}` 는 셸 환경변수를
참조하며 프로젝트 `.env` 를 자동으로 불러오지 않습니다. 값이 `.env` 에만 있으면
`Unauthorized: Wrong API Key` 가 납니다.

```bash
export CEREBRAS_API_KEY=$(awk -F= '/^CEREBRAS_API_KEY=/{print $2}' .env)
opencode run -m cerebras/gemma-4-31b "reply with OK only"   # OK 가 나와야 합니다
opencode -m cerebras/gemma-4-31b                            # 그 뒤에 기동
```

**기동 전에 `opencode run` 으로 1회 호출해 응답을 확인하십시오.**
`opencode models` 에 보이는 것은 설정 파일을 읽었다는 뜻일 뿐입니다. 2026-08-14
세션에서 코디네이터가 목록만 확인하고 설정을 병합했고, 워커를 붙인 뒤에야 위 두
오류를 발견했습니다.

**컨텍스트가 65K 로 Antigravity 계열보다 작습니다.** 큰 파일을 여러 개 읽어야
하는 작업은 맞지 않습니다. 지시서가 자족적이고 읽을 범위가 좁은 감사·분석에
적합합니다.

오류별 원인입니다.

| 오류 | 원인 |
| --- | --- |
| `"undefined/chat/completions" cannot be parsed as a URL` | `baseURL` 이 `options` 밖에 있습니다 |
| `Unauthorized: Wrong API Key` | 셸에 `CEREBRAS_API_KEY` 가 없습니다. `.env` 는 자동으로 읽히지 않습니다 |
| `payment_required_error` | Cerebras Billing 에서 무료 크레딧이 활성화되지 않았습니다 |

세 오류 모두 `opencode models` 는 정상으로 보입니다. **목록에 보이는 것을 사용
가능의 근거로 쓰지 마십시오.**

---

`orca account list` 가 `opencodeGo` 를 `Session cookie not configured` 로
보고하는 대상이 아래쪽 유료 풀입니다. **무료 풀은 그 설정과 무관하게 지금
동작합니다.** 쿠키를 붙이면 유료 풀과 Orca 한도 표시가 함께 열립니다.

모델을 지정해 띄우는 형식입니다.

```bash
opencode -m opencode/nemotron-3-ultra-free
opencode run --dir <워크트리> -m opencode/mimo-v2.5-free "<preamble>"
```

**같은 무료 풀 안에서도 편차가 큽니다.** 2026-08-20 쓰기 과제 경합
(`run_d2fd971f7daa`)에서 여섯 중 셋만 완주했습니다. 아래 시간은 1회 실행값이며
통과 셋 사이의 순위 근거가 아닙니다.

| 모델 | 판정 | 근거 |
| --- | --- | --- |
| `opencode/nemotron-3-ultra-free` | **쓰기 통과** | 9분01초. `FREE_POOL_ORDER` 선두이나 동등 합격군 |
| `opencode/deepseek-v4-flash-free` | **쓰기 통과** | 11분31초. 사양 결함을 유일하게 `ask` 로 제기 |
| `opencode/mimo-v2.5-free` | **쓰기 통과** | 13분58초 |
| `opencode/nemotron-3.5-lightning-free` | **격리** | 4.8KB 지시문에 다국어 토큰이 섞인 무의미 출력. 아래 경고 |
| `opencode/hy3-free` | **격리** | 파일 3개를 읽고 아무것도 쓰지 않은 채 종료 코드 0 |
| `opencode/muse-spark-1.2-contributor-free` | **자격 미달** | 지역 차단. `This model is not available in your country`. 아래 1.4.1 절 |

#### 1.4.1 muse spark 계열은 능력 미달이 아니라 자격 미달입니다

`muse-spark-1.2` 는 컨텍스트 1,048,576 토큰으로 무료 풀 최상위와 동급이라
강해 보입니다. 그래서 "왜 뺐는가" 를 반복해 묻게 됩니다. **능력을 재 본 적이
없습니다.** 1차 경합에서 7초 만에 기동 실패했으므로 `behavioral_score` 는
`null` 이고, 성능을 근거로 뺀 것이 아닙니다.

측정 단위가 `모델 + 제공자 + CLI 하네스` 조합이므로 두 경로를 갈라 적습니다.
모델 이름만 보고 하나로 묶으면 판단을 그르칩니다.

| 스택 | 상태 | 근거 (2026-08-21 확인) |
| --- | --- | --- |
| `opencode/muse-spark-1.2-contributor-free` | 지역 차단 | `This model is not available in your country` |
| `openrouter/meta/muse-spark-1.2` | **무료 아님** | `pricing.prompt` $1.25/M, `completion` $4.25/M |
| `openrouter/meta/muse-spark-1.1` | **무료 아님** | 위와 동일 |

무료 풀 편입 요건은 `pricing.prompt` 와 `pricing.completion` 이 모두 `"0"` 인
것입니다. 현재 편입된 네 slug 는 전부 이 요건을 만족합니다. muse spark 는 두
경로 모두 만족할 방법이 없으므로 **측정 대기 목록이 아니라 자격 미달로
닫았습니다.** 재측정해도 이 사실은 바뀌지 않습니다.

**재검토 트리거는 둘뿐입니다.**

1. OpenRouter 에 `meta/muse-spark-1.2:free` 변종이 등장
2. opencode contributor-free 의 지역 차단 해제

유료 풀 편입은 권하지 않습니다. 유료 자리에는 `gemini-3.8-flash` 와
`claude-sonnet-4-6` 이 실측 기반으로 있고, muse spark 는 능력 데이터가 0 인
상태로 비용을 씁니다. 1M 컨텍스트 축은 `or-free/nemotron-ultra` 가 무료로
이미 커버합니다.

**`nemotron-3.5-lightning` 은 probe 로 걸러지지 않습니다.** 짧은 지시
("OK 만 답하라", "2+2")에는 정상 응답하고, 긴 지시문에서만 무너집니다.
`probe_model()` 은 `ping` 한 마디에 종료 코드 0 이면 통과시키므로 이 유형을
잡을 수 없습니다. **가용성 확인과 적합성 확인은 다른 문제입니다.**

무료 모델에 넘길 작업 범위는 5장 표를 지키십시오. **자동 검증이 정오를
판정해 주는 작업만** 넘기고, 공유 자원 소유권은 주지 않습니다.

### 1.5 Kimi Code 는 OpenRouter 무료 모델을 단발 워커로 씁니다

`kimi` 는 별도 프로필로 OpenRouter `:free` 모델을 고정해 씁니다. 프로필은
`KIMI_CODE_HOME` 으로 가르며, 기본 설정과 분리되어 있습니다.

```bash
KIMI_CODE_HOME=/Users/kwanbum/.kimi-openrouter-free kimi --version   # 0.37.2
```

**`openrouter/free` 라우터를 쓰지 마십시오.** 모델을 무작위로 고르므로 어느
모델이 응답했는지 증적이 남지 않습니다. 아래 별칭은 각각 slug 하나를 고정합니다.

| 별칭 | slug | 컨텍스트 / 최대 출력 | 판정 | 비고 |
| --- | --- | ---: | :---: | --- |
| `or-free/laguna-xs` | `poolside/laguna-xs-2.1:free` | 262,144 / 32,768 | **쓰기 통과** | 11분03초. 무료 풀 2순위. 핵심 불변식을 두 테스트로 쪼개 커버한 유일한 구현 |
| `or-free/nemotron-ultra` | `nvidia/nemotron-3-ultra-550b-a55b:free` | 1,000,000 / 65,536 | **쓰기 통과** | 12분32초. 무료 풀 4순위. `reasoning_effort` 지원 |
| `or-free/laguna-s` | `poolside/laguna-s-2.1:free` | 262,144 / 32,768 | **격리** | 32분간 379KB 출력에 도구 호출 0건. 아래 1.6 절 |
| `or-free/north-mini` | `cohere/north-mini-code:free` | 256,000 / 64,000 | **격리** | 31분50초에 테스트 미착수. 실격선 28분 초과 |

판정 근거는 2026-08-20 쓰기 과제 경합(`run_d2fd971f7daa`)입니다. 그 전의
`pass`/`conditional_pass` 는 **읽기 전용 probe 결과였고 쓰기 적합성을 예측하지
못했습니다.** 당시 네 모델은 감사 6문항을 전부 맞혀 변별되지 않았는데, 같은
네 모델에 쓰기 과제를 주자 둘이 격리됐습니다.

**시간은 순위가 아닙니다.** 스택당 1회 실행이라 무료 엔드포인트의
큐·콜드스타트·429 편차를 분리하지 못했습니다. 통과한 둘은 동등한 합격군입니다.
격리된 둘도 영구 판정이 아니라 재시험 전까지의 배정 중단입니다.

네 slug 모두 2026-08-20 `GET /api/v1/models` 에서 `pricing.prompt`,
`pricing.completion` 이 `"0"` 이고 `supported_parameters` 에 `tools` 와
`tool_choice` 를 포함합니다. 전부 읽기 전용 probe 로 `pwd` 와 `head -1 AGENTS.md`
tool loop 를 완주하고 `worker_done` 까지 보냈습니다 (Run `run_a32b6b614996`).

**기동은 preamble 을 런치 인자로 넘기는 경로만 씁니다.**

**런처를 터미널 명령으로 지정하십시오.** 명령 없는 셸 터미널을 만들고 나중에
`terminal send` 로 kimi 를 띄우면, Orca 는 그 터미널을 에이전트 터미널로
등록하지 않아 **좌측 목록에 워커 행이 생기지 않습니다.** 다른 CLI 워커는 보이는데
Kimi 만 보이지 않아 진행 상태를 눈으로 확인할 수 없게 됩니다. 소급 등록도 되지
않습니다 (2026-08-25 실측).

`scripts/orca_kimi_launch.py` 가 preamble 이 나타날 때까지 기다렸다가 kimi 를
exec 하므로, 터미널을 **먼저** 런처 명령으로 만들 수 있습니다.

```bash
# 1. 런처를 명령으로 지정해 터미널 생성 (여기서 워커 행이 생깁니다)
orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
  --command "uv run python scripts/orca_kimi_launch.py --model or-free/nemotron-ultra"

# 2. Dispatch 해서 preamble 을 받고 워크트리에 씁니다
orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
#    결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 저장하면 런처가 이어받습니다
```

**이 경로는 `taskctl dispatch` 를 거치지 않습니다.** 그래서 0.5 절의 권한 자동 승인
4단계가 빠지고, 코디네이터가 `prepare-worker` 를 따로 부르는 것을 잊으면 워커가
파일 편집 대화창마다 멈춥니다. 2026-08-31 세션에서 실제로 이 일이 일어났고,
절차를 기억에 의존하게 둔 것이 원인이었습니다.

`scripts/orca_agy_launch.py` 는 이제 이를 **스스로 겁니다.** `ORCA_TERMINAL_HANDLE`
환경변수로 자기 터미널을 알아내 `exec` 직전에 분리된 자식을 띄우고, 자식이 agy TUI
기동을 기다렸다가 `prepare_worker_terminal` 을 호출합니다. 결과는
`<워크트리>/.orca/permission_setup.log` 에 남습니다. `ORCA_TERMINAL_HANDLE` 이 없으면
조용히 넘어가지 않고 stderr 에 경고를 남깁니다.

**`start_auto_approve` 와 `enable_file_edit_auto_approve` 를 직접 부르면 안 됩니다.**
그 둘만 부르면 **CLI 종류 메타데이터가 기록되지 않고**, 그 메타데이터로 CLI 를
판정하는 `classify_file_edit_auto_approve_support` 가 fail-closed 로 막혀
accept-edits 를 영영 확보하지 못합니다. 감시기는 떠 있는데 파일 편집 대화창만
계속 보류되는 상태가 되며, 겉으로는 준비가 된 것처럼 보입니다. 2026-08-31 에
이 방식으로 워커가 대화창에 그대로 갇혔습니다. 반드시
`prepare_worker_terminal(terminal, cli_type=..., model=..., launcher=...)` 를
통째로 호출하십시오.

```bash
tail -2 <워크트리>/.orca/permission_setup.log   # [권한설정] 확보: ... 를 확인
```

**다른 런처(`orca_kimi_launch.py`)에는 아직 이 자동화가 없습니다.** 그 경로로 띄웠다면
터미널 생성 직후 다음을 직접 실행하십시오.

```bash
python3 scripts/orca_taskctl.py prepare-worker --terminal <handle> \
  --cli-type <kimi|opencode|...> --model <id> --launcher <런처 경로>
```

런처는 커밋 고지문을 자동으로 덧붙입니다. one-shot 워커가 커밋 없이 완료를
선언하는 사고(21.7 절)를 막기 위한 기본값이며 `--no-commit-notice` 로 끕니다.
빈 파일은 지시문으로 받아들이지 않고 계속 기다립니다.

| 하지 말 것 | 이유 |
| --- | --- |
| `dispatch --inject` | Kimi TUI 는 주입된 Enter 로 **종료**합니다 |
| `-p` 와 `-y`/`--auto` 병용 | 2026-08-20 실측에서 `error: Cannot combine --prompt with --yolo.` 와 `... with --auto.` 로 종료 코드 1 입니다. `--help` 에는 이 제약이 적혀 있지 않습니다 |
| 대화형·다단계 감독 Task 배정 | `-p` 는 one-shot 입니다. 자족적 지시서 1개로 끝나는 Task 만 줍니다 |
| 커밋을 acceptance 에 안 적고 쓰기 Task 배정 | 완료 요약만 출력하고 커밋 없이 세션이 끝납니다 ([`orca_do_not_repeat.md`](orca_do_not_repeat.md) 21.7) |

**one-shot 워커는 완료 선언 뒤 사라집니다.** 세션이 끝나면
`orca orchestration send` 도 `dispatch --inject` 도 닿지 않습니다. 완료 요약이
터미널에 뜬 그 시점에 `git -C <워크트리> log --oneline main..HEAD | wc -l` 로
커밋을 직접 확인하고, 0 이면 종료 시 출력된 재개 핸들로 다시 띄워 커밋만
시키십시오.

```bash
KIMI_CODE_HOME=~/.kimi-openrouter-bakeoff kimi -r <session_id> -p "<커밋 지시>"
```
| 격리 모델(`laguna-s`, `north-mini`) 배정 | 위 표를 보십시오. 쓰기 과제에서 완주하지 못합니다 |
| 공유 자원 소유·마감 있는 Task 배정 | `:free` 는 provider capacity 에 따라 429 가 납니다 |

**쓰기 Task 를 주려면 프로필의 권한 모드를 바꿔야 합니다.**

`-p` 는 `-y`/`--auto` 와 병용할 수 없지만, 그것이 쓰기 불가를 뜻하지는
않습니다. 승인 정책은 `config.toml` 의 `default_permission_mode` 가 정하고
`-p` 도 그 값을 따릅니다. 기본 프로필은 `manual` 이라 파일 쓰기가 막힙니다.

```bash
cp -R ~/.kimi-openrouter-free ~/.kimi-openrouter-bakeoff
# 사본에서만 default_permission_mode 를 "auto" 로 바꿉니다
KIMI_CODE_HOME=~/.kimi-openrouter-bakeoff kimi -m <alias> -p "<preamble>"
```

**기본 프로필을 고치지 마십시오.** 무료 모델이 승인 없이 파일을 쓰게 되는
설정이므로, 격리 워크트리에서 도는 쓰기 워커 전용 사본으로만 씁니다.
2026-08-20 에 이 경로로 `laguna-xs` 와 `nemotron-ultra` 가 쓰기 과제를
완주했습니다.

**요청 한도는 근거 종류를 구분해 적습니다.**

| 항목 | 값 | 근거 |
| --- | --- | --- |
| `:free` 계정 일일 한도 | 1,000 requests/day (누적 $10 이상 구매 계정) | OpenRouter 공식 FAQ |
| `:free` 분당 한도 | 20 RPM | OpenRouter 공식 FAQ |
| 계정 상태 | `is_free_tier: false`, 누적 usage 10.23 | 2026-08-20 `GET /api/v1/key` 실측 |
| 명시적 상한 설정 | `limit`, `limit_remaining` 모두 null | 2026-08-20 `GET /api/v1/key` 실측 |

**실패와 재시도도 요청 한도를 씁니다.** 이번 검증은 모델당 direct 1회 + probe
1회로 총 8회를 썼고 429 를 만나지 않았습니다. `/api/v1/key` 에서 일일 잔여
횟수는 확인되지 않으므로, 한도 근접 여부는 **호출 횟수를 직접 세어** 판단합니다.

**한 터미널은 활성 Dispatch 를 하나만 가집니다.** 재 Dispatch 할 때는 새
터미널을 만드십시오 (`already has an active dispatch`). 또한 `task-create` 와
`dispatch` 는 Run 코디네이터로 바인딩된 터미널만 수행할 수 있습니다
(`consumer_fenced`).

**stderr 에 사고 과정이 길게 흐릅니다.** nemotron-ultra 와 north-mini 가
그렇습니다. `-p` 단발 모드의 stdout 은 최종 답만 담으므로 수집은
`2> /dev/null` 없이도 파이프로 분리됩니다.

---

### 1.6 Codex 는 Capsule 배치 경합에 주의하십시오

`worker-start` 는 워크트리 생성과 워커 기동을 한 번에 합니다. 그래서 기동 뒤에
Capsule 을 복사하면 워커가 그 사이에 정본을 찾으러 갔다가 없는 것을 봅니다.
`.orca/` 는 gitignore 대상이라 새 워크트리에 따라가지 않습니다.

**2026-09-02 세션에서 이 경합으로 워커 네 대가 계약 없이 작업했거나 멈췄습니다.**

| 워커 | 결과 |
| --- | --- |
| E1 | arq cron 대신 OS cron 생성기를 만들고 코디네이터 소유 문서를 수정 |
| E2 | 지정한 라우터가 아닌 다른 라우터에 엔드포인트 추가 |
| E3 | Capsule 없음으로 조사 중단 |
| G1 | Capsule 없음으로 Task 가 `failed` 로 종결 |

공식 스킬의 기본은 `worker-start --worktree current` 입니다. 현재 트리에는
`.orca/capsules` 가 이미 있으므로 이 경합이 없습니다. **새 워크트리를 만들
때만** 아래 런처를 쓰십시오. 워크트리가 생기는 즉시 Capsule 과 `.env` 를 넣어
경합 창을 좁힙니다.

```bash
uv run python scripts/orca_codex_launch.py --task <task_id> --name <워크트리명>
# 추론 수준을 올릴 때만 --effort high 를 붙입니다
```

`worker-start` 를 직접 부르는 저수준 경로도 여전히 유효하지만, **그때는
워크트리가 생기자마자 Capsule 을 넣고 워커에게 배치 사실을 즉시 고지해야
합니다.** 고지 없이 두면 워커는 이미 없는 파일을 본 상태로 진행합니다.

### 1.7 Grok Code 는 독립 리뷰어의 기본 경로입니다

리뷰어는 빌더와 다른 계열이어야 합니다. 빌더가 Antigravity Gemini 인 동안
`TIER_POLICY` 의 리뷰어 주 모델은 `qwen-plus` 이지만, Alibaba Token Plan 잔량이
마르면 대체 경로가 필요합니다. `grok` 이 그 자리입니다.

| 항목 | 값 |
| --- | --- |
| 실행 파일 | `/opt/homebrew/bin/grok` |
| 라우터 등록 모델 | `grok-4.6`, `grok-4.5` (둘 다 `auto_selectable=False`, 수동 지정 전용) |
| provider | `grok` |
| 기동 경로 | `dispatch --return-preamble` 뒤 `terminal send` |

Kimi 와 같은 계열의 경로입니다. TUI 에 지시를 주입하지 않고 preamble 을
런치 인자로 넘깁니다.

```bash
orca terminal create --worktree path:<워크트리> --title "리뷰어 grok" --command "zsh" --json
orca orchestration dispatch --task <task_id> --to <handle> --run <run_id> --return-preamble --json
# 반환된 preamble 을 <워크트리>/.orca/preamble_grok.txt 에 기록한 뒤
orca terminal send --terminal <handle> \
  --text 'grok --model grok-4.6 --always-approve "$(cat .orca/preamble_grok.txt)"' --enter --json
```

`--always-approve` 라 승인 대화창에 걸리지 않으므로 `shift+tab` 전송이나
자동 승인 감시기가 필요 없습니다. 읽기 전용 리뷰어에게만 쓰십시오. 쓰기 범위가
있는 빌더에 `--always-approve` 를 주면 승인 없이 파일을 고칩니다.

**effort 를 올리지 마십시오.** 추론 등급 상향은 코디네이터 등급이며 워커에는
쓰지 않습니다.

**이 경로는 `worker-start` 가 아니므로 비감독입니다.** `worker_dispatches` 행이
생기지 않아 `worker-release` 가 `retained` / `no_owned_resource` 로 돌아옵니다.
회수는 `orca terminal close --terminal <handle>` 로 직접 하고, 비감독을 선택한
사실을 인수인계에 적으십시오.

2026-09-05 세션에서 이 경로로 리뷰어 세 대(T10, T-01, C-01/C-02)를 띄웠고
전부 정상 판정을 반환했습니다. 같은 날 `qwen3.7-plus` 는 할당량 소진 상태였습니다.

---

---

## 2. 비 Claude·Codex CLI 를 워커로 붙이는 절차

Antigravity(`agy`) 워커는 직접 TUI를 띄울 경우 스플래시 화면에서 정체되는 현상이 있으므로, **런처(`scripts/orca_agy_launch.py`)를 터미널 명령으로 지정하고 `dispatch --launcher`로 투입하는 경로**가 표준 정본입니다.

```bash
# 1. 격리 워크트리 생성
orca worktree create --name <이름> \
  --repo path:/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box \
  --base-branch main --setup skip --json

# 2. 워크트리 일괄 준비 (.env 복사, Antigravity 신뢰 등록, pre-commit 훅 확인/설치)
uv run python scripts/orca_prepare_worktree.py <워크트리>
# 준비 여부만 판정할 때:
# uv run python scripts/orca_prepare_worktree.py <워크트리> --check

# 3. 그 워크트리에 런처를 명령으로 지정한 터미널 생성 (스플래시 정체 방지)
orca terminal create --worktree path:<워크트리> \
  --title "<섹션명>" \
  --command "uv run python scripts/orca_agy_launch.py --model gemini-3.8-flash-high" --json

# 4. Task 투입 (dispatch --launcher 가 preamble 추출 -> <워크트리>/.orca/preamble_{task_id}_{dispatch_id}_{nonce}.txt 고유 파일 기록 -> 런처 소비 후 즉시 삭제 확인 -> 감시기 부착을 일괄 처리합니다)
uv run python scripts/orca_taskctl.py dispatch --intent <의도.yaml> --terminal <handle> --launcher

# 5. 실존 및 진행 확인
orca orchestration dispatch-show --task <task_id> --json
```

`terminal create` 에는 `--repo` 플래그가 없습니다. `--worktree` 만 받습니다.

**3 단계와 4 단계 사이에 두 가지를 반드시 하십시오.** 빠뜨리면 오류 문구가
원인을 가립니다 ([`orca_do_not_repeat.md`](orca_do_not_repeat.md) 21장).

| 조치 | 이유 |
| --- | --- |
| `orca terminal read` 로 런처가 대기 중인지 확인 | `preamble 대기 중: .orca/preamble.txt` 또는 대기 안내 출력이 화면에 떠 있는지 확인합니다 |
| `.orca/capsules/` 를 **통째로** 워크트리에 복사 | Task `spec` 은 생성 후 변경할 수 없어 잠정 ID 경로를 가리킵니다. 실제 ID 디렉터리 하나만 복사하면 워커가 없는 파일을 엽니다 |
| 워크트리 잔여 preamble 부재 확인 | 워크트리에 이전 시도의 미소비 preamble(`preamble_*.txt`)이 남아있으면 새 dispatch 가 거부(종료 코드 2)됩니다 |

```bash
cp -R <주 저장소>/.orca/capsules <워크트리>/.orca/
```

`create` 로 만든 Task 를 `dispatch` 로 이을 때는 `create` 출력의 `task_id` 와
`capsule` 을 `--task-id`, `--capsule` 로 넘기십시오. 넘기지 않으면 Intent
파일명으로 ID 를 유추하다 `Task not found` 로 끝납니다.

> **미해결 항목**: `source_commit` 자동 갱신은 코디네이터 소유 파일 충돌 방지를 위해 이번 워커 준비 범위에서 제외되었습니다.

### 2.1 워크트리 준비 도구 (`scripts/orca_prepare_worktree.py`)

기존에 수동으로 수행하던 `.env` 복사와 `scripts/orca_trust_worktree.py` 호출, 그리고 누락되기 쉬운 `pre-commit` 훅 점검을 단일 명령으로 묶어 자동화합니다.

1. **`.env` 배치**: 주 저장소의 `.env`를 워크트리로 복사하며, 이미 존재하면 건너뜁니다 (환경변수 값은 출력하지 않음).
2. **폴더 신뢰 사전 등록**: Antigravity CLI의 `trustedWorkspaces` 및 `trustedFolders.json`에 워크트리 절대경로를 사전 등록하여 기동 직후의 다이얼로그 차단을 방지합니다.
3. **pre-commit 훅 확인 및 설치**: 워크트리 환경에서 Git `pre-commit` 훅의 실존 및 실행 권한을 확인하고, 미설치 시 자동으로 `pre-commit install`을 수행하여 검증 생략 커밋을 방지합니다.

`--check` 옵션을 주면 파일이나 설정을 변경하지 않고 세 항목의 준비 상태만 검사하며, 미준비 항목이 하나라도 있을 경우 종료 코드 1을 반환합니다. 준비 실행도 먼저 대상과 주 저장소가 같은 Git common directory를 공유하는지 검증하므로, 비Git 디렉터리나 다른 저장소에는 `.env`·신뢰 설정·훅을 변경하지 않습니다.

Antigravity 는 승인 결과를 `~/.gemini/antigravity-cli/settings.json` 의
`trustedWorkspaces` 배열에 **경로 문자열 그대로** 넣습니다. 사용자가 언젠가
"다음부터 묻지 않기" 를 눌렀더라도 그것은 그때 그 폴더를 등록한 것이고,
`orca worktree create` 로 새로 생긴 경로에는 적용되지 않습니다. 설정이 듣지
않는 것이 아니라 키가 경로입니다.

다이얼로그가 떠 있는 동안 주입한 Task 는 대화창에 먹혀 사라집니다. 사람이
직접 승인해야 워커가 시작하므로 병렬 기동이 그 자리에서 멈춥니다.

**터미널을 띄우기 전에 `scripts/orca_prepare_worktree.py` 로 등록하십시오.** 그러면 다이얼로그가 뜨지 않습니다.

`trustedWorkspaces` 와 `~/.gemini/trustedFolders.json` 두 곳을 함께 채우고,
쓰기 전에 `.orca-bak` 백업을 남기며, 이미 등록된 경로는 건너뜁니다. 두 파일의
읽기·수정·쓰기는 프로세스 간 잠금으로 직렬화하고 고유 임시 파일로 원자 교체합니다.
`trustedFolders.json`이 처음부터 없어도 생성하며, 두 번째 파일 쓰기가 실패하면
첫 번째 파일까지 원문으로 복구합니다.

**생성 직후 빈 엔터를 보내는 방식에 의존하지 마십시오.** CLI 가 다이얼로그를
그리기 전에 입력이 도착하면 그대로 소비되고 다이얼로그는 화면에 남습니다.
2026-08-22 에 터미널 3대를 연속 생성하면서 이 순서로 실패했고, 결국 사용자가
세 번 직접 승인했습니다.

### 2.2 파일 편집 승인은 통합 준비 상태 기계(prepare_worker_terminal)를 통해 자동 전환됩니다

폴더 신뢰를 미리 등록해도 **파일 편집·생성 승인은 따로 뜹니다.** 전역
`permissions.allow` 와도 무관합니다. 워커는 첫 편집에서 멈추고, 코디네이터가
알아채지 못하면 사람이 발견할 때까지 유휴로 남습니다.

다이얼로그 하단의 `shift+tab to auto-approve file edits` 가 해제 수단입니다.
현재 `scripts/orca_taskctl.py dispatch` 및 런처 경로는 통합 준비 함수 `prepare_worker_terminal` (또는 CLI 서브커맨드 `prepare-worker`)을 통해 다음을 자동으로 수행합니다:
1. **메타데이터 우선 판정**: 기동 시점에 기록한 메타데이터(`{terminal}.meta.json`)를 통해 대상 CLI 가 Antigravity 계열인지 판정합니다.
2. **모드 선확인 및 안전 순환**: 현재 화면을 먼저 읽어 이미 `accept-edits` 면 추가 전송을 건너뛰고, `plan` 모드로 빠져 있으면 `accept-edits` 로 복구 순환 전송을 수행합니다.
3. **Cursor 및 미식별 CLI 차단 (fail-closed)**: **Cursor CLI 는 `shift+tab` 이 Plan Mode(읽기 전용, 편집 금지) 전환이므로 전송하지 않고 차단합니다.** 미식별 CLI 역시 기본 차단됩니다.
4. **Antigravity 지시 투입 대체 경로**: `--inject` 가 `agent_prompt_blocked` 로 실패하는 경우 자동으로 `--return-preamble` 로 지시문을 추출하여 `terminal send` 로 전달하고 Enter 투입 및 사후 도달 검증을 완료합니다.

| 구분 | 자동 처리 (`scripts/orca_taskctl.py dispatch` / `prepare-worker`) | 수동 대체 (Antigravity 전용 수동 실행) |
| --- | --- | --- |
| 동작 방식 | `prepare_worker_terminal` 상태 기계를 통해 메타데이터 확인 -> 신뢰 승인 -> 감시기 -> 모드 안전 순환 | `orca_taskctl.py prepare-worker --terminal <handle>` |
| 순환 가드 | 이미 `accept-edits` 면 키 미전송, `plan` 상태면 `accept-edits` 로 안전 복구 (상한 3회) | 화면 확인 후 필요한 경우에만 `$'\x1b[Z'` 전송 |
| Cursor 대응 | Cursor 계열 감지 시 자동 전송 차단 (Plan Mode 오전환 방지) | 수동 전송 금지 |
| 미식별 대응 | 식별 불가 시 자동 전송 차단 (fail-closed, `--enable-file-edit-auto-approve` 로 강제 가능) | 신중 확인 후 필요 시에만 수동 실행 |
| 지시 투입 fallback | Antigravity `--inject` 실패 시 `--return-preamble` + `terminal send` 자동 전환 | 수동으로 preamble 추출 후 `terminal send` |
| 비활성화 | `ORCA_DISABLE_AUTO_APPROVE=1` 환경변수 시 자동 억제 | 해당 없음 |
| 실패 처리 | Dispatch 중단 없이 stderr 안내 및 수동 조치 명령 안내 | 사용자가 직접 실행 후 상태 확인 |

수동 확인 및 복구 명령:

```bash
# 통합 준비 절차 수동 실행
python3 scripts/orca_taskctl.py prepare-worker --terminal <handle> --cli-type antigravity

# 수동 모드 전환 전송 (직접 키 전송 시)
orca terminal send --terminal <handle> --text $'\x1b[Z'
orca terminal read --terminal <handle> | tail -3   # Accept-edits mode 확인
```

`\x1b[Z` 가 shift+tab 입니다. 성공하면 하단 상태줄에
`accept-edits` 표지가 나타납니다.

자동 승인은 쓰기 범위를 넓히지 않습니다. Capsule 의 `allowed_write_files` 는
Level 1 게이트 2 가 병합 전에 따로 검사하므로, 범위 밖 파일을 만들면 승인
여부와 무관하게 게이트에서 걸립니다.

명령 단위 권한(`permissions.allow`)은 이와 별개이며 전역입니다. `uv *`,
`git *`, `python3 *`, `pytest *` 같은 와일드카드가 이미 등록되어 있어 대개
다시 묻지 않습니다. 워커 기동에서 걸리는 것은 대부분 명령 승인이 아니라 폴더
신뢰입니다.

### 2.3 통제면 3대 계약: 역할별 고지문 분기, Preamble 격리 수명주기, 리뷰어 독립성 강제

2026-09-04 외부 진단 및 실측에서 발견된 통제면 3대 결함(역할 혼선으로 인한 리뷰어 불법 커밋, 고정 preamble 재사용으로 인한 지시문 오염, 리뷰어 독립 provider 정책 우회)을 영구 차단하기 위해 다음 3대 규약이 기계적으로 강제됩니다:

#### 2.3.1 역할별 Capsule 고지문 분기 및 커밋 의무 제어
`scripts/orca_taskctl.py` 의 `build_capsule_notice` 는 Task 의 역할(`role`)과 반환 계약(`return_contract`)을 파싱하여 고지문을 엄격하게 분기합니다:
- **Reviewer 고지문**: 소스 코드 수정 금지, 커밋 생성 금지 명시, `ORCA_REVIEW_DONE_V2` 반환 계약 및 사전 검증 명령(`python3 scripts/validate_review_report.py --capsule <capsule> --report <report>`)만 주입합니다. 빌더용 커밋 의무(`commit_count` 검사, 0개 시 escalation), `allowed_write_files` 범위 문구, `ORCA_WORKER_DONE_V2`, guard 안내는 일절 주입하지 않습니다.
- **Builder 고지문**: `allowed_write_files` 가 비어 있지 않은 경우에만 커밋 생성 의무(`commit_count` 가 0이면 escalation)와 `ORCA_WORKER_DONE_V2` 및 `orca_worker_done_guard.py` 안내를 주입합니다. 쓰기 범위가 없는 읽기 전용 빌더는 커밋 의무를 주입하지 않습니다.
- **역할 불일치 방지**: Capsule 에 선언된 `role` 과 Intent 또는 CLI 인자로 지정된 `role` 이 상이하면 Dispatch 단계에서 종료 코드 1(`capsule_spec_error`)로 즉시 중단합니다.

#### 2.3.2 시도 단위 고유 Preamble 수명주기 및 격리 파손 방지
- **고유 파일명 발행**: 고정 파일명(`.orca/preamble.txt`) 재사용을 전면 금지하고, 시도마다 고유한 파일명(`preamble_{task_id}_{dispatch_id}_{nonce}.txt`)을 워크트리 `.orca/` 에 발행합니다.
- **런처 즉시 소비 및 삭제**: 런처(`scripts/orca_agy_launch.py`)는 워크트리 내의 고유 preamble 파일을 감지하여 읽은 즉시 삭제(`unlink`)하고 표준 출력에 소비 완료 표지를 남깁니다.
- **다중 후보 거부(Fail-Closed)**: 런처 대기 시 워크트리에 둘 이상의 preamble 후보(`preamble_*.txt`)가 발견되면 어느 것도 조용히 고르거나 소비하지 않고, 남아 있는 후보 파일 목록을 표준 에러로 출력한 뒤 즉시 기동을 거부(`ValueError`)합니다.
- **잔여 preamble 격리 가드**: 워크트리에 이전 시도의 소비되지 않은 잔여 preamble 파일(`preamble_*.txt`)이 남아 있으면 새 Dispatch 를 종료 코드 2(`unconsumed_preamble_exists`)로 거부하여 지시문 교차 오염을 원천 차단합니다.

#### 2.3.3 리뷰어 독립 Provider 강제 및 명시 모델 우회 차단
- **빌더 Provider 자동 배제**: 리뷰어 모델 배정 시 빌더의 provider 계열(예: gemini, qwen 등)을 `exclude_providers` 에 전달하여 동일 계열 모델이 배정되지 않도록 강제합니다.
- **다층 방어 및 공백/None 정규화**: `select_model` 과 `resolve_dispatch_model` 양측에서 `builder_provider` 에 대해 `None`, 빈 문자열, 공백/탭(`\t`, `\n` 등)을 strip 정규화하여 `unknown` 으로 판정합니다.
- **빌더 Provider 미상 시 Fail-Closed**: 위험도가 `medium` 또는 `high` 이거나 쓰기 권한이 있는 리뷰어 Task 에서 빌더 provider 가 확인되지 않으면 경고가 아닌 오류(`ModelRoutingError`)로 배정을 즉시 중단합니다.
- **명시 모델(`--model`) 우회 차단**: 사용자가 `--model` 로 명시 지정하더라도 (1) `MODEL_POOL` 미등록 모델, (2) 코디네이터 전용 모델(`codex`), (3) 리뷰어인 경우 빌더와 동일한 provider 의 모델을 지정하면 오류를 발생시키고 기동을 거부합니다.

---

## 3. 막히는 지점과 조치

실측으로 확인한 실패 두 건입니다.

| 오류 | 원인 | 조치 |
| --- | --- | --- |
| `terminal_worktree_mismatch` | `worker-start --terminal` 에 `--worktree` 를 생략하면 Run 의 기본 워크트리를 가정합니다 | `--worktree path:<트리>` 를 함께 지정합니다 |
| `Agent startup blocked: codex-trust-workspace` | `worker-start` 의 준비 게이트가 Codex 기준입니다. 비 Codex TUI 가 `>` 프롬프트로 정상 대기 중이어도 차단됩니다 | `worker-start` 를 포기하고 `dispatch --to <handle> --inject` 로 투입합니다 |

두 번째는 `--retry-of` 로도 풀리지 않습니다 (`task_not_startable`). Task 를
`ready` 로 되돌린 뒤 `dispatch --inject` 를 쓰는 것이 유일한 경로입니다.

### 3.1 오해하기 쉬운 신호

| 신호 | 실제 의미 |
| --- | --- |
| `orca account list` 의 `status: unavailable` | Orca 가 그 제공자의 사용량·한도를 읽지 못한다는 뜻입니다. CLI 기동 가능 여부와 무관합니다 |
| Antigravity 상태바 `AI: Out of credits` | 실제 호출은 성공할 수 있습니다. 표시를 근거로 불가 판정하지 마십시오 |
| Antigravity 배너 `You are currently not signed in` | 계정명·플랜 표시와 함께 찍히며, 그 상태에서도 호출이 성공했습니다 |

판정 전 확인 명령입니다.

```bash
agy --print "reply with OK only" --print-timeout 60s
```

2026-08-14 12:40 실행 결과는 `OK`, 종료 코드 0 이었습니다. 같은 시각 상태바에는
`AI: Out of credits` 가 떠 있었습니다.

### 3.2 Orca 밖 터미널은 붙일 수 없습니다

`--terminal` 에는 `orca terminal list` 에 나오는 핸들만 들어갑니다. macOS
기본 터미널이나 다른 앱에서 띄운 CLI 는 Orca 가 보지 못하므로 부착 대상이
아닙니다. 반드시 `orca terminal create` 로 만든 터미널에서 띄우십시오.

---

### 3.3 기동은 절반입니다. 도달을 확인하십시오

**이 문서의 기동 경로를 따랐다고 워커가 일을 시작한 것은 아닙니다.**
2026-08-14 세션에서 이 문서대로 안티그래비티 워커 3대를 띄웠고 `dispatch
--inject` 가 세 번 모두 `ok: true` 를 반환했지만, **셋 다 6분간 빈 프롬프트에
멈춰 있었습니다.**

부팅 중 워크스페이스 신뢰 확인 대화창이 주입된 키 입력을 먹습니다. Orca 쪽
기록은 정상으로 남아 어디에서도 오류가 보이지 않습니다.

| 확인할 것 | 명령 | 실패 신호 |
| --- | --- | --- |
| 주입 도달 | `orca terminal read --terminal <handle>` | 배너와 빈 `>` 만 보임 |
| 메시지 대기열 | `orca orchestration check --terminal <handle>` | `No messages.` |
| 실제 진척 | `git -C <워크트리> log --oneline main..HEAD \| wc -l` | 5분 넘게 0 |

`ps` 로 CLI 프로세스가 살아 있는 것을 확인하는 것은 **근거가 아닙니다.** 지시를
받지 못한 CLI 도 정상적으로 떠 있습니다.

도달하지 않았으면 `terminal send` 로 직접 전달합니다. 절차는
[`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 5.2 절에
있습니다.

### 3.4 신뢰 확인 대화창은 모든 전달 경로를 막습니다

`orca worktree create` 로 만든 새 경로에서 Antigravity CLI 는 워크스페이스 신뢰
확인 대화창을 **반드시** 띄웁니다.

```
Do you trust the contents of this project?
> Yes, I trust this folder
  No, exit
```

**주입 방식과 인자 방식의 결과가 다릅니다.**

| 전달 경로 | 대화창이 열려 있을 때 |
| --- | --- |
| `dispatch --inject` | 키 입력이 대화창에 먹혀 **유실**. Orca 는 `ok: true` 로 보고 |
| `terminal send` | 같음 |
| `agy -i "<프롬프트>"` | **유실 없음.** 다만 승인까지 실행이 시작되지 않음 |

`agy -i` 를 "유실 지점이 없는 권장 경로" 로만 기억하면 승인 대기를 정체로
오판합니다. 2026-08-15 T6 실행 검증에서 확인했습니다
([`orca_v2_runtime_smoke_20260815.md`](orca_v2_runtime_smoke_20260815.md) V.6).

기동 절차는 세 단계입니다.

```bash
orca terminal create --worktree name:<wt> --command "bash <프롬프트 포함 런처>"
orca terminal send --terminal <handle> --enter --text ""   # 신뢰 승인
orca terminal read --terminal <handle> | tail -5           # 진행 확인
```

---

### 3.5 이 경로의 워커는 감독 목록에 없습니다

`terminal create` + 주입으로 붙인 워커는 Dispatch 계보는 남지만 **감독 워커로
등록되지 않습니다.**

| 명령 | `worker-start` 경로 | `terminal create` + 주입 경로 |
| --- | --- | --- |
| `orca orchestration worker-list` | 행이 나옵니다 | **나오지 않습니다** |
| `orca orchestration worker-read` | 출력을 읽습니다 | `has no agent terminal` |
| `orca terminal read` | 가능 | **유일한 관측 수단** |

또한 워커 터미널 탭은 **자기 워크트리 그룹**에 들어갑니다. Orca 사이드바가 주
저장소를 보고 있으면 화면에 나타나지 않습니다. `orca terminal list` 로 어느
워크트리 그룹에 있는지 확인하고 사용자에게 알려 주십시오. 워커를 띄웠는데
사용자가 볼 수 없는 상태로 두면 감독이 코디네이터 한 사람에게만 남습니다.

### 3.6 워커 완료 보고 계약 (v2)

기동이 성공해도 완료 보고는
[`orca_task_capsule_v2.md`](orca_task_capsule_v2.md) 3장의 계약을 따릅니다.
상세 분석은 파일 아티팩트로 커밋하고, `worker_done` `--body`는 3문장 이내
요약 + `reportPath`만 전달합니다. 원시 로그나 diff 전문을 `--body`에
붙이지 않습니다. 커밋이 필요한 Task에서 커밋 0이면 `succeeded`를 보내지
않습니다.

---

## 4. 같은 탭 분할 주의

`terminal show` 의 `tabId` 가 코디네이터의 것과 같으면 그 워커는 코디네이터와
같은 탭의 분할 창입니다. 이때 `terminal close --tab` 은 **코디네이터까지
닫습니다.** 닫을 때는 `--tab` 없이 창 단위로만 닫으십시오 (스킬 8.4).

---

## 5. 배정 기준은 별도 문서입니다

어떤 모델에 어떤 작업을 줄지는 이 문서가 아니라
[`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 4장을
따릅니다. 이 문서는 **기동 방법만** 다룹니다.

그 4장의 요지 셋입니다.

1. **코디네이터 토큰이 가장 희소한 자원입니다.** 배정 기준은 작업 난이도가 아니라
   위임 시 코디네이터 토큰이 실제로 줄어드는지입니다
2. **기본 코디네이터는 Codex `gpt-5.6-terra` + effort `medium`** 이며 Claude 구독은
   예비 코디네이터입니다. `gpt-5.6` 별칭은 Sol을 가리키므로 기본값으로 쓰지 않습니다.
   Sol High는 데이터 무손실·컷오버·복잡한 병합의 최종 판정에만 수동 사용합니다. 둘 다
   워커로 쓰지 않습니다. 기본값 변경 전에는 사용자에게 `MODEL_CHANGE_NOTICE`를 보내며,
   Sol High는 사용자 승인 후에만 적용합니다. 상세 매트릭스는
   [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 4.2.1절입니다. 주력
   워커는 Antigravity Gemini Flash입니다
3. **검증·병합 판정·게이트 기준 제정은 위임하지 않습니다.** 절감률은 50~60%
   이며 검증 비용은 남습니다

변하지 않는 원칙만 옮겨 적습니다.

| 항목 | 규칙 |
| --- | --- |
| 공유 자원 소유 | `main` 병합, 서빙 루트, DB 쓰기, 대량 색인은 무료·저가 모델에 주지 않습니다 |
| 판정 작업 | 유의성, 승격, 회귀 판정은 코디네이터 또는 최상위 모델이 합니다 |
| 병합 근거 | 워커 보고가 아니라 코디네이터의 `git diff` 직접 확인입니다 |
| OpenCode 무료 풀 | 결정론적·병렬 조사 전용. 자동 검증이 정오를 판정하는 작업만 넘기고 임계 경로에 두지 않습니다 |
