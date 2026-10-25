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
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ANN-{row_id}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"공고 {row_id}",
            dminstt_nm="가나기관",
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
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"공고 {row_id}",
            dminstt_nm="가나기관",
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
