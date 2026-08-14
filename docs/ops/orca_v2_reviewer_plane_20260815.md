# Reviewer 계층 첫 실행 결과와 한계

> **작성일**: 2026-08-15
> **작성자**: 코디네이터 (Claude Opus 5)
> **대상**: 설계 9장 `Builder -> Reviewer -> Coordinator` 구조의 첫 실사용
> **판정**: **계약은 작동합니다. 그러나 Reviewer 의 pass 를 코디네이터 검토 축소의 근거로 쓸 수 없습니다**
> **근거 문서**: [`orca_coordinator_token_optimization_v2.md`](orca_coordinator_token_optimization_v2.md) 9·10장, [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)

---

## 1. 왜 이 실행이 필요했는가

설계 9장은 코디네이터 토큰 절감의 핵심 장치로 Reviewer 위임을 둡니다.

> 워커 결과를 무검증 신뢰하는 대신 **검증 비용의 일부도 별도 워커에게 위임**합니다.

그런데 `ORCA_REVIEW_DONE_V2` 계약이 문서 5곳에 정의돼 있는데도 **실사용 이력이
0건**이었습니다. 리뷰 산출물 0건, `review` 역할 Task 등록 0건입니다.

2026-08-15 시점까지 검증은 전부 코디네이터가 직접 했습니다. **설계가 없애려던
비용이 그대로 남아 있었습니다.**

---

## 2. 실행 구성

검토 대상은 **코디네이터가 직접 작성해 자기 검증만 거쳐 병합한 코드**입니다.

| 항목 | 값 |
| --- | --- |
| 커밋 범위 | `795d293..a1739f0` |
| Reviewer | Antigravity `gemini-3.7-flash-high` × 2 |
| 계약 | `ORCA_REVIEW_DONE_V2` |
| 권한 | read-only, `allowed_write_files: []` |

### 2.1 설계 5장 분할 규칙을 적용했습니다

코드 diff 가 31,524자로 Reviewer 예산 20,000자를 넘어 관심사별로 나눴습니다.

| Reviewer | 관심사 | diff |
| --- | --- | ---: |
| R1 | 검증 계약 v2 (`validate_agent_rules.py` + 테스트) | 12,048자 |
| R2 | 부트스트랩 계측 도구 (`measure_agent_bootstrap_cost.py` + 테스트) | 19,476자 |

Capsule 은 2,564자 / 2,618자로 예산(4,000자) 이내입니다.

---

## 3. 작동한 것

### 3.1 Capsule 배치 규약이 격리 누수를 막았습니다

직전 T6 smoke 에서 워커가 허용 4개를 넘어 8개를 읽었고 그중 2개가 다른 Task 의
파일이었습니다. 그 결과로 [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)
2.9 절 배치 규약을 만들었고 이번에 처음 적용했습니다.

| Reviewer | `allowed_read_files` | 실제 `read_files` | 초과 |
| --- | ---: | ---: | ---: |
| R1 | 4 | **4** | **0** |
| R2 | 4 | **4** | **0** |

**두 Reviewer 모두 이웃 Task 파일을 읽지 않았습니다.** Task 하나당 디렉터리 하나와
Capsule 자기 경로 포함이라는 두 규칙이 실제로 효과가 있었습니다.

### 3.2 계약 형식이 그대로 도착했습니다

두 Reviewer 모두 `ORCA_REVIEW_DONE_V2` 스키마로 `verdict`, `blocking_issues`,
`unverified_claims`, `missing_tests`, `requested_context`, `commands_to_verify`,
`read_files` 를 채워 보냈습니다. 자유형 장문 보고가 아니었습니다.

---

## 4. 작동하지 않은 것 — 두 Reviewer 모두 결함을 놓쳤습니다

두 Reviewer 의 판정은 **`verdict: pass`, `blocking_issues: []`,
`unverified_claims: []`, `missing_tests: []`** 였습니다.

**그러나 검토 대상 코드에 실제 결함 3건이 있었습니다.** 코디네이터가 리뷰 결과를
받은 뒤 직접 찾아 재현했습니다.

| 결함 | 위치 | 재현 |
| --- | --- | --- |
| `subprocess.run` 에 `timeout` 없음 | `validate_agent_rules.py` `_commits_behind_head` | `timeout` 인자 사용 0회. git 이 잠기면 검증기가 함께 멈추고, pre-commit 에서 돌므로 **커밋 자체가 막힘** |
| 정규식이 줄을 넘어 매칭 | 같은 파일 `check_current_state_sections` | `\D` 는 줄바꿈도 매칭. `source_commit` 값이 비어도 아래 줄의 `deadbeef` 를 커밋으로 읽음 (실측: `eadbeef` 반환) |
| 대상 부재를 통과로 처리 | 같은 파일 `check_context_budgets` | `AGENTS.md` 가 없는 트리에서 `PASS / 대상 파일 없음` 반환. 예산 검사가 파일 소실을 조용히 넘김 |

