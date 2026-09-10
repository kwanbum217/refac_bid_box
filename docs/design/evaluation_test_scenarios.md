# 일반용역 적격심사 정량평가 실사용 검증 시나리오

> **작성일**: 2026-09-10
> **목적**: 별표 14종 전량의 패턴 매칭과 4대 차단 경로를 실제 공고처럼 재현하는 시나리오를 정의하고
>   회귀 테스트로 고정한다. 기존 검증은 `9901035`(시설분야용역, 별표 1) 한 건에 의존하고 있어
>   나머지 13종 별표와 차단 경로가 보호되지 않았다.

---

## 1. 시나리오 구성 원칙

각 시나리오는 다음 조건을 충족한다:

1. **독립 실행 가능**: 외부 API(모델 추론, Redis, DB 라이브) 없이 합성 공고로 실행 가능
2. **화면 재현 가능**: 동일한 `qualification_input`을 화면에 입력하면 동일한 결과가 나와야 함
3. **결정론적**: 입력이 같으면 출력이 항상 같음 (시각·난수 의존 없음)

---

## 2. 별표 14종 패턴 매칭 시나리오

각 별표에 대해 `sucsfbidMthdNm` 값을 바꾸어 가며 올바른 `rule_id`와 `lwlt_rate`가
매칭되는지 검증한다. 기존 검증(별표 1, 공고 9901035)은 그대로 두고 별표 2-14를 추가한다.

### 2.1 별표 1: 시설분야용역 (FACILITY) -- 검증 완료 (기존)

| 항목 | 값 |
|------|------|
| 공고 예시 | 9901035 |
| sucsfbidMthdNm | `시설분야용역 적격심사 추정가격 5억원 미만` |
| sucsfbidLwltRate | `89.995` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_01` |
| 기대 하한율 | `89.995` |
| 검증 상태 | 기존 테스트로 보호됨 |

### 2.2 별표 2: 보험용역 (INSURANCE)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `보험용역 적격심사 추정가격 5억원미만` |
| sucsfbidLwltRate | `47.995` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_02` |
| 특징 | 하한율 47.995%로 14종 중 유일하게 50% 미만. 실측 정본. |

### 2.3 별표 3: 여객 육상운송용역 (PASSENGER_TRANSPORT)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `여객 육상운송용역 적격심사 추정가격 5억원미만` |
| sucsfbidLwltRate | `87.995` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_03` |

### 2.4 별표 4: 소프트웨어용역 중기간 경쟁대상 (SW_SME)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만` |
| sucsfbidLwltRate | `87.995` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_04` |
|特徴 | 패턴에 괄호 포함. normalize_pattern_string 이 공백/특수문자를 제거하는지 검증. |

### 2.5 별표 5: 소프트웨어용역 비대상 (SW_NON_SME)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액미만` |
| sucsfbidLwltRate | `86.245` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_05` |

### 2.6 별표 6: 학술연구용역 고시금액 미만 (ACADEMIC)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `학술연구용역 적격심사 추정가격 고시금액 미만` |
| sucsfbidLwltRate | `86.245` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_06` |

### 2.7 별표 7: 학술연구용역 고시금액 이상 (ACADEMIC)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상` |
| sucsfbidLwltRate | `82.495` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_07` |
| 특징 | 같은 ACADEMIC 타입이지만 별표 6과 다른 패턴. 길이가 긴 패턴이 우선 매칭되어야 함. |

### 2.8 별표 8: 폐기물처리용역 고시금액 미만 (WASTE)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `폐기물처리용역 적격심사 추정가격 고시금액미만` |
| sucsfbidLwltRate | `86.245` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_08` |

### 2.9 별표 9: 폐기물처리용역 고시금액 이상 (WASTE)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상` |
| sucsfbidLwltRate | `82.495` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_09` |
| 특징 | 패턴에 하이픈(`-`) 포함. normalize_pattern_string 이 하이픈을 제거하는지 검증. |

### 2.10 별표 10: 화물 육상운송용역 고시금액 미만 (FREIGHT)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `화물 육상운송용역 적격심사 추정가격 고시금액미만` |
| sucsfbidLwltRate | `86.245` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_10` |

### 2.11 별표 11: 화물 육상운송용역 고시금액 이상 (FREIGHT)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `화물 육상운송용역 적격심사 추정가격 5억원 미만 고시금액 이상` |
| sucsfbidLwltRate | `82.495` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_11` |

### 2.12 별표 12: 추정가격 2억원 미만인 용역 (GENERAL)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `추정가격 2억원 미만인 용역` |
| sucsfbidLwltRate | `87.745` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_12` |
| 특징 | GENERAL 타입 중 가장 표본이 많음(480건). 패턴이 간결하여 기타 별표와 혼동되지 않아야 함. |

