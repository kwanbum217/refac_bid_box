"""
tests/test_official_province_district.py

정식 광역 명칭 바로 뒤에 시·군·구가 오는 질의를 광역 전체가 아니라 그 구역
기관 범위로 좁히는지 검증합니다. 기존 광역 단독 질의와 단축 광역명 + 시·군·구,
지역 비교·나열 질의의 동작은 그대로여야 합니다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.planner_interpreter import interpret_request
from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

# "최근 60일" 창이 2026-08-27 ~ 2026-10-26 으로 닫히도록 고정합니다.
_FROZEN_TODAY = date(2026, 10, 26)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("서울특별시 중구의 최근 60일 용역 평균 낙찰률 얼마야?", "서울특별시 중구"),
        ("서울특별시 강남구 공고 5개", "서울특별시 강남구"),
        ("부산광역시 해운대구 낙찰 건수", "부산광역시 해운대구"),
        ("경기도 수원시 용역 공고", "경기도 수원시"),
        ("제주특별자치도 제주시 공고", "제주특별자치도 제주시"),
        ("서울특별시중구 공고 5개", "서울특별시 중구"),
    ],
)
def test_plan_narrows_official_province_district(query: str, expected: str):
    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_name") == expected
    assert execution_plan.filters.get("institution_name") == expected


@pytest.mark.parametrize(
    ("query", "key", "expected"),
    [
        ("서울특별시 공고 몇 건", "institution_name", "서울"),
        ("세종특별자치시 공고 몇 건", "institution_name", "세종"),
        ("대전 유성구 공고 몇 건", "institution_name", "유성구"),
        ("부산 공고 몇 건", "institution_name", "부산"),
        ("부산이랑 대구 공고 건수 비교해줘", "region_names", ["부산", "대구"]),
        ("부산 및 대구 공고 건수", "region_scope_names", ["부산", "대구"]),
    ],
)
def test_plan_keeps_existing_region_scope(query: str, key: str, expected):
    plan = build_retrieval_plan(query)

    assert plan.filters.get(key) == expected
    if key == "institution_name":
        assert "region_names" not in plan.filters
        assert "region_scope_names" not in plan.filters


def _announcement(
    bid_ntce_no: str,
    institution: str,
    day: int,
    *,
    category: str = "Servc",
) -> BidAnnouncement:
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        category=category,
        bid_ntce_nm=f"공고 {bid_ntce_no}",
        dminstt_nm=institution,
        presmpt_prce=1000000,
        bid_ntce_dt=datetime(2026, 10, day),
        bid_clse_dt=datetime(2026, 10, day + 1),
        collected_at=datetime(2026, 10, day),
    )


def _result(
    bid_ntce_no: str,
    institution: str,
    day: int,
    rate: float,
    *,
    category: str = "Servc",
) -> BidResult:
    return BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="00",
        bid_ntce_nm=f"낙찰 {bid_ntce_no}",
        bidwinnr_nm=f"업체 {bid_ntce_no}",
        sucsf_bid_amt=1000000,
        sucsf_bid_rate=rate,
        rl_openg_dt=datetime(2026, 10, day),
        dminstt_nm=institution,
        category=category,
        collected_at=datetime(2026, 10, day),
    )


@pytest.fixture
def official_district_db(isolated_db):
    isolated_db.add_all(
        [
            _announcement("ANN-001", "서울특별시 중구", 20),
            _announcement("ANN-002", "서울특별시 중구 보건소", 19),
            _announcement("ANN-003", "서울특별시 강남구", 18),
            _announcement("ANN-004", "서울특별시 강남구청", 17),
            _announcement("ANN-005", "서울특별시", 16),
            _announcement("ANN-006", "부산광역시 해운대구", 15),
            _announcement("ANN-007", "부산광역시 해운대구청", 14),
            _announcement("ANN-008", "부산광역시 수영구", 13),
            _announcement("ANN-009", "경기도 수원시", 12),
            _announcement("ANN-010", "경기도 수원시청", 11),
            _announcement("ANN-011", "경기도 성남시", 10),
            _announcement("ANN-012", "제주특별자치도 제주시", 9),
            _announcement("ANN-013", "제주특별자치도 서귀포시", 8),
        ]
    )
    isolated_db.add_all(
        [
            _result("RES-001", "서울특별시 중구", 20, 90.0),
            _result("RES-002", "서울특별시 중구 보건소", 19, 80.0),
            _result("RES-003", "서울특별시 강남구", 18, 10.0),
            _result("RES-004", "서울특별시", 17, 20.0),
            _result("RES-005", "부산광역시 해운대구", 15, 70.0),
            _result("RES-006", "부산광역시 해운대구청", 14, 60.0),
            _result("RES-007", "부산광역시 수영구", 13, 50.0),
        ]
    )
    isolated_db.commit()
    return isolated_db


def _direct_result_average(
    db,
    *,
    date_from: str,
    date_to: str,
    contains: str,
    category: str,
) -> float:
    """플래너 코드를 거치지 않고 낙찰 결과를 직접 집계합니다."""
    conditions = [
        BidResult.rl_openg_dt >= datetime.fromisoformat(date_from),
        BidResult.rl_openg_dt < datetime.fromisoformat(date_to) + timedelta(days=1),
        BidResult.dminstt_nm.contains(contains),
        BidResult.category == category,
    ]
    return float(
        db.execute(select(func.avg(BidResult.sucsf_bid_rate)).where(*conditions)).scalar_one()
    )


def _sample_announcements(db, filters: dict) -> list[dict]:
    plan = RetrievalPlan(use_sql=True, filters=filters)
    return retrieve_structured_data(db, plan)["summary"]["sample_announcements"]


def test_rate_query_scopes_district_and_matches_direct_aggregation(official_district_db):
    query = "서울특별시 중구의 최근 60일 용역 평균 낙찰률 얼마야?"
    plan = build_retrieval_plan(query)

    assert plan.filters.get("institution_name") == "서울특별시 중구"

    result = retrieve_structured_data(official_district_db, plan)
    date_from = str(plan.filters.get("date_from") or "")
    date_to = str(plan.filters.get("date_to") or "")
    district_average = _direct_result_average(
        official_district_db,
        date_from=date_from,
        date_to=date_to,
        contains="서울특별시 중구",
        category="Servc",
    )
    province_average = _direct_result_average(
        official_district_db,
        date_from=date_from,
        date_to=date_to,
        contains="서울특별시",
        category="Servc",
    )

    assert district_average == pytest.approx(85.0)
    assert province_average == pytest.approx(50.0)
    assert result["summary"]["average_winning_rate"] == pytest.approx(district_average)
    assert result["summary"]["average_winning_rate"] != pytest.approx(province_average)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("서울특별시 강남구 공고 5개", {"ANN-003", "ANN-004"}),
        ("경기도 수원시 용역 공고", {"ANN-009", "ANN-010"}),
        ("제주특별자치도 제주시 공고", {"ANN-012"}),
    ],
)
def test_announcement_queries_return_only_district_rows(
    official_district_db, query: str, expected: set[str]
):
    plan = build_retrieval_plan(query)
    samples = _sample_announcements(
        official_district_db, {**plan.filters, "announcement_limit": 20}
    )

    assert {sample["bid_ntce_no"] for sample in samples} == expected


def test_result_query_returns_only_district_rows(official_district_db):
    plan = build_retrieval_plan("부산광역시 해운대구 낙찰 건수")

    assert plan.filters.get("institution_name") == "부산광역시 해운대구"

    scoped = RetrievalPlan(use_sql=True, filters={**plan.filters, "result_limit": 20})
    recent = retrieve_structured_data(official_district_db, scoped)["summary"]["recent_results"]

    assert {row["bid_ntce_no"] for row in recent} == {"RES-005", "RES-006"}
