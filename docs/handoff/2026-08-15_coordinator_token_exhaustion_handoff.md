# 코디네이터 토큰 소진 인수인계 (2026-08-15)

> **작성일**: 2026-08-15 09:00 (Asia/Seoul)
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
| `task_eec190e02921` (a1) | `scripts/orca_run_reviewer.py` 신설. Level 2 리뷰어 실행을 단일 명령으로 묶는다 | Antigravity `gemini-3.7-flash-high` | `kwanbum217/orca-run-reviewer` | `/Users/kwanbum/orca/capsules/run_659389fed248/a1/capsule.yaml` |
| `task_3a80e902743a` (b1) | 2026-08-15 병합분(`c381075..de26b3f`) 4개 도구 독립 감사. 코드 수정 없음 | Antigravity `gemini-3.7-flash-high` | `kwanbum217/orca-audit-20260815` | `/Users/kwanbum/orca/capsules/run_659389fed248/b1/capsule.yaml` |

두 Task 는 서로 독립이며 파일이 겹치지 않습니다. b1 은 감사 문서 1개만 쓰고 `scripts/`, `tests/` 를 건드리지 않습니다.

두 Capsule 모두 `coordinator_absent` 절을 담고 있습니다. 막히면 기다리지 말고 그 지점까지 커밋하고 `blocking_issues` 에 사유를 적어 종료하도록 지시했습니다. `verdict` 는 반드시 `candidate`(a1) 또는 검출 결과에 따른 값(b1)이며 `pass` 는 코디네이터 검증 뒤에만 붙습니다.

---

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

Claude 잔량이 완전히 끊긴 상태에서 즉시 진행이 필요하면 GPT 세션이 인수합니다. 전달할 것은 이 문서 하나와 [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 입니다. 그 밖의 문서는 요청받았을 때만 엽니다.

GPT 세션도 주간 잔량이 적다고 확인되었으므로 다음을 지킵니다.

1. `CURRENT_STATE.md` 와 이 문서만 읽고 시작합니다. 설계서 전문과 과거 handoff 를 열지 않습니다.
2. 검증은 4.2 의 세 명령으로만 합니다. 원시 diff 통독은 4.3 의 지점에 한정합니다.
3. 새 작업을 띄우지 않습니다. 대기 중인 a1, b1 의 검증과 병합까지만 하고 멈춥니다.
4. 병합 후 `CURRENT_STATE.md` §4 를 갱신하고 `source_commit` 을 맞춥니다.

---

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
