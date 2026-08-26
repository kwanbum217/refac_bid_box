# 세션 인수인계: 미판정 브랜치 정리와 동시성 테스트 회수 시도 (2026-08-26 저녁)

> **작성일**: 2026-08-26 (Asia/Seoul)
> **세션 시작 HEAD**: `918881e`
> **세션 종료 HEAD**: `20bfb24` (원격 반영 완료)
> **status**: current
> **Orca Run**: `run_0e78bf666e8c`
> **종료선**: 2026-08-26 18:30 KST (사용자 장비 종료)
> **역할**: coordinator (Claude Opus 5)

---

## 1. 이 세션이 한 일

직전 세션이 정리 도중 끊겨 상태 확인부터 시작했습니다. **작업 유실은 없었습니다.**
mypy 부채 감축과 `predict_price_api` 재측정은 이미 병합·푸시까지 끝나 있었고,
게이트를 재실행해 mypy 198파일 통과, ruff 통과, 규칙 12/12 통과를 확인했습니다.

남은 실질 과제가 미판정 브랜치 정리라고 판단해 Orca 워커 3대로 병렬 처리했습니다.

| Task | 워커 | 결과 |
| --- | --- | --- |
| W1 `task_cd26c794ab1e` | cursor Composer 2.5 | 커밋했으나 **병합 기각**. 3.1 절 |
| W2 `task_49975ee8d7ea` | Antigravity Gemini 3.7 Flash Medium | **병합 완료** (`f69f0a7` -> `20bfb24`) |
| W3 `task_4190ee358120` | Kimi Code `or-free/minimax-m3` | 종료선까지 미완. 3.2 절 |

## 2. 병합한 산출물

`integrate/arq-worker-cutover` 는 판정 문서가 없던 유일한 미병합 통합 브랜치였습니다.
W2 가 트리 고유 파일 4건과 merge base 이후 변경 파일 35건을 전수 대조해
**전량 폐기 권고**로 판정했습니다([`arq_worker_cutover_branch_verdict_20260826.md`](../ops/arq_worker_cutover_branch_verdict_20260826.md)).

검증은 Level 1 게이트 PASS(통과 4 / 건너뜀 2 / 실패 0)와 코디네이터의 주장 표본
대조로 했습니다. `manual_retrain_task`, `Frgcpt` 카테고리, `/run/retrain`
엔드포인트, `.harness/pipeline.yaml` 부재, `request_id` VARCHAR(36),
`test_chat_page_transfers_result_context` 6건 모두 보고서 주장과 일치했습니다.

**이로써 저장소의 모든 미병합 브랜치에 판정 문서가 갖춰졌습니다.**

---

## 3. 기각과 미완

### 3.1 W1 동시성 테스트 회수는 기각했습니다

코디네이터가 착수 전에 `feat/p1-reliability-lock` 의 잔여 가치를 "main 테스트는
`Pool` 만 써서 실제 경합이 없다" 로 판단했으나 **이 판단이 틀렸습니다.**

`main` 의 `test_no_lost_updates_under_concurrent_writes` 는 이미
`ctx.Barrier(n_writers)` 와 `ctx.Process` 를 쓰고 있습니다
(`tests/test_orca_model_router.py:1766`). 브랜치 `75dd019` 를 봤을 때의 diff 는
그 커밋 시점 base 와의 비교였고, 그 뒤 `main` 이 독자적으로 Barrier 를 도입한 것을
확인하지 않았습니다.

W1 이 만든 변경(`12f88c3`)은 `Pool.map` + 전역 Barrier 로 바꾸면서 두 가지를
잃습니다.

| 잃는 것 | 근거 |
| --- | --- |
| 프로세스별 `exitcode == 0` 단언 | `Pool.map` 은 개별 종료 코드를 노출하지 않습니다 |
| Windows(spawn) 경로 커버리지 | fork 전용이 되어 `os.name == "nt"` 를 skip 합니다 |

W1 은 `worker_done` 에서 "잠금을 무력화하면 8건 중 1건만 남는 것을 확인했다" 고
보고했습니다. 그 판본이 회귀를 잡는다는 것은 사실로 보이나, 이는 자기 판본이
작동한다는 증거일 뿐 `main` 보다 낫다는 증거가 아닙니다. **워커는 자신이 무엇을
잃는지 보고하지 않았습니다.**

