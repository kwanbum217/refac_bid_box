"""
tests/test_chat_window_stats.py

기간 통계 질의(건수·평균 낙찰률)가 벡터 검색 거절로 새지 않고 DB 집계값을
직접 답하는지 검증합니다.

기준일은 2026-10-24 로 고정하고, structured_data 는 손으로 만든 dict 를 씁니다.
라우팅, 이번 달 기간 해석, 문맥 적용 조건 줄, 단일 지표 직접 응답 네 축을
각각 고정합니다.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.rag import query_planning
from src.rag.answer_format import _build_single_metric_answer
from src.rag.engine import HybridRAGEngine
from src.rag.query_planning import (
    _is_count_statistics_query,
    build_retrieval_plan,
    is_announcement_list_query,
)
from src.rag.snapshots import _extract_statistical_snapshot

_TODAY = date(2026, 10, 24)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """기간 해석이 실행 날짜에 흔들리지 않도록 기준일을 고정합니다."""
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


ROUTING_TRUE_CASES = [
    "이번 달 용역 낙찰이 총 몇 건이야?",
    "이번 달 용역 공고 몇 건 올라왔어?",
    "최근 7일 동안 올라온 공고 총 몇 건이야?",
    "지난달 공사 낙찰 건수 몇 건이야?",
    "이번 달 외자 공고 몇 건이야?",
]


@pytest.mark.parametrize("query", ROUTING_TRUE_CASES)
def test_count_phrases_route_to_statistics(query):
    """건수 표현과 공고·낙찰 표지가 함께 있으면 정형 통계 질의입니다."""
    assert _is_count_statistics_query(query) is True
    assert build_retrieval_plan(query).use_sql is True


@pytest.mark.parametrize(
    "query",
    [
        "공고 알려줘",
        "최근 용역 공고 5개만 리스트해줘",
    ],
)
def test_non_statistics_queries_do_not_become_count_statistics(query):
    """목록·일반 질의는 건수 통계로 바뀌지 않습니다."""
    assert _is_count_statistics_query(query) is False


def test_plain_announcement_request_stays_vector():
    """'공고 알려줘' 는 목록 신호도 건수 표현도 없어 기본 벡터 질의로 남습니다."""
    plan = build_retrieval_plan("공고 알려줘")

    assert plan.use_sql is False
    assert plan.use_vector is True


def test_announcement_list_request_stays_list():
    """'5개만 리스트' 는 통계가 아니라 공고 목록 질의입니다."""
    query = "최근 용역 공고 5개만 리스트해줘"

    assert is_announcement_list_query(query) is True
    assert build_retrieval_plan(query).filters.get("announcement_limit") == 5


def test_this_month_window_runs_from_first_day_to_today():
    """이번 달은 오늘이 속한 달의 1일부터 오늘까지입니다."""
    plan = build_retrieval_plan("이번 달 용역 공고 몇 건 올라왔어?")

    assert plan.filters.get("date_from") == "2026-10-01"
    assert plan.filters.get("date_to") == "2026-10-24"
    assert plan.filters.get("category") == "Servc"


def _summary() -> dict:
    return {
        "total_bids": 4857,
        "announcement_count": 10165,
        "average_winning_rate": 90.83,
        "total_winning_amount": 1000000.0,
        "top_winners": [],
        "top_institutions": [],
        "top_announcements": [],
        "sample_announcements": [],
        "recent_results": [],
        "latest_available_result_at": None,
        "time_series": [],
    }


def _structured_data(summary: dict | None = None, filters: dict | None = None) -> dict:
    return {
        "filters": filters if filters is not None else {},
        "summary": summary if summary is not None else _summary(),
        "insufficiency_hints": [],
    }


def test_statistical_snapshot_states_applied_conditions():
    """문맥 머리 아래에 실제 기간과 분류가 한 줄로 적힙니다."""
    structured = _structured_data(
        filters={
            "date_from": "2026-10-01",
            "date_to": "2026-10-24",
            "category": "Servc",
            "category_label": "용역",
        }
    )

    snapshot = _extract_statistical_snapshot(structured)

    assert "- 적용 조건: 기간 2026-10-01 ~ 2026-10-24, 분류 용역" in snapshot


def test_statistical_snapshot_states_whole_period_and_category_when_absent():
    """조건이 없으면 전체 기간·전체 분류로 밝힙니다."""
    snapshot = _extract_statistical_snapshot(_structured_data())

    assert "- 적용 조건: 기간 전체, 분류 전체" in snapshot


def test_statistical_snapshot_includes_region_and_institution_filters():
    """지역·기관 필터는 같은 적용 조건 줄에 덧붙습니다."""
    region_snapshot = _extract_statistical_snapshot(
        _structured_data(filters={"region_names": ["부산", "대구"]})
    )
    institution_snapshot = _extract_statistical_snapshot(
        _structured_data(filters={"institution_name": "서울"})
    )

    assert "지역 부산, 대구" in region_snapshot
    assert "지역 서울" in institution_snapshot


def test_single_metric_answers_bid_count_with_period_and_category():
    """최근 한 달 용역 낙찰 건수는 DB 집계값을 기간과 함께 답합니다."""
    plan = build_retrieval_plan("최근 한 달 용역 낙찰이 총 몇 건이야?")

    assert (
        _build_single_metric_answer(plan, _structured_data())
        == "2026-09-25 ~ 2026-10-24 용역 낙찰 건수는 4,857건입니다."
    )


def test_single_metric_answers_average_rate():
    """최근 2주 용역 평균 낙찰률은 소수 둘째 자리까지 답합니다."""
    plan = build_retrieval_plan("최근 2주 용역 평균 낙찰률은?")

    assert (
        _build_single_metric_answer(plan, _structured_data())
        == "2026-10-11 ~ 2026-10-24 용역 평균 낙찰률은 90.83%입니다."
    )


def test_single_metric_answers_announcement_count():
    """이번 달 용역 공고 건수는 공고 수를 답합니다."""
    plan = build_retrieval_plan("이번 달 용역 공고 몇 건 올라왔어?")

    assert (
        _build_single_metric_answer(plan, _structured_data())
        == "2026-10-01 ~ 2026-10-24 용역 공고는 10,165건입니다."
    )


def test_single_metric_is_empty_for_list_and_axis_questions():
    """목록·축 질문은 각자의 직접 응답이 맡으므로 단일 지표 응답을 내지 않습니다."""
    list_plan = build_retrieval_plan("최근 용역 공고 5개만 리스트해줘")
    axis_plan = build_retrieval_plan("분류별 공고 건수 알려줘")

    assert _build_single_metric_answer(list_plan, _structured_data()) == ""
    assert _build_single_metric_answer(axis_plan, _structured_data()) == ""


def test_single_metric_is_empty_when_value_is_none():
    """값이 None 이면 0 으로 답하지 않고 LLM 경로로 넘깁니다."""
    plan = build_retrieval_plan("이번 달 용역 낙찰 건수 몇 건이야?")
    summary = _summary()
    summary["total_bids"] = None

    assert _build_single_metric_answer(plan, _structured_data(summary=summary)) == ""


def test_single_metric_is_empty_for_ranking_and_explanatory_questions():
    """업체 순위·설명형 질문은 단일 지표 직접 응답 대상이 아닙니다."""
    ranking_plan = build_retrieval_plan("용역 낙찰 많이 한 업체 순위 알려줘")
    explanatory_plan = build_retrieval_plan("이번 달 용역 낙찰 건수가 왜 늘었어?")

    assert _build_single_metric_answer(ranking_plan, _structured_data()) == ""
    assert _build_single_metric_answer(explanatory_plan, _structured_data()) == ""


class _NoLlmBackend:
    name = "no-llm"

    def generate(self, *args, **kwargs) -> str:
        raise AssertionError("단일 지표 직접 응답은 LLM 을 호출하지 않습니다.")

    def stream_generate(self, *args, **kwargs):
        raise AssertionError("단일 지표 직접 응답은 LLM 을 호출하지 않습니다.")


def _tool_context() -> dict:
    return {"tool_results": {"bid_query": {"result": _structured_data()}}}


def _engine() -> HybridRAGEngine:
    engine = HybridRAGEngine()
    engine._backend_resolved = True
    engine._backend = _NoLlmBackend()
    return engine


def test_engine_sync_answers_single_metric_without_llm():
    """동기 사슬도 직접 응답 순서의 끝에서 단일 지표를 답합니다."""
    bundle = _engine().get_answer_sync(
        "이번 달 용역 공고 몇 건 올라왔어?",
        tool_context=_tool_context(),
    )

    assert "2026-10-01 ~ 2026-10-24 용역 공고는 10,165건입니다." in bundle.answer


def test_engine_stream_answers_single_metric_without_llm():
    """스트리밍 사슬도 같은 단일 지표 답을 done 이벤트에 싣습니다."""

    async def _collect() -> list[dict]:
        return [
            event
            async for event in _engine().stream_tokens(
                "이번 달 용역 공고 몇 건 올라왔어?",
                tool_context=_tool_context(),
            )
        ]

    events = asyncio.run(_collect())
    done = next(event for event in events if event.get("type") == "done")

    assert "2026-10-01 ~ 2026-10-24 용역 공고는 10,165건입니다." in done["final_answer"]
