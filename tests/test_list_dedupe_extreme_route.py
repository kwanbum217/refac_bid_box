"""
tests/test_list_dedupe_extreme_route.py

공고 목록이 같은 공고번호의 정정·안내 행 때문에 개수를 잃지 않는지, 공고 금액
최댓값·최솟값 질의가 의미 검색이 아니라 정형 조회(bid_query_tool)로 가는지
검증합니다.
"""

from datetime import datetime

import pytest

from src.app.models.bids import BidAnnouncement
from src.app.services.planner import plan_chat_request
from src.rag.query_planning import build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data

LIST_QUERY = "추정가격 5억 이상 용역 공고 5개 보여줘"


def _announcement(
    bid_ntce_no: str,
    *,
    bid_ntce_dt: datetime,
    bid_ntce_ord: str = "000",
    bid_ntce_nm: str | None = None,
    category: str = "Servc",
    presmpt_prce: int | None = None,
    base_amount: int | None = None,
) -> BidAnnouncement:
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        category=category,
        bid_ntce_nm=bid_ntce_nm or f"공고 {bid_ntce_no}",
        dminstt_nm="수요기관",
        presmpt_prce=presmpt_prce,
        base_amount=base_amount,
        bid_ntce_dt=bid_ntce_dt,
        bid_clse_dt=bid_ntce_dt,
        collected_at=bid_ntce_dt,
    )


@pytest.fixture
def duplicated_rows(isolated_db):
    """정정·안내 행이 붙은 공고 하나와 다른 공고 다섯 개를 넣습니다."""
    rows = [
        _announcement(
            "R26BK01789549",
            bid_ntce_ord="000",
            bid_ntce_dt=datetime(2026, 10, 24, 9, 39, 30),
            bid_ntce_nm="용역 원공고",
            presmpt_prce=1_546_200_000,
        ),
        _announcement(
            "R26BK01789549",
            bid_ntce_ord="001",
            bid_ntce_dt=datetime(2026, 10, 24, 9, 44, 2),
            bid_ntce_nm="용역 PQ 제출 안내 공고",
            presmpt_prce=1_546_200_000,
        ),
        _announcement(
            "R26BK01787467",
            bid_ntce_dt=datetime(2026, 10, 23, 10, 0),
            presmpt_prce=1_200_000_000,
        ),
        _announcement(
            "R26BK01789392",
            bid_ntce_dt=datetime(2026, 10, 22, 10, 0),
            presmpt_prce=1_100_000_000,
        ),
        _announcement(
            "R26BK01789749",
            bid_ntce_dt=datetime(2026, 10, 21, 10, 0),
            presmpt_prce=1_000_000_000,
        ),
        _announcement(
            "R26BK01790123",
            bid_ntce_dt=datetime(2026, 10, 20, 10, 0),
            presmpt_prce=900_000_000,
        ),
        _announcement(
            "R26BK01790456",
            bid_ntce_dt=datetime(2026, 10, 19, 10, 0),
            presmpt_prce=800_000_000,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


@pytest.fixture
def three_unique_rows(isolated_db):
    """중복 행을 걷어내면 고유 공고가 세 건뿐인 목록을 만듭니다."""
    rows = [
        _announcement(
            "R26BK01800001",
            bid_ntce_ord="000",
            bid_ntce_dt=datetime(2026, 10, 24, 9, 39, 30),
            presmpt_prce=1_500_000_000,
        ),
        _announcement(
            "R26BK01800001",
            bid_ntce_ord="001",
            bid_ntce_dt=datetime(2026, 10, 24, 9, 44, 2),
            bid_ntce_nm="용역 정정 안내 공고",
            presmpt_prce=1_500_000_000,
        ),
        _announcement(
            "R26BK01800002",
            bid_ntce_dt=datetime(2026, 10, 23, 10, 0),
            presmpt_prce=900_000_000,
        ),
        _announcement(
            "R26BK01800002",
            bid_ntce_ord="001",
            bid_ntce_dt=datetime(2026, 10, 23, 11, 0),
            bid_ntce_nm="용역 재공고 안내",
            presmpt_prce=900_000_000,
        ),
        _announcement(
            "R26BK01800003",
            bid_ntce_dt=datetime(2026, 10, 22, 10, 0),
            presmpt_prce=700_000_000,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_list_is_filled_with_unique_bid_numbers(isolated_db, duplicated_rows):
    plan = build_retrieval_plan(LIST_QUERY)
    assert plan.filters.get("announcement_limit") == 5

    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]
    numbers = [sample["bid_ntce_no"] for sample in samples]

    assert len(samples) == 5
    assert len(set(numbers)) == 5
    assert numbers == [
        "R26BK01789549",
        "R26BK01787467",
        "R26BK01789392",
        "R26BK01789749",
        "R26BK01790123",
    ]


def test_duplicate_keeps_latest_row_and_keeps_sort_order(isolated_db, duplicated_rows):
    plan = build_retrieval_plan(LIST_QUERY)
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    duplicated = [sample for sample in samples if sample["bid_ntce_no"] == "R26BK01789549"]
    assert len(duplicated) == 1
    assert duplicated[0]["bid_ntce_nm"] == "용역 PQ 제출 안내 공고"
    assert duplicated[0]["bid_ntce_dt"] == "2026-10-24 09:44:02"

    dates = [sample["bid_ntce_dt"] for sample in samples]
    assert dates == sorted(dates, reverse=True)


def test_list_returns_available_rows_when_unique_count_is_short(isolated_db, three_unique_rows):
    plan = build_retrieval_plan(LIST_QUERY)
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    numbers = [sample["bid_ntce_no"] for sample in samples]
    assert len(numbers) == 3
    assert len(set(numbers)) == 3
    assert numbers == ["R26BK01800001", "R26BK01800002", "R26BK01800003"]
    assert samples[0]["bid_ntce_dt"] == "2026-10-24 09:44:02"


def test_list_without_duplicates_keeps_limit_and_order(isolated_db, duplicated_rows):
    plan = build_retrieval_plan("추정가격 5억 이상 용역 공고 3개 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert [sample["bid_ntce_no"] for sample in samples] == [
        "R26BK01789549",
        "R26BK01787467",
        "R26BK01789392",
    ]


@pytest.mark.parametrize(
    "query",
    [
        "용역 공고 중 추정가격이 가장 큰 건 얼마야?",
        "용역 공고 중 추정가격 최댓값 알려줘",
        "용역 공고 중 추정가격이 가장 높은 건 얼마야?",
        "기초금액 가장 작은 공사 공고",
    ],
)
def test_amount_extreme_questions_route_to_bid_query_tool(query):
    plan = plan_chat_request(query)
    tools = [step.tool for step in plan.steps]

    assert plan.intent_type == "statistics_query"
    assert tools == ["bid_query_tool", "respond"]
    assert "semantic_search_tool" not in tools
    assert plan.steps[0].params.get("query") == query


def test_amount_extreme_route_keeps_category_filter():
    plan = plan_chat_request("용역 공고 중 추정가격이 가장 큰 건 얼마야?")

    assert plan.steps[0].params.get("category") == "Servc"


@pytest.mark.parametrize(
    ("query", "expected_tools"),
    [
        ("낙찰 많이 한 업체 순위", ["bid_query_tool", "respond"]),
        ("추정가격이 뭐야", ["semantic_search_tool", "respond"]),
        ("최근 공사 공고 5개", ["bid_query_tool", "respond"]),
    ],
)
def test_questions_without_amount_extreme_keep_existing_tools(query, expected_tools):
    plan = plan_chat_request(query)

    assert [step.tool for step in plan.steps] == expected_tools