### 2.13 별표 13: 추정가격 5억원 미만 2억원 이상인 용역 (GENERAL)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `추정가격 5억원 미만 2억원 이상인 용역` |
| sucsfbidLwltRate | `86.745` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_13` |

### 2.14 별표 14: 추정가격 30억원 미만 15억원 이상인 용역 (GENERAL)

| 항목 | 값 |
|------|------|
| sucsfbidMthdNm | `추정가격 30억원 미만 15억원 이상인 용역` |
| sucsfbidLwltRate | `82.995` |
| 기대 rule_id | `SERVC_QUAL_POST_20260526_ATTACH_14` |

---

## 3. 차단 경로 시나리오

### 3.1 NOT_SERVC -- 용역 카테고리가 Servc가 아님

| 항목 | 값 |
|------|------|
| category | `Thng` (물품) |
| sucsfbidMthdNm | 모든 값 무시 |
| 기대 차단 코드 | `NOT_SERVC` |
| 화면 표시 | "이 공고는 지원 범위 밖입니다" |

### 3.2 NON_PRED_PRICE -- 비예가 공고

| 항목 | 값 |
|------|------|
| category | `Servc` |
| prearngPrceDcsnMthdNm | `비예가` |
| 기대 차단 코드 | `NON_PRED_PRICE` |
| 화면 표시 | "비예가 공고는 예정가격이 없어 가격점수 산출 분모가 부재합니다" |

### 3.3 MANUAL_EVALUATION -- 관리규정외 수기심사

| 항목 | 값 |
|------|------|
| category | `Servc` |
| sucsfbidMthdNm | `적격심사제-관리규정외 수기심사(총점입력)` |
| 기대 차단 코드 | `MANUAL_EVALUATION` |
| 화면 표시 | "발주기관 자체 기준이 적용되므로 공고문 확인이 필요합니다" |

### 3.4 RULE_NOT_FOUND -- 매칭 실패

| 항목 | 값 |
|------|------|
| category | `Servc` |
| sucsfbidMthdNm | `알수없는특수용역적격심사방식` |
| 기대 차단 코드 | `RULE_NOT_FOUND` |
| 화면 표시 | "일치하는 일반용역 적격심사 별표를 찾을 수 없습니다" |

### 3.5 PRED_PRICE_UNAVAILABLE -- 예정가격 없음

| 항목 | 값 |
|------|------|
| category | `Servc` |
| base_amount | `None` |
| sucsfbidMthdNm | `시설분야용역 적격심사 추정가격 5억원 미만` |
| 기대 차단 코드 | `PRED_PRICE_UNAVAILABLE` |
| 특징 | 배점표가 있어도 기초금액/예정가격이 없으면 계산 차단 |

### 3.6 MISSING_SCORE_TABLE -- 배점표 미입력

| 항목 | 값 |
|------|------|
| score_table | `None` (B, k, T 셋 다 미입력) |
| 기대 차단 코드 | `MISSING_SCORE_TABLE` |
| 특징 | 규칙 판별과 하한율/최저투찰금액은 전달되나 점수 계열이 모두 None |

---

## 4. 점수 계산 시나리오

각 별표 유형에 대해 scoring 엔드포인트를 호출했을 때 점수 계산 결과도 보호한다.

| 시나리오 | 별표 | B/k/T | 입찰금액 | 기대 가격점수 | 기대 적격 여부 |
|---------|------|-------|---------|-------------|-------------|
| 별표1 기준시나리오 | ATTACH_01 | 20/2/95 | 407,448,800 | 2.98 | 불가 (총점 77.98 < 95) |
| 별표1 공고하한율구속 | ATTACH_01 | 20/2/95 | 449,000,000 | 19.60 | 가능 (총점 102.60 >= 95) |
| 별표2 보험 | ATTACH_02 | 30/2/90 | 480,000,000 | (server 계산) | (server 계산) |
| ... | ... | ... | ... | ... | ... |

(세부 점수는 결정론적 도메인 함수의 동작이 정본이며, 시나리오 문서는 매칭 규칙과 차단 경로에 집중한다.)

---

## 5. 회귀 테스트 매핑

| 시나리오 ID | 테스트 파일 | 테스트 함수 | 적용 별표 |
|------------|-----------|-----------|---------|
| SCEN-001 | test_evaluation_scoring.py | `test_post_20260526_rules_count` | 전별표 (등록 개수) |
| SCEN-002 | test_evaluation_scoring.py | `test_all_14_rules_have_correct_rates_and_metadata` | 전별표 (하한율) |
| SCEN-003~016 | test_evaluation_scoring.py | `test_each_star_pattern_resolves_correctly[별표1~14]` | 별표 1-14 각각 |
| SCEN-017~020 | test_evaluation_scoring.py | `test_block_when_*` | 차단 4종 |
| SCEN-021~022 | test_evaluation_scoring.py | `test_edge_category_none` / `test_edge_raw_data_none` | 에지 케이스 |
| SCEN-023~036 | test_evaluations_api.py | `test_each_star_analyze_returns_correct_rule[별표1~14]` | 별표 1-14 각각 |
| SCEN-037~042 | test_evaluations_api.py | `test_analyze_returns_blocked_result_with_reason_code[*]` | 차단 5종 |
| SCEN-043 | test_evaluations_api.py | `test_bid_without_pred_price_is_blocked` | PRED_PRICE_UNAVAILABLE |
| SCEN-044 | test_evaluations_api.py | `test_score_table_input_drives_server_calculation` | 별표1 (기존) |

---

## 6. 검증 방법

1. 단위 테스트: `python3 -m pytest tests/test_evaluation_scoring.py -v`
2. API 테스트: `python3 -m pytest tests/test_evaluations_api.py -v`
3. 화면 재현: 공고 상세 페이지에서 각 별표에 해당하는 `sucsfbidMthdNm`을 가진 공고를 열고
   같은 `qualification_input`을 입력하여 같은 `rule_id`, `lower_bound_rate`, `scenario_results`가
   나오는지 확인한다.
