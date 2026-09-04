# mypy 24건 결함 및 타입 표현 문제 정밀 분류 및 해결 보고서

> **작성일**: 2026-09-04
> **작성자**: Orca Worker (`term_d19cd515-f941-45af-ae06-e80132d7e399`)
> **Task ID**: `task_304f542fefbd`
> **Dispatch ID**: `ctx_ede083743fd0`
> **목적**: CI `lint-and-validate`를 차단하던 mypy 24건 오류를 억제(`# type: ignore`) 없이 전량 근본 수정하고, 런타임 결함과 타입 표현 문제를 분류하여 문서화

---

## 1. 개요 및 총괄 요약

`uv run mypy src scripts/backup_recovery.py` 실행 시 7개 파일에서 총 24건의 오류가 검출되었습니다.
외부 감사 보고서는 이를 전부 잠재적 `AttributeError` 위험으로 과장 보고하였으나, 실제 코드 및 런타임 동작을 면밀히 분석한 결과는 다음과 같습니다:

- **(a) 실제 런타임 결함 (1건)**: `src/app/core/observability.py:236`의 `trace.reset_span(token)`. `opentelemetry.trace` 모듈에 존재하지 않는 API를 호출하고 있었으며, `except Exception` 블록에 의해 조용히 은폐되어 Arq 워커 작업 간 분산 추적 컨텍스트 누수를 유발하고 있었습니다.
- **(b) 타입 표현 문제 (23건)**: 런타임에는 정상적인 분기 및 인스턴스 검사로 안전하게 실행되지만, 타입 어노테이션 부재, 가변 키워드 인자(`**kwargs`) 타입 불일치, SQLAlchemy의 `Result` 스텁 한계, 또는 불리언 플래그 기반 세션 분기(`own_session = db is None`)로 인해 mypy가 정적 좁히기(Narrowing)를 추적하지 못해 발생한 문제입니다.

본 작업에서는 `# type: ignore`를 일절 추가하지 않고, `pyproject.toml` 설정을 일체 완화하지 않으며, 전량 올바른 API 호출 및 타입 좁히기 리팩터링으로 24건을 0건으로 해소했습니다.

---

## 2. 24건 전량 분류 및 해결 내역 표

