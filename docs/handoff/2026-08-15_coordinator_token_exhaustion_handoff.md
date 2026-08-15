# 코디네이터 토큰 소진 인수인계 (2026-08-15)

> **작성일**: 2026-08-15 09:00 (Asia/Seoul)
> **갱신**: 2026-08-15 (a1/b1/c1 병합 완료, e1 착수, GPT 전환 절차 확정)
> **작성자**: Claude Opus 5 코디네이터
> **사유**: 주간 토큰 한도 97% 소진. 리셋 2026-08-16 18:00 (Asia/Seoul)
> **인수 대상**: 다음 코디네이터 세션 (Claude 리셋 후 복귀, 또는 GPT 세션으로 즉시 전환)
> **바인딩 Run**: `run_659389fed248`

---

## 1. 왜 이 문서가 있는가

Claude 코디네이터의 주간 한도가 97% 소진되어 약 33시간 동안 검증·병합 판정을 할 수 없습니다. 그동안 워커 2대가 격리 브랜치에서 작업합니다. **워커 산출물은 병합되지 않은 상태로 대기하며, `main` 은 안전합니다.**

전환 계획은 두 단계입니다.

| 단계 | 조건 | 행동 |
| --- | --- | --- |
| 1 (현재) | 워커만 진행, 코디네이터 침묵 | 워커가 자체 검증하고 `escalation` 만 남긴다 |
| 2 | Claude 잔량이 완전히 끊기고 즉시 진행이 필요할 때 | GPT 세션이 코디네이터를 인수한다 |

---

## 2. 토큰 실측 (2026-08-15 08:45 기준)

`/usage` 표시와 로컬 트랜스크립트 집계를 맞춘 값입니다.

| 창 | 소진 | 리셋 | 창 내 원시 토큰 | 잔여 추정 |
| --- | :---: | --- | ---: | ---: |
| 5시간 (세션) | 55% | 08-15 12:50 | 23.7M | 19.4M |
| **주간 (전 모델)** | **97%** | **08-16 18:00** | 748.0M | **23.1M** |

주간 창 시작은 08-09 18:00 이며 그 사이 요청 3,686건, 시간당 원시 5.55M 을 소비했습니다.

잔여 3% 의 실질 환산은 **약 114 요청**입니다. 비율 기반이므로 서버의 캐시 가중치와 무관하게 성립합니다. 단 향후 작업 패턴이 과거와 유사하다는 가정이 붙습니다.

측정 방법은 재현 가능합니다. `~/.claude/projects/**/*.jsonl` 의 assistant 메시지에서 `message.usage` 를 모아 `requestId` 로 중복을 제거하고 시간창별로 합산했습니다.

---

## 3. 지금 돌고 있는 작업

| Task | 내용 | 워커 | 브랜치 | Capsule |
| --- | --- | --- | --- | --- |
| `task_4d22d2ba2859` (e1) | **Level 3 축소 가능성 실험.** 체크리스트 밖 결함 6건을 심고 현행 계약(팔 A)과 개선안(팔 B)으로 각 3회 리뷰어를 돌려 검출률과 오탐률을 비교 | Antigravity `gemini-3.7-flash-high` | `kwanbum217/orca-level3-experiment` | `/Users/kwanbum/orca/capsules/run_659389fed248/e1/capsule.yaml` |

### 3.1 이미 끝난 작업 (참고)

| Task | 결과 |
| --- | --- |
| a1 | `scripts/orca_run_reviewer.py` 병합. Level 2 가 명령 하나가 됨 |
| b1 | 수신면 도구 4개 독립 감사. **실재 결함 7건 검출** |
| c1 | 그 7건 전건 수정. 코디네이터가 재현 7/7 확인 후 병합 |

### 3.2 e1 실험의 핵심 제약

이 실험은 **결과를 유리하게 만들 여지를 사전에 막아 둔 설계**입니다. 검증자는 다음을 반드시 확인하십시오.

| 확인 항목 | 방법 |
| --- | --- |
| 채점 규칙이 실행보다 먼저 확정됐는가 | `git log --oneline` 에서 `scoring_rule.md` 커밋이 결과 문서 커밋보다 앞에 있어야 한다 |
| 두 팔의 차이가 명시된 세 가지뿐인가 | `arm_a_capsule.yaml` 과 `arm_b_capsule.yaml` 의 diff |
| 심은 결함이 정확히 6개인가 | `seeded_target_clean.py` 와 `seeded_target_defective.py` 의 diff |
| 무효 실행을 검출 0 으로 세지 않았는가 | 결과 문서의 유효 실행 수와 무효 횟수 |
| 축소 권고 기준을 지켰는가 | 결론 (가)를 쓰려면 6개 중 5개를 3회 모두 검출해야 한다 |

