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

### 5.3 파이프라인으로 검증 명령의 종료 코드 판정

`uv run pytest ... | tail -3 && <다음 명령>` 은 파이프라인 종료 코드가 `tail` 의 것이므로 **테스트 실패에도 다음 명령이 실행되고 전체가 성공으로 보입니다.**

2026-08-15 에 이 방식으로 실패 2건을 통과로 볼 뻔했습니다. 실제로는 워크트리에 Git 미추적 자산(`model.bin`, `chroma_db`)이 없어 발생한 `data_assets` 마커 테스트였고 회귀는 아니었으나, 판정 방식 자체가 틀렸습니다.

검증은 `scripts/orca_level1_gate.py` 로 수행합니다. 직접 실행할 때는 종료 코드를 파이프라인과 분리해 확인합니다.

격리 워크트리에서 전체 테스트를 돌릴 때는 `-m 'not data_assets'` 를 씁니다. 자산이 있는 주 저장소에서는 전량 실행이 정본입니다.

### 5.4 워커가 계약 필드명을 자기 표기로 바꿔 쓰는 것을 그대로 받는 행위

2026-08-15 에 워커가 자기 보고에 `files_modified` 를 쓰고, 지표 원장 코드도 그 필드명을 읽게 만들었습니다. 결과로 **계약을 지킨 모든 보고에 `changed_files_count: 0` 을 조용히 기록**했습니다.

`ORCA_WORKER_DONE_V2` 의 필드명은 `changed_files` 입니다. 비표준 필드 폴백을 코드에 남기지 않습니다. 남기면 계약 위반이 정상값으로 섞입니다.

---

## 6. 문서와 측정 판정

### 6.1 크기 예산을 바이트로 판정

설계 5장의 8,000자는 **문자 수**이며 바이트가 아닙니다. `wc -c` 로 재면 한글이 3바이트라 초과처럼 보입니다.

검증기 `check_context_budgets` 는 `len()` 으로 문자 수를 셉니다. 공용 헬퍼는 `scripts/orca_contract.py` 의 `char_len` 입니다.
