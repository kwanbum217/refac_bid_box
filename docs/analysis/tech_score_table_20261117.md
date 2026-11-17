# 조달청 기술용역 적격심사 별표1 배점표·평탄 반영 (2026-11-17)

> **작성일**: 2026-11-17
> **작업**: `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT`(현행)·`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526`(개정 전)에 별표1 의 추정가격 구간별 가격배점한도 B·평점계수 k·적격통과점수 T·기준비율과 평탄 구간을 선언
> **값의 정본**: `data/reference/pps_tech_lwlt_pre_20260526.yaml` (조달청 기술용역 적격심사 세부기준 별표1)
> **판정**: candidate. `MISSING_SCORE_TABLE` 차단을 해소했고, 평탄 구간도 등록해 최상가 계산에 반영했다. 남은 위험은 9장에 적었다.

---

## 1. 결론

- 두 기술용역 규칙에 별표1 의 네 구간 B·k·T 와 기준비율을 넣었다. 규칙 선언만으로 배점표가 채워져 `MISSING_SCORE_TABLE` 로 막히지 않는다.
- 네 구간의 평탄 비율·점수도 `evaluation_flat_zones.py` 의 기술용역 전용 조회에 등록했다. 고시금액 경계가 연도별로 달라 `PriceBand.upper_bound` 대신 `resolve_score_params` 의 `price_band_index` 를 키로 쓴다. `/api/v1/evaluations/analyze` 와 `/api/v1/evaluations/recommend` 가 이 평탄을 가격점수·최상가에 반영한다.
- 낙찰하한율은 종전과 같다. 두 규칙의 `lwlt_rate` 는 `None` 이고, 공고의 `sucsfbidLwltRate` 만 유효 하한율로 쓴다.
- 2026-06-01 이후 기술용역 적격심사 공고 4,173건을 5단계로 재생한 결과, `MISSING_SCORE_TABLE` 이 **3,716건에서 0건**으로 줄었다. 다른 단계의 차단(수기심사 408건·비예가 49건)은 그대로다.
- 비가격 점수가 0 이거나 없을 때 기술용역과 일반용역은 같은 `PRICE_BOUNDS_UNRESOLVED` 차단을 낸다. 화면 표시 경로도 같아 코드를 바꾸지 않았다(7장).

---

## 2. 넣은 값

### 2.1 구간별 값

`data/reference/pps_tech_lwlt_pre_20260526.yaml` 의 `revisions[].attachments[별표 1].bands` 와 `boundary_reference` 를 그대로 옮겼다. 구간 표기는 원문의 이상·미만을 따른다.

| 원문 구간 | 추정가격 | B | k | T | 기준비율 (개정 전 / 현행) | 평탄 비율 (개정 전 / 현행) | 평탄 점수 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10억원 이상 | 30 | 1 | 92 | 88/100 / 90/100 | 96 / 98 | 22 |
| 2 | 10억원 미만 5억원 이상 | 50 | 2 | 95 | 88/100 / 90/100 | 90.5 / 92.5 | 45 |
| 3 | 5억원 미만 고시금액 이상 | 70 | 4 | 95 | 88/100 / 90/100 | 89.25 / 91.25 | 65 |
| 4 | 고시금액 미만 | 90 | 20 | 95 | 88/100 / 90/100 | 88.25 / 90.25 | 85 |

- 개정 전 규칙의 기준비율은 88/100, 현행 규칙은 90/100 이다. B·k·T 는 두 규칙이 같다.
- 통과점수 T 는 별표가 아니라 본문 제4조 제1항이 추정가격 10억원 기준으로 나눈다. 그래서 `threshold_bands` 는 10억원 미만 95점, 10억원 이상 92점 두 구간이다.
- 구간 순서는 코드에서 추정가격 오름차순(원문 구간 4 → 1)이다. 경계값은 상위 구간에 든다(10억원 정확히는 B=30, 5억원 정확히는 B=50, 고시금액 정확히는 B=70).

### 2.2 원문 증거

개정 전(조달청지침 제6352호 시행 2025-09-01·제654호 시행 2026-01-26):

