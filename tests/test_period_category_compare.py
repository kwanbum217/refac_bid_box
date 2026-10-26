"""
tests/test_period_category_compare.py

기간·분류 비교 질의의 판정, 실시간 집계, 비교 표 응답 계약을 검증합니다.

- 기간 표현 두 개(올해·작년, 이번 달·지난달)는 기관명 후보로 남지 않고
  time 비교의 대상이 됩니다.
- 분야어 두 개(공사·용역)는 category 비교의 대상이 되며, 기관명 속 "공사"
  글자는 분야어로 오인하지 않습니다.
- 두 대상은 같은 지표로 각자의 기간 창·분류 조건에서 집계됩니다.
- 응답은 두 행과 차이 한 줄, 진행 중 기간 안내를 냅니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import query_planning
from src.rag.answer_format import _build_comparison_answer
from src.rag.query_planning import _extract_comparison_targets, build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data

_FROZEN_TODAY = date(2026, 10, 25)


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
    institution: str = "가나기관",
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
    rate: float,
    institution: str = "가나기관",
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=1_000_000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def _seed_period_category_rows(session) -> None:
    rows = [
        # 2025 Servc 2건, 2026 Servc 3건(10월 26일 1건은 올해 창 밖)
        (1, datetime(2025, 3, 2, 9), "Servc"),
        (2, datetime(2025, 12, 30, 9), "Servc"),
        (3, datetime(2026, 1, 1, 9), "Servc"),
        (4, datetime(2026, 6, 1, 9), "Servc"),
        (5, datetime(2026, 10, 25, 9), "Servc"),
        (6, datetime(2026, 10, 26, 9), "Servc"),
        # Cnstwk 2025 1건, 2026 2건
        (7, datetime(2025, 8, 1, 9), "Cnstwk"),
        (8, datetime(2026, 2, 1, 9), "Cnstwk"),
        (9, datetime(2026, 4, 1, 9), "Cnstwk"),
        # Thng 2025 1건, 2026 1건
        (10, datetime(2025, 5, 1, 9), "Thng"),
        (11, datetime(2026, 5, 1, 9), "Thng"),
    ]
    for row_id, ntce_dt, category in rows:
        _seed_announcement(session, row_id=row_id, ntce_dt=ntce_dt, category=category)

    results = [
        (101, datetime(2025, 5, 1, 9), "Servc", 90.0),
        (102, datetime(2025, 11, 1, 9), "Servc", 80.0),
        (103, datetime(2026, 2, 1, 9), "Servc", 95.0),
        (104, datetime(2026, 7, 1, 9), "Servc", 85.0),
        (105, datetime(2026, 10, 20, 9), "Servc", 75.0),
        (201, datetime(2025, 9, 1, 9), "Cnstwk", 70.0),
        (202, datetime(2025, 10, 1, 9), "Cnstwk", 72.0),
        (203, datetime(2026, 3, 1, 9), "Cnstwk", 88.0),
        (301, datetime(2025, 6, 1, 9), "Thng", 60.0),
        (302, datetime(2026, 6, 1, 9), "Thng", 65.0),
    ]
    for row_id, opened_at, category, rate in results:
        _seed_result(
            session,
            row_id=row_id,
            opened_at=opened_at,
            category=category,
            rate=rate,
        )
    session.commit()


def _seed_comparison_extra_rows(session) -> None:
    """분기·연도·분류 비교의 대상 값을 서로 다르게 만드는 추가 행입니다.

    기존 픽스처는 두 대상 값이 우연히 같아지므로, 비교 표가 대상별 창과 분류를
    실제로 구분했는지 확인할 수 있도록 값을 벌려 둡니다.
    """
    announcements = [
        (20, datetime(2026, 8, 3, 9), "Servc"),
        (21, datetime(2026, 9, 20, 9), "Servc"),
        (22, datetime(2026, 10, 5, 9), "Servc"),
        (23, datetime(2026, 9, 5, 9), "Cnstwk"),
        (24, datetime(2026, 10, 12, 9), "Thng"),
        (25, datetime(2026, 3, 10, 9), "Frgcpt"),
    ]
    for row_id, ntce_dt, category in announcements:
        _seed_announcement(session, row_id=row_id, ntce_dt=ntce_dt, category=category)

    results = [
        (401, datetime(2026, 8, 14, 9), "Servc", 80.0),
        (402, datetime(2026, 9, 30, 9), "Servc", 90.0),
        (403, datetime(2026, 10, 24, 9), "Servc", 70.0),
        (404, datetime(2024, 3, 1, 9), "Thng", 60.0),
        (405, datetime(2024, 7, 15, 9), "Servc", 75.0),
        (406, datetime(2024, 11, 20, 9), "Cnstwk", 85.0),
    ]
    for row_id, opened_at, category, rate in results:
        _seed_result(
            session,
            row_id=row_id,
            opened_at=opened_at,
            category=category,
            rate=rate,
        )
    session.commit()


def _seed_scoped_comparison_rows(session) -> None:
    """기관·지역 하나와 기간 비교가 섞인 질의의 공통 범위를 검증할 행입니다.

    기관별 값과 전체 값이 우연히 같아지지 않도록 다른 기관 행을 함께 둡니다.
    """
    announcements = [
        (30, datetime(2025, 4, 2, 9), "Servc", "한국전력공사"),
        (31, datetime(2026, 2, 2, 9), "Servc", "한국전력공사"),
        (32, datetime(2026, 9, 2, 9), "Servc", "한국전력공사"),
        (33, datetime(2025, 5, 2, 9), "Thng", "부산광역시청"),
        (34, datetime(2026, 3, 2, 9), "Thng", "부산광역시청"),
        (35, datetime(2026, 8, 2, 9), "Thng", "부산광역시청"),
        (36, datetime(2025, 6, 2, 9), "Thng", "공주시청"),
        (37, datetime(2026, 6, 2, 9), "Thng", "공주시청"),
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
        (500, datetime(2026, 9, 10, 9), "Servc", 80.0, "공주시청"),
        (501, datetime(2026, 9, 20, 9), "Servc", 90.0, "공주시청"),
        (502, datetime(2026, 10, 2, 9), "Servc", 70.0, "공주시청"),
        (503, datetime(2026, 10, 5, 9), "Servc", 60.0, "다른기관"),
        (504, datetime(2026, 9, 15, 9), "Servc", 50.0, "다른기관"),
    ]
    for row_id, opened_at, category, rate, institution in results:
        _seed_result(
            session,
            row_id=row_id,
            opened_at=opened_at,
            category=category,
            rate=rate,
            institution=institution,
        )
    session.commit()


def _comparison_map(summary: dict) -> dict[str, dict]:
    return {item["key"]: item for item in summary.get("comparison") or []}


@pytest.mark.parametrize(
    ("query", "dimension", "keys", "metric", "category"),
    [
        (
            "작년 대비 올해 용역 공고 건수 알려줘",
            "time",
            ["2025", "2026"],
            "announcement_count",
            "Servc",
        ),
        (
            "올해랑 작년 공사 평균 낙찰률 비교해줘",
            "time",
            ["2026", "2025"],
            "avg_rate",
            "Cnstwk",
        ),
        ("공사랑 용역 낙찰 건수 비교해줘", "category", ["Cnstwk", "Servc"], "bid_count", None),
        (
            "이번 분기 대비 지난 분기 용역 낙찰 건수",
            "time",
            ["2026-Q4", "2026-Q3"],
            "bid_count",
            "Servc",
        ),
        ("용역 대비 공사 평균 낙찰률", "category", ["Servc", "Cnstwk"], "avg_rate", None),
        (
            "지난달 대비 이번 달 공고 건수",
            "time",
            ["2026-09", "2026-10"],
            "announcement_count",
            None,
        ),
        ("2024년과 2025년 낙찰 건수 비교", "time", ["2024", "2025"], "bid_count", None),
        (
            "물품이랑 외자 공고 건수 비교",
            "category",
            ["Thng", "Frgcpt"],
            "announcement_count",
            None,
        ),
    ],
)
def test_comparison_plan_classifies_period_and_category(query, dimension, keys, metric, category):
    """기간·분류 비교는 기관명 후보를 만들지 않고 전용 차원으로 판정됩니다."""
    assert _extract_comparison_targets(query) == ([], [])

    filters = build_retrieval_plan(query).filters

    assert filters.get("comparison_dimension") == dimension
    assert [target["key"] for target in filters["comparison_targets"]] == keys
    assert filters.get("metric") == metric
    assert "institution_names" not in filters
    assert "region_names" not in filters
    if category:
        assert filters.get("category") == category
    else:
        assert "category" not in filters
    assert "date_from" not in filters
    assert "date_to" not in filters


def test_period_comparison_counts_each_window(isolated_db):
    """작년·올해 용역 공고 건수를 각자의 창에서 직접 센 값과 같게 냅니다."""
    _seed_period_category_rows(isolated_db)

    plan = build_retrieval_plan("작년 대비 올해 용역 공고 건수 알려줘")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    assert entries["2025"]["announcement_count"] == 2
    assert entries["2026"]["announcement_count"] == 3
    assert result["summary"]["comparison_meta"]["dimension"] == "time"
    assert result["summary"]["comparison_meta"]["metric"] == "announcement_count"

    answer = _build_comparison_answer(plan, result)
    assert "| 기간 | 공고 건수 |" in answer
    assert "| 2025년(1년 전체) | 2 |" in answer
    assert "| 2026년(1월 1일~10월 25일) | 3 |" in answer
    assert "1건 많습니다" in answer
    assert "2026년 10월 25일까지 집계된 진행 중 기간" in answer


def test_period_comparison_average_rate(isolated_db):
    """올해·작년 공사 평균 낙찰률을 한 표와 %p 차이로 냅니다."""
    _seed_period_category_rows(isolated_db)

    plan = build_retrieval_plan("올해랑 작년 공사 평균 낙찰률 비교해줘")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    assert entries["2026"]["avg_rate"] == pytest.approx(88.0)
    assert entries["2025"]["avg_rate"] == pytest.approx(71.0)
    assert entries["2026"]["sample_count"] == 1
    assert entries["2025"]["sample_count"] == 2

    answer = _build_comparison_answer(plan, result)
    assert "| 2026년(1월 1일~10월 25일) | 88.0000% |" in answer
    assert "| 2025년(1년 전체) | 71.0000% |" in answer
    assert "2025년(1년 전체)이(가) 2026년(1월 1일~10월 25일)보다 17.00%p 낮습니다." in answer


def test_category_comparison_bid_counts(isolated_db):
    """공사·용역 낙찰 건수를 분류별로 세고 지표 열 하나만 냅니다."""
    _seed_period_category_rows(isolated_db)

    plan = build_retrieval_plan("공사랑 용역 낙찰 건수 비교해줘")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    assert entries["Cnstwk"]["bid_count"] == 3
    assert entries["Servc"]["bid_count"] == 5
    assert result["summary"]["comparison_meta"]["dimension"] == "category"

    answer = _build_comparison_answer(plan, result)
    assert "분류별 낙찰 건수 비교입니다." in answer
    assert "| 건설 | 3 |" in answer
    assert "| 용역 | 5 |" in answer
    assert "2건 많습니다" in answer
    assert "공고 건수" not in answer


def test_quarter_comparison_counts_each_quarter_window(isolated_db):
    """이번 분기·지난 분기 창을 _parse_time_window 와 같은 산식으로 나눠 셉니다."""
    _seed_period_category_rows(isolated_db)
    _seed_comparison_extra_rows(isolated_db)

    plan = build_retrieval_plan("이번 분기 대비 지난 분기 용역 낙찰 건수")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 이번 분기(2026-10-01~10-25) 용역 낙찰 2건, 지난 분기(2026-07-01~09-30) 3건
    assert entries["2026-Q4"]["bid_count"] == 2
    assert entries["2026-Q3"]["bid_count"] == 3
    assert plan.filters.get("category") == "Servc"
    assert "institution_names" not in plan.filters

    meta = result["summary"]["comparison_meta"]
    assert meta["dimension"] == "time"
    assert meta["metric"] == "bid_count"
    periods = {item["key"]: item for item in meta["periods"]}
    assert periods["2026-Q4"]["date_from"] == "2026-10-01"
    assert periods["2026-Q4"]["date_to"] == "2026-10-25"
    assert periods["2026-Q4"]["ongoing"] is True
    assert periods["2026-Q3"]["date_from"] == "2026-07-01"
    assert periods["2026-Q3"]["date_to"] == "2026-09-30"
    assert periods["2026-Q3"]["ongoing"] is False

    answer = _build_comparison_answer(plan, result)
    assert "| 2026년 4분기(10월 1일~10월 25일) | 2 |" in answer
    assert "| 2026년 3분기(3개월 전체) | 3 |" in answer
    assert "1건 많습니다" in answer
    assert "2026년 10월 25일까지 집계된 진행 중 기간" in answer


def test_category_comparison_average_rate_with_marker_between(isolated_db):
    """대비 표지가 분야어 사이에 있어도 두 분류의 평균 낙찰률을 나란히 냅니다."""
    _seed_period_category_rows(isolated_db)

    plan = build_retrieval_plan("용역 대비 공사 평균 낙찰률")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 용역 (90+80+95+85+75)/5 = 85.0, 공사 (70+72+88)/3 = 76.6667
    assert entries["Servc"]["avg_rate"] == pytest.approx(85.0)
    assert entries["Servc"]["sample_count"] == 5
    assert entries["Cnstwk"]["avg_rate"] == pytest.approx(76.6667, abs=1e-4)
    assert entries["Cnstwk"]["sample_count"] == 3
    assert "category" not in plan.filters
    assert result["summary"]["comparison_meta"]["dimension"] == "category"
    assert result["summary"]["comparison_meta"]["metric"] == "avg_rate"

    answer = _build_comparison_answer(plan, result)
    assert "분류별 평균 낙찰률 비교입니다." in answer
    assert "| 용역 | 85.0000% |" in answer
    assert "| 건설 | 76.6667% |" in answer
    assert "8.33%p 낮습니다" in answer


def test_month_comparison_announcement_counts(isolated_db):
    """지난달·이번 달 공고 건수를 각자의 월 창에서 직접 센 값과 같게 냅니다."""
    _seed_period_category_rows(isolated_db)
    _seed_comparison_extra_rows(isolated_db)

    plan = build_retrieval_plan("지난달 대비 이번 달 공고 건수")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 지난달(2026-09) 2건, 이번 달(2026-10-01~10-25) 3건. 10월 26일 공고는 창 밖입니다.
    assert entries["2026-09"]["announcement_count"] == 2
    assert entries["2026-10"]["announcement_count"] == 3
    assert "category" not in plan.filters

    answer = _build_comparison_answer(plan, result)
    assert "| 2026년 9월(1개월 전체) | 2 |" in answer
    assert "| 2026년 10월(10월 1일~10월 25일) | 3 |" in answer
    assert "1건 많습니다" in answer


def test_spaced_last_month_comparison_counts_each_month(isolated_db):
    """띄어 쓴 지난 달도 기간 비교로 판정하고 각자의 월 창에서 셉니다."""
    _seed_period_category_rows(isolated_db)
    _seed_comparison_extra_rows(isolated_db)

    query = "이번 달 대비 지난 달 공사 공고 건수"
    assert _extract_comparison_targets(query) == ([], [])

    plan = build_retrieval_plan(query)
    filters = plan.filters

    assert filters.get("comparison_dimension") == "time"
    assert [target["key"] for target in filters["comparison_targets"]] == ["2026-10", "2026-09"]
    assert filters.get("category") == "Cnstwk"

    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 이번 달(2026-10-01~10-25) 공사 공고 0건, 지난 달(2026-09) 1건입니다.
    assert entries["2026-10"]["announcement_count"] == 0
    assert entries["2026-09"]["announcement_count"] == 1


def test_year_comparison_bid_counts(isolated_db):
    """연도 두 개의 낙찰 건수를 각자의 연 창에서 직접 센 값과 같게 냅니다."""
    _seed_period_category_rows(isolated_db)
    _seed_comparison_extra_rows(isolated_db)

    plan = build_retrieval_plan("2024년과 2025년 낙찰 건수 비교")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    assert entries["2024"]["bid_count"] == 3
    assert entries["2025"]["bid_count"] == 5

    answer = _build_comparison_answer(plan, result)
    assert "| 2024년(1년 전체) | 3 |" in answer
    assert "| 2025년(1년 전체) | 5 |" in answer
    assert "2건 많습니다" in answer


def test_category_comparison_announcement_counts(isolated_db):
    """물품·외자 공고 건수를 분류별로 직접 센 값과 같게 냅니다."""
    _seed_period_category_rows(isolated_db)
    _seed_comparison_extra_rows(isolated_db)

    plan = build_retrieval_plan("물품이랑 외자 공고 건수 비교")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 물품 (2025-05, 2026-05, 2026-10-12) 3건, 외자 (2026-03-10) 1건
    assert entries["Thng"]["announcement_count"] == 3
    assert entries["Frgcpt"]["announcement_count"] == 1
    assert "category" not in plan.filters

    answer = _build_comparison_answer(plan, result)
    assert "분류별 공고 건수 비교입니다." in answer
    assert "| 물품 | 3 |" in answer
    assert "| 외자 | 1 |" in answer
    assert "2건 적습니다" in answer


def test_bid_query_tool_category_comparison_keeps_both_categories(isolated_db):
    """도구가 분야 하나를 파라미터로 더해도 두 분류 집계가 유지됩니다."""
    from src.app.services.tools.bid_query_tool import execute

    _seed_period_category_rows(isolated_db)

    result = execute(
        db=isolated_db,
        query="공사랑 용역 낙찰 건수 비교해줘",
        category="Cnstwk",
        years=5,
    )
    summary = result["result"]["summary"]
    entries = _comparison_map(summary)

    assert entries["Cnstwk"]["bid_count"] == 3
    assert entries["Servc"]["bid_count"] == 5
    assert "category" not in result["result"]["filters"]


def test_region_and_institution_comparison_unchanged():
    """기존 지역·기관 비교 판정은 그대로 유지됩니다."""
    region_query = "부산이랑 대구 공고 건수 비교해줘"
    assert _extract_comparison_targets(region_query) == (["부산", "대구"], [])
    region_filters = build_retrieval_plan(region_query).filters
    assert region_filters.get("region_names") == ["부산", "대구"]
    assert "comparison_dimension" not in region_filters

    institution_query = "한국전력공사와 한국농어촌공사 낙찰률 비교"
    assert _extract_comparison_targets(institution_query) == (
        [],
        ["한국전력공사", "한국농어촌공사"],
    )
    institution_filters = build_retrieval_plan(institution_query).filters
    assert institution_filters.get("institution_names") == [
        "한국전력공사",
        "한국농어촌공사",
    ]
    assert "comparison_dimension" not in institution_filters


@pytest.mark.parametrize(
    ("query", "institution", "metric"),
    [
        ("한국전력공사 작년 대비 올해 공고 건수", "한국전력공사", "announcement_count"),
        ("공주시 이번 달 지난달 낙찰 건수 비교", "공주시", "bid_count"),
        ("부산 작년 대비 올해 공고 건수", "부산", "announcement_count"),
    ],
)
def test_institution_or_region_and_period_comparison_keeps_scope(query, institution, metric):
    """기관·지역 하나와 기간 비교가 섞여도 그 범위가 공통 조건으로 남습니다."""
    filters = build_retrieval_plan(query).filters

    assert filters.get("comparison_dimension") == "time"
    assert filters.get("institution_name") == institution
    assert filters.get("metric") == metric
    assert "institution_names" not in filters
    assert "region_names" not in filters


def test_institution_and_period_comparison_counts_only_that_institution(isolated_db):
    """한국전력공사 작년·올해 공고 건수가 그 기관 행만 센 값과 같습니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("한국전력공사 작년 대비 올해 공고 건수")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 전체 2025년 3건, 2026년 5건 중 한국전력공사 행은 1건, 2건입니다.
    assert entries["2025"]["announcement_count"] == 1
    assert entries["2026"]["announcement_count"] == 2
    assert result["summary"]["comparison_meta"]["scope"] == {"institution_name": "한국전력공사"}

    answer = _build_comparison_answer(plan, result)
    assert "한국전력공사 범위에서 두 대상을 같은 지표로 집계했습니다." in answer
    assert "| 2025년(1년 전체) | 1 |" in answer
    assert "| 2026년(1월 1일~10월 25일) | 2 |" in answer
    assert "1건 많습니다" in answer


