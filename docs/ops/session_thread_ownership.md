# SQLAlchemy Session 스레드 소유권 및 격리 규칙

> **작성일**: 2026-09-03
> **상태**: 확정 (Active)
> **관련 테스트**: `tests/test_session_thread_ownership.py`, `tests/test_session_ownership.py`

---

## 1. 개요 및 배경

FastAPI 와 비동기 이벤트 루프(asyncio) 환경에서 SQLAlchemy 의 동기 ORM `Session` 객체를 `asyncio.to_thread` 등의 워커 스레드로 넘겨 사용하면 다음과 같은 심각한 동시성 결함이 발생합니다:

1. **드라이버 연결 상태 경합**: 하나의 물리 커넥션을 복수의 스레드가 동시에 점유하거나 재진입할 위험.
2. **Identity Map 오염**: SQLAlchemy 세션 내부의 객체 캐시(Identity Map)는 단일 스레드 전용으로 설계되어 다중 스레드 동시 접근 시 상태 불일치 유발.
3. **트랜잭션 경계 모호성**: 이벤트 루프와 워커 스레드 간 commit/rollback 책임 소재 분열.

본 저장소는 **"SQLAlchemy Session 은 생성된 스레드 문맥 내에서만 사용되고 소멸한다"** 는 엄격한 단일 스레드 소유권 원칙을 집행합니다.

---

## 2. 핵심 아키텍처 원칙

| 원칙 | 설명 |
| --- | --- |
| **단일 스레드 소유** | `Session` 객체는 생성된 스레드에서만 사용되며, `asyncio.to_thread` 인자로 전달되지 않습니다. |
| **순수 데이터 전송** | 스레드 경계를 넘는 데이터는 식별자, 스칼라, Pydantic 스키마, 순수 dict/list 로 제한됩니다. |
| **자체 수명 주기** | 워커 스레드에서 동작하는 동기 함수는 스레드 내부에서 `SessionLocal()`을 생성하고 `try...finally: session.close()`로 해제합니다. |
| **정적 검사 강제** | CI 및 테스트 파이프라인(`test_session_thread_ownership.py`)에서 AST 정적 검사로 위반을 차단합니다. |

---

## 3. 계층별 구현 패턴

### 3.1 API 계층 (FastAPI 라우트)

엔드포인트는 동기 DB 작업과 CPU 점유 연산을 스레드로 오프로드할 때, `db: Session = Depends(get_db)`를 스레드로 넘기지 않습니다.

```python
# 올바른 패턴 (Good)
def _authenticate_and_update_login(username: str, password: str) -> dict[str, Any]:
    db, should_close = _open_session()
    try:
        user = db.execute(select(CustomUser).where(CustomUser.username == username)).scalar_one_or_none()
        if not user or not check_password(password, user.password):
            return {"status": "invalid"}
        user.last_login = utcnow()
        db.commit()
        return {"status": "success", "user_id": user.id, "username": user.username}
    finally:
        if should_close:
            db.close()

@router.post("/accounts/login/")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    auth_result = await asyncio.to_thread(_authenticate_and_update_login, username, password)
    ...
```

### 3.2 태스크 및 서비스 계층 (Arq Worker & Services)

비동기 태스크에서 동기 작업을 스레드로 위임할 때, 스레드 전용 러너 또는 세션 래퍼를 사용합니다.

```python
# 올바른 패턴 (Good)
def _invoke_sync_runner(runner_fn: Callable[..., object], kwargs: dict[str, object]) -> object:
    sig = inspect.signature(runner_fn)
    if "db" in sig.parameters:
        runner_db = SessionLocal()
        try:
            return runner_fn(runner_db, **kwargs)
        finally:
            runner_db.close()
    return runner_fn(**kwargs)

# to_thread 호출 시 Session 객체를 전달하지 않음
outcome = await asyncio.to_thread(_invoke_sync_runner, runner_fn, kwargs)
```

---

## 4. AST 정적 검증 (`tests/test_session_thread_ownership.py`)

CI 파이프라인에서 다음 6개 핵심 모듈의 AST 를 분석하여 `asyncio.to_thread` 인자로 `db`, `session`, `db_session` 등이 넘어가는 패턴을 자동 검출합니다:

1. `src/app/api/ui.py`
2. `src/app/api/v1/chatbot.py`
3. `src/app/services/collector_service.py`
4. `src/tasks/automation_tasks.py`
5. `src/tasks/scheduled_tasks.py`
6. `src/tasks/retrain_task.py`
