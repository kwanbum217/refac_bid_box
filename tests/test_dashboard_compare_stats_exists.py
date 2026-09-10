"""compare-stats 매칭 건수의 EXISTS 의미 보존 회귀 검증."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import dashboard


def _announcement(db, bid_ntce_no: str) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"공고 {bid_ntce_no}",
        dminstt_nm="검증 기관",
        category="Thng",
        base_amount=1000,
        presmpt_prce=1000,
        bid_ntce_dt=datetime(2026, 9, 1),
        collected_at=datetime(2026, 9, 1),
    )
    db.add(row)
    return row


def _result(db, bid_ntce_no: str, category: str, opened_at: datetime) -> None:
    db.add(
        BidResult(
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="000",
            bid_ntce_nm=f"결과 {bid_ntce_no}",
            bidwinnr_nm="검증 업체",
            dminstt_nm="검증 기관",
            category=category,
            sucsf_bid_amt=900,
            sucsf_bid_rate=90,
            rl_openg_dt=opened_at,
            collected_at=opened_at,
        )
    )


def test_compare_stats_matching_count_uses_exists_and_preserves_meaning(isolated_db, monkeypatch):
    """복수 낙찰·기간 밖·미매칭 공고가 존재해도 매칭 공고 수는 정확히 센다."""
    _announcement(isolated_db, "MATCHED")
    _announcement(isolated_db, "OUTSIDE")
    _announcement(isolated_db, "UNMATCHED")
    isolated_db.commit()

    fixed_now = datetime(2026, 9, 10)
    _result(isolated_db, "MATCHED", "Thng", fixed_now)
    _result(isolated_db, "MATCHED", "Servc", fixed_now - timedelta(days=1))
    _result(isolated_db, "OUTSIDE", "Thng", fixed_now - timedelta(days=366))
    isolated_db.commit()

    summaries = {
        "announcement": SimpleNamespace(total_count=3, total_amount=3000, is_stale=False),
        "result": SimpleNamespace(total_count=3, total_amount=2700, is_stale=False),
    }
    scalar = Mock(wraps=isolated_db.scalar)
    monkeypatch.setattr(isolated_db, "scalar", scalar)
    monkeypatch.setattr(dashboard.cache, "get", lambda _key: None)
    monkeypatch.setattr(dashboard.cache, "set", lambda *_args: None)
    monkeypatch.setattr(dashboard, "_compare_stats_cache_key", lambda *_args: "test-key")
    monkeypatch.setattr(dashboard, "_build_monthly_counts", lambda *_args: [])
    monkeypatch.setattr(dashboard, "utcnow", lambda: fixed_now)

    with patch.object(
        dashboard,
        "get_bid_dataset_summary",
        side_effect=lambda _db, dataset: summaries[dataset],
    ):
        data = dashboard.get_compare_stats_data(isolated_db)

    assert data["matched_count"] == 1
    matching_stmt = scalar.call_args.args[0]
    assert "EXISTS" in str(matching_stmt.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "JOIN" not in str(matching_stmt).upper()
