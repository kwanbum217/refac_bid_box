# Arq 취소 태스크 최상위 Span 상태 보존 및 분류 분석 보고서

> **작성일**: 2026-09-05
> **작업 ID**: `task_82b3c4587fbe`
> **대상 모듈**: `src/app/core/observability.py`, `src/tasks/worker.py`, `tests/test_observability.py`
> **검증 결과**: 전체 테스트(3637 passed, 41 skipped, 3 deselected), mypy(0건), 규칙 검증(20/20) 통과

---

## 1. 개요 및 배경

2026-09-05 T-01 작업의 Level 2 리뷰에서 지적된 잔여 리스크로, OpenTelemetry 분산 추적이 활성화된 환경에서 Arq 비동기 작업이 취소(`asyncio.CancelledError`)되었을 때 최상위 span(`arq.job:{job_id}`)이 여전히 `StatusCode.OK`로 종결되는 결함이 존재했습니다.

`WorkerSettings`에 `allow_abort_jobs = True`가 설정되어 있어 운영 환경에서 사용자 중단(Harness abort API 대응 `abort_arq_job`)이나 워커 종료 신호에 의해 작업 취소가 일상적으로 발생합니다. 취소된 작업이 성공(`StatusCode.OK`)으로 남으면 배치 작업 모니터링 대시보드에서 중단 사실을 인지할 수 없게 됩니다.

본 작업에서는 취소 경로에서도 span의 취소 상태를 정확히 보존하고, 정상 워커 종료 시 배경 태스크 취소와 사용자 의도 중단을 구분하여 기록하는 메커니즘을 구현했습니다.

---

## 2. 결함 원인 분석

### 2.1 asyncio.CancelledError 의 BaseException 계층 구조

Python 3.8 이후 `asyncio.CancelledError`는 일반 `Exception`이 아닌 `BaseException`을 상속합니다. 기존 `src/app/core/observability.py`의 `trace_worker_task` 컨텍스트 매니저는 예외 포획 블록이 `except Exception as exc:`로만 작성되어 있어 취소 예외(`CancelledError`)가 이 블록에 걸리지 않고 그대로 통과했습니다.

### 2.2 arq_on_job_end 의 비에러 상태에 대한 일괄 OK 덮어쓰기

`trace_worker_task`를 빠져나간 취소 예외로 인해 최상위 span(`arq.job:{job_id}`)의 상태는 초기값인 `StatusCode.UNSET`으로 유지되었습니다. 이후 Arq 라이프사이클 종료 훅인 `arq_on_job_end`가 호출되면서 아래 로직을 수행했습니다:

```python
status = getattr(span, "status", None)
status_code = getattr(status, "status_code", None)
if status_code != StatusCode.ERROR:
    span.set_status(Status(StatusCode.OK))
span.end()
```

기존 조건식은 상태 코드가 오직 `StatusCode.ERROR`가 아닐 때 무조건 `StatusCode.OK`를 부여하도록 작성되어 있었습니다. 따라서 취소로 인해 `StatusCode.UNSET` 상태로 남아있던 최상위 span이 강제로 `StatusCode.OK`로 덮어써지는 문제가 발생했습니다.

---

## 3. 설계 결정 및 구현 내용

### 3.1 취소 상태 처리 및 상태 코드 결정 근거 (Ground Truth 36, 39)

취소(`asyncio.CancelledError`)는 코드 결함이나 런타임 크래시와 같은 오류(`StatusCode.ERROR`)가 아니라, 사용자의 의도된 중단(User Abort) 또는 시스템의 정상 수명주기 종료(Worker Shutdown)에 해당합니다.

- **운영 노이즈 방지**: 취소된 작업을 일괄적으로 `StatusCode.ERROR`로 처리할 경우, 정상적인 워커 배포나 정상적인 사용자 의도 중단이 APM 알람 및 에러율(SLO/SLI) 지표에 장애로 잡히는 운영 노이즈를 유발합니다 (`shutdown_not_polluted` 준수).
- **성공 오인 방지**: 반대로 `StatusCode.OK`로 남겨두면 실패/중단된 작업이 정상 완료된 것으로 왜곡됩니다 (`cancel_not_ok` 준수).
- **설계 결정**:
  1. OpenTelemetry 표준 권고에 따라 취소된 span의 상태 코드는 `StatusCode.ERROR`나 `StatusCode.OK`가 아닌 `StatusCode.UNSET`으로 유지합니다.
  2. 취소 사실 및 원인을 명확히 파악할 수 있도록 span 속성에 `task.cancelled = True` 및 `task.cancel_reason`('aborted' 또는 'worker_shutdown')을 기록합니다.
  3. `arq_on_job_end`에서 취소 플래그(`cancelled` 또는 `_task_cancelled`)를 확인하여 취소된 작업의 경우 `StatusCode.OK`로 덮어쓰지 않고 원본 상태를 보존한 채 `span.end()`를 호출합니다.
  4. 취소 예외(`CancelledError`)는 절대로 삼키지 않고 `raise`하여 asyncio의 협조적 태스크 취소 전파를 100% 보장합니다.

