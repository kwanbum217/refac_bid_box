"""협상 공고 과거 낙찰률 분포의 산식·캐시 회귀 테스트."""

from datetime import datetime
from decimal import Decimal

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import negotiation_stats


def _add_pair(db, no: str, base: int, awarded: int, method: str, ord_: str = "000") -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category="Servc",
            base_amount=base,
            bid_ntce_dt=datetime(2026, 6, 1),
            raw_data={"sucsfbidMthdNm": method},
        )
    )
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category="Servc",
            sucsf_bid_amt=awarded,
            rl_openg_dt=datetime(2026, 6, 2),
        )
    )
    db.commit()


def test_distribution_excludes_out_of_range_and_zero_base(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "valid", 100, 95, "협상에의한계약")
    _add_pair(isolated_db, "low", 100, 49, "협상에의한계약")
    _add_pair(isolated_db, "high", 100, 111, "협상에의한계약")
    _add_pair(isolated_db, "zero", 0, 95, "협상에의한계약")

    result = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    assert result == {
        "valid_count": 1,
        "average": Decimal("95.0000"),
        "median": Decimal("95.0000"),
        "minimum": Decimal("95.0000"),
        "maximum": Decimal("95.0000"),
    }


def test_distribution_second_call_uses_cache(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "cached", 100, 90, "협상에의한계약")
    first = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    def fail_query(*args, **kwargs):
        raise AssertionError("두 번째 호출에서 DB를 조회하면 안 됩니다")

    monkeypatch.setattr(negotiation_stats, "_rows", fail_query)
    assert negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD") == first