- 구간 표기: `추정가격이 10억원 이상인 용역`, `추정가격이 10억원 미만 5억원 이상인 용역`, `추정가격이 5억원 미만 고시금액 이상인 용역`, `추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 용역`
- 산식: `평점=30-｜( 88/100 - 입찰가격/예정가격 )×100｜`, `평점=50-2×｜…｜`, `평점=70-4×｜…｜`, `평점=90-20×｜…｜`
- 평탄 문구: `입찰가격이 예정가격이하로서 100분의 96이상인 경우의 평점은 22점`, `90.5이상 45점`, `89.25이상 65점`, `88.25이상 85점`
- 통과점수: `추정가격이 10억원 이상인 용역은 92점, 추정가격이 10억원 미만인 용역은 95점`

현행(조달청지침 제5283호 시행 2026-05-26):

- 기준비율 네 구간 모두 `90`
- 평탄 문구: `98이상 22점`, `92.5이상 45점`, `91.25이상 65점`, `90.25이상 85점`
- `delta_from_pre`: `평점계수·배점한도·통과점수는 그대로다.`

YAML 키와 행:

| 값 | YAML 키 | 행 |
| --- | --- | --- |
| 개정 전 B·k·T·기준비율·평탄 | `revisions[notice_key=2025-6352].attachments[별표 1]` | 83~178 |
| 개정 전 B·k·T·기준비율·평탄 (제654호) | `revisions[notice_key=2026-654].attachments[별표 1]` | 180~275 |
| 현행 기준비율·평탄 | `boundary_reference` | 277~314 |
| 통과점수 근거 | `revisions[].pass_score_evidence` | 92~95, 191~194 |

### 2.3 고시금액 경계

고시금액은 연도별 국가계약 고시금액이다. 기존 `src/ml/notice_amount.py` 의 `notice_amount_for_year()` 를 그대로 쓴다. 일반용역 기관 규칙도 같은 함수를 쓴다.

| 연도 | 용역 고시금액 | 근거 |
| ---: | ---: | --- |
| 2021 | 210,000,000 | 기획재정부 고시 제2020-39호 |
| 2022 | 210,000,000 | 기획재정부 고시 제2020-39호 |
| 2023 | 220,000,000 | 기획재정부 고시 제2022-32호 |
| 2024 | 220,000,000 | 기획재정부 고시 제2022-32호 |
| 2025 | 230,000,000 | 기획재정부 고시 제2024-42호 |
| 2026 | 230,000,000 | 기획재정부 고시 제2024-42호 |

구간 선언은 2026년 값(230,000,000원)으로 두고, `resolve_score_params` 가 공고일 연도 값으로 첫 구간 상한을 바꿔 쓴다. 고정 230,000,000원을 쓰면 다음 공고가 잘못된 구간에 들어간다(읽기 전용 조회, `srvceDivNm=기술용역`·`sucsfbidMthdCd=낙030001`·추정가격 기준, 상한 추정).

| 연도 | 실제 경계 | 고정 230,000,000원 사용 시 잘못 분류될 수 있는 건수 |
| ---: | ---: | ---: |
| 2022 | 210,000,000 | 19 |
| 2023 | 220,000,000 | 190 |
| 2024 | 220,000,000 | 143 |
| 2025 | 230,000,000 | 0 |
| 2026 | 230,000,000 | 0 |

합계 352건이다. 이 가운데 일부는 정량 배점표 등 앞 단계에서 이미 막히므로 실제 계산 오류는 더 적다. 그래도 연도별 경계를 쓰는 편이 원문에 맞다. 평탄 조회도 같은 이유로 `PriceBand.upper_bound` 대신 구간 순서를 키로 쓴다(4장).

### 2.4 코드 위치

- B·k·T 선언: `src/app/services/evaluation_rules.py:1198-1320` (`_SERVC_TECH_SCORE_YAML`, `_servc_tech_price_bands`, `_servc_tech_threshold_bands`, 두 규칙)
- 연도별 고시금액 치환: `src/app/services/evaluation_rules.py:690` (`resolve_score_params`) 와 `src/app/services/evaluation_rules.py:1273-1287` (`_servc_tech_price_bands_for_announcement`)
- 평탄 데이터: `src/app/services/evaluation_flat_zones.py:672-774` (`_SERVC_TECH_FLAT_ZONES`, `servc_tech_flat_zone_for`, `servc_tech_flat_zone_entries`)
- 평탄 선택 연결: `src/app/api/v1/evaluations.py:299-332` (`_selected_flat_zone`), `src/app/api/v1/predictions.py:206-235` (`_flat_zone_for_bid`)
- 시험: `tests/test_tech_score_table_20261117.py`, `tests/test_evaluation_rules.py`, `tests/test_pps_flat_zones.py`

