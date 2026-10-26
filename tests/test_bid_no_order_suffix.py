"""
tests/test_bid_no_order_suffix.py

차수 접미사가 붙은 공고번호를 공고번호와 차수(bid_ntce_ord)로 읽어 단건 조회하는
계약을 검증합니다.

- "R26BK01788962-001" 은 공고번호 R26BK01788962 의 001 회차 단건 조회입니다.
- 접미사가 없으면 기존처럼 공고번호만으로 단건 조회합니다.
- 소문자는 대문자로 정규화하고, 두 자리 접미사·접수번호는 공고번호로 읽지 않습니다.
- 계산 방법을 묻는 설명형은 기존 설명 경로를 유지합니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.query_planning import (
    build_retrieval_plan,
    extract_bid_ntce_no,
    extract_bid_ntce_ord,
    is_bid_number_query,
)
from src.rag.structured_data import retrieve_structured_data

_NOW = datetime(2026, 10, 20, 9, 0, 0)
_TARGET_NO = "R26BK01788962"


def _seed_announcements(session) -> None:
    for row_id, ord_value, title in (
        (1, "000", "원공고"),
        (2, "001", "재공고"),
    ):
        session.add(
            BidAnnouncement(
                id=row_id,
                bid_ntce_no=_TARGET_NO,
                bid_ntce_ord=ord_value,
                bid_ntce_nm=f"{title} {_TARGET_NO}",
                dminstt_nm="조달청",
                presmpt_prce=100_000_000,
                bid_ntce_dt=_NOW,
                bid_clse_dt=_NOW,
                category="Servc",
                raw_data=None,
            )
        )


def _seed_results(session) -> None:
    # 낙찰 결과 테이블에는 과거 2자리 차수로 적재된 행도 있습니다.
    for row_id, ord_value, winner, rate in (
        (1, "00", "가나기술(주)", 80.0),
        (2, "01", "다라기술(주)", 90.0),
    ):
        session.add(
            BidResult(
                id=row_id,
                bid_ntce_no=_TARGET_NO,
                bid_ntce_ord=ord_value,
                bid_ntce_nm=f"공고 {_TARGET_NO}",
                dminstt_nm="조달청",
                bidwinnr_nm=winner,
                sucsf_bid_amt=90_000_000,
                sucsf_bid_rate=rate,
                rl_openg_dt=_NOW,
                category="Servc",
            )
        )


def test_suffix_is_read_as_bid_number_and_ord():
    """차수 접미사는 공고번호와 차수로 갈라 읽습니다."""
    query = "R26BK01788962-001 분석해줘"

    assert is_bid_number_query(query) is True
    assert extract_bid_ntce_no(query) == _TARGET_NO
    assert extract_bid_ntce_ord(query) == "001"

    plan = build_retrieval_plan(query)
    assert plan.filters.get("bid_ntce_no") == _TARGET_NO
    assert plan.filters.get("bid_ntce_ord") == "001"
    assert plan.use_sql is True
    assert "result_limit" not in plan.filters
    assert "announcement_limit" not in plan.filters


def test_lowercase_suffix_is_normalized():
    """소문자 공고번호도 대문자로 정규화하고 차수를 유지합니다."""
    plan = build_retrieval_plan("r26bk01788962-001 분석해줘")

    assert plan.filters.get("bid_ntce_no") == _TARGET_NO
    assert plan.filters.get("bid_ntce_ord") == "001"


def test_suffix_adds_ord_condition_to_single_lookup():
    """단건 조회 WHERE 는 공고번호와 차수를 함께 씁니다."""
    plan = build_retrieval_plan("R26BK01788962-001 분석해줘")

    result_sql = str(
        select(BidResult.id)
        .where(*structured_data._result_conditions(plan, bid_ntce_no=_TARGET_NO))
        .compile(compile_kwargs={"literal_binds": True})
    )
    announcement_sql = str(
        select(BidAnnouncement.id)
        .where(*structured_data._announcement_conditions(plan, bid_ntce_no=_TARGET_NO))
        .compile(compile_kwargs={"literal_binds": True})
    )

    assert "bid_ntce_no = 'R26BK01788962'" in result_sql
    assert "bid_ntce_ord IN ('001', '01')" in result_sql
    assert "bid_ntce_no = 'R26BK01788962'" in announcement_sql
    assert "bid_ntce_ord IN ('001', '01')" in announcement_sql
    assert "rl_openg_dt" not in result_sql
    assert "bid_ntce_dt" not in announcement_sql


def test_suffix_returns_only_requested_ord(isolated_db):
    """같은 공고번호에 여러 차수가 있어도 요청한 차수 행만 읽습니다."""
    _seed_announcements(isolated_db)
    _seed_results(isolated_db)
    isolated_db.commit()

    plan = build_retrieval_plan("R26BK01788962-001 분석해줘")
    result = retrieve_structured_data(isolated_db, plan)
    detail = result["summary"]["bid_detail"]

    assert detail["announcement"]["bid_ntce_no"] == _TARGET_NO
    assert detail["announcement"]["bid_ntce_nm"] == f"재공고 {_TARGET_NO}"
    assert detail["result"]["bid_ntce_no"] == _TARGET_NO
    assert detail["result"]["bid_ntce_ord"] == "01"
    assert detail["result"]["bidwinnr_nm"] == "다라기술(주)"
    assert len(result["summary"]["recent_results"]) == 1


def test_suffix_rate_question_is_single_lookup(isolated_db):
    """낙찰률 판단 질의도 차수 붙은 공고번호를 단건으로 읽습니다."""
    _seed_announcements(isolated_db)
    _seed_results(isolated_db)
    isolated_db.commit()

    plan = build_retrieval_plan("공고번호 R26BK01788962-001 의 낙찰률은 높은 편이야")
    result = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("bid_ntce_ord") == "001"
    assert result["summary"]["bid_detail"]["result"]["bidwinnr_nm"] == "다라기술(주)"


def test_without_suffix_keeps_bid_number_only_lookup(isolated_db):
    """접미사가 없는 공고번호 질의의 동작은 그대로입니다."""
    _seed_announcements(isolated_db)
    _seed_results(isolated_db)
    isolated_db.commit()

    plan = build_retrieval_plan("R26BK01788962 공고 알려줘")

    assert plan.filters.get("bid_ntce_no") == _TARGET_NO
    assert "bid_ntce_ord" not in plan.filters

    result = retrieve_structured_data(isolated_db, plan)
    detail = result["summary"]["bid_detail"]

    assert detail["announcement"]["bid_ntce_no"] == _TARGET_NO
    assert detail["result"]["bid_ntce_no"] == _TARGET_NO
    assert len(result["summary"]["recent_results"]) == 1


def test_suffix_without_matching_ord_does_not_widen(isolated_db):
    """없는 차수를 지목하면 다른 차수나 전체 통계로 넓히지 않습니다."""
    _seed_announcements(isolated_db)
    _seed_results(isolated_db)
    isolated_db.commit()

    plan = build_retrieval_plan("R26BK01788962-003 알려줘")
    result = retrieve_structured_data(isolated_db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["bid_detail"] is None


@pytest.mark.parametrize(
    "query",
    [
        "R26BK01788962-01 분석해줘",
        "R26BK01788962-0011 분석해줘",
        "12345678901-001 알려줘",
    ],
)
def test_non_three_digit_suffix_is_not_bid_number(query):
    """두 자리·네 자리 접미사와 접수번호는 공고번호로 읽지 않습니다."""
    assert is_bid_number_query(query) is False
    assert extract_bid_ntce_no(query) == ""
    assert extract_bid_ntce_ord(query) == ""

    plan = build_retrieval_plan(query)
    assert "bid_ntce_no" not in plan.filters
    assert "bid_ntce_ord" not in plan.filters


def test_suffix_explanation_stays_on_explanation_path():
    """차수가 붙어도 계산 방법을 묻는 설명형은 단건 조회가 아닙니다."""
    query = "R26BK01788962-001 계산 방법 알려줘"

    assert is_bid_number_query(query) is False
    assert "bid_ntce_no" not in build_retrieval_plan(query).filters
