# 코디네이터 토큰 소진 인수인계 (2026-08-15)

> **작성일**: 2026-08-15 09:00 (Asia/Seoul)
> **갱신**: 2026-08-15 (Run 전건 병합·검증 완료. 대기 작업 없음. GPT 세션으로 상태 인수)
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

## 3. 대기 중인 작업: 없음

**2026-08-15 시점에 진행 중이거나 미병합인 워커 작업은 없습니다.** Run `run_659389fed248` 의 Task 7건이 모두 `completed` 이고 전부 검증 후 `main` 에 병합됐습니다.

| Task | 산출물 | 검증 |
| --- | --- | --- |
| w1 | `scripts/orca_level1_gate.py` | Level 1 단일 호출, 사람 출력 상한 2,000자 |
| w2 | `scripts/summarize_worker_done.py` | 보고 계약 판정 + 1,200자 다이제스트 |
| w3 | `scripts/orca_metrics_ledger.py` | 프록시 지표 append-only 원장 |
| a1 | `scripts/orca_run_reviewer.py` | Level 2 단일 호출 |
| b1 | 독립 감사 문서 | 실재 결함 7건 검출 |
| c1 | 결함 7건 수정 | 코디네이터가 재현 7/7 확인 |
| e1 | Level 3 축소 실험 | 실측 완료. **축소 미채택** (근거는 실험 문서 9장) |

공용 파서 `scripts/orca_contract.py` 는 코디네이터가 직접 작성했습니다.

`main` = `e37f125` = `origin/main`, 전체 테스트 **1149 passed / 2 skipped**, 규칙 검증 12/12, 미커밋 0, 활성 워크트리 없음, 메일박스 비움.

### 3.1 따라서 인수는 작업 인수가 아니라 상태 인수입니다

넘길 미완 작업이 없습니다. 아래 4장은 앞으로 워커를 쓸 때의 검증 절차이고, 6장이 다음에 할 일과 각각의 제약입니다.

### 3.2 오늘 세 번 반복된 문제 (다음에 정리할 값이 있음)

수명주기 이력과 실제 산출물이 어긋나는 일이 세 번 났습니다.

| 사례 | 증상 |
| --- | --- |
| `report_path` 재사용 | 후속 Dispatch 가 1차 보고를 덮어써 이력 소실 (금지 목록 12) |
| 완료된 Task 에 재작업 지시 | 2차 `worker_done` 이 `Rejected` 되어 반려 사유가 이력에서 사라짐 (금지 목록 15) |
| e1 이 `ready` 로 잔류 | 산출물은 커밋에 있는데 Task 상태가 미완으로 남아 코디네이터가 수동 정정 |

세 건 모두 **커밋을 근거로 판단하는 원칙** 덕에 결과에는 영향이 없었습니다. 그러나 무인 운영을 늘릴수록 이력만으로 판단할 수 없다는 뜻입니다. 정리 방향은 Task 하나에 Dispatch 하나를 원칙으로 두고, 재작업은 새 Task 로 만드는 것입니다.

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

## 6. 다음에 할 일과 각각의 제약

`CURRENT_STATE.md` §4 의 우선순위입니다. **셋 중 둘은 사용자 없이 할 수 없습니다.**

| 순위 | 작업 | 무인 가능 | 제약 |
| :---: | --- | :---: | --- |
| 1 | Ollama `OLLAMA_NUM_PARALLEL` 실험, SSE 동시성 기준선 제정 | **불가** | 호스트 Ollama 가 사용자 소유 프로세스이며 재기동 필요. Docker 독점 점유 필요 |
| 2 | Windows Docker Desktop 실기 검증 (G2 완결) | **불가** | Windows 실기 환경 필요 |
| 3 | 수집 2·3회차 관찰 | 조건부 | Docker 스택 기동 필요 |
| - | Level 3 축소 재실험 | **가능** | 순수 소프트웨어, 공유 자원 없음 |

### 6.1 Ollama 실험을 함부로 시작하지 마십시오

게이트 규약은 회차당 표본 수와 3회 반복, 주변 부하 실측을 요구합니다. `OLLAMA_NUM_PARALLEL` 값별로 반복해야 하므로 측정만 수 시간입니다.

**중간에 코디네이터 토큰이 끊기면 규약 §7 에 따라 그 측정은 양방향으로 무효입니다.** 절반만 측정된 데이터는 판단 근거가 못 되고 다음 세션이 처음부터 다시 해야 합니다. 시작 전에 다음을 모두 확인하십시오.