def test_institution_and_month_comparison_counts_only_that_institution(isolated_db):
    """공주시 이번 달·지난달 낙찰 건수가 그 기관 행만 센 값과 같습니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("공주시 이번 달 지난달 낙찰 건수 비교")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 전체 2026-09 3건, 2026-10 2건 중 공주시청 행은 2건, 1건입니다.
    assert entries["2026-09"]["bid_count"] == 2
    assert entries["2026-10"]["bid_count"] == 1

    answer = _build_comparison_answer(plan, result)
    assert "공주시 범위에서 두 대상을 같은 지표로 집계했습니다." in answer
    assert "| 2026년 9월(1개월 전체) | 2 |" in answer
    assert "| 2026년 10월(10월 1일~10월 25일) | 1 |" in answer
    assert "1건 많습니다" in answer


def test_region_and_period_comparison_counts_only_that_region(isolated_db):
    """부산 작년·올해 공고 건수가 부산 기관 행만 센 값과 같습니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("부산 작년 대비 올해 공고 건수")
    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    # 전체 2025년 3건, 2026년 5건 중 부산광역시청 행은 1건, 2건입니다.
    assert entries["2025"]["announcement_count"] == 1
    assert entries["2026"]["announcement_count"] == 2

    answer = _build_comparison_answer(plan, result)
    assert "부산 범위에서 두 대상을 같은 지표로 집계했습니다." in answer


