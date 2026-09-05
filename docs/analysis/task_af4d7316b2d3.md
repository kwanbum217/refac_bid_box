# Arq 작업 최상위 Span 상태 보존 및 trace_worker_task 배선 분석 보고서

> **작성일**: 2026-09-05
> **작업 ID**: `task_af4d7316b2d3`
> **대상 모듈**: `src/app/core/observability.py`, `src/tasks/worker.py`, `src/tasks/automation_tasks.py`, `src/tasks/scheduled_tasks.py`, `src/tasks/summary_tasks.py`, `src/tasks/retrain_task.py`
> **검증 결과**: 전체 테스트(3624 passed, 41 skipped) 및 규칙 검증 통과 (20/20)

---

## 1. 개요 및 배경

2026-09-04 외부 진단 보고서 T-01에 따르면, OpenTelemetry 분산 추적이 활성화되어 있는 환경에서도 Arq 비동기 배치 작업이 예외로 비정상 종료되었을 때 Datadog/Jaeger 등 수집기 상에서 해당 작업의 최상위 span(`arq.job:{job_id}`)이 항상 `StatusCode.OK`로 기록되어 장애를 인지하지 못하는 결함이 존재했습니다.

또한, 태스크 구간 계측을 위해 작성된 `trace_worker_task` 컨텍스트 매니저가 운영 코드에 전혀 배선되어 있지 않아(호출부 0곳), 실제 Arq 작업의 세부 구간 지연 및 파라미터가 추적되지 못하고 있었습니다.

본 작업에서는 다음 두 가지 핵심 문제를 해결했습니다:
1. `arq_on_job_end` 훅이 이미 `StatusCode.ERROR`로 표시된 최상위 span을 무조건 `StatusCode.OK`로 덮어쓰던 결함 수정
2. Arq 워커에 등록된 모든 태스크 함수(15개: 일반 태스크 13개 + 크론 전용 태스크 2개)를 `@traced_worker_task` 데코레이터를 통해 `trace_worker_task`로 배선하고, 향후 태스크 추가 시 배선 누락을 방지하는 방어 로직 및 회귀 테스트 추가

---

## 2. 결함 원인 분석

### 2.1 arq_on_job_end 의 무조건적 OK 덮어쓰기

`src/app/core/observability.py`의 `arq_on_job_end` 훅은 기존에 다음과 같이 구현되어 있었습니다:

```python
finally:
    if span is not None:
        span.set_status(Status(StatusCode.OK))
        span.end()
```

Arq의 라이프사이클 설계 상 `after_job_end(on_job_end)` 훅의 `ctx` 딕셔너리에는 발생한 예외 객체가 전달되지 않습니다. 따라서 작업 실패 여부는 태스크 본체 실행 경로에서 span에 기록되어야 합니다. 그러나 `arq_on_job_end`가 태스크 종료 시 span의 기존 상태를 확인하지 않고 무조건 `span.set_status(Status(StatusCode.OK))`를 호출하여, 태스크 내부에서 아무리 에러를 기록했어도 최상위 span이 최종적으로 `OK`로 덮어씌워지고 있었습니다.

### 2.2 trace_worker_task 미배선 및 최상위 Span 예외 전파 부재

`trace_worker_task`는 `with tracer.start_as_current_span(f"arq.task:{task_name}")`으로 자식 span을 생성하여 자식 span에만 `record_exception`과 `StatusCode.ERROR`를 설정했습니다. Arq의 최상위 span(`arq.job:{job_id}`)은 `arq_on_job_start` 시점에 context에 바인딩되어 있으므로, 자식 span뿐만 아니라 최상위 span에도 에러 상태 및 예외 이벤트(`record_exception`)를 반영해주어야 온전한 에러 추적이 가능했습니다.

---

## 3. 구현 내용 및 설계 결정

### 3.1 arq_on_job_end Span 상태 보존

`src/app/core/observability.py`의 `arq_on_job_end`에서 span의 현재 상태 코드를 확인하여, 이미 `StatusCode.ERROR`로 기록된 경우에는 `OK`로 덮어쓰지 않고 원본 에러 상태를 보존한 채 `span.end()`만 호출하도록 수정했습니다.

```python
if span is not None:
    status = getattr(span, "status", None)
    status_code = getattr(status, "status_code", None)
    if status_code != StatusCode.ERROR:
        span.set_status(Status(StatusCode.OK))
    span.end()
```

### 3.2 trace_worker_task 최상위 Span 에러 전파

