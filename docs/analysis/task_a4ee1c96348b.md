# Task a4ee1c96348b 분석 및 구현 보고서: RAG 구간 벤치마크 실패 증거 보존 및 분리 집계

> 작성일: 2026-09-07
> 대상: `scripts/benchmark_rag_segments.py`, `tests/test_benchmark_rag_segments.py`
> 작업 ID: `task_a4ee1c96348b`

---

## 1. 배경 및 목적

2026-09-06 R-13 콜드 SQL 재측정에서 canonical 게이트 `no_request_failures` 가 8회 중 2회 실패로 미충족되었습니다.
그러나 기존 하네스는 실패 시 예외 객체, 소요 시간, 문항 식별자, 콜드 여부를 버리고 정수 카운터(`errors: failures`)만 남겼기 때문에, 실패한 2건이 타임아웃인지, HTTP 5xx 서버 오류인지, 혹은 응답은 정상 수신되었으나 `X-RAG-Trace-Id` 헤더만 누락된 것인지 산출물만으로는 원인을 판정할 수 없었습니다.

본 작업의 목적은:
1. 질의 전송 함수 `send_query`가 타임아웃, 일반 전송 실패, 트레이스 헤더 누락을 명확히 구분하고 예외 메시지를 함께 보존하도록 개선합니다.
2. 질의 전송 루프에서 실패 회차마다 문항 ID(`item_id`), 질문(`question`), 반복 인덱스(`repetition_index`), 콜드 여부(`is_cold`), 소요 시간(`elapsed_ms`), 실패 사유(`reason`), 예외 메시지(`error`)를 상세히 기록하여 산출물 JSON(`failed_queries`)에 영구 보존합니다.
3. 전송 실패 건수(`transport_failures`)와 트레이스 헤더 누락 건수(`missing_header_failures`)를 분리 집계하여 산출물 및 `canonical_rationale`에 명시하되, 게이트 판정(`evaluate_canonical`)에는 두 건수의 합(`request_failures`)을 그대로 전달하여 종전의 `no_request_failures` 게이트 엄격성을 100% 유지합니다.

---

## 2. 세부 변경 사항

### 2.1 `send_query` 반환 계약 및 사유 분류 (`scripts/benchmark_rag_segments.py`)
- 반환 타입 확장: `tuple[float, bool, str | None, str | None, str | None]`
  - `(elapsed_ms, ok, trace_id, reason, error_message)`
- 사유 상수 정의:
  - `REASON_TIMEOUT` (`"timeout"`): `TimeoutError`, `socket.timeout`, `URLError` 내부 timeout 원인
  - `REASON_TRANSPORT_ERROR` (`"transport_error"`): 네트워크 연결 거부, HTTP 5xx 오류 등 그 외 `URLError`/`OSError`
  - `REASON_MISSING_HEADER` (`"missing_header"`): HTTP 응답은 수신되었으나 `X-RAG-Trace-Id` 헤더가 부재하거나 공백인 경우
- 정상 응답 시 `(elapsed_ms, True, trace_id, None, None)` 반환

### 2.2 질의 루프 증거 보존 및 분리 집계
- `failed_queries` 배열에 실패한 각 요청의 메타데이터(`item_id`, `question`, `repetition_index`, `is_cold`, `elapsed_ms`, `reason`, `error`) 기록. 불필요한 산출물 비대화를 방지하기 위해 응답 본문은 제외.
- `transport_failures` 와 `missing_header_failures` 분리 계측.
- `failures = transport_failures + missing_header_failures` 로 종전 합계 유지.
- `evaluate_canonical(..., request_failures=failures, ...)` 로 게이트 판정에 합계를 전달하여 판정 완화 없음.
- `canonical_rationale` 부분 실패 문구에 `[전송 실패: N, 헤더 누락: M]` 포맷 추가.
- 산출물 JSON payload에 호환성 필드(`errors`, `failures`, `request_failures`)와 분리 필드(`transport_failures`, `missing_header_failures`, `transport_failures_count`, `missing_header_failures_count`, `failed_queries`, `failed_requests`) 등록.

### 2.3 단위 및 회귀 테스트 보강 (`tests/test_benchmark_rag_segments.py`)
- `test_send_query_success_with_header`, `test_send_query_missing_header_returns_false`, `test_send_query_network_error_returns_false` 반환 계약 갱신 및 사유/에러 메시지 단언 추가.
- `test_send_query_timeout_error_returns_timeout_reason`: `TimeoutError` 발생 시 `timeout` 사유 판정 검증.
- `test_send_query_urlerror_wrapping_timeout_returns_timeout_reason`: `URLError` 내 타임아웃 래핑 케이스 검증.
- `test_send_query_oserror_timeout_returns_timeout_reason`: `OSError` 타임아웃 케이스 검증.
- `test_main_failure_evidence_and_separated_counts`: 타임아웃, 500 에러, 헤더 누락 3개 경로가 각각 고유 사유로 `failed_queries`에 보존되고 건수가 분리 집계되는지 E2E 검증.
- `test_main_failures_sum_evaluated_in_canonical_gate`: 헤더 누락만 발생해도 두 건수의 합이 `evaluate_canonical`에 전달되어 `no_request_failures` 게이트가 정상 탈락하는지 검증.

---

## 3. 검증 결과

1. `uv run pytest tests/test_benchmark_rag_segments.py tests/test_rag_segment_metrics.py -q`:
   - 77 passed in 1.48s
2. `uv run pytest tests/ -q -m 'not data_assets'`:
   - 3948 passed, 41 skipped, 3 deselected in 142.70s
3. `python3 scripts/validate_agent_rules.py --quiet`:
   - 검증 통과: 20/20 건