def test_region_and_period_comparison_matches_single_period_counts(isolated_db):
    """부산 기간 비교의 각 대상 값이 같은 범위의 단일 기간 질문 값과 같습니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("부산 작년 대비 올해 공고 건수")
    assert plan.filters.get("institution_name") == "부산"
    assert plan.filters.get("institution_aliases") == ["부산"]

    result = retrieve_structured_data(isolated_db, plan)
    entries = _comparison_map(result["summary"])

    for key, single_query in (
        ("2025", "부산 2025년 공고 건수"),
        ("2026", "부산 2026년 공고 건수"),
    ):
        single_result = retrieve_structured_data(isolated_db, build_retrieval_plan(single_query))
        assert entries[key]["announcement_count"] == single_result["summary"]["announcement_count"]


def test_unresolved_institution_comparison_does_not_widen_to_all(isolated_db):
    """해석되지 않은 기관은 전체로 넓히지 않고 기존 안내를 냅니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("없는시 작년 대비 올해 공고 건수")
    result = retrieve_structured_data(isolated_db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["announcement_count"] is None
    assert any("확정하지 못했습니다" in hint for hint in result["insufficiency_hints"])


def test_unresolved_corporation_comparison_does_not_widen_to_all(isolated_db):
    """기관명을 해석하지 못한 공기업 모양 후보도 전체 기관 값으로 넓히지 않습니다."""
    _seed_scoped_comparison_rows(isolated_db)

    plan = build_retrieval_plan("없는기관공사 작년 대비 올해 공고 건수")
    result = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("institution_name") == "없는기관공사"
    assert result["query_skipped"] is True
    assert result["summary"]["announcement_count"] is None
    assert "comparison" not in result["summary"]
    assert any("확정하지 못했습니다" in hint for hint in result["insufficiency_hints"])


class _RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args, **kwargs) -> str:
        self.calls += 1
        return "LLM 응답"


