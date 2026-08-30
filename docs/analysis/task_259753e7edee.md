# Task task_259753e7edee: 콜드 스타트 SQL 비용 귀속 측정 하네스 구축

> **작성일**: 2026-08-30
> **Task ID**: `task_259753e7edee`
> **역할**: `builder`
> **대상 파일**:
> - [`scripts/measure_coldsql_attribution.py`](../../scripts/measure_coldsql_attribution.py)
> - [`tests/test_measure_coldsql_attribution.py`](../../tests/test_measure_coldsql_attribution.py)

---

## 1. 개요 및 배경

2026-08-30 RAG 정형 질의 콜드 스타트 조사 과정에서 EXPLAIN 기반 단일 쿼리 추정에 의존하여 실제 97초 비용의 약 15%만 점유하는 쿼리를 수정하는 오류가 발생했습니다. 동일한 실수를 방지하고 실측 기반으로 쿼리별 소비를 정확히 규명하기 위해, MySQL `performance_schema.events_statements_summary_by_digest` 기반의 콜드/웜 SQL 비용 귀속 측정 하네스(`scripts/measure_coldsql_attribution.py`)를 구축했습니다.

---

## 2. 핵심 설계 원칙 및 구현

| 설계 항목 | 구현 내용 | 근거 / 안전장치 |
| :--- | :--- | :--- |
| **쿼리별 귀속 정본** | `performance_schema.events_statements_summary_by_digest` 활용 (`DIGEST_TEXT`, `COUNT_STAR`, `SUM_TIMER_WAIT`, `MAX_TIMER_WAIT`) | 단위 변환: 피코초(ps) 기준 `SUM_TIMER_WAIT / 1e12` (초), `MAX_TIMER_WAIT / 1e9` (밀리초) |
| **캐시 비우기 안전장치** | `--flush-cache` 명시적 CLI 플래그가 주어졌을 때만 Redis `FLUSHALL` 실행 (기본값: `False`) | 공유 자원 오염 방지 (`flush_requested=False` 시 호출 원천 차단) |
| **Cold vs Warm 차이 계산** | 동일 질의 표본(Fixture 문항)에 대해 Cold(캐시 미스) 측정 후 Warm(캐시 적중) 측정을 직렬 수행하고 쿼리별 차이(`delta_sum_sec`, `delta_count`, `delta_max_ms`) 산출 | 절감 가능한 SQL 비용 기준 내림차순 정렬 (`calculate_attribution_diff`) |
| **Canonical 게이트 판정** | `scripts/measure_llm_quality.py` 의 `CANONICAL_FIXTURE_HASHES`, `compute_file_sha256`, `evaluate_canonical` 직접 재사용 | 중복 코드 방지 및 정본 기준 일치성 보장 |
| **Fail-Closed 검증** | `performance_schema` 비활성화(OFF) 또는 테이블 접근 실패 시 `PerformanceSchemaUnavailableError` 발생 (종료 코드 2) | 조용한 실패 및 빈 산출물 방지 |
| **테스트 격리성 (DI)** | DB executor 및 Redis client 를 주입 가능한 콜러블/객체 형태로 구현 | 실제 MySQL/Redis 없이 Mock 기반 완전 격리 테스트 지원 |

---

## 3. 하네스 사용법

```bash
# 기본 사용 (기본 Fixture 문항 q03, q08, q25, q31 대상, 캐시 비우기 미실행)
uv run python scripts/measure_coldsql_attribution.py \
  --base-url http://127.0.0.1:8000 \
  --output data/benchmarks/coldsql_attribution_result.json

# 명시적 캐시 비우기 포함 실행
uv run python scripts/measure_coldsql_attribution.py \
  --flush-cache \
  --base-url http://127.0.0.1:8000 \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --item-ids q03,q08,q25,q31 \
  --output data/benchmarks/coldsql_attribution_result.json
```

---

## 4. 검증 결과

### 4.1 단위 및 회귀 테스트 (`tests/test_measure_coldsql_attribution.py`)

- `test_flush_cache_disabled_by_default_does_not_execute_flushall`: 기본 상태에서 Redis FLUSHALL 미호출 보증 (PASSED)
- `test_flush_cache_enabled_executes_flushall`: 플래그 지정 시 정상 FLUSHALL 호출 보증 (PASSED)
- `test_flush_cache_enabled_without_client_raises_error`: 클라이언트 미제공 시 예외 처리 보증 (PASSED)
- `test_timer_conversion_precision`: 피코초 -> 초/밀리초 단위 변환 정밀도 검증 (PASSED)
- `test_fetch_digest_statistics_converts_units_properly`: digest 데이터 추출 및 내부 쿼리 필터링 검증 (PASSED)
- `test_calculate_attribution_diff_computes_delta_correctly`: cold/warm delta 및 정렬 검증 (PASSED)
- `test_check_performance_schema_disabled_raises`: performance_schema OFF 시 fail-closed 검증 (PASSED)
- `test_check_performance_schema_query_failure_raises`: 테이블 조회 실패 시 fail-closed 검증 (PASSED)
- `test_reset_performance_schema_failure_raises`: TRUNCATE 실패 시 예외 처리 검증 (PASSED)
- `test_main_returns_code_2_on_performance_schema_unavailable`: CLI 종료 코드 2 반환 검증 (PASSED)
- `test_canonical_false_on_unregistered_fixture_hash`: 미등록 fixture hash 처리 검증 (PASSED)
- `test_run_attribution_measurement_complete_flow`: Mock 기반 전 주기 측정 흐름 검증 (PASSED)

총 12건 테스트 전량 통과 (`12 passed in 0.34s`).

---

## 5. Review Checklist 자가 점검

| 점검 ID | 질의 | 판정 | 설명 |
| :--- | :--- | :---: | :--- |
| `flush_by_default` | 캐시 비우기가 플래그 없이 실행되는가? | **No** (정상) | `flush_cache_requested` 기본값 `False`, 미지정 시 절대 실행되지 않음 |
| `attribution_guessed` | 쿼리별 귀속을 digest 가 아니라 추정으로 계산하는가? | **No** (정상) | `performance_schema.events_statements_summary_by_digest` 실측치 집계 |
| `silent_on_missing_perfschema` | performance_schema 를 못 쓸 때 조용히 빈 결과를 남기는가? | **No** (정상) | `PerformanceSchemaUnavailableError` 발생 및 exit code 2 종료 |
| `canonical_logic_duplicated` | canonical 판정을 복사해 두 벌로 만들었는가? | **No** (정상) | `scripts.measure_llm_quality` 의 함수/상수를 직접 임포트하여 사용 |
| `tests_require_live_services` | 테스트가 실제 DB 나 Redis 를 요구하는가? | **No** (정상) | Mock 객체 및 DI 구조를 통해 완전 격리 실행 |
| `measurement_executed` | 실제 측정을 실행했는가? | **No** (정상) | 하네스 및 테스트만 작성하였으며 `data/benchmarks/` 산출물 미생성 |
