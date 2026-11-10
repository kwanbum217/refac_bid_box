"""F-01 비교 화면 매칭률 기간 창 통일 회귀 테스트.

매칭률 분자와 분모는 둘 다 bid_ntce_dt 가 최근 365일인 공고를 기준으로 셉니다.
스냅샷 경로와 실시간 폴백이 같은 정의를 쓰는지, 화면에 근거 없는 정확도 문구가
남아 있지 않은지 함께 고정합니다.
"""

from datetime import timedelta
from pathlib import Path

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/compare.html"

COMPARE_FIELDS = {
    "announce_count",
    "announce_total_base_amount",
    "announce_total_prce",
    "result_count",
    "result_total_amt",
    "matched_count",
    "announce_count_1y",
    "matched_count_1y",
    "announce_by_month",
    "result_by_month",
    "agency_announce_top10",
}


def _add_announcement(db, bid_ntce_no: str, bid_ntce_dt):
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"매칭률 검증 공고 {bid_ntce_no}",
        dminstt_nm="매칭률 검증 기관",
        category="Thng",
        base_amount=1000000,
        presmpt_prce=1000000,
        bid_ntce_dt=bid_ntce_dt,
        collected_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _add_result(db, bid_ntce_no: str, rl_openg_dt):
    row = BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"매칭률 검증 결과 {bid_ntce_no}",
        bidwinnr_nm="매칭률 검증 업체",
        dminstt_nm="매칭률 검증 기관",
        category="Thng",
        sucsf_bid_amt=900000,
        sucsf_bid_rate=90.0,
        rl_openg_dt=rl_openg_dt,
        collected_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _window_start(now):
    return dashboard.kst_now(now) - timedelta(days=snapshots.COMPARE_STATS_WINDOW_DAYS)


def _isolated_cache(monkeypatch):
    store = {}
    monkeypatch.setattr(dashboard.cache, "get", store.get)
    monkeypatch.setattr(
        dashboard.cache, "set", lambda key, value, ttl: store.__setitem__(key, value)
    )
    return store


def test_365일_창_밖_공고는_분자와_분모에서_모두_빠진다(isolated_db):
    """창 밖 공고에 창 안 결과가 있어도 분자·분모 어느 쪽에도 들어가지 않는다."""
    now = utcnow()
    _add_announcement(isolated_db, "INSIDE", now - timedelta(days=10))
    _add_result(isolated_db, "INSIDE", now - timedelta(days=10))
    _add_announcement(isolated_db, "OUTSIDE", now - timedelta(days=400))
    _add_result(isolated_db, "OUTSIDE", now - timedelta(days=10))
    isolated_db.commit()

    counts = dashboard._query_match_rate_1y_realtime(isolated_db, _window_start(now))

    assert counts == {"announce_count_1y": 1, "matched_count_1y": 1}


def test_창_안_공고_중_결과가_있는_공고만_분자에_들어간다(isolated_db):
    """분모는 창 안 공고 전체, 분자는 그중 같은 공고번호 결과가 있는 공고만 센다."""
    now = utcnow()
    _add_announcement(isolated_db, "MATCHED", now - timedelta(days=20))
    _add_result(isolated_db, "MATCHED", now - timedelta(days=15))
    _add_announcement(isolated_db, "UNMATCHED", now - timedelta(days=5))
    _add_announcement(isolated_db, "UNRELATED", now - timedelta(days=3))
    _add_result(isolated_db, "OTHER-NO", now - timedelta(days=2))
    isolated_db.commit()

    counts = dashboard._query_match_rate_1y_realtime(isolated_db, _window_start(now))

    assert counts == {"announce_count_1y": 3, "matched_count_1y": 1}


def test_스냅샷과_실시간_폴백이_같은_매칭률_값을_낸다(isolated_db, monkeypatch):
    """스냅샷 재집계 값과 실시간 폴백 값이 갈라지지 않는다."""
    now = utcnow()
    _add_announcement(isolated_db, "MATCHED-1", now - timedelta(days=30))
    _add_result(isolated_db, "MATCHED-1", now - timedelta(days=25))
    _add_announcement(isolated_db, "MATCHED-2", now - timedelta(days=60))
    _add_result(isolated_db, "MATCHED-2", now - timedelta(days=55))
    _add_announcement(isolated_db, "UNMATCHED", now - timedelta(days=90))
    _add_announcement(isolated_db, "OUTSIDE", now - timedelta(days=400))
    _add_result(isolated_db, "OUTSIDE", now - timedelta(days=20))
    isolated_db.commit()
    store = _isolated_cache(monkeypatch)

    fallback = dashboard.get_compare_stats_data(isolated_db)

    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    store.clear()
    from_snapshot = dashboard.get_compare_stats_data(isolated_db)

    assert fallback["announce_count_1y"] == 3
    assert fallback["matched_count_1y"] == 2
    assert from_snapshot["announce_count_1y"] == fallback["announce_count_1y"]
    assert from_snapshot["matched_count_1y"] == fallback["matched_count_1y"]

    payload = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_MATCHED_COUNT).payload
    assert payload["announce_count_1y"] == fallback["announce_count_1y"]
    assert payload["matched_count_1y"] == fallback["matched_count_1y"]
    assert snapshots.is_matched_payload_usable(payload) is True


def test_응답에_기존_필드와_새_필드가_모두_있다(client, isolated_db):
    """외부 소비자용 기존 필드를 유지하면서 매칭률용 새 두 필드를 함께 준다."""
    now = utcnow()
    _add_announcement(isolated_db, "API-MATCHED", now - timedelta(days=10))
    _add_result(isolated_db, "API-MATCHED", now - timedelta(days=5))
    isolated_db.commit()

    response = client.get("/api/v1/bids/compare-stats")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) >= COMPARE_FIELDS
    assert payload["announce_count"] == 1
    assert payload["announce_count_1y"] == 1
    assert payload["matched_count_1y"] == 1


def test_비교_화면에_근거_없는_정확도_문구가_없다():
    """화면은 새 두 필드로 매칭률을 계산하고 99.8% 고정 문구를 쓰지 않는다."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "99.8" not in template
    assert "정확도" not in template
    assert "announce_count_1y" in template
    assert "matched_count_1y" in template