def test_comparison_engine_returns_direct_period_table_without_llm():
    """기간 비교 응답도 LLM 앞에서 결정론적 표로 조립됩니다."""
    from src.rag.engine import HybridRAGEngine

    structured = {
        "filters": {"category": "Servc", "metric": "announcement_count"},
        "summary": {
            "comparison": [
                {
                    "label": "2025년(1년 전체)",
                    "key": "2025",
                    "announcement_count": 120,
                    "bid_count": 90,
                    "avg_rate": 88.0,
                    "sample_count": 90,
                },
                {
                    "label": "2026년(1월 1일~10월 25일)",
                    "key": "2026",
                    "announcement_count": 150,
                    "bid_count": 110,
                    "avg_rate": 89.0,
                    "sample_count": 110,
                },
            ],
            "comparison_meta": {
                "dimension": "time",
                "metric": "announcement_count",
                "targets": ["2025년(1년 전체)", "2026년(1월 1일~10월 25일)"],
                "periods": [
                    {
                        "key": "2025",
                        "label": "2025년(1년 전체)",
                        "date_from": "2025-01-01",
                        "date_to": "2025-12-31",
                        "ongoing": False,
                        "days": 365,
                    },
                    {
                        "key": "2026",
                        "label": "2026년(1월 1일~10월 25일)",
                        "date_from": "2026-01-01",
                        "date_to": "2026-10-25",
                        "ongoing": True,
                        "days": 298,
                    },
                ],
            },
        },
        "insufficiency_hints": [],
    }

    engine = HybridRAGEngine()
    backend = _RecordingBackend()
    engine._backend_resolved = True
    engine._backend = backend

    bundle = engine.get_answer_sync(
        "작년 대비 올해 용역 공고 건수 알려줘",
        tool_context={"tool_results": {"bid_query": {"result": structured}}},
    )

    assert backend.calls == 0
    assert "| 2025년(1년 전체) | 120 |" in bundle.answer
    assert "| 2026년(1월 1일~10월 25일) | 150 |" in bundle.answer
    assert "30건 많습니다" in bundle.answer
    assert "2026년 10월 25일까지 집계된 진행 중 기간" in bundle.answer
    assert "90" not in bundle.answer


def test_single_period_question_is_not_comparison():
    """기간 표현이 하나뿐인 질의는 기존 단일 지표 경로를 유지합니다."""
    filters = build_retrieval_plan("올해 공사 공고 건수 알려줘").filters

    assert "comparison_dimension" not in filters
    assert "comparison_targets" not in filters
    assert filters.get("date_from") == "2026-01-01"
    assert filters.get("date_to") == "2026-10-25"
