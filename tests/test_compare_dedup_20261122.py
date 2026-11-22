"""비교 분석 통계 공고 집계의 최신 차수 단일화·취소공고 제외 회귀 테스트.

2026-11-22 사용자 확인(기관별 기초금액 TOP 10)에서 같은 공고의 여러 차수가
각각 더해져 건수·금액이 부풀려진 사실이 드러났습니다. 기관별 상위 10, 최근
1년 매칭 공고 수와 매칭률 분모, 월별 공고 추이, 전체 기간 공고 건수·금액이
모두 같은 공고번호·업무구분의 최신 차수 한 행만 세고 최신 차수가 취소공고인
공고를 빼는지 고정합니다.

시험은 SQLite 인메모리 픽스처(isolated_db)만 쓰며 로컬 .env, 운영 DB, Redis 에
기대지 않습니다.
"""

from datetime import timedelta

from src.app.core.timeutil import kst_now, utcnow
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard

INDUSTRY_CODE = "1172"
CANCELLED = "취소공고"


def _add_announcement(
    db,
    bid_ntce_no: str,
    *,
    bid_ntce_ord: str = "000",
    dminstt_nm: str = "차수 검증 기관",
    base_amount: int = 1_000_000,
    ntce_kind_nm: str | None = None,
    bid_ntce_dt=None,
    category: str = "Servc",
    industry_code: str | None = INDUSTRY_CODE,
) -> BidAnnouncement:
    now = utcnow()
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        bid_ntce_nm=f"차수 검증 공고 {bid_ntce_no}-{bid_ntce_ord}",
        dminstt_nm=dminstt_nm,
        category=category,
        base_amount=base_amount,
        presmpt_prce=base_amount,
        ntce_kind_nm=ntce_kind_nm,
        bid_ntce_dt=bid_ntce_dt or (now - timedelta(days=10)),
        collected_at=now,
    )
    db.add(row)
    if industry_code is not None:
        db.add(
            BidAnnouncementLicenseLimit(
                bid_ntce_no=bid_ntce_no,
                bid_ntce_ord=bid_ntce_ord,
                lmt_grp_no="1",
                lmt_sno="1",
                permsn_indstryty_list=f"업종/{industry_code}",
                collected_at=now,
            )
        )
    db.commit()
    db.refresh(row)
    return row


def _add_result(
    db,
    bid_ntce_no: str,
    *,
    bid_ntce_ord: str = "000",
    category: str = "Servc",
    rl_openg_dt=None,
) -> BidResult:
    now = utcnow()
    row = BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        bid_ntce_nm=f"차수 검증 결과 {bid_ntce_no}-{bid_ntce_ord}",
        bidwinnr_nm="차수 검증 업체",
        dminstt_nm="차수 검증 기관",
        category=category,
        sucsf_bid_amt=900_000,
        sucsf_bid_rate=90.0,
        rl_openg_dt=rl_openg_dt or (now - timedelta(days=10)),
        collected_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _agency_payload(db) -> dict[str, dict]:
    row = db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    assert row is not None
    return {item["name"]: item for item in row.payload}


def _payload(db, key: str):
    row = db.get(BidCompareStatsSnapshot, key)
    assert row is not None
    return row.payload


def test_같은_공고의_여러_차수는_기관_상위10_금액과_건수에_한_번만_반영된다(isolated_db):
    """(a) 000·001 차수를 가진 공고는 최신 001 차수 한 행만 상위 10 에 들어간다."""
    _add_announcement(
        isolated_db,
        "DEDUP-A",
        bid_ntce_ord="000",
        dminstt_nm="중복 검증 기관",
        base_amount=90_000_000_000,
        ntce_kind_nm="등록공고",
    )
    _add_announcement(
        isolated_db,
        "DEDUP-A",
        bid_ntce_ord="001",
        dminstt_nm="중복 검증 기관",
        base_amount=90_000_000_000,
        ntce_kind_nm="변경공고",
    )
    _add_announcement(
        isolated_db,
        "DEDUP-B",
        dminstt_nm="비교 검증 기관",
        base_amount=10_000_000_000,
    )

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    agency = _agency_payload(isolated_db)
    assert agency["중복 검증 기관"]["total_base_amount"] == 90_000_000_000
    assert agency["중복 검증 기관"]["total_prce"] == 90_000_000_000
    assert agency["중복 검증 기관"]["count"] == 1
    assert agency["비교 검증 기관"]["total_base_amount"] == 10_000_000_000
    assert agency["비교 검증 기관"]["count"] == 1

    one_year_ago = kst_now(utcnow()) - timedelta(days=snapshots.COMPARE_STATS_WINDOW_DAYS)
    realtime = dashboard._query_agency_announce_top10_realtime(isolated_db, one_year_ago)
    assert realtime == _payload(isolated_db, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)


