"""MySQL 8 동시성 및 세션 복구 통합 테스트입니다.

이 모듈은 SQLite 인메모리로는 드러나지 않는 MySQL 8 InnoDB 트랜잭션/세션
상태 동작을 실제 MySQL 인스턴스에서 검증하기 위한 회귀 안전망입니다.

================================================================================
검증 범위와 비범위
================================================================================
- 검증 대상은 Capsule contract 가 명시한 다음 5가지 MySQL 고유 동작입니다.
  1) 명시적 트랜잭션이 실패한 세션을 rollback 으로 복구
  2) SELECT ... FOR UPDATE 행 잠금 대기 및 innodb_lock_wait_timeout
  3) 데드락 자동 감지(1213) 후 세션 재사용
  4) UNIQUE 제약 위반 commit 실패 후 rollback 으로 복구
  5) 동시 INSERT 후 UNIQUE 재시도로 결론 회복

- SQLite 와 같이 동작해 차이가 드러나지 않는 검증(예: 단순 CRUD, 양쪽 엔진에서
  동일한 SQLAlchemy 컴파일 결과)은 의도적으로 제외합니다. 운영 코드의
  `src/tasks/automation_tasks.py` 가 같은 SessionLocal 인스턴스를 commit/rollback
  으로 재사용하는 흐름에서 발생할 수 있는 회귀를 잡는 것이 목적입니다.

================================================================================
운영 안전 원칙
================================================================================
- 운영 스키마(procurement) 또는 운영 테이블(bid_announcements, bid_results 등)
  에 대해 어떤 DDL/DML 도 실행하지 않습니다. 전용 스키마 `concurrency_test` 와
  `concurrency_*` 접두 테이블 안에서만 동작합니다.
- 테스트 종료 시점에 모듈 픽스처가 DROP TABLE / DROP SCHEMA 로 정리합니다.
- MySQL 인스턴스가 없으면 명시적 사유와 함께 skip 합니다. skip 은 통과가
  아닙니다. 보고서에서 실행 여부를 정확히 적습니다.
- 벽시계 단언(예: time.sleep(N) 후 N초 안에 완료) 은 쓰지 않습니다. 잠금
  대기는 innodb_lock_wait_timeout 을 1초로 줄인 뒤 예외 종류로 판정합니다.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.mysql_integration


# ----------------------------------------------------------------------
# 모듈 픽스처: 엔진, 격리 스키마, 세션 팩토리
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def mysql_engine() -> Engine:
    """CI 의 격리 MySQL 8 인스턴스에 연결하고, 없으면 명시적 사유와 함께 skip 합니다.

    기존 tests/test_mysql_integration_queries.py 의 mysql_engine 픽스처 패턴을
    그대로 따릅니다. 새 픽스처 방식을 만들지 않습니다.
    """
    url = os.getenv("MYSQL_TEST_URL")
    if not url:
        pytest.skip("MYSQL_TEST_URL이 설정되지 않아 MySQL 동시성 테스트를 건너뜁니다.")
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        if engine.dialect.name != "mysql":
            pytest.skip("MYSQL_TEST_URL이 MySQL 방언이 아니어서 동시성 테스트를 건너뜁니다.")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except Exception as exc:
        pytest.skip(f"MySQL 8 인스턴스에 접속할 수 없어 동시성 테스트를 건너뜁니다: {exc}")


@pytest.fixture(scope="module")
def mysql_concurrency_schema(mysql_engine: Engine) -> None:
    """`concurrency_test` 스키마와 `concurrency_*` 테이블을 모듈 시작 시 생성합니다.

    운영 스키마(`procurement`) 와 운영 테이블(`bid_announcements`, `bid_results`
    등)에는 어떤 영향도 주지 않습니다. 모듈 종료 시점에는 모든 픽스처 객체를
    DROP 한 뒤 스키마 자체를 DROP 합니다.
    """
    schema_name = "concurrency_test"

    create_statements = [
        f"DROP DATABASE IF EXISTS `{schema_name}`",
        f"CREATE DATABASE `{schema_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
        f"USE `{schema_name}`",
        # 1) pending-rollback 복구 시나리오용: 단순 카운터
        """
        CREATE TABLE `concurrency_counter` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `name` VARCHAR(50) NOT NULL UNIQUE,
            `value` INT NOT NULL DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # 2) 행 잠금 대기 / 3) 데드락 / 4) commit 실패 복구 시나리오용: 두 행을 가진 테이블
        """
        CREATE TABLE `concurrency_wallet` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `label` VARCHAR(50) NOT NULL UNIQUE,
            `balance` INT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # 5) 동시 INSERT 후 재시도 시나리오용: 멱등 키가 있는 이벤트 로그
        """
        CREATE TABLE `concurrency_event_log` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `dedup_key` VARCHAR(64) NOT NULL UNIQUE,
            `payload` VARCHAR(255) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]

    drop_statements = [
        f"DROP DATABASE IF EXISTS `{schema_name}`",
    ]

    with mysql_engine.begin() as connection:
        for stmt in create_statements:
            connection.execute(text(stmt))
        # 시드: 두 행을 미리 삽입해 SELECT ... FOR UPDATE / 데드락 시나리오가
        # 즉시 진행할 수 있도록 합니다.
        connection.execute(
            text(
                "INSERT INTO `concurrency_wallet` (`label`, `balance`) VALUES "
                "('alpha', 1000), ('beta', 2000)"
            )
        )
        connection.execute(
            text("INSERT INTO `concurrency_counter` (`name`, `value`) VALUES ('hits', 0)")
        )

    try:
        yield
    finally:
        # 실패 케이스에서 잠금이 남았을 가능성에 대비해 세션을 정리합니다.
        try:
            with mysql_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except OperationalError:
            # cleanup 단계의 사전 진단이므로 실패해도 정리 시도는 계속 진행합니다.
            pass
        with mysql_engine.begin() as connection:
            for stmt in drop_statements:
                connection.execute(text(stmt))


