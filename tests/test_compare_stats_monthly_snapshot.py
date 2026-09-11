"""비교 통계 월별 사전 집계 스냅샷 고정 테스트.

기존 테스트 파일은 수정하지 않고 이 파일에서 월별 스냅샷 기구를 검증합니다.
"""

from datetime import timedelta
from decimal import Decimal

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidDatasetSummary,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard


def _add_announcement(db, **overrides):
    now = utcnow()
    payload = {
        "bid_ntce_no": "SNAP-M-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "월별 스냅샷 검증 공고",
        "dminstt_nm": "월별 검증 기관",
        "category": "Thng",
        "base_amount": 1000000,
        "presmpt_prce": 1000000,
        "bid_ntce_dt": now - timedelta(days=10),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, **overrides):
    now = utcnow()
    payload = {
        "bid_ntce_no": "SNAP-M-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "월별 스냅샷 검증 결과",
        "bidwinnr_nm": "월별 검증 업체",
        "dminstt_nm": "월별 검증 기관",
        "category": "Thng",
        "sucsf_bid_amt": 900000,
        "sucsf_bid_rate": 90.0,
        "rl_openg_dt": now - timedelta(days=10),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _isolated_cache(monkeypatch):
    store = {}
    captured = {}
    monkeypatch.setattr(dashboard.cache, "get", store.get)

    def _set(key, value, ttl):
        store[key] = value
        captured["key"] = key
        captured["ttl"] = ttl

    monkeypatch.setattr(dashboard.cache, "set", _set)
    return store, captured


def test_재집계가_네_스냅샷을_만들고_월별_payload_형태가_사양과_같다(isolated_db):
    """네 스냅샷이 생기고 월별 payload 형태와 window_days 가 사양과 같다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)

    outcome = snapshots.rebuild_compare_stats_snapshots(isolated_db)

    assert outcome["status"] == "success"
    assert outcome["snapshots"] == [
        snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
        snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
        snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
        snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
    ]

    ann_month_row = isolated_db.get(
        BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH
    )
    res_month_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH)

    assert ann_month_row is not None
    assert res_month_row is not None
    assert ann_month_row.window_days == 365
    assert res_month_row.window_days == 365

    assert isinstance(ann_month_row.payload, list)
    assert isinstance(res_month_row.payload, list)
    assert ann_month_row.payload
    assert res_month_row.payload

    for item in ann_month_row.payload:
        assert set(item.keys()) == {"month", "count"}
        assert isinstance(item["month"], str)
        assert isinstance(item["count"], int)

    for item in res_month_row.payload:
        assert set(item.keys()) == {"month", "count"}
        assert isinstance(item["month"], str)
        assert isinstance(item["count"], int)

    assert snapshots.is_monthly_payload_usable(ann_month_row.payload) is True
    assert snapshots.is_monthly_payload_usable(res_month_row.payload) is True


def test_월별_payload_검증기_단위_테스트():
    """is_monthly_payload_usable 의 형태 검증 규칙을 단위 테스트로 확인한다."""
    assert snapshots.is_monthly_payload_usable(None) is False
    assert snapshots.is_monthly_payload_usable("invalid") is False
    assert snapshots.is_monthly_payload_usable({"month": "2026-09", "count": 1}) is False
    assert snapshots.is_monthly_payload_usable([]) is True
    assert snapshots.is_monthly_payload_usable([{"month": "2026-09", "count": 10}]) is True
    # 키 누락
    assert snapshots.is_monthly_payload_usable([{"month": "2026-09"}]) is False
    assert snapshots.is_monthly_payload_usable([{"count": 10}]) is False
    # 타입 불일치
    assert snapshots.is_monthly_payload_usable([{"month": 202609, "count": 10}]) is False
    assert snapshots.is_monthly_payload_usable([{"month": "2026-09", "count": "10"}]) is False
    # dict 아닌 요소 포함
    assert snapshots.is_monthly_payload_usable([{"month": "2026-09", "count": 10}, "bad"]) is False


def test_스냅샷이_있으면_실시간_월별_집계가_실행되지_않는다(isolated_db, monkeypatch):
    """신선한 스냅샷이 있으면 월별 실시간 집계 함수를 호출하지 않는다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    _isolated_cache(monkeypatch)

    def _forbidden_announce_month(_db, _one_year_ago):
        raise AssertionError("신선한 스냅샷이 있는데 공고 월별 실시간 집계가 실행됐다")

    def _forbidden_result_month(_db, _one_year_ago):
        raise AssertionError("신선한 스냅샷이 있는데 개찰결과 월별 실시간 집계가 실행됐다")

    monkeypatch.setattr(dashboard, "_query_announce_by_month_realtime", _forbidden_announce_month)
    monkeypatch.setattr(dashboard, "_query_result_by_month_realtime", _forbidden_result_month)

    data = dashboard.get_compare_stats_data(isolated_db)

    ann_month_row = isolated_db.get(
        BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH
    )
    res_month_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH)
    assert data["announce_by_month"] == ann_month_row.payload
    assert data["result_by_month"] == res_month_row.payload


