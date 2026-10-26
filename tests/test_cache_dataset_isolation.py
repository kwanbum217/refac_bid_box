"""
tests/test_cache_dataset_isolation.py

집계 결과 캐시가 데이터셋(DB) 단위로 격리되는지 검증합니다.

2026-10-26 측정에서 시험·시드용 SQLite 픽스처가 운영 Redis 의 rag:rows: 키를
채워 운영 응답에 9·11 같은 소형 값이 섞였습니다. _stmt_cache_key 가 SQL 문자열만
해시해 데이터셋이 달라도 같은 키를 썼기 때문입니다. 같은 SQL 이라도 DB 가
다르면 다른 키여야 하고, 같은 DB 안에서는 키가 결정적으로 같아야 합니다.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.schemas import RetrievalPlan

COUNT_ITEMS = text("SELECT COUNT(*) FROM items")


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """테스트마다 프로세스 로컬 캐시를 비우고 Redis 재연결을 막습니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _items_engine(path, rows: int):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)"))
        for index in range(rows):
            conn.execute(
                text("INSERT INTO items (label) VALUES (:label)"),
                {"label": f"row-{index}"},
            )
    return engine


def test_cached_rows_are_isolated_per_dataset(tmp_path):
    """같은 SQL 이라도 다른 DB 의 집계 값이 섞이면 조용히 틀린 답이 됩니다."""
    first_engine = _items_engine(tmp_path / "first.sqlite3", 1)
    second_engine = _items_engine(tmp_path / "second.sqlite3", 7)

    with Session(first_engine) as first, Session(second_engine) as second:
        first_key = structured_data._stmt_cache_key("rag:rows:", COUNT_ITEMS, first)
        second_key = structured_data._stmt_cache_key("rag:rows:", COUNT_ITEMS, second)

        assert first_key != second_key
        assert structured_data._cached_rows(first, COUNT_ITEMS) == [(1,)]
        assert structured_data._cached_rows(second, COUNT_ITEMS) == [(7,)]


def test_cached_aggregate_is_isolated_per_dataset(tmp_path):
    """단일 행 집계도 데이터셋이 다르면 서로의 값을 돌려주지 않아야 합니다."""
    first_engine = _items_engine(tmp_path / "agg_first.sqlite3", 3)
    second_engine = _items_engine(tmp_path / "agg_second.sqlite3", 11)

    with Session(first_engine) as first, Session(second_engine) as second:
        assert structured_data._cached_aggregate(first, COUNT_ITEMS) == [3]
        assert structured_data._cached_aggregate(second, COUNT_ITEMS) == [11]


def test_same_dataset_keeps_cache_hits(tmp_path):
    """같은 엔진에서는 키가 결정적으로 같아 두 번째 호출이 DB 를 치지 않습니다."""
    engine = _items_engine(tmp_path / "same.sqlite3", 3)
    executions = 0

    def count_execution(*_args, **_kwargs):
        nonlocal executions
        executions += 1

    event.listen(engine, "before_cursor_execute", count_execution)
    try:
        with Session(engine) as session:
            first = structured_data._cached_rows(session, COUNT_ITEMS)
            after_first = executions
            second = structured_data._cached_rows(session, COUNT_ITEMS)
    finally:
        event.remove(engine, "before_cursor_execute", count_execution)

    assert first == second == [(3,)]
    assert after_first == 1
    assert executions == after_first


def test_dataset_identity_excludes_credentials():
    """신원 문자열에는 접속 대상만 남고 비밀번호와 사용자 이름은 빠집니다."""
    engine = create_engine("mysql+pymysql://alice:s3cr3t@db.example.com:3306/bidding")
    with Session(engine) as session:
        identity = structured_data._dataset_identity(session)

    assert "s3cr3t" not in identity
    assert "alice" not in identity
    assert "mysql+pymysql" in identity
    assert "db.example.com" in identity
    assert "3306" in identity
    assert "bidding" in identity


def _bidding_engine(path):
    engine = create_engine(f"sqlite:///{path}")
    BidAnnouncement.__table__.create(engine)
    BidResult.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            [
                BidAnnouncement(
                    bid_ntce_no="R25-SUMMER",
                    bid_ntce_dt=datetime(2025, 6, 1, 12, 0),
                    dminstt_nm="자정기관",
                    category="Servc",
                ),
                BidAnnouncement(
                    bid_ntce_no="R26-MIDNIGHT",
                    bid_ntce_dt=datetime(2026, 1, 1, 0, 0),
                    dminstt_nm="자정기관",
                    category="Servc",
                ),
                BidResult(
                    bid_ntce_no="R25-SUMMER",
                    rl_openg_dt=datetime(2025, 6, 1, 12, 0),
                    dminstt_nm="자정기관",
                    category="Servc",
                    sucsf_bid_rate=90.0,
                ),
                BidResult(
                    bid_ntce_no="R26-MIDNIGHT",
                    rl_openg_dt=datetime(2026, 1, 1, 0, 0),
                    dminstt_nm="자정기관",
                    category="Servc",
                    sucsf_bid_rate=91.0,
                ),
            ]
        )
        session.commit()
    return engine


def test_midnight_row_counts_only_in_this_year(tmp_path):
    """경계 자정 행은 작년 버킷(상한 미만)에서 빠지고 올해 버킷에만 들어갑니다."""
    engine = _bidding_engine(tmp_path / "midnight.sqlite3")
    plan = RetrievalPlan(semantic_query="", filters={})
    targets = [
        {"key": "2025", "label": "2025", "date_from": "2025-01-01", "date_to": "2025-12-31"},
        {"key": "2026", "label": "2026", "date_from": "2026-01-01", "date_to": "2026-12-31"},
    ]

    with Session(engine) as session:
        result = structured_data._period_category_comparison_result(
            session, plan, targets, dimension="time"
        )

    entries = {item["key"]: item for item in result["summary"]["comparison"]}
    assert entries["2025"]["announcement_count"] == 1
    assert entries["2026"]["announcement_count"] == 1
    assert entries["2025"]["bid_count"] == 1
    assert entries["2026"]["bid_count"] == 1
