"""
tests/test_backfill_prearng_by_notices_20261111.py

용역 예비가격 상세 공고 단건 소급(scripts/backfill_prearng_by_notices.py) 검증.

막으려는 사고:
  - dry-run 이 나라장터를 호출해 호출 한도를 소모하는 것
  - --limit 을 넘겨 호출하거나 상한 5000 을 넘기는 것
  - 개찰일 범위 밖·이미 적재된 공고·용역 외 분야를 후보로 끌어오는 것
  - 적재가 없는데 사정률 후속 단계를 부르거나, 적재가 있는데 빠뜨리는 것
  - 실패 공고를 성공으로 보고해 조용히 누락하는 것

나라장터 API 와 운영 DB 는 대역(double)으로 대체하며 실호출과 쓰기를 하지 않습니다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scripts.backfill_prearng_by_notices as bf
from src.app.core.db import Base
from src.app.models.bids import BidAnnouncement
from src.app.models.prearng_prices import BidPrearngPrice
from src.app.services.api_collector import RangeCollectionError

SINCE = "2026-10-12"
UNTIL = "2026-11-10"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[BidAnnouncement.__table__, BidPrearngPrice.__table__],
    )
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_announcement(
    session: Any,
    notice_no: str,
    *,
    category: str = "Servc",
    openg_dt: datetime | None = None,
) -> None:
    session.add(BidAnnouncement(bid_ntce_no=notice_no, category=category, openg_dt=openg_dt))


def _add_prearng(session: Any, notice_no: str) -> None:
    session.add(
        BidPrearngPrice(
            bid_ntce_no=notice_no,
            bid_ntce_ord="000",
            bid_clsfc_no="0",
            rbid_no="000",
            category="Servc",
            collected_at=datetime(2026, 11, 1, 9, 0),
        )
    )


class _StubSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


# ============================================================================
# 1. dry-run 은 수집 함수를 부르지 않는다
# ============================================================================


def test_dry_run_never_calls_collector(db_session, monkeypatch, capsys) -> None:
    _add_announcement(db_session, "R-DRY", openg_dt=datetime(2026, 11, 1, 10, 0))
    db_session.commit()
    monkeypatch.setattr(bf, "SessionLocal", lambda: db_session)

    async def _fail(*args: Any, **kwargs: Any) -> int:
        raise AssertionError("dry-run 에서는 나라장터를 호출하지 않아야 합니다")

    monkeypatch.setattr(bf, "stream_servc_prearng_by_notices", _fail)

    code = bf.run(["--since", SINCE, "--until", UNTIL])

    assert code == 0
    captured = capsys.readouterr()
    assert "후보 공고 1건" in captured.out
    assert "dry-run" in captured.out


# ============================================================================
# 2. --limit 은 최근 개찰일부터 자르고, 상한 5000 을 넘길 수 없다
# ============================================================================


def test_limit_keeps_most_recent_openg_dates(db_session) -> None:
    for index, day in enumerate([1, 5, 9, 3]):
        _add_announcement(db_session, f"R-{index}", openg_dt=datetime(2026, 11, day, 10, 0))
    db_session.commit()

    candidates = bf.select_backfill_candidates(
        db_session, since=date(2026, 10, 12), until=date(2026, 11, 10), limit=2
    )

    assert [notice for notice, _ in candidates] == ["R-2", "R-1"]


def test_limit_above_cap_is_rejected() -> None:
    assert bf.run(["--since", SINCE, "--limit", "5001"]) == 2


def test_limit_is_not_forwarded_as_page_size(monkeypatch) -> None:
    calls: dict[str, Any] = {"stream": [], "kwargs": None}

    async def _stream(notices, sink, *args: Any, **kwargs: Any) -> int:
        calls["stream"].append(list(notices))
        calls["kwargs"] = kwargs
        return 1

    async def _followup(saved: int) -> dict[str, Any]:
        return {"linked": 0, "stats_rebuilt": None}

    monkeypatch.setattr(bf, "SessionLocal", _StubSession)
    monkeypatch.setattr(
        bf,
        "select_backfill_candidates",
        lambda db, **kwargs: [("R1", datetime(2026, 11, 1, 10, 0))],
    )
    monkeypatch.setattr(bf, "stream_servc_prearng_by_notices", _stream)
    monkeypatch.setattr(bf, "_run_sajeong_stats_followup", _followup)

    code = bf.run(["--since", SINCE, "--until", UNTIL, "--limit", "3", "--execute"])

    assert code == 0
    assert calls["stream"] == [["R1"]]
    assert calls["kwargs"] == {}


# ============================================================================
# 3. 후보 조건: 개찰일 범위, 예비가격 없음, 용역
# ============================================================================


def test_candidates_filter_range_category_and_collected(db_session) -> None:
    inside = datetime(2026, 11, 1, 10, 0)
    _add_announcement(db_session, "R-IN", openg_dt=inside)
    _add_announcement(db_session, "R-BEFORE", openg_dt=datetime(2026, 10, 11, 23, 0))
    _add_announcement(db_session, "R-AFTER", openg_dt=datetime(2026, 11, 11, 10, 0))
    _add_announcement(db_session, "R-COLLECTED", openg_dt=inside)
    _add_announcement(db_session, "T-IN", category="Thng", openg_dt=inside)
    _add_announcement(db_session, "R-NO-OPEN", openg_dt=None)
    _add_prearng(db_session, "R-COLLECTED")
    db_session.commit()

    result = bf.select_backfill_candidates(
        db_session, since=date(2026, 10, 12), until=date(2026, 11, 10), limit=10
    )

    assert [notice for notice, _ in result] == ["R-IN"]


# ============================================================================
# 4. 적재가 있으면 후속 단계를 한 번 부르고, 없으면 부르지 않는다
# ============================================================================


def test_followup_runs_once_when_rows_saved(monkeypatch, capsys) -> None:
    calls: dict[str, list[Any]] = {"stream": [], "followup": []}

    async def _stream(notices, sink, num_of_rows: int = 500) -> int:
        calls["stream"].append(list(notices))
        return 3

    async def _followup(saved: int) -> dict[str, Any]:
        calls["followup"].append(saved)
        return {"linked": 2, "stats_rebuilt": {"rows": 1}}

    monkeypatch.setattr(bf, "SessionLocal", _StubSession)
    monkeypatch.setattr(
        bf,
        "select_backfill_candidates",
        lambda db, **kwargs: [("R1", datetime(2026, 11, 1, 10, 0))],
    )
    monkeypatch.setattr(bf, "stream_servc_prearng_by_notices", _stream)
    monkeypatch.setattr(bf, "_run_sajeong_stats_followup", _followup)

    code = bf.run(["--since", SINCE, "--until", UNTIL, "--execute"])

    assert code == 0
    assert calls["stream"] == [["R1"]]
    assert calls["followup"] == [3]
    assert "수요기관명 연결 2건" in capsys.readouterr().out


def test_followup_is_skipped_when_nothing_saved(monkeypatch) -> None:
    calls: dict[str, list[int]] = {"followup": []}

    async def _stream(notices, sink, num_of_rows: int = 500) -> int:
        return 0

    async def _followup(saved: int) -> dict[str, Any]:
        calls["followup"].append(saved)
        return {"linked": 0, "stats_rebuilt": None}

    monkeypatch.setattr(bf, "SessionLocal", _StubSession)
    monkeypatch.setattr(
        bf,
        "select_backfill_candidates",
        lambda db, **kwargs: [("R1", datetime(2026, 11, 1, 10, 0))],
    )
    monkeypatch.setattr(bf, "stream_servc_prearng_by_notices", _stream)
    monkeypatch.setattr(bf, "_run_sajeong_stats_followup", _followup)

    code = bf.run(["--since", SINCE, "--until", UNTIL, "--execute"])

    assert code == 0
    assert calls["followup"] == []


# ============================================================================
# 5. 실패 공고가 있으면 종료 코드 1
# ============================================================================


def test_failed_notices_exit_with_code_one(monkeypatch, capsys) -> None:
    async def _stream(notices, sink, num_of_rows: int = 500) -> int:
        raise RangeCollectionError("예비가격상세", 2, [("R2", "R2")])

    async def _followup(saved: int) -> dict[str, Any]:
        return {"linked": 1, "stats_rebuilt": None}

    monkeypatch.setattr(bf, "SessionLocal", _StubSession)
    monkeypatch.setattr(
        bf,
        "select_backfill_candidates",
        lambda db, **kwargs: [
            ("R1", datetime(2026, 11, 1, 10, 0)),
            ("R2", datetime(2026, 11, 2, 10, 0)),
        ],
    )
    monkeypatch.setattr(bf, "stream_servc_prearng_by_notices", _stream)
    monkeypatch.setattr(bf, "_run_sajeong_stats_followup", _followup)

    code = bf.run(["--since", SINCE, "--until", UNTIL, "--execute"])

    assert code == 1
    captured = capsys.readouterr()
    assert "실패 공고 1건" in captured.err
    assert "R2" in captured.err