def test_최신_차수가_취소공고면_빼고_재공고_변경공고_NULL_최신은_유지한다(isolated_db):
    """(b) 취소된 최신 차수는 이전 차수까지 통째로 빼고, 유효한 공고종류는 남긴다."""
    _add_announcement(
        isolated_db,
        "CANCEL-LATEST",
        bid_ntce_ord="000",
        dminstt_nm="취소 검증 기관",
        base_amount=5_000_000_000,
        ntce_kind_nm="재공고",
    )
    _add_announcement(
        isolated_db,
        "CANCEL-LATEST",
        bid_ntce_ord="001",
        dminstt_nm="취소 검증 기관",
        base_amount=5_000_000_000,
        ntce_kind_nm=CANCELLED,
    )
    _add_announcement(
        isolated_db,
        "RE-ANNOUNCE",
        bid_ntce_ord="000",
        dminstt_nm="재공고 검증 기관",
        base_amount=1_000_000_000,
        ntce_kind_nm="등록공고",
    )
    _add_announcement(
        isolated_db,
        "RE-ANNOUNCE",
        bid_ntce_ord="001",
        dminstt_nm="재공고 검증 기관",
        base_amount=3_000_000_000,
        ntce_kind_nm="재공고",
    )
    _add_announcement(
        isolated_db,
        "CHANGE",
        bid_ntce_ord="000",
        dminstt_nm="변경공고 검증 기관",
        base_amount=500_000_000,
        ntce_kind_nm="등록공고",
    )
    _add_announcement(
        isolated_db,
        "CHANGE",
        bid_ntce_ord="001",
        dminstt_nm="변경공고 검증 기관",
        base_amount=2_000_000_000,
        ntce_kind_nm="변경공고",
    )
    _add_announcement(
        isolated_db,
        "NULL-KIND",
        dminstt_nm="공고종류 없음 기관",
        base_amount=1_000_000_000,
        ntce_kind_nm=None,
    )

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    totals = _payload(isolated_db, snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS)
    assert totals["announce_count"] == 3
    assert totals["announce_total_base_amount"] == 6_000_000_000

    agency = _agency_payload(isolated_db)
    assert "취소 검증 기관" not in agency
    assert agency["재공고 검증 기관"]["total_base_amount"] == 3_000_000_000
    assert agency["재공고 검증 기관"]["count"] == 1
    assert agency["변경공고 검증 기관"]["total_base_amount"] == 2_000_000_000
    assert agency["공고종류 없음 기관"]["total_base_amount"] == 1_000_000_000

    matched = _payload(isolated_db, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)
    assert matched["announce_count_1y"] == 3
    assert matched["matched_count_1y"] == 0


def test_월별_매칭_분모_전체_합계도_같은_규칙을_쓴다(isolated_db):
    """(c) 월별 추이·1년 분모·전체 건수·금액도 최신 차수 하나·취소 제외로 센다."""
    bid_dt = utcnow() - timedelta(days=10)
    _add_announcement(
        isolated_db,
        "MONTH-DUP",
        bid_ntce_ord="000",
        dminstt_nm="월별 중복 기관",
        base_amount=3_000_000_000,
        bid_ntce_dt=bid_dt,
    )
    _add_announcement(
        isolated_db,
        "MONTH-DUP",
        bid_ntce_ord="001",
        dminstt_nm="월별 중복 기관",
        base_amount=7_000_000_000,
        bid_ntce_dt=bid_dt,
    )
    _add_announcement(
        isolated_db,
        "MONTH-CANCEL",
        bid_ntce_ord="000",
        dminstt_nm="월별 취소 기관",
        base_amount=4_000_000_000,
        bid_ntce_dt=bid_dt,
    )
    _add_announcement(
        isolated_db,
        "MONTH-CANCEL",
        bid_ntce_ord="001",
        dminstt_nm="월별 취소 기관",
        base_amount=4_000_000_000,
        ntce_kind_nm=CANCELLED,
        bid_ntce_dt=bid_dt,
    )
    _add_announcement(
        isolated_db,
        "MONTH-KEEP",
        dminstt_nm="월별 유지 기관",
        base_amount=1_000_000_000,
        bid_ntce_dt=bid_dt,
    )
    _add_result(isolated_db, "MONTH-DUP", bid_ntce_ord="001", rl_openg_dt=bid_dt)

    snapshots.rebuild_compare_stats_snapshots(isolated_db)

    month = bid_dt.strftime("%Y-%m")
    announce_by_month = _payload(isolated_db, snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH)
    assert announce_by_month == [{"month": month, "count": 2}]

    matched = _payload(isolated_db, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)
    assert matched == {"value": 1, "announce_count_1y": 2, "matched_count_1y": 1}

    totals = _payload(isolated_db, snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS)
    assert totals["announce_count"] == 2
    assert totals["announce_total_base_amount"] == 8_000_000_000

    one_year_ago = kst_now(utcnow()) - timedelta(days=snapshots.COMPARE_STATS_WINDOW_DAYS)
    assert (
        dashboard._query_announce_by_month_realtime(isolated_db, one_year_ago) == announce_by_month
    )
    assert dashboard._query_match_rate_1y_realtime(isolated_db, one_year_ago) == {
        "announce_count_1y": 2,
        "matched_count_1y": 1,
    }
    assert dashboard._query_matched_count_realtime(isolated_db, one_year_ago) == 1
    assert dashboard._query_industry_totals_realtime(isolated_db) == totals


def test_정의_버전과_캐시_키_버전이_올라간다(isolated_db):
    """(d) 새 정의가 옛 스냅숏·옛 응답 캐시를 재사용하지 않도록 버전을 올린다."""
    assert snapshots.COMPARE_STATS_DEFINITION_VERSION == 3
    for key in (
        snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
        snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
        snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
        snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
        snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS,
    ):
        assert key.endswith(":v3")

    announcement_summary = dashboard.get_bid_dataset_summary(isolated_db, "announcement")
    result_summary = dashboard.get_bid_dataset_summary(isolated_db, "result")
    cache_key = dashboard._compare_stats_cache_key(announcement_summary, result_summary)
    assert cache_key.startswith("dashboard_compare_stats:v3:")
    assert f":defv{snapshots.COMPARE_STATS_DEFINITION_VERSION}:" in cache_key
