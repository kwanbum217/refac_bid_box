# 조달청 기술용역 적격심사 별표1 배점표 반영 (2026-11-17)

> **작성일**: 2026-11-17
> **작업**: `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT`(현행)·`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526`(개정 전)에 별표1 의 추정가격 구간별 가격배점한도 B·평점계수 k·적격통과점수 T·기준비율을 선언
> **값의 정본**: `data/reference/pps_tech_lwlt_pre_20260526.yaml` (조달청 기술용역 적격심사 세부기준 별표1)
> **판정**: candidate. `MISSING_SCORE_TABLE` 차단은 해소했다. 평탄 비율은 규칙 평탄 구간 데이터 미등록으로 계산에 넣지 않았고, 그 영향은 4장에 적었다.

---

## 1. 결론

- 두 기술용역 규칙에 별표1 의 네 구간 B·k·T 와 기준비율을 넣었다. 규칙 선언만으로 배점표가 채워져 `MISSING_SCORE_TABLE` 로 막히지 않는다.
- `/api/v1/evaluations/analyze` 는 기술용역 공고에서 가격점수와 하단·기준·상단 시나리오 점수를 계산한다. `/api/v1/evaluations/recommend` 도 선언 배점표 B·k·T 를 응답한다.
- 낙찰하한율은 종전과 같다. 두 규칙의 `lwlt_rate` 는 `None` 이고, 공고의 `sucsfbidLwltRate` 만 유효 하한율로 쓴다.
- 평탄 비율(개정 전 96/90.5/89.25/88.25, 현행 98/92.5/91.25/90.25)과 평탄 점수(22/45/65/85)는 값은 확인했으나 계산에 넣지 않았다. 기술용역은 평탄 구간 데이터를 등록하지 않는 것이 기존 시험 계약이며(`tests/test_pps_flat_zones.py::test_excluded_rules_have_no_flat_data`), 이번 작업의 쓰기 허용 범위에 평탄 구간 데이터 모듈이 없기 때문이다. 영향은 4장에 정량화했다.
- 평탄을 넣지 않아도 **낙찰하한율 근처의 최저 투찰금액은 달라지지 않는다**. 평탄 구간은 기준비율 위쪽, 즉 하한율보다 훨씬 높은 투찰률에서만 발동한다.

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

합계 352건이다. 이 가운데 일부는 정량 배점표 등 앞 단계에서 이미 막히므로 실제 계산 오류는 더 적다. 그래도 연도별 경계를 쓰는 편이 원문에 맞다.

### 2.4 코드 위치

- 선언: `src/app/services/evaluation_rules.py:1198-1320` (`_SERVC_TECH_SCORE_YAML`, `_servc_tech_price_bands`, `_servc_tech_threshold_bands`, 두 규칙)
- 연도별 고시금액 치환: `src/app/services/evaluation_rules.py:690` (`resolve_score_params`) 와 `src/app/services/evaluation_rules.py:1273-1287` (`_servc_tech_price_bands_for_announcement`)
- 시험: `tests/test_tech_score_table_20261117.py`, `tests/test_evaluation_rules.py`

---

## 3. 적용 기간 판정

