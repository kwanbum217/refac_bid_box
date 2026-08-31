# 기각 및 반복 금지 목록 (Do Not Repeat) 상세

> **작성일**: 2026-08-15
> **버전**: v1.0.0
> **상태**: 확정 정본
> **요약 정본**: [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 3장
> 본 문서는 반복 금지 항목의 **근거와 실측 세부**를 담습니다. 코디네이터 부트스트랩에서는 `CURRENT_STATE.md` 3장의 한 줄 요약만 읽고, 근거가 필요할 때 해당 항목만 여기서 찾습니다.

---

## 1. 목적과 사용법

이 목록은 과거 검증을 거쳐 기각되었거나 실패가 확정된 항목입니다. 같은 시도를 반복하지 않기 위한 것입니다.

목록이 무한히 자라면 `CURRENT_STATE.md` 의 8,000자 예산을 잠식합니다. 그래서 **요약과 근거를 분리**합니다.

| 문서 | 내용 | 읽는 시점 |
| --- | --- | --- |
| `CURRENT_STATE.md` 3장 | 항목명과 결론 한 줄 | 부트스트랩마다 |
| 본 문서 | 실측 수치, 발생 경위, 대안 판정 | 그 항목을 다시 검토하려 할 때만 |

새 항목을 추가할 때는 두 곳에 함께 넣습니다. 요약만 있고 근거가 없으면 다음 세션이 판단 근거를 잃습니다.

**예외가 하나 있습니다.** 게이트나 도구가 기계로 막는 항목은 `CURRENT_STATE.md` 표에 넣지 않고 본 문서 7장에 강제 장치와 함께 둡니다. 기계가 막는 것을 매 부트스트랩마다 읽을 이유가 없고, 목록이 자라면 정작 판단이 필요한 항목이 묻힙니다. 강제 장치를 제거할 때는 7장에서 표로 되돌립니다.

---

## 2. 성능 및 서빙 (G3)

### 2.1 Uvicorn 워커 수 증설 (workers 3/4)

다중 워커 설정 시 지연시간 개선이 없었고 코어 경합과 메모리 오버헤드만 증가해 기각했습니다.

### 2.2 `PREDICTION_GC_MODE=batch-disable`

100ms 초과 발생이 30건으로 기본값(21건)보다 악화되어 기각했습니다. 측정으로 기각한 항목이므로 추정으로 되살리지 않습니다.

### 2.3 `PREDICTION_GC_MODE=threshold`

`freeze` 모드가 확정 채택되었고 두 모드는 상호 배타적이므로 재검토가 불필요합니다.

### 2.4 `README.md` 에 성능 실측값 또는 판정 문구 기재

2026-08-15 에 G3 실측 3행을 제거하고 `CURRENT_STATE.md` 포인터로 대체했습니다. 수치를 README 에 적고 갱신하는 방식은 다음 측정에서 다시 뒤처지므로 채택하지 않습니다.

**수치만 옮기는 것으로는 부족합니다.** 2026-08-15 조치는 수치 3행만 제거하고
`미달`, `달성이 남았습니다` 같은 **판정 문구를 남겼습니다.** 그 결과 정본이 예측
API 통과로 바뀐 뒤에도 README 는 2026-08-16 까지 미달로 표시했고, 이 항목이
"포인터로 대체 완료" 로 기록돼 있어 어긋남을 덮었습니다.

판정도 실측에서 파생되므로 같은 속도로 낡습니다. README 에는 어느 게이트가 항목별
판정 대상인지와 정본 위치만 적고, 통과·미달 자체를 적지 않습니다.

레이턴시 지표의 정본은 `CURRENT_STATE.md` 2장, 게이트 판정의 정본은 같은 문서 1장이며 측정 조건은 [`latency_gate_protocol.md`](latency_gate_protocol.md) 를 따릅니다.

---

### 2.9 블로킹 I/O 오프로드에서 같은 세션을 동시 실행

`asyncio.to_thread` 오프로드는 반드시 `await` 로 순차 실행합니다. 하나의
`SessionLocal()` 세션을 쓰는 두 호출을 `asyncio.gather` 나 `create_task` 로
동시에 실행하면 SQLAlchemy 동기 세션이 깨집니다. 세션은 각 코루틴 안에서만
쓰이므로 순차 `await` 에서는 동시 사용이 발생하지 않습니다.

병렬화로 얻을 이득이 있어 보여도, 세션을 공유하는 호출에는 적용하지 않습니다.
병렬이 필요하면 호출마다 세션을 따로 열어야 하며 그것은 별도 판단 사안입니다.

### 2.10 제너레이터 함수 호출을 블로킹 지점으로 오판

본문에 `yield` 가 있는 함수는 호출 시점에 본문을 한 줄도 실행하지 않습니다.
`token_gen = backend.stream_generate(...)` 는 제너레이터 객체만 만들며 HTTP
소켓도 열리지 않습니다. 실제 I/O 는 첫 `next()` 에서 일어나므로, 블로킹
여부는 `next()` 가 오프로드되어 있는지로 판정합니다. 2026-08-18 G3 감사가
이 지점을 결함으로 올렸고 코드 확인으로 기각했습니다.

## 3. 미병합 브랜치

| 브랜치 | 판정 | 사유 |
| --- | --- | --- |
| `feat/codex-task-routing` | 전량 폐기 | 중복 라우터 및 불필요 스킬 |
| `integrate/arq-worker-cutover` | 폐기 | `preprocess.py`, `champion_summary.json` 병합 금지 |
| `perf/predict-tail` (`0fd489a`) | 병합 불가, 진단 전용 보존 | 관측성 삭제 포함 |

판정 기록: [`phase8_predict_tail_merge_verdict_20260814.md`](phase8_predict_tail_merge_verdict_20260814.md), [`codex_task_routing_branch_verdict_20260814.md`](codex_task_routing_branch_verdict_20260814.md)

---

## 4. 워커 기동과 조율

### 4.1 신뢰 확인 미완료 상태에서의 무검증 `dispatch --inject`

Antigravity CLI 는 워크스페이스 신뢰 확인 대화창을 먼저 띄웁니다. 그 상태에서:

| 전달 경로 | 실제 결과 |
| --- | --- |
| `dispatch --inject` | 키 입력 유실 |
| `agy -i "<프롬프트>"` | 유실 없음. 다만 승인 전까지 실행이 시작되지 않아 워커가 유휴로 보임 |

**2026-08-15 추가 실측**: 신뢰를 승인하고 `terminal read` 로 프롬프트가 준비된 것을 확인한 뒤 `dispatch --inject` 를 했는데도 키 입력이 도달하지 않은 사례가 있었습니다. 승인 완료가 도달을 보장하지 않습니다. 유실을 확인하면 Task 를 `ready` 로 되돌려 재 Dispatch 하거나 `terminal send` 로 지시문을 직접 투입합니다.

`agy -i` 를 "유실 지점이 없는 안전한 경로" 로만 기억하면 승인 대기를 정체로 오판합니다.

기동은 세 단계입니다.

1. `terminal create` 로 CLI 를 띄운다
2. `terminal send --text "" --enter` 로 신뢰를 승인한다 (기본 선택이 신뢰)
3. `terminal read` 로 진행을 확인한다

도달 확인 없는 맹목적 대기를 금지합니다. 근거: [`orca_v2_runtime_smoke_20260815.md`](orca_v2_runtime_smoke_20260815.md) V.6

**2026-08-17: 1단계와 2단계를 `dispatch` 가 대신합니다.** 그 전에는 세 단계가 문서에만 있고 도구가 강제하지 않아, 새 워크트리에 Dispatch 하면서 Capsule 고지문이 신뢰 대화창에 먹혔습니다. 이제 `orca_taskctl.py dispatch --terminal` 이 Dispatch 전에 대화창을 승인합니다.

**한 번만 보고 판정하면 안 됩니다.** 기동 직후에는 CLI 가 부팅 중이라 대화창이 아직 없습니다. 그 상태를 통과로 보면 직후에 대화창이 떠서 지시를 먹습니다. `approve_trust_prompt` 는 대화창이 뜨거나 입력 프롬프트(마지막 줄이 단독 `>`)가 준비될 때까지 기다립니다. 반환 상태는 다섯입니다.

| 상태 | 의미 | `dispatch` 의 처리 |
| --- | --- | --- |
| `not_present` | 프롬프트 준비됨, 대화창 없음 | 그대로 진행 |
| `approved` | 대화창을 승인했고 사라진 것을 확인 | 그대로 진행 |
| `still_present` | 승인이 도달하지 않음 | **종료 코드 2 로 중단.** 보내면 지시가 사라진다 |
| `unreadable` | 터미널 출력 조회 실패 | 경고 후 진행. 도달을 직접 확인 |
| `not_settled` | 대기 시간 안에 어느 상태도 아님 (이미 작업 중일 수 있음) | 경고 후 진행 |

3단계(도달 확인)는 여전히 판단입니다. 승인이 됐다고 주입이 도달한 것은 아닙니다.

### 4.2 무료 LLM 풀의 임계 경로 투입

`cerebras/gemma-4-31b` 는 TPM 초과 위험이 있고 OpenCode 무료 모델은 안정성과 컨텍스트 제약이 있어 주력·임계 경로에서 배제합니다. `deepseek-v4-flash-free` 는 2026-08-20 에 일시적 호출 실패를 겪었으나 같은 날 복구를 확인했습니다.

동시에 **무료 모델을 실패나 무산출로 단정하지 않습니다.** 자동 검증이 가능한 비임계 경로(단독 감사, 분리된 검증)로 한정해 사용합니다.

**2026-08-17 실측: TPM 은 파일 수 축소로 해소되지 않습니다.** `cerebras/gemma-4-31b` 에 같은 감사를 세 형태로 주었습니다.

| 형태 | 워커 입력 | 결과 |
| --- | --- | --- |
| 파일 2개(1,081줄) 통독 | 파일 전문 + grep | TPM 초과, 백오프 14s -> 42s -> 58s |
| 파일 1개(522줄) 통독 | 파일 전문 + grep | TPM 초과 재현 |
| 사실 주입 원샷 | Capsule 4,433자, 도구 호출 0회 | 성공. 계약 준수 보고 |

같은 시각 `1+1 은?` 같은 짧은 요청은 통과했습니다. 즉 한 번의 큰 입력이 아니라 **에이전트 루프가 매 턴 전체 컨텍스트를 재전송해 분당 유입이 누적되는 것**이 원인입니다. 턴 수를 줄이지 않으면 대상 파일을 줄여도 같은 벽에 부딪칩니다.

따라서 TPM 제약 모델에는 코디네이터가 심볼 지도, 외부 참조, patch 처를 미리 뽑아 `ground_truth` 로 주입하고 `recheck: false` 로 재조사를 막은 **단발 판정**만 보냅니다. 이때 절감은 워커 쪽에서만 일어나고 추출 비용이 코디네이터로 옮겨 오므로, 합산해서 판단합니다.

**2026-08-16 조건부 개방**: 전면 배제는 유지하되, `scripts/orca_model_router.py` 가 세 조건을 모두 만족할 때만 명시적 opt-in(`--allow-free`)으로 무료 풀을 엽니다. 역할이 `investigator` 이고, 위험도가 `low` 이고, `allowed_write_files` 가 빈 목록인 경우입니다. `reviewer` 는 읽기 전용이지만 판정이 병합 결정에 쓰이므로 임계 경로이며 개방 대상이 아닙니다.

기존 세 풀의 `auto_selectable` 값은 바꾸지 않았습니다. **무료 풀은 여전히 자동 선택 대상이 아닙니다.** 조건은 [`orca_control_plane_tools.md`](orca_control_plane_tools.md) 4.3.1 절에 있습니다.

컨텍스트 상한이 좁은 것(Cerebras 65,536)이 개방의 전제입니다. 프로젝트 전체 탐색에는 쓸 수 없고, Task Capsule 로 읽기 범위가 이미 좁혀진 작업에만 맞습니다.

#### 4.2.1 실측하지 않은 모델 ID 를 풀에 등록

`MODEL_POOL` 에 자리표시자 ID 를 넣어두고 probe 로 확인하지 않으면, 그 항목이 선택되는 순간에야 `Model not found` 로 실패합니다. 2026-08-16 에 `opencode-free` 항목의 ID 가 실재하지 않는 값이었고, 실측 ID 는 `opencode/nemotron-3.5-lightning-free` 였습니다. 같은 diff 에서 `codex` 항목의 provider 도 `opencode` 로 잘못 적혀 있었습니다.

풀에 항목을 추가하거나 고칠 때는 그 자리에서 `probe` 를 돌려 응답 본문을 확인합니다. 목록은 `opencode models` 로 얻습니다. 근거 없는 ID 는 5.5 절과 같은 부류입니다.

#### 4.2.2 `{env:...}` 가 저장소 `.env` 를 읽는다고 가정

`opencode.json` 의 `"apiKey": "{env:CEREBRAS_API_KEY}"` 는 **프로세스 환경 변수**를 읽습니다. 이 저장소의 `.env` 는 셸로 export 되지 않으므로 키가 도달하지 않고, 증상은 키 부재가 아니라 `Unauthorized: Wrong API Key` 입니다. 2026-08-16 에 이 메시지 때문에 Cerebras 세 모델을 전부 사용 불가로 오판했습니다.

`scripts/orca_model_router.py` 는 `.env` 를 읽어 subprocess 의 `env` 딕셔너리에만 주입합니다. **키 값은 로그·예외·경고·문서 어디에도 출력하지 않고**, 부재 시 `CEREBRAS_API_KEY 미설정` 이라는 사실만 보고합니다.

#### 4.2.3 모델 선정 전에 이 문서를 조회하지 않기

2026-08-17 에 저는 `cerebras/gemma-4-31b` 를 파일 두 개 통독 감사에 배정했습니다. 그 위험은 **본 문서 4.2 절에 이미 적혀 있었고**, 같은 절이 `reviewer` 역할은 무료 풀 개방 대상이 아니라고도 못박고 있었습니다. 둘 다 어겼습니다.

기록이 있는데 조회하지 않으면 기록은 없는 것과 같습니다. 워커 모델을 고르는 첫 단계는 이 문서에서 해당 모델명을 검색하는 것입니다.

#### 4.2.4 OpenCode 워커에게 저장소 밖 경로로 보고를 쓰게 하기

`opencode` 는 작업 트리 밖 경로 쓰기를 `external_directory` 권한 요청으로 보고 자동 거부합니다. Capsule 디렉터리(`/Users/kwanbum/orca/capsules/...`)를 `report_path` 로 주면 판정을 다 해놓고 마지막 쓰기에서 버립니다.

읽기 전용 워커의 보고는 표준출력으로 받아 코디네이터가 저장합니다. 도구 호출이 사라져 TPM 에도 유리합니다.

### 4.3 Capsule 을 공유 디렉터리에 배치

2026-08-15 T6 실행 검증에서 워커가 자기 Capsule 과 함께 다른 Task 의 사양·런처를 읽었습니다. 원인은 워커가 아니라 코디네이터의 배치였습니다.

- Task 하나당 디렉터리 하나를 씁니다
- `allowed_read_files` 에 Capsule 자신의 경로를 넣습니다
- `allowed_read_files` 는 지시이며 강제 장치가 아닙니다. 준수는 `worker_done` 의 `read_files` 로 사후 확인합니다

규약: [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md) 2.9

#### 4.3.1 읽기 범위와 쓰기 범위의 강제 수준을 같다고 가정

두 범위의 강제 수준이 **비대칭**입니다. `scripts/orca_level1_gate.py` 는 쓰기 범위를 `git diff` 로 기계 검증하지만, `read_scope_excess` 는 **워커가 스스로 신고한 `read_files` 목록만** `allowed_read_files` 와 대조합니다. `forbidden` 항목도 같습니다.

즉 읽기 범위 위반은 워커가 정직하게 신고했을 때만 검출됩니다. 신고를 누락하면 게이트는 통과합니다. 2026-08-16 확인 사항입니다.

따라서 읽기 범위는 **차단 장치가 아니라 컨텍스트 예산 설계**로 취급합니다. 유출되면 안 되는 것은 `allowed_read_files` 에서 빼는 것으로 막지 말고, 워커 작업 트리 자체에 두지 않습니다.

### 4.4 후속 Dispatch 에 같은 `report_path` 재사용

워커가 같은 경로에 새 보고를 덮어씁니다. 2026-08-15 에 발생해 첫 Dispatch 의 `report_chars` 와 `changed_files` 를 지표 원장에 기록할 수 없었습니다.

반려나 재작업을 지시할 때는 새 `report_path` 를 함께 전달합니다. 규약: [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md) 2.9.3

### 4.5 반려 후 재작업을 완료된 Task 에 태우기

이미 `completed` 인 Task 의 터미널에 수정 지시만 보내면 워커는 정상적으로
고치지만, 두 번째 `worker_done` 은 Orca 가 `Rejected worker_done` 으로
거부합니다. Task 를 두 번 완료할 수 없기 때문입니다.

산출물은 커밋에 남으므로 병합 판단은 가능합니다. 그러나 **반려 사유와 2차 수용
판정이 수명주기 이력에 남지 않아** 다음 세션이 경위를 복원할 수 없습니다.
2026-08-15 에 세 워커 모두 이 상태가 되어 `Rejected worker_done` 8건이
쌓였습니다.

재작업은 Task 를 `ready` 로 되돌려 재 Dispatch 하거나, 원 Task 를 선행
의존성으로 둔 새 Task 를 만들어 태웁니다. 후자가 이력 보존에 낫고, 전자가
왕복 지표를 한 Task 에 모으기에 낫습니다. 절차: [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 6.2.1

#### 4.5.1 `ready` 로 되돌린 뒤 재 Dispatch 를 빠뜨리기

`task-update --status ready` 만 하고 터미널에 지시를 보내면 **기존 Dispatch 의
권한이 회수된 상태**라 재보고가 `Dispatch <id> capability is revoked` 로
거부됩니다. `ready` 복귀는 재 Dispatch 의 전제이며 그 자체로 권한을 주지
않습니다. 2026-08-16 에 워커 두 대가 이 상태로 각각 두 번 거부되었습니다.

순서는 `task-update --status ready` 다음 `dispatch --task <id> --to <handle>`
이고, 그 뒤에 터미널로 수정 지시를 보냅니다.

#### 4.5.2 병합한 Task 를 `completed` 로 닫지 않기

산출물을 병합했는데 Task 상태를 그대로 두면 그 터미널에 활성 Dispatch 가
남아, 같은 터미널에 다음 Task 를 Dispatch 할 때
`Terminal <handle> already has an active dispatch` 로 거부됩니다. 워커를
재사용하려면 병합 직후 `task-update --status completed` 로 닫습니다.

### 4.6 `worker-list` 로 동시 워커 수를 판정

`orca orchestration worker-list` 는 `worker-start` 로 기동한 **감독 대상 워커만** 반환합니다. `terminal create` 로 띄우고 `dispatch --to <handle>` 로 붙인 워커는 여기에 나타나지 않습니다.

2026-08-16 에 워커 3대가 붙어 일하는 중에 `worker-list` 가 활성 0 을 반환했습니다. 이 값으로 동시성 상한을 검사하면 상한이 조용히 무력화됩니다.

동시 점유 판정은 `orca orchestration task-list --run <id> --json` 의 `status` 로 합니다. 유효 상태는 `pending`, `ready`, `dispatched`, `completed`, `failed`, `blocked` 이고, 워커를 점유하는 것은 **`dispatched` 뿐**입니다. 두 명령의 JSON 키 표기도 다릅니다. `worker-list` 는 camelCase, `task-list` 는 snake_case 입니다.

`--run` 에 자리표시자(`run_auto` 등)를 기본값으로 두면 조회가 `ok: true`, 결과 0건으로 돌아와 같은 무력화가 발생합니다. Run ID 는 `run-current` 로 해석하고, 해석 실패 시 fail-closed 로 거부합니다. 구현: `scripts/orca_taskctl.py` 의 `check_write_concurrency`, 규칙: [`../../AGENTS.md`](../../AGENTS.md) 4장 5.1

### 4.7 Capsule 을 정본으로 선언하고 경로를 주입하지 않기

**`orca orchestration dispatch --inject` 는 Orca Task 의 `spec` 만 주입합니다.** Capsule 파일 경로도 내용도 들어가지 않습니다. 워커는 한두 문장짜리 요약만 보고 작업을 시작합니다.

2026-08-17 대형 모듈 분할 Run 에서 워커 **3대 전부**가 같은 방식으로 어긋났습니다.

| 위반 | 발생 |
| --- | --- |
| `allowed_write_files` 의 파일명을 무시하고 임의 작명 | 3/3 |
| `commit_count: 0` 인데 `succeeded` 전송 (계약은 `escalation` 요구) | 3/3 |
| `report_path` 에 보고 JSON 미작성 | 3/3 |
| `worker_done` 의 `filesModified` 가 실제 파일명과 불일치 | 3/3 |

셋이 독립적으로 같은 실수를 했다는 것이 진단입니다. **워커 품질 문제가 아니라 전달 경로가 끊긴 것입니다.** Capsule 이 정본이라고 문서에 적혀 있어도 워커가 읽지 못하면 계약은 존재하지 않습니다.

Dispatch 직후 `terminal send` 로 Capsule 절대 경로를 보내되, **이미 작업을 시작한 뒤에 보내면 늦습니다.** Task `spec` 자체에 Capsule 절대 경로를 넣어 `task-create` 하는 것이 순서상 맞습니다.

**2026-08-17 조치**: `scripts/orca_taskctl.py` 에 `create` 서브커맨드를 신설해 Capsule 절대 경로를 Task `spec` 에 넣고, `dispatch` 가 기동 직후 고지문을 자동 투입합니다. 전송 실패는 `capsule_notice.status: failed` 와 stderr 경고로 드러납니다. 상세: [`orca_control_plane_tools.md`](orca_control_plane_tools.md) 3.4

#### 4.7.1 재 Dispatch 후 새 `dispatchId` 를 워커에게 알리지 않기

4.5.1 은 `ready` 복귀만 하고 재 Dispatch 를 빠뜨리는 경우를 다룹니다. **재 Dispatch 를 했어도 같은 거부가 납니다.** 워커가 자기 문맥에 남은 옛 ID 로 보고하기 때문입니다.

```
Orca rejected this worker_done: Dispatch <old_id> capability is revoked.
```

2026-08-17 에 이 거부가 3회 났습니다. `--inject` 프리앰블은 새 `dispatchId` 를 실어 주지 않습니다. 재 Dispatch 직후 `dispatch-show --task <id>` 로 유효 ID 를 확인해 워커에게 **명시적으로 전달**하십시오. 전달했더라도 워커가 이미 전송 중이면 한 번 더 거부될 수 있습니다.

#### 4.7.2 Capsule 템플릿의 `artifact_paths` 가 쓰기 범위 밖

`scripts/orca_taskctl.py` 의 `expand` 는 `artifact_paths` 에 `docs/analysis/<task_id>.md` 를 자동으로 넣지만, `allowed_write_files` 는 Intent 의 `scope` 로만 구성됩니다. **템플릿이 지시한 산출물 경로가 쓰기 범위 밖입니다.**

2026-08-17 에 워커 3대가 모두 `docs/analysis/` 를 만들었고, 그대로 커밋하면 Level 1 게이트가 범위 초과로 거부합니다. Intent 의 `scope` 에 산출물 경로를 함께 넣거나, 커밋하지 말고 미추적으로 남기라고 지시하십시오.

### 4.8 `check` 를 `--ack` 없이 호출

`orca orchestration check` 는 **확인 처리되지 않은 가장 오래된 배치를 계속 재전달합니다.** `--ack <delivery_id>` 로 이전 배치를 닫아야 큐가 전진합니다.

2026-08-17 에 heartbeat 2건이 배치에 남아 있어서 같은 두 건이 세 번 연속 나왔고, 그 뒤에 도착한 `worker_done` 3건이 가려져 보이지 않았습니다. **`--wait` 도 무력화됩니다.** 미확인 배치가 이미 있으면 즉시 그것을 반환하므로 15분 대기가 성립하지 않았습니다.

순서는 `check --json` 으로 `deliveryId` 를 받고, 처리 후 다음 호출에 `--ack <그 id>` 를 붙이는 것입니다. 4.6 및 5.5.1 과 같은 부류입니다. **명령이 성공했다는 것이 의도한 일이 일어났다는 뜻은 아닙니다.**

---

## 5. 검증 태도

### 5.1 워커 요약 보고 텍스트만 신뢰하는 행위

워커의 비정형 요약과 실제 산출물 사이의 불일치가 빈발합니다. 코디네이터는 생성된 파일 diff 와 결정론 검증 결과를 직접 대조합니다.

수단: `python3 scripts/orca_level1_gate.py`, `python3 scripts/summarize_worker_done.py`

### 5.2 Reviewer 의 `pass` 를 코디네이터 검토 축소 근거로 사용

첫 실사용에서 Reviewer 2대가 실재 결함 3건을 놓치고 `pass` 를 냈습니다. 계약 도달과 Capsule 격리는 작동했으나 검출은 미달이었습니다.

계약 v2.1 체크리스트 도입 후 같은 모델이 0/3 에서 4/4 로 개선됐습니다. 다만 **체크리스트에 없던 결함은 절반만 찾습니다.** 따라서 Level 3 코디네이터 검토를 유지합니다.

이 관찰 당시 Reviewer 기본 모델은 `gemini-3.7-flash-high`였고 Claude 계열과 검출 성적이 동일했습니다. 현재 정본 정책은 `gemini-3.7-flash-medium`을 기본으로 하며, High는 high 위험도 교차검토에만 `WORKER_MODEL_NOTICE`와 함께 승격합니다.

근거: [`orca_v2_reviewer_plane_20260815.md`](orca_v2_reviewer_plane_20260815.md), [`orca_v2_reviewer_sensitivity_20260815.md`](orca_v2_reviewer_sensitivity_20260815.md)

### 5.2.1 코디네이터 검토를 Level 2 대체로 사용

5.2 는 리뷰어의 `pass` 가 코디네이터 검토를 대체하지 못한다고 적었습니다. **역방향도 성립합니다.**

2026-08-15 에 코디네이터 검토만으로 수신면 도구 4개를 병합했습니다. 이후 독립 리뷰어 감사에서 실재 결함 7건이 나왔고 전부 재현되었습니다.

| 결함 | 재현 |
| --- | --- |
| `matches_any` 가 경로 탈출을 허용으로 오판 | `matches_any('scripts/../../secret.py', ['scripts/...'])` -> `True` |
| 빈 경로 허용 | `matches_any('', ['*'])` -> `True` |
| 따옴표 안 샵을 주석으로 절단 | `- "src/file #1.py"` -> `['src/file']` |
| 0열 주석이 Capsule 블록을 끊어 항목 유실 | `a.py` 뒤 주석, `b.py` -> `['a.py']` |
| **`blocking_issues` id 부분문자열 매칭** | `['C10']` 으로 `C1` 요구 충족, 위반 0건 |
| folded scalar 미파싱 | `question: >` -> `question` 이 `'>'` |
| 불리언이 수치 지표에 합산 | `_collect_numeric([{'v': True}], 'v')` -> `[1.0]` |

다섯 번째가 가장 무거웠습니다. 리뷰어가 결함을 보고했는지 검사하는 **강제 장치 자체의 허점**이며, 체크리스트가 `C1`~`C10` 인 조건에서 실제로 성립했습니다. 고치지 않으면 이후 모든 리뷰 계약 판정이 조용히 통과합니다.

교훈은 두 층이 서로를 대체하지 못한다는 것입니다. 리뷰어는 코디네이터가 자기 코드에서 못 보는 것을 보고, 코디네이터는 리뷰어가 근거 없이 주장하는 것을 걸러냅니다. **어느 한쪽만으로 병합하지 않습니다.**

근거: [`orca_v2_intake_tools_audit_20260815.md`](orca_v2_intake_tools_audit_20260815.md)

### 5.3 파이프라인으로 검증 명령의 종료 코드 판정

`uv run pytest ... | tail -3 && <다음 명령>` 은 파이프라인 종료 코드가 `tail` 의 것이므로 **테스트 실패에도 다음 명령이 실행되고 전체가 성공으로 보입니다.**

2026-08-15 에 이 방식으로 실패 2건을 통과로 볼 뻔했습니다. 실제로는 워크트리에 Git 미추적 자산(`model.bin`, `chroma_db`)이 없어 발생한 `data_assets` 마커 테스트였고 회귀는 아니었으나, 판정 방식 자체가 틀렸습니다.

검증은 `scripts/orca_level1_gate.py` 로 수행합니다. 직접 실행할 때는 종료 코드를 파이프라인과 분리해 확인합니다.

격리 워크트리에서 전체 테스트를 돌릴 때는 `-m 'not data_assets'` 를 씁니다. 자산이 있는 주 저장소에서는 전량 실행이 정본입니다.

### 5.4 워커가 계약 필드명을 자기 표기로 바꿔 쓰는 것을 그대로 받는 행위

2026-08-15 에 워커가 자기 보고에 `files_modified` 를 쓰고, 지표 원장 코드도 그 필드명을 읽게 만들었습니다. 결과로 **계약을 지킨 모든 보고에 `changed_files_count: 0` 을 조용히 기록**했습니다.

`ORCA_WORKER_DONE_V2` 의 필드명은 `changed_files` 입니다. 비표준 필드 폴백을 코드에 남기지 않습니다. 남기면 계약 위반이 정상값으로 섞입니다.

#### 5.4.1 계약 이름만 적고 필드명을 열거하지 않기

Capsule 에 `return_contract: ORCA_REVIEW_DONE_V2` 라고만 적는 것은 스키마를 학습하지 않은 모델에게 아무 구속이 아닙니다. **계약 이름은 규격이 아니라 라벨입니다.**

2026-08-17 측정에서 같은 형태의 감사 4건을 모델별로 돌린 결과입니다.

| 워커 모델 | Capsule 에 필드명 열거 | 결과 |
| --- | --- | --- |
| `gemini-3.7-flash-high` | 없음 | 규약 준수 |
| `claude-sonnet-4-6` | 없음 | `checklist_results` -> `checklist`, `verdict` 를 객체로 |
| `claude-opus-4-6-thinking` | 없음 | 같은 이탈 재현 |
| `cerebras/gemma-4-31b` | `report_schema` 로 열거 | 규약 준수 |

이탈한 두 보고 때문에 원장의 `verdict` 분포에 객체가 그대로 들어갔습니다. 필드명을 열거한 마지막 건만 정상이었으므로, 원인은 모델 능력이 아니라 **사양의 구속력 부재**입니다.

`expand_intent_to_capsule` 이 이제 역할별 `report_schema` 블록을 항상 넣습니다. 손으로 Capsule 을 쓸 때도 필드명을 열거합니다.

#### 5.4.2 Orca 메시지 필드명을 보고 계약 위반으로 오판

두 층이 별개입니다.

| 층 | 스키마 | 필드 표기 |
| --- | --- | --- |
| 보고 파일 (`report_path`) | `ORCA_WORKER_DONE_V2` / `ORCA_REVIEW_DONE_V2` | snake_case (`changed_files`, `commit_count`) |
| Orca 메시지 payload | Orca 런타임 자체 스키마 | camelCase (`taskId`, `dispatchId`, `filesModified`, `reportPath`, `phase`) |

`orca orchestration send` 가 `--files-modified <csv>` 플래그를 제공하고 그 값을 payload 의 `filesModified` 로 넣습니다. 즉 **camelCase 는 CLI 설계이며 워커의 이탈이 아닙니다.**

2026-08-17 에 저는 `check` 로 받은 payload 의 `filesModified` 를 보고 워커가 5.4 절 위반을 했다고 판정했습니다. 틀렸습니다. `send --help` 를 먼저 봤으면 나오지 않을 오판이었고, 이 오판대로 워커를 고치거나 코드에 폴백을 넣으면 5.4 절이 금지한 바로 그 상태를 만들게 됩니다.

판정 순서는 이렇습니다. 보고 파일은 `ORCA_WORKER_DONE_V2` 로 대조하고, 메시지 payload 는 `orca orchestration send --help` 의 서명으로 대조합니다. 하나의 계약으로 둘을 재지 않습니다.

#### 5.4.3 `worker_done` 을 두 번 보내면서 첫 번째에 다른 `report_path` 를 넣기

2026-08-17 S3 워커가 `worker_done` 을 두 번 보냈습니다. 1차 `reportPath` 는 `docs/analysis/s3.md`, 2차는 Capsule 이 선언한 경로였습니다. 스스로 고쳐 다시 보낸 것으로 보입니다.

코디네이터에게는 같은 Task 의 완료 신고가 둘로 보이고, 먼저 읽은 쪽이 Capsule 이 선언하지 않은 경로를 가리킵니다. 그 경로를 그대로 원장의 `report_path` 로 기록하면 `report_chars` 가 분석 문서 길이가 되어 보고량 비교가 오염됩니다.

원장에 넣을 경로는 메시지가 아니라 **Capsule 의 `report_path`** 입니다. 메시지의 `reportPath` 는 참고값으로만 씁니다.

### 5.5 확인하지 않은 외부 CLI 서명으로 코드를 작성

이 저장소에서 **가장 많이 반복된 결함 부류**입니다. 세 번 나왔습니다.

| 시점 | 허구 서명 | 실제 |
| --- | --- | --- |
| 2026-08-16 `3453a3f` | `orca orchestration dispatch --capsule --model --worktree` | `--task`, `--to` 만 존재 |
| 2026-08-16 `3453a3f` | `orca worktree create --branch` | `--name` |
| 2026-08-16 재작성 1차 | `dispatch --inject <값>` | `--inject` 는 값을 받지 않음 |
| 2026-08-16 재작성 1차 | `opencode ask --model --prompt` | `opencode run [message..] -m <provider/model>` |

**값 유무는 `--help` 의 Usage 줄에서 구분합니다.** `--task <task_id>` 처럼
자리표시자가 있으면 값을 받고, `[--inject]` 처럼 없으면 불리언입니다. Options
목록은 둘을 구분해 주지 않으므로 Usage 줄을 보십시오.

이 부류가 특히 위험한 이유는 **틀린 서명이 조용히 실패한다는 점**입니다.
`opencode ask` 는 `ask` 를 프로젝트 경로로 해석해 실패하면서 **종료 코드 0** 을
반환했고, probe 는 그것을 가용으로 판정해 거짓 양성을 냈습니다. 실패를 성공으로
보고하는 쪽이 반대보다 위험합니다.

외부 명령을 조립하는 코드는 **종료 코드만으로 성공을 선언하지 않습니다.**
응답 본문 같은 추가 근거를 함께 요구하십시오.

#### 5.5.1 Orca 자체 CLI 의 인자 값을 확인 없이 사용

같은 부류가 **Orca CLI 에서도** 나왔습니다. `orca orchestration check --types ask`
는 `ask` 가 유효한 종류가 아니어서 아무것도 대기하지 않지만, `ok: false` 를
출력하면서 **종료 코드 0** 을 반환합니다.

2026-08-16 에 이 명령으로 30분 대기를 걸었고, 실제로는 대기가 성립하지 않았는데
`완료 (종료 코드 0)` 으로 보고되었습니다. 유효한 종류는 `worker_done`,
`escalation` 입니다.

**Orca 명령은 종료 코드와 `ok` 필드를 따로 확인합니다.** 5.5 절의 "외부 CLI"
경계 안쪽이라고 안심하지 마십시오. 인자에 열거형 값을 넣을 때는 `--help` 로
허용 값을 먼저 확인하고, 없으면 잘못된 값을 한 번 넣어 오류 메시지에서 목록을
받아냅니다.

### 5.6 테스트가 틀린 사실을 정답으로 고정

`3453a3f` 의 테스트 54건은 전부 통과했지만 결함이 있던 세 함수(워크트리 생성,
Dispatch, finalize)를 하나도 덮지 않았습니다. 재작성 1차에서는 더 나쁜 형태가
나왔습니다. 테스트가 `["--inject", "some_preamble"]` 를 **기대값으로 단정**해
존재하지 않는 서명을 정답으로 고정했습니다.

**통과하는 테스트는 확인의 근거가 아닙니다.** 기대값이 코드가 그렇게 동작한다는
이유로 정해졌는지, 외부 계약이 그렇다는 근거로 정해졌는지 구분하십시오. 전자는
동어반복입니다.

리뷰어 체크리스트에 이 항목을 넣으십시오. 2026-08-16 에 Level 2 가 이 결함을
놓친 것은 체크리스트에 해당 질문이 없었기 때문입니다.

### 5.7 동작 보존 분할을 사람 판독으로만 검증

"로직을 바꾸지 않고 이동만 한다" 는 사양은 **AST 대조로 기계 검증할 수 있습니다.** 리뷰어에게 읽혀서 판정하지 마십시오.

2026-08-17 대형 모듈 분할에서 이동 함수를 원본과 AST 로 대조했습니다.

| 대상 | 이전 함수 | 사라짐 | 본문 변경 |
| --- | ---: | :---: | ---: |
| `rag/engine.py` | 37 | 0 | 0 |
| `planner.py` | 28 | 0 | 0 |
| `automation_orchestrator.py` | 41 | 0 | **5** |

`automation_orchestrator` 의 5건은 리뷰어가 읽어서는 찾지 못했을 크기입니다(docstring 전각 마침표, 타입 주석, 리스트 연결의 언패킹 전환, 매개변수 신설과 그 전달). 방법은 다음입니다.

```python
ast.dump(node, include_attributes=False)  # 위치 정보를 제외해 이동만으로는 값이 변하지 않게 한다
```

`include_attributes=False` 가 핵심입니다. 빼지 않으면 줄 번호가 달라져 전부 변경으로 보입니다.

**이름을 평평하게 모으면 거짓 양성이 납니다.** 클래스 메서드와 모듈 수준 함수가 같은 이름을 가질 수 있습니다. 2026-08-17 2차 분할에서 `predict_interval` 이 본문 변경으로 나왔는데, 실제로는 `JoblibModelWrapper.predict_interval` 메서드와 모듈 수준 `predict_interval` 함수가 한 칸을 다퉜을 뿐이고 둘 다 동일했습니다. 소유자를 포함해 정규화하십시오.

```python
f"{cls.name}.{method.name}"  # 클래스 메서드
f"<module>.{func.name}"  # 모듈 수준 함수
```

정규화 후 재대조에서 `model_registry.py` 61개와 `chatbot.py` 24개 전부가 동일로 확정되었습니다. **대조 도구가 낸 결함 신호도 근거를 확인하기 전에는 결함이 아닙니다.**

### 5.8 충족 불가능한 수락 기준을 내려보내기

같은 Task 에 "함수를 다른 모듈로 옮긴다" 와 "기존 테스트 파일을 수정하지 않는다" 를 함께 요구했는데, 테스트 12곳 이상이 `automation_orchestrator._enqueue_arq_job` 을 patch 하고 있었습니다. 함수를 옮기면 patch 대상이 끊기므로 **두 조건을 동시에 만족시킬 방법이 없었습니다.**

워커는 운영 코드에 주입 지점(`enqueue_fn`)을 만들어 우회했습니다. 런타임 동작은 같지만 공개 서명이 늘었습니다. 이것은 5.6 의 이웃 사례입니다. 테스트를 통과시키려고 운영 코드를 바꾸는 압력이 사양에서 나왔습니다.

**수락 기준을 쓸 때 patch 대상, monkeypatch 경로, import 경유 참조를 먼저 조사하십시오.** 조사 결과 충돌이 있으면 이동 대상에서 빼거나 예외를 사양에 명시합니다. 워커가 `escalation` 을 보내는 것이 규약이지만, 모순을 만든 책임은 코디네이터에게 있습니다.

### 5.9 워커의 린터 통과 보고를 전체 통과로 읽기

2026-08-17 에 워커가 `uv run ruff check src/app/services/...` 로 대상 파일만 검사하고 "ruff 린터 통과" 로 보고했습니다. 자기가 새로 만든 **테스트 파일은 검사하지 않았습니다.** 병합 후 `ruff check .` 에서 오류 4건이 나왔습니다.

`scripts/orca_level1_gate.py` 의 게이트 4 는 `validate_agent_rules.py` 이고 **ruff 는 포함되지 않습니다.** 병합 전 확인 목록에 `uv run ruff check .` 를 저장소 전체 범위로 직접 넣으십시오. 워커의 린터 보고는 그 워커가 지정한 경로에 대한 것일 뿐입니다.

---

## 6. 문서와 측정 판정

### 6.1 크기 예산을 바이트로 판정

설계 5장의 8,000자는 **문자 수**이며 바이트가 아닙니다. `wc -c` 로 재면 한글이 3바이트라 초과처럼 보입니다.

검증기 `check_context_budgets` 는 `len()` 으로 문자 수를 셉니다. 공용 헬퍼는 `scripts/orca_contract.py` 의 `char_len` 입니다.

### 6.2 `defect_when` 에 산문을 쓰기

`review_checklist` 의 `defect_when` 은 **어느 답이 결함인지를 나타내는 `yes` 또는
`no` 극성 토큰**입니다. 설명 문장이 아닙니다.

2026-08-16 에 한국어 산문("그런 조합이 남아 있으면 결함이다")을 넣어
`validate_review_report.py` 가 극성을 읽지 못했고, 리뷰어 판정 8항목이 전부
`조건3 판정 불가` 로 무효 처리되었습니다. **리뷰 내용은 정상이었는데 형식으로
무효가 되었습니다.**

질문의 극성을 뒤집어 쓰지 않도록 주의하십시오. "결함이 있는가" 형태면 `yes`,
"규칙을 지키는가" 형태면 `no` 입니다. 설명은 `question` 이나 `how` 에 적습니다.
정본 형식: [`.agents/templates/review_done_v2.json`](../../.agents/templates/review_done_v2.json)

### 6.3 예산 상한을 함수에만 두고 CLI 에 노출하지 않기

`orca_run_reviewer.py` 의 `max_diff_chars` 가 함수 인자로만 존재하고 CLI 에
없어서, 2026-08-16 에 50,261자 diff 를 60% 절단된 상태로만 검토할 수 있었습니다.
설계서는 초과 시 파일별 분할을 지시하지만 경로 필터도 없어 분할 자체가
불가능했습니다.

**운영 판정을 좌우하는 상한은 호출자가 조정할 수 있어야 합니다.** 기본값으로
예산을 지키게 하고, 근거가 있을 때 올릴 수 있는 경로를 함께 두십시오.

### 6.4 `coordinator_input_tokens` 로 위임 절감을 비교

이 값은 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 의
합이고, 2026-08-16 실측에서 `cache_read` 가 **99.5 퍼센트**(399,563,803 중
397,513,915)를 차지했습니다. `cache_read` 는 매 assistant 메시지가 캐시된 접두부
전체를 다시 읽어 누적되므로 **대화 턴 수에 비례하고 위임 여부와 무관**합니다.

이 값으로 비교하면 위임을 잘한 세션이 턴이 많다는 이유로 더 나빠 보입니다.
위임 비교 대표 지표는 `coordinator_fresh_input_tokens`(uncached + cache_creation)
뿐입니다. 근거와 실측표: [`orca_v2_metrics_ledger.md`](orca_v2_metrics_ledger.md) 3.1

같은 트랜스크립트를 집계할 때 두 함정이 더 있습니다.

| 함정 | 결과 |
| --- | --- |
| `message.id` 중복 제거 누락 | 같은 id 가 여러 줄에 반복되어 약 1.9배 과대 계상 |
| 프로젝트 `*.jsonl` 전체 합산 | 병렬 Claude 세션 이력이 있어 다른 세션 토큰이 섞임 |

세션 기본값은 수정 시각이 가장 최근인 파일 하나입니다. 또한 조회 실패를 조용히
넘기면 창 필드만 채워진 행이 계측된 것처럼 보이므로, `usage_lookup_status` 로
상태를 함께 기록합니다.

### 6.5 순차 단독 Dispatch 행을 모델 성능 비교로 읽기

2026-08-17 에 대표 지표 유효 행을 처음 4건 확보했습니다. 그런데 그 4건은 M1 -> M4 순서로 갈수록 `coordinator_fresh_input_tokens` 가 내려갑니다(7,363 / 5,461 / 3,349, M4c 는 사실 추출을 포함해 14,338).

이것을 모델별 절감으로 읽으면 틀립니다. 뒤 행일수록 코디네이터가 **같은 절차를 반복해 캐시 접두부가 이미 만들어져 있고 확인 명령도 줄어듭니다.** 순서 효과와 모델 효과가 같은 방향으로 섞여 있어 4행으로는 분리되지 않습니다.

모델 비교를 하려면 순서를 뒤집은 반복 측정이 필요하고, 절감 추세를 보려면 같은 모델로 여러 Run 을 누적해야 합니다. 한 Run 의 순차 행으로 두 결론을 동시에 내지 않습니다.

---

## 7. 기계 강제로 재발이 차단된 항목

아래 항목은 게이트나 도구가 기계로 막습니다. 그래서 `CURRENT_STATE.md` 3장의 부트스트랩 표에서 빼고 여기에 둡니다. **부트스트랩 표는 판단으로만 지킬 수 있는 항목으로 한정합니다.** 그렇게 하지 않으면 목록이 무한히 자라 8,000자 예산을 잠식하고, 정작 판단이 필요한 항목이 묻힙니다.

| 항목 | 강제 장치 | 상세 |
| --- | --- | --- |
| 무료 LLM 풀의 임계 경로 투입 | `free_pool_eligibility()` 가 역할·위험도·쓰기 범위 세 조건을 검사하고 `auto_selectable` 이 False | 4.2 |
| 크기 예산을 바이트로 판정 | `scripts/validate_agent_rules.py` 가 문자 수로 보고 (`7214자/8000`) | 6.1 |
| `worker-list` 로 동시 워커 수 판정 | `orca_taskctl.py dispatch` 가 `task-list` 의 `dispatched` 로 점유를 세고 상한 초과 시 종료 코드 1 로 거부 | 4.6 |
| Capsule 경로를 주입하지 않기 | `taskctl create` 가 경로를 Task `spec` 에 넣고 `dispatch` 가 고지문을 `terminal send` 로 전달 | 4.7 |
| 워커의 린터 보고를 전체 통과로 읽기 | Level 1 게이트 4b 가 저장소 전체 `uv run ruff check .` 를 실행 | 5.9 |
| 계약 이름만 적고 필드명 미열거 | `expand_intent_to_capsule` 이 역할별 `report_schema` 블록을 항상 삽입 | 5.4.1 |
| 추론 등급을 항상 high 로 배정 | `TIER_POLICY` 표가 역할·위험도로 배정하고 high 를 high 위험도 전용으로 둠 | 4.2 |
| 신뢰 대화창이 뜬 채로 Dispatch | `dispatch --terminal` 이 `approve_trust_prompt` 로 승인하고, 승인 실패 시 종료 코드 2 로 중단 | 4.1 |
| completed 워커 창을 남긴 채 다음 Dispatch | `orca_settled_session_audit.py` 가 잔류를 찾고 `taskctl dispatch` 가 종료 코드 1 로 거부 | 25 |
| `defect_when` 에 산문 기재 | `validate_review_report.py` 가 극성을 정규화하고 판정 불가 시 "극성을 알 수 없음" 위반으로 보고 | 6.2 |
| `coordinator_input_tokens` 로 절감 비교 | `orca_metrics_ledger.py` 가 `fresh_input_tokens` 를 스스로 계산해 대표 지표로 기록 | 6.4 |

### 6.7 CI 를 초록으로 가정하기

2026-08-18 에 CI 가 최소 9시간, 확인된 5회 연속 실패 상태였는데 아무도
몰랐습니다. 실패 단계가 `bandit` 이었고 그 뒤의 프론트엔드 테스트·빌드와
macOS·Windows 테스트가 통째로 실행되지 않았습니다. 로컬 `pytest` 는 계속
통과했으므로 로컬 통과는 CI 통과의 근거가 아닙니다.

**푸시한 뒤에는 `gh run list` 로 결과를 확인합니다.** 특히 한 단계가 실패해
뒤 단계가 건너뛰어졌다면, 그 구간은 검증된 적이 없는 코드입니다. 실패를
고친 직후 실행에서 새 실패가 나오는 것은 회귀가 아니라 가려져 있던 상태가
드러난 것입니다.

### 6.6 원장 기록 시 사용량 창을 주지 않기

`orca_metrics_ledger.py record` 는 `--usage-since` 와 `--usage-until` 이 있어야
코디네이터 토큰을 트랜스크립트에서 계산합니다. 창을 주지 않으면 행은 남지만
`coordinator_fresh_input_tokens` 가 `None` 이라 대표 지표 집계에서 빠집니다.
2026-08-18 에 7행을 그렇게 기록해 유효 행이 7행 그대로였습니다.

**Dispatch 직전에 시각을 적어 두고 `worker_done` 직후에 그 창으로 기록합니다.**
나중에 창을 복원하려 하면 코디네이터가 그 사이 다른 일을 한 구간까지 섞여
수치가 오염됩니다. 비어 있는 행을 남기는 편이 낫습니다.

**강제 장치를 지우면 항목을 다시 표로 올립니다.** 장치가 사라진 채 표에도 없으면 그 교훈은 조용히 소실됩니다. 강제 장치는 각각 테스트로 고정되어 있으므로, 해당 테스트를 삭제하려면 이 표를 함께 고쳐야 합니다.

---

## 8. 대형 모듈 분할 종결 판정 (2026-08-17)

1,000줄 -> 600줄 -> 500줄 순으로 기준을 내리며 진행했고, **모듈 분할 관점에서 종결했습니다.** 500줄 초과 7개 전부에 판정이 있습니다.

| 모듈 | 줄 | 판정 | 판정자와 근거 |
| --- | --- | --- | --- |
| `src/tasks/automation_tasks.py` | 570 | 분할 불필요 | M3. 큐 등록·상태 전이·결과 후처리를 책임 행렬로 정리해 뒤섞임 없음. 테스트가 `SessionLocal` 등을 patch 해 위치 제약 |
| `src/app/services/automation_orchestrator.py` | 550 | 분할 불필요 | M3. 같은 근거 |
| `src/app/api/v1/chatbot.py` | 534 | 분할 완료 잔여 | 2차 분할로 792 -> 534. 추가 제안 없음 |
| `src/rag/structured_data.py` | 522 | 분할 비권고 | A1. 진입점 `retrieve_structured_data` 하나에 헬퍼 17개가 종속된 허브-스포크. 코디네이터 호출 그래프로 독립 확인 |
| `src/app/services/bid_queries.py` | 521 | 분할 비권고 | M2. 변경 사유가 공고 조회 로직 하나로 수렴 |
| `src/ml/model_wrappers.py` | 514 | 분할 비권고 | A1. `BaseModelWrapper(ABC)` + 상속 6개의 단일 계층. 최상위 함수 0개 |
| `src/ml/trainer.py` | 502 | 분할 완료 잔여 | M1 제안 3경계 전부 실행 |

**줄 수는 후보를 고르는 장치이고 판정이 아닙니다.** 기준선을 내릴 때마다 걸린 모듈을 자동으로 자르지 않고 감사에 판정을 받았습니다. 세 모듈은 그 판정으로 자르지 않기로 했습니다.

### 8.1 남긴 과제: 함수 길이

남은 크기는 모듈 구조가 아니라 **함수 하나**에 몰려 있습니다. `retrieve_structured_data` 가 236줄로 `structured_data.py` 의 45퍼센트이고, 그 안 L369~L441 에 13줄+4줄 블록이 세 번 반복됩니다.

A1 은 C5(중복 여부)에 "이미 높은 수준으로 추출이 완료되어 추가 추출 불필요" 로 답했는데 틀렸습니다. **모듈 관점 감사는 함수 내부를 보지 않을 수 있습니다.** 체크리스트에 "최장 함수의 줄 수와 그 안의 반복 블록" 을 명시하지 않으면 이 층은 판정되지 않습니다.

이 과제를 지금 하지 않는 이유는 둘입니다.

1. **검증 수단이 다릅니다.** 심볼 이동은 `ast.dump` 동일성으로 동작 보존을 증명할 수 있지만, 함수 추출은 본문을 바꾸므로 그 증명이 불가능하고 테스트에만 의존합니다. 커버리지를 재려면 `pytest-cov` 추가가 필요하고 이는 사전 합의 사항입니다. 테스트 참조 수(21곳)는 커버리지가 아닙니다.
2. **문제가 발생한 증거가 없습니다.** 236줄이 버그나 변경 난이도를 실제로 일으킨 기록이 없습니다. 줄 수만으로 추출하면 이 문서가 세 번 경고한 숫자 맞추기가 됩니다.

재개 조건은 `pytest-cov` 승인 또는 이 함수에서 실제 결함이 나오는 것입니다.

---

## 9. 종결된 Orca 운영 판정

아래는 판정이 끝나 다시 논의하지 않는 항목입니다. `CURRENT_STATE.md` 4장에서
옮겨 왔습니다. **부트스트랩 정본에는 아직 판단이 남은 항목만 둡니다.**

| 판정 | 근거 | 재개 조건 |
| --- | --- | --- |
| 리뷰 Level 3 유지 | 결함 밀도 0.05 사전 등록, A/B 검출 0/3 | 새 결함 밀도 근거 확보 |
| 추론 등급: 기계적 분할은 medium 이 high 와 동등 | 품질 9항목 동일, AST 15/15, 정정 왕복 0 | S1 급 난이도 작업 발생 시 재측정 |
| 워커 모델 4종 전부 사용 가능 | flash-high, sonnet-4-6, opus-4-6-thinking, gemma-4-31b 읽기 전용 감사 4건 전부 저장소 무수정 | 없음 |
| 동시 쓰기 워커 3대 병렬 운용 가능 | 2026-08-18 T1-T3 3섹션 병렬, 파일 비중첩, 게이트 3건 전부 통과 후 병합 | 상한 변경 시 |
| 실사용 도구 결함 5건 종결 | 기동·Capsule·중복·산출물 경로(`76c3013`, `eb6f429`, `cef6623`, `b86d833`), Intent 사실 미전달(`08f4fe5`). 전부 문서상으로는 완비였다 | 없음 |

문서상 완비가 실사용 통과를 뜻하지 않는다는 것이 다섯 건의 공통 교훈입니다.
도구를 만들면 문서 검토가 아니라 실제 기동으로 확인합니다.

---

## 10. 제어 경계 fail-open 결함 9건 (2026-08-18 종결)

외부 지적 10건을 코드로 직접 검증한 결과입니다. 9건이 실재했고 전부 수정했습니다.
공통 기전은 하나입니다. **`실패`, `미검증`, `절단`, `미도달` 같은 중간 상태가 병합, 수집,
검증 경계에서 SUCCESS 로 승격됩니다.**

| 분류 | 결함 | 위치 | 커밋 |
| --- | --- | --- | --- |
| 데이터 | 수집 구간 부분 실패를 로그만 남기고 성공 합계 반환 | `api_collector.py` `_run_ranges` | `e1e50c5` |
| 판정 | `full_validation` 이 `run_mode` 불일치 실행을 재사용. 7개 액션이 `pipeline_id` 공유 | `automation_orchestrator.py` | `dcefb38` |
| 판정 | Level 1 게이트 JSON 키 5개 vs 게이트 6개. 린터 결과가 리뷰 키로 들어감 | `orca_level1_gate.py` | `d449f93` |
| 판정 | 건너뛴 게이트를 통과로 계산 (`--strict` 신설) | `orca_level1_gate.py` | `d449f93` |
| 판정 | Level 2 리뷰어가 절단된 diff 로 통과 판정 | `orca_run_reviewer.py` | `4c70a83` |
| 판정 | Dispatch 가 지시 도달 미확인을 종료 코드 0 으로 보고 | `orca_taskctl.py` | `31cb843` |
| 실행 | 알 수 없는 `run_mode` 가 0개 스텝 수행 후 SUCCESS | `automation_tasks.py` | `acd15ca` |
| 실행 | 종료된 요청이 늦은 final 콜백으로 뒤집힘 (`canceled` 만 보호) | `automation_orchestrator.py` | `acd15ca` |
| 실행 | 콜백 토큰에 만료 없음 (`max_age` 미전달) | `automation_tokens.py` | `acd15ca` |
| 런타임 | Dockerfile 이 `uv.lock` 미사용. CI 검증 의존성과 운영 이미지 불일치 | `Dockerfile` | `31cb843` |

### 10.1 판단 기준

- **중간 상태를 성공으로 승격하지 않습니다.** 다만 `skip` 을 무조건 실패로 바꾸지도
  않습니다. Level 1 게이트 5는 단독 실행에서 정당하게 건너뜁니다. 해법은 판정 종류에
  맞는 강제 모드(`--strict`, `--allow-truncated-diff`, `--allow-unverified-delivery`)를
  두고 병합 판정 호출에서만 켜는 것입니다.
- **부분 실패는 건수를 살리고 상태만 실패로 둡니다.** 예외만 올리면 실패 이전에 적재된
  건수가 통계에서 사라져 반대 방향으로 거짓 보고가 됩니다.
- **전제가 깨진 코드는 조건을 손보지 말고 경로를 제거합니다.** `run_mode` 대체 재사용은
  `pipeline_id` 가 액션마다 다를 때만 성립하는데 이 저장소는 전부 공유합니다.

### 10.2 반복 금지

- **결함 9건 중 5건은 기존 테스트가 잘못된 동작을 정상으로 고정하고 있었습니다.**
  구현부터 고치면 테스트가 깨지면서 수정이 회귀로 오인됩니다. 순서는 항상
  `계약(테스트) 정정 -> 구현 수정 -> negative 테스트 추가` 입니다.
- **키 존재만 보는 단언은 계약을 지키지 못합니다.** `"gate5_review_report" in gates` 는
  그 키가 린터 결과를 담고 있어도 통과했습니다. 이름이나 내용으로 대조합니다.
- **소스 전체를 되돌리는 반증은 신규 심볼이 있으면 import 오류로 무효입니다.** 결함
  로직만 국소적으로 되살려야 행동 반증이 됩니다.
- **Docker 를 로컬에서 못 쓰면 CI 잡으로 검증합니다.** CI 는 `fix/**` 브랜치 푸시에도
  돌므로 병합 전에 확인할 수 있습니다. 미검증 상태로 배포 경로를 바꾸지 않습니다.

---

## 11. 무료 워커 풀 운용 판정 (2026-08-18)

Gemini 주간 한도가 1.77% 까지 떨어져 builder 작업에 배정할 후보가 사라진 상황에서
무료 풀을 실사용한 결과입니다.

| 모델 | 판정 | 근거 |
| --- | --- | --- |
| `opencode/deepseek-v4-flash-free` | **주력 사용 가능** | 2026-08-20 에 일시적으로 목록에서 빠지고 `Model not found` 가 났다가 같은 날 복구됐다. 목록 이탈을 삭제로 읽지 않는다. 컨텍스트 1M, 추론 high. 테스트 계약 13건을 정확히 갱신했고 지시하지 않은 불변식 단정(`reviewer` 제외)까지 추가 |
| `cerebras/gemma-4-31b` | **에이전트 워커로 불가** | 무료 등급 분당 30K 토큰 상한. 하네스 오버헤드만으로 초과 (11.1) |

### 11.1 Cerebras 무료 등급은 Orca 워커를 태울 수 없습니다

공식 문서 기준 제약은 분당 요청 5회, 분당 30K 토큰, 시간·일 1M 토큰,
컨텍스트 65K(유료 131K)입니다.

에이전트는 매 턴 대화 전체를 재전송합니다. 따라서 **컨텍스트가 30K 를 넘는
순간 요청 한 건 자체가 분당 예산을 초과**해 어떤 대기로도 통과할 수 없습니다.
재시도 표시가 `attempt #1` 에서 늘지 않고 리셋되면 이 상태입니다. 느린 것이
아니라 수렴 불가입니다.

2026-08-18 1차 실측에서 Orca 프리앰블과 3,847자 Capsule 만으로 28K 가 찼습니다.
그때는 원인을 Capsule 크기로 보고 "10K 이하로 줄이면 도구 호출이 적은 작업은
가능하다" 고 적었습니다. **이 판정은 같은 날 2차 실측으로 반증됐습니다.**

2차 실측에서는 Orca Capsule 을 아예 쓰지 않고 **960바이트짜리 순수 지시**를
직접 넣었는데도 동일하게 `Tokens per minute limit exceeded` 로 수렴하지
못했습니다. 즉 예산을 쓰는 주체는 코디네이터가 주는 지시가 아니라
**에이전트 하네스(opencode)의 시스템 프롬프트와 도구 스키마**입니다.
이것은 코디네이터가 줄일 수 있는 부분이 아닙니다.

**결론: 무료 등급 Cerebras 모델은 지시를 아무리 줄여도 에이전트 워커가 될 수
없습니다.** 지시 압축으로 해결하려는 시도를 반복하지 마십시오. 사용하려면
유료 등급으로 상한을 올리거나, 하네스 없이 단발 API 호출로 쓰는 방법뿐입니다.

**모델 능력 문제가 아닙니다.** gemma4 는 지시받은 코드 수정과 테스트 4케이스를
전부 정확히 작성했고, 검증·커밋·보고에만 도달하지 못했습니다.

### 11.2 probe 가 통과해도 워커는 뜨지 못할 수 있습니다

`probe_model` 은 `build_probe_env` 로 저장소 `.env` 의 `CEREBRAS_API_KEY` 를
주입해 호출합니다. `orca terminal create` 는 주입하지 않습니다. **두 경로의
환경이 달라 probe 결과가 워커 기동 가능 여부를 보장하지 않습니다.**

opencode 는 프로젝트 `.env` 를 읽지 않으므로 기동 명령에서 직접 넣습니다.

```bash
orca terminal create --worktree "path:<worktree>" \
  --command "sh -lc 'set -a; . <repo>/.env; set +a; exec opencode --model cerebras/gemma-4-31b'"
```

`.env` 는 Git 미추적이라 격리 트리에 따라가지 않습니다(10장). 값을 복사하지
말고 위처럼 주 저장소 경로를 읽게 하십시오.

### 11.3 반복 금지

- **분당 토큰 상한이 하네스 오버헤드보다 낮은 모델에 워커를 배정하지
  마십시오.** 지시를 줄여 해결하려는 시도는 2026-08-18 에 두 번 실패했습니다.
  배정 전에 상한을 확인하고, 상한이 30K/분 수준이면 후보에서 제외하십시오.
- **`probe` 통과를 워커 기동 가능으로 읽지 마십시오.** 기동 직후 터미널
  출력을 실제로 확인해야 합니다. `Unauthorized` 는 종료 코드 0 과 함께 옵니다.
- **무료 풀 개방 조건은 역할과 위험도로만 통제합니다.** 2026-08-18 부터
  `builder` 와 쓰기 범위를 허용합니다. 산출물이 Level 1 게이트와 테스트를
  거쳐 코디네이터가 병합을 결정하므로 오류가 저장소에 그대로 들어가지
  않습니다. `reviewer` 는 병합 판정에 직결되므로 계속 제외합니다.
## 12. 제어 평면 검증 경계 계약 불일치 17건 (2026-08-18 2차 종결)

10장 수정 직후 같은 스냅샷을 다시 감사해 찾은 결함입니다. 10장이 "중간 상태가
SUCCESS 로 승격되는" 계열이었다면, 이번 계열은 **검증 도구끼리 주고받는 계약이
어긋나 검증 자체가 성립하지 않던** 것입니다.

| 분류 | 결함 | 위치 | 커밋 |
| --- | --- | --- | --- |
| 계약 | Capsule 이 가르치는 보고 스키마가 검증기 `REQUIRED_FIELDS` 와 불일치. 필수 필드 7개 누락 | `orca_taskctl.py` | `f4b4db0` |
| 계약 | `finalize` 가 Reviewer 에 `--base/--branch` 전달. Reviewer 는 `--diff-base/--diff-branch` 만 수용 | `orca_taskctl.py` | `f4b4db0` |
| 판정 | `finalize` 가 `--tests`/`--strict` 미전달. 테스트를 한 번도 실행하지 않고 통과 | `orca_taskctl.py` | `f4b4db0` |
| 판정 | 명시된 작업 트리가 없으면 주 저장소로 대체. 변경분 없는 저장소를 검사해 통과 | `orca_taskctl.py` | `f4b4db0` |
| 판정 | `allowed_write_files` 가 빈 목록이면 모든 파일 수정이 허용됨 | `orca_contract.py` | `a541f64` |
| 판정 | `commit_count == 0` 이고 `changed_files` 도 비면 무작업 `succeeded` 통과 | `summarize_worker_done.py` | `a541f64` |
| 실행 | 알 수 없는 `run_mode` 를 가장 무거운 `manual_full_task` 로 대체 | `automation_jobs.py` | `f4b4db0` |
| 판정 | `--json` 호출의 비JSON·빈 응답을 성공으로 판정 | `orca_taskctl.py` | `ac56ceb` |
| 계약 | `TIER_POLICY` 배정과 `suitable_for` 가 36개 중 9개 불일치 | `orca_model_router.py` | 아래 12.3 |
| 표시 | 산출 불가 공고의 `optimal_price: 0` 을 "추천 투찰가 0원" 으로 표시 | `chatbot_format.py` | `8481522` |
| 판정 | PSI 표본 부재를 `0.0` 으로 돌려 STABLE 로 승격 | `src/ml/monitoring.py` | `8481522` |
| 실행 | 검증할 모델·표본이 없는 예측 스텝이 SUCCESS | `automation_tasks.py` | `e094887` |
| 판정 | 필수 테이블 누락·벡터DB 공백이 경고 문구만 남기고 SUCCESS | `automation_tasks.py` | `e094887` |
| 실행 | 야간 스케줄 후속 집계 실패가 최종 상태에 안 드러남 | `scheduled_tasks.py` | `e094887` |
| 판정 | 카탈로그에 없는 `action_key` 를 SUCCESS 로 종결 | `automation_orchestrator.py` | `90ae36c` |
| 판정 | 상태 동기화 예외를 문구로만 남기고 `found: True` | `automation_status_tool.py` | `90ae36c` |
| 표시 | 날짜 파싱 실패 시 조건을 빼고 전체 기간을 조회 | `src/rag/structured_data.py` | `90ae36c` |

### 12.1 가장 비쌌던 것은 스키마 불일치입니다

`WORKER_REPORT_SCHEMA` 는 워커에게 `outcome`, `blocked_by` 를 쓰라고 가르쳤고
`summarize_worker_done.py` 는 `status`, `blocking_issues`, `task_id`, `branch`,
`commit`, `read_files`, `verdict` 를 요구했습니다. 정규화 계층은 없었습니다.

**워커가 지시를 정확히 따를수록 필수 필드 누락으로 거부됩니다.** 잘못된 코드가
들어오는 방향이 아니라 재작업이 반복되는 방향의 손해이며, 코디네이터 토큰을
아끼려고 만든 구조가 정확히 그 지점에서 토큰을 새게 했습니다.

### 12.2 mock 경계가 계약 불일치를 통째로 숨겼습니다

Reviewer 인자 불일치는 `finalize --reviewer` 를 argparse 단계에서 실패시켰습니다.
**Level 2 는 한 번도 실행된 적이 없습니다.** 그런데 기존 테스트 89건은 전부
통과했습니다. `_run_command` 를 mock 해 종료 코드와 JSON 만 흉내냈기 때문입니다.

수정한 테스트는 finalize 가 조립한 인자 목록을 **실제 하위 파서
(`orca_run_reviewer._parse_args`, `orca_level1_gate.parse_arguments`)에 먹입니다.**
도구를 조합하는 코드는 조합 결과가 상대 도구에 실제로 받아들여지는지를
검증해야 합니다.

### 12.3 모델 라우터의 정본은 `TIER_POLICY` 입니다

`select_model()` 은 `suitable_for` 를 검사하지 않습니다. 실제로 돌아가는 것은
`TIER_POLICY` 뿐이고 `suitable_for` 는 장식이었으므로, 둘이 달라도 코드가
어느 쪽이 틀렸는지 말해 주지 않습니다. 2026-08-18 대조에서 배정 조합 36개 중
9개가 어긋났습니다.

**`TIER_POLICY` 를 정본으로 확정합니다.** 운영에서 조정해 온 쪽이고 행동
변화가 없어 위험이 낮습니다. `suitable_for` 를 거기에 맞추고, 다시 어긋나면
실패하는 불변식 테스트를 넣었습니다. `gemini-flash-low` 는 종전 판정대로
`reviewer`·`builder` 에서 계속 제외하며 이것도 테스트로 고정돼 있습니다.

### 12.4 실패를 0 으로 표시하면 사용자가 답으로 읽습니다

`bid_prediction_tool` 은 비예가 공고와 모델 전량 실패에 `skipped: True` 와 함께
`optimal_price: 0`, `prediction_rate: 0` 을 담습니다. 포맷터가 이 값을 그대로
찍어 **"추천 투찰가 0원, 예상 낙찰률 0.0%"** 로 표시했습니다. 정상 예측과
구분이 없어, 실패가 아니라 0원이라는 답으로 읽힙니다.

`skipped` 항목은 금액 대신 `산출 불가`, 낙찰률 대신 `-` 를 쓰고 사유를 함께
붙입니다. 사용 모델 요약에서도 제외합니다.

**0 은 "값이 없음" 의 표기가 아닙니다.** 숫자 자리에 실패를 0 으로 채우면
계산 결과와 구별되지 않습니다. 표시 계층에서도 fail-open 이 성립합니다.

### 12.5 상태를 안 붙이면 성공이 되는 규약은 fail-open 입니다

`run_automation_pipeline` 의 디스패치 루프는 스텝이 2요소 튜플을 돌려주면
`metrics["status"]` 가 없을 때 `STATUS_SUCCESS` 를 기본값으로 줍니다
(`automation_tasks.py:427-433`). 편의를 위한 기본값이지만, **스텝 작성자가
상태를 빠뜨리는 것과 성공을 선언하는 것이 구별되지 않습니다.**

`_step_predict` 는 등록된 모델이 0개여도, `_step_inspect` 는 DB 필수 테이블이
없거나 ChromaDB 가 비어 있어도 이 경로로 성공이 됐습니다. 둘 다 `partial_success`
를 명시하도록 고쳤습니다. 이 상태는 파이프라인을 실패로 표시하되 중단하지는
않으므로 남은 스텝의 진단 정보를 잃지 않습니다.

기본값을 실패로 뒤집는 방법도 있으나, 정상 스텝 다수가 2요소 튜플을 쓰고
있어 광범위한 회귀를 부릅니다. **원천에서 상태를 명시하는 쪽을 택했습니다.**

### 12.6 Cursor Auto 는 빈 출력으로 끝날 수 있습니다

2026-08-18 실측에서 `cursor-agent -p --model auto --mode plan` 이 **5회 중 3회
출력 없이 종료 코드 0** 으로 끝났습니다. 프롬프트를 짧게 줄여도 재현됐습니다.
같은 질문을 DeepSeek 에 주면 4회 전부 정확히 답했습니다.

**빈 출력을 "결함 없음" 으로 읽으면 코디네이터 자신이 fail-open 이 됩니다.**
무료 조사 워커의 주력은 `opencode-deepseek` 로 두고, Cursor 는 `--mode plan`
으로 읽기 전용을 도구 차원에서 강제해야 할 때만 씁니다. 프롬프트는 stdin
으로 넣습니다. 인자로 주면 무시됩니다.

### 12.7 반복 금지

- **같은 계약을 두 곳에 손으로 적지 마십시오.** 지시하는 쪽과 검사하는 쪽이
  갈리면 반드시 어긋납니다. 나눌 수 없으면 일치를 테스트로 강제하십시오.
- **하위 프로세스 호출을 mock 한 테스트는 인자 호환성을 증명하지 않습니다.**
  상대 파서를 임포트해 실제로 파싱시키십시오.
- **빈 허용 목록의 의미는 읽기와 쓰기가 정반대입니다.** 읽기는 판정 근거 없음,
  쓰기는 전면 금지입니다. 같은 함수로 처리하지 마십시오.
- **검증 대상 경로가 없을 때 다른 경로로 대체하지 마십시오.** 검증할 것이
  없으면 통과가 아니라 오류입니다.
- **`--json` 을 붙여 호출했으면 JSON 이 아닌 응답은 실패입니다.** 파싱 실패를
  관대하게 넘기면 미확인이 SUCCESS 로 승격됩니다.
- **강제되지 않는 메타데이터를 두 벌 두지 마십시오.** 검사하지 않는 필드는
  반드시 실제 동작과 어긋납니다. 정본을 정하고 불변식으로 묶으십시오.
- **실패와 미산출을 0 으로 표시하지 마십시오.** 숫자 자리의 0 은 계산 결과와
  구별되지 않습니다. 표시 계층도 fail-open 대상입니다.
- **"상태 미지정 = 성공" 기본값을 만들지 마십시오.** 빠뜨린 것과 선언한 것이
  같아집니다. 기본값을 바꾸기 어려우면 원천에서 상태를 명시하십시오.
- **후속 작업 실패를 최종 상태에서 지우지 마십시오.** 야간 스케줄의 기관 이력
  집계 실패는 추론의 `inst_hist_rate` 를 낡게 만들어 train/serve skew 로
  이어집니다. 중단하지 않는 것과 보고하지 않는 것은 다릅니다.
- **워커의 빈 응답을 결과로 세지 마십시오.** 종료 코드 0 과 빈 출력이 함께
  오는 도구가 있습니다. 응답 없음은 실패입니다.
- **해석하지 못한 필터를 빼고 조회하지 마십시오.** 조건이 빠진 전체 범위
  결과가 사용자가 지정한 범위의 답으로 돌아갑니다.
- **표본이 없는 상태를 안정으로 읽지 마십시오.** 감시할 근거가 없는 것과
  변화가 없는 것은 다릅니다. PSI 는 표본 부재에 예외를 던지고 호출부는
  `INSUFFICIENT_DATA` 를 돌려줍니다.

---

---

## 13. 상위 경계 상태 유실 10건 (2026-08-19 3차 종결)

3차 외부 감사(GPT)와 교차 검증(Grok)이 지적한 10건이 **전부 실재했다.** 코디네이터가
코드와 실행으로 재현해 확인했고, 신규 결함 1건을 추가로 찾았다.

**계열이 바뀌었다.** 10장·12장은 "검증하지 않고 성공" 이었고, 이번은 **하위 컴포넌트가
실패·불능을 알고 있는데 상위 orchestration·API 경계에서 그 상태를 잃어버리는** 것이다.
개별 수정이 아니라 반환 계약의 문제다.

### 13.1 strict 게이트가 어떤 입력에도 실패했다

`finalize` 는 Level 1 을 먼저 돌리고 리뷰어를 그 뒤에 돌린다. 그래서 Level 1 시점에
리뷰 보고서는 **존재할 수 없다.** 그런데 `--strict` 가 모든 건너뜀을 실패로 세어
게이트 5 가 항상 skipped 이고, 결과적으로 `finalize --strict` 는 어떤 입력에도
exit 1 을 냈다. 기존 테스트 89건은 `_run_command` 를 mock 해 Level 1 결과를 PASS 로
돌려주었기 때문에 이 조합을 잡지 못했다.

**해결은 `--allow-skipped-gates` 를 기본으로 켜는 것이 아니다.** 그러면 게이트 3
(테스트) 건너뜀까지 함께 열려 원래의 fail-open 으로 되돌아간다. 대신 `GateResult` 에
`required` 를 두어 두 가지를 구분한다.

| 구분 | 의미 | strict 판정 |
| --- | --- | --- |
| 필수 건너뜀 | 검증했어야 하는데 하지 않음 | 실패 |
| 적용 대상 아님 | 이 호출의 검증 범위가 아님 | 통과 |

게이트 5 는 리뷰 보고를 넘기지 않은 호출에서 적용 대상이 아니다. 리뷰 계약은 뒤이어
도는 `orca_run_reviewer` 가 **같은 `evaluate()`** 로 판정하므로 검증이 빠지지 않는다.
그래서 **strict 인데 리뷰어를 돌리지 않는 조합은 도구를 하나도 실행하기 전에 거부한다.**

게이트 3 은 Capsule 의 `allowed_write_files` 에 코드 파일이 있는지로 필수 여부를 정한다.
문서만 바꾸는 Task 까지 테스트를 강제하면 strict 가 상시 실패해, 운영자가 우회 옵션을
습관적으로 켜게 된다.

### 13.2 스텝 반환 계약이 status 를 버렸다

`run_automation_pipeline` 은 2요소 튜플을 받으면 `metrics` 에 `status` 키가 없을 때
SUCCESS 로 승격한다. `_step_rag` 가 `rebuild_knowledge_base` 의 `status` 를 버리고
2요소 튜플을 돌려주어 **KB 재구축 실패가 성공으로 보고**됐다. 기존 벡터가 남아 있으면
후속 점검에서 `vector_count > 0` 이라 파이프라인 전체가 성공으로 끝난다.

3요소 튜플로 status 를 전파하고, 허용된 네 값 밖은 실패로 강등한다.

### 13.3 검사 불능(None)과 측정값 0 은 다르다

`_check_chroma_vectors` 는 파일 부재나 예외에서 `None` 을 돌려주는데 판정은
`== 0` 만 봤다. `db_table_count` 도 같았다. **`0` 은 검사했고 비어 있다는 측정값이고,
`None` 은 검사하지 못했다는 뜻이다.** 후자를 통과시키면 점검의 목적이 사라진다.

같은 원리로 `retrieve_semantic_context` 가 검색 성공 0건과 ChromaDB 예외를 모두 빈
리스트로 돌려주던 것을 `SemanticSearchResult(ok, documents, error)` 로 나눴다.
**하위 호환 래퍼를 남기지 않았다.** 두 경로가 남으면 호출부가 조용히 예전 경로에 머문다.

`query_skipped` 도 같다. 잘못된 날짜로 조회를 건너뛰었는데 0 통계를 문맥에 실으면
모델은 "조회했더니 0건" 으로 읽는다. 수치 줄을 아예 만들지 않는다.

### 13.4 판정 문구 매칭에 의존하지 않는다

치명 경고를 `warning.startswith("DB 필수 테이블 누락")` 같은 문자열 매칭으로 골라내면
**문구를 다듬는 순간 판정이 조용히 깨진다.** 경고를 만들 때 치명 목록에 함께 넣는다.

### 13.5 계약 검증은 형까지 본다

`commit_count` 가 문자열 `"0"` 이면 `== 0` 이 거짓이라 무작업 완료 보고가 그대로
통과했다. `bool` 은 `int` 의 하위형이라 `True` 도 1 로 통과한다. 필드 존재 여부만
보는 검증은 계약 검증이 아니다.

**`pydantic` 을 쓰지 않았다.** 이 스크립트들은 `uv` 없이 `python3` 로 직접 실행되므로
표준 라이브러리 밖 의존성을 늘리면 실행 자체가 깨진다. `PyYAML` 을 피한 것과 같은 이유다.

### 13.6 라우터 probe 가 풀 키를 그대로 넘겼다 (신규)

`probe_model` 은 풀 키(`gemini-flash-medium`)로 provider 를 찾은 뒤, 명령에는 **그 풀
키를 그대로** 넣었다. CLI 는 실제 모델 ID(`gemini-3.7-flash-medium`)를 요구하므로
"알 수 없는 모델" 로 거부한다. `list` 출력과 문서가 안내하는 이름이 풀 키이므로
**이것이 기본 사용법이었고, 살아 있는 모델 두 개를 사용 불가로 오판했다.**

가용성 판정이 틀리면 워커 배정이 통째로 틀어진다. 판정 도구의 결함은 판정 대상의
결함보다 파급이 크다.

### 13.7 무료 풀만 불변식 밖에 있었다

`TIER_POLICY` 경로는 `suitable_for` 불변식으로 묶여 있는데 `select_model` 이 무료
후보를 앞에 붙일 때는 걸러 내지 않았다. 주 모델을 제외하면 `investigator` 전용 모델이
`builder` 로 배정된다. **테스트로만 맞추면 후보를 추가할 때마다 다시 어긋난다.**
실행 코드가 계약을 지키게 한다.

### 13.8 반복 금지

1. 게이트 건너뜀을 일괄로 실패 처리하지 않는다. 적용 대상 여부를 구분한다.
2. strict 판정을 뚫으려고 건너뜀 허용 옵션을 상시로 켜지 않는다.
3. 스텝이 하위 호출의 `status` 를 버리지 않는다. 2요소 튜플 승격 규칙에 기대지 않는다.
4. `None` 을 `0` 으로 취급하지 않는다. 렌더링 기본값 `get(key, 0)` 도 같은 함정이다.
5. 반환 계약을 바꿀 때 하위 호환 래퍼를 남기지 않는다.
6. 판정을 사용자 표시 문구의 부분 일치로 하지 않는다.
7. 계약 검증에서 타입과 값 집합을 함께 본다.
8. `scripts/` 아래 도구에 표준 라이브러리 밖 의존성을 넣지 않는다.

### 13.9 조율에서 배운 것

- **Capsule 을 워크트리 밖 절대 경로로 지시하면 워커가 매 디렉터리마다 권한 승인을 요구한다.** Capsule 을 각 워크트리에 복사해 상대 경로로 지시한다. opencode 는 `~/.config/opencode/opencode.json` 의 `permission.external_directory` 로도 끌 수 있으나, **저장소의 `opencode.json` 은 Git 추적 대상이므로 권한 완화를 그쪽에 넣지 않는다.**
- **Task 사양(`--spec`)의 Capsule 경로 자리표시자를 실제 경로로 채운다.** 워커는 고지문보다 TASK 블록을 먼저 읽는다.
- **`review_checklist` 없는 Capsule 은 Level 2 를 실행할 수 없다.** 항목 키는 `id`, `question`, `defect_when` 이며 `defect_when` 은 산문이 아니라 `yes`/`no` 극성이다.
- **Capsule 의 "이미 확인된 사실" 이 틀릴 수 있다.** 호출부가 3곳이라고 단정했으나 워커가 4번째(`AsyncVectorStore.search_similar_docs`)를 찾아냈다. `escalate_when` 에 사실 불일치를 넣어 두었기에 드러났다.
- `dispatch` 의 `terminal_not_settled` 로 인한 exit 3 은 여전히 오탐이다. 판정이 Dispatch 전에 이루어지고 이후 재확인이 없다.

### 13.10 코디네이터 토큰은 왕복 횟수로 소모된다

2026-08-19 세션에서 사용자가 "작업량에 비해 사용량이 과하다" 고 지적했고, 확인한
결과 **실제로 코디네이터 측 낭비가 있었다.**

도구를 한 번 호출할 때마다 그 시점까지의 대화 전체가 다시 전송된다. 이 세션의
문맥에는 직전 세션 압축 요약, `AGENTS.md`, 메모리 인덱스, 그리고 사용자가 붙여 넣은
감사문 2건이 들어 있었다. **그 큰 문맥이 도구 호출 70여 회에 곱해졌다.** 비용은 한
일의 양이 아니라 호출 횟수에 비례한다.

| 실제로 한 낭비 | 회피법 |
| --- | --- |
| 보고 검증·게이트·리뷰·diff 를 네 번에 나눠 실행 | 한 호출로 묶는다 |
| 워커 터미널을 진행 확인용으로 반복해서 읽음 | `until` 배경 대기로 커밋 발생만 감지한다 |
| 게이트·테스트 출력을 `tail` 로 통째로 받음 | python 한 줄로 판정 필드만 뽑는다 |
| Capsule 경로를 잘못 줘 워커 3대에 정정 왕복 | Dispatch 전 점검표(스킬 3.3)를 통과시킨다 |
| `permission` 스키마를 외부에서 시행착오로 조회 | 저장소의 검증기·설정 소스를 먼저 읽는다 |

**워커 터미널 읽기가 단가가 가장 높다.** ANSI 장식과 넓은 여백이 대부분이라 정보량
대비 비용이 크다. 도달 확인, 정체 판정, 모달 처리 세 경우에만 쓴다.

재발 방지는 [`.agents/skills/orca-section-coordination/SKILL.md`](../../.agents/skills/orca-section-coordination/SKILL.md)
3.2·3.3 절에 반영했다. **위임은 여전히 가장 큰 지렛대이지만 검증 비용은 남으므로
절감률은 50~60% 다**(3.1 절).

### 13.11 `check --ack` 는 배치 ID 를 받는다

`orca orchestration check` 는 배치(delivery) 단위로 응답하며, 최상위 `deliveryId` 가
배치 식별자이고 `messages[].id`(`msg_...`)는 그 안의 개별 메시지다. **`--ack` 는
`deliveryId` 를 받는다.** `msg_...` 를 넘기면 다음 오류가 난다.

```
stale_delivery: Delivery msg_88456b5c227b does not belong to this Run.
```

**이 문구가 오해를 부른다.** Run 바인딩 문제처럼 읽히지만 실제 원인은 식별자 종류다.
2026-08-19 에 이 문구를 보고 등록된 Run 을 전부 순회하며 재시도했고, 원인을 찾지
못한 채 "런타임 부기 문제이며 영향 없음" 으로 넘겼다. **판정이 틀렸다.**

영향은 실재했다. 배치는 FIFO 로 하나씩 나오므로 첫 배치를 ack 하지 않으면 그 뒤
배치가 보이지 않는다. 그날 워커의 `question` 이 두 번째 배치에 있었는데 정규 경로로는
드러나지 않았다. 터미널 출력에서 우연히 발견해 답했으나, 그러지 않았다면 워커가
응답 대기로 멈춰 있었을 것이다.

**배달 소진은 감독 절차의 일부다.** 비어질 때까지 ack 를 반복한다. 절차는
[`.agents/skills/orca-section-coordination/SKILL.md`](../../.agents/skills/orca-section-coordination/SKILL.md) 3.4 절.

**원인을 찾지 못한 것을 "영향 없음" 으로 결론짓지 않는다.** 이 세션이 내내 제거해 온
fail-open 과 같은 형태다. 미확인은 정상이 아니다.

---

## 14. 병합 게이트 자체의 구멍 3건 (2026-08-19 4차 종결)

4차 외부 감사가 지적한 7건이 전부 실재했다. **그중 세 건은 직전 라운드에서
게이트를 고치며 내가 만든 것이다.** 게이트를 손보는 작업은 그 자체가 게이트를
뚫을 수 있다.

### 14.1 코드 확장자 양성 목록은 조용히 뚫린다

Gate 3 의 필수 여부를 `CODE_SUFFIXES = (".py",)` 로 판정했다. 목록에 없는 형식은
전부 면제되므로 **`.ts`, `.tsx`, Dockerfile, JSON 변경이 테스트 하나 없이 strict 를
통과했다.** 실제 저장소에는 프론트엔드가 있고 CI 에 `npm run test` 도 있는데
Level 1 은 그것을 하나도 요구하지 않았다.

**판정을 뒤집는다.** 코드를 찾지 말고 **문서 전용만 면제한다.**

```python
DOC_ONLY_SUFFIXES = frozenset({".md", ".rst", ".adoc"})
# 기본은 "검증 필요". 새 파일 형식이 들어와도 뚫리지 않는다.
```

양성 목록은 추가를 잊으면 열리고, 면제 목록은 추가를 잊으면 닫힌다. **잊었을 때
어느 쪽으로 실패하는가**가 설계 기준이다.

판정 근거도 Capsule 의 `allowed_write_files` 에서 **Gate 1 이 구한 실제
`changed_files`** 로 옮겼다. 선언은 "고쳐도 되는 범위" 일 뿐이라, 범위를 넓게 잡아
둔 Task 는 문서만 고쳐도 테스트를 요구받고 좁게 적어 둔 Task 는 코드를 고쳐도
면제됐다.

### 14.2 도달 증명은 시도마다 새 표지로 한다

Dispatch 후 도달 확인을 `task_id` 와 Capsule 경로로 했다. **재 Dispatch 하면 화면에
남은 이전 시도의 잔상이 그대로 통과한다.** 지시가 도달하지 않았는데 성공으로
보고되므로 fail-open 이다.

직전 수정이 "Dispatch 전 판정" 오탐을 고치면서 반대 방향 오탐을 만들었다.
**이쪽이 더 위험하다.** 시도마다 `ORCA_DELIVERY_PROBE_<난수>` 를 만들어 고지문에
싣고 그 표지만 찾는다. 표지가 없으면(고지 실패, `--no-capsule-notice`) 증명 수단이
없는 것이므로 미확인으로 둔다.

### 14.3 표지 검사는 첫 실사용에서 두 번 틀렸다

도입 직후 워커 2대가 모두 `not_observed` 로 나왔고 **원인이 서로 달랐다.**

| 워커 | 실제 | 원인 |
| --- | --- | --- |
| Gemini | 도달함 | 3초 폴링 사이에 표지가 스크롤아웃 — 오탐 |
| opencode | 미도달 | 상태줄 표지를 보자마자 준비로 판정해 주입이 삼켜짐 — 진짜 |

표지는 뷰포트에 잠깐 머물다 워커 출력에 밀려난다. **폴링은 1초 이하로 촘촘해야
한다.** 그리고 상태줄 표지는 TUI 가 그려지자마자 나타나므로 백엔드가 연결 중이어도
준비로 보인다. **표지가 안정화 시간만큼 계속 보여야 준비로 인정한다.** 단독 `>`
프롬프트는 입력 대기가 확실하므로 즉시 인정한다.

**판정 방향은 두 경우 모두 옳았다.** 성공으로 넘긴 것이 하나도 없었다. 옛 방식이면
Gemini 쪽을 통과시켰을 것이다. 오탐은 고치면 되지만 fail-open 은 모르고 지나간다.

### 14.4 N/A 와 도구 오류를 구분한다

Gate 5 가 `review_report_path is None or capsule_path is None` 을 하나로 묶어
N/A 처리했다. **리뷰 보고서를 명시했는데 Capsule 만 빠진 호출도 조용히 통과했다.**
보고서를 안 준 것은 "이 단계에서 리뷰를 안 한다" 는 뜻이지만, 주고서 대조 정본이
없는 것은 호출 오류다.

### 14.5 인용 문구도 근거 주장이다

`query_skipped` 에서 통계, Evidence, 대체 답변의 0 값은 막았는데 인용 문구 한
경로가 남아 있었다. 조회하지 않았는데 "근거: DB 집계 기반" 이 붙고, 벡터가 있으면
**"근거: 혼합 근거"** 가 붙었다. 후자가 더 나쁘다. 조회하지 않은 것을 근거에
섞였다고 단언한다.

### 14.6 반복 금지

1. 검증 면제를 양성 목록으로 만들지 않는다. 잊었을 때 닫히는 쪽으로 설계한다.
2. 게이트 판정 근거를 선언이 아니라 실제 변경에서 가져온다.
3. 도달 증명에 재사용 가능한 식별자를 쓰지 않는다. 시도마다 새 표지를 만든다.
4. 증명 수단이 없는 상태를 성공으로 돌리지 않는다.
5. 화면 관찰 기반 판정은 폴링 간격이 관찰 대상의 수명보다 짧아야 한다.
6. TUI 표지 하나로 입력 수용 준비를 단정하지 않는다.
7. "적용 대상 아님" 과 "호출 오류" 를 같은 분기로 묶지 않는다.
8. 사용자에게 보이는 근거 문구도 데이터 주장이다. 데이터 경로와 같은 기준으로 막는다.

---

## 15. 게이트 3 은 판정만 고쳤고 실행은 그대로였다 (2026-08-19 5차 종결)

4차에서 "비-Python 변경 무검증 통과" 를 닫았다고 기록했지만, 닫힌 것은 **검증이
필요한지 판정하는 절반**뿐이었다. 5차 외부 감사(GPT)가 나머지 절반을 지적했고
코드로 재현해 확인했다.

### 15.1 필요 판정과 실행 대상이 분리되어 있었다

`.tsx` 변경은 `required=True` 가 되지만, 실제로 실행되는 것은 `CAPSULE_TEMPLATE`
에 박혀 있던 backend pytest 두 줄이었다. `expand_intent_to_capsule()` 에는
`verification_commands` 치환 슬롯 자체가 없어 Intent 가 무엇을 적든 무시됐고,
`extract_pytest_specs()` 는 pytest 아닌 명령을 조용히 버렸다. 결과는
**frontend 변경이 무관한 backend pytest 통과로 병합되는 상태**였다.

"무검증 통과" 를 막았어도 "엉뚱한 검증 통과" 가 남으면 게이트는 여전히 열려 있다.
판정과 실행을 각각 확인해야 한다.

해결: 변경 파일을 `backend` / `frontend` 영역으로 나누고, 각 영역을 덮는 검증
명령이 없으면 `--strict` 에서 실패한다. Capsule 의 `verification_commands` 를
게이트가 직접 읽어 실행하고, Intent 지정을 존중하며, 쓰기 범위에 `frontend/` 가
있으면 frontend 검증을 자동으로 붙인다. 실행은 허용 목록(`uv run pytest ...`,
`npm ci`, `npm run <script>`)으로 제한하고 나머지는 게이트 3 실패로 거부한다.
임의 문자열을 셸에 넘기면 Capsule 을 쓰는 쪽이 코디네이터 권한을 얻는다.

### 15.2 rename 은 새 경로만 남는다

`git diff --name-only` 는 rename 의 새 경로만 보여 준다. `a.py` 를 `docs.md` 로
옮긴 변경이 `changed_files == ["docs.md"]` 가 되어 문서 전용 면제를 받았다.
`--name-status -z -M` 으로 원본 경로까지 받아 확장자 판정에 함께 넣는다.

### 15.3 반복 금지

1. 게이트를 고쳤다고 할 때 "판정" 과 "실행" 을 각각 확인한다. 한쪽만 고치면 열려 있다.
2. 실행할 검증을 중간 단계에서 걸러내지 않는다. 거른 것은 아무도 실행하지 않는다.
3. 인식하지 못한 검증 명령을 조용히 버리지 않는다. 거부는 실패로 드러낸다.
4. Capsule 문자열을 셸에 넘기지 않는다. 허용된 실행기만 고정 인자 목록으로 만든다.
5. 변경 파일 목록은 rename 원본까지 본다. 새 경로만으로 성격을 단정하지 않는다.
6. 수정 보고에서 "전부 완료" 는 미룬 부분이 하나도 없을 때만 쓴다.

---

## 16. 영역 하나로 묶으면 아무 명령이나 하나로 덮인다 (2026-08-19 6차)

5차에서 검증 명령을 일반화하면서 변경을 `backend` / `frontend` 두 **영역**으로
나눴다. 6차 감사(GPT)가 영역 단위 판정의 구멍 둘을 지적했고 재현해 확인했다.

### 16.1 `npm run lint` 하나가 test 와 build 를 대신했다

`npm run <script>` 는 스크립트 이름과 무관하게 frontend 영역을 덮은 것으로
쳤다. Intent 가 `npm --prefix frontend run lint` 하나만 적으면 test 도 build 도
돌지 않은 채 게이트가 통과했다.

해결: 영역 대신 **검증 능력(capability)** 으로 본다. `test` 는 `frontend_test`
를, `build` 는 `frontend_build` 를 덮고, 대응이 없는 스크립트는 실행은 되지만
아무 능력도 덮지 않는다. 통합 스크립트는 이름을 명시적으로 등록해야 한다.

### 16.2 Dockerfile 변경을 backend pytest 가 덮었다

`Dockerfile`, `docker-compose.yml`, `pyproject.toml` 이 모두 backend 로 분류돼
pytest 통과만으로 병합 가능했다. **5차에서 닫았다고 한 "무관한 검증으로 통과"
가 infra 에 그대로 남아 있었다.** 한 계열을 닫을 때는 같은 기전이 다른 입력에도
있는지 전수로 본다.

해결: `Dockerfile*` 은 `docker_build`, `docker-compose*.yml` 은
`compose_config` 를 요구한다. docker 는 공유 자원이므로 이 검증을 넣는 Task 는
`shared_resources` 에 선언한다.

`.github/workflows/**` 는 로컬 검증 수단이 없어 `backend_pytest` 로 남겼다.
**러너 없는 능력을 필수로 걸면 fail-open 이 fail-deadlock 이 될 뿐이다.**
워크플로우 변경은 브랜치 CI 가 검증한다.

### 16.3 요구와 부착의 기준이 갈라지면 통과 불가능한 Task 가 생긴다

Capsule 에 붙일 검증을 정하는 쪽(`orca_taskctl`)과 요구를 판정하는 쪽
(`orca_level1_gate`)이 각자 경로 규칙을 구현하면 어긋난 순간 아무도 통과할 수
없는 Task 가 만들어진다. 부착도 `required_capabilities()` 를 그대로 불러 쓴다.
문서 전용 Task 에 전량 pytest 가 붙던 것도 이 기준을 안 쓴 탓이었다.

### 16.4 경고는 아무도 고치지 않는다

`CURRENT_STATE.source_commit` 신선도는 허용 지연을 넘겨도 WARN 이라 exit 0 이었고,
실제로 6 커밋 뒤처진 채 통과하고 있었다. CI 는 `fetch-depth: 1` 이라 커밋 조회
자체가 실패해 항상 "미검증" 으로 내려앉았다. 지연 초과를 FAIL 로 올리고 CI
체크아웃에 `fetch-depth: 0` 을 줬다.

### 16.5 반복 금지

1. 검증 대상을 영역으로 묶지 않는다. 무엇을 확인했는지 능력 단위로 센다.
2. 한 계열을 닫을 때 같은 기전이 다른 입력에도 있는지 전수로 본다.
3. 러너 없는 능력을 필수로 걸지 않는다. 교착은 개선이 아니다.
4. 요구 판정과 검증 부착은 같은 함수를 쓴다. 두 번 구현하면 어긋난다.
5. 강제할 생각이 없는 검사는 WARN 으로 두지 않는다. 지키게 할 것이면 FAIL 로 만든다.
6. CI 에서 도는 검사가 CI 환경(얕은 클론 등)에서 무력화되지 않는지 확인한다.

### 16.6 러너가 없으면 만들거나, 능력을 두지 않는다

16.2 에서 `.github/workflows/**` 를 로컬 검증 수단이 없다는 이유로
`backend_pytest` 에 남겼다. 교착은 피했지만 **pytest 가 워크플로우를 검증하지
않는다는 사실은 그대로였다.** 러너가 없다는 것은 능력을 포기할 이유가 아니라
러너를 들일 이유다. `actionlint-py` 를 개발 의존성으로 추가해
`workflow_lint` 능력을 만들고 `make check-all` 과 CI 에도 배선했다.

셸 스크립트는 반대로 처리했다. 저장소에 `.sh` 가 0건이므로 능력을 두지 않는다.
쓰지 않는 도구를 먼저 들이면 G2 크로스 플랫폼 표면만 넓어진다. 첫 파일이
생기는 시점에 shellcheck 와 함께 추가한다.

`pyproject.toml` 은 `backend_pytest` 로 둔다. pytest 가 그 의존성 위에서
돌므로 무관한 검증이 아니다.

### 16.7 능력을 만들면 그 능력에 딸린 것도 함께 나와야 한다

능력 모델을 세운 뒤 6차 감사(GPT)가 세 곳의 누락을 찾았다. 셋 다 "새 구조가
생겨서 비로소 보이는" 것이지 기존 수정의 실패는 아니다.

1. **`.dockerignore` 가 `backend_pytest` 였다.** 빌드 컨텍스트를 정하는 파일인데
   확장자도 이름도 Dockerfile 이 아니라 일반 코드로 분류됐다. 여기서 `src/` 를
   제외하면 pytest 는 그대로 통과하고 이미지 빌드만 깨진다. 능력을 경로 규칙으로
   정할 때는 **그 능력에 실제로 영향을 주는 파일 전부**를 센다.
2. **docker 검증은 자동으로 붙는데 `shared_resources: docker` 는 아니었다.**
   스킬 문서는 선언을 요구하는데 템플릿은 `features_py` 만 고정으로 적고 있었다.
   `verification_commands` 를 슬롯화했을 때와 같은 결함이 옆 필드에 남아 있었다.
   **한 필드를 템플릿 고정에서 풀 때 같은 파일의 다른 고정 필드도 함께 본다.**
3. **조회 불가 커밋이 여전히 WARN 이었다.** CI 가 `fetch-depth: 0` 이 된 뒤로는
   "확인 불가" 가 곧 "값이 틀렸다" 는 신호다. 전제가 바뀌면 그 전제 위에 세운
   완화 규칙도 다시 본다. `.git` 이 없는 환경에서만 WARN 으로 남긴다.

`docker build` 의 인자는 제한하지 않는다. Capsule 을 쓰는 주체가 코디네이터이고
`shell=False` 로 실행하므로 주입 경로가 없다. 워커가 Capsule 을 쓰게 되면 그때
서명을 고정한다.

### 16.8 검증 불능을 확정된 실패로 단정하지 않는다

16.7 에서 "이력이 있는데 커밋을 못 찾으면 값이 틀린 것" 으로 보고 FAIL 을 냈다.
**전제가 틀렸다.** `fetch-depth: 0` 을 준 것은 `lint-and-validate` 잡 하나뿐이고
테스트 잡 셋은 여전히 얕은 클론이다. 얕은 클론은 이력을 가지고 있지만 커밋의
부재를 증명하지 못한다. 정상 값이 오타로 판정되어 세 플랫폼 테스트가 전부
깨졌다.

fail-open 을 뒤집어 fail-closed 로 만들 때 **"확인 불가" 를 "확정된 실패" 로
옮기면 같은 크기의 오류가 된다.** 확인 불가의 정직한 자리는 미검증이다.
판정은 `git rev-parse --is-shallow-repository` 로 부재를 증명할 수 있는
저장소인지 먼저 확인한 뒤에 내린다.

전제를 바꾸는 설정을 넣을 때는 **그 전제에 기대는 코드가 그 설정을 실제로 받는
경로에서만 도는지** 확인한다. 잡 하나에 준 설정을 저장소 전체의 성질로 읽었다.

### 16.9 병합 커밋이 지연 예산을 하나 더 먹는다

16.4 에서 `source_commit` 지연 초과를 FAIL 로 올린 직후 **그 규칙이 스스로에게
걸려 main 이 빨개졌다.** 작업 커밋 시점에는 지연 5 로 pre-commit 을 통과했는데,
`--no-ff` 병합 커밋이 하나 더 붙어 6 이 됐다. pre-commit 은 아직 존재하지 않는
병합 커밋을 볼 수 없다.

변경 한 건은 작업 커밋과 병합 커밋으로 **지연을 2 씩** 올린다. 허용치 5 는
정본을 건드리지 않는 변경 두 건까지만 버틴다. 정본을 손대는 커밋에서는
`source_commit` 을 그 시점 HEAD 로 갱신하고, 손대지 않는 변경이 연달아 두 건
이상이면 갱신 커밋을 따로 만든다.

허용치를 올려 회피하지 않는다. 이번에 실제로 정본이 낡아 있었고 검사는 제
일을 했다. 게이트가 사후에 main 을 빨갛게 만드는 것이 문제라면 답은 기준
완화가 아니라 병합 전에 지연을 확인하는 것이다.

### 16.10 능력 이름이 검증 범위를 담지 못하면 다시 무관한 검증이 된다

7차 감사(GPT)가 찾았다. `frontend/Dockerfile` 은 `docker_build` 를 요구하는데
그 능력을 덮는 명령이 `docker build .` 하나뿐이었다. 루트 `.dockerignore` 는
`frontend/` 를 제외하므로 **그 빌드는 문제의 파일을 읽지도 않는다.** 능력
단위로 바꿨는데도 능력 이름이 컨텍스트를 담지 못해 같은 자리로 돌아왔다.

능력 이름은 `docker_build:<컨텍스트>` 로 갈랐다. 요구는 Dockerfile 이 놓인
디렉터리에서, 제공은 `docker build` 의 위치 인자에서 계산한다. Dockerfile 이
늘어도 규칙이 그대로 확장된다.

같은 판정에서 인자 파싱 결함도 나왔다. 컨텍스트를 "마지막 토큰" 으로 읽으면
`docker build -t x` 의 **태그를 컨텍스트로 읽는다.** 값을 먹는 옵션을 건너뛰고
남은 위치 인자가 정확히 하나일 때만 받는다. 목록에 없는 옵션이 값을 먹으면
위치 인자가 둘이 되어 거부된다. 조용히 틀린 값을 고르지 않는다.

### 16.11 자원 점유는 선언된 범위가 아니라 실제 실행에서 나온다

`shared_resources` 를 쓰기 범위에서만 유도하면, Intent 가 docker 명령을 직접
적고 쓰기 범위에는 파이썬 파일만 둔 Task 가 점유 없이 docker 를 쓴다. 범위와
검증 명령 양쪽에서 능력을 모아 판정한다.

---

## 17. 읽기 전용 probe 는 쓰기 적합성을 예측하지 못한다 (2026-08-20)

### 17.1 만점은 변별이 아니다

2026-08-20 오전에 OpenRouter 무료 4종을 감사 6문항으로 재고 전부 6/6 을 받았다.
그래서 `FREE_POOL_ORDER` 순서를 문맥 크기와 응답 시간으로 매기고 **잠정**이라고
적었다. 같은 날 오후에 같은 네 모델에 쓰기 과제를 주자 둘이 실격했다.

**천장에 붙은 측정은 순위 근거가 아니라 측정 실패다.** 전원 만점이 나오면
과제가 쉬웠다는 뜻이지 모델이 동등하다는 뜻이 아니다. 그 결과로 순서를 매기지
말고 과제를 바꿔야 한다.

### 17.2 갈린 것은 코딩 능력이 아니라 막혔을 때의 행동이었다

Capsule 의 acceptance 에 만족 불가능한 조건이 하나 있었다(기존 테스트 1건이
새 판정 기준과 양립 불가). 통과 5종은 이 모순을 전부 정확히 인지했다.

    deepseek       3분 만에 ask 로 올려 답을 받고 진행. 11분31초 완주
    laguna-s       같은 모순을 인지하고 escalation 을 결정했다가 매번
                   재검토로 되돌아감. 32분간 379KB 출력에 도구 호출 0건

**정답을 아는 것과 막혔을 때 빠져나오는 것은 다른 능력이고, 후자는 읽기 전용
과제에서 드러나지 않는다.** 쓰기 워커를 고를 때는 이쪽을 봐야 한다.

### 17.3 짧은 입력에 답하는 것은 워커로 쓸 수 있다는 뜻이 아니다

`opencode/nemotron-3.5-lightning-free` 는 `MODEL_POOL` 에 등록되어 배정을 받고
있었는데, 4.8KB Capsule 을 주자 다국어 토큰이 무작위로 섞인 무의미 출력을 냈다.
`OK 만 답하라`, `2+2` 에는 정상 응답한다.

`probe_model()` 은 `ping` 한 마디를 보내고 종료 코드 0 이면 통과시킨다. **이
유형은 probe 를 100% 통과한다.** 가용성 확인과 적합성 확인을 같은 것으로 다루지
말 것.

### 17.4 등록 목록이 후보 목록은 아니다

같은 OpenCode 무료 풀 여섯 중 셋만 쓰기 과제를 완주했다. 그런데 등록되어 있던
둘 중 하나가 못 쓰는 쪽이었고, **통과한 셋 중 둘은 등록조차 되어 있지 않았다.**
경합 범위를 "이미 등록된 것" 으로 잡으면 더 나은 후보를 못 본 채 순위를 매긴다.
사용자 지적으로 범위를 넓혀 mimo-v2.5 와 nemotron-3-ultra 를 찾았다.

### 17.5 시간은 채점 항목이어야 한다

첫 Capsule 의 acceptance 에는 시간 제한이 없었다. 그래서 32분째 진행 중인
워커를 "결과가 나올 때까지" 기다렸다. 통과 5종이 11~14분에 몰려 있었으므로
그때 이미 배정 가치가 없었다.

**실격선을 미리 정하고 사양에 적을 것.** 이번에는 최장 통과의 2배(28분)로
잡았다. 결과가 맞아도 2.3배 걸리는 워커는 배정할 이유가 없다. 같은 시간에
다른 모델로 두 건을 끝낼 수 있다.

### 17.6 채점기가 틀리면 멀쩡한 산출물이 실격된다

구현 내부에 의존하지 않는 중립 시나리오로 5종을 채점했는데, 판정 줄을 찾지
않고 출력 전체에서 `"소멸"` 문자열을 검색했다. 안내문에 들어 있던
"3회 연속 이탈이 확인될 때만 소멸 판정합니다" 가 걸려 **두 모델이 4/8 로
나왔다.** 고치니 5종 전부 8/8 이었다.

이번 세션에서 워커 결함보다 코디네이터 측정 도구의 결함이 더 많았다.
만족 불가능한 acceptance, 러너의 무차별 `pkill -f kimi-code`(다른 워커까지
죽인다), 그리고 이 채점기까지 셋이다. **낮은 점수가 나오면 대상을 의심하기
전에 측정기를 먼저 의심할 것.**

### 17.7 워크트리 하나당 터미널 하나가 강제로 생긴다

`orca worktree create` 는 터미널 생성을 끄는 옵션이 없다. 워커를 배경
프로세스로 돌리는 경로(Kimi `-p`, `opencode run`)에서는 그 창을 쓰지 않으므로
**만든 직후 `orca terminal close` 로 닫는다.** pty 만 죽고 워크트리·커밋·브랜치는
남는다. 경합 규모를 늘리면 그만큼 목록에 쌓이므로 늘리기 전에 이 비용을
사용자에게 먼저 알릴 것.

### 17.8 잰 역할만 부여한다 (2026-08-20 GPT 감사)

builder 과제 하나를 통과시킨 모델에 `benchmarker` 와 `documenter` 까지 함께
부여했다. **측정한 적이 없는 역할이다.** `investigator` 는 코드를 정확히 읽어야
쓰기 과제를 완주할 수 있으므로 포섭되지만, 측정을 설계하는 능력과 문서를 쓰는
능력은 포섭되지 않는다.

기존 관행을 따른 것이 이유였다. `opencode-deepseek` 과 `cursor-auto` 가 이미
넷을 갖고 있어 같은 모양으로 맞췄는데, **그 둘의 부여도 근거가 없었다.**
특히 `cursor-auto` 는 5회 중 3회 빈 출력 기록을 가진 채 `builder` 를 들고
`FREE_POOL_ORDER` 에 있었다. 무료 풀 전체에서 회수하고, 테스트로 불변식을
걸었다(무료 풀 항목은 `{investigator, builder}` 밖의 역할을 가질 수 없다).

**옆 항목이 그렇게 되어 있다는 것은 근거가 아니다.**

### 17.9 n=1 결과를 순위로 쓰지 않는다 (2026-08-20 GPT 감사)

통과 5종이 전부 8/8 이라 소요 시간으로 나열하고 `FREE_POOL_ORDER` 를
"능력 근거로 정렬했다" 고 커밋 메시지에 적었다. **스택당 1회 실행이다.**
무료 엔드포인트는 큐, 콜드스타트, 429, provider routing 으로 편차가 커서
9분과 11분의 차이를 능력 차이로 읽을 수 없다.

순위를 확정하려면 서로 다른 과제 여러 종을 스택당 최소 3회 반복해 median 과
p95, 성공률, 무응답률로 재야 한다. 그 전까지는 **동등 합격군**이다.

같은 이유로 실격 판정도 격리(quarantine)로 바꿨다. `north-mini` 는 사후에
정한 실격선을 넘었을 뿐이고, `laguna-s` 는 1회 관측이며 그 회차의 Capsule 에
코디네이터가 만든 모순이 섞여 있었다.

### 17.10 측정 단위는 모델이 아니라 워커 스택이다 (2026-08-20 GPT 감사)

`kimi -p` 는 one-shot 이고 `opencode run` 은 대화 경로가 있다. 그래서 사양
모순이 드러났을 때 deepseek 은 코디네이터 회신을 받았고 Kimi 쪽 워커들은
받지 못했다. **같은 프롬프트를 줬다고 같은 실행 환경이 아니다.**

기록 단위는 `모델 + 제공자 + CLI 하네스` 조합으로 적는다. 같은 모델이라도
`or-free/nemotron-ultra`(Kimi)와 `opencode/nemotron-3-ultra-free`(OpenCode)는
다른 스택이다.

### 17.11 측정 장치를 저장소 밖에 두지 않는다 (2026-08-20 GPT 감사)

1회차의 Capsule 은 `.orca/`(gitignore), 채점기와 러너와 로그는 세션
scratchpad 에 있었다. **세션이 끝나면 전부 사라지고 "8/8, 9분01초" 라는 숫자만
남는다.** 다음 사람이 같은 시험을 재현할 수 없다.

`benchmarks/free_workers/` 로 옮겼다. Capsule, 채점기, 러너, 로그 꼬리,
회차별 결과 JSON 이 함께 있고, 결과 JSON 에는 값뿐 아니라 **그 회차의 한계**를
`limitations` 로 적는다. 채점기는 인자 없이 부르면 저장소 구현을 자체 시험한다.

### 17.12 2차 경합이 1차 순위를 뒤집었다 (2026-08-20)

같은 5스택에 소형 builder 과제를 3회씩 물렸다. 실격선(720초)과 채점기를 실행
전에 동결하고 라운드로빈으로 돌렸다. 성공은 **시한 내 종료 AND 커밋 1건 이상
AND 채점 만점** 셋을 모두 만족한 회차다.

    opencode-deepseek         3/3  median 253s  p95 279s
    or-free-laguna-xs         3/3  median 458s  p95 507s
    opencode-mimo             2/3  median 456s  p95 506s
    or-free-nemotron-ultra    2/3  median 586s  p95 610s
    opencode-nemotron3-ultra  1/3  median 594s  p95 594s

**1차 1위가 최하위가 됐다.** `opencode-nemotron3-ultra` 는 매 회차 `audit()` 의
반환값을 2-튜플에서 3-튜플로 바꿔 기존 테스트 10건을 깨뜨리고, 그걸 복구하느라
3회 중 2회가 시한을 넘겼다. 1차 3위였던 `opencode-deepseek` 은 기존 시그니처를
건드리지 않아 median 이 다른 스택의 절반이다.

**속도 차이가 처리 속도가 아니라 설계 판단에서 나왔다.** 그리고 그 판단은
회차마다 재현됐다. n=1 에서는 이것이 우연한 빠름으로 보였다.

실패 유형도 1차와 달랐다. `mimo` 는 1회차에서 구현 대신 계획서를 쓰고
"승인해 주시면 구현을 시작하겠습니다" 로 67초 만에 끝냈다. 단발 프롬프트를
대화형 세션으로 착각한 것이다. 과제가 작아지자 나타난 유형이다.

### 17.13 코드가 맞아도 성공이 아니다 (2026-08-20)

채점만 보면 15회 중 13회가 만점이다. 그런데 그중 둘은 시한을 넘겨 종료된
회차였다. 산출물이 워크트리에 남아 있어 채점기는 통과시켰지만, **커밋이 없으면
다음 단계가 이어받을 수 없다.**

성공 조건에 종료 코드와 커밋 수를 함께 넣었다. 채점 점수만으로 워커를 고르면
"옳은 코드를 시한 밖에 내놓는" 스택이 상위에 올라온다.

### 17.14 하나의 순서를 모든 역할에 쓰면 builder 실측이 investigator 배정을 바꾼다 (2026-08-20 GPT 2차 감사)

`select_model()` 이 `FREE_POOL_ORDER` 하나를 모든 역할에 썼다. builder 과제로
잰 순서를 반영하자 **investigator 배정 순서까지 함께 바뀌었다.** 벤치마크
README 에 "과제 1종으로 전역 순위를 만들지 않는다" 고 적어 놓고 라우터에서는
그대로 전역 순위로 썼다.

`FREE_ORDER_BY_ROLE` 로 갈랐다. builder 는 실측 순서, investigator 는 아직
측정하지 않았음을 코드에 명시하고 builder 순서를 임시로 물려 쓴다.

**쓰기 능력이 조사 능력을 포섭한다고 보지 말 것.** 조사는 큰 코드베이스 탐색,
원인 후보 생성과 반증, 근거 수집, 허위 지적 억제를 요구한다. 코딩을 잘하면서
없는 결함을 만들어내는 성향이 강할 수 있다.

### 17.15 성공 회차만으로 낸 p95 는 실패한 스택을 좋아 보이게 한다 (2026-08-20 GPT 2차 감사)

`oc_nemo3ultra` 는 3회 중 2회가 720초 시한 초과인데, 성공한 1회만으로 p95 를
내니 **594초로 나왔다.** 성공률과 함께 보지 않으면 상위 스택과 비슷해 보인다.

이름을 `median_success_sec`, `p95_success_sec` 로 바꿔 범위를 드러내고, 시한
초과를 절단 관측으로 포함한 `p95_all_sec` 를 따로 뒀다. 같은 스택이 720초가 된다.

같은 집계기에 결함이 둘 더 있었다. 0 이 아닌 종료 코드를 전부 `timeout` 으로
분류해 모델 없음·CLI 오류·강제 종료를 구분하지 못했고(124 만 시한 초과다),
만점을 6 으로 하드코딩해 다른 문항 수의 벤치마크에 재사용할 수 없었다.
채점 결과 문자열에서 분모를 읽도록 고쳤다.

### 17.16 실제로 돌린 러너를 남기지 않으면 재현이 안 된다 (2026-08-20 GPT 2차 감사)

1차 지적을 받아 벤치마크를 저장소로 옮길 때 Capsule, 채점기, 집계기, 결과
JSON 은 넣었는데 **2차를 실제로 돌린 러너를 빠뜨렸다.** 저장소에 있던
`runner.sh` 는 1차용이었고 1차 스택 이름과 로컬 scratchpad 경로가 박혀 있었다.

과제별로 `builder_0N/run.sh` 를 두고 저장소 밖 경로는 환경변수로 뺐다.
**"측정 장치를 버전 관리한다" 는 결과물만이 아니라 실행 경로까지다.**

### 17.17 시한 초과를 기록만 하고 프로세스를 죽이지 않으면 다음 회차가 오염된다 (2026-08-20 GPT 3차 감사)

2차 경합 러너는 720초가 지나면 `.exit` 파일에 `124` 를 적고 슬롯을 비웠지만
**워커 프로세스와 터미널을 종료하지 않았다.** 그래서 다음 회차가 같은
워크트리에 `git reset --hard` 를 걸고 시작하는 동안 앞 회차 워커가 계속
파일을 쓰고 커밋했다.

    oc_nemo3ultra_r1  124 720  커밋 0
    oc_nemo3ultra_r2  124 720  커밋 2   <- 잔류 프로세스가 함께 커밋
    oc_nemo3ultra_r3  0   594  커밋 2
    다른 스택 11 회             전부 커밋 1

**커밋 수가 오염의 지표였다.** 이 스택의 2차 결과와 최하위 판정은 신뢰할 수
없다. 시한 초과가 없었던 deepseek 과 laguna_xs 의 3/3 은 영향받지 않는다.

반복 실험에서 회차 독립성은 프로세스 종료로 보장해야 한다. 순서는
**해당 워커만 종료 -> 종료 확인 -> 산출물 수집 -> 슬롯 반납 -> 다음 회차 허용**
이다. 이름으로 죽이면(`pkill -f kimi`) 다른 스택까지 죽는다(17.6 참조).
`orca terminal create` 가 돌려주는 핸들을 보관해 그 창만 닫아야 한다.

### 17.18 역할별로 갈랐다고 적고 같은 객체를 넣으면 갈린 것이 아니다 (2026-08-20 GPT 3차 감사)

`FREE_ORDER_BY_ROLE` 를 만들면서 `builder` 와 `investigator` 에 **같은
`FREE_BUILDER_ORDER` 객체**를 넣었다. 구조만 생겼고 동작은 그대로다.
"investigator 는 아직 측정하지 않았다" 고 주석에 적고 바로 다음 줄에서 builder
순서를 넣었으므로, builder 실측이 investigator 배정을 바꾸는 문제는 남아 있다.

테스트도 investigator 기대값을 builder 순서로 고정해 **그 결합을 정답으로
박아 놓았다.** 별도 목록으로 분리하고, 두 순서를 다르게 둔 상태에서 역할별로
다른 모델이 선택되는지 검증하는 테스트가 필요하다.

---

## 18. 워커 기동과 검증 경로에서 조용히 어긋나는 것들 (2026-08-21)

17 장의 P0 두 건을 고치는 과정에서 새로 드러난 함정이다. 넷 다 실패를
보고하지 않고 **성공한 것처럼 보이는 상태**로 진행된다는 공통점이 있다.

### 18.1 OpenCode TUI 는 `-m` 이 실패해도 다른 모델로 뜬다

`opencode -m opencode/deepseek-v4-flash-free --auto` 로 워커를 띄웠는데
화면에 GLM-4.7 Flash (Z.AI Coding Plan) 가 떴다. 그 모델이 그날
`Model not found` 였고, TUI 는 오류를 내지 않고 **기본 프로바이더로 조용히
떨어졌다.** 사용자가 화면을 보고 지적하지 않았다면 이 저장소가 한 번도
적합성을 측정한 적 없는 스택에 쓰기 과제가 배정된 채로 진행됐다.

**기동 직후 화면에서 모델명을 확인하기 전에는 Dispatch 하지 않는다.**

```bash
orca terminal read --terminal <handle> --json | ...  # "Build ... · <모델명>" 확인
```

`opencode models` 목록과 TUI 선택 목록도 서로 다르다. 목록에 없어도 `-m`
으로 호출되는 경우가 있다(`mimo-v2.5-free`). 목록 부재는 판정 근거가 아니다.

### 18.2 고지문의 주 저장소 절대 경로가 워커를 주 저장소로 끌어온다

`orca_taskctl dispatch` 는 Capsule 과 `worker_done.json` 경로를 주 저장소
절대 경로로 넣는다. 워커가 그 경로를 자기 작업 공간으로 인식해, 격리
워크트리를 두고 **주 저장소에서 브랜치를 파고 커밋했다.** `main` 은 무사했으나
주 저장소의 체크아웃이 그 브랜치로 넘어가 있었다.

Capsule 사본을 워크트리에 두고 그 안의 절대 경로를 상대 경로로 바꾼 것만으로는
부족하다. **Dispatch 직후 워커의 커밋이 어느 저장소에 생기는지 확인한다.**

```bash
git -C <주 저장소> branch --show-current   # main 이어야 한다
git -C <워크트리> log --oneline main..HEAD
```

### 18.3 테스트에 저장소 절대 경로를 박으면 워크트리 검증이 무의미해진다

18.2 의 부작용으로, 워커가 만든 테스트가 `subprocess` 의 `cwd` 에 주 저장소
절대 경로를 하드코딩했다. 그 결과 격리 워크트리에서 돌려도 **주 저장소의 옛
코드가 실행됐다.** 워크트리의 수정본은 한 번도 검증되지 않았고, 실패 양상이
기능 미구현과 구분되지 않아 산출물 전체를 폐기할 뻔했다.

경로는 `Path(__file__).resolve().parents[N]` 으로 유도한다. 브랜치별 검증이
성립하려면 테스트가 자기 트리를 봐야 한다.

### 18.4 자동 생성 경고문에 사례 세부를 박지 않는다

집계기가 오염 경고를 자동 생성하면서 스택 이름만 치환하고 `r1/r2 가 시한을
넘겼다`, `r2/r3 가 2다` 는 특정 사례의 사실을 고정해 두었다. 다른 스택이
오염되면 **사실과 다른 경고가 생성된다.** 경고문이 거짓을 주장하면 경고가
없느니만 못하다. 문구는 실제 회차 데이터에서 유도한다.

### 18.5 Orca CLI 서브커맨드에는 `--help` 가 통하지 않는다

`orca orchestration dispatch --help` 는 `Unknown command` 로 떨어진다.
13 번이 지시하는 "값 유무는 `--help` Usage 로 본다" 가 이 버전에서는 성립하지
않는다. 서명은 `orca agent-context --json` 으로 확인한다.

같은 이유로 저장소 도구의 인자 형식도 직접 확인해야 한다.
`scripts/orca_level1_gate.py --tests` 는 **pytest 인자만** 받는다.
`uv run pytest ...` 전체를 넘기면 `file or directory not found: uv` 로
게이트 3 이 실패하는데, 이것이 테스트 실패처럼 보인다.

---

## 19. 무료 스택 순위는 하루 만에 뒤집힌다 (2026-08-21 3차 재측정)

2 차 경합의 `oc_nemo3ultra` 오염분을 러너를 고친 뒤 다시 쟀다. 같은 base
ref(`8b0b400`), 같은 Capsule, 같은 동시 3 대 조건을 맞추려고 `mimo` 와
`laguna_xs` 를 함께 투입했다. 재측정에서 나온 것은 오염 해소만이 아니었다.

### 19.1 같은 스택이 3/3 에서 0/3 으로 뒤집혔다

`or-free/laguna-xs` 는 2 차에서 429·512·458 초로 3 회 전부 완주해 무료 풀
2 순위였다. 하루 뒤 같은 조건에서 3 회 전부 720 초 시한을 넘겨 0/3 이 됐다.

**능력이 떨어진 것이 아니다.** 3 회 중 2 회(r1, r3)는 채점 **6/6 만점** 코드를
만들어 놓고 시한 안에 커밋에 도달하지 못했다. 코드는 옳았고 속도만 느렸다.
무료 엔드포인트의 응답 지연이다.

그러므로 **n=3 으로 매긴 스택 간 순위는 재현되지 않는다.** 17 장이 "n=1 로
매긴 순서는 재현되지 않는다" 로 끝났는데, 3 회로 늘려도 같은 결론이다.
실측으로 말할 수 있는 것은 **n=3 수준에서 순위가 재현되지 않는다** 는
것까지다. 얼마나 늘리면 수렴하는지는 재 본 적이 없으므로 "아무리 늘려도
수렴하지 않는다" 고 적지 말 것. 다만 그 비용을 들여도 얻는 것은 측정한 날의
순위이므로 판단은 같다.

측정을 더 하지 말고 **상시 관측**으로 갈음한다. 종료 기준과 재실행 트리거
3 개는 `benchmarks/free_workers/README.md` 6 장에 적었다.

### 19.2 "커밋 없음" 과 "일하지 않음" 은 다른 실패다

같은 회차 표에서 실패가 둘 다 커밋 0 건으로 보이지만 원인이 정반대다.

| 회차 | 종료 | 소요 | 채점 | 실제 원인 |
| --- | --- | ---: | --- | --- |
| `laguna_xs_r1` | 124 | 720s | **6/6** | 다 만들고 커밋만 못 함. 지연 |
| `oc_nemo3ultra_r1` | 0 | 183s | **0/6** | 파일 3 개 읽고 종료. 미착수 |

`results.tsv` 의 커밋 수만 보면 둘 다 실패로 같아 보인다. **채점 점수를 같이
보지 않으면 조치를 정반대로 고른다.** 전자는 시한을 늘리거나 순위를 낮추면
되고 풀에 남긴다. 후자는 시한을 늘려도 해결되지 않는다. 17 장의 `hy3-free`
와 같은 유형이다.

### 19.3 배정 순서는 속도가 아니라 최근 실패율로 매긴다

`FREE_BUILDER_ORDER` 를 속도로 줄 세우면 다음 측정에서 또 뒤집힌다. 지연으로
실패하는 스택을 앞에 두면 회차마다 시한을 통째로 버리므로, 순서는 **가장
최근에 관측된 실패율** 기준으로 둔다.

`opencode-deepseek` 은 순서를 손대지 않는다. `apply_inventory_history()` 가
실재 관측 이력으로 자동 강등·제외하므로 순서까지 건드리면 이중 처리가 된다.

`FREE_INVESTIGATOR_ORDER` 는 builder 재정렬을 따라가지 않는다. 조사 능력은
쓰기 능력에 포섭되지 않으므로 builder 실측을 investigator 재배열 근거로 쓸 수
없다. 2026-08-21 부터 두 순서는 값도 실제로 갈라졌다.

### 19.4 일부만 재측정할 때 혼자 돌리면 비교가 깨진다

`BENCH_STACKS` 로 스택을 좁힐 수 있지만, 혼자 돌리면 백엔드 경합이 사라진다.
실패 모드가 시한 초과인 스택에서는 조건 완화가 **성공 쪽으로 편향**되므로,
그 값을 나머지 회차와 나란히 놓으면 안 된다. 원래와 같은 수의 스택을 동시에
투입해 경합 조건을 유지한다.

### 19.5 집계기 메타데이터에 기본값을 두면 조용히 거짓을 기록한다

`aggregate.py` 는 `date`, `timeout_sec`, `concurrency` 를 하드코딩하고 있었다.
조건을 바꿔 다시 돌려도 결과 JSON 은 이전 조건을 그대로 적는다. 오류가 나지
않으므로 **읽는 사람이 알 방법이 없다.** 실행 조건은 기본값 없는 필수 인자로
받는다.

### 19.6 채점기는 저장소 루트가 `sys.path` 에 있어야 한다

후보 모듈이 `from scripts.orca_model_router import MODEL_POOL` 를 하므로,
`uv run python benchmarks/.../scoring_02.py` 로 실행하면 `sys.path[0]` 이
스크립트 디렉터리라 후보 전원이 `ModuleNotFoundError` 로 채점 불가가 된다.
산출물 결함으로 오해하기 쉽다. `PYTHONPATH` 를 저장소 루트로 지정한다.

### 19.7 모델 이름이 같아도 경로가 다르면 다른 스택이다

`muse-spark-1.2` 를 opencode 무료 경로에서 지역 차단으로 못 쓴 것이,
OpenRouter 경로에 대해 말해주는 바는 없다. 문서에 모델 이름 기준으로
`사용 불가` 만 적어두면 "강해 보이는데 왜 뺐는가" 를 반복해 묻게 된다.
경로별로 상태와 근거를 갈라 적는다. 판정은
`docs/ops/agent_worker_launch_reference.md` 1.4.1 절에 있다.

---

## 20. 워커에게 준 절대 경로가 워커를 주 저장소로 데려간다 (2026-08-23)

하루에 **워커 4대**가 격리 작업 트리를 벗어나 주 저장소에서 일했습니다. 모델도
CLI 도 서로 달랐습니다. Antigravity `claude-sonnet-4-6`, Kimi
`or-free/nemotron-ultra`, OpenCode `nemotron-3-ultra-free`,
`mimo-v2.5-free` 가 모두 같은 행동을 했습니다. **워커 품질 문제가 아니라
코디네이터의 지시 설계 결함입니다.**

### 20.1 무엇이 일어났는가

`scripts/orca_taskctl.py` 의 `build_task_spec` 과 `build_capsule_notice` 가
Capsule 경로를 **주 저장소 절대 경로**로 넣었습니다.

```text
정본 사양(Capsule): /Users/kwanbum/Documents/.../refac_bid_box/.orca/capsules/<task>/capsule.yaml
```

워커는 지시문에서 이 경로를 가장 먼저 읽고, 그 파일이 있는 저장소를 작업
대상으로 이해해 `cd` 합니다. 격리 워크트리에 Capsule 을 복사해 두어도 소용이
없습니다. 지시문이 다른 곳을 가리키기 때문입니다.

### 20.2 어디까지 번졌는가

| 단계 | 결과 |
| --- | --- |
| 워커가 주 저장소로 이동 | 주 저장소 작업 트리가 워커 산출물로 더러워짐 |
| 워커가 거기서 `git checkout -b` | 코디네이터의 `main` 이 워커 브랜치로 바뀜 |
| 코디네이터가 그 상태로 병합 실행 | 병합 2건이 `main` 이 아니라 워커 브랜치 위에 쌓임 |
| 코디네이터가 그 브랜치를 `-D` 로 삭제 | 병합 2건이 브랜치 포인터를 잃음 |
| 커밋 해시로 fast-forward | 복구 성공. 데이터 손실은 없었음 |

**한 번의 경로 실수가 병합 소실 직전까지 갔습니다.**

### 20.3 규칙

1. **워커에게 주는 모든 경로는 워크트리 상대 경로입니다.** Capsule 정본 경로,
   보고 JSON 경로, 읽기 대상 경로 전부입니다. 절대 경로는 워커를 그 저장소로
   데려갑니다.
2. **지시문에 작업 트리 경계를 명시합니다.** "현재 작업 디렉터리가 당신의 격리
   작업 트리이며 벗어나면 계약 위반" 을 고지문에 넣습니다.
3. **`git merge` 직전마다 `git branch --show-current` 를 확인합니다.** 워커를
   격리 트리에 붙였다는 사실은 주 저장소가 안전하다는 보장이 아닙니다.
4. **브랜치를 지우기 전에 `git log --oneline main..<branch>` 결과를 읽습니다.**
   출력만 하고 넘어가면 지우는 순간 알 수 없습니다. 이번에 실제로 출력해 놓고
   읽지 않았습니다.
5. **워커 화면에서 `cd` 나 `git checkout -b` 를 보면 즉시 끊고 재지시합니다.**
   대화형 CLI 는 `esc` 후 워크트리 절대경로와 파일 경로를 다시 주면 대체로
   따릅니다. Kimi `-p` 는 단발이라 개입할 수 없으므로, 자족적 Task 에만 주고
   산출물은 코디네이터가 회수합니다.

### 20.4 기계 강제

규칙만으로는 반복됩니다. 실제로 2026-08-23 오후에 이 함정을 겪고 메모리에
적어둔 뒤, **같은 날 저녁 다음 라운드에서 그대로 재발했습니다.**

`scripts/orca_taskctl.py` 에 `worktree_relative_capsule_path()` 를 두고
`build_task_spec` 과 `build_capsule_notice` 가 반드시 이를 통과하도록 했습니다.
`.orca` 이후 경로만 남기며, `.orca` 가 없으면 파일명만 남겨 절대 경로 유출을
막습니다. 회귀 테스트는
`tests/test_orca_taskctl.py::test_capsule_paths_never_leak_main_repo_absolute_path`
입니다. 두 진입점 중 하나라도 절대 경로를 흘리면 실패합니다.

### 20.5 남은 경로

`allowed_read_files` 와 `report_path` 는 Intent 작성자가 직접 씁니다. 여기에
절대 경로를 쓰면 같은 일이 재발합니다. Intent 를 쓸 때 경로는 항상 저장소
루트 기준 상대 경로로 적으십시오 (AGENTS.md 3장 3호).

---

## 21. 워커 3대가 동시에 없는 Capsule 을 열었다 (2026-08-25)

### 21.1 증상

`orca_taskctl.py create` 로 만든 Task 3건을 각각 다른 CLI 워커에 Dispatch 하자
세 워커가 모두 존재하지 않는 파일을 열었습니다. Gemini 워커의 터미널에는
다음이 남았습니다.

    === TASK ===
    ... 정본 사양(Capsule): 현재 작업 디렉터리의
    .orca/capsules/task_rag_intent_routing_fix/capsule.yaml

실제 Capsule 은 `.orca/capsules/task_76587799510f/capsule.yaml` 이었습니다.
워커는 파일을 찾지 못하자 워크트리 전체를 glob 으로 뒤졌습니다. 이번에는
워크트리에 Capsule 이 한 벌뿐이라 우연히 찾아냈지만, 여러 벌이 있었으면
남의 Task 사양을 읽었을 것입니다.

### 21.2 원인

**Orca 의 Task ID 는 서버가 발급하고, `spec` 은 생성 후 변경할 수 없습니다.**

`orca orchestration task-update` 는 `--status` 만 받습니다. `--spec` 이
없으므로 한 번 만든 Task 의 본문은 고칠 수 없습니다.

`cmd_create` 는 이 두 사실과 어긋나게 동작했습니다.

| 순서 | 하던 일 |
| --- | --- |
| 1 | Intent 파일명으로 잠정 ID(`task_<stem>`)를 만들어 그 경로에 Capsule 을 쓴다 |
| 2 | 그 잠정 경로를 담아 `spec` 을 만들고 `task-create` 를 호출한다 |
| 3 | Orca 가 실제 ID(`task_76587799510f`)를 돌려준다 |
| 4 | Capsule 을 실제 ID 디렉터리로 옮기고 **잠정 경로를 지운다** |
| 5 | `final_spec` 을 새로 만들지만 **어디에도 반영하지 않는다** |

4단계에서 지우는 파일이 2단계에서 Orca 에 박아 넣은 경로입니다. `dispatch
--inject` 가 워커에게 전달하는 본문은 오직 이 `spec` 이므로, 워커는 항상 지워진
경로를 받습니다.

**회귀 테스트가 결함을 불변식으로 고정하고 있었습니다.**
`test_cmd_create_syncs_actual_task_id_to_capsule_and_spec` 에
`assert not provisional_dir.exists()` 가 있었습니다. 정리라고 이름 붙은
동작이 실제로는 워커 지시를 깨뜨리는 동작이었고, 테스트는 그것을 지켰습니다.

### 21.3 조치

`cmd_create` 는 이제 잠정 경로의 Capsule 을 지우지 않고 실제 ID 경로와 **같은
내용으로 함께 유지**합니다. `spec` 이 가리키는 곳과 도구가 `task_id` 로 찾는
곳이 둘 다 성립합니다. `--json` 출력에 `spec_capsule` 과
`spec_capsule_relative` 를 추가했고, 사람이 읽는 경로에서는 두 경로를 함께
출력하며 stderr 로 워크트리 복사 안내를 냅니다.

**워크트리에는 `.orca/capsules/` 를 통째로 복사하십시오.** Task 하나에 대응하는
디렉터리 하나만 복사하면 `spec` 이 가리키는 쪽이 빠집니다.

```bash
cp -R <주 저장소>/.orca/capsules <워크트리>/.orca/
```

테스트는 반대 방향으로 다시 썼습니다. 잠정 경로의 Capsule 이 남아 있고 실제
경로와 내용이 같으며 `spec` 이 잠정 ID 를 담고 있어야 통과합니다.

### 21.4 `create` 와 `dispatch` 는 Task ID 로 이어지지 않습니다

같은 뿌리에서 나온 두 번째 결함입니다. `cmd_dispatch` 도 `--task-id` 가 없으면
Intent 파일명으로 ID 를 유추하는데, `create` 가 만든 Task 는 Orca 발급 ID 를
가지므로 다음이 반드시 실패합니다.

```bash
python3 scripts/orca_taskctl.py create   --intent <intent>   # task_76587799510f 생성
python3 scripts/orca_taskctl.py dispatch --intent <intent>   # task_<stem> 을 찾다가 실패
#   -> 오류: 워커 기동 실패 (종료 코드 1): Task not found: task_rag_intent_routing_fix
```

`Task not found` 는 Task 가 사라졌다는 뜻이 아니라 **ID 를 유추한 것이 틀렸다는
뜻입니다.** `create` 의 출력에서 `task_id` 와 `capsule` 을 받아
`--task-id`, `--capsule` 로 넘겨야 이어집니다. 오류 메시지에 이 안내를
넣었습니다.

### 21.5 CLI 자체가 죽어 있으면 Dispatch 오류가 모델 문제처럼 보입니다

같은 세션에서 OpenCode 워커가 다음으로 실패했습니다.

    Cannot dispatch --inject to terminal <handle>:
    no recognized agent detected.

원인은 모델도 터미널도 아니고 CLI 설치였습니다.

    Error: opencode-ai's postinstall script was not run.

`terminal create --command "opencode"` 는 명령이 즉시 죽어도 터미널을 만들고
셸 프롬프트를 남깁니다. Orca 는 에이전트를 찾지 못했다고만 말하므로 원인이
가려집니다. 조치는 1.3 절과 같습니다.

```bash
cd /opt/homebrew/lib/node_modules/opencode-ai && node postinstall.mjs
opencode --version    # 판이 나와야 정상
```

**터미널을 만든 직후 `orca terminal read` 로 CLI 가 실제로 떴는지 한 번
보십시오.** Dispatch 를 먼저 하면 오류 문구가 원인을 가립니다.

### 21.6 모델 ID 는 라우터 등록값이 아니라 CLI 목록이 정본입니다

`scripts/orca_model_router.py list` 는 OpenCode DeepSeek 을
`opencode/deepseek-v4-flash-free` 로 등록하고 있으나, 2026-08-25
`opencode models` 의 실제 ID 는 `opencode-go/deepseek-v4-flash` 입니다.
등록값으로 기동하면 모델을 찾지 못합니다.

**기동 전에 `opencode run -m <id> "reply with OK only"` 로 1회 호출해
응답을 확인하십시오.** 목록에 보이는 것과 호출되는 것은 다릅니다 (1.3 절).

### 21.7 완료 선언은 커밋이 아니고, 정체 감시는 종료를 잡지 못합니다

같은 세션에서 Kimi 워커가 터미널에 완료 요약을 출력하고 세션을 끝냈습니다.
요약에는 수정 항목 6건과 "전체 테스트 2022 passed" 까지 적혀 있었습니다.
실제로는 **커밋이 0건이었고 변경 6건이 전부 미커밋** 이었으며 `worker_done`
도 오지 않았습니다.

**세 가지가 겹쳐서 발견이 늦었습니다.**

| 겹친 것 | 내용 |
| --- | --- |
| 워커 계약 | 계약(4.1)은 `commit_count: 0` 이면 `succeeded` 대신 `escalation` 을 보내라고 하지만, 워커가 `worker_done` 자체를 안 보내면 이 검사가 돌지 않습니다 |
| 감시 설계 | 감시가 **커밋 발생** 과 **정체** 만 봤습니다. 세션이 끝나 더 이상 아무 일도 일어나지 않는 상태는 정체와 구분되지 않아, 10분 타이머가 만료될 때까지 알림이 없습니다 |
| one-shot CLI | `kimi -p` 는 one-shot 이라 완료 선언 뒤 프로세스가 사라집니다. `orca orchestration send` 는 워커가 `check` 를 해야 도착하므로(9장) 지시가 닿지 않습니다 |

**완료 선언을 커밋의 근거로 쓰지 마십시오.** 터미널에 요약이 뜬 그 시점에
저장소 상태를 직접 보십시오. 이 한 줄이면 됩니다.

```bash
git -C <워크트리> log --oneline main..HEAD | wc -l
```

0 이면 병합할 대상이 없습니다. 보고 내용이 아무리 상세해도 완료가 아닙니다.

**감시는 정체가 아니라 종료를 잡아야 합니다.** one-shot CLI 를 붙였으면
"세션이 살아 있는가" 를 함께 봅니다. 정체 타이머만으로 잡으면 그 타이머만큼
시간을 버립니다.

```bash
# 워커 프로세스가 사라졌는데 커밋이 0 이면 즉시 알린다
while :; do
  sleep 45
  c=$(git -C "$WT" log --oneline main..HEAD | wc -l | tr -d ' ')
  [ "$c" -gt 0 ] && { echo "COMMITTED"; exit 0; }
  if ! pgrep -f "$WORKER_PATTERN" >/dev/null; then
    echo "WORKER_EXITED_WITHOUT_COMMIT"; git -C "$WT" status --short; exit 2
  fi
done
```

**복구는 세션 재개입니다.** `kimi` 는 종료 시 재개 명령을 출력합니다.
그 핸들로 터미널에서 직접 다시 띄우고 커밋만 시키십시오.

```bash
KIMI_CODE_HOME=~/.kimi-openrouter-bakeoff kimi -r <session_id> -p "<커밋 지시>"
```

**Capsule 에 커밋을 명시적 acceptance 로 넣으십시오.** 이번 Capsule 은 검증
명령은 요구했지만 커밋을 acceptance 항목으로 적지 않았습니다. 워커는 요구한
것만 합니다.

    acceptance:
      - 변경을 작업 브랜치에 커밋했고 git log --oneline main..HEAD 가 1건 이상이다.

### 21.8 죽은 감시는 감시가 아닙니다

같은 세션에서 배경 감시 스크립트가 첫 줄에서 죽었습니다.

    declare: -A: invalid option

macOS 기본 셸은 bash 3.2 라 **연상 배열(`declare -A`)을 지원하지 않습니다.**
스크립트는 즉시 종료했고, 코디네이터는 그 사실을 모른 채 사용자에게 감시를
붙였다고 보고했습니다.

| 하지 말 것 | 대신 |
| --- | --- |
| 배경 실행 직후 "감시 중" 이라고 보고 | `ps -ef \| grep [w]atch` 로 프로세스 생존을 확인한 뒤 보고 |
| bash 4 문법 사용 | `bash -n` 으로 문법 검사, 상태는 연상 배열 대신 변수나 파일로 |

**시작했다는 것과 돌고 있다는 것은 다릅니다.** 감시는 실패해도 조용하므로,
확인하지 않으면 없는 감시를 있다고 믿게 됩니다.

### 21.9 로컬 green 은 CI green 이 아닙니다

2026-08-25 세션에서 워커 산출물 3건을 Level 1 게이트와 로컬 전체 테스트 통과만
보고 병합했습니다. **원격 CI 는 그 시점에 이미 빨간불이었습니다.** 세션 시작
커밋 `3e9d014` 의 run `32727481204` 은 `lint-and-validate` 와 3플랫폼 테스트가
모두 실패한 상태였고, 병합 판정에는 이 사실이 전혀 반영되지 않았습니다.

원인은 두 가지였고 **둘 다 로컬에서는 재현되지 않습니다.**

| 실패 | 기전 |
| --- | --- |
| 문서 링크 33건 | `validate_doc_links.py` 가 절대 경로를 **작성자 머신에 존재하면 통과**시켰습니다. `/Users/kwanbum/orca/...` 와 `file:///Users/kwanbum/...` 링크가 이 경로로 살아남았습니다 |
| macOS 테스트 1건 | GitHub macOS 러너에는 Docker 가 없어 `docker.docker_version` 이 unknown 이 되고 provenance 필수 필드 검사가 실패합니다 |

**병합 전에 원격 CI 상태를 확인하십시오.** 로컬 통과는 필요조건이지 충분조건이
아닙니다.

```bash
gh run list --branch main --limit 1 --json headSha,conclusion
```

**OS 의존 fail-open 은 Docker 로 재현하십시오.** macOS 는 대소문자를 구분하지
않고 개발자 홈 디렉터리가 실재하므로, 경로를 다루는 검증기는 로컬에서 항상
후하게 통과합니다.

```bash
docker run --rm -v "$PWD":/w -w /w python:3.12-slim python3 scripts/validate_doc_links.py
```

검증기는 이제 저장소 루트 기준 절대 표기(`/docs/...`)만 허용하고, 머신 절대
경로는 존재해도 깨진 링크로 잡습니다. 회귀 테스트는
`test_host_absolute_path_is_broken_even_if_it_exists` 와
`test_file_uri_to_host_path_is_broken` 입니다.

---

## 22. 승인 대기가 워커를 멈추는 세 지점 (2026-08-30)

한 세션에서 워커 승인 대기가 여덟 차례 넘게 발생했고 그중 여러 번을 사용자가 먼저
발견했습니다. 코디네이터가 매번 손으로 풀었을 뿐 원인을 고치지 않았기 때문입니다.

### 22.1 일괄 보류는 판정이 아니라 회피였습니다

`scripts/orca_auto_approve.py` 는 셸 메타문자가 하나라도 있으면 명령을 통째로
보류했습니다. 워커의 조사와 검증 명령은 파이프, 리다이렉트, `&&` 를 일상적으로
쓰므로 거의 전부 걸립니다.

**해결**: 따옴표 밖 구분자로 파이프라인을 분해해 각 구간을 기존 규칙으로 판정하고,
모든 구간이 승인일 때만 승인합니다. 판정이 느슨해진 것이 아니라 정밀해집니다.
`ls | grep foo` 는 승인하고 `ls | git push` 는 뒤 구간이 걸려 보류합니다.

**구분자에 개행과 캐리지 리턴을 반드시 포함하십시오.** 빠뜨리면
`git diff\recho x` 가 한 구간으로 보여 승인되고 실제로는 두 명령이 실행됩니다.
이 실수를 기존 테스트가 잡았습니다.

### 22.2 워커의 주력 도구를 막으면 워커가 멈춥니다

`python` 실행이 명시적 보류 대상이었습니다. 워커의 조사와 검증은 거의 전부
python 으로 이뤄지므로 사실상 상시 차단입니다.

**해결**: `os.system`, `subprocess`, `shutil.rmtree`, `eval`, `exec` 같은 셸 탈출
토큰이 없을 때만 승인합니다.

### 22.3 히어독 보고서 쓰기를 막으면 보고서를 못 씁니다

워커는 분석 보고서를 `cat <<'EOF' > docs/analysis/x.md` 로 씁니다. 히어독을
일괄 보류하면 보고서를 쓸 때마다 걸립니다.

**해결**: 구분자를 따옴표로 감싼 히어독(`<<'EOF'`)은 셸이 본문을 확장하지 않아
본문이 순수 데이터입니다. 쓰기 대상 경로만 검증하면 안전합니다. 따옴표 없는
`<<EOF` 는 확장이 일어나므로 계속 보류합니다.

### 22.4 함께 발견한 기존 결함

`cat` 이 안전 목록에 있어 **`cat .env` 가 승인되고 있었습니다.** AGENTS.md 7장이
금지하는 값 노출입니다. 읽기 전용 도구라도 인자에 비밀 파일이 있으면 보류하도록
고쳤습니다.

**교훈**: 안전 목록은 실행 파일 이름만 보면 안 되고 인자도 봐야 합니다.

---

## 23. 프로필마다 등록된 모델이 다르다 (2026-08-30)

`or-free/minimax-m3` 을 기본 프로필(`~/.kimi-code`)에서 3회 응답 확인한 뒤 런처로
띄웠는데, `scripts/orca_kimi_launch.py` 의 `DEFAULT_HOME` 은
`~/.kimi-openrouter-bakeoff` 였고 그 프로필에는 해당 모델이 없었습니다.

```
error: failed to run prompt: Model "or-free/minimax-m3" is not configured in config.toml.
```

**화면에는 워커가 뜬 것처럼 보이므로 사람이 원인을 찾기 어렵습니다.** 런처가
preamble 을 최대 300초 기다린 뒤에야 실패하므로 그동안 코디네이터는 워커가 도는
줄 압니다.

**해결**: 런처가 기동 전에 대상 프로필의 `config.toml` 을 읽어 모델 등록 여부를
확인하고, 없으면 그 프로필에서 쓸 수 있는 모델 목록과 함께 즉시 중단합니다.

**교훈**: 모델 가용성 검증은 **실제로 워커를 띄울 프로필과 같은 조건**에서 해야
합니다. 다른 조건에서 확인한 결과는 근거가 되지 않습니다.

---

## 24. 정본 문서 신선도를 HEAD 로 재면 수렴하지 않는다 (2026-08-30)

`validate_agent_rules.py` 가 `CURRENT_STATE.md` 의 `source_commit` 신선도를
`rev-list --count <commit>..HEAD` 로 쟀습니다. 작업 브랜치에서는 그 브랜치의
커밋까지 세므로, **워커가 커밋을 낼수록 문서가 낡은 것으로 오판됩니다.**

한 세션에서 갱신을 네 번 반복했고 그중 두 번은 **어떤 값으로도 수렴하지
않았습니다.** 갱신 커밋 자체가 정본 브랜치를 두 커밋 앞세우고, 작업 브랜치가
그것을 병합하면 거리가 다시 늘기 때문입니다. 그 결과 실질 품질 게이트를 전부
통과한 Task 두 건을 이 아티팩트 하나 때문에 게이트 실패 상태로 병합해야 했습니다.

**해결**: 신선도 기준을 `HEAD` 가 아니라 **`HEAD` 와 `main` 의 공통 조상**으로
바꿉니다. 정본 문서의 신선도는 정본 브랜치 기준으로 재는 것이 맞고, 작업 브랜치의
자체 커밋은 세지 않습니다. `main` 을 찾을 수 없으면 종전대로 `HEAD` 를 씁니다.

**교훈**: 게이트가 반복해서 같은 아티팩트로 실패하면 워커를 탓하기 전에
**게이트의 측정 기준이 옳은지** 보십시오.

---

## 25. 완료된 워커 하위 세션을 회수하지 않는다 (2026-09-01)

Wave J 워커 4대가 `worker_done` 을 보낸 뒤에도 터미널과 워크트리가 남아
있었습니다. 코디네이터는 병합 판정과 Level 1 을 우선했고, 기존 8.1 절이
`origin/main` 병합을 회수의 첫 조건으로 적어 원격 미푸시를 핑계로 창을
남겨 두었습니다. 사용자는 그 잔류를 먼저 발견했습니다.

**회수는 병합의 후속이 아닙니다.** Task 가 `completed` 면 워커 창부터
닫습니다. 워크트리와 브랜치는 로컬 `main` 병합 확인 뒤에만 지웁니다.

강제 장치: `scripts/orca_settled_session_audit.py`, `taskctl dispatch` 의
완료 세션 잔류 검사, `orca_worker_watch.py` 의 `[차단:회수 대기]`.