---

## 3. 적용 기간 판정

`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 는 코드상 공고일이 2026-05-26 미만인 모든 기술용역 공고에 쓰인다. 그 안에서 별표1 값이 같은 판만 배점표·평탄을 적용하고, 다른 판은 종전처럼 막는다.

| 판 | 시행일 | B·k·T·기준비율 | 평탄 | 코드 처리 | 근거 |
| --- | --- | --- | --- | --- | --- |
| 제5290호 | 2015-11-19 | 30억원 기준 T 85/90/95, 구간 1 이 10억~30억과 30억 이상으로 갈림 | 구간 1 96·20, 나머지 동일 | 적용하지 않음. `RULE_REGIME_MISMATCH` 로 규칙 판별 단계에서 차단 | `data/reference/pps_servc_tech_qual_history_2015_2022.yaml:25-118` |
| 제5460호 | 2017-11-01 | 위와 같음 | 위와 같음 | 〃 | 같은 파일 `:120-213` |
| 제1824호 | 2018-04-01 | B·k·T·기준비율은 같음 | 구간 1 평탄 비율 98 | 2022-11-01 이전이라 적용하지 않음 | 같은 파일 `:215-295` |
| 제919호 | 2019-04-01 | 위와 같음 | 위와 같음 | 〃 | 같은 파일 `:297-377` |
| 제7701호 | 2020-10-15 | B·k·T·기준비율·평탄 모두 개정 전 별표와 같음 | 〃 | 2022-11-01 이전이라 적용하지 않음(보수적 판정) | 같은 파일 `:379-459` |
| 제8983호 | 2022-11-01 | B·k·T·기준비율·평탄 모두 개정 전 별표와 같음 | 96/90.5/89.25/88.25 | 개정 전 규칙 적용 | 같은 파일 `:461-540`, `data/reference/pps_tech_lwlt_pre_20260526.yaml:126-129` |
| 제6352호 | 2025-09-01 | 〃 | 〃 | 개정 전 규칙 적용 | `data/reference/pps_tech_lwlt_pre_20260526.yaml:83-178` |
| 제654호 | 2026-01-26 | 〃 | 〃 | 개정 전 규칙 적용 | 같은 파일 `:180-275` |
| 제5283호 | 2026-05-26 | 기준비율 90, B·k·T 동일 | 98/92.5/91.25/90.25 | 현행 규칙 적용 | 같은 파일 `:277-314` |

- 2022-11-01 이전 공고는 PRE 규칙의 `effective_date` 보다 앞서므로 `_apply_rule_effective_date` 가 `RULE_REGIME_MISMATCH` 로 막는다. 배점표·평탄을 넣어도 이 차단은 그대로다(시험 `test_announcement_before_2022_11_01_stays_blocked_at_rule_resolution`).
- 제8983호와 제6352호·제654호는 B·k·T·기준비율·평탄이 같아 한 규칙으로 묶었다. 제7701호도 B·k·T 는 같지만, 원문 판본 대조 범위를 넓히지 않기 위해 2022-11-01 이전은 적용하지 않는다.
- 2026-05-26 경계는 공고일 기준이다. 2026-05-25 공고는 88/100 과 개정 전 평탄, 2026-05-26 공고는 90/100 과 현행 평탄을 쓴다(시험 `test_regime_boundary_switches_base_rate`).

---

## 4. 평탄 구간 반영

### 4.1 등록 방식

- 기존 `_FLAT_ZONES`(지방 규칙, `PriceBand.upper_bound` 키)와 `_PPS_FLAT_ZONES`(조달청 일반용역, B 5억·k 고시금액 두 축 키)는 기술용역의 10억 경계를 표현하지 못한다. 기술용역은 추정가격 4구간이고, 첫 구간 상한(고시금액)이 연도별로 달라 안정적인 upper_bound 키가 없다.
- 그래서 `src/app/services/evaluation_flat_zones.py` 에 기술용역 전용 `_SERVC_TECH_FLAT_ZONES` 를 추가했다. 키는 규칙 ID → `price_band_index`(추정가격 오름차순 0~3)이고, 값은 `FlatZone` 이다.
- `servc_tech_flat_zone_for(rule_id, band_index)` 가 그 조회를 담당한다. `src/app/api/v1/evaluations.py::_selected_flat_zone` 과 `src/app/api/v1/predictions.py::_flat_zone_for_bid` 가 `price_bands` 규칙이면 이 함수를 먼저 보고, 없으면 기존 `flat_zone_for` 로 넘어간다. 기존 지방·기관 규칙 경로는 호출 순서만 앞에 조회가 하나 붙을 뿐 결과가 같다.
- 기존 `flat_zone_entries()`·`pps_flat_zone_for`·`_FLAT_ZONES` 는 건드리지 않았다. `tests/test_flat_zone_scoring.py::TestFlatZoneLinkedRuleIds` 가 요구하는 "평탄 항목은 LOCAL_RULES·INSTITUTION_RULES 안에 있다"는 계약도 그대로다.
- 평탄값의 출처는 각 `FlatZone.source` 에 YAML 경로·키와 조달청지침 번호, 원문 평탄 문장을 적었다.

### 4.2 구간 매핑

| `price_band_index` | 추정가격 | 개정 전 평탄 | 현행 평탄 |
| ---: | --- | --- | --- |
| 0 | 고시금액 미만 | 0.8825 · 85점 | 0.9025 · 85점 |
| 1 | 5억원 미만 고시금액 이상 | 0.8925 · 65점 | 0.9125 · 65점 |
| 2 | 10억원 미만 5억원 이상 | 0.905 · 45점 | 0.925 · 45점 |
| 3 | 10억원 이상 | 0.96 · 22점 | 0.98 · 22점 |

### 4.3 적용 효과

`calculate_price_score` 의 산식(`B - k × |기준비율 - x| × 100`)만 쓰면 `x >= 평탄 비율` 구간에서 점수가 평탄 점수 아래로 내려간다. 평탄을 등록하면 그 구간이 고정된다.

현행(기준비율 0.90):

| 구간 | B·k | 평탄 비율·점수 | x=0.95 산식 | x=0.95 적용 | 차이 | x=1.00 산식 | x=1.00 적용 | 차이 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30·1 | 0.98·22 | 25.00 | 25.00 | 0 | 20.00 | 22 | 2 |
| 2 | 50·2 | 0.925·45 | 40.00 | 45 | 5 | 30.00 | 45 | 15 |
| 3 | 70·4 | 0.9125·65 | 50.00 | 65 | 15 | 30.00 | 65 | 35 |
| 4 | 90·20 | 0.9025·85 | -10.00 | 85 | 95 | -110.00 | 85 | 195 |

개정 전(기준비율 0.88):

| 구간 | B·k | 평탄 비율·점수 | x=0.95 산식 | x=0.95 적용 | 차이 | x=1.00 산식 | x=1.00 적용 | 차이 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30·1 | 0.96·22 | 23.00 | 23.00 | 0 | 18.00 | 22 | 4 |
| 2 | 50·2 | 0.905·45 | 36.00 | 45 | 9 | 26.00 | 45 | 19 |
| 3 | 70·4 | 0.8925·65 | 42.00 | 65 | 23 | 22.00 | 65 | 43 |
| 4 | 90·20 | 0.8825·85 | -50.00 | 85 | 135 | -150.00 | 85 | 235 |

- 낙찰하한율 근처(x ≈ 0.87~0.90)는 평탄 비율보다 낮아 산식과 적용값이 같다. 그래서 **최저 투찰금액(하한율 금액)은 평탄 등록 전후로 달라지지 않는다.**
- 차이는 기준비율 위쪽, 즉 통과 상한(최상가)에서 커진다. 예를 들어 현행 2구간(추정가격 6억원), T=95, 비가격 50점(필요 가격점수 45), 공고 하한율 87.495% 이면:
  - 평탄 없음: 통과 비율 상한 0.925 → 예정가격 612,000,000원 기준 최상가 566,100,000원
  - 평탄 적용: 평탄 점수 45가 필요점수 45를 충족해 상한 1.00 → 최상가 612,000,000원
  - 차이 약 45,900,000원(7.5%). 원 단위 격자·반올림에 따라 몇 원 달라질 수 있다.
- 시험은 `test_flat_zone_is_applied_to_max_bid_amount`(동일 조건에서 평탄 적용 최상가가 더 큼)와 `test_tech_analyze_applies_flat_zone_to_price_score`(투찰률 0.95에서 산식 40점 대신 평탄 45점)로 고정했다.

---

## 5. 효과 측정: MISSING_SCORE_TABLE 감소

`docs/analysis/score_table_coverage_20261117.md` 2.2절의 5단계 재생과 같은 순서로 2026-06-01 이후 기술용역 적격심사 공고를 변경 전(main)과 후로 셌다.

- 모집단: `Servc`, `sucsfbidMthdCd=낙030001`, `srvceDivNm=기술용역`, 2026-06-01 00:00 ~ 2026-11-18 00:00, 공고번호별 최신 차수, 취소공고 제외
- 재생 순서: (1) 규칙 판별 (2) 유효 낙찰하한율 (3) 예정가격 (4) 정량 배점표·구간 (5) B·k·T 확정
- 변경 전: `main` 브랜치의 `src/app/services/evaluation_rules.py` 를 `git show` 로 읽어 메모리에서 실행
- DB: `scripts/db_readonly_query.py` 로만 읽음. 쓰기 없음
- 스크립트: 일회성, 저장소에 커밋하지 않음

| 구분 | 건수 |
| --- | ---: |
| 조회 행 | 6,004 |
| 취소공고 제외 | 691 |
| 재생 공고 | 4,173 |
| 변경 전 `MISSING_SCORE_TABLE` | 3,716 |
| 변경 후 `MISSING_SCORE_TABLE` | **0** |
| 변경 전 `MANUAL_EVALUATION` | 408 |
| 변경 후 `MANUAL_EVALUATION` | 408 |
| 변경 전 `NON_PRED_PRICE` | 49 |
| 변경 후 `NON_PRED_PRICE` | 49 |
| 변경 후 계산 가능(`OK`) | 3,716 |

- 바뀐 3,716건은 전부 `MISSING_SCORE_TABLE` → `OK` 이고, 그 밖의 판정 변경은 0건이다.
- `docs/analysis/score_table_coverage_20261117.md` 는 현행 규칙 `MISSING_SCORE_TABLE` 을 3,712건으로 적었다. 이번 재생은 3,716건으로 4건 많다. 같은 규칙·같은 5단계이며, 문서 측정 시점 이후 수집된 공고가 포함된 차이다. 규칙 로직 차이가 아니다.
- 408건의 수기심사와 49건의 비예가는 1단계에서 막혀 5단계에 도달하지 않는다. 이번 변경으로 풀리지 않으며, 배점표 범위 밖이다.

---

## 6. 판정 비교

`scripts/judge_snapshot_diff.py` 로 main 기준 스냅샷과 변경 스냅샷을 비교했다. 기준일 2026-11-17, 12개월, `Servc`, 낙찰방법 코드 `낙030001` 이다.

| 항목 | 값 |
| --- | ---: |
| 기준 스냅샷 행 | 27,857 |
| 변경 스냅샷 행 | 27,857 |
| 바뀐 공고 | 0 |
| 판정 변경 | 0 |
| before 에만 있음 | 0 |
| after 에만 있음 | 0 |
| `--expect` 목록 | 0 |
| 종료 코드 | 0 |

- **0건은 이상 없음이 아니라 스냅샷의 기록 범위 때문이다.** `scripts/judge_snapshot_diff.py` 는 `collect_judgments` → `report_rule_coverage.classify_result` 로 **규칙 선택 결과만** 덤프한다. `_score_table`·`resolve_score_params` 의 B·k·T 확정과 평탄 선택은 스냅샷 열(scope·rule_id·block_code·공고 키·기관)에 들어가지 않는다.
- 기준 TSV 에 `rule_id` 가 두 기술용역 규칙이면서 `block_code=MISSING_SCORE_TABLE` 인 행이 없어 `--expect` 목록도 비었다. `judge_expect.txt` 는 0줄이다.
- 따라서 종료 코드 0 은 **규칙 선택 부작용이 없다**는 회귀 확인이다. 배점표·평탄 해소 자체는 5장의 5단계 재생과 `tests/test_tech_score_table_20261117.py` 로 확인했다.
- 같은 기준일·같은 12개월 창이라 낮 수집으로 새로 들어온 공고 차이는 없었다.

---

## 7. PRICE_BOUNDS_UNRESOLVED 동작 비교

회원 비가격 점수가 0 이거나 없을 때 기술용역 공고가 일반용역과 같은지 `evaluations.py` 경로로 확인했다.

| 항목 | 기술용역 | 일반용역 |
| --- | --- | --- |
| 적용 규칙 | `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | `SERVC_QUAL_POST_20260526_ATTACH_01` |
| B·k·T | 50·2·95 (추정가격 6억원) | 60·5·85 (추정가격 6억원) |
| 비가격 점수 | 0 | 0 |
| `/recommend` status | blocked | blocked |
| `blocked_reason` 코드 | `PRICE_BOUNDS_UNRESOLVED` | `PRICE_BOUNDS_UNRESOLVED` |
| `prediction.optimal_price` | 있음 | 있음 |
| `price_bounds` | 있음(status blocked) | 있음(status blocked) |

