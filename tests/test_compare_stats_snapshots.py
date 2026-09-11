"""비교 통계 사전 집계 스냅샷 전환 고정 테스트.

기존 테스트 파일은 수정하지 않고 이 파일에서만 검증합니다.
"""

from datetime import timedelta

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard


def _add_announcement(db, **overrides):
    now = utcnow()
    payload = {
        "bid_ntce_no": "SNAP-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "스냅샷 검증 공고",
        "dminstt_nm": "스냅샷 검증 기관",
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
        "bid_ntce_no": "SNAP-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "스냅샷 검증 결과",
        "bidwinnr_nm": "스냅샷 검증 업체",
        "dminstt_nm": "스냅샷 검증 기관",
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


def test_재집계가_두_스냅샷을_만들고_형태가_사양과_같다(isolated_db):
    """두 스냅샷이 생기고 payload 형태와 window_days 가 사양과 같다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)

    outcome = snapshots.rebuild_compare_stats_snapshots(isolated_db)

    assert outcome["status"] == "success"
    agency_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    matched_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)
    assert agency_row is not None
    assert matched_row is not None
    assert agency_row.window_days == 365
    assert matched_row.window_days == 365
    assert isinstance(agency_row.payload, list)
    assert agency_row.payload
    for item in agency_row.payload:
        assert set(item.keys()) == {"name", "total_base_amount", "total_prce", "count"}
        assert item["total_base_amount"] == item["total_prce"]
    assert set(matched_row.payload.keys()) == {"value"}
    assert isinstance(matched_row.payload["value"], int)
    assert matched_row.payload["value"] == 1


def test_상한_초과_금액은_집계에서_빠진다(isolated_db):
    """100조를 넘는 기초금액은 스냅샷 합계에 들어가지 않는다."""
    _add_announcement(isolated_db)
    _add_announcement(
        isolated_db,
        bid_ntce_no="SNAP-OUTLIER",
        bid_ntce_nm="자릿수가 깨진 공고",
        base_amount=137150000137150000,
    )

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    assert row is not None
    assert len(row.payload) == 1
    assert row.payload[0]["total_base_amount"] == 1000000
    assert row.payload[0]["total_prce"] == 1000000


def test_스냅샷이_있으면_실시간_집계가_실행되지_않는다(isolated_db, monkeypatch):
    """신선한 스냅샷이 있으면 폴백용 실시간 함수를 호출하지 않는다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    _isolated_cache(monkeypatch)

    def _forbidden_matched(_db, _one_year_ago):
        raise AssertionError("신선한 스냅샷이 있는데 매칭 실시간 집계가 실행됐다")

    def _forbidden_agency(_db, _one_year_ago):
        raise AssertionError("신선한 스냅샷이 있는데 기관 실시간 집계가 실행됐다")

    monkeypatch.setattr(dashboard, "_query_matched_count_realtime", _forbidden_matched)
    monkeypatch.setattr(dashboard, "_query_agency_announce_top10_realtime", _forbidden_agency)

    data = dashboard.get_compare_stats_data(isolated_db)

    agency_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    matched_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)
    assert data["matched_count"] == matched_row.payload["value"]
    assert data["agency_announce_top10"] == agency_row.payload


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

    assert data_snapshot["matched_count"] == data_fallback["matched_count"]
    assert data_snapshot["agency_announce_top10"] == data_fallback["agency_announce_top10"]
    assert data_fallback["matched_count"] == 1
    assert data_fallback["agency_announce_top10"][0]["total_base_amount"] == 1000000


def test_요약이_신선하고_스냅샷이_없으면_표준_24시간_TTL이_유지된다(isolated_db, monkeypatch):
    """폴백은 실시간 계산이므로 신선하며 stale TTL 로 바뀌지 않는다."""
    from decimal import Decimal

    from src.app.models.bids import (
        DATASET_ANNOUNCEMENT,
        DATASET_RESULT,
        BidDatasetSummary,
    )
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
    ):
        row = isolated_db.get(BidCompareStatsSnapshot, key)
        row.rebuilt_at = old
    isolated_db.commit()
    _store, captured = _isolated_cache(monkeypatch)

    matched_calls: list[bool] = []
    agency_calls: list[bool] = []
    orig_matched = dashboard._query_matched_count_realtime
    orig_agency = dashboard._query_agency_announce_top10_realtime

    def _spy_matched(db, one_year_ago):
        matched_calls.append(True)
        return orig_matched(db, one_year_ago)

    def _spy_agency(db, one_year_ago):
        agency_calls.append(True)
        return orig_agency(db, one_year_ago)

    monkeypatch.setattr(dashboard, "_query_matched_count_realtime", _spy_matched)
    monkeypatch.setattr(dashboard, "_query_agency_announce_top10_realtime", _spy_agency)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert matched_calls
    assert agency_calls
    assert captured["ttl"] == dashboard.COMPARE_STATS_CACHE_TTL
    assert not captured["key"].endswith(":stale")
    assert data["matched_count"] == 1


def test_손상된_기관명이_제외되지_않고_그대로_남는다(isolated_db):
    """깨진 기관명을 새로 걸러내지 않고 스냅샷에 그대로 둔다."""
    _add_announcement(isolated_db, bid_ntce_no="SNAP-OK")
    _add_announcement(
        isolated_db,
        bid_ntce_no="SNAP-BROKEN",
        bid_ntce_nm="깨진 기관 공고",
        dminstt_nm="��깨진기관",
        base_amount=500000,
    )

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    assert row is not None
    names = [item["name"] for item in row.payload]
    assert "��깨진기관" in names


def test_항목_키가_빠진_스냅샷은_예외_대신_폴백한다(isolated_db):
    """리스트라는 것만 보고 항목을 인덱싱하면 KeyError 로 전체가 실패한다.

    리뷰어가 잔여 위험으로 지적한 경로다. 작성기는 이 형태를 쓰지 않지만
    손으로 넣은 행이나 옛 형태가 남을 수 있다.
    """
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    row.payload = [{"name": "키가 빠진 기관"}]
    isolated_db.commit()

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["agency_announce_top10"][0]["name"] is not None
    assert "total_base_amount" in data["agency_announce_top10"][0]


def test_정확히_2일_경계는_스냅샷을_쓴다(isolated_db):
    """규약은 2일 이내면 스냅샷이다. 48.0시간은 폴백이 아니다."""
    now = utcnow()
    assert snapshots.is_snapshot_fresh(now - timedelta(days=2), now=now) is True
    assert snapshots.is_snapshot_fresh(now - timedelta(days=2, seconds=1), now=now) is False


def test_aware_datetime_도_naive_와_같게_판정한다(isolated_db):
    """이 저장소는 naive 와 aware 가 섞여 사고가 난 이력이 있다."""
    from datetime import UTC

    now = utcnow()
    aware = (now - timedelta(days=1)).replace(tzinfo=UTC)
    assert snapshots.is_snapshot_fresh(aware, now=now) is True
    stale_aware = (now - timedelta(days=3)).replace(tzinfo=UTC)
    assert snapshots.is_snapshot_fresh(stale_aware, now=now) is False