1. 사용자가 동석해 호스트 Ollama 재기동을 승인했는가
2. Docker 와 Ollama 를 독점 점유할 수 있는가 (다른 세션이 쓰고 있지 않은가)
3. 남은 토큰으로 측정 완주와 판정까지 가능한가

하나라도 아니면 시작하지 않고 사용자에게 보고합니다.

### 6.2 무인으로 안전한 유일한 항목: Level 3 축소 재실험

e1 실험은 절차는 지켰으나 외적 타당성이 미달이었습니다. 픽스처의 **함수당 결함 밀도가 1.0** 이어서, 개선안의 "전수 열거" 요구가 열거만으로 검출되는 구조였습니다. 실제 코드는 약 0.05 입니다.

재실험 조건은 이미 기록돼 있습니다 ([`../ops/orca_v2_level3_reduction_experiment_20260815.md`](../ops/orca_v2_level3_reduction_experiment_20260815.md) 9.4).

1. 결함 밀도를 실제 수준(함수당 0.05 내외)으로 낮춘다
2. 팔 A 체크리스트에 **로직 항목을 섞는다** (e1 의 팔 A 는 의존성·이모지·명명·docstring 뿐이라 0% 가 나왔고, 선행 감도 시험의 50% 와 불일치한다)
3. 여러 함수에 걸친 **상호작용 결함을 최소 1건** 포함한다

하네스는 `scripts/run_level3_reduction_experiment.py` 로 이미 있습니다. 픽스처와 채점 규칙만 새로 만들면 됩니다. 사전 등록 원칙(채점 규칙을 실행보다 먼저 커밋)을 반드시 지키십시오.

**다만 GPT 주간 잔량도 적다고 확인되었습니다.** 잔량이 실험 완주에 부족하면 시작하지 말고 사용자에게 보고하는 것이 맞습니다. 미완 실험은 다음 세션에 부채로 남습니다.

### 6.3 정책을 바꾸지 마십시오

Level 3 코디네이터 검토는 **유지**로 확정됐습니다. e1 이 (가) 결론을 냈지만 코디네이터가 채택하지 않았고, 그 판단 근거가 실험 문서 9장에 있습니다. 재실험 결과가 좋아도 정책 변경은 사용자 확인을 받습니다.

개선안 3요구(포괄 항목, 전수 열거, 재현 명령)는 이미 리뷰어 Capsule **기본형으로 채택**됐습니다. 새 리뷰어 Capsule 을 쓸 때 이 셋을 넣으십시오.

## 7. 정리 상태

| 항목 | 값 |
| --- | --- |
| `main` | `e37f125` = `origin/main` |
| 전체 테스트 | 1149 passed / 2 skipped |
| 규칙 검증 | 12/12 |
| 미커밋 | 0 |
| 활성 워크트리 | 없음 (주 저장소 1개) |
| 활성 워커 터미널 | 없음 |
| Orca Task | `run_659389fed248` 7건 전부 `completed` |
| 메일박스 | 비움 |
| 미병합 폐기 판정 브랜치 | `feat/codex-task-routing`, `integrate/arq-worker-cutover`, `perf/predict-tail` (재병합 시도 금지) |
| 지표 원장 | 4행 (Capsule 중앙값 7,720자, 보고 2,197자, `read_files` 7.5건, 왕복 2회) |

### 7.1 코디네이터가 남긴 규칙 위반 기록

`210ef4a`, `b07a0e4` 두 커밋이 `main` 에서 직접 만들어졌습니다. AGENTS.md 금지 7번 위반입니다. 내용은 검증된 상태이고 이미 푸시되어, 푸시된 이력을 되쓰는 것이 위반보다 위험하다고 판단해 그대로 두고 기록합니다. 인수자는 같은 실수를 반복하지 마십시오. 병합 직후 이어서 작업할 때가 특히 위험합니다.

### 7.2 주 저장소를 공유하는 세션이 있습니다

GPT 세션이 격리 워크트리가 아니라 **주 저장소 작업 디렉터리**에서 돌고 있습니다. 다음을 지키십시오.

- `git add -A` 와 `git stash` 를 쓰지 않습니다. 다른 세션의 미커밋 변경을 삼킵니다
- 커밋은 파일을 명시해 `git add <경로>` 로 합니다
- 컨테이너와 브랜치를 임의로 정리하지 않습니다
- 테스트 실패가 나오면 단독 재실행으로 격리해 확인합니다