- 두 경우 모두 B(기술 50, 일반 60)보다 필요한 가격점수(T 95, 85)가 커서 통과 구간을 확정하지 못한다. 기술용역과 일반용역의 응답 모양과 차단 코드가 같다.
- 화면은 `src/app/templates/bids/detail.html::renderRecommendAmounts` 가 `data.blocked` 이면 `#prediction-result` 를 숨기고 `#recommend-blocked` 를 연다. `PRICE_BOUNDS_UNRESOLVED` 이고 `hasMemberQuantData(data)` 가 false 이면 `#recommend-member-missing` 도 함께 연다. 이 조건은 기술용역·일반용역이 같다.
- 따라서 **일반용역과 같게 맞출 코드 변경은 없다.** 기술용역은 비가격 배점표가 아직 등록되지 않아 `quant_score_table` 이 없고, 화면에서 정량 항목을 입력해 이 차단을 풀 수 없다는 점은 별도 과제다(9장).
- 시험 `test_price_bounds_unresolved_matches_general_service_without_non_price_score` 가 두 규칙의 차단 코드·비가격 0·예측가·price_bounds 존재를 함께 고정한다.

---

## 8. 시험

### 8.1 요구 항목 대응

| 항목 | 시험 |
| --- | --- |
| (a) 두 규칙 네 구간 B·k·T·기준비율이 YAML 과 같다 | `test_pre_rule_bands_match_reference_yaml`(제6352호·제654호), `test_current_rule_bands_match_reference_yaml` |
| (b) 10억·5억·고시금액 경계값이 올바른 구간에 든다 | `test_band_boundaries_follow_printed_lower_inclusive_upper_exclusive`, `test_pre_rule_notice_boundary_uses_announcement_year_not_fixed_2026_value` |
| (c) 2026-05-26 전후가 88·90 기준비율을 쓴다 | `test_regime_boundary_switches_base_rate` |
| (d) `MISSING_SCORE_TABLE` 로 막히지 않고 최저가·최상가가 계산된다 | `test_score_table_resolves_without_user_input`, `test_tech_price_bounds_are_computed_with_declared_table`, `test_tech_analyze_is_not_blocked_by_missing_score_table`, `test_tech_recommend_is_not_blocked_by_missing_score_table` |
| (e) 2022-11-01 이전 공고 처리 | `test_announcement_before_2022_11_01_stays_blocked_at_rule_resolution`, `test_announcement_on_2022_11_01_uses_pre_rule_bands` |
| (f) 낙찰하한율은 여전히 공고 `sucsfbidLwltRate` | `test_tech_lwlt_still_comes_from_announcement_rate` |
| 평탄 값·출처·구간 순서 | `test_flat_zones_match_reference_yaml`, `TestTechFlatZoneData`(4개) |
| 평탄이 최상가·가격점수에 반영 | `test_flat_zone_is_applied_to_max_bid_amount`, `test_tech_analyze_applies_flat_zone_to_price_score` |
| predictions·evaluations 최저가·최상가 일치 | `test_tech_price_bounds_match_between_predictions_and_evaluations` |
| 비가격 0 일 때 일반용역과 동일 | `test_price_bounds_unresolved_matches_general_service_without_non_price_score` |
| 기존 일반용역 평탄 동작 불변 | `tests/test_flat_zone_scoring.py`, `tests/test_flat_zone_rest.py`, `tests/test_pps_flat_zones.py` |

