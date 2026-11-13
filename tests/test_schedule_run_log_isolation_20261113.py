"""
tests/test_schedule_run_log_isolation_20261113.py

conftest 의 기본 격리가 실제로 운영 DB 쓰기를 막는지 고정합니다.

(1) 대역을 걸지 않은 테스트에서 `src.tasks.worker.SessionLocal` 이 운영 팩토리
    (`src.app.core.db.SessionLocal`)와 다른 객체여야 합니다.
(2) `record_schedule_result` 를 불러도 운영 엔진의 `connect` 가 호출되지 않아야
    합니다. 운영 엔진의 connect 를 실패 대역으로 바꿔 확인하며, 실제 MySQL 에는
    연결하지 않습니다.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.app.core import db
from src.tasks import worker


def test_worker_session_local_is_not_the_production_factory() -> None:
    """기본 상태에서 worker 의 세션 팩토리는 운영 엔진에 묶여 있지 않습니다."""
    assert worker.SessionLocal is not db.SessionLocal


def test_record_schedule_result_never_reaches_the_production_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실행 기록은 운영 엔진의 connect 를 부르지 않습니다.

    `_record_schedule_run` 은 기록 실패를 삼키므로 예외를 던지는 대역으로는
    호출 여부를 알 수 없습니다. 호출 횟수를 세어 0 임을 확인합니다.
    """
    connects: list[Any] = []

    def counting_connect(*args: Any, **kwargs: Any) -> Any:
        connects.append((args, kwargs))
        raise AssertionError("운영 DB 엔진에 연결하려 했습니다")

    monkeypatch.setattr(db.engine, "connect", counting_connect)

    worker.record_schedule_result("drift_monitor", {"status": "success"}, True)

    assert connects == []
