# 에이전트 워커 기동 정본 참조

> **작성일**: 2026-08-14
> **수정일**: 2026-08-21
> **작성 근거**: 2026-08-14 세션에서 코디네이터가 각 경로를 직접 실행해 확인한 결과. Task Capsule v2 워커 실행 계약 반영. 1.5 절은 2026-08-20 Run `run_a32b6b614996` 의 모델별 실측 검증 결과
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
| Kimi Code (OpenRouter 무료) | `dispatch --return-preamble` 뒤 `kimi -m <alias> -p "<preamble>"` | 예 (Dispatch 계보만) |

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

유료 풀 편입은 권하지 않습니다. 유료 자리에는 `gemini-3.7-flash` 와
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

```bash
orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json  # preamble 추출
KIMI_CODE_HOME=/Users/kwanbum/.kimi-openrouter-free kimi -m <alias> -p "<preamble>"
```

| 하지 말 것 | 이유 |
| --- | --- |
| `dispatch --inject` | Kimi TUI 는 주입된 Enter 로 **종료**합니다 |
| `-p` 와 `-y`/`--auto` 병용 | 2026-08-20 실측에서 `error: Cannot combine --prompt with --yolo.` 와 `... with --auto.` 로 종료 코드 1 입니다. `--help` 에는 이 제약이 적혀 있지 않습니다 |
| 대화형·다단계 감독 Task 배정 | `-p` 는 one-shot 입니다. 자족적 지시서 1개로 끝나는 Task 만 줍니다 |
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

## 2. 비 Claude·Codex CLI 를 워커로 붙이는 절차

```bash
# 1. 격리 워크트리 생성
orca worktree create --name <이름> \
  --repo path:/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box \
  --base-branch main --setup skip --json

# 2. 워크트리 일괄 준비 (.env 복사, Antigravity 신뢰 등록, pre-commit 훅 확인/설치)
uv run python scripts/orca_prepare_worktree.py <워크트리>
# 준비 여부만 판정할 때:
# uv run python scripts/orca_prepare_worktree.py <워크트리> --check

# 3. 그 워크트리에 CLI 를 띄운 터미널 생성
orca terminal create --worktree path:<워크트리> \
  --title "<섹션명>" --command "agy --model gemini-3.7-flash-high" --json

# 4. Task 투입
orca orchestration dispatch --task <task_id> --to <handle> --inject --json

# 5. 파일 편집 자동 승인 (shift+tab. 빠뜨리면 첫 편집에서 멈춥니다. 2.2 절 참조)
orca terminal send --terminal <handle> --text $'\x1b[Z'

# 6. 실존 확인
orca orchestration dispatch-show --task <task_id> --json
```

`terminal create` 에는 `--repo` 플래그가 없습니다. `--worktree` 만 받습니다.

**3 단계와 4 단계 사이에 두 가지를 반드시 하십시오.** 빠뜨리면 오류 문구가
원인을 가립니다 ([`orca_do_not_repeat.md`](orca_do_not_repeat.md) 21장).

| 조치 | 이유 |
| --- | --- |
| `orca terminal read` 로 CLI 가 실제로 떴는지 확인 | 명령이 즉시 죽어도 터미널은 만들어지고, Dispatch 는 `no recognized agent detected` 로만 말합니다 |
| `.orca/capsules/` 를 **통째로** 워크트리에 복사 | Task `spec` 은 생성 후 변경할 수 없어 잠정 ID 경로를 가리킵니다. 실제 ID 디렉터리 하나만 복사하면 워커가 없는 파일을 엽니다 |

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

### 2.2 파일 편집 승인은 Dispatch 직후 자동 승인으로 바꿉니다

폴더 신뢰를 미리 등록해도 **파일 편집·생성 승인은 따로 뜹니다.** 전역
`permissions.allow` 와도 무관합니다. 워커는 첫 편집에서 멈추고, 코디네이터가
알아채지 못하면 사람이 발견할 때까지 유휴로 남습니다. 준비 스크립트로도
막을 수 없습니다. 워크트리가 아니라 터미널 세션마다 걸리는 상태이기 때문입니다.

다이얼로그 하단의 `shift+tab to auto-approve file edits` 가 해제 수단입니다.
Dispatch 직후 각 터미널에 한 번 보내면 그 세션 내내 다시 묻지 않습니다.

```bash
orca terminal send --terminal <handle> --text $'\x1b[Z'
orca terminal read --terminal <handle> | tail -3   # Accept-edits mode 확인
```

`\x1b[Z` 가 shift+tab 입니다. 성공하면 하단에
`Accept-edits mode: file edits auto-approved` 가 뜹니다. 2026-08-22 에 이
단계를 빠뜨려 워커 5대가 각각 편집 승인에서 멈췄고 전부 사용자가 직접
눌러야 했습니다.

자동 승인은 쓰기 범위를 넓히지 않습니다. Capsule 의 `allowed_write_files` 는
Level 1 게이트 2 가 병합 전에 따로 검사하므로, 범위 밖 파일을 만들면 승인
여부와 무관하게 게이트에서 걸립니다.

명령 단위 권한(`permissions.allow`)은 이와 별개이며 전역입니다. `uv *`,
`git *`, `python3 *`, `pytest *` 같은 와일드카드가 이미 등록되어 있어 대개
다시 묻지 않습니다. 워커 기동에서 걸리는 것은 대부분 명령 승인이 아니라 폴더
신뢰입니다.

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
