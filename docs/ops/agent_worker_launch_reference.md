# 에이전트 워커 기동 정본 참조

> **작성일**: 2026-08-14
> **수정일**: 2026-08-15
> **작성 근거**: 2026-08-14 세션에서 코디네이터가 각 경로를 직접 실행해 확인한 결과. Task Capsule v2 워커 실행 계약 반영
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

## 1. 제공자별 기동 경로

| 제공자 | 기동 방법 | Orca 감독 |
| --- | --- | --- |
| Claude | `worker-start --agent claude --model <id> --effort <level>` | 예 |
| Codex | `worker-start --agent codex --model <id> --effort <level>` | 예 |
| Antigravity (Gemini) | `terminal create --command "agy ..."` 뒤 `dispatch --inject` | 예 |
| OpenCode Zen (MiMo, DeepSeek) | `terminal create --command "opencode"` 뒤 `dispatch --inject` | 예 |

`worker-start --agent` 는 **claude·codex·cursor 만** 받습니다. 그 밖의 CLI 는
2절의 터미널 부착 경로를 씁니다. 두 경로 모두 Task·Dispatch 계보가 남으므로
`worker_done` 권한도 정상입니다.

### 1.1 모델 ID

Codex 는 `~/.codex/models_cache.json`, Antigravity 는 `agy models` 로 확인합니다.
**잘못된 ID 를 주면 워커가 기동 직후 죽는데 Orca 는 `dispatched`/`ready` 로
표시합니다** (플레이북 4.2).

| 제공자 | 2026-08-14 확인된 ID |
| --- | --- |
| Codex | `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-sol-wm`, `gpt-5.6-terra`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini` |
| Antigravity | `gemini-3.7-flash-high`, `-medium`, `-low` (3.6·3.5 도 동일 3단), `gemini-3.1-pro-high`, `gemini-3.1-pro-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium` |
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
| 구현·검증이 절차적이고 양이 많다 | Antigravity `gemini-3.7-flash-high` 또는 Codex |
| 최종 승격·컷오버 판정 | 코디네이터가 직접 (위임하지 않습니다) |

한도가 여러 풀로 나뉘어 있다는 점이 핵심입니다. 한 풀이 마르면 작업 등급을
낮추기 전에 **다른 풀의 같은 등급 모델**을 먼저 확인하십시오.

### 1.3 OpenCode Zen 은 무료 풀과 유료 풀이 나뉩니다

`opencode models` 로 조회합니다. 2026-08-14 확인 결과입니다.

| 풀 | 상태 | 모델 |
| --- | --- | --- |
| `opencode/` (무료) | 지금 사용 가능 | `mimo-v2.5-free`, `deepseek-v4-flash-free`, `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`, `laguna-s-2.1-free`, `hy3-free`, `big-pickle` |
| `opencode-go/` (유료) | **세션 쿠키 미설정** | `deepseek-v4-pro`, `kimi-k3`, `kimi-k2.7-code`, `qwen3.8-max`, `qwen3.7-max`, `glm-5.2`, `grok-4.5`, `minimax-m3`, `gpt-5.6-luna`, `mimo-v2.5-pro` 등 |

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
opencode -m opencode/mimo-v2.5-free
opencode -m opencode/deepseek-v4-flash-free
```

무료 모델에 넘길 작업 범위는 5장 표를 지키십시오. **자동 검증이 정오를
판정해 주는 작업만** 넘기고, 공유 자원 소유권은 주지 않습니다.

---

## 2. 비 Claude·Codex CLI 를 워커로 붙이는 절차

```bash
# 1. 격리 워크트리 생성
orca worktree create --name <이름> \
  --repo path:/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box \
  --base-branch main --setup skip --json

# 2. .env 배치 (Git 미추적이라 워크트리에 따라가지 않습니다)
cp <주 저장소>/.env <워크트리>/.env

# 3. 그 워크트리에 CLI 를 띄운 터미널 생성
orca terminal create --worktree path:<워크트리> \
  --title "<섹션명>" --command "agy --model gemini-3.7-flash-high" --json

# 4. 첫 기동이면 폴더 신뢰 프롬프트가 뜹니다. 기본 선택이 신뢰이므로 엔터만 보냅니다
orca terminal send --terminal <handle> --text "" --enter

# 5. Task 투입
orca orchestration dispatch --task <task_id> --to <handle> --inject --json

# 6. 실존 확인
orca orchestration dispatch-show --task <task_id> --json
```

`terminal create` 에는 `--repo` 플래그가 없습니다. `--worktree` 만 받습니다.

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

### 3.4 이 경로의 워커는 감독 목록에 없습니다

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

### 3.5 워커 완료 보고 계약 (v2)

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
닫습니다.** 닫을 때는 `--tab` 없이 창 단위로만 닫으십시오 (스킬 7.4).

---

## 5. 배정 기준은 별도 문서입니다

어떤 모델에 어떤 작업을 줄지는 이 문서가 아니라
[`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 4장을
따릅니다. 이 문서는 **기동 방법만** 다룹니다.

그 4장의 요지 셋입니다.

1. **코디네이터 토큰이 가장 희소한 자원입니다.** 배정 기준은 작업 난이도가 아니라
   위임 시 코디네이터 토큰이 실제로 줄어드는지입니다
2. **주력 워커는 Antigravity Gemini Flash** 이며 Claude 구독은 코디네이터
   전용입니다. 한 풀이 마르면 등급을 낮추기 전에 다른 풀의 같은 등급을 봅니다
3. **검증·병합 판정·게이트 기준 제정은 위임하지 않습니다.** 절감률은 50~60%
   이며 검증 비용은 남습니다

변하지 않는 원칙만 옮겨 적습니다.

| 항목 | 규칙 |
| --- | --- |
| 공유 자원 소유 | `main` 병합, 서빙 루트, DB 쓰기, 대량 색인은 무료·저가 모델에 주지 않습니다 |
| 판정 작업 | 유의성, 승격, 회귀 판정은 코디네이터 또는 최상위 모델이 합니다 |
| 병합 근거 | 워커 보고가 아니라 코디네이터의 `git diff` 직접 확인입니다 |
| OpenCode 무료 풀 | 결정론적·병렬 조사 전용. 자동 검증이 정오를 판정하는 작업만 넘기고 임계 경로에 두지 않습니다 |
