# 공고 기초금액 컬럼 기반 집계 전환 및 적재 파싱 강화

> **작성일**: 2026-09-04
> **버전**: v1.0.0
> **상태**: 구현 및 검증 완료
> **관련 커밋**: Task task_ca4426a52f9b
> **대상 파일**:
> - [`../../src/app/services/dashboard.py`](../../src/app/services/dashboard.py)
> - [`../../src/app/models/bids.py`](../../src/app/models/bids.py)
> - [`../../src/app/services/api_collector.py`](../../src/app/services/api_collector.py)
> - [`../../tests/test_amount_parsing.py`](../../tests/test_amount_parsing.py)
> - [`../../tests/test_dashboard_stats_parity.py`](../../tests/test_dashboard_stats_parity.py)
> - [`../../tests/test_mysql_integration_queries.py`](../../tests/test_mysql_integration_queries.py)

---

## 1. 개요

기존 공고 기초금액 집계(`src/app/services/dashboard.py`)는 질의 시점마다 5,497,840건 전체 행에 대해 `json_extract`, `replace`, `cast` 연산을 전수 수행하여 기관별 순위(`agency_announce_top10`)가 31.97초, 전체 요약 재집계가 554초 소요되는 심각한 지연을 유발했습니다.

수집 적재 파이프라인(`src/app/services/api_collector.py`)은 이미 원본 `raw_data`의 예산 금액(`asignBdgtAmt`, `bdgtAmt`)을 정제하여 `bid_announcements.base_amount` 컬럼에 적재하고 있으므로, 집계 쿼리가 질의 시점에 동일한 JSON 파싱을 중복 수행할 필요가 없습니다.

본 작업은 다음 세 가지를 완수했습니다:
1. 집계 표현식(`_announcement_amount_expr`)을 `base_amount` 컬럼 기반으로 전환 (인덱스 활용 및 파싱 오버헤드 제거).
2. 파이썬 금액 변환(`_coerce_amount`)을 `Decimal`로 통일하여 부동소수점 정밀도 손실(2^53 초과 자릿수 왜곡)을 제거하고, 소수점은 과거 107건 불일치 데이터와의 일관성을 위해 내림(`ROUND_DOWN`)으로 정수부 절단.
3. 적재 경로(`_map_announcement_item`)에서 `BIGINT` 범위를 벗어나는 값이 DB에 조용히 포화/클램프되는 취약점을 차단하고, 초과 시 컬럼에 `NULL`을 저장하며 경고 로그를 남기도록 개선. 원본 `raw_data`는 G1 무손실 원칙에 따라 100% 보존.

---

## 2. 정합성 및 안전성 근거

전수 실측 조사([`../../docs/analysis/base_amount_column_mismatch_343_20260904.md`](../../docs/analysis/base_amount_column_mismatch_343_20260904.md))에서 규명된 343건의 불일치 정체에 따라, 컬럼 기반 집계 전환 후에도 집계 산출값은 실질적으로 변하지 않습니다:

| 형태 구분 | 건수 | 원인 및 현상 | 집계 영향 |
| --- | :---: | --- | --- |
| `column_null` | 234 | `raw_data`가 `"0.0"` 또는 `"0"`, 컬럼은 `NULL` | **0 (동일)**: `SUM`에서 0과 `NULL`은 합계 기여가 0으로 완전히 동일 |
| `value_differs` (소수부) | 107 | `raw_data` 소수점 표기, 적재 시 정수 절단 | **최대 107원 미만**: 2,125조 총액 대비 상대오차 5e-17로 무의미 |
| `value_differs` (포화) | 2 | 20자리 원본으로 적재 시 `BIGINT` 최대값(`9223372036854775807`) 포화 | **0 (동일)**: 양쪽 경로 모두 100조(`MAX_REASONABLE_ANNOUNCEMENT_AMOUNT`) 상한에 걸려 제외(`NULL`) |

이상치 상한 필터(`MAX_REASONABLE_ANNOUNCEMENT_AMOUNT = 100조`)와 `DECIMAL(30, 0)`(`AMOUNT_NUMERIC`) 누적을 철저히 유지하여, 포화 2건 및 원본 자릿수 중복 입력 31건이 집계에 유입되어 합계가 음수로 wrap되는 문제를 원천 차단했습니다.

---

## 3. 주요 변경 사항

### 3.1 집계 서비스 (`src/app/services/dashboard.py`)
- `_announcement_amount_expr`: `BidAnnouncement.base_amount` 컬럼을 `AMOUNT_NUMERIC`으로 캐스팅하고 100조 초과 시 `None`을 반환하는 간결하고 빠른 SQL 표현식으로 개편 (`json_extract` 완전 제거).
- `SUMMARY_ALGORITHM_VERSIONS`: `announcement` 집계 기대 버전을 2에서 3으로 상향. 기존 DB에 저장된 요약 스냅샷을 stale로 판정하여 비동기 재집계를 안전하게 유도.

### 3.2 도메인 모델 (`src/app/models/bids.py`)
- `_coerce_amount`: `float` 경유 경로를 완전히 제거하고 `Decimal` 단일 경로로 통일.
- `NaN`, `Infinity`, 음수를 명시적으로 검사하여 유효하지 않은 금액은 `None`을 반환.
- 소수점 표기는 과거 적재 데이터 107건과의 정합성을 유지하기 위해 `ROUND_DOWN`(내림)으로 정수부를 취하도록 확정.

### 3.3 수집 적재기 (`src/app/services/api_collector.py`)
- `BIGINT_MIN = -9_223_372_036_854_775_808`, `BIGINT_MAX = 9_223_372_036_854_775_807` 범위 경계 상수 도입.
- `_map_announcement_item` 및 `_map_result_item`에서 추출된 금액이 `BIGINT` 범위를 초과하면 컬럼 값을 `None`으로 설정하고 `logger.warning`을 기록.
- 원본 `raw_data` 딕셔너리는 일체 수정하지 않고 그대로 보존하여 G1 데이터 무손실 원칙 준수.

---

## 4. 검증 결과

| 검증 영역 | 테스트 스위트 | 결과 | 비고 |
| --- | --- | :---: | --- |
| 금액 파싱 단위 검증 | `tests/test_amount_parsing.py` | 12/12 통과 | 20자리 정밀도, 소수점 절단, 이상치 제외, 적재 방어 |
| 집계 정합성 대조 | `tests/test_dashboard_stats_parity.py` | 17/17 통과 | 옛 JSON 파싱 대 새 컬럼 경로 대조 100% 일치 |
| 알고리즘 버전 판정 | `tests/test_dashboard_summary_version.py` | 4/4 통과 | 버전 3 미만 요약의 stale 판정 및 비동기 재집계 큐 등록 |
| MySQL 통합 질의 | `tests/test_mysql_integration_queries.py` | 6/6 통과 (건너뜀/구조검증) | 20자리, 소수점, 콤마, 상한초과, NULL MySQL 8 방언 테스트 추가 |
| 전체 회귀 테스트 | `uv run pytest tests/ -q -m 'not data_assets'` | 3,558/3,558 통과 | 기존 기능 및 화면 무회귀 확인 |
| 정적 분석 / 린트 | `uv run ruff check .` & `uv run mypy src` | 통과 (0 errors) | 무결성 확인 |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 통과 | 규약 정합성 통과 |
