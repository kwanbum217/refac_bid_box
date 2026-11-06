# 계산 차단 응답 과제의 원래 제안 추적

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_177e67e4c1ca` (builder). 제품 코드·규칙·원장을 바꾸지 않고 기록만 추적한다.
> **정본 사양**: `.orca/capsules/task_calc_block_trace_20261106/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/calc-block-trace`
> **범위**: `docs/handoff/`, `docs/analysis/`, `docs/design/`, git 이력. 운영 DB·Redis·Docker·네트워크를 쓰지 않았다.

---

## 1. 결론

- **특정했다.** 인수인계에만 남아 있던 "계산 차단 응답(구현)"은 2026-10-15 인수인계 3절의 **"계산 차단 약 67% 의 구현"** 네 선택지를 가리킨다. "계산 차단 응답"이라는 정확한 표현은 2026-10-21 인수인계에서 처음 붙었고, 그 문서에는 정의가 없다.
- 한 문장 정의: **규칙이 확정되지 않아 계산이 막힌 용역 적격심사 공고(당시 20,973건, 66.6%)에 대해 ① 구판 별표 적재 ② 수기심사 안내 ③ 지역 규칙 등록 ④ 용역 세부유형 기본값 중 어느 방식으로 응답을 바꿀지 정하고 구현하는 과제**다.
- 정의의 정본은 [handoff_20261015_official_reread_close.md](../handoff/handoff_20261015_official_reread_close.md) 3절(`238e5ed3`)이다. 2026-10-14 두 인수인계의 "계산 차단 67% 대응"이 전신이며, 2026-10-28 인수인계에서 "계산 차단 구현"으로 줄어 다시 등장한다.
- 다만 "응답"을 **API 차단 응답 계약**으로 좁게 읽는 해석도 성립한다. 그 계약은 2026-10-05 설계와 2026-10-14 구현으로 이미 대부분 존재하므로, 두 해석은 남은 작업의 범위를 크게 가른다. 차이는 4.3절과 5절에 적었다.

---

## 2. 등장 이력

| 날짜 | 문서·커밋 | 원문 인용 (80자 이내) | 읽는 바 |
| --- | --- | --- | --- |
| 2026-10-14 | [handoff_20261014_detail_page_coverage_close.md](../handoff/handoff_20261014_detail_page_coverage_close.md) 4·6절, `7513b3a7` | "계산 차단 67% 대응(시행일 이전 공고용 구판 별표, 수기심사 안내, 세부유형 기본값)" … | 최초 제안. 세 선택지가 사용자 결정 대기로 남았다 |
| 2026-10-14 | 같은 문서 4절 | "계산 차단 \| 20,973 \| 66.6%" | "67%"의 산출 근거. 발행 원장 31,485건 기준 |
| 2026-10-14 | [handoff_20261014_ocr_ledger_close.md](../handoff/handoff_20261014_ocr_ledger_close.md) 0·4절, `b55bec7e` | "계산 차단 약 67% 대응 \| 사용자 결정 전" … | 다음 세션으로 그대로 넘겼다 |
| 2026-10-15 | [handoff_20261015_official_reread_close.md](../handoff/handoff_20261015_official_reread_close.md) 3절, `238e5ed3` | "계산 차단 약 67% 의 구현 \| 구판 적재, 수동 평가 안내, 지역 규칙 등록, 기본 용역 유형" … | "대응"이 "구현"으로 바뀌고 네 선택지로 범위가 확정됐다. 유일한 범위 정의 |
| 2026-10-20 | [handoff_20261020_close.md](../handoff/handoff_20261020_close.md) 5절, `59b2554a` | "차단 응답 세 곳에 남은 `assert effective_lwlt_rate is not None`" … | "차단 응답"이 API 응답 경로를 가리키는 용례 |
| 2026-10-21 | [handoff_20261021_close.md](../handoff/handoff_20261021_close.md) 0절 3번, `4b29025b` | "산림청 등록과 계산 차단 응답도 승인 밖" … | 정확한 표현의 첫 등장. 정의 없이 승인 대기로만 적었다 |
| 2026-10-28 | [handoff_20261028_session_close.md](../handoff/handoff_20261028_session_close.md) 5절, `cd4898a0` | "산림청 등록, `rule_coverage_ledger.yaml` 재작성, 계산 차단 구현" … | "계산 차단 구현"으로 축약. 범위 설명 없음 |
| 2026-11-06 | 이 문서 | - | 2026-10-15 3절을 원래 제안으로 특정 |

- 2026-10-15 문서는 처음에 `main` 에 병합되지 않았고, 2026-10-19 `238e5ed3` 으로 저장소에 들어왔다. 2026-10-21 인수인계는 그 문서를 읽을 수 있는 시점에 작성됐다.
- 2026-10-21과 2026-10-28 문서는 이 항목을 "승인 밖", "사용자 승인 전"으로만 적었다. 두 문서 안에 무엇을 바꾸자는지에 대한 설명은 없다.
- 2026-10-20 5절의 "차단 응답"은 `evaluations.py` 의 차단 응답 경로를 가리키는 기술 메모다. 이 과제와 같은 단어를 쓰지만 문맥은 다르다.

---

## 3. 원래 제안의 범위

### 3.1 네 선택지와 대상 차단 코드

원 제안은 "차단을 모두 없앤다"가 아니라, 차단 원인별로 응답 방식을 고르는 묶음이다. 수치는 2026-10-15 조사 [block_cause_survey_20261015.md](block_cause_survey_20261015.md)(`e892a236`) 4절, 최근 12개월(`2025-10-15`~`2026-10-15`)·`Servc`·낙찰방법 `낙030001`·최신 차수 31,441건 기준이다.

| 선택지 | 대상 차단 코드 | 공고 | 전체 대비 | 차단 대비 | 기록된 의미 |
| --- | --- | ---: | ---: | ---: | --- |
| ① 구판 별표 적재 | `RULE_REGIME_MISMATCH` | 9,518 | 30.27% | 45.53% | 공고일이 적용 별표 시행일보다 앞섬 |
| ② 수기심사 안내 | `MANUAL_EVALUATION` | 9,420 | 29.96% | 45.06% | 낙찰방법이 `관리규정외 수기심사` |
| ③ 지역 규칙 등록 | `LOCAL_RULE_NOT_FOUND` | 1,184 | 3.77% | 5.66% | 수요기관 시·도 규칙 부재 |
| ④ 용역 세부유형 기본값 | `LOCAL_SERVICE_TYPE_UNRESOLVED` | 72 | 0.23% | 0.34% | 지자체 별표 세부유형 미선택 |
| **네 선택지 합계** | | **20,194** | **64.23%** | **96.60%** | |
| (참고) 기관 규칙 등록 | `RULE_NOT_FOUND` | 499 | 1.59% | 2.39% | 별표 식별 실패·기관 규칙 부재. 네 선택지 밖 |
| (참고) 비예가 | `NON_PRED_PRICE` | 212 | 0.67% | 1.01% | 대응 선택지가 기록에 없음 |
| **차단 전체** | | **20,905** | **66.49%** | **100.00%** | |

- 2026-10-14 발행 원장 기준 값은 20,973건(66.6%, 전체 31,485건)이다([handoff_20261014_detail_page_coverage_close.md](../handoff/handoff_20261014_detail_page_coverage_close.md) 4절). 조사 값 20,905건과의 차이는 창 하루 이동과 `min_announcements` 차이다([block_cause_survey_20261015.md](block_cause_survey_20261015.md) 6절).
- `RULE_NOT_FOUND` 499건은 2026-10-15 네 선택지에 들어 있지 않다. 산림청·해양환경공단 같은 기관 규칙 등록은 별도 항목으로 다뤄졌다.
- 2026-10-18 조사 [remaining_block_codes_20261018.md](remaining_block_codes_20261018.md)(`5b190c8c`)는 `NON_PRED_PRICE` 185건에 대해 "인수인계에 대응 선택지 없음, 대응 여부 미정"으로 적었다. 네 선택지가 차단 전체를 덮지 않는 이유다.

### 3.2 바꿀 파일·함수·응답 필드

원 제안 문서는 파일명을 지정하지 않았다. 아래는 2026-10-05 설계([local_user_input_ui_20261005.md](../design/local_user_input_ui_20261005.md), `9ccfda2b`)와 현재 코드에서 대응 지점을 역으로 붙인 것이다.

| 선택지 | 파일 | 함수·지점 | 응답 필드·화면 |
| --- | --- | --- | --- |
| ① 구판 별표 적재 | `src/app/services/evaluation_rules.py`, `src/app/services/evaluation_rules_local.py` | 규칙 정의와 시행일 선택(`resolve_evaluation_rule`, 구판 후보 선택) | `rule_id`, `rule_basis`, `warnings` |
| ② 수기심사 안내 | `src/app/api/v1/evaluations.py`, `src/app/templates/bids/detail.html` | `_manual_user_input_rule`, 차단 분기, `getBlockedReasonText`·`getBlockedGuidanceText` | `status`, `blocked`, `blocked_reason`, `warnings`, `rule_id`, `rule_basis` |
| ③ 지역 규칙 등록 | `src/app/services/evaluation_rules_local.py`, `src/app/api/v1/evaluations.py` | `LOCAL_RULES`, `_local_user_input_rule`, 차단 분기 | `rule_id`, `rule_basis`, `warnings`, 사용자 입력 경고 |
| ④ 용역 세부유형 기본값 | `src/app/services/evaluation_rules.py`, `src/app/templates/bids/detail.html` | `resolve_local_service_type`, 차단 분기, 세부유형 선택 UI | `warnings`의 `후보 별표:`·`추천:`, `blocked_reason`의 `예: ...` |

- 차단 응답의 공통 계약은 2026-10-05 설계 2.2절이 정본이다. 모든 차단 응답은 `status="blocked"`, `blocked=true`, `blocked_reason="<CODE>: <메시지>"` 형식이고, 코드에 따라 `warnings`, `rule_id`, `rule_basis`, `score_table` 이 함께 온다.
- 2026-10-05 설계의 입력 필드는 `base_rate`, `manual_non_price_score`, `local_service_type`, `estimated_price` 이다. 네 선택지 중 ②③④가 이 필드들과 직접 연결된다.
- 2026-10-14 구현 `d284b963` 은 `PRICE_BOUNDS_UNRESOLVED` 차단에 "통과까지 부족한 정량점수와 여지 항목"을 안내하는 응답을 이미 추가했다. 이는 원 제안의 네 선택지와 별개로 진행된 차단 응답 개선이다.

### 3.3 기록에 있는 영향 공고 수

| 값 | 수치 | 출처 |
| --- | --- | --- |
| 발행 원장 전체·차단 | 31,485건 중 20,973건(66.6%) | [handoff_20261014_detail_page_coverage_close.md](../handoff/handoff_20261014_detail_page_coverage_close.md) 4절, `7513b3a7` |
| 조사 창 전체·차단 | 31,441건 중 20,905건(66.49%) | [block_cause_survey_20261015.md](block_cause_survey_20261015.md) 3절, `e892a236` |
| 선택지별 건수 | 9,518 / 9,420 / 1,184 / 72 | 같은 문서 4절 |
| 네 선택지 밖 | `RULE_NOT_FOUND` 499, `NON_PRED_PRICE` 212 | 같은 문서 4절 |

- 원 제안에는 "몇 건이 풀린다"는 예상치가 없다. 위 수치는 대상 규모이고, 선택지를 구현했을 때의 감소량은 기록에 없다.
- 2026-10-18 이후 실제 감소량은 별도 기록에 있다. 차단은 10,304 → 10,119 → 10,109 → 9,911건으로 줄었다([handoff_20261019_close.md](../handoff/handoff_20261019_close.md) 1절, [handoff_20261018_close.md](../handoff/handoff_20261018_close.md) 6·7절). 이 감소는 주로 ① 구판 적재와 ③ 지역 규칙 등록의 결과다.

---

## 4. 현재 코드 상태

### 4.1 판정 요약

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 차단 응답 공통 계약 | 구현됨 | `evaluations.py:1219`, `schemas/evaluations.py:539` |
| ① 구판 별표 적재 | 구현됨(부분) | `evaluation_rules.py:1134`, `:3417`, `evaluation_rules_local.py:617` |
| ② 수기심사 안내 | 구현됨 | `evaluations.py:547`, `:1887`, `detail.html:860`, `:883` |
| ③ 지역 규칙 등록 | 구현됨(부분) | `evaluation_rules_local.py:617`, `evaluations.py:499`, `:1857` |
| ④ 용역 세부유형 기본값 | 미구현 | `evaluation_rules.py:1912`, `:2225`, `detail.html:933` |
| 산림청 기관 규칙 등록 | 미구현 | `src/` 에 산림청 규칙 없음 |
| `NON_PRED_PRICE` 해제 경로 | 미구현(차단 유지) | `evaluation_rules.py:3336`, `detail.html:859` |

### 4.2 세부 근거

- **차단 응답 공통 계약**: `_blocked_response` 가 `status="blocked"`, `blocked=True`, `blocked_reason=f"{code}: {message}"`, `warnings` 를 만든다(`src/app/api/v1/evaluations.py:1219-1245`). 스키마 필드는 `src/app/schemas/evaluations.py:539-543` 이다. API 시험은 500 이 아니라 200 차단 응답임을 고정한다(`tests/test_evaluations_api.py:830-851`).
- **① 구판 별표 적재**: 기술용역 구판 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 이 정의되어 있고(`src/app/services/evaluation_rules.py:1134-1150`), 공고일로 현행·구판을 고른다(`:3417-3419`). 시·도 규칙 모듈에는 `SERVC_LOCAL_` 규칙 ID가 71개 있다(`src/app/services/evaluation_rules_local.py:617` 이하). 구판 선택 시험은 `tests/test_tech_service_qualification.py:18`, `:143` 에 있다. 다만 모든 시행일 구간의 구판이 등록된 것은 아니므로 "부분 구현"으로 판정한다.
- **② 수기심사 안내**: `MANUAL_EVALUATION` 차단에서 `_manual_user_input_rule` 이 B·k·기준비율·통과점수를 받아 계산하고, 일부만 오면 부족 항목을 안내한다(`src/app/api/v1/evaluations.py:547-594`, 분기 `:1887-1919`). 화면은 차단 사유·안내 문구를 코드별로 매핑하고(`src/app/templates/bids/detail.html:860`, `:883`), 입력 패널을 연다(`:922`, `:994-1027`). 시험은 `tests/test_manual_eval_input.py:121-160` 이다. 따라서 "안내"를 넘어 "직접 입력 계산"까지 구현됐다.
- **③ 지역 규칙 등록**: `LOCAL_RULE_NOT_FOUND` 차단에서 `_local_user_input_rule` 이 네 값을 받아 계산한다(`src/app/api/v1/evaluations.py:499-544`, 분기 `:1857-1883`). 규칙 자체는 `LOCAL_RULES` 에 등록되어 있다(`src/app/services/evaluation_rules_local.py:617`). 시험은 `tests/test_local_regime_api.py` 에 있다. 등록되지 않은 시·도·유형 조합은 여전히 차단되므로 "부분 구현"이다.
- **④ 용역 세부유형 기본값**: `resolve_local_service_type` 은 확정하지 못하면 `("GENERAL", "UNRESOLVED", ...)` 를 돌려준다(`src/app/services/evaluation_rules.py:1912-1930`). 이 경우 `LOCAL_SERVICE_TYPE_UNRESOLVED` 로 막고 후보와 추천만 `warnings` 에 싣는다(`:2225-2291`). 화면은 사용자가 고른 값만 보내고 자동 선택하지 않는다(`src/app/templates/bids/detail.html:933-991`, 선택 상자 `:541-545`). 2026-10-05 결정 D5("사용자 선택 + 자동 추천, 자동 확정 금지")를 그대로 지킨 상태이므로, "기본값"은 구현되지 않았다.
- **산림청**: `src/` 와 기관 규칙 명단에 산림청 규칙이 없다. 저장소의 산림청 문자열은 RAG·원장 조사 시험에만 있다(`tests/test_rule_coverage_ledger.py:523`). 미등록 사유는 "적격심사 공고에 `산림사업` 토큰 0건"이다([forest_koem_register_gap_20261015.md](forest_koem_register_gap_20261015.md)).
- **`NON_PRED_PRICE`**: 비예가 공고를 차단하고 안내 문구만 준다(`src/app/services/evaluation_rules.py:3336`, `src/app/templates/bids/detail.html:859`, `:882`). 해제 입력 경로가 없다.

### 4.3 원장의 "계산 차단"과 화면의 "차단 응답"은 다르다

- 커버리지 원장은 `scripts/report_rule_coverage.py` 가 `resolve_evaluation_rule_from_raw_data` 를 **사용자 입력 없이** 호출해 분류한다. `is_blocked` 면 `BLOCKED` 로 센다(`scripts/report_rule_coverage.py:143-167`).
- 그래서 `MANUAL_EVALUATION` 8,221건과 `LOCAL_RULE_NOT_FOUND` 135건은 원장에서 차단으로 남아 있지만, API 에서는 사용자가 값을 입력하면 계산된다. 발행 원장(2026-10-19 생성)의 차단은 9,911건(31.66%)이고, 기관 행 `block_codes` 합은 8,606건, `tail` 의 차단은 1,305건이다(`data/reference/rule_coverage_ledger.yaml`).
- 즉 "계산 차단 응답 구현"을 **원장 분류**로 읽으면 아직 할 일이 있고, **API 응답**으로 읽으면 이미 대부분 구현되어 있다. 2026-10-28 인수인계가 이 항목을 원장 재작성과 나란히 둔 것도 이 구분 때문으로 보인다.

---

## 5. 사용자 결정에 필요한 선택지

| 선택지 | 범위 | 이미 된 것 | 새로 바꿀 것 | 영향 |
| --- | --- | --- | --- | --- |
| A. 2026-10-15 네 선택지 묶음을 정본으로 확정 | ①~④ | ①②③ 구현, ④ 사용자 선택만 구현 | ④ 기본값을 둘지 결정. 두려면 D5를 바꾸고 `resolve_local_service_type`·차단 문구·시험을 고친다 | 지자체 `LOCAL_SERVICE_TYPE_UNRESOLVED` 72건(2026-10-15 기준)의 응답이 달라진다. D5 회귀 위험 |
| B. "계산 차단 응답"을 API 차단 응답 계약으로 한정 | 공통 `blocked` 계약과 코드별 안내 | `_blocked_response`, 코드별 사유·안내, 사용자 입력 경로 | 코드 변경 없음. 인수인계 문구만 정정하고 항목을 닫는다 | 원장 수치·차단 건수 변화 없음. 가장 작은 범위 |
| C. 차단 응답에 구조화된 해제 정보를 추가 | 모든 차단 코드 | 현재는 `blocked_reason` 문자열과 `warnings` 뿐 | `required_inputs`·`resolution_options` 같은 새 응답 필드, 스키마·화면·시험 | 응답 계약 변경. 클라이언트와 스냅샷 시험에 영향. 기록에 없는 신규 제안 |
| D. 원장 분류를 응답 기준으로 바꾼다 | `report_rule_coverage.py`, 원장 | 사용자 입력 없이 판정하는 현재 분류 | 사용자 입력으로 풀리는 코드를 별도 분류로 나누고 원장을 재생성 | `data/reference/rule_coverage_ledger.yaml` 재작성 승인 필요. 과거 수치와 비교 불가 |
| E. 현 상태 유지, 산림청만 별도 결정 | 산림청 등록만 | 나머지 그대로 | 산림청 규칙 등록 여부만 결정 | 계산 차단 응답 항목은 계속 "승인 전"으로 남는다 |

- **B가 가장 먼저 정리할 선택지다.** 원 제안의 네 선택지 중 ①②③은 이미 코드에 들어왔고, ④만 D5 때문에 의도적으로 남아 있다. "계산 차단 응답"이라는 이름으로 다시 구현할 코드는 현재 없다.
- ④를 실제로 구현하려면 2026-10-05 D5("자동 확정 금지")를 바꿔야 한다. 기본값을 넣으면 사용자가 고르지 않은 별표로 계산될 수 있으므로, 단순 UI 변경이 아니라 계산 정책 변경이다.
- 원장 재작성(D)은 2026-10-21 인수인계가 "승인 없이 `--output` 을 생략하면 게시 원장을 덮어쓴다"고 경고한 항목과 같다. 별도 승인 없이 실행하지 않는다.

---

## 6. 조사 범위와 한계

| 항목 | 내용 |
| --- | --- |
| 찾은 범위 | `docs/handoff/`, `docs/analysis/`, `docs/design/`, 전체 git 이력(`git log -S`) |
| 찾지 못한 것 | 2026-10-21 이전에 "계산 차단 응답"을 정의한 문서. 정확한 표현은 2026-10-21 이 처음이다 |
| 정의의 근거 | 2026-10-15 인수인계 3절의 네 선택지. "응답"이라는 단어는 후속 인수인계에서 붙었다 |
| 판정의 한계 | ①②③의 "구현됨"은 현재 코드와 시험으로 확인했다. 남은 구판·지역 규칙의 원문 확보 범위는 이 문서에서 다시 측정하지 않았다 |
| 수치의 한계 | 3.1절 수치는 2026-10-15 조사 창의 값이고, 4.3절 원장 수치는 2026-10-19 생성본이다. 서로 다른 창·하한이므로 대체하지 않는다 |
| 하지 않은 것 | 코드·규칙·원장·DB 변경, 원장 재생성, 운영 서비스 호출 |