`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 는 코드상 공고일이 2026-05-26 미만인 모든 기술용역 공고에 쓰인다. 그 안에서 별표1 값이 같은 판만 배점표를 적용하고, 다른 판은 종전처럼 막는다.

| 판 | 시행일 | B·k·T·기준비율 | 코드 처리 | 근거 |
| --- | --- | --- | --- | --- |
| 제5290호 | 2015-11-19 | 30억원 기준 T 85/90/95, 구간 1 이 10억~30억과 30억 이상으로 갈림 | 적용하지 않음. `RULE_REGIME_MISMATCH` 로 규칙 판별 단계에서 차단 | `data/reference/pps_servc_tech_qual_history_2015_2022.yaml:25-118` |
| 제5460호 | 2017-11-01 | 위와 같음 | 〃 | 같은 파일 `:120-213` |
| 제1824호 | 2018-04-01 | B·k·T·기준비율은 같으나 구간 1 평탄 비율이 98 | 2022-11-01 이전이라 적용하지 않음 | 같은 파일 `:215-295` |
| 제919호 | 2019-04-01 | 위와 같음 | 〃 | 같은 파일 `:297-377` |
| 제7701호 | 2020-10-15 | B·k·T·기준비율·평탄 모두 개정 전 별표와 같음 | 2022-11-01 이전이라 적용하지 않음(보수적 판정) | 같은 파일 `:379-459` |
| 제8983호 | 2022-11-01 | B·k·T·기준비율·평탄 모두 개정 전 별표와 같음 | 개정 전 규칙 적용 | 같은 파일 `:461-540`, `data/reference/pps_tech_lwlt_pre_20260526.yaml:126-129` |
| 제6352호 | 2025-09-01 | 〃 | 개정 전 규칙 적용 | `data/reference/pps_tech_lwlt_pre_20260526.yaml:83-178` |
| 제654호 | 2026-01-26 | 〃 | 개정 전 규칙 적용 | 같은 파일 `:180-275` |
| 제5283호 | 2026-05-26 | 기준비율 90, 평탄 비율만 2%p 상승 | 현행 규칙 적용 | 같은 파일 `:277-314` |

- 2022-11-01 이전 공고는 PRE 규칙의 `effective_date` 보다 앞서므로 `_apply_rule_effective_date` 가 `RULE_REGIME_MISMATCH` 로 막는다. 배점표를 넣어도 이 차단은 그대로다(시험 `test_announcement_before_2022_11_01_stays_blocked_at_rule_resolution`).
- 제8983호와 제6352호·제654호는 B·k·T·기준비율이 같아 한 규칙으로 묶었다. 제7701호도 값은 같지만, 원문 판본 대조 범위를 넓히지 않기 위해 2022-11-01 이전은 적용하지 않는다.
- 2026-05-26 경계는 공고일 기준이다. 2026-05-25 공고는 88/100, 2026-05-26 공고는 90/100 을 쓴다(시험 `test_regime_boundary_switches_base_rate`).

---

## 4. 평탄 비율 미적용과 영향

### 4.1 왜 넣지 않았나

- 평탄 처리는 이미 있다. `ScoreTable.flat_ratio`·`flat_score` 와 `evaluation_flat_zones.flat_zone_for`·`pps_flat_zone_for` 가 그 역할을 한다.
- 그러나 기술용역은 평탄 구간 데이터를 등록하지 않는 것이 기존 계약이다. `tests/test_pps_flat_zones.py::test_excluded_rules_have_no_flat_data` 가 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` 에 평탄 데이터가 없음을 단언한다.
- 이번 작업의 쓰기 허용 범위는 `src/app/services/evaluation_rules.py` 와 시험·보고서뿐이라, 평탄 구간 데이터 모듈(`src/app/services/evaluation_flat_zones.py`)에 기술용역 항목을 추가할 수 없다. 새 계산식을 임의로 만들지 않고 B·k·T 만 넣었다.
- 평탄 비율과 평탄 점수는 YAML 원문에 있으므로, 평탄 구간 데이터를 등록하는 후속 작업에서 그대로 쓸 수 있다.

### 4.2 계산 차이

평탄이 없으면 `x >= 평탄 비율` 구간에서 산식값이 평탄 점수 아래로 내려간다. 아래 표는 `calculate_price_score` 의 산식(`B - k × |기준비율 - x| × 100`)으로 계산한 값이다.

현행(기준비율 0.90):

| 구간 | B·k | 평탄 비율·점수 | x=0.95 산식 | x=0.95 평탄 | 차이 | x=1.00 산식 | x=1.00 평탄 | 차이 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30·1 | 0.98·22 | 25.00 | 25.00 | 0 | 20.00 | 22 | 2 |
| 2 | 50·2 | 0.925·45 | 40.00 | 45 | 5 | 30.00 | 45 | 15 |
| 3 | 70·4 | 0.9125·65 | 50.00 | 65 | 15 | 30.00 | 65 | 35 |
| 4 | 90·20 | 0.9025·85 | -10.00 | 85 | 95 | -110.00 | 85 | 195 |

개정 전(기준비율 0.88):

| 구간 | B·k | 평탄 비율·점수 | x=0.95 산식 | x=0.95 평탄 | 차이 | x=1.00 산식 | x=1.00 평탄 | 차이 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30·1 | 0.96·22 | 23.00 | 23.00 | 0 | 18.00 | 22 | 4 |
| 2 | 50·2 | 0.905·45 | 36.00 | 45 | 9 | 26.00 | 45 | 19 |
| 3 | 70·4 | 0.8925·65 | 42.00 | 65 | 23 | 22.00 | 65 | 43 |
| 4 | 90·20 | 0.8825·85 | -50.00 | 85 | 135 | -150.00 | 85 | 235 |

- 낙찰하한율 근처(x ≈ 0.87~0.90)는 평탄 비율보다 낮아 두 계산이 같다. 그래서 **최저 투찰금액(하한율 금액)은 달라지지 않는다.**
- 차이는 기준비율 위쪽, 즉 통과 상한(최상가)을 계산할 때 커진다. 예를 들어 현행 2구간(추정가격 6억원), T=95, 비가격 50점(필요 가격점수 45), 공고 하한율 87.495% 이면:
  - 평탄 없음: 통과 비율 상한 0.925 → 예정가격 612,000,000원 기준 최상가 566,100,000원
  - 평탄 있음: 평탄 점수 45가 필요점수 45를 충족해 상한 1.00 → 최상가 612,000,000원
  - 차이 약 45,900,000원(7.5%). 원 단위 격자·반올림에 따라 몇 원 달라질 수 있다.
