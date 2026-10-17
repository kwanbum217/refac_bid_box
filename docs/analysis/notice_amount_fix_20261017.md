# 규칙용 용역 고시금액 2021~2022 년 정정 (2026-10-17)

> 작성일: 2026-10-17
> Task: task_20a8517a29db
> 브랜치: kwanbum217/orca-notice-amount-fix

## 요약

규칙(적격심사 배점표)이 쓰는 용역 고시금액에 2021~2022 년 값 210,000,000 원(기획재정부
고시 제2020-39호, 2020-12-30 고시, 시행 2021-01-01~2022-12-31)을 넣었습니다. 기존 표에
그 해가 없어 `notice_amount_for_year` 가 기본값 220,000,000 원으로 떨어지던 것을 원문
값으로 바로잡았습니다. ML 특징이 쓰는 값과 표는 손대지 않았습니다.

---

## 바꾼 표

`src/ml/notice_amount.py` 에 규칙 전용 표 `RULE_NOTICE_AMOUNT_BY_YEAR` 를 새로 두고
`notice_amount_for_year` 가 그 표를 읽도록 했습니다. ML 특징 전용 표
`NOTICE_AMOUNT_BY_YEAR` 와 `DEFAULT_NOTICE_AMOUNT` 는 값·이름을 그대로 두고 용도를
주석으로 못박았습니다.

| 연도 | 규칙용 `RULE_NOTICE_AMOUNT_BY_YEAR` | ML 특징용 `NOTICE_AMOUNT_BY_YEAR` | 근거 |
| --- | --- | --- | --- |
| 2021 | 210,000,000 | 없음(기본값 220,000,000) | 기획재정부 고시 제2020-39호(2020-12-30) |
| 2022 | 210,000,000 | 없음(기본값 220,000,000) | 기획재정부 고시 제2020-39호(2020-12-30) |
| 2023 | 220,000,000 | 220,000,000 | 기획재정부 고시 제2022-32호(2022-12-30) |
| 2024 | 220,000,000 | 220,000,000 | 기획재정부 고시 제2022-32호(2022-12-30) |
| 2025 | 230,000,000 | 230,000,000 | 기획재정부 고시 제2024-42호(2024-12-24) |
| 2026 | 230,000,000 | 230,000,000 | 기획재정부 고시 제2024-42호(2024-12-24) |
| 그 밖 | 220,000,000(규칙용 기본값) | 220,000,000(ML 기본값) | 기존 동작 유지 |

---

## 소비처별 영향

| 소비처 | 표/함수 | 영향 |
| --- | --- | --- |
| 규칙 배점표(`src/app/services/evaluation_rules.py`) | `notice_amount_for_year` | 2021~2022 년 공고에서 고시금액 경계가 2.1억으로 바뀜 |
| 이력 매핑(`scripts/map_past_criteria_to_rules.py`) 301행 | `history_notice_amount_for_year` | 2021~2022 년 값이 2.1억으로 확정됨 |
| 이력 매핑 376행(서빙 경로) | `notice_amount_for_year` | 2021~2022 년 값이 2.1억으로 확정됨 |
| 이력 레지스트리 생성(`scripts/build_pps_history_rules.py`) | `NOTICE_AMOUNT_BY_YEAR` | 2021, 2022 를 출처와 함께 추가, 생성물 재생성 |
| ML 특징(`src/ml/features.py`) | `NOTICE_AMOUNT_BY_YEAR`, `DEFAULT_NOTICE_AMOUNT` | 변경 없음. `notice_amt_ratio`, `is_over_notice_amt` 는 그대로 |

`src/ml/features.py` 는 diff 에 없고, `tests/test_score_param_band_selection.py` 의
`test_features_notice_amount_values_remain_unchanged` 단정(2021 -> 220,000,000 포함)도
그대로입니다.

---

## 고친 시험

| 파일 | 시험 | 내용 |
| --- | --- | --- |
| `tests/test_notice_amount.py`(신규) | `test_rule_notice_amount_includes_2021_and_2022` 외 4건 | 규칙용 2021·2022 = 2.1억, 2023~2026 = 기존 값, 표에 없는 해 기본값 2.2억, ML 표에 2021·2022 키 없음 |
| `tests/test_evaluation_rules_history.py` | `test_notice_amount_only_evidenced_years` | 2021·2022 = 2.1억, 2023 = 2.2억, 2019~2020 = None 으로 수정 |
| `tests/test_map_past_criteria_to_rules.py` | `test_pre_2023_05_unknown_notice_amount_is_not_guessed` | 미확정 단정을 2019~2020 년으로 확장 |
| `tests/test_map_past_criteria_to_rules.py`(신규) | `test_pre_2023_05_evidenced_notice_amount_resolves` | 2021~2022 년 이력 규칙이 확정됨을 확인 |
| `tests/test_evaluation_rules_history.py` | `test_committed_module_matches_yaml_render`/`_build_check_mode_passes` | 생성물이 재실행 결과와 같음을 유지 |

---

## 남은 일

| 항목 | 사유 |
| --- | --- |
| ML 특징 값 정정(2021~2022 -> 2.1억) | 특징 정의가 바뀌므로 재학습·승격 판단과 함께 별도 Task 로 다룸 |
| 2027 년 고시금액 반영 | 아직 미고시. 고시되면 규칙용 표와 ML 표 정정을 함께 판단 |
| 2024~2026 년 규칙용 표 확장 | 이력 레지스트리 구간(2015~2023-04) 밖이라 이번 범위에서 불필요 |