### 3.2 정상 종료(Shutdown)와 사용자 Abort 구분 메커니즘

`src/app/core/observability.py`에 `_resolve_cancel_reason` 헬퍼 함수를 추가하고, `src/tasks/worker.py`의 워커 셧다운 라이프사이클과 연동했습니다.

| 취소 유형 | 식별 기준 | span 속성 (task.cancel_reason) | 상태 코드 |
| --- | --- | --- | --- |
| 정상 워커 셧다운 | `exc.args`에 "worker_shutdown" 포함, 또는 `ctx["worker_shutting_down"]=True`, 또는 `ctx["is_background_catchup"]=True` | `worker_shutdown` | `StatusCode.UNSET` |
| 사용자 / Harness Abort | 위 셧다운 조건에 해당하지 않는 Arq 작업 취소 | `aborted` | `StatusCode.UNSET` |

`src/tasks/worker.py`의 `_on_shutdown`에서 `catchup_task.cancel("worker_shutdown")`과 `ctx["worker_shutting_down"] = True`를 설정하여 워커 종료 시 실행 중이던 배경 catch-up 태스크 취소가 정상 셧다운으로 정확히 판별되도록 했습니다.

### 3.3 비활성화 경로(OTEL_ENABLED=False) 무비용 원칙

`settings.OTEL_ENABLED`가 False인 기본 운영 상태에서는 컨텍스트 매니저 및 데코레이터가 추가 객체 생성이나 지연 없이 원본 함수를 즉시 호출하며, 취소 예외 발생 시에도 아무런 부가 동작 없이 즉시 투명하게 전파됩니다.

---

## 4. 검증 결과

### 4.1 회귀 및 신규 단위 테스트

`tests/test_observability.py`에 다음 3가지 핵심 회귀 테스트를 추가하여 총 20개 테스트를 전량 통과시켰습니다:
1. `test_arq_cancelled_task_top_level_span_not_ok_and_propagated`: 사용자 abort 취소 시 최상위 span 및 태스크 span의 상태가 OK가 아니며, `task.cancelled=True`, `task.cancel_reason="aborted"`가 기록되고 `CancelledError`가 정상 전파됨을 검증.
2. `test_arq_worker_shutdown_cancellation_not_polluted`: 워커 정상 셧다운 시 배경 태스크 span이 ERROR나 OK로 기록되지 않고 `StatusCode.UNSET` 및 `task.cancel_reason="worker_shutdown"`으로 기록됨을 검증.
3. `test_otel_disabled_cancellation_zero_overhead_and_transparent`: `OTEL_ENABLED=False` 환경에서 취소 예외가 투명하게 전파되며 부가 상태 오염이 없음을 검증.

<!-- METRICS: observability_regression_test_summary -->
| 검증 항목 | 검증 명령어 | 수행 결과 |
| --- | --- | --- |
| 관측성 회귀 테스트 (20개) | `uv run pytest tests/test_observability.py -v` | 통과 (20 passed in 0.18s) |
| 스케줄 태스크 회귀 테스트 (14개) | `uv run pytest tests/test_scheduled_tasks.py -q` | 통과 (14 passed in 0.15s) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | 통과 (3637 passed, 41 skipped, 3 deselected in 166.62s) |
| 정적 타입 검사 | `uv run mypy src` | 통과 (Success: no issues found in 93 source files) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 (20/20 passed) |

---

## 5. 리뷰 체크리스트 자체 점검

- [x] **cancel_not_ok**: 취소로 끝난 태스크의 최상위 span 상태가 `StatusCode.OK`가 아닌 `StatusCode.UNSET`으로 보존됨.
- [x] **cancel_reraised**: `CancelledError`를 포획 후 반드시 다시 `raise`하여 태스크 전파를 차단하지 않음.
- [x] **existing_paths_unchanged**: 성공 경로는 `StatusCode.OK`, 일반 예외 경로는 `StatusCode.ERROR`로 유지됨.
- [x] **shutdown_not_polluted**: 워커 정상 종료 시 배경 태스크가 `StatusCode.ERROR`가 아닌 `StatusCode.UNSET`으로 기록되어 운영 노이즈를 만들지 않음.
- [x] **span_always_closed**: 취소 경로에서도 `start_as_current_span` 및 `arq_on_job_end`의 finally 블록에서 `span.end()`가 항상 호출됨.
- [x] **disabled_path_zero_cost**: `OTEL_ENABLED=False` 경로에서 오버헤드 없이 동일하게 예외가 전파됨.
- [x] **test_expectations_honest**: 사양에 명시된 불변조건을 정직하게 단정문으로 검증함.
- [x] **scope_excess**: `allowed_write_files`에 명시된 파일 외 다른 파일은 일체 수정하지 않음.
