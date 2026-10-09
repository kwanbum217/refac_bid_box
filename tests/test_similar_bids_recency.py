"""
tests/test_similar_bids_recency.py

공고 상세의 유사 공고 5건이 최신 공고일시(bid_ntce_dt) 내림차순으로 나오는지, 그리고 기존
최신 차수 배제(NOT EXISTS) 의미가 그대로 유지되는지 검증합니다.

정렬을 붙이기 전에는 인덱스 순서(공고명 가나다순)로 오래된 공고가 먼저 나왔습니다. 정렬 키는
bid_ntce_dt 내림차순이며 동률은 id 내림차순으로 가릅니다. 이 정렬을 받치는
(dminstt_nm, category, bid_ntce_dt) 인덱스는 리비전 f5a6b7c8d9e0 이 만듭니다.
"""

from datetime import timedelta

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-NTCE-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기본 공고명",
        "dminstt_nm": "수요기관A",
        "ntce_instt_nm": "공고기관A",
        "category": "Servc",
        "base_amount": 10000000,
        "presmpt_prce": 10000000,
        "bid_ntce_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_similar_bids_are_newest_first_and_limited_to_five(isolated_db):
    """유사 공고 6건 중 최신 5건만 공고일시 내림차순으로 나오고 가장 오래된 1건은 잘립니다."""
    base_time = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="TARGET-01",
        bid_ntce_dt=base_time,
        collected_at=base_time,
    )

    sims = [
        _add_announcement(
            isolated_db,
            bid_ntce_no=f"SIM-{index:02d}",
            bid_ntce_nm=f"유사 공고 {index}",
            bid_ntce_dt=base_time - timedelta(days=index),
            collected_at=base_time - timedelta(days=index),
        )
        for index in range(1, 7)
    ]

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    similar_dts = [row.bid_ntce_dt for row in detail["similar_bids"]]
    assert similar_dts == sorted(similar_dts, reverse=True)
    assert [row.id for row in detail["similar_bids"]] == [row.id for row in sims[:5]]
    assert sims[5].id not in {row.id for row in detail["similar_bids"]}


def test_similar_bids_tie_break_by_id_desc(isolated_db):
    """공고일시가 같은 유사 공고는 id 내림차순으로 갈립니다."""
    base_time = utcnow()
    same_dt = base_time - timedelta(days=1)
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="TARGET-02",
        bid_ntce_dt=base_time,
        collected_at=base_time,
    )
    older_id = _add_announcement(
        isolated_db,
        bid_ntce_no="TIE-01",
        bid_ntce_dt=same_dt,
        collected_at=same_dt,
    )
    newer_id = _add_announcement(
        isolated_db,
        bid_ntce_no="TIE-02",
        bid_ntce_dt=same_dt,
        collected_at=same_dt,
    )
    assert newer_id.id > older_id.id

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    assert [row.id for row in detail["similar_bids"]][:2] == [newer_id.id, older_id.id]


def test_similar_bids_exclude_superseded_revision(isolated_db):
    """더 최신 차수가 있는 구 차수는 배제되고, 차수에서 기관이 바뀐 그룹도 결과에서 빠집니다."""
    base_time = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="TARGET-03",
        bid_ntce_dt=base_time,
        collected_at=base_time,
    )

    # 같은 기관에서 차수만 올라간 그룹: 구 차수(000)는 배제되고 최신 차수(001)만 남습니다.
    superseded_v1 = _add_announcement(
        isolated_db,
        bid_ntce_no="SAME-INST-01",
        bid_ntce_ord="000",
        bid_ntce_dt=base_time - timedelta(days=5),
        collected_at=base_time - timedelta(days=5),
    )
    latest_v2 = _add_announcement(
        isolated_db,
        bid_ntce_no="SAME-INST-01",
        bid_ntce_ord="001",
        bid_ntce_dt=base_time - timedelta(days=2),
        collected_at=base_time - timedelta(days=2),
    )

    # 더 나중 차수에서 기관이 바뀐 그룹: 어느 쪽도 이 기관의 유사 공고가 아닙니다.
    moved_v1 = _add_announcement(
        isolated_db,
        bid_ntce_no="MOVED-INST-01",
        bid_ntce_ord="000",
        bid_ntce_dt=base_time - timedelta(days=4),
        collected_at=base_time - timedelta(days=4),
    )
    moved_v2 = _add_announcement(
        isolated_db,
        bid_ntce_no="MOVED-INST-01",
        bid_ntce_ord="001",
        dminstt_nm="수요기관B",
        bid_ntce_dt=base_time - timedelta(days=1),
        collected_at=base_time - timedelta(days=1),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    similar_ids = {row.id for row in detail["similar_bids"]}
    assert latest_v2.id in similar_ids
    assert superseded_v1.id not in similar_ids
    assert moved_v1.id not in similar_ids
    assert moved_v2.id not in similar_ids
    assert target.id not in similar_ids
