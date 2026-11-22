"""비교 분석 화면 4대 업종 한정 회귀 테스트.

GET /api/v1/bids/compare-stats 의 전체 기간 건수·금액, 1년 창 수치, 월별 추세,
기관별 상위 10 이 모두 4대 업종(파견, 경비업, 위생관리용역업, 유료직업소개업)
업종 제한이 걸린 공고와 그 공고의 낙찰 결과만 세는지 고정합니다.

시험은 SQLite 인메모리 픽스처(isolated_db)만 쓰며 로컬 .env, 운영 DB, Redis 에
기대지 않습니다.
"""

from datetime import timedelta

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard

RESPONSE_KEYS = {
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

INDUSTRY_CODES = ("1172", "1164", "1162", "5603")


def _add_announcement(db, bid_ntce_no: str, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": "000",
        "bid_ntce_nm": f"업종 한정 검증 공고 {bid_ntce_no}",
        "dminstt_nm": "업종 한정 검증 기관",
        "category": "Servc",
        "base_amount": 1_000_000,
        "presmpt_prce": 1_000_000,
        "bid_ntce_dt": now - timedelta(days=10),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, bid_ntce_no: str, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": "000",
        "bid_ntce_nm": f"업종 한정 검증 결과 {bid_ntce_no}",
        "bidwinnr_nm": "업종 한정 검증 업체",
        "dminstt_nm": "업종 한정 검증 기관",
        "category": "Servc",
        "sucsf_bid_amt": 900_000,
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


def _add_license_limit(
    db,
    bid_ntce_no: str,
    *,
    bid_ntce_ord: str = "000",
    lcns_lmt_nm: str | None = None,
    permsn_indstryty_list: str | None = None,
    lmt_sno: str = "1",
) -> BidAnnouncementLicenseLimit:
    row = BidAnnouncementLicenseLimit(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        lmt_grp_no="1",
        lmt_sno=lmt_sno,
        lcns_lmt_nm=lcns_lmt_nm,
        permsn_indstryty_list=permsn_indstryty_list,
        collected_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _isolated_cache(monkeypatch) -> dict:
    store: dict = {}
    monkeypatch.setattr(dashboard.cache, "get", store.get)

    def _set(key, value, ttl):
        store[key] = value

    monkeypatch.setattr(dashboard.cache, "set", _set)
    return store


def _seed_scoped_and_out_of_scope(db) -> None:
    """업종 안 공고 1건과 업종 밖·제한 없음 공고 각 1건을 만든다."""
    _add_announcement(db, "IN-1172", dminstt_nm="업종 안 기관")
    _add_license_limit(db, "IN-1172", permsn_indstryty_list="기타/1172")
    _add_result(db, "IN-1172", dminstt_nm="업종 안 기관")

    _add_announcement(db, "OUT-7740", dminstt_nm="업종 밖 기관")
    _add_license_limit(db, "OUT-7740", lcns_lmt_nm="가축방역위생관리업/7740")
    _add_result(db, "OUT-7740", dminstt_nm="업종 밖 기관")

    _add_announcement(db, "NO-LIMIT", dminstt_nm="제한 없음 기관")
    _add_result(db, "NO-LIMIT", dminstt_nm="제한 없음 기관")


def test_스냅숏은_업종_제한_공고와_그_결과만_센다(isolated_db):
    """업종 밖 코드와 업종 제한 행이 없는 공고·결과는 모든 스냅숏에서 빠진다."""
    _seed_scoped_and_out_of_scope(isolated_db)

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    totals = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS)
    assert totals is not None
    assert totals.payload == {
        "announce_count": 1,
        "announce_total_base_amount": 1_000_000,
        "result_count": 1,
        "result_total_amt": 900_000,
    }

    matched = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)
    assert matched is not None
    assert matched.payload == {"value": 1, "announce_count_1y": 1, "matched_count_1y": 1}

    agency = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    assert agency is not None
    assert [item["name"] for item in agency.payload] == ["업종 안 기관"]

    announce_month = isolated_db.get(
        BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH
    )
    result_month = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH)
    assert announce_month is not None
    assert result_month is not None
    assert sum(item["count"] for item in announce_month.payload) == 1
    assert sum(item["count"] for item in result_month.payload) == 1


