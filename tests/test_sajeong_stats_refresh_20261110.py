"""기관별 사정률 통계 재집계 연결(F-02) 검증.

막으려는 사고:
  - 예비가격 일일 증분이 새 행을 적재하고도 사정률 통계를 다시 집계하지 않는 것
  - 적재분이 없는데 매번 전량 재집계를 도는 것
  - 후속 연결·재집계 실패가 수집 결과 status 를 뒤집는 것
  - 스크립트와 태스크가 연결 로직을 각자 복제하는 것

운영 DB·나라장터 API·Redis 는 대역으로 대체하며 실호출과 운영 DB 쓰기를 하지
않습니다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from src.app.services import prearng_dminstt_link
from src.tasks import scheduled_tasks
from src.tasks.scheduled_tasks import prearng_daily_task

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _FakeSession:
    """close·commit·rollback 만 있는 DB 세션 대역."""

    def __init__(self) -> None:
        self.closed = False
        self.committed = 0
        self.rolled_back = 0

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


@pytest.fixture
def fake_env(monkeypatch):
    """세션과 후속 단계를 대역으로 바꾸고 호출 기록을 돌려줍니다."""
    session = _FakeSession()
    calls: dict[str, Any] = {"link": 0, "rebuild": 0, "order": []}
    rebuild_result = {
        "rows": 3,
        "institution_rows": 2,
        "region_rows": 0,
        "category_rows": 1,
        "window_days": 1095,
        "rebuilt_at": "2026-11-10T00:00:00",
    }

    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: ["R1"])
    monkeypatch.setattr(scheduled_tasks, "_bulk_insert", lambda db, model, rows: len(rows))
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *args, **kwargs: None)

    def _link(db):
        calls["link"] += 1
        calls["order"].append("link")
        calls["link_db"] = db
        return 5

    def _rebuild(db):
        calls["rebuild"] += 1
        calls["order"].append("rebuild")
        calls["rebuild_db"] = db
        return dict(rebuild_result)

    monkeypatch.setattr(scheduled_tasks, "link_prearng_dminstt", _link)
    monkeypatch.setattr(scheduled_tasks, "rebuild_institution_sajeong_rate_stats", _rebuild)
    return session, calls, rebuild_result


async def _stream_saving_one(notice_list, sink, num_of_rows=500):
    return sink([{"bid_ntce_no": "R1", "category": "Servc"}])


# ============================================================================
# 1. 새 행을 적재하면 연결과 재집계가 이어서 실행된다
# ============================================================================


@pytest.mark.asyncio
async def test_new_rows_trigger_link_and_rebuild_once(monkeypatch, fake_env) -> None:
    session, calls, rebuild_result = fake_env
    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _stream_saving_one)

    outcome = await prearng_daily_task({})

    assert outcome["status"] == "success"
    assert outcome["notice_count"] == 1
    assert outcome["saved"] == 1
    assert calls["link"] == 1
    assert calls["rebuild"] == 1
    assert calls["order"] == ["link", "rebuild"]
    assert outcome["linked"] == 5
    assert outcome["stats_rebuilt"] == rebuild_result
    assert calls["link_db"] is session
    assert calls["rebuild_db"] is session
    assert session.committed == 1
    assert session.closed is True


# ============================================================================
# 2. 적재분이 없으면 재집계하지 않는다
# ============================================================================


@pytest.mark.asyncio
async def test_zero_saved_rows_do_not_touch_stats(monkeypatch, fake_env) -> None:
    session, calls, _rebuild_result = fake_env

    async def _stream_nothing(notice_list, sink, num_of_rows=500):
        return 0

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _stream_nothing)

    outcome = await prearng_daily_task({})

    assert outcome == {"status": "success", "notice_count": 1, "saved": 0}
    assert calls["link"] == 0
    assert calls["rebuild"] == 0
    assert session.closed is True


@pytest.mark.asyncio
async def test_no_notices_skip_does_not_touch_stats(monkeypatch, fake_env) -> None:
    _session, calls, _rebuild_result = fake_env
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: [])

    async def _fail(*args, **kwargs):
        raise AssertionError("신규 공고가 없으면 나라장터를 호출하지 않아야 합니다")

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _fail)

    outcome = await prearng_daily_task({})

    assert outcome == {"status": "skipped", "reason": "no_new_notices", "notice_count": 0}
    assert calls["link"] == 0
    assert calls["rebuild"] == 0


# ============================================================================
# 3. 후속 단계가 실패해도 수집 결과 status 는 바뀌지 않는다
# ============================================================================


@pytest.mark.asyncio
async def test_rebuild_failure_does_not_change_collection_status(monkeypatch, fake_env) -> None:
    session, calls, _rebuild_result = fake_env

    def _rebuild_raises(db):
        calls["rebuild"] += 1
        raise RuntimeError("재집계 실패")

    monkeypatch.setattr(
        scheduled_tasks,
        "rebuild_institution_sajeong_rate_stats",
        _rebuild_raises,
    )
    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _stream_saving_one)

    outcome = await prearng_daily_task({})

    assert outcome["status"] == "success"
    assert outcome["saved"] == 1
    assert outcome["linked"] == 5
    assert outcome["stats_rebuilt"] is None
    assert session.rolled_back == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_link_failure_still_attempts_rebuild(monkeypatch, fake_env) -> None:
    _session, calls, rebuild_result = fake_env

    def _link_raises(db):
        calls["link"] += 1
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(scheduled_tasks, "link_prearng_dminstt", _link_raises)
    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _stream_saving_one)

    outcome = await prearng_daily_task({})

    assert outcome["status"] == "success"
    assert outcome["linked"] is None
    assert calls["rebuild"] == 1
    assert outcome["stats_rebuilt"] == rebuild_result


# ============================================================================
# 4. 스크립트와 태스크가 같은 연결 함수를 쓴다
# ============================================================================


def _load_script_module():
    name = "link_prearng_dminstt_single_source"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "link_prearng_dminstt.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_script_and_task_share_one_link_function() -> None:
    script = _load_script_module()

    assert script.link_prearng_dminstt is prearng_dminstt_link.link_prearng_dminstt
    assert scheduled_tasks.link_prearng_dminstt is prearng_dminstt_link.link_prearng_dminstt
    assert script.normalize_ord is prearng_dminstt_link.normalize_ord
