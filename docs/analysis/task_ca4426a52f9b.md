# Task 분석 및 완료 보고서: task_ca4426a52f9b

> **작성일**: 2026-09-04
> **Task ID**: `task_ca4426a52f9b`
> **Dispatch ID**: `ctx_e4c747a1b622`
> **작업 역할**: Builder
> **목표**: 공고 금액 집계를 질의 시점 JSON 파싱에서 base_amount 컬럼 기반으로 전환하고, 적재 경로의 금액 파싱을 Decimal 로 통일하며 범위를 벗어난 값이 조용히 클램프되지 않게 한다. 집계 산출값은 바뀌지 않아야 한다.

---

## 1. 작업 개요 및 변경 내역

| 대상 파일 | 주요 변경 내용 |
| --- | --- |
| [`../../src/app/services/dashboard.py`](../../src/app/services/dashboard.py) | - `_announcement_amount_expr`: `base_amount` 컬럼 기반 집계로 전환 (`json_extract` 완전 제거)<br>- `MAX_REASONABLE_ANNOUNCEMENT_AMOUNT = 100조` 상한 필터 유지<br>- `AMOUNT_NUMERIC = Numeric(30, 0)` 누적 유지<br>- `SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]` 기대 버전을 2에서 3으로 상향 |
| [`../../src/app/models/bids.py`](../../src/app/models/bids.py) | - `_coerce_amount`: `float` 경유 완전 제거 및 `Decimal` 단일 경로 통일<br>- `NaN`, `Infinity`, 음수 입력에 대한 명시적 제외 (`None` 반환)<br>- 과거 107건 불일치 데이터와의 일관성을 위해 소수점 표기는 `ROUND_DOWN`(내림)으로 정수부 절단 |
| [`../../src/app/services/api_collector.py`](../../src/app/services/api_collector.py) | - `BIGINT_MIN = -9_223_372_036_854_775_808`, `BIGINT_MAX = 9_223_372_036_854_775_807` 경계 상수 정의<br>- `_map_announcement_item` 및 `_map_result_item`에서 `BIGINT` 범위를 초과하는 금액은 컬럼에 `None`을 넣고 `logger.warning` 기록<br>- 원본 `raw_data`는 G1 무손실 원칙에 따라 100% 보존 |
| [`../../tests/test_amount_parsing.py`](../../tests/test_amount_parsing.py) | - 신규 작성: `_coerce_amount` 정밀도 보존, 소수점 절단, 이상치 배제 및 적재기 `BIGINT` 초과 방어/경고 로그 단위 테스트 12건 |
| [`../../tests/test_dashboard_stats_parity.py`](../../tests/test_dashboard_stats_parity.py) | - `test_compare_stats_reads_comma_separated_amount`: 적재 경로 연계 픽스처 갱신<br>- `test_announcement_amount_column_parity_with_legacy_json_path`: 343건 세 형태(0/NULL, 소수점 절단, 100조 초과)를 포함한 픽스처에서 옛 JSON 경로와 새 컬럼 경로의 집계 합산 결과 100% 일치 대조 검증 추가 |
| [`../../tests/test_mysql_integration_queries.py`](../../tests/test_mysql_integration_queries.py) | - `test_mysql_amount_column_aggregation_and_cast_dialects`: MySQL 8 환경에서의 20자리 값, 소수점 표기, 콤마 포함, 상한 초과, `NULL` 집계 방언 검증 케이스 추가 |
| [`../../docs/ops/amount_column_aggregation_20260904.md`](../../docs/ops/amount_column_aggregation_20260904.md) | - 운영 가이드 및 전환 정합성 문서 신규 작성 |

---

## 2. 정합성 및 무손실 검증 분석

### 2.1 343건 불일치 행의 집계 무영향 실증
- **234건 (`column_null`)**: `raw_data` 금액이 `"0.0"`, 컬럼 `base_amount`는 `NULL`. `SUM` 연산 시 `NULL`은 무시되고 `0`은 합계에 기여하지 않으므로 양쪽 경로의 결과가 정확히 동일합니다.
- **107건 (`value_differs` 소수부)**: `raw_data`가 소수점을 가지고 컬럼은 정수로 절단됨. 차이는 전수 1원 미만이며 합계 107원 미만(2,125조 원 대비 상대오차 5e-17). 새 파서 역시 과거 일관성을 위해 `ROUND_DOWN`을 적용하므로 신규 적재 데이터에서도 정합성이 유지됩니다.
- **2건 (`value_differs` 포화)**: 20자리 원본으로 인해 컬럼에 `9223372036854775807`로 포화된 건. 양쪽 경로 모두 100조 상한 필터(`MAX_REASONABLE_ANNOUNCEMENT_AMOUNT`)에 의해 집계에서 배제(`NULL`)되므로 집계 결과에 영향을 주지 않습니다.

### 2.2 적재 경로 안정성 확보
- 기존에는 조달청 원본이 20자리(`12240000012240000011`)인 경우 DB 적재 시 암묵적으로 `BIGINT` 최대값으로 클램프되어 데이터가 오염되었습니다.
- 본 개선을 통해 `BIGINT` 범위를 벗어나는 값은 컬럼에 `NULL`로 명시적 저장되고 경고 로그가 기록되며, 원본 `raw_data`는 온전히 보존되어 추후 별도 승인 하에 재해석할 수 있습니다.

---

## 3. 검증 실행 결과

```bash
# 1. 린트 및 정적 분석
$ uv run ruff check .
All checks passed!

$ uv run mypy src
Success: no issues found in 93 source files

# 2. 전량 테스트 스위트 (data_assets 제외)
$ uv run pytest tests/ -q -m 'not data_assets'
3558 passed, 32 skipped, 3 deselected in 110.85s (0:01:50)
exit_code: 0

# 3. 에이전트 규칙 검증
$ python3 scripts/validate_agent_rules.py --quiet
검증 통과: 20/20 건.
exit_code: 0
```