**개선안이 나아지지 않았다는 결론도 유효한 결과입니다.** (다) 결론이 나왔다고 재실행을 지시하지 마십시오. 표본이 팔당 3회라 작다는 한계는 문서에 명시되어 있어야 합니다.

## 4. 인수자가 할 일

### 4.1 수신

```bash
orca orchestration run-use --id run_659389fed248 --json
orca orchestration task-list --run run_659389fed248
orca orchestration check --run run_659389fed248
```

`Rejected worker_done` 이 보이면 그 Task 가 이미 `completed` 인 상태에서 두 번째 보고가 온 것입니다. 산출물은 커밋에 남아 있으니 커밋으로 판단합니다. 절차는 [`../ops/orca_orchestration_playbook.md`](../ops/orca_orchestration_playbook.md) 6.2.1.

### 4.2 검증

**보고 JSON 전문을 읽지 마십시오.** 도구로 받습니다.

```bash
# a1 (worker_done)
python3 scripts/summarize_worker_done.py \
  --report /Users/kwanbum/orca/capsules/run_659389fed248/a1/worker_done_d1.json \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/a1/capsule.yaml

# b1 (review_done)
python3 scripts/validate_review_report.py \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/b1/capsule.yaml \
  --report /Users/kwanbum/orca/capsules/run_659389fed248/b1/review_done_d1.json

# Level 1 기계 검증
python3 scripts/orca_level1_gate.py --base main --branch HEAD \
  --repo /Users/kwanbum/orca/workspaces/refac_bid_box/orca-run-reviewer \
  --tests 'tests/test_orca_run_reviewer.py' \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/a1/capsule.yaml
```

종료 코드 의미는 세 도구 모두 `0` 통과, `1` 위반 또는 게이트 실패, `2` 도구 오류입니다.

### 4.3 반드시 직접 볼 것 (Level 3)

a1 의 다음 지점은 도구가 잡지 못합니다.

- 모델 호출 경계가 실제로 분리되어 테스트가 실제 API 를 때리지 않는지
- diff 절단 상한이 프롬프트와 판정 블록 양쪽에 표시되는지
- JSON 추출 실패 시 원문을 `.raw` 로 보존하는지

b1 의 감사 결과는 **재현 명령과 실제 출력이 붙은 결함만** 받습니다. 재현 없는 의심은 `remaining_risks` 로 분류하도록 지시했습니다.

### 4.4 병합

```bash
uv run pytest -q                                  # 주 저장소에서 전량
python3 scripts/validate_agent_rules.py --quiet   # 12/12
git merge --no-ff kwanbum217/<브랜치> -m "merge: <설명>"
```

격리 워크트리에서 전량 실행하면 `data_assets` 마커 2건이 반드시 실패합니다. 회귀가 아니며 워크트리에서는 `-m 'not data_assets'` 를 씁니다. 자산이 있는 주 저장소가 정본입니다.

**`pytest ... | tail -3 && <다음>` 형태로 검증하지 마십시오.** 파이프라인 종료 코드가 `tail` 의 것이 되어 실패를 통과로 봅니다. 2026-08-15 에 실제로 놓칠 뻔했습니다.

### 4.5 지표 원장 기록

병합 후 각 Dispatch 를 한 행 남깁니다.

```bash
python3 scripts/orca_metrics_ledger.py record \
  --run run_659389fed248 --task <task_id> --dispatch <dispatch_id> \
  --role builder --model gemini-3.7-flash-high \
  --capsule <Capsule 경로> --report <보고 경로> --roundtrips <실제 왕복 횟수>
python3 scripts/orca_metrics_ledger.py summary
```

없는 값은 채우지 마십시오. `--roundtrips` 를 모르면 생략해 `null` 로 둡니다.

---

## 5. GPT 세션으로 전환할 때 (2단계)

사용자와 합의된 전환 조건입니다. **Claude 코디네이터의 응답이 토큰 한도로 끊기면 같은 세션의 GPT 가 코디네이터를 인수합니다.**

### 5.1 인수 시 읽을 것

이 문서와 [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) **둘뿐**입니다. 설계서 전문, 과거 handoff, `README.md`, `SKILLS.md` 를 열지 마십시오. GPT 주간 잔량도 적으므로 같은 절약 원칙이 적용됩니다.

