"""
tests/test_single_metric_institution.py

단일 지표(건수·평균 낙찰률) 질의의 기관 해석을 검증합니다.

- 개체 접미사가 있는 기관명은 이름 속 지역명(서울, 경기, 대구)이 아니라
  기관 전체 이름을 기관 조건으로 삼습니다.
- 접미사 목록에 없는 기금·진흥원도 후보로 남겨 카탈로그에서 해석합니다.
- 카탈로그에서 확인하지 못한 기관은 전체 값이 아니라 미해석 안내로 끝냅니다.
- 기관 후보가 없고 지역명만 있는 질의와 분야어 질의는 기존 동작을 유지합니다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import query_planning
from src.rag.answer_format import _build_single_metric_answer
from src.rag.query_planning import build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data

# 올해 창이 2026-01-01 ~ 2026-10-26 으로 닫히도록 고정합니다.
_FROZEN_TODAY = date(2026, 10, 26)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def _seed_announcement(
    session,
    *,
    row_id: int,
    ntce_dt: datetime,
    category: str,
    institution: str,
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ANN-{row_id}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"공고 {row_id}",
            dminstt_nm=institution,
            bid_ntce_dt=ntce_dt,
            category=category,
            raw_data=None,
        )
    )


def _seed_result(
    session,
    *,
    row_id: int,
    opened_at: datetime,
    category: str,
    institution: str,
    rate: float,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"낙찰 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=1_000_000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def _seed_catalog_rows(session) -> None:
    """기관별 값이 전체 값과 우연히 같아지지 않도록 행을 배치합니다."""
    announcements = [
        # 서울대학교병원: 올해 2건, 작년 1건, 창 밖 1건
        (1, datetime(2026, 1, 5, 9), "Servc", "서울대학교병원"),
        (2, datetime(2026, 3, 5, 9), "Cnstwk", "서울대학교병원"),
        (3, datetime(2025, 5, 5, 9), "Servc", "서울대학교병원"),
        (4, datetime(2026, 12, 1, 9), "Servc", "서울대학교병원"),
        # 경기도교육청: 올해 2건(공사 1건 포함), 작년 1건
        (5, datetime(2026, 2, 10, 9), "Servc", "경기도교육청"),
        (6, datetime(2026, 4, 10, 9), "Cnstwk", "경기도교육청"),
        (7, datetime(2025, 3, 10, 9), "Servc", "경기도교육청"),
        # 대구광역시교육청: 올해 1건, 작년 1건
        (8, datetime(2026, 5, 10, 9), "Thng", "대구광역시교육청"),
        (9, datetime(2025, 6, 10, 9), "Thng", "대구광역시교육청"),
        # 기술보증기금: 올해 3건
        (10, datetime(2026, 6, 10, 9), "Servc", "기술보증기금"),
        (11, datetime(2026, 7, 10, 9), "Cnstwk", "기술보증기금"),
        (12, datetime(2026, 8, 10, 9), "Servc", "기술보증기금"),
        # 부산광역시청: 올해 2건
        (13, datetime(2026, 2, 20, 9), "Servc", "부산광역시청"),
        (14, datetime(2026, 9, 20, 9), "Cnstwk", "부산광역시청"),
        # 한국전력공사: 올해 2건
        (15, datetime(2026, 1, 20, 9), "Cnstwk", "한국전력공사"),
        (16, datetime(2026, 3, 20, 9), "Cnstwk", "한국전력공사"),
        # 다른기관: 전체 값 비교용 올해 3건
        (17, datetime(2026, 1, 1, 9), "Servc", "다른기관"),
        (18, datetime(2026, 2, 1, 9), "Cnstwk", "다른기관"),
        (19, datetime(2026, 3, 1, 9), "Servc", "다른기관"),
    ]
    for row_id, ntce_dt, category, institution in announcements:
        _seed_announcement(
            session,
            row_id=row_id,
            ntce_dt=ntce_dt,
            category=category,
            institution=institution,
        )

    results = [
        # 한국인터넷진흥원: 평균 80.0
        (101, datetime(2026, 2, 1, 9), "Servc", "한국인터넷진흥원", 90.0),
        (102, datetime(2026, 5, 1, 9), "Servc", "한국인터넷진흥원", 80.0),
        (103, datetime(2026, 8, 1, 9), "Cnstwk", "한국인터넷진흥원", 70.0),
        # 다른기관: 전체 평균을 70.0 으로 끌어내립니다.
        (104, datetime(2026, 3, 1, 9), "Servc", "다른기관", 50.0),
        (105, datetime(2026, 6, 1, 9), "Cnstwk", "다른기관", 60.0),
    ]
    for row_id, opened_at, category, institution, rate in results:
        _seed_result(
            session,
            row_id=row_id,
            opened_at=opened_at,
            category=category,
            institution=institution,
            rate=rate,
        )
    session.commit()


@pytest.fixture
def catalog_db(isolated_db):
    _seed_catalog_rows(isolated_db)
    return isolated_db


def _window_of(plan) -> tuple[str, str]:
    return (
        str(plan.filters.get("date_from") or ""),
        str(plan.filters.get("date_to") or ""),
    )


def _direct_announcement_count(
    db,
    *,
    date_from: str = "",
    date_to: str = "",
    institution: str = "",
    contains: str = "",
    category: str = "",
) -> int:
    """플래너 코드를 거치지 않고 공고를 직접 집계합니다."""
    conditions = []
    if date_from:
        conditions.append(BidAnnouncement.bid_ntce_dt >= datetime.fromisoformat(date_from))
    if date_to:
        conditions.append(
            BidAnnouncement.bid_ntce_dt < datetime.fromisoformat(date_to) + timedelta(days=1)
        )
    if institution:
        conditions.append(BidAnnouncement.dminstt_nm == institution)
    if contains:
        conditions.append(BidAnnouncement.dminstt_nm.contains(contains))
    if category:
        conditions.append(BidAnnouncement.category == category)
    return int(
        db.execute(
            select(func.count()).select_from(BidAnnouncement).where(*conditions)
        ).scalar_one()
    )


@pytest.mark.parametrize(
    ("query", "institution", "expected"),
    [
        ("서울대학교병원 올해 공고 건수", "서울대학교병원", 2),
        ("경기도교육청 올해 공고 건수", "경기도교육청", 2),
        ("대구광역시교육청 올해 공고 건수", "대구광역시교육청", 1),
        ("기술보증기금 올해 공고 건수", "기술보증기금", 3),
        ("한국전력공사 올해 공고 건수", "한국전력공사", 2),
    ],
)
def test_single_metric_keeps_full_institution_name(
    catalog_db, query: str, institution: str, expected: int
):
    """기관명 속 지역명이 아니라 기관 전체 이름으로 그 기관만 셉니다."""
    plan = build_retrieval_plan(query)

    assert plan.filters.get("institution_name") == institution
    assert plan.filters.get("institution_aliases") is None

    result = retrieve_structured_data(catalog_db, plan)
    date_from, date_to = _window_of(plan)

    assert result.get("query_skipped") is not True
    assert result["summary"]["announcement_count"] == expected
    assert result["summary"]["announcement_count"] == _direct_announcement_count(
        catalog_db, date_from=date_from, date_to=date_to, institution=institution
    )
    total = _direct_announcement_count(catalog_db, date_from=date_from, date_to=date_to)
    assert result["summary"]["announcement_count"] != total


def test_single_metric_avg_rate_uses_institution_scope(catalog_db):
    """접미사 목록에 없는 진흥원도 평균 낙찰률의 기관 조건이 됩니다."""
    plan = build_retrieval_plan("한국인터넷진흥원 평균 낙찰률")

    assert plan.filters.get("institution_name") == "한국인터넷진흥원"

    result = retrieve_structured_data(catalog_db, plan)
    average = result["summary"]["average_winning_rate"]

    assert average == pytest.approx(80.0)
    assert average != pytest.approx(70.0)


def test_unknown_institution_single_metric_reports_unresolved(catalog_db):
    """확인하지 못한 기관은 전체 값이 아니라 미해석 안내로 끝냅니다."""
    plan = build_retrieval_plan("없는기관진흥원 올해 공고 건수")

    assert plan.filters.get("institution_name") == "없는기관진흥원"

    result = retrieve_structured_data(catalog_db, plan)
    date_from, date_to = _window_of(plan)

    assert result["query_skipped"] is True
    assert result["summary"]["announcement_count"] is None
    assert any("확인하지 못해" in hint for hint in result["insufficiency_hints"])
    assert _direct_announcement_count(catalog_db, date_from=date_from, date_to=date_to) > 0
    assert _build_single_metric_answer(plan, result) == ""


def test_region_only_single_metric_keeps_region_fallback(catalog_db):
    """기관 후보가 없고 지역명만 있으면 기존 광역 대체 경로를 씁니다."""
    plan = build_retrieval_plan("부산 올해 공고 건수")

    assert plan.filters.get("institution_name") == "부산"

    result = retrieve_structured_data(catalog_db, plan)
    date_from, date_to = _window_of(plan)

    assert result.get("query_skipped") is not True
    assert result["summary"]["announcement_count"] == _direct_announcement_count(
        catalog_db, date_from=date_from, date_to=date_to, contains="부산"
    )


def test_region_and_category_single_metric_keeps_existing_scope(catalog_db):
    """지역명과 분야어만 있는 건수 질의는 기관 조건을 만들지 않습니다."""
    plan = build_retrieval_plan("서울 공사 공고 몇 건")

    assert plan.filters.get("institution_name") == "서울"
    assert plan.filters.get("category") == "Cnstwk"

    result = retrieve_structured_data(catalog_db, plan)

    assert result["summary"]["announcement_count"] == _direct_announcement_count(
        catalog_db, contains="서울", category="Cnstwk"
    )


def test_category_only_single_metric_has_no_institution_scope(catalog_db):
    """기관 이름이 없는 분야 건수 질의는 기관 조건을 만들지 않습니다."""
    plan = build_retrieval_plan("올해 용역 공고 몇 건")

    assert "institution_name" not in plan.filters
    assert "institution_aliases" not in plan.filters
    assert plan.filters.get("category") == "Servc"

    result = retrieve_structured_data(catalog_db, plan)
    date_from, date_to = _window_of(plan)

    assert result["summary"]["announcement_count"] == _direct_announcement_count(
        catalog_db, date_from=date_from, date_to=date_to, category="Servc"
    )


@pytest.mark.parametrize(
    "query",
    [
        "도로공사 공고 몇 건",
        "건설공사 공고 몇 건",
        "인입철도공사 공고 몇 건",
    ],
)
def test_construction_phrases_do_not_become_institution_scope(catalog_db, query: str):
    """분야어·사업명으로도 읽히는 공사 낱말은 기관 조건으로 승격하지 않습니다."""
    plan = build_retrieval_plan(query)

    assert "institution_name" not in plan.filters
    assert plan.filters.get("category") == "Cnstwk"
