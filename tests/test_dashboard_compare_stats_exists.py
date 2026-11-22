"""compare-stats 매칭 건수의 EXISTS 의미 보존 회귀 검증."""

from datetime import datetime, timedelta
from unittest.mock import Mock

from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
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
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            permsn_indstryty_list="업종/1172",
            collected_at=datetime(2026, 9, 1),
        )
    )
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
    """복수 낙찰·기간 밖·미매칭 공고가 존재해도 매칭 공고 수는 정확히 센다.

    요청 경로는 스냅숏이 없으면 pending 으로 답하므로, 매칭 EXISTS 질의의
    의미 검증은 스냅숏 재집계도 함께 쓰는 실시간 함수를 직접 호출해 확인한다.
    """
    from src.app.services import compare_stats_snapshots as snapshots

    _announcement(isolated_db, "MATCHED")
    _announcement(isolated_db, "OUTSIDE")
    _announcement(isolated_db, "UNMATCHED")
    isolated_db.commit()

    fixed_now = datetime(2026, 9, 10)
    _result(isolated_db, "MATCHED", "Thng", fixed_now)
    _result(isolated_db, "MATCHED", "Servc", fixed_now - timedelta(days=1))
    _result(isolated_db, "OUTSIDE", "Thng", fixed_now - timedelta(days=366))
    isolated_db.commit()

    scalar = Mock(wraps=isolated_db.scalar)
    monkeypatch.setattr(isolated_db, "scalar", scalar)
    monkeypatch.setattr(dashboard, "utcnow", lambda: fixed_now)

    one_year_ago = dashboard.kst_now(fixed_now) - timedelta(
        days=snapshots.COMPARE_STATS_WINDOW_DAYS
    )
    matched_count = dashboard._query_matched_count_realtime(isolated_db, one_year_ago)
    counts = dashboard._query_match_rate_1y_realtime(isolated_db, one_year_ago)

    assert matched_count == 1
    # 매칭률 분자·분모는 개찰 결과 날짜가 아니라 공고 날짜(bid_ntce_dt)의 1년 창을
    # 씁니다. 세 공고가 모두 창 안이고, 결과가 있는 MATCHED 와 OUTSIDE 가 분자입니다.
    assert counts["announce_count_1y"] == 3
    assert counts["matched_count_1y"] == 2
    matching_stmt = scalar.call_args.args[0]
    assert "EXISTS" in str(matching_stmt.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "JOIN" not in str(matching_stmt).upper()
