"""
tests/test_chat_winner_axis.py

업체 순위 질의의 축 판정, 실시간 집계, 기간 명시 응답을 검증합니다.

업체 축은 낙찰 결과 테이블의 bidwinnr_nm 으로만 집계하고, 기간 조건이 있으면
스냅샷을 쓰지 않습니다. 손상값·빈 업체명 제외와 동점 순서 고정, 개체 지목
질의 보호, 기존 축 질의 유지를 함께 고정합니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.rag import query_planning, structured_data
from src.rag.answer_format import _build_axis_answer
from src.rag.query_planning import DEFAULT_GROUP_LIMIT, build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

FIXED_TODAY = date(2026, 10, 25)


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def fixed_today(monkeypatch):
    """상대 기간 해석 기준일을 고정합니다."""

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return FIXED_TODAY

    monkeypatch.setattr(query_planning, "date", _FixedDate)
    return FIXED_TODAY


def _seed_result(
    session,
    *,
    row_id: int,
    winner: str,
    opened_at: datetime,
    category: str = "Cnstwk",
    institution: str = "서울특별시",
    rate: float | None = 90.0,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=winner,
            sucsf_bid_amt=1000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def test_recent_month_category_winner_uses_window_and_live_count(isolated_db, fixed_today):
    """T01: 기간·분류가 있는 업체 1위는 그 창의 실시간 집계로 답합니다."""
    _seed_result(isolated_db, row_id=1, winner="가나건설", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    _seed_result(isolated_db, row_id=2, winner="가나건설", opened_at=datetime(2026, 10, 2, 9, 0, 0))
    _seed_result(isolated_db, row_id=3, winner="가나건설", opened_at=datetime(2026, 10, 3, 9, 0, 0))
    _seed_result(isolated_db, row_id=4, winner="다라건설", opened_at=datetime(2026, 10, 4, 9, 0, 0))
    # 창 시작(2026-09-26) 이전이라 집계에서 빠져야 합니다.
    _seed_result(isolated_db, row_id=5, winner="가나건설", opened_at=datetime(2026, 9, 25, 9, 0, 0))
    _seed_result(
        isolated_db,
        row_id=6,
        winner="마바상사",
        opened_at=datetime(2026, 10, 5, 9, 0, 0),
        category="Servc",
    )
    isolated_db.commit()

    plan = build_retrieval_plan("최근 한 달 동안 공사 쪽에서 낙찰 많이 한 업체 1위는 몇 건이야?")

    assert plan.filters["category"] == "Cnstwk"
    assert plan.filters["date_from"] == "2026-09-26"
    assert plan.filters["date_to"] == "2026-10-25"
    assert plan.filters["group_by"] == "winner"
    assert plan.filters["metric"] == "bid_count"
    assert plan.filters["group_limit"] == 1

    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    breakdown = summary["axis_breakdown"]

    assert len(breakdown) == 1
    assert breakdown[0]["label"] == "가나건설"
    assert breakdown[0]["bid_count"] == 3
    assert summary["aggregate_meta"]["metric"] == "bid_count"
    assert summary["aggregate_meta"]["window"] == {
        "date_from": "2026-09-26",
        "date_to": "2026-10-25",
    }


def test_winner_axis_without_period_states_full_period(isolated_db, fixed_today):
    """T02: 기간이 없는 업체 1위는 전체 기간 기준임을 표 위에 밝힙니다."""
    _seed_result(isolated_db, row_id=1, winner="가나건설", opened_at=datetime(2020, 1, 1, 9, 0, 0))
    _seed_result(isolated_db, row_id=2, winner="가나건설", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    _seed_result(isolated_db, row_id=3, winner="다라건설", opened_at=datetime(2026, 10, 2, 9, 0, 0))
    isolated_db.commit()

    plan = build_retrieval_plan("공사 쪽에서 낙찰 많이 한 업체 1위는 몇 건이야?")
    assert "date_from" not in plan.filters
    assert plan.filters["group_by"] == "winner"
    assert plan.filters["group_limit"] == 1

    result = retrieve_structured_data(isolated_db, plan)
    answer = _build_axis_answer(plan, result)

    assert result["summary"]["axis_breakdown"][0]["label"] == "가나건설"
    assert "전체 기간 기준" in answer
    assert "건설 업체별 낙찰 건수입니다." in answer


def test_winner_axis_without_category_states_all_categories(isolated_db, fixed_today):
    """T03: 분류가 없는 질문은 전체 분야임을 밝히고 모든 분류를 합산합니다."""
    _seed_result(isolated_db, row_id=1, winner="가나건설", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    for offset in range(3):
        _seed_result(
            isolated_db,
            row_id=2 + offset,
            winner="다라상사",
            opened_at=datetime(2026, 10, 2 + offset, 9, 0, 0),
            category="Servc",
        )
    isolated_db.commit()

    plan = build_retrieval_plan("최근 한 달 동안 가장 많이 낙찰받은 업체는 몇 건이야?")
    assert "category" not in plan.filters
    assert plan.filters["group_by"] == "winner"

    result = retrieve_structured_data(isolated_db, plan)
    answer = _build_axis_answer(plan, result)

    assert result["summary"]["axis_breakdown"][0]["label"] == "다라상사"
    assert result["summary"]["axis_breakdown"][0]["bid_count"] == 3
    assert "2026-09-26 ~ 2026-10-25" in answer
    assert "전체 분야 업체별 낙찰 건수입니다." in answer


def test_top_n_winner_query_returns_requested_rows(isolated_db):
    """T07: "상위 10개" 는 5개로 조용히 잘리지 않고 10행을 냅니다."""
    row_id = 1
    for index in range(12):
        winner = f"업체{index:02d}"
        for _ in range((index % 3) + 1):
            _seed_result(
                isolated_db,
                row_id=row_id,
                winner=winner,
                opened_at=datetime(2026, 10, 1, 9, 0, 0),
                category="Servc",
            )
            row_id += 1
    isolated_db.commit()

    plan = build_retrieval_plan("용역 낙찰 업체 순위 상위 10개 보여줘")
    assert plan.filters["category"] == "Servc"
    assert plan.filters["group_by"] == "winner"
    assert plan.filters["metric"] == "bid_count"
    assert plan.filters["group_limit"] == 10

    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    breakdown = summary["axis_breakdown"]

    assert len(breakdown) == 10
    assert summary["aggregate_meta"]["truncated"] is True
    counts = [item["bid_count"] for item in breakdown]
    assert counts == sorted(counts, reverse=True)


def test_rank_count_without_top_marker_sets_group_limit(isolated_db):
    """T07 변형: "업체 순위 10개" 도 같은 행 수로 읽습니다."""
    plan = build_retrieval_plan("공사 낙찰 업체 순위 10개")

    assert plan.filters["group_by"] == "winner"
    assert plan.filters["group_limit"] == 10


def test_winner_axis_excludes_corrupted_and_empty_names(isolated_db):
    """T09: 손상 업체명과 빈 업체명은 순위에서 제외합니다."""
    row_id = 1
    for _ in range(5):
        _seed_result(
            isolated_db,
            row_id=row_id,
            winner="깨진\ufffd업체",
            opened_at=datetime(2026, 10, 1, 9, 0, 0),
        )
        row_id += 1
    for _ in range(4):
        _seed_result(
            isolated_db, row_id=row_id, winner="", opened_at=datetime(2026, 10, 1, 9, 0, 0)
        )
        row_id += 1
    for _ in range(2):
        _seed_result(
            isolated_db, row_id=row_id, winner="정상업체", opened_at=datetime(2026, 10, 1, 9, 0, 0)
        )
        row_id += 1
    isolated_db.commit()

    plan = build_retrieval_plan("업체별 낙찰 건수 알려줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    breakdown = summary["axis_breakdown"]

    assert [item["label"] for item in breakdown] == ["정상업체"]
    assert breakdown[0]["bid_count"] == 2


def test_winner_axis_orders_ties_by_name(isolated_db):
    """동점이면 업체명 오름차순으로 고정해 응답 순서가 흔들리지 않습니다."""
    _seed_result(isolated_db, row_id=1, winner="나중업체", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    _seed_result(isolated_db, row_id=2, winner="나중업체", opened_at=datetime(2026, 10, 2, 9, 0, 0))
    _seed_result(isolated_db, row_id=3, winner="가나업체", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    _seed_result(isolated_db, row_id=4, winner="가나업체", opened_at=datetime(2026, 10, 2, 9, 0, 0))
    isolated_db.commit()

    plan = build_retrieval_plan("업체별 낙찰 건수 알려줘")
    breakdown = retrieve_structured_data(isolated_db, plan)["summary"]["axis_breakdown"]

    assert [item["label"] for item in breakdown] == ["가나업체", "나중업체"]


def test_winner_axis_with_rate_marker_aggregates_average_rate(isolated_db):
    """업체별 평균 낙찰률 질의는 낙찰 건수가 아니라 평균 낙찰률을 집계합니다."""
    _seed_result(
        isolated_db,
        row_id=1,
        winner="가나건설",
        opened_at=datetime(2026, 10, 1, 9, 0, 0),
        rate=80.0,
    )
    _seed_result(
        isolated_db,
        row_id=2,
        winner="가나건설",
        opened_at=datetime(2026, 10, 2, 9, 0, 0),
        rate=90.0,
    )
    _seed_result(
        isolated_db,
        row_id=3,
        winner="다라건설",
        opened_at=datetime(2026, 10, 3, 9, 0, 0),
        rate=95.0,
    )
    _seed_result(
        isolated_db,
        row_id=4,
        winner="다라건설",
        opened_at=datetime(2026, 10, 4, 9, 0, 0),
        rate=95.0,
    )
    # 낙찰률이 없는 행과 손상 업체명은 평균과 순위에서 빠집니다.
    _seed_result(
        isolated_db,
        row_id=5,
        winner="마바상사",
        opened_at=datetime(2026, 10, 5, 9, 0, 0),
        rate=None,
    )
    _seed_result(
        isolated_db,
        row_id=6,
        winner="깨진\ufffd업체",
        opened_at=datetime(2026, 10, 6, 9, 0, 0),
        rate=99.0,
    )
    isolated_db.commit()

    plan = build_retrieval_plan("업체별 평균 낙찰률 알려줘")
    assert plan.filters["group_by"] == "winner"
    assert plan.filters["metric"] == "avg_rate"
    assert plan.filters["group_limit"] == DEFAULT_GROUP_LIMIT

    result = retrieve_structured_data(isolated_db, plan)
    summary = result["summary"]

    assert summary["aggregate_meta"]["metric"] == "avg_rate"
    assert [(item["label"], item["avg_rate"]) for item in summary["axis_breakdown"]] == [
        ("다라건설", 95.0),
        ("가나건설", 85.0),
    ]

    answer = _build_axis_answer(plan, result)
    assert "업체별 평균 낙찰률입니다." in answer
    assert "| 업체 | 평균 낙찰률 |" in answer
    assert "낙찰 건수" not in answer


@pytest.mark.parametrize(
    ("query", "category", "expected_limit"),
    [
        ("지금 가장 많이 낙찰받은 업체는 몇 건이야?", None, 1),
        ("최근 한 달 동안 가장 많이 낙찰받은 업체는 몇 건이야?", None, 1),
        ("제일 많이 낙찰한 용역 업체", "Servc", 1),
        ("업체별 최다 낙찰 업체", None, 1),
        ("공사 쪽에서 낙찰 많이 한 업체 1등은 몇 건이야?", "Cnstwk", 1),
        ("용역 낙찰 업체 순위 상위 10개 보여줘", "Servc", 10),
    ],
)
def test_winner_group_limit_reads_rank_markers(query, category, expected_limit):
    """가장 많이·제일 많이·최다·1등·1위는 1행, 상위 N 은 N행으로 읽습니다."""
    filters = build_retrieval_plan(query).filters

    assert filters["group_by"] == "winner"
    assert filters["group_limit"] == expected_limit
    if category:
        assert filters["category"] == category


def test_dated_winner_axis_does_not_use_ranking_snapshot(isolated_db, fixed_today, monkeypatch):
    """T13: 기간이 있는 업체 순위는 스냅샷을 읽지 않고 실시간으로 집계합니다."""

    def _fail(*args, **kwargs):
        raise AssertionError("기간이 있는 업체 축은 스냅샷을 쓰면 안 됩니다.")

    monkeypatch.setattr(structured_data, "get_top_rankings", _fail)
    _seed_result(isolated_db, row_id=1, winner="가나건설", opened_at=datetime(2026, 10, 1, 9, 0, 0))
    isolated_db.commit()

    plan = build_retrieval_plan("최근 한 달 동안 공사 쪽에서 낙찰 많이 한 업체 1위는 몇 건이야?")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["axis_breakdown"][0]["label"] == "가나건설"


@pytest.mark.parametrize(
    "query",
    [
        "주식회사 한백 낙찰 건수 알려줘",
        "(주)대광기공 낙찰 결과",
        "주식회사 한백 업체별 낙찰 건수 알려줘",
        "(주)대광기공 낙찰 업체 순위 알려줘",
    ],
)
def test_entity_specific_queries_are_not_winner_axis(query):
    """개체를 지목한 질의는 업체 순위 축으로 새지 않습니다."""
    assert "group_by" not in build_retrieval_plan(query).filters


@pytest.mark.parametrize(
    ("query", "axis", "metric"),
    [
        ("분류별 평균 낙찰률 알려줘", "category", "avg_rate"),
        ("기관별 낙찰 건수 알려줘", "institution", "bid_count"),
        ("지역별 공고 건수 알려줘", "region", "announcement_count"),
    ],
)
def test_existing_axes_keep_their_routing(query, axis, metric):
    """기존 분류·기관·지역 축 질의는 같은 축과 기본 행 수를 유지합니다."""
    filters = build_retrieval_plan(query).filters

    assert filters["group_by"] == axis
    assert filters["metric"] == metric
    assert filters["group_limit"] == DEFAULT_GROUP_LIMIT


def test_winner_answer_renders_period_and_category_caption():
    """업체 표는 기간·분야를 표 위 문장에 명시하고 한 지표만 냅니다."""
    plan = RetrievalPlan(
        filters={
            "group_by": "winner",
            "metric": "bid_count",
            "category": "Cnstwk",
            "group_limit": 1,
            "date_from": "2026-09-26",
            "date_to": "2026-10-25",
        }
    )
    structured = {
        "filters": {"category_label": "공사"},
        "summary": {
            "axis_breakdown": [
                {
                    "label": "가나건설",
                    "key": "가나건설",
                    "announcement_count": None,
                    "bid_count": 201,
                    "avg_rate": None,
                    "sample_count": None,
                }
            ],
            "aggregate_meta": {
                "group_by": "winner",
                "metric": "bid_count",
                "limit": 1,
                "truncated": False,
                "window": {
                    "date_from": "2026-09-26",
                    "date_to": "2026-10-25",
                },
            },
        },
    }

    answer = _build_axis_answer(plan, structured)

    assert "2026-09-26 ~ 2026-10-25 공사 업체별 낙찰 건수입니다." in answer
    assert "| 업체 | 낙찰 건수 |" in answer
    assert "| 가나건설 | 201 |" in answer
    assert "공고 건수" not in answer
