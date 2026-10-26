"""
tests/test_unresolved_institution_failclosed.py

기간 비교 질의에서 기관 후보를 공사·공단 접미사로 거르지 않고 기관 카탈로그로
대조하는 판정을 검증합니다.

- 기금·공단처럼 접미사가 다른 실제 기관도 공통 기관 조건을 만듭니다.
- 카탈로그에서 확인하지 못한 기관 후보는 전체 기관 값으로 넓히지 않고
  미해석 안내로 끝냅니다.
- 기간·분야·지역 낱말은 기관 후보로 남지 않아 기관 없는 기간 비교가 그대로
  전체 값을 냅니다.
- 지역 별칭 기간 비교와 분류 비교는 기존 판정을 유지합니다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import query_planning
from src.rag.answer_format import _build_comparison_answer
from src.rag.query_planning import (
    _comparison_unresolved_institution_candidate,
    build_retrieval_plan,
)
from src.rag.structured_data import retrieve_structured_data

# 기간 비교의 진행 중 창이 2026-10-26 까지 닫히도록 고정합니다.
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
            sucsf_bid_rate=90.0,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def _seed_catalog_rows(session) -> None:
    """기관별·기간별 값이 전체 값과 우연히 같아지지 않도록 행을 배치합니다."""
    announcements = [
        # 기술보증기금: 2025 2건, 2026 3건(10월 26일 포함)
        (1, datetime(2025, 2, 11, 9), "Servc", "기술보증기금"),
        (2, datetime(2025, 11, 20, 9), "Cnstwk", "기술보증기금"),
        (3, datetime(2026, 1, 15, 9), "Servc", "기술보증기금"),
        (4, datetime(2026, 7, 1, 9), "Thng", "기술보증기금"),
        (5, datetime(2026, 10, 26, 9), "Servc", "기술보증기금"),
        # 신용보증기금: 2025 1건, 2026 4건
        (6, datetime(2025, 6, 1, 9), "Servc", "신용보증기금"),
        (7, datetime(2026, 2, 1, 9), "Servc", "신용보증기금"),
        (8, datetime(2026, 3, 1, 9), "Servc", "신용보증기금"),
        (9, datetime(2026, 4, 1, 9), "Cnstwk", "신용보증기금"),
        (10, datetime(2026, 5, 1, 9), "Thng", "신용보증기금"),
        # 한국산업인력공단: 2025 3건, 2026 0건
        (11, datetime(2025, 1, 10, 9), "Servc", "한국산업인력공단"),
        (12, datetime(2025, 4, 10, 9), "Cnstwk", "한국산업인력공단"),
        (13, datetime(2025, 12, 10, 9), "Thng", "한국산업인력공단"),
        # 부산광역시청: 2025 1건, 2026 2건
        (14, datetime(2025, 8, 8, 9), "Servc", "부산광역시청"),
        (15, datetime(2026, 2, 8, 9), "Servc", "부산광역시청"),
        (16, datetime(2026, 9, 8, 9), "Cnstwk", "부산광역시청"),
        # 다른기관: 2025 5건, 2026 6건
        (17, datetime(2025, 1, 1, 9), "Servc", "다른기관"),
        (18, datetime(2025, 2, 1, 9), "Servc", "다른기관"),
        (19, datetime(2025, 3, 1, 9), "Servc", "다른기관"),
        (20, datetime(2025, 4, 1, 9), "Servc", "다른기관"),
        (21, datetime(2025, 5, 1, 9), "Servc", "다른기관"),
        (22, datetime(2026, 1, 1, 9), "Servc", "다른기관"),
        (23, datetime(2026, 2, 1, 9), "Servc", "다른기관"),
        (24, datetime(2026, 3, 1, 9), "Servc", "다른기관"),
        (25, datetime(2026, 4, 1, 9), "Servc", "다른기관"),
        (26, datetime(2026, 5, 1, 9), "Servc", "다른기관"),
        (27, datetime(2026, 6, 1, 9), "Servc", "다른기관"),
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
        (101, datetime(2025, 5, 1, 9), "Servc", "기술보증기금"),
        (102, datetime(2026, 2, 1, 9), "Servc", "신용보증기금"),
        (103, datetime(2026, 3, 1, 9), "Servc", "신용보증기금"),
        (104, datetime(2025, 7, 1, 9), "Cnstwk", "다른기관"),
        (105, datetime(2026, 4, 1, 9), "Cnstwk", "다른기관"),
        (106, datetime(2026, 8, 1, 9), "Cnstwk", "다른기관"),
    ]
    for row_id, opened_at, category, institution in results:
        _seed_result(
            session,
            row_id=row_id,
            opened_at=opened_at,
            category=category,
            institution=institution,
        )
    session.commit()


@pytest.fixture
def catalog_db(isolated_db):
    _seed_catalog_rows(isolated_db)
    return isolated_db


def _comparison_map(summary: dict) -> dict[str, dict]:
    return {item["key"]: item for item in summary.get("comparison") or []}


def _direct_announcement_counts(
    db,
    targets: list[dict],
    *,
    institution: str = "",
    category: str = "",
) -> dict[str, int]:
    """플래너 코드를 거치지 않고 대상 창마다 직접 집계합니다."""
    counts: dict[str, int] = {}
    for target in targets:
        start = datetime.fromisoformat(str(target["date_from"]))
        end = datetime.fromisoformat(str(target["date_to"]))
        conditions = [
            BidAnnouncement.bid_ntce_dt >= start,
            BidAnnouncement.bid_ntce_dt < end + timedelta(days=1),
        ]
        if institution:
            conditions.append(BidAnnouncement.dminstt_nm == institution)
        if category:
            conditions.append(BidAnnouncement.category == category)
        counts[str(target["key"])] = int(
            db.execute(
                select(func.count()).select_from(BidAnnouncement).where(*conditions)
            ).scalar_one()
        )
    return counts


@pytest.mark.parametrize(
    ("query", "institution"),
    [
        ("기술보증기금 작년 대비 올해 공고 건수", "기술보증기금"),
        ("신용보증기금 작년 대비 올해 공고 건수", "신용보증기금"),
        ("한국산업인력공단 작년 대비 올해 공고 건수", "한국산업인력공단"),
    ],
)
def test_catalog_institution_period_comparison_counts_only_that_institution(
    catalog_db, query: str, institution: str
):
    """접미사와 무관하게 카탈로그에서 확인된 기관은 그 기관 행만 셉니다."""
    plan = build_retrieval_plan(query)
    targets = plan.filters["comparison_targets"]

    assert plan.filters.get("comparison_dimension") == "time"
    assert plan.filters.get("institution_name") == institution

    result = retrieve_structured_data(catalog_db, plan)
    entries = _comparison_map(result["summary"])

    expected = _direct_announcement_counts(catalog_db, targets, institution=institution)
    all_institutions = _direct_announcement_counts(catalog_db, targets)
    for key, count in expected.items():
        assert entries[key]["announcement_count"] == count
    assert any(expected[key] != all_institutions[key] for key in expected)
    assert result.get("query_skipped") is not True

    answer = _build_comparison_answer(plan, result)
    assert f"{institution} 범위에서 두 대상을 같은 지표로 집계했습니다." in answer


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        ("없는기관진흥원 작년 대비 올해 공고 건수", "없는기관진흥원"),
        ("없는기관공사 작년 대비 올해 공고 건수", "없는기관공사"),
    ],
)
def test_unknown_institution_period_comparison_reports_unresolved(
    catalog_db, query: str, candidate: str
):
    """카탈로그에서 확인하지 못한 기관 후보는 전체 값이 아니라 미해석 안내로 끝냅니다."""
    plan = build_retrieval_plan(query)

    assert plan.filters.get("comparison_dimension") == "time"
    assert plan.filters.get("institution_name") == candidate

    result = retrieve_structured_data(catalog_db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["announcement_count"] is None
    assert "comparison" not in result["summary"]
    assert any("확정하지 못했습니다" in hint for hint in result["insufficiency_hints"])


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("작년 대비 올해 공고 건수", ""),
        ("작년 대비 올해 용역 공고 건수", "Servc"),
        ("지난달 대비 이번 달 공고 건수", ""),
        ("이번 분기 대비 지난 분기 용역 낙찰 건수", "Servc"),
        ("2024년과 2025년 낙찰 건수 비교", ""),
    ],
)
def test_institution_free_period_comparison_keeps_all_rows(catalog_db, query: str, category: str):
    """기간·분야 낱말은 기관 후보가 아니므로 전체 기관 값을 그대로 냅니다."""
    plan = build_retrieval_plan(query)

    assert plan.filters.get("comparison_dimension") == "time"
    assert "institution_name" not in plan.filters
    assert _comparison_unresolved_institution_candidate(query) == ""

    result = retrieve_structured_data(catalog_db, plan)

    assert result.get("query_skipped") is not True
    entries = _comparison_map(result["summary"])
    expected = _direct_announcement_counts(
        catalog_db, plan.filters["comparison_targets"], category=category
    )
    for key, count in expected.items():
        assert entries[key]["announcement_count"] == count


def test_region_period_comparison_keeps_broad_region_alias(catalog_db):
    """광역 지역명 기간 비교는 기존 이름·별칭 조건을 그대로 씁니다."""
    plan = build_retrieval_plan("부산 작년 대비 올해 공고 건수")

    assert plan.filters.get("comparison_dimension") == "time"
    assert plan.filters.get("institution_name") == "부산"
    assert plan.filters.get("institution_aliases") == ["부산"]

    result = retrieve_structured_data(catalog_db, plan)
    entries = _comparison_map(result["summary"])
    expected = _direct_announcement_counts(
        catalog_db, plan.filters["comparison_targets"], institution="부산광역시청"
    )
    for key, count in expected.items():
        assert entries[key]["announcement_count"] == count


def test_category_comparison_has_no_institution_candidate(catalog_db):
    """분류 비교는 기관 후보를 만들지 않고 두 분류만 집계합니다."""
    query = "공사랑 용역 낙찰 건수 비교해줘"
    plan = build_retrieval_plan(query)

    assert plan.filters.get("comparison_dimension") == "category"
    assert "institution_name" not in plan.filters
    assert _comparison_unresolved_institution_candidate(query) == ""

    result = retrieve_structured_data(catalog_db, plan)
    entries = _comparison_map(result["summary"])

    assert entries["Cnstwk"]["bid_count"] == 3
    assert entries["Servc"]["bid_count"] == 3