### 5.2 인수 즉시 할 일

```bash
orca orchestration run-use --id run_659389fed248 --json
orca orchestration task-list --run run_659389fed248
git -C /Users/kwanbum/orca/workspaces/refac_bid_box/orca-level3-experiment log --oneline main..HEAD
git -C /Users/kwanbum/orca/workspaces/refac_bid_box/orca-level3-experiment status --short
```

터미널 핸들은 `term_b5e554ec` (e1) 입니다. **Task status 를 진척의 근거로 쓰지 마십시오.** 커밋 수와 미커밋 변경 수, 그리고 `orca terminal read` 만이 근거입니다.

### 5.3 검증 (보고 전문을 읽지 않습니다)

```bash
python3 scripts/summarize_worker_done.py \
  --report /Users/kwanbum/orca/capsules/run_659389fed248/e1/worker_done_d1.json \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/e1/capsule.yaml

python3 scripts/orca_level1_gate.py --base main --branch HEAD \
  --repo /Users/kwanbum/orca/workspaces/refac_bid_box/orca-level3-experiment \
  --tests 'tests/test_run_level3_reduction_experiment.py' \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/e1/capsule.yaml
```

그 다음 3.2 표의 다섯 항목을 직접 확인합니다. 이 다섯 개는 도구가 잡지 못합니다.

### 5.4 지키는 범위

1. **새 작업을 띄우지 않습니다.** e1 의 검증과 병합까지만 하고 멈춥니다.
2. 병합은 `git merge --no-ff` 로 하고, 주 저장소에서 `uv run pytest -q` 전량과 `python3 scripts/validate_agent_rules.py --quiet` 를 통과시킵니다.
3. **`pytest ... | tail && <다음>` 형태를 쓰지 마십시오.** 파이프라인 종료 코드가 `tail` 것이 되어 실패를 통과로 봅니다.
4. 병합 후 `CURRENT_STATE.md` §4 의 미청구 사항에서 Level 3 항목을 실험 결론으로 갱신하고 `source_commit` 을 맞춥니다.
5. 결론이 (가)여도 **Level 3 을 즉시 없애지 마십시오.** 축소를 검토할 근거가 생겼다는 것까지만 기록하고, 실제 정책 변경은 사용자 확인을 받습니다.
6. 워커·워크트리 정리는 병합 후에 합니다. 활성 Dispatch 가 소유한 트리를 건드리지 않습니다.

### 5.5 GPT 도 끊기면

e1 의 산출물은 브랜치에 격리되어 있고 `main` 은 안전합니다. 아무것도 하지 않고 Claude 주간 리셋(2026-08-16 18:00)을 기다리는 것이 정답입니다. 미검증 상태로 병합하지 마십시오.

## 6. 코디네이터 복귀 후 다음 순서

`CURRENT_STATE.md` §4 의 우선순위를 따릅니다. 다만 다음 두 건은 **사용자가 함께 있어야** 합니다.

| 작업 | 왜 무인 불가 |
| --- | --- |
| Ollama `OLLAMA_NUM_PARALLEL` 실험 (§4 우선순위 2) | 호스트 Ollama 프로세스가 사용자 소유이며 재기동이 필요. Docker 독점 점유 필요 |
| Windows Docker Desktop 검증 (§4 우선순위 3) | Windows 실기 환경 필요 |

미청구 3건 중 **Level 3 축소 가능성**은 a1 의 `orca_run_reviewer.py` 가 병합되면 실험이 가능해집니다. 체크리스트 밖 결함을 심어 두 팔(현행 계약 대비 개선안)로 검출률을 재는 설계이며, a1 이 그 실험 하네스를 제공합니다.

---

## 7. 정리 상태

| 항목 | 값 |
| --- | --- |
| `main` | `de26b3f`, origin 동기화 |
| 전체 테스트 | 1122 passed / 2 skipped |
| 규칙 검증 | 12/12 |
| 주 저장소 미커밋 | 0 |
| 활성 워크트리 | `orca-run-reviewer`, `orca-audit-20260815` (a1, b1 소유. 건드리지 말 것) |
| 활성 터미널 | `term_660151f0` (a1), `term_916eebe0` (b1) |
| 미병합 폐기 판정 브랜치 | `feat/codex-task-routing`, `integrate/arq-worker-cutover`, `perf/predict-tail` |

활성 Dispatch 가 소유한 워크트리와 터미널은 해제하지 마십시오. 병합이 끝난 뒤에 정리합니다.