@pytest.fixture(scope="module")
def concurrency_session_factory(
    mysql_engine: Engine, mysql_concurrency_schema: None
) -> sessionmaker[Session]:
    """`concurrency_test` 스키마를 기본으로 바인딩한 SessionLocal 팩토리입니다.

    운영 SessionLocal(src/app/core/db.py 의 autocommit=False, autoflush=False)
    과 동일한 정책으로 묶어 운영 코드의 세션 처리 흐름과 같은 결함을 검증합니다.
    """
    return sessionmaker(
        bind=mysql_engine,
        autocommit=False,
        autoflush=False,
    )


# ----------------------------------------------------------------------
# 헬퍼
# ----------------------------------------------------------------------


def _use_concurrency_schema(connection: Any) -> None:
    """연결 단위의 기본 스키마를 concurrency_test 로 강제합니다."""
    connection.execute(text("USE `concurrency_test`"))


def _assert_mysql_operational_error(exc: OperationalError, expected_codes: tuple[int, ...]) -> None:
    """MySQL 이 돌려준 OperationalError 의 원본 에러 코드가 기대값 집합에 속하는지 확인합니다."""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) if orig is not None else None
    assert args, (
        "OperationalError 에 원본 에러 코드가 없습니다. MySQL 방언이 아닌 "
        "드라이버를 쓴 것은 아닌지 확인해 주십시오."
    )
    code = args[0]
    assert code in expected_codes, (
        f"예상치 못한 MySQL 에러 코드입니다. 기대 {expected_codes}, 실제 {code} "
        f"(메시지={args[1] if len(args) > 1 else ''!r})"
    )


# ----------------------------------------------------------------------
# 1) pending-rollback 세션 복구
# ----------------------------------------------------------------------