### 8.2 실행 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_tech_score_table_20261117.py tests/test_evaluation_rules.py tests/test_evaluation_scoring.py tests/test_evaluation_recommend.py -q` | `114 passed` |
| `uv run pytest tests/test_predictions_api.py tests/test_predictions_score_verification.py tests/test_tech_score_table_20261117.py tests/test_pps_flat_zones.py tests/test_evaluations_api.py tests/test_evaluation_recommend.py tests/test_evaluation_scoring.py tests/test_evaluation_rules.py -q` | `224 passed, 1 skipped` |
| `uv run pytest tests/ -q -m 'not data_assets'` | `11160 passed, 41 skipped, 3 deselected, 2 xfailed` (285.77s) |
| `uv run mypy src` | `Success: no issues found in 152 source files` |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 (exit 0) |
| `uv run python scripts/judge_snapshot_diff.py diff ... --expect ...` | 바뀐 공고 0건, 기대 목록 0건 일치, exit 0 |
| 5단계 재생(2026-06-01 이후 기술용역) | `MISSING_SCORE_TABLE` 3,716 → 0, 그 밖의 판정 변경 0 |

### 8.3 기존 시험 변경

- `tests/test_pps_flat_zones.py::test_excluded_rules_have_no_flat_data` 에서 기술용역 제외 항목을 뺐다. 제외 사유였던 "평탄 문장 귀속 미확인" 이 YAML 원문 확인으로 해소됐기 때문이다.
- 같은 파일에 `TestTechFlatZoneData` 를 추가해 두 규칙 4구간의 값·출처·산식 일치를 고정했다.
- 기술용역의 배점표 미확인을 단언하던 다른 기존 시험은 없었다. `tests/test_flat_zone_scoring.py` 의 평탄 항목-LOCAL/INSTITUTION 연결 계약은 건드리지 않았고 그대로 통과한다.
- 새 시험 파일 `tests/test_evaluation_rules.py` 는 규칙 레지스트리 공통 계약(구간 목록·출처·일반용역 경로 불변)을 고정한다.