| 번호 | 파일 경로 및 라인 | mypy 오류 코드 | 분류 | 발생 원인 및 런타임 영향 | 수정 방식 |
|---|---|---|---|---|---|
| 1 | `scripts/backup_recovery.py:312` | `[var-annotated]` | (b) 타입 표현 | `drill_start, timings, errors = datetime.now(UTC), {}, []` 다중 할당으로 빈 딕셔너리 타입 추론 불가 | 할당문을 분리하고 `timings: dict[str, Any] = {}`, `errors: list[str] = []`로 명시적 타입 지정 |
| 2 | `src/app/core/observability.py:170` | `[arg-type]` (endpoint) | (b) 타입 표현 | `otlp_kwargs = {"endpoint": endpoint}` 딕셔너리가 `dict[str, str]`로 추론되어 `**otlp_kwargs` 언패킹 시 다른 생성자 인자 타입과 충돌 | 딕셔너리 언패킹을 제거하고 `OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()`로 직접 전달 |
| 3 | `src/app/core/observability.py:170` | `[arg-type]` (headers) | (b) 타입 표현 | 위 2번 언패킹에 따른 연쇄 충돌 | 위 2번 수정으로 함께 해소 |
| 4 | `src/app/core/observability.py:170` | `[arg-type]` (timeout) | (b) 타입 표현 | 위 2번 언패킹에 따른 연쇄 충돌 (`float | None` 기대) | 위 2번 수정으로 함께 해소 |
| 5 | `src/app/core/observability.py:170` | `[arg-type]` (compression) | (b) 타입 표현 | 위 2번 언패킹에 따른 연쇄 충돌 (`Compression | None` 기대) | 위 2번 수정으로 함께 해소 |
| 6 | `src/app/core/observability.py:170` | `[arg-type]` (session) | (b) 타입 표현 | 위 2번 언패킹에 따른 연쇄 충돌 (`Session | None` 기대) | 위 2번 수정으로 함께 해소 |
| 7 | `src/app/core/observability.py:236` | `[attr-defined]` | **(a) 실제 런타임 결함** | `opentelemetry.trace`에 `reset_span` 함수가 없음. 예외가 swallow되어 컨텍스트 토큰이 detach되지 않고 워커 작업 간 컨텍스트 누수 발생 | `opentelemetry.context`를 임포트하여 `context.attach(trace.set_span_in_context(span))` 및 `context.detach(token)`으로 정상화하고 단위 테스트 추가 |
| 8 | `src/app/services/automation_orchestrator.py:452` | `[attr-defined]` | (b) 타입 표현 | `db.execute(stmt)`가 UPDATE 문에서 런타임에 `CursorResult`를 반환하나 정적 타입 스텁이 `Result[Any]`로 선언되어 `rowcount` 미인식 | `from sqlalchemy.engine import CursorResult` 임포트 후 `if isinstance(result, CursorResult) and result.rowcount == 0:`로 안전하게 타입 좁히기 |
| 9 | `src/tasks/retrain_task.py:124` | `[union-attr]` (`.add`) | (b) 타입 표현 | `own_session = db is None` 후 삼항 연산자로 `session` 할당 시 mypy가 `Session | None`으로 추론하여 `add` 속성 경고 | `if db is None:` 분기에서 `SessionLocal()` 생성 및 `own_session = True`, `else:`에서 `session = db`, `own_session = False`로 명시적 좁히기 |
| 10 | `src/tasks/retrain_task.py:133` | `[union-attr]` (`.commit`) | (b) 타입 표현 | 위 9번과 동일 | 위 9번 수정으로 함께 해소 |
| 11 | `src/tasks/retrain_task.py:136` | `[union-attr]` (`.close`) | (b) 타입 표현 | 위 9번과 동일 | 위 9번 수정으로 함께 해소 |
| 12 | `src/tasks/automation_tasks.py:143` | `[arg-type]` | (b) 타입 표현 | `own_session = caller_db is None` 삼항식으로 `session`이 `Session | None`으로 남아 `get_automation_request` 인자 타입 충돌 | `if caller_db is None:` 분기에서 `SessionLocal()` 생성 및 `own_session = True`, `else:`에서 `session = caller_db`, `own_session = False`로 명시적 좁히기 |
| 13 | `src/tasks/automation_tasks.py:146` | `[arg-type]` | (b) 타입 표현 | 위 12번과 동일 (`apply_callback_payload` 인자 타입 충돌) | 위 12번 수정으로 함께 해소 |
| 14 | `src/tasks/automation_tasks.py:150` | `[union-attr]` (`.rollback`) | (b) 타입 표현 | 위 12번과 동일 (`session.rollback()` 호출 경고) | 위 12번 수정으로 함께 해소 |
| 15 | `src/tasks/automation_tasks.py:155` | `[union-attr]` (`.close`) | (b) 타입 표현 | 위 12번과 동일 (`session.close()` 호출 경고) | 위 12번 수정으로 함께 해소 |
| 16 | `src/tasks/scheduled_tasks.py:118` | `[union-attr]` (`.add`) | (b) 타입 표현 | `_create_scheduled_execution`에서 `own_session = db is None` 삼항식 사용으로 인한 미좁힘 | `if db is None: session = SessionLocal(); own_session = True` else `session = db; own_session = False` 분기로 재작성 |
| 17 | `src/tasks/scheduled_tasks.py:133` | `[union-attr]` (`.commit`) | (b) 타입 표현 | 위 16번과 동일 | 위 16번 수정으로 함께 해소 |
| 18 | `src/tasks/scheduled_tasks.py:137` | `[union-attr]` (`.close`) | (b) 타입 표현 | 위 16번과 동일 | 위 16번 수정으로 함께 해소 |
| 19 | `src/tasks/scheduled_tasks.py:397` | `[union-attr]` (`.add`) | (b) 타입 표현 | `_record_drift_log`에서 `own_session = db is None` 삼항식 사용으로 인한 미좁힘 | `if db is None: session = SessionLocal(); own_session = True` else `session = db; own_session = False` 분기로 재작성 |
| 20 | `src/tasks/scheduled_tasks.py:406` | `[union-attr]` (`.commit`) | (b) 타입 표현 | 위 19번과 동일 | 위 19번 수정으로 함께 해소 |
| 21 | `src/tasks/scheduled_tasks.py:409` | `[union-attr]` (`.close`) | (b) 타입 표현 | 위 19번과 동일 | 위 19번 수정으로 함께 해소 |
| 22 | `src/tasks/scheduled_tasks.py:837` | `[union-attr]` (`.execute`) | (b) 타입 표현 | `get_latest_collection_time`에서 `own_session = db is None` 삼항식 사용으로 인한 미좁힘 | `if db is None: session = SessionLocal(); own_session = True` else `session = db; own_session = False` 분기로 재작성 |
| 23 | `src/tasks/scheduled_tasks.py:840` | `[union-attr]` (`.close`) | (b) 타입 표현 | 위 22번과 동일 | 위 22번 수정으로 함께 해소 |
| 24 | `src/app/api/v1/chatbot.py:438` | `[arg-type]` | (b) 타입 표현 | `_run_chat` 2번째 매개변수가 `payload: ChatRequest | None`으로 선언되어 있으나, 호출부 `asyncio.to_thread(_run_chat, payload, user.id if user else None)`에서 `int | None`을 전달하여 불일치 발생. 런타임에는 내부 `uid = payload if isinstance(payload, int) else user_id` 처리로 정상 동작함 | `_run_chat` 2번째 인자 타입을 `payload: ChatRequest | int | None = None`으로 수정하여 호출부 전달 타입과 완전 일치시킴 (570라인 상한 준수) |

