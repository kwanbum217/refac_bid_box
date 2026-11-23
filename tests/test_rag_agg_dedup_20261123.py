"""RAG 공고 집계의 최신 차수 단일화·취소공고 제외 회귀 테스트.

챗봇 정형 답변의 공고 총계, 업종·지역·금액구간 축, 지역·기관 비교표,
분기 시계열, 기관별·공고명별 순위는 같은 공고의 여러 차수를 각각 세고
최신 차수가 취소공고인 공고까지 셌습니다. 2026-11-22 감사에서 최근 1년
공고 507,585행 중 서로 다른 공고가 451,702건, 그중 최신 차수가 취소공고인
공고가 28,778건으로 확인되어 13.1% 가 부풀려져 있었습니다.

시험은 SQLite 인메모리 픽스처(isolated_db)만 쓰며 로컬 .env, 운영 DB, Redis 에
기대지 않습니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data as structured_data_module
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

WINDOW = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
CANCELLED = "취소공고"

# 같은 공고번호·업무구분의 차수 행 목록입니다.
# DEDUP-A: 000·001 등록공고 -> 001 한 행만 센다.
# DEDUP-B: 000 등록공고 + 001 취소공고 -> 최신 차수가 취소이므로 통째로 뺀다.
# DEDUP-C: 000 등록공고 + 001 재공고 -> 재공고는 유효하므로 001 한 행만 센다.
# DEDUP-D: 공고종류 NULL 단일 차수 -> 유지한다.
# DEDUP-E: 000 등록공고 + 002 변경공고 -> 002 한 행만 센다.
# DEDUP-F: 취소공고 단일 차수 -> 최신 차수가 취소이므로 뺀다.
SEEDS: tuple[tuple[str, str, str | None, str, str, int], ...] = (
    ("DEDUP-A", "000", "등록공고", "중복 검증 공고 A 000", "서울특별시", 50_000_000),
    ("DEDUP-A", "001", "등록공고", "중복 검증 공고 A 001", "서울특별시", 60_000_000),
    ("DEDUP-B", "000", "등록공고", "중복 검증 공고 B 000", "서울특별시", 40_000_000),
    ("DEDUP-B", "001", CANCELLED, "중복 검증 공고 B 001", "서울특별시", 45_000_000),
    ("DEDUP-C", "000", "등록공고", "중복 검증 공고 C 000", "부산광역시", 70_000_000),
    ("DEDUP-C", "001", "재공고", "중복 검증 공고 C 001", "부산광역시", 80_000_000),
    ("DEDUP-D", "000", None, "중복 검증 공고 D 000", "서울특별시", 30_000_000),
    ("DEDUP-E", "000", "등록공고", "중복 검증 공고 E 000", "대구광역시", 110_000_000),
    ("DEDUP-E", "002", "변경공고", "중복 검증 공고 E 002", "대구광역시", 120_000_000),
    ("DEDUP-F", "000", CANCELLED, "중복 검증 공고 F 000", "인천광역시", 20_000_000),
)

# 최신 차수 한 행만 세고 취소공고를 뺀 기대 공고 수입니다.
EXPECTED_TOTAL = 4


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def seeded_db(isolated_db):
    """차수 중복·취소공고 픽스처를 넣은 세션을 돌려줍니다."""
    for index, (no, ord_value, kind, title, agency, amount) in enumerate(SEEDS):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=no,
                bid_ntce_ord=ord_value,
                bid_ntce_nm=title,
                dminstt_nm=agency,
                ntce_kind_nm=kind,
                category="Servc",
                presmpt_prce=amount,
                base_amount=amount,
                bid_ntce_dt=datetime(2026, 3, 1, 9, 0, 0),
                collected_at=datetime(2026, 4, 1, 9, 0, 0) + _minutes(index),
            )
        )
    isolated_db.commit()
    return isolated_db


def _minutes(index: int):
    from datetime import timedelta

    return timedelta(minutes=index)


def _summary(db, filters: dict) -> dict:
    plan = RetrievalPlan(use_sql=True, filters=filters)
    return retrieve_structured_data(db, plan)["summary"]


def test_공고_총계는_최신_차수_한_행만_센다(seeded_db):
    """(a)(b) 총계가 4건이고 취소된 최신 차수는 이전 차수로도 대신 세지 않습니다."""
    summary = _summary(seeded_db, dict(WINDOW))

    assert summary["announcement_count"] == EXPECTED_TOTAL


def test_업종_축은_최신_차수와_취소_제외를_따른다(seeded_db):
    summary = _summary(
        seeded_db,
        {**WINDOW, "group_by": "category", "metric": "announcement_count"},
    )

    counts = {item["key"]: item["announcement_count"] for item in summary["axis_breakdown"]}
    assert counts == {"Servc": EXPECTED_TOTAL}
    assert sum(counts.values()) == summary["announcement_count"]


def test_지역_축은_최신_차수와_취소_제외를_따른다(seeded_db):
    summary = _summary(
        seeded_db,
        {**WINDOW, "group_by": "region", "metric": "announcement_count"},
    )

    counts = {item["key"]: item["announcement_count"] for item in summary["axis_breakdown"]}
    # 서울은 A 001 + D 000 이고, 취소된 B 는 이전 차수(000)도 대신 세지 않습니다.
    assert counts == {"서울": 2, "부산": 1, "대구": 1}
    assert sum(counts.values()) == summary["announcement_count"]


def test_금액구간_축은_최신_차수와_취소_제외를_따른다(seeded_db):
    summary = _summary(
        seeded_db,
        {**WINDOW, "group_by": "amount_band", "metric": "announcement_count"},
    )

    counts = {item["key"]: item["announcement_count"] for item in summary["axis_breakdown"]}
    # A 001(6천만)·C 001(8천만)·D 000(3천만) 은 1억 미만, E 002(1.2억) 은 1억~5억입니다.
    # 이전 차수(A 000 5천만, C 000 7천만, E 000 1.1억)를 함께 세면 값이 달라집니다.
    assert counts["1억 미만"] == 3
    assert counts["1억~5억"] == 1
    assert counts["5억~10억"] == 0
    assert counts["10억 이상"] == 0
    assert sum(counts.values()) == summary["announcement_count"]


def test_기관별_공고명별_순위는_최신_차수만_센다(seeded_db):
    summary = _summary(seeded_db, dict(WINDOW))

    institutions = {item["dminstt_nm"]: item["ntce_count"] for item in summary["top_institutions"]}
    assert institutions == {"서울특별시": 2, "부산광역시": 1, "대구광역시": 1}

    titles = {item["bid_ntce_nm"]: item["ntce_count"] for item in summary["top_announcements"]}
    assert titles["중복 검증 공고 A 001"] == 1
    assert "중복 검증 공고 A 000" not in titles
    assert "중복 검증 공고 B 000" not in titles
    assert "중복 검증 공고 B 001" not in titles
    assert all(count == 1 for count in titles.values())


def test_분기_시계열_공고_건수도_같은_모집단을_쓴다(seeded_db):
    summary = _summary(
        seeded_db,
        {**WINDOW, "time_bucket": "quarter", "category": "Servc"},
    )

    series = {item["label"]: item for item in summary["time_series"]}
    assert series["2026년 1분기"]["announcement_count"] == EXPECTED_TOTAL
    assert series["2026년 1분기"]["ntce_count"] == EXPECTED_TOTAL


def test_지역_비교표_공고_건수도_같은_모집단을_쓴다(seeded_db):
    summary = _summary(
        seeded_db,
        {**WINDOW, "region_names": ["서울", "부산"], "category": "Servc"},
    )

    counts = {item["label"]: item["announcement_count"] for item in summary["comparison"]}
    assert counts == {"서울": 2, "부산": 1}


def test_기관_비교표_공고_건수도_같은_모집단을_쓴다(seeded_db):
    for index, agency in enumerate(("서울특별시", "부산광역시")):
        seeded_db.add(
            BidResult(
                bid_ntce_no=f"DEDUP-RES-{index}",
                bid_ntce_ord="00",
                bid_ntce_nm=f"중복 검증 결과 {index}",
                bidwinnr_nm="중복 검증 업체",
                dminstt_nm=agency,
                category="Servc",
                sucsf_bid_amt=10_000_000,
                sucsf_bid_rate=90.0,
                rl_openg_dt=datetime(2026, 3, 20, 9, 0, 0),
                collected_at=datetime(2026, 4, 1, 9, 0, 0),
            )
        )
    seeded_db.commit()

    summary = _summary(
        seeded_db,
        {
            **WINDOW,
            "institution_names": ["서울특별시", "부산광역시"],
            "category": "Servc",
            "metric": "announcement_count",
        },
    )

    counts = {item["label"]: item["announcement_count"] for item in summary["comparison"]}
    # 취소된 B 는 이전 차수로도 남지 않습니다.
    assert counts == {"서울특별시": 2, "부산광역시": 1}


def test_기간_비교표_공고_건수도_같은_모집단을_쓴다(seeded_db):
    summary = _summary(
        seeded_db,
        {
            **WINDOW,
            "category": "Servc",
            "comparison_dimension": "time",
            "comparison_targets": [
                {
                    "key": "상반기",
                    "label": "2026년 상반기",
                    "date_from": "2026-01-01",
                    "date_to": "2026-06-30",
                },
                {
                    "key": "하반기",
                    "label": "2026년 하반기",
                    "date_from": "2026-07-01",
                    "date_to": "2026-12-31",
                },
            ],
        },
    )

    counts = {item["label"]: item["announcement_count"] for item in summary["comparison"]}
    assert counts == {"2026년 상반기": EXPECTED_TOTAL, "2026년 하반기": 0}


def test_공고번호_단건_조회는_최신_차수_필터를_걸지_않는다(seeded_db):
    """(c) 최신 차수가 취소공고인 공고도 번호로는 찾을 수 있어야 합니다."""
    for bid_ntce_no in ("DEDUP-B", "DEDUP-F"):
        summary = _summary(seeded_db, {"bid_ntce_no": bid_ntce_no})

        detail = summary["bid_detail"]
        assert detail is not None
        assert detail["bid_ntce_no"] == bid_ntce_no
        assert detail["announcement"] is not None
        assert detail["announcement"]["bid_ntce_no"] == bid_ntce_no


def test_공고번호_단건_조회는_이전_차수도_차수_지정으로_찾는다(seeded_db):
    summary = _summary(seeded_db, {"bid_ntce_no": "DEDUP-A", "bid_ntce_ord": "000"})

    detail = summary["bid_detail"]
    assert detail is not None
    assert detail["announcement"] is not None
    # 차수를 지정하면 최신 차수(001)가 아니라 지정한 이전 차수(000)를 돌려줍니다.
    assert detail["announcement"]["bid_ntce_nm"] == "중복 검증 공고 A 000"


def test_공고종류_지정_질의는_최신_차수_취소_제외를_걸지_않는다(seeded_db):
    """(c) '취소공고' 질의는 취소 행 자체를 세야 하므로 종전과 같습니다."""
    cancelled = _summary(seeded_db, {**WINDOW, "notice_kind": CANCELLED})
    assert cancelled["announcement_count"] == 2

    reannounced = _summary(seeded_db, {**WINDOW, "notice_kind": "재공고"})
    assert reannounced["announcement_count"] == 1


def test_순위_차원은_v2_스냅숏을_쓴다(seeded_db, monkeypatch):
    """(d) 기관별·공고명별 순위가 최신 차수 기준 차원을 요청합니다."""
    requested: list[tuple[str, str]] = []

    def fake_get_top_rankings(db, dataset, dimension, category, limit):
        requested.append((dataset, dimension))
        return None

    monkeypatch.setattr(structured_data_module, "get_top_rankings", fake_get_top_rankings)

    summary = _summary(seeded_db, {})

    dimensions = {dimension for dataset, dimension in requested if dataset == "announcement"}
    assert {"dminstt_nm_v2", "bid_ntce_nm_v2"} <= dimensions
    assert "dminstt_nm" not in dimensions
    assert "bid_ntce_nm" not in dimensions
    # 스냅숏이 없어 실시간 경로로 내려가도 같은 모집단을 셉니다.
    assert summary["announcement_count"] == EXPECTED_TOTAL


def test_최신_차수_범위는_유니크_키_MAX_차수와_취소_제외를_쓴다():
    """유니크 키 때문에 최신 차수는 MAX(차수)로 확정되고, 취소 제외가 뒤따릅니다."""
    plan = RetrievalPlan(use_sql=True, filters={})
    stmt = structured_data_module._announcement_aggregate_scope(plan)(
        select(func.count(BidAnnouncement.id))
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "max(latest_ann.bid_ntce_ord)" in compiled
    assert "latest_ann.bid_ntce_no = bid_announcements.bid_ntce_no" in compiled
    assert "latest_ann.category = bid_announcements.category" in compiled
    assert "취소공고" in compiled
    # 최신 차수 판정이 취소 제외보다 앞에 옵니다.
    assert compiled.index("max(latest_ann.bid_ntce_ord)") < compiled.index("취소공고")


def test_예외_질의는_최신_차수_범위를_걸지_않는다():
    """공고번호 단건·공고종류 지정 질의는 종전 문장을 그대로 씁니다."""
    identity = structured_data_module._identity_statement
    detail = RetrievalPlan(use_sql=True, filters={"bid_ntce_no": "DEDUP-A"})
    notice_kind = RetrievalPlan(use_sql=True, filters={"notice_kind": CANCELLED})

    assert structured_data_module._announcement_aggregate_scope(detail) is identity
    assert structured_data_module._announcement_aggregate_scope(notice_kind) is identity

    aggregate = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    assert (
        structured_data_module._announcement_aggregate_scope(aggregate)
        is structured_data_module._apply_latest_announcement_scope
    )