세 결함 모두 **R1 의 담당 범위 안**에 있었습니다. R1 의 `review_priorities` 는
"subprocess 실패, 예외, 경계값 처리 누락" 과 "단위 오류" 를 3번·6번 항목으로
명시했습니다. **범위 문제가 아니라 검토 깊이 문제입니다.**

### 4.1 조치

세 결함을 수정하고 회귀 테스트 4개를 추가했습니다.

| 조치 | 내용 |
| --- | --- |
| `GIT_PROBE_TIMEOUT_SECONDS = 10` | 모든 `subprocess.run` 에 적용. `TimeoutExpired`, `OSError` 포착 |
| 정규식 동일 줄 한정 | `source_commit[*_`\t ]*[:=][*_`\t ]*([0-9a-f]{7,40})\b`. 마크다운 강조 형식 허용 |
| 대상 부재는 FAIL | `missing` 목록을 만들어 명시적으로 실패 처리 |
| 테스트 19 -> 23 | 세 결함 각각과 `subprocess.run` 전수 `timeout` 지정을 잠금 |

수정 과정에서 **제 첫 정규식이 실제 형식 `> **source_commit**: `hash`` 를 놓쳐
검증기가 1/12 로 떨어졌습니다.** 즉시 재실행이 그것을 잡았습니다. Level 1 기계
검증이 제 실수를 막은 사례입니다.

---

## 5. 판정

| 항목 | 판정 |
| --- | --- |
| `ORCA_REVIEW_DONE_V2` 계약 도달 | **작동** |
| Capsule 격리 (2.9 규약 적용 후) | **작동.** 초과 0건 |
| diff 예산 분할 규칙 | **작동** |
| **Reviewer 의 결함 검출** | **미달.** 실재 결함 3건을 놓치고 pass |

### 5.1 이것이 의미하는 것

**Reviewer 의 `pass` 는 코디네이터 검토를 대체하지 않습니다.** 설계 10장은
Level 2(Reviewer) 뒤에 Level 3(Coordinator Critical Review)를 두는데, 이번 실행은
**Level 3 을 줄이면 결함이 그대로 통과한다**는 것을 보여줍니다.

따라서 현재 Reviewer 계층의 효용은 다음으로 한정합니다.

| 쓸 수 있는 것 | 쓸 수 없는 것 |
| --- | --- |
| `read_files` 대 `allowed_read_files` 대조 같은 **기계적 대조** | 결함 부재의 근거 |
| `commands_to_verify` 재현 목록 확보 | 코디네이터 diff 검토 축소 |
| 형식화된 판정 수신으로 코디네이터 읽기량 감소 | 승격·병합 판정 |

### 5.2 개선 방향 (미착수)

Reviewer 가 결함을 찾게 만드려면 다음이 필요해 보입니다. 어느 것도 아직
검증되지 않았습니다.

1. **결함이 있는 diff 로 감도 시험(seeded defect)**. 알려진 결함을 넣은 diff 를
   주고 잡는지 확인합니다. 잡지 못하면 모델이나 프롬프트를 바꿉니다
2. **`review_priorities` 를 질문 형태로 바꾸기.** "subprocess 실패 처리" 대신
   "모든 `subprocess.run` 에 `timeout` 이 있는가" 처럼 예/아니오로 답하게 합니다
3. **Reviewer 를 다른 모델 계열로.** 설계 11장은 "다른 제공자의 강한 모델" 을
   권하는데 이번은 Gemini Flash 였습니다. Antigravity Claude 계열 비교가 남았습니다
4. **`verdict: pass` 에 근거 요구.** 무엇을 확인해서 pass 인지 항목별로 적게 하면
   빈 검토가 드러납니다

**2번과 4번이 비용 대비 효과가 클 것으로 보이나 측정 전입니다.**

---

## 6. 코디네이터 토큰 절감에 대한 현재 결론

설계 24장의 네 항 중 셋째 항(Reviewer 가 diff 를 공격적으로 검증)이 **형식은
갖췄고 실질은 미달**입니다.

그 결과 넷째 항("코디네이터는 기계 검증과 핵심 diff 만으로 최종 판정")도 아직
성립하지 않습니다. 이번에도 코디네이터가 전체 코드를 다시 읽어 결함을 찾았습니다.

**즉 v2 의 절감 효과는 현재 "자동 주입 축소" 에서만 실현되고 있으며, "검증 위임"
은 계약만 존재합니다.** 5.2 의 개선이 측정으로 확인될 때까지 이 상태를 절감으로
계산하지 마십시오.