@pytest.mark.parametrize("code", INDUSTRY_CODES)
def test_네_업종_코드는_모두_업종_안으로_센다(isolated_db, code):
    """파견, 경비업, 위생관리용역업, 유료직업소개업 코드가 모두 포함된다."""
    bid_ntce_no = f"IN-{code}"
    _add_announcement(isolated_db, bid_ntce_no)
    _add_license_limit(isolated_db, bid_ntce_no, permsn_indstryty_list=f"업종/{code}")
    _add_result(isolated_db, bid_ntce_no)

    payload = snapshots._compute_industry_totals_payload(isolated_db)

    assert payload["announce_count"] == 1
    assert payload["result_count"] == 1


def test_실시간_폴백이_스냅숏과_같은_값을_낸다(isolated_db, monkeypatch):
    """스냅숏 재집계 값과 실시간 폴백 값이 모든 응답 키에서 일치한다."""
    _seed_scoped_and_out_of_scope(isolated_db)
    _isolated_cache(monkeypatch)

    fallback = dashboard.get_compare_stats_data(isolated_db)
    assert set(fallback.keys()) == RESPONSE_KEYS

    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    monkeypatch.setattr(dashboard.cache, "get", lambda _key: None)
    snapshot = dashboard.get_compare_stats_data(isolated_db)

    assert {key: snapshot[key] for key in RESPONSE_KEYS} == fallback
    assert fallback["announce_count"] == 1
    assert fallback["announce_total_base_amount"] == 1_000_000
    assert fallback["announce_total_prce"] == 1_000_000
    assert fallback["result_count"] == 1
    assert fallback["result_total_amt"] == 900_000
    assert fallback["matched_count"] == 1
    assert fallback["announce_count_1y"] == 1
    assert fallback["matched_count_1y"] == 1
    assert [item["name"] for item in fallback["agency_announce_top10"]] == ["업종 안 기관"]


def test_업종_제한이_없는_공고만_있으면_모든_값이_0이다(isolated_db, monkeypatch):
    """업종 제한 행이 없는 공고·결과는 화면 수치 어디에도 들어가지 않는다."""
    _add_announcement(isolated_db, "NO-LIMIT")
    _add_result(isolated_db, "NO-LIMIT")
    _isolated_cache(monkeypatch)

    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["announce_count"] == 0
    assert data["announce_total_base_amount"] == 0
    assert data["result_count"] == 0
    assert data["result_total_amt"] == 0
    assert data["matched_count"] == 0
    assert data["announce_count_1y"] == 0
    assert data["matched_count_1y"] == 0
    assert data["announce_by_month"] == []
    assert data["result_by_month"] == []
    assert data["agency_announce_top10"] == []


def test_응답_키와_스키마가_바뀌지_않는다(isolated_db, monkeypatch):
    """정의가 바뀌어도 응답 키 집합은 그대로다."""
    _seed_scoped_and_out_of_scope(isolated_db)
    _isolated_cache(monkeypatch)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert set(data.keys()) == RESPONSE_KEYS


def test_캐시와_스냅숏_키에_정의_버전이_있다(isolated_db):
    """옛 업종 무관 캐시·스냅숏이 새 정의에 재사용되지 않도록 버전이 붙는다."""
    assert snapshots.COMPARE_STATS_DEFINITION_VERSION >= 2
    for key in (
        snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
        snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
        snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
        snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
        snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS,
    ):
        assert key.endswith(f":v{snapshots.COMPARE_STATS_DEFINITION_VERSION}")

    announcement_summary = dashboard.get_bid_dataset_summary(isolated_db, "announcement")
    result_summary = dashboard.get_bid_dataset_summary(isolated_db, "result")
    cache_key = dashboard._compare_stats_cache_key(announcement_summary, result_summary)
    assert cache_key.startswith("dashboard_compare_stats:v3:")
