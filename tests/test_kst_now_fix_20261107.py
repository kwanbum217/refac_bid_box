"""
tests/test_kst_now_fix_20261107.py

KST/UTC 혼용 수정 회귀 시험.

(a) kst_now() 가 utcnow() + 9시간인지, (b) kst_today() 가 KST 달력 날짜인지,
(c) 마감 판정이 KST 원문 시각 기준인지, (d) 수집 창 종료일이 KST 달력 기준인지,
(e) 대시보드 1년 창 경계가 KST 기준인지 확인합니다.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from src.app.core import timeutil
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries, collector_service, dashboard


def _add_announcement(db, **overrides) -> BidAnnouncement:
    payload = {
        "bid_ntce_no": "KST-NTCE-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "KST 시각 회귀 공고",
        "dminstt_nm": "수요기관A",
        "ntce_instt_nm": "공고기관A",
        "category": "Servc",
        "base_amount": 10000000,
        "presmpt_prce": 10000000,
        "bid_ntce_dt": datetime(2025, 6, 1, 9, 0, 0),
        "bid_clse_dt": datetime(2026, 11, 7, 10, 0, 0),
        "collected_at": datetime(2025, 6, 1, 0, 0, 0),
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, **overrides) -> BidResult:
    payload = {
        "bid_ntce_no": "KST-RES-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "KST 시각 회귀 낙찰",
        "bidwinnr_nm": "낙찰업체A",
        "dminstt_nm": "수요기관A",
        "category": "Servc",
        "sucsf_bid_amt": 9000000,
        "sucsf_bid_rate": 90.0,
        "rl_openg_dt": datetime(2025, 11, 7, 5, 0, 0),
        "collected_at": datetime(2025, 11, 7, 0, 0, 0),
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_kst_now_adds_nine_hours(monkeypatch):
    """(a) kst_now() 는 UTC naive 에 고정 9시간을 더합니다."""
    fixed_utc = datetime(2026, 11, 7, 1, 30, 0)
    monkeypatch.setattr(timeutil, "utcnow", lambda: fixed_utc)

    assert timeutil.kst_now() == fixed_utc + timedelta(hours=9)
    assert timeutil.kst_now(fixed_utc) == fixed_utc + timedelta(hours=9)


def test_kst_today_uses_kst_calendar(monkeypatch):
    """(b) UTC 16:00 은 KST 로 다음 날이므로 kst_today() 가 하루 앞섭니다."""
    fixed_utc = datetime(2026, 11, 7, 16, 0, 0)
    monkeypatch.setattr(timeutil, "utcnow", lambda: fixed_utc)

    assert fixed_utc.date() == date(2026, 11, 7)
    assert timeutil.kst_today() == date(2026, 11, 8)
    assert timeutil.kst_now() == datetime(2026, 11, 8, 1, 0, 0)


def test_uncollected_legacy_uses_kst_closing_time(isolated_db, monkeypatch):
    """(c) KST 10:00 마감 공고는 KST 10:30 에 uncollected_legacy 가 아닙니다."""
    bid = _add_announcement(isolated_db)

    monkeypatch.setattr(bid_queries, "utcnow", lambda: datetime(2026, 11, 7, 0, 59, 0))
    before_deadline = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert before_deadline["uncollected_legacy"] is True

    monkeypatch.setattr(bid_queries, "utcnow", lambda: datetime(2026, 11, 7, 1, 30, 0))
    after_deadline = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert after_deadline["uncollected_legacy"] is False


def test_collection_window_end_is_kst_yesterday(isolated_db, monkeypatch):
    """(d) KST 02:00 실행이면 수집 창 종료일이 KST 기준 어제입니다."""
    monkeypatch.setattr(collector_service, "utcnow", lambda: datetime(2026, 11, 6, 17, 0, 0))

    _start, end, is_catchup = collector_service.resolve_collection_window(
        isolated_db,
        start_date=None,
        end_date=None,
        fetch_type="announce",
    )

    assert end == "20261106"
    assert is_catchup is True


def test_dashboard_one_year_window_starts_from_kst(isolated_db, monkeypatch):
    """(e) 대시보드 1년 창 경계는 UTC 가 아니라 KST 기준입니다."""
    fixed_utc = datetime(2026, 11, 7, 1, 30, 0)
    monkeypatch.setattr(dashboard, "utcnow", lambda: fixed_utc)
    monkeypatch.setattr(dashboard.cache, "get", lambda _key: None)
    monkeypatch.setattr(dashboard.cache, "set", lambda *_args: None)
    monkeypatch.setattr(dashboard, "_compare_stats_cache_key", lambda *_args: "test-key")
    monkeypatch.setattr(dashboard, "_build_monthly_counts", lambda *_args: [])

    summaries = {
        "announcement": SimpleNamespace(total_count=2, total_amount=2000, is_stale=False),
        "result": SimpleNamespace(total_count=2, total_amount=1800, is_stale=False),
    }
    monkeypatch.setattr(
        dashboard,
        "get_bid_dataset_summary",
        lambda _db, dataset: summaries[dataset],
    )

    # UTC 기준 경계(2025-11-07 01:30)보다 뒤지만 KST 경계(10:30)보다 앞선 시각입니다.
    outside_kst_window = _add_result(
        isolated_db,
        bid_ntce_no="KST-WINDOW-OUT",
        dminstt_nm="수요기관A",
        rl_openg_dt=datetime(2025, 11, 7, 5, 0, 0),
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="KST-WINDOW-OUT",
        bid_ntce_dt=datetime(2025, 11, 7, 5, 0, 0),
    )
    _add_result(
        isolated_db,
        bid_ntce_no="KST-WINDOW-IN",
        dminstt_nm="수요기관B",
        rl_openg_dt=datetime(2025, 11, 7, 23, 0, 0),
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="KST-WINDOW-IN",
        bid_ntce_dt=datetime(2025, 11, 7, 23, 0, 0),
    )

    data = dashboard.get_compare_stats_data(isolated_db)

    assert outside_kst_window.bid_ntce_no == "KST-WINDOW-OUT"
    assert data["matched_count"] == 1
