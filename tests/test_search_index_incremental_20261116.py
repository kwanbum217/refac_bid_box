"""Meilisearch 증분 동기화의 최신 차수 판정 범위 시험.

증분 동기화는 수집분이 속한 공고번호·분류 파티션만 순위를 매기되, 파티션 안의 다른
차수는 그대로 순위 대상으로 남겨야 합니다. 이 파일은 그 조건이 전체 순위 뒤
collected_at 으로 거른 기존 결과와 정확히 같은 ID 집합을 내는지 확인합니다.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import mysql

from src.app.models.bids import BidAnnouncement
from src.app.services import search_index
from src.app.services.bid_queries import latest_announcement_filter

SINCE = datetime(2026, 11, 16, 0, 0, 0)


def _legacy_ids(db, since: datetime) -> set[int]:
    stmt = latest_announcement_filter(select(BidAnnouncement.id)).where(
        BidAnnouncement.collected_at >= since
    )
    return set(db.execute(stmt).scalars())


def _incremental_ids(db, since: datetime) -> set[int]:
    stmt = latest_announcement_filter(select(BidAnnouncement.id), collected_since=since).where(
        BidAnnouncement.collected_at >= since
    )
    return set(db.execute(stmt).scalars())


def _add(
    db,
    bid_ntce_no: str,
    bid_ntce_ord: str,
    category: str,
    collected_at: datetime,
    bid_ntce_dt: datetime | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        bid_ntce_nm=f"{bid_ntce_no}-{bid_ntce_ord}",
        category=category,
        bid_ntce_dt=bid_ntce_dt or collected_at,
        collected_at=collected_at,
    )
    db.add(row)
    return row


def test_incremental_sync_indexes_new_latest_ordinal(isolated_db):
    """(a) 이번에 들어온 상위 차수가 있으면 그 차수만 증분 결과에 남는다."""
    old = _add(isolated_db, "INC-A", "000", "Servc", SINCE - timedelta(days=1))
    new = _add(isolated_db, "INC-A", "001", "Servc", SINCE + timedelta(hours=9))
    isolated_db.commit()

    result = _incremental_ids(isolated_db, SINCE)

    assert result == {new.id}
    assert old.id not in result
    assert result == _legacy_ids(isolated_db, SINCE)


def test_incremental_sync_does_not_promote_older_ordinal(isolated_db):
    """(b) 상위 차수가 어제 것이면 오늘 재수집된 옛 차수를 최신으로 올리지 않는다."""
    latest_ord = _add(isolated_db, "INC-B", "001", "Servc", SINCE - timedelta(days=1))
    recollected_old = _add(isolated_db, "INC-B", "000", "Servc", SINCE + timedelta(hours=2))
    isolated_db.commit()

    result = _incremental_ids(isolated_db, SINCE)

    assert recollected_old.id not in result
    assert latest_ord.id not in result
    assert result == set()
    assert result == _legacy_ids(isolated_db, SINCE)


def test_incremental_sync_sql_limits_ranked_partitions():
    """(c) 순위 계산 서브쿼리 안에 수집분 파티션 조건이 들어간다."""
    incremental_sql = str(
        latest_announcement_filter(select(BidAnnouncement), collected_since=SINCE).compile(
            dialect=mysql.dialect()
        )
    ).upper()
    ranked_region = incremental_sql.split(") AS LATEST_ANN", 1)[0]

    assert "EXISTS" in ranked_region or " IN (" in ranked_region
    assert "INCREMENTAL_ANN" in ranked_region


def test_full_sync_sql_keeps_unrestricted_ranking():
    """collected_since 가 없으면 기존 전체 순위 SQL 과 같아야 한다."""
    sql = str(latest_announcement_filter(select(BidAnnouncement)).compile(dialect=mysql.dialect()))

    assert "EXISTS" not in sql.upper()
    assert "incremental_ann" not in sql


def test_incremental_sync_matches_legacy_filter_across_partitions(isolated_db):
    """(d) 여러 파티션 조합에서 증분 결과 ID 집합이 기존 필터 결과와 같다."""
    yesterday = SINCE - timedelta(days=1)
    last_week = SINCE - timedelta(days=7)
    isolated_db.add_all(
        [
            _add(isolated_db, "INC-MULTI-1", "000", "Servc", last_week),
            _add(isolated_db, "INC-MULTI-1", "001", "Servc", SINCE + timedelta(hours=1)),
            _add(isolated_db, "INC-MULTI-2", "001", "Servc", yesterday),
            _add(isolated_db, "INC-MULTI-2", "000", "Servc", SINCE + timedelta(hours=2)),
            _add(isolated_db, "INC-MULTI-2", "000", "Cnstwk", SINCE + timedelta(hours=3)),
            _add(isolated_db, "INC-MULTI-3", "002", "Thng", last_week),
            _add(
                isolated_db,
                "INC-MULTI-4",
                "000",
                "Servc",
                SINCE + timedelta(hours=4),
                bid_ntce_dt=yesterday,
            ),
        ]
    )
    isolated_db.commit()

    for since in (SINCE, yesterday + timedelta(hours=12), last_week + timedelta(hours=12)):
        assert _incremental_ids(isolated_db, since) == _legacy_ids(isolated_db, since)


def test_sync_path_uses_incremental_ranking(isolated_db):
    """동기화 진입점이 증분 인자를 넘겨 같은 ID 집합을 내는지 확인한다."""
    old = _add(isolated_db, "INC-SYNC", "000", "Servc", SINCE - timedelta(days=2))
    latest = _add(isolated_db, "INC-SYNC", "001", "Servc", SINCE + timedelta(hours=5))
    isolated_db.commit()

    incremental = {row.id for row in search_index._latest_announcements(isolated_db, SINCE)}
    full = {row.id for row in search_index._latest_announcements(isolated_db, None)}

    assert incremental == {latest.id}
    assert incremental == _legacy_ids(isolated_db, SINCE)
    assert full == {latest.id}
    assert old.id not in full