def test_스냅샷이_없으면_폴백하고_결과가_실시간_계산과_같다(isolated_db, monkeypatch):
    """스냅샷이 없으면 실시간으로 폴백하고 TTL 판정은 종전과 같다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    store, captured = _isolated_cache(monkeypatch)

    data_fallback = dashboard.get_compare_stats_data(isolated_db)

    assert captured["ttl"] == dashboard.COMPARE_STATS_CACHE_TTL
    assert not captured["key"].endswith(":stale")

    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    store.clear()
    data_snapshot = dashboard.get_compare_stats_data(isolated_db)

    assert data_snapshot["announce_by_month"] == data_fallback["announce_by_month"]
    assert data_snapshot["result_by_month"] == data_fallback["result_by_month"]
    assert len(data_fallback["announce_by_month"]) > 0
    assert len(data_fallback["result_by_month"]) > 0


def test_요약이_신선하고_스냅샷이_없으면_표준_24시간_TTL이_유지된다(isolated_db, monkeypatch):
    """폴백은 실시간 계산이므로 신선하며 stale TTL 로 바뀌지 않는다."""
    from src.app.services.dashboard import SUMMARY_ALGORITHM_VERSIONS

    ann = _add_announcement(isolated_db)
    res = _add_result(isolated_db)
    isolated_db.add(
        BidDatasetSummary(
            dataset=DATASET_RESULT,
            total_count=1,
            total_amount=Decimal("900000"),
            avg_rate=Decimal("90.0000"),
            source_latest_collected_at=res.collected_at,
            aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_RESULT],
            rebuilt_at=utcnow(),
        )
    )
    isolated_db.add(
        BidDatasetSummary(
            dataset=DATASET_ANNOUNCEMENT,
            total_count=1,
            total_amount=Decimal("1000000"),
            avg_rate=None,
            source_latest_collected_at=ann.collected_at,
            aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT],
            rebuilt_at=utcnow(),
        )
    )
    isolated_db.commit()
    _store, captured = _isolated_cache(monkeypatch)

    dashboard.get_compare_stats_data(isolated_db)

    assert captured["ttl"] == dashboard.COMPARE_STATS_CACHE_TTL
    assert not captured["key"].endswith(":stale")


def test_2일을_넘은_스냅샷은_폴백하고_TTL_판정은_종전과_같다(isolated_db, monkeypatch):
    """3일 된 스냅샷은 낡은 것으로 보고 실시간으로 폴백한다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    old = utcnow() - timedelta(days=3)
    for key in (
        snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
        snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
        snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
        snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
    ):
        row = isolated_db.get(BidCompareStatsSnapshot, key)
        row.rebuilt_at = old
    isolated_db.commit()
    _store, captured = _isolated_cache(monkeypatch)

    announce_month_calls: list[bool] = []
    result_month_calls: list[bool] = []
    orig_announce = dashboard._query_announce_by_month_realtime
    orig_result = dashboard._query_result_by_month_realtime

    def _spy_announce(db, one_year_ago):
        announce_month_calls.append(True)
        return orig_announce(db, one_year_ago)

    def _spy_result(db, one_year_ago):
        result_month_calls.append(True)
        return orig_result(db, one_year_ago)

    monkeypatch.setattr(dashboard, "_query_announce_by_month_realtime", _spy_announce)
    monkeypatch.setattr(dashboard, "_query_result_by_month_realtime", _spy_result)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert announce_month_calls
    assert result_month_calls
    assert captured["ttl"] == dashboard.COMPARE_STATS_CACHE_TTL
    assert not captured["key"].endswith(":stale")
    assert len(data["announce_by_month"]) > 0
    assert len(data["result_by_month"]) > 0


def test_항목_키가_빠진_스냅샷은_예외_대신_폴백한다(isolated_db):
    """월별 payload 항목에 month 또는 count 키가 빠져도 예외 없이 실시간 폴백한다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    ann_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH)
    ann_row.payload = [{"month": "2026-09"}]  # count 누락
    res_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH)
    res_row.payload = [{"count": 1}]  # month 누락
    isolated_db.commit()

    data = dashboard.get_compare_stats_data(isolated_db)

    assert len(data["announce_by_month"]) > 0
    assert len(data["result_by_month"]) > 0
    for item in data["announce_by_month"]:
        assert "month" in item
        assert "count" in item
    for item in data["result_by_month"]:
        assert "month" in item
        assert "count" in item


def test_대시보드_통계의_by_month는_스냅샷과_무관하게_종전대로_동작한다(isolated_db, monkeypatch):
    """get_dashboard_stats 의 by_month 는 스냅샷 유무와 무관하게 기존 실시간 집계로 동일하게 동작한다."""
    _add_result(isolated_db)
    store, _captured = _isolated_cache(monkeypatch)

    # 스냅샷 부재 상태에서의 대시보드 통계
    data_before = dashboard.get_dashboard_stats(isolated_db)

    # 스냅샷 생성 후의 대시보드 통계 (캐시 비우고 재호출하여 실제 집계 확인)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    store.clear()
    data_after = dashboard.get_dashboard_stats(isolated_db)

    assert data_before["by_month"] == data_after["by_month"]
    assert len(data_after["by_month"]) > 0
    for item in data_after["by_month"]:
        assert set(item.keys()) == {"month", "count"}
