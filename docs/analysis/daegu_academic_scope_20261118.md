# 대구광역시 학술연구 공고의 시·도 예규 적용범위 배제 적용 (2026-11-18)

> **작업**: Orca Task `task_2adccfff5665` (builder, Run `run_b68a3b16b660`)
> **정본**: `.orca/capsules/task_daegu_academic_scope_20261118/capsule.yaml`
> **변경 비교 기준**: `kwanbum217/orca-integ-1118e` (3445ed5f)

## 1. 변경 요약

대구광역시(시·도 코드 27)처럼 시·도 예규가 "일반용역" 정의에서 학술용역을 제외한 지역의
학술연구 공고를 `ACADEMIC` 에서 `GENERAL/UNRESOLVED` 로 되돌려 단순노무 단독 차단
(`LOCAL_SIMPLE_LABOR_ONLY_REASON`)으로 보내지 않습니다. `LOCAL_RULE_NOT_FOUND` 와
적용범위 배제 사유를 돌려 기존 행안부 예규 제2장의2 [별표 4] 학술연구용역 띠
구제(`select_mois_academic_band_rule`)가 계산하게 했습니다.

- `evaluation_rules.py`: `LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES = frozenset({"27"})`,
  `LOCAL_ACADEMIC_SCOPE_EXCLUDED_REASON` 추가. `_select_local_rule` 에서 `ACADEMIC` +
  `PROCUREMENT_CLASS` + 행안부 학술 띠 선택 가능 + 지역에 `ACADEMIC`·`GENERAL` 별표 없음 +
  배제 지역이면 두 되돌림 대신 `LOCAL_RULE_NOT_FOUND` 를 돌려줍니다. 새 rule id·규칙 값은
  만들지 않았습니다.
- `tests/test_daegu_academic_scope_20261118.py` 신규 12건.
- `tests/test_method_cross_check_20261107.py`: 코디네이터 승인으로 D18 시험에서 1억미만
  케이스를 빼고, 같은 입력이 `SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E` 로 계산됨을
  단언하는 시험을 분리했습니다. band 표기 차단 단언은 그대로입니다.

## 2. 원문 근거

- `data/sources/qualification/files/daegu/d876df81b09d_elis_daegu_008.txt:156` (예규 제238호,
  시행 2026-05-11), 같은 조문의 예규 제223호 판
  `data/sources/qualification/files/daegu/856673076d70_elis_daegu_main.txt:158`:
  제2조 제1호 `"일반용역"이란 ... "기술용역과 학술용역 이외의 용역"을 말한다.`
- 두 대표 공고문은 행안부 [별표 4] 학술연구용역 1억원 미만(낙찰하한율 80.495%, 종합평점
  85점)을 지목합니다. 정리는 `docs/analysis/blocked_decision_daegu_20261118.md` 3.1~3.3절.

## 3. 경계

| 경계 | 처리 |
| --- | --- |
| (가) 대구 이외 지역 | 새 분기 미적용, 종전 `LOCAL_SERVICE_TYPE_UNRESOLVED`/`LOCAL_RULE_NOT_FOUND` 유지 |
| (나) 단순노무 표기·선택, 폐기물 | `ACADEMIC` 확정 전에 갈려 종전 대구 별표 유지 |
| (다) 학술이 아닌 대구 일반 공고 | `GENERAL/UNRESOLVED` 되돌림과 D18 차단 그대로 |
| (라) 국가계약(NATIONAL) | 시·도 분기와 행안부 구제 모두 미적용 |
| (마) 공고 명시 기준 라우팅 | 대구 학술 표기는 조달청·환경부 명시 표기와 겹치지 않아 종전 경로 유지 |
| band 표기(`2억미만 1억이상`) | 되돌림을 바꾸지 않고 D18 차단 유지(구제가 `RULE_NOT_FOUND` 만 받음) |

## 4. 판정 비교 (스냅숏은 커밋하지 않음)

```sh
uv run python scripts/judge_snapshot_diff.py dump --months 24 --as-of 2026-11-18 --output /tmp/after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/judge_base_g_20261118.tsv /tmp/after.tsv --expect /tmp/expect.txt
```

```
공고 before 51357건, after 51357건
바뀐 공고 3건(판정 변경 3건, before 만 0건, after 만 0건)
  [판정 변경] R25BK00801493 000  block_code: LOCAL_SERVICE_TYPE_UNRESOLVED -> RULE_REGIME_MISMATCH
  [판정 변경] R26BK01270603 000  scope: BLOCKED -> PPS_DEFAULT  rule_id: - -> SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E  block_code: LOCAL_SERVICE_TYPE_UNRESOLVED -> -
  [판정 변경] R26BK01724914 000  scope: BLOCKED -> PPS_DEFAULT  rule_id: - -> SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E  block_code: LOCAL_SERVICE_TYPE_UNRESOLVED -> -
[expect] 일치: 3건
```

`R25BK00801493`(대구광역시, 2025-04-22, 추정가격 2억이상)은 같은 조건에 맞는 유일한 다른
공고이며, 행안부 [별표 4] 시행일(2025-07-01) 전이라 계산 대신 `RULE_REGIME_MISMATCH` 로
막힙니다(차단 유지). 같은 기준 스냅숏의 대구 `LOCAL_SERVICE_TYPE_UNRESOLVED` 4건 중
`R25BK00704741` 은 band 표기라 종전 D18 차단을 유지했습니다. `only_before`/`only_after` 0건.

## 5. 검증

- 신규: `uv run pytest -q -m 'not data_assets and not e2e' tests/test_daegu_academic_scope_20261118.py` -> 12 passed
- 전량: `uv run pytest -q -m 'not data_assets and not e2e' tests/` -> 11243 passed, 36 skipped, 35 deselected, 2 xfailed
- `uv run mypy src` -> Success (152 files), `python3 scripts/validate_agent_rules.py --quiet` -> 22/22 PASS

## 6. 남은 것

없음. 다른 시·도에 같은 "일반용역 정의 학술 제외" 조항이 있는지는 조사하지 않았고, 상수에
지역을 추가하려면 원문 파일·줄 근거가 필요합니다.