---

## 3. 핵심 수정 상세 분석

### 3.1 `src/app/core/observability.py:236` (실제 런타임 결함)
- **증상**: Arq 작업 시작(`arq_on_job_start`) 시 `trace.use_span(...)`의 컨텍스트 제너레이터를 토큰으로 오인해 보관하고, 작업 종료(`arq_on_job_end`) 시 `trace.reset_span(token)`이라는 존재하지 않는 API를 호출했습니다. `AttributeError`가 `except Exception`에 의해 조용히 무시되면서 작업 간 컨텍스트 토큰이 정상적으로 해제(detach)되지 않는 누수가 발생했습니다.
- **해결**: 표준 OpenTelemetry Context API(`opentelemetry.context`)를 도입하여 `context.attach(trace.set_span_in_context(span))`로 토큰을 획득하고, 종료 시 `context.detach(token)`을 직접 호출하도록 수정했습니다.
- **회귀 방지 검증**: `tests/test_observability.py`에 `test_arq_context_token_detach_lifecycle` 테스트를 추가하여 Arq 작업 전-중-후 컨텍스트 스팬 바인딩 및 토큰 detach가 정상 작동함을 단언했습니다.

### 3.2 `src/app/api/v1/chatbot.py:438` (시그니처 타입 표현 불일치 판정)
- **코드 실측 결과**:
  ```python
  def _run_chat(
      payload_or_db: Session | ChatRequest,
      payload: ChatRequest | int | None = None,
      user_id: int | None = None,
  ) -> ChatResponse:
      if isinstance(payload_or_db, Session):
          req_payload = payload if isinstance(payload, ChatRequest) else ChatRequest(message="")
          uid = user_id
          session = payload_or_db
          should_close = False
      else:
          req_payload = payload_or_db
          uid = payload if isinstance(payload, int) else user_id
          session, should_close = open_thread_session()
  ```
  `chat_api`는 `_run_chat(payload, user.id if user else None)` 형태로 호출합니다. 런타임에서는 `payload`가 `int`일 때 `uid`로 승계되고, `user`가 `None`일 때 `user_id` 기본값인 `None`으로 안전하게 동작하므로 결함이 터지지 않았습니다. 그러나 정적 시그니처 상 2번째 인자가 `ChatRequest | None`으로만 묶여 있어 mypy 오류를 유발했습니다.
- **해결 및 라인 상한 준수**: 2번째 매개변수 타입을 `ChatRequest | int | None = None`으로 수정하여 타입 정합성을 확보하였으며, `tests/test_chatbot_api_split.py`의 `chatbot.py <= 570줄` 제한(실측 558줄)을 완벽히 준수했습니다.

### 3.3 `Session | None` 계열 13건의 무결성 보존 좁히기
- `retrain_task.py`(3건), `automation_tasks.py`(4건), `scheduled_tasks.py`(8건 중 8건)의 총 15건(관련 오류 포함)은 `own_session = db is None`이라는 별도 bool 변수와 삼항식으로 인해 발생했습니다.
- 런타임에 None이 전달되는 경로가 없음을 확인하였으며, `if db is None:` 분기 내에서 `session = SessionLocal()` 및 `own_session = True`를 한 묶음으로 처리하고, `else:`에서 `session = db`, `own_session = False`로 처리하여 세션 소유권 및 생명주기 동작의 변경 없이 mypy가 `session`을 `Session`으로 명확히 인식하도록 개선했습니다.

---

## 4. 검증 결과

1. **mypy 검사**:
   - `uv run mypy src scripts/backup_recovery.py`: `Success: no issues found in 93 source files` (오류 0건)
   - `uv run mypy src`: `Success: no issues found in 92 source files` (오류 0건)
2. **코드 스타일 및 규칙 검사**:
   - `uv run ruff check .`: 통과 (`All checks passed!`)
   - `uv run ruff format --check .`: 통과 (`484 files already formatted`)
   - `python3 scripts/validate_agent_rules.py --quiet`: 통과 (`20/20 건`)
3. **단위 및 통합 테스트**:
   - `uv run pytest tests/ -q -m 'not data_assets'`: `3485 passed, 40 skipped, 3 deselected in 96.26s` (전량 통과)
   - `tests/test_observability.py`: `11 passed in 0.40s`
   - `tests/test_chatbot_api_split.py`: `7 passed in 0.02s`