**`main` 판본이 상위이므로 병합하지 않았습니다.** 브랜치
`kwanbum217/orca-w1-concurrency-2` 에 보존만 했습니다. `feat/p1-reliability-lock`
역시 코드 수정분이 이미 `main` 에 더 나은 형태로 들어가 있어 회수 가치가 없습니다.

### 3.2 W3 베이크오프 브랜치 판정은 미완입니다

`b2-*` 5개와 `bakeoff-*` 4개(총 9개, 전부 2026-08-20)는
`scripts/audit_model_inventory.py` 에 같은 기능을 넣는 과제를 여러 모델에 태운
산출물로 보입니다. 회수 가치 판정을 W3 에 맡겼으나 종료선까지 조사 단계에
머물렀습니다. 브랜치는 **삭제하지 않고 전부 보존**했습니다.

Capsule 은 `.orca/capsules/task_4190ee358120/capsule.yaml` 에 있으므로 다음 세션에서
그대로 재 Dispatch 할 수 있습니다.

---

## 4. 이 세션에서 배운 도구 사실

| 항목 | 내용 |
| --- | --- |
| Antigravity `AI: Out of credits` | **또 오탐**입니다. 표시가 떠 있는 상태에서 Gemini 3.7 Flash Medium 이 정상 호출됐고 작업을 완주했습니다 |
| Kimi preamble 주입 | preamble 을 셸 인자로 직접 넘기면 개행과 따옴표가 깨져 zsh 오류가 쏟아집니다. 지시문을 파일로 두고 `-p "$(cat INSTR.txt)"` 로 넘기면 동작합니다 |
| `worker-start` 실패의 잔재 | 실패해도 워크트리와 브랜치는 남습니다. 이 세션에서 고아 트리 하나가 감시 도구의 차단 신호를 계속 울렸습니다. 실패 직후 정리하십시오 |
| Task 상태 전이 | 기동이 한 번 실패하면 Task 가 `failed`/`blocked` 로 굳고 재 Dispatch 가 거부됩니다. `orca orchestration task-update --id <task> --status ready` 로 되돌립니다. 플래그는 `--task` 가 아니라 `--id` 입니다 |
| `taskctl dispatch --repo` | 생략하면 `repo_not_found` 입니다. 워크트리 경로를 명시해야 합니다 |
| 재기동하면 `worker_done` 이 거부됩니다 | 터미널 부착 경로로 워커를 다시 띄우면 원래 Dispatch 의 capability 가 revoked 되어 `worker_done` 과 `escalation` 이 전부 반려됩니다. 이 세션에서 4건이 그렇게 반려됐습니다. **산출물은 멀쩡하므로 반려를 실패로 읽지 마십시오.** 커밋과 게이트로 직접 검증하고, 판정 근거는 Orca 메시지가 아니라 git 상태로 삼습니다 |

---

## 5. 자원 정리 상태

| 대상 | 상태 |
| --- | --- |
| 고아 워크트리 `orca-w1-concurrency` | **제거 완료**, 브랜치도 삭제 |
| `orca-w2-arqverdict` 워크트리·브랜치 | 병합 완료. 다음 세션에서 정리 가능 |
| `orca-w1-concurrency-2` 워크트리·브랜치 | **보존**. 기각 판정 근거가 담겨 있습니다 |
| `orca-w3-bakeoff` 워크트리·브랜치 | **보존**. 미완 작업 |
| 병합 완료 브랜치 8개(`orca-w1`~`w5`, `orca-t2`~`t4`) | **미정리**. 전부 ahead 0 이라 삭제 안전 |
| Docker | `refac_bid_box` compose 5개 기동 상태 |

---

## 6. 다음 세션 착수 순서

1. **브랜치 일괄 정리**: ahead 0 인 8개를 `git branch -d` 로 삭제합니다. `-D` 는 쓰지 마십시오.
2. **W3 재 Dispatch**: 베이크오프 9개 브랜치 판정. Capsule 재사용 가능합니다.
3. **`integrate/arq-worker-cutover` 삭제**: 판정이 전량 폐기 권고이므로 삭제 가능합니다. 삭제 전 `git log --oneline main..integrate/arq-worker-cutover` 를 한 번 읽으십시오.
4. **G3 잔여**: Windows Docker Desktop 실기는 장비 부재로 불가합니다. 남은 것은 LLM fixture 밖 일반화 측정과 numeric 절대 정확도(65.7%) 개선이며 둘 다 새 과제입니다.