- 반대로 1구간처럼 평탄 점수가 필요점수보다 낮으면 평탄이 있어도 통과 상한이 넓어지지 않는다.

### 4.3 남은 위험

- 평탄을 넣지 않아 **최상가(통과 상한)가 실제보다 낮게** 나올 수 있다. 최저가·낙찰하한율 판단에는 영향이 없다.
- `/api/v1/evaluations/recommend` 는 기술용역 정량(비가격) 배점표가 아직 등록되지 않아 비가격 0점으로 계산한다. T=95 이고 B 최대 90 이므로 비가격 점수가 없으면 `PRICE_BOUNDS_UNRESOLVED` 가 될 수 있다. 이는 배점표 미확인이 아니라 비가격 배점표 부재 때문이며, 이번 작업 범위 밖이다. `/api/v1/evaluations/analyze` 는 가격점수와 시나리오 점수를 계산한다.
- 공고일을 읽지 못하면 고시금액 경계는 선언값인 2026년 230,000,000원을 쓴다. 기술용역 규칙 판별은 공고일이 있어야 PRE/현행을 가르므로, 날짜가 없는 공고는 현행 규칙으로 가고 2026년 값을 쓴다.

---

## 5. 판정 비교

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

- 기준 TSV 에 `rule_id` 가 두 기술용역 규칙이면서 `block_code=MISSING_SCORE_TABLE` 인 행이 없어 기대 목록이 비었다. 이 스냅샷은 규칙 판별 결과만 담고 배점표 해소 여부는 담지 않는다(`scripts/report_rule_coverage.py::classify_result`). 그래서 0건 변경은 **규칙 판별 부작용이 없다**는 회귀 확인이지, 배점표 해소 자체의 확인은 아니다.
- 배점표 해소는 `tests/test_tech_score_table_20261117.py::test_tech_analyze_is_not_blocked_by_missing_score_table` 와 `::test_score_table_resolves_without_user_input` 로 확인했다.
- 같은 기준일·같은 12개월 창이라 낮 수집으로 새로 들어온 공고 차이는 없었다.

---

## 6. 시험

### 6.1 요구 항목 대응

| 항목 | 시험 |
| --- | --- |
| (a) 두 규칙 네 구간 B·k·T·기준비율이 YAML 과 같다 | `test_pre_rule_bands_match_reference_yaml`(제6352호·제654호), `test_current_rule_bands_match_reference_yaml` |
| (b) 10억·5억·고시금액 경계값이 올바른 구간에 든다 | `test_band_boundaries_follow_printed_lower_inclusive_upper_exclusive`, `test_pre_rule_notice_boundary_uses_announcement_year_not_fixed_2026_value` |
| (c) 2026-05-26 전후가 88·90 기준비율을 쓴다 | `test_regime_boundary_switches_base_rate` |
| (d) `MISSING_SCORE_TABLE` 로 막히지 않고 최저가·최상가가 계산된다 | `test_score_table_resolves_without_user_input`, `test_tech_price_bounds_are_computed_with_declared_table`, `test_tech_analyze_is_not_blocked_by_missing_score_table`, `test_tech_recommend_is_not_blocked_by_missing_score_table` |
| (e) 2022-11-01 이전 공고 처리 | `test_announcement_before_2022_11_01_stays_blocked_at_rule_resolution`, `test_announcement_on_2022_11_01_uses_pre_rule_bands` |
| (f) 낙찰하한율은 여전히 공고 `sucsfbidLwltRate` | `test_tech_lwlt_still_comes_from_announcement_rate` |

### 6.2 실행 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_tech_score_table_20261117.py tests/test_evaluation_rules.py tests/test_evaluation_scoring.py tests/test_evaluation_recommend.py -q` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets'` | `11148 passed, 41 skipped, 3 deselected, 2 xfailed` (297.96s) |
| `uv run mypy src` | `Success: no issues found in 152 source files` |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |

### 6.3 기존 시험 변경

기술용역의 배점표 미확인을 단언하던 기존 시험은 없었다. `tests/test_pps_flat_zones.py` 는 기술용역에 평탄 데이터가 없다는 것만 단언하며, 이번 변경과 충돌하지 않아 고치지 않았다. 새 시험 파일 `tests/test_evaluation_rules.py` 는 규칙 레지스트리 공통 계약(구간 목록·출처·일반용역 경로 불변)을 고정한다.

---

## 7. 근거 파일

- `data/reference/pps_tech_lwlt_pre_20260526.yaml` — 개정 전 제6352호·제654호 별표1, 현행 제5283호 경계 참조
- `data/reference/pps_servc_tech_qual_history_2015_2022.yaml` — 2015~2022 시행판과 제8983호
- `docs/analysis/score_table_coverage_20261117.md` — `MISSING_SCORE_TABLE` 분포와 확보 효과
- `docs/context/CURRENT_STATE.md` — 데이터 무손실 원칙
