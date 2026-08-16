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

### 2.4 `README.md` 에 성능 실측값 기재

2026-08-15 에 G3 실측 3행을 제거하고 `CURRENT_STATE.md` 포인터로 대체했습니다. 수치를 README 에 적고 갱신하는 방식은 다음 측정에서 다시 뒤처지므로 채택하지 않습니다.

레이턴시 지표의 정본은 `CURRENT_STATE.md` 2장이며 측정 조건은 [`latency_gate_protocol.md`](latency_gate_protocol.md) 를 따릅니다.

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

### 4.3 Capsule 을 공유 디렉터리에 배치

2026-08-15 T6 실행 검증에서 워커가 자기 Capsule 과 함께 다른 Task 의 사양·런처를 읽었습니다. 원인은 워커가 아니라 코디네이터의 배치였습니다.

- Task 하나당 디렉터리 하나를 씁니다
- `allowed_read_files` 에 Capsule 자신의 경로를 넣습니다
- `allowed_read_files` 는 지시이며 강제 장치가 아닙니다. 준수는 `worker_done` 의 `read_files` 로 사후 확인합니다

규약: [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md) 2.9

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
