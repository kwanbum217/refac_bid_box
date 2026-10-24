"""
tests/test_announcement_list_query.py

낙찰 표지 없는 공고 목록 질의의 판정, 정형 조회 필터, 직접 표 답변을 검증합니다.
"""

from datetime import datetime

import pytest

from src.app.models.bids import BidAnnouncement
from src.app.services.planner_interpreter import interpret_request
from src.rag.answer_format import _build_announcement_list_answer
from src.rag.query_planning import build_retrieval_plan, is_announcement_list_query
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


@pytest.mark.parametrize(
    "query",
    [
        "최근 용역 공고 5개만 리스트해줘",
        "공고 목록 보여줘",
        "물품 공고 10건",
        "서울시 공사 공고 목록 보여줘",
        "조달청 용역 공고 3건 뽑아줘",
    ],
)
def test_announcement_list_query_matches_request(query):
    assert is_announcement_list_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "공고 목록 작성 방법 알려줘",
        "공고 목록 관련 규정 설명해줘",
        "공고 목록은 어디서 봐?",
        "공고 리스트 기능 있어?",
        "입찰공고 목록 보는 법",
        "공고 5개 이상 동시에 투찰 가능해?",
    ],
)
def test_announcement_list_query_excludes_explanatory_questions(query):
    assert is_announcement_list_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "최근 낙찰 결과 5개 리스트",
        "용역 공고 낙찰률 평균",
        "공고번호 R26BK01775039 알려줘",
        "최근 입찰 동향 알려줘",
    ],
)
def test_announcement_list_query_excludes_result_and_statistics_queries(query):
    assert is_announcement_list_query(query) is False


def test_announcement_list_query_excludes_field_lookup_and_distant_marker():
    assert (
        is_announcement_list_query(
            "광주시 소하천정비종합계획 재수립 용역(봉골천 등 33개소)(PQ 후 가격입찰)의 "
            "공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"
        )
        is False
    )
    assert (
        is_announcement_list_query(
            "2025년 12월 31일 23시 59분에 마감된 공고와 2026년 1월 1일 00시에 공고된 사업의 "
            "연도 구분을 정확히 하여 2026년도 신규 사업만 골라줘"
        )
        is False
    )


def test_retrieval_plan_uses_announcement_limit_without_result_limit():
    plan = build_retrieval_plan("최근 용역 공고 5개만 리스트해줘")

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("announcement_limit") == 5
    assert plan.filters.get("category") == "Servc"
    assert "result_limit" not in plan.filters


def _sample(index: int) -> dict:
    return {
        "bid_ntce_no": f"SERVC-{index:03d}",
        "bid_ntce_nm": f"용역 공고 {index}",
        "dminstt_nm": "수요기관",
        "presmpt_prce": 1000000 * index,
        "bid_ntce_dt": f"2026-10-{index:02d} 09:00:00",
        "bid_clse_dt": f"2026-10-{index + 1:02d} 18:00:00",
    }


def test_announcement_list_answer_builds_table_without_llm():
    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc", "announcement_limit": 5})
    structured_data = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {"sample_announcements": [_sample(i) for i in range(1, 6)]},
    }

    answer = _build_announcement_list_answer(plan, structured_data)

    assert answer.splitlines()[0] == "최근 용역 공고 5건입니다."
    assert "| # | 공고명(공고번호) | 수요기관 | 추정가격 | 공고일 | 마감일 |" in answer
    assert "용역 공고 1 (SERVC-001)" in answer
    assert "1,000,000원" in answer
    assert len([line for line in answer.splitlines() if line.startswith("| ")]) == 7


def test_announcement_list_answer_reports_zero_rows():
    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc", "announcement_limit": 5})
    structured_data = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {"sample_announcements": []},
    }

    assert (
        _build_announcement_list_answer(plan, structured_data)
        == "요청하신 기간에 조건에 맞는 용역 공고는 0건입니다."
    )


def test_announcement_list_answer_is_empty_for_other_queries():
    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})

    assert _build_announcement_list_answer(plan, {"summary": {"sample_announcements": []}}) == ""


def test_planner_routes_announcement_list_to_bid_query_tool():
    execution_plan = interpret_request("최근 용역 공고 5개만 리스트해줘")

    assert execution_plan.query_type == "answer"
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("announcement_limit") == 5
    assert "limit" not in execution_plan.parameters


def test_planner_keeps_winning_result_list_route():
    execution_plan = interpret_request("최근 낙찰 결과 5개 리스트")

    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("limit") == 5
    assert "announcement_limit" not in execution_plan.parameters


def test_structured_data_returns_requested_number_of_announcements(isolated_db):
    for index in range(1, 7):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=f"SERVC-{index:03d}",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm=f"용역 공고 {index}",
                dminstt_nm="수요기관",
                presmpt_prce=1000000 * index,
                bid_ntce_dt=datetime(2026, 10, index),
                bid_clse_dt=datetime(2026, 10, index + 1),
                collected_at=datetime(2026, 10, index),
            )
        )
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc", "announcement_limit": 5})
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert len(samples) == 5
    assert [sample["bid_ntce_no"] for sample in samples] == [
        "SERVC-006",
        "SERVC-005",
        "SERVC-004",
        "SERVC-003",
        "SERVC-002",
    ]
    assert samples[0]["bid_ntce_dt"] == "2026-10-06 00:00:00"
    assert samples[0]["presmpt_prce"] == 6000000
    assert samples[0]["category"] == "Servc"