`trace_worker_task` 실행 시 `ctx`의 `_otel_span` 또는 현재 context의 recording span을 참조하여, 예외 발생 시 자식 span(`arq.task:...`)과 최상위 span(`arq.job:...`) 모두에 `record_exception(exc)` 및 `set_status(Status(StatusCode.ERROR, str(exc)))`를 기록한 후 예외를 원래대로 재발생(`raise`)시킵니다. 이를 통해 Arq 본연의 재시도(retry) 및 실패 격리 메커니즘을 100% 보존합니다.

### 3.3 @traced_worker_task 데코레이터 도입 및 전수 배선

개별 태스크 함수 내부마다 `with trace_worker_task(...)` 블록을 수동으로 삽입하는 방식은 코드 중복이 심하고 신규 태스크 작성 시 실수로 누락하기 쉽습니다. 따라서 데코레이터 패턴인 `@traced_worker_task`를 도입했습니다.

- **비활성화 시 무비용 (Zero-overhead)**: `OTEL_ENABLED=False`일 때는 어떠한 context 매니저나 TracerProvider 호출 없이 즉시 원래의 `await fn(*args, **kwargs)`를 실행합니다.
- **메타데이터 보존**: `__traced_worker_task__ = True` 속성을 래퍼 함수에 부여하여 런타임 및 테스트에서 계측 여부를 기계적으로 검증할 수 있도록 했습니다.
- **전수 배선**: 아래 표와 같이 등록된 모든 태스크 함수에 데코레이터를 적용했습니다.

| 모듈 경로 | 태스크 함수명 | 등록 위치 |
| --- | --- | --- |
| `src/tasks/automation_tasks.py` | `preflight_check_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `collect_bids_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `update_kb_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `validate_model_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `refresh_data_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `manual_full_task` | `WorkerSettings.functions` |
| `src/tasks/automation_tasks.py` | `manual_retrain_task` | `WorkerSettings.functions` |
| `src/tasks/retrain_task.py` | `run_retrain_pipeline_task` | `WorkerSettings.functions` |
| `src/tasks/summary_tasks.py` | `rebuild_dataset_summary_task` | `WorkerSettings.functions` |
| `src/tasks/scheduled_tasks.py` | `development_data_refresh_task` | `WorkerSettings.functions`, `cron_jobs` |
| `src/tasks/scheduled_tasks.py` | `drift_monitor_task` | `WorkerSettings.functions`, `cron_jobs` |
| `src/tasks/scheduled_tasks.py` | `backup_schedule_task` | `WorkerSettings.functions`, `cron_jobs` |
| `src/tasks/scheduled_tasks.py` | `run_schedule_catchup_task` | `WorkerSettings.functions` |
| `src/tasks/scheduled_tasks.py` | `nightly_schedule_task` | `WorkerSettings.cron_jobs` |
| `src/tasks/scheduled_tasks.py` | `weekly_retrain_task` | `WorkerSettings.cron_jobs` |

### 3.4 WorkerSettings 배선 누락 2중 방어

1. **런타임 방어 (`ensure_all_worker_tasks_traced`)**: `src/tasks/worker.py` 모듈 로드 시점에 `WorkerSettings.functions`에 등록된 함수들을 검사하여, 데코레이터가 누락된 함수가 있을 경우 자동으로 `@traced_worker_task`로 감싸 계측을 보장합니다.
2. **테스트 타임 검증 (`test_all_worker_settings_tasks_have_instrumentation`)**: `tests/test_observability.py`에 회귀 테스트를 추가하여, `WorkerSettings.functions`와 `cron_jobs`에 등록된 모든 태스크가 계측 배선을 갖추었는지 검증합니다.

---

## 4. 검증 결과

| 검증 항목 | 명령어 | 결과 |
| --- | --- | --- |
| 관측성 회귀 테스트 (17개) | `uv run pytest tests/test_observability.py -v` | 통과 (17 passed in 0.24s) |
| 스케줄 태스크 회귀 테스트 (14개) | `uv run pytest tests/test_scheduled_tasks.py -v` | 통과 (14 passed in 0.17s) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | 통과 (3624 passed, 41 skipped in 191s) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 (20/20 passed) |

---

## 5. 결론 및 향후 유지보수 지침

- 실패한 Arq 작업의 최상위 span이 정상적으로 `StatusCode.ERROR`로 수집기에 전송되며 `exception` 스택 트레이스 이벤트가 기록됩니다.
- 신규 Arq 태스크 함수를 작성할 때는 `@traced_worker_task` 데코레이터를 명시적으로 부여하며, 실수로 누락하더라도 `worker.py`의 런타임 보장 및 테스트 스위트가 이를 감지하여 누락을 방지합니다.