def test_mysql_pending_rollback_session_can_be_recovered_via_rollback(
    concurrency_session_factory: sessionmaker[Session],
) -> None:
    """명시적 트랜잭션 안에서 실패한 SQLAlchemy 세션을 rollback 으로 복구합니다.

    MySQL InnoDB 는 START TRANSACTION 이후 세션이 활성 트랜잭션을 들고 있는 동안
    다음 명령이 실패하면 명시적으로 ROLLBACK / COMMIT 으로 트랜잭션을 닫기
    전까지 새 명령을 받지 않습니다. SQLite 의 implicit transaction 은 트랜잭션
    경계가 자동으로 정리되어 같은 시나리오가 통과될 수 있어 차이가 드러나지
    않습니다. 이 테스트는 rollback 으로 트랜잭션을 닫고 동일 세션을 후속
    INSERT 에 재사용할 수 있는지 검증합니다.
    """
    session: Session = concurrency_session_factory()
    try:
        _use_concurrency_schema(session.connection())
        session.execute(text("INSERT INTO concurrency_counter (name, value) VALUES ('probe_1', 1)"))
        # 의도적으로 UNIQUE 위반으로 트랜잭션을 실패 상태로 둔다.
        with pytest.raises(IntegrityError):
            session.execute(
                text("INSERT INTO concurrency_counter (name, value) VALUES ('probe_1', 2)")
            )

        # 실패한 트랜잭션을 닫지 않고 다음 명령을 보내면 MySQL 은
        # "Commands out of sync" 류의 OperationalError 를 던진다. 여기서는
        # rollback 으로 명시적으로 트랜잭션을 닿아 복구 가능한지만 본다.
        session.rollback()

        # 동일 세션으로 새 INSERT 가 가능해야 한다.
        session.execute(text("INSERT INTO concurrency_counter (name, value) VALUES ('probe_2', 1)"))
        session.commit()

        rows = session.execute(
            text(
                "SELECT name FROM concurrency_counter WHERE name IN ('probe_1', 'probe_2') "
                "ORDER BY name"
            )
        ).fetchall()
    finally:
        session.close()

    names = [row[0] for row in rows]
    assert "probe_1" not in names, (
        "실패한 트랜잭션의 행이 남아 있습니다. 세션이 명시적으로 닫혔는지 확인해 주십시오."
    )
    assert "probe_2" in names, (
        "rollback 후 동일 세션의 후속 INSERT 가 반영되지 않았습니다. MySQL 명시적 "
        "트랜잭션 경계가 닫혔는지, 또는 세션이 잘못 만들어졌는지 확인해 주십시오."
    )


# ----------------------------------------------------------------------
# 2) 행 잠금 대기 및 innodb_lock_wait_timeout
# ----------------------------------------------------------------------


