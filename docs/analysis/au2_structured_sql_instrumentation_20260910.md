# 정형 검색 SQL 구간 계측

## 목적

`retrieve_structured_data`의 기존 반환값과 `sql_ms` 계산을 유지하면서, 첫 호출의 긴 SQL 구간을 캐시·커서 실행·파이썬 잔여 비용으로 분리합니다. 계측은 `settings.LATENCY_SEGMENT_LOGGING`이 `False`인 기본 상태에서 완전히 비활성입니다.

## 기록 필드

`structured_sql_segments`는 기존 `rag_engine_latency` 로그에 `trace_id`와 함께 기록됩니다.

| 필드 | 의미 |
| --- | --- |
| `segments.cache_lookup_ms` | 정형 경로의 캐시 조회 소요 합계 |
| `segments.cached_aggregate_N` | N번째 `_cached_aggregate` 호출 전체 시간 |
| `segments.top_rows_N` | N번째 `_top_rows` 호출 전체 시간 |
| `segments.corrupted_probe_ms` | 손상값 탐침 SQL 소요 시간 |
| `segments.result_assembly_ms` | 정형 검색 결과 딕셔너리 조립 시간 |
| `cursor_ms` | SQLAlchemy 커서 실행 시간 합계 |
| `cursor_count` | 커서 실행 횟수 |
| `total_ms` | `retrieve_structured_data` 전체 시간 |
| `residual_ms` | `total_ms - cursor_ms`의 음수 보정값; checkout 대기와 파이썬 부수 비용 포함 |

`cached_aggregate_N`과 `top_rows_N`은 호출 순서의 N으로 구분합니다. `cursor_ms`는 SQLAlchemy `Engine`의 커서 이벤트로 측정하며, 계측 레코드가 열려 있는 호출만 집계합니다.

## 측정 방법

측정 프로세스의 환경 설정에서 `LATENCY_SEGMENT_LOGGING=true`를 지정하고 프로세스를 재시작한 뒤, 코디네이터가 동일 질의를 실행합니다. 결과는 기존 `rag_engine_latency` 한 줄의 `trace_id`와 `structured_sql_segments`를 사용해 결합하며, 측정 후에는 플래그를 `false`로 되돌립니다.

`residual_ms`가 크면 실제 SQL 실행보다 연결 checkout 대기, 락 대기, 캐시 계층, 결과 변환 등 비커서 구간의 비중이 큰 것입니다. 계측값은 응답 반환 딕셔너리에 추가하지 않으므로 API 응답 형식은 변하지 않습니다.
