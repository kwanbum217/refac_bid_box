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

### 4.2 무료 LLM 풀의 임계 경로 투입

`cerebras/gemma-4-31b` 는 TPM 초과 위험이 있고 OpenCode 무료 모델(`deepseek-v4-flash-free` 등)은 안정성과 컨텍스트 제약이 있어 주력·임계 경로에서 배제합니다.

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

Reviewer 기본 모델은 `gemini-3.7-flash-high` 입니다. Claude 계열과 검출 성적이 동일했습니다.

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
f"{cls.name}.{method.name}"   # 클래스 메서드
f"<module>.{func.name}"       # 모듈 수준 함수
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
