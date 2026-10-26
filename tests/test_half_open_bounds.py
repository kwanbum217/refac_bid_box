"""
tests/test_half_open_bounds.py

공고·낙찰·마감 기간 조건의 상한이 반개 구간인지 검증합니다.

종료일 다음 날 0시에 찍힌 행은 종료일 창에서 빠지고 다음 날 창에만 들어가야
합니다. 상한이 `<= 종료일 다음 날 0시` 이면 같은 행이 두 기간에 중복으로
세어집니다.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.schemas import RetrievalPlan

LAST_DAY_FILTERS = {"date_from": "2026-10-25", "date_to": "2026-10-25"}
NEXT_DAY_FILTERS = {"date_from": "2026-10-26", "date_to": "2026-10-26"}


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """테스트마다 프로세스 로컬 캐시를 비우고 Redis 재연결을 막습니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def bidding_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'half_open.sqlite3'}")
    BidAnnouncement.__table__.create(engine)
    BidResult.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            [
                BidAnnouncement(
                    bid_ntce_no="A-LAST-SECOND",
                    bid_ntce_dt=datetime(2026, 10, 25, 23, 59, 59),
                    bid_clse_dt=datetime(2026, 10, 25, 12, 0, 0),
                    bid_ntce_nm="전날 마지막 공고",
                    dminstt_nm="자정기관",
                    category="Servc",
                ),
                BidAnnouncement(
                    bid_ntce_no="A-MIDNIGHT",
                    bid_ntce_dt=datetime(2026, 10, 26, 0, 0, 0),
                    bid_clse_dt=datetime(2026, 10, 26, 0, 0, 0),
                    bid_ntce_nm="자정 공고",
                    dminstt_nm="자정기관",
                    category="Servc",
                ),
                BidResult(
                    bid_ntce_no="R-LAST-SECOND",
                    rl_openg_dt=datetime(2026, 10, 25, 23, 59, 59),
                    bid_ntce_nm="전날 마지막 낙찰",
                    dminstt_nm="자정기관",
                    bidwinnr_nm="업체",
                    category="Servc",
                    sucsf_bid_rate=80.0,
                ),
                BidResult(
                    bid_ntce_no="R-MIDNIGHT",
                    rl_openg_dt=datetime(2026, 10, 26, 0, 0, 0),
                    bid_ntce_nm="자정 낙찰",
                    dminstt_nm="자정기관",
                    bidwinnr_nm="업체",
                    category="Servc",
                    sucsf_bid_rate=100.0,
                ),
            ]
        )
        session.commit()
    return engine


def _plan(filters: dict) -> RetrievalPlan:
    return RetrievalPlan(semantic_query="", filters=dict(filters))


def _announcement_count(session: Session, filters: dict) -> int:
    plan = _plan(filters)
    return int(
        session.scalar(
            select(func.count(BidAnnouncement.id)).where(
                *structured_data._announcement_conditions(plan)
            )
        )
        or 0
    )


def _result_stats(session: Session, filters: dict) -> tuple[int, float | None]:
    plan = _plan(filters)
    count, rate = session.execute(
        select(func.count(BidResult.id), func.avg(BidResult.sucsf_bid_rate)).where(
            *structured_data._result_conditions(plan)
        )
    ).one()
    return int(count or 0), rate


def test_announcement_count_excludes_next_day_midnight(bidding_engine):
    """공고일 자정 행은 종료일 창과 다음 날 창 어느 한쪽에만 들어갑니다."""
    with Session(bidding_engine) as session:
        last_day = _announcement_count(session, LAST_DAY_FILTERS)
        next_day = _announcement_count(session, NEXT_DAY_FILTERS)

    assert last_day == 1
    assert next_day == 1
    assert last_day + next_day == 2


def test_result_count_and_average_exclude_next_day_midnight(bidding_engine):
    """개찰일 자정 행은 종료일 창의 건수와 평균 낙찰률에서 빠집니다."""
    with Session(bidding_engine) as session:
        last_count, last_rate = _result_stats(session, LAST_DAY_FILTERS)
        next_count, next_rate = _result_stats(session, NEXT_DAY_FILTERS)

    assert (last_count, last_rate) == (1, 80.0)
    assert (next_count, next_rate) == (1, 100.0)


def test_announcement_list_excludes_next_day_midnight(bidding_engine):
    """공고 목록도 종료일 창에서 다음 날 0시 행을 빼고 돌려줍니다."""
    filters = dict(LAST_DAY_FILTERS)
    plan = _plan(filters)
    with Session(bidding_engine) as session:
        samples = structured_data._fetch_sample_announcements(
            session,
            structured_data._announcement_conditions(plan),
            limit=5,
            detailed=True,
            filters=plan.filters,
        )

    assert [sample["bid_ntce_no"] for sample in samples] == ["A-LAST-SECOND"]


def test_result_list_excludes_next_day_midnight(bidding_engine):
    """낙찰 목록도 종료일 창에서 다음 날 0시 행을 빼고 돌려줍니다."""
    filters = dict(LAST_DAY_FILTERS)
    plan = _plan(filters)
    with Session(bidding_engine) as session:
        recent = structured_data._fetch_recent_results(
            session,
            structured_data._result_conditions(plan),
            5,
            filters=plan.filters,
        )

    assert [row["bid_ntce_no"] for row in recent] == ["R-LAST-SECOND"]


def test_close_window_is_half_open(bidding_engine):
    """마감일 창도 다음 날 0시 마감 행을 종료일 창에서 뺍니다."""
    conditions = structured_data._close_conditions(
        {"close_from": "2026-10-25", "close_to": "2026-10-25"}
    )
    with Session(bidding_engine) as session:
        count = session.scalar(select(func.count(BidAnnouncement.id)).where(*conditions))

    assert int(count or 0) == 1


def test_category_comparison_shared_window_is_half_open(bidding_engine):
    """분류 비교의 공통 기간 창도 자정 행을 중복 집계하지 않습니다."""
    plan = _plan(LAST_DAY_FILTERS)
    targets = [{"key": "Servc", "label": "용역"}]
    with Session(bidding_engine) as session:
        result = structured_data._period_category_comparison_result(
            session, plan, targets, dimension="category"
        )

    entry = result["summary"]["comparison"][0]
    assert entry["announcement_count"] == 1
    assert entry["bid_count"] == 1
    assert entry["avg_rate"] == 80.0