---

## 9. 남은 위험

- `/api/v1/evaluations/recommend` 의 `price_bounds` 와 `/api/v1/predictions/predict-price` 의 `score_verdict.effective_amount_low/high` 는 같은 기술용역 공고에서 같은 최저가·최상가를 낸다. 시험 `test_tech_price_bounds_match_between_predictions_and_evaluations` 가 같은 공고·같은 B·k·T·비가격 50점에서 두 경로의 유효 금액 하한·상한을 대조한다.
- `/recommend` 는 기술용역 비가격 배점표가 아직 등록되지 않아 비가격 0점으로 계산한다. T=95 이고 B 최대 90 이므로 비가격 점수가 없으면 `PRICE_BOUNDS_UNRESOLVED` 가 된다. 일반용역과 같은 차단이지만, 기술용역 화면에서는 정량 항목을 입력해 풀 수 없다. 비가격 배점표 등록은 후속 과제다.
- 공고일을 읽지 못하면 고시금액 경계와 평탄 구간 판정은 선언값인 2026년 230,000,000원 기준이 된다. 기술용역 규칙 판별은 공고일이 있어야 PRE/현행을 가르므로, 날짜가 없는 공고는 현행 규칙으로 간다.
- 2018-04-01 ~ 2022-10-31 판은 B·k·T 가 같지만, 원문 판본 대조 범위를 넓히지 않기 위해 2022-11-01 이전은 적용하지 않는다. 이 기간 공고는 `RULE_REGIME_MISMATCH` 로 남는다.

---

## 10. 근거 파일

- `data/reference/pps_tech_lwlt_pre_20260526.yaml` — 개정 전 제6352호·제654호 별표1, 현행 제5283호 경계 참조
- `data/reference/pps_servc_tech_qual_history_2015_2022.yaml` — 2015~2022 시행판과 제8983호
- `docs/analysis/score_table_coverage_20261117.md` — `MISSING_SCORE_TABLE` 분포와 확보 효과
- `docs/context/CURRENT_STATE.md` — 데이터 무손실 원칙