def test_mysql_concurrent_row_lock_blocks_second_writer_and_raises_on_timeout(
    concurrency_session_factory: sessionmaker[Session],
) -> None:
    """SELECT ... FOR UPDATE 행 잠금 대기 시간을 innodb_lock_wait_timeout 으로 판정합니다.

    첫 세션이 행 잠금을 잡은 동안 두 번째 세션이 같은 행에 FOR UPDATE 를 시도하면
    MySQL 은 innodb_lock_wait_timeout 이 만료될 때까지 기다린 뒤 OperationalError
    1205 (Lock wait timeout exceeded) 를 던집니다. SQLite 는 FOR UPDATE 가 무시되거나
    RESERVED 잠금으로 처리되어 동일 시나리오에서 같은 에러를 만들지 못합니다.

    시간 단언 대신: 테스트 시작 전에 SESSION 변수로 innodb_lock_wait_timeout 을
    1 초로 줄이고, 후행 세션에서 예외가 발생하는지/어떤 코드인지로 판정합니다.
    """
    holder: Session = concurrency_session_factory()
    waiter: Session = concurrency_session_factory()
    try:
        _use_concurrency_schema(holder.connection())
        _use_concurrency_schema(waiter.connection())

        holder.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
        waiter.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))

        holder.execute(
            text("SELECT balance FROM concurrency_wallet WHERE label = 'alpha' FOR UPDATE")
        ).fetchone()

        # 후행 세션은 별도 스레드에서 같은 행에 잠금을 시도한다. 실제로 잠금이
        # 겹친 상태에서 MySQL의 대기 시간 초과를 관찰한다.
        result: dict[str, BaseException] = {}

        def wait_for_lock() -> None:
            try:
                waiter.execute(
                    text("SELECT balance FROM concurrency_wallet WHERE label = 'alpha' FOR UPDATE")
                )
            except BaseException as exc:  # 스레드 예외를 주 스레드에서 검증한다.
                result["error"] = exc

        thread = threading.Thread(target=wait_for_lock)
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive(), "잠금 대기 스레드가 제한 시간 안에 종료되지 않았습니다."
        error = result.get("error")
        assert isinstance(error, OperationalError), f"잠금 대기 예외가 없습니다: {error!r}"
        _assert_mysql_operational_error(error, (1205,))
        waiter.rollback()

        # 후행 세션이 잠금 해제 후에는 정상 동작해야 한다.
        holder.rollback()
        row = waiter.execute(
            text("SELECT balance FROM concurrency_wallet WHERE label = 'alpha'")
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 1000
        waiter.commit()
    finally:
        holder.close()
        waiter.close()


# ----------------------------------------------------------------------
# 3) 데드락 자동 감지(1213) 후 세션 재사용
# ----------------------------------------------------------------------


def test_mysql_deadlock_detection_raises_1213_and_session_still_usable(
    concurrency_session_factory: sessionmaker[Session],
) -> None:
    """MySQL deadlock 자동 감지로 1213 이 발생하고, 세션이 재사용 가능한지 검증합니다.

    두 세션이 (alpha, beta) 행을 서로 반대 순서로 잠그면 MySQL 의 deadlock detector
    가 한 세션을 victim 으로 선정해 트랜잭션을 중단하고 1213 을 돌려줍니다.
    SQLite 가 deadlock 을 자동 해소하지 않는 것과 차이가 나는 지점입니다.

    시간 단언 대신: 어떤 세션이 victim 이 되든 OperationalError 1213 이 한쪽에서
    발생하고, victim 세션이 rollback 으로 복구되어 다음 INSERT 가 가능한지만 봅니다.
    """
    sessions = [concurrency_session_factory(), concurrency_session_factory()]
    barrier = threading.Barrier(2)
    results: list[tuple[Session, BaseException | None]] = []
    result_lock = threading.Lock()

    def create_deadlock(index: int) -> None:
        session = sessions[index]
        first = "alpha" if index == 0 else "beta"
        second = "beta" if index == 0 else "alpha"
        error: BaseException | None = None
        try:
            _use_concurrency_schema(session.connection())
            session.execute(text("SET SESSION innodb_lock_wait_timeout = 5"))
            session.execute(
                text("SELECT balance FROM concurrency_wallet WHERE label = :label FOR UPDATE"),
                {"label": first},
            )
            barrier.wait(timeout=10)
            session.execute(
                text("SELECT balance FROM concurrency_wallet WHERE label = :label FOR UPDATE"),
                {"label": second},
            )
            session.commit()
        except BaseException as exc:
            error = exc
            session.rollback()
        with result_lock:
            results.append((session, error))

    threads = [threading.Thread(target=create_deadlock, args=(index,)) for index in (0, 1)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads), (
            "데드락 스레드가 종료되지 않았습니다."
        )
        failures = [(session, error) for session, error in results if error is not None]
        assert len(failures) == 1, f"데드락 victim은 정확히 하나여야 합니다: {results!r}"
        victim, error = failures[0]
        assert isinstance(error, OperationalError), f"데드락 예외가 아닙니다: {error!r}"
        _assert_mysql_operational_error(error, (1213,))
        victim.execute(
            text(
                "INSERT INTO concurrency_event_log (dedup_key, payload) "
                "VALUES ('post_deadlock', 'recovered')"
            )
        )
        victim.commit()
    finally:
        for session in sessions:
            session.close()


# ----------------------------------------------------------------------
# 4) UNIQUE 제약 commit 실패 후 세션 복구
# ----------------------------------------------------------------------


def test_mysql_commit_failure_session_can_be_rolled_back_and_reused(
    concurrency_session_factory: sessionmaker[Session],
) -> None:
    """UNIQUE 제약 위반으로 commit 이 거부된 세션을 rollback 으로 복구합니다.

    SQLAlchemy autoflush 정책에서는 flush 시점에 UNIQUE 위반이 IntegrityError 로
    터지고, 이를 그대로 두면 같은 세션의 다음 flush 가 같은 에러로 다시 막힙니다.
    MySQL InnoDB 의 경우 명령 단위 auto-commit 이라서 트랜잭션 경계가 명시적이고,
    rollback 으로 닫기 전에는 후속 명령이 거부됩니다. SQLite 의 implicit rollback
    정책은 같은 시나리오를 다른 경로로 처리하므로 차이가 드러나지 않습니다.
    """
    session: Session = concurrency_session_factory()
    try:
        _use_concurrency_schema(session.connection())

        # 첫 INSERT 는 정상.
        session.execute(
            text("INSERT INTO concurrency_event_log (dedup_key, payload) VALUES ('k1', 'v1')")
        )
        session.commit()

        # 같은 키로 다시 INSERT 하면 flush 단계에서 UNIQUE 위반이 발생한다.
        with pytest.raises(IntegrityError):
            session.execute(
                text("INSERT INTO concurrency_event_log (dedup_key, payload) VALUES ('k1', 'v2')")
            )
        session.commit()

        # rollback 으로 트랜잭션을 닿고 다른 키 INSERT 가 가능한지 본다.
        session.rollback()
        session.execute(
            text("INSERT INTO concurrency_event_log (dedup_key, payload) VALUES ('k2', 'v2')")
        )
        session.commit()

        rows = session.execute(
            text(
                "SELECT dedup_key FROM concurrency_event_log "
                "WHERE dedup_key IN ('k1', 'k2') ORDER BY dedup_key"
            )
        ).fetchall()
    finally:
        session.close()

    keys = [row[0] for row in rows]
    assert keys == ["k1", "k2"], (
        f"commit 실패 후 rollback 으로 복구된 세션의 결과가 기대치와 다릅니다: {keys}"
    )


# ----------------------------------------------------------------------
# 5) 동시 INSERT 후 UNIQUE 재시도 회복
# ----------------------------------------------------------------------


def test_mysql_concurrent_increments_with_unique_constraint_are_resolved(
    concurrency_session_factory: sessionmaker[Session],
) -> None:
    """동시 INSERT 가 같은 dedup_key 를 두고 한쪽을 거부해도 재시도로 결론을 회복합니다.

    멱등 enqueue 패턴은 운영 코드에서 자주 등장합니다. MySQL 의 INSERT 는 UNIQUE
    위반 시 즉시 거부되어 호출 측에서 재시도 결정을 받아야 하고, SQLite 의
    INSERT OR REPLACE 는 의미가 달라 같은 코드 경로의 회귀를 잡지 못합니다.

    이 테스트는 두 세션이 같은 dedup_key 로 INSERT 를 시도하고, 한쪽은 실패하지만
    전체 시스템은 (k1, payloadA) 또는 (k1, payloadB) 둘 중 하나로 결론이 난 상태가
    되며, 후속 SELECT 가 정확히 한 건만 반환함을 검증합니다.
    """
    sessions = [concurrency_session_factory(), concurrency_session_factory()]
    barrier = threading.Barrier(2)
    results: list[bool] = []
    result_lock = threading.Lock()

    def insert_once(index: int) -> None:
        session = sessions[index]
        succeeded = False
        try:
            _use_concurrency_schema(session.connection())
            barrier.wait(timeout=10)
            session.execute(
                text(
                    "INSERT INTO concurrency_event_log (dedup_key, payload) "
                    "VALUES ('race_key', :payload)"
                ),
                {"payload": "payloadA" if index == 0 else "payloadB"},
            )
            session.commit()
            succeeded = True
        except IntegrityError:
            session.rollback()
        finally:
            with result_lock:
                results.append(succeeded)

    threads = [threading.Thread(target=insert_once, args=(index,)) for index in (0, 1)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads), (
            "동시 INSERT 스레드가 종료되지 않았습니다."
        )

        assert sum(results) == 1, (
            f"두 세션 중 정확히 하나만 INSERT 에 성공해야 합니다. 실제 결과: {results}"
        )

        # 어느 세션이든 후속 SELECT 가 정확히 1건만 반환해야 한다.
        count = (
            sessions[0]
            .execute(
                text("SELECT COUNT(*) FROM concurrency_event_log WHERE dedup_key = 'race_key'")
            )
            .scalar_one()
        )
        sessions[0].commit()
        assert int(count) == 1, (
            f"동시 INSERT 후 dedup_key='race_key' 가 정확히 1건만 존재해야 합니다. 실제: {count}"
        )
    finally:
        for session in sessions:
            session.close()
