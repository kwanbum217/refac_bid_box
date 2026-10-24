"""
tests/test_bid_number_lookup.py

공고번호 단건 질의의 판정, 유일 인덱스 조회, 같은 분류 평균 비교, 미발견 시
전체 통계 차단 계약을 검증합니다.

- "R26BK01778156" 같은 엄격형 공고번호만 단건으로 읽고, 11자리 숫자나 금액은
  공고번호로 읽지 않습니다.
- 단건 질의는 목록 제한 없이 SQL 로 가며 벡터 검색을 켜지 않습니다.
- 낙찰 결과가 있으면 그 행의 분류와 같은 기간 평균을 비교 기준으로 씁니다.
- 공고만 있으면 공고 정보를, 어느 쪽도 없으면 전체 통계 대신 없다는 답을 냅니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.planner_interpreter import interpret_request
from src.rag import structured_data
from src.rag.answer_format import _build_bid_detail_answer
from src.rag.engine import HybridRAGEngine
from src.rag.query_planning import (
    build_retrieval_plan,
    extract_bid_ntce_no,
    is_bid_number_query,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

_NOW = datetime(2026, 5, 10, 9, 0, 0)
_TARGET_NO = "R26BK01778156"
_OTHER_NO = "R26BK01775039"


def _seed_announcement(
    session,
    *,
    row_id: int,
    bid_ntce_no: str,
    institution: str = "충청남도 청양군",
    category: str = "Servc",
    ntce_dt: datetime = _NOW,
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="000",
            bid_ntce_nm=f"공고 {bid_ntce_no}",
            dminstt_nm=institution,
            presmpt_prce=38_909_091,
            bid_ntce_dt=ntce_dt,
            bid_clse_dt=ntce_dt,
            category=category,
            raw_data=None,
        )
    )


def _seed_result(
    session,
    *,
    row_id: int,
    bid_ntce_no: str,
    institution: str = "충청남도 청양군",
    winner: str = "지나지반기술(주)",
    rate: float | None = 88.0,
    category: str = "Servc",
    opened_at: datetime = _NOW,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="00",
            bid_ntce_nm=f"공고 {bid_ntce_no}",
            dminstt_nm=institution,
            bidwinnr_nm=winner,
            sucsf_bid_amt=37_751_000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


@pytest.mark.parametrize(
    "query",
    [
        "공고번호 R26BK01778156 낙찰 결과 알려줘",
        "R26BK01778156 낙찰률 높은 편이야?",
        "공고번호 R26BK01775039 알려줘",
        "R26BK01778156 낙찰업체 알려줘",
        "R26BK01778156 유찰이야?",
    ],
)
def test_bid_number_true_cases(query):
    """공고번호 참 사례는 단건 필터로 라우팅됩니다."""
    assert is_bid_number_query(query) is True
    assert extract_bid_ntce_no(query) in {_TARGET_NO, _OTHER_NO}
    assert build_retrieval_plan(query).filters.get("bid_ntce_no") == extract_bid_ntce_no(query)


@pytest.mark.parametrize(
    "query",
    [
        "공고번호가 뭐야?",
        "접수번호 12345678901 알려줘",
        "2026년 3분기 낙찰 결과 알려줘",
        "최근 낙찰 결과 5개 보여줘",
        "2026년 예산 123456789012원 알려줘",
    ],
)
def test_long_numeric_id_is_not_bid_number(query):
    """11자리 숫자·금액은 공고번호로 읽지 않습니다."""
    assert is_bid_number_query(query) is False
    assert extract_bid_ntce_no(query) == ""
    assert "bid_ntce_no" not in build_retrieval_plan(query).filters


def test_bid_number_explanation_is_not_lookup():
    """공고번호가 있어도 계산법을 묻는 설명형은 단건 조회가 아닙니다."""
    query = "R26BK01778156 낙찰률 계산 방법 알려줘"

    assert is_bid_number_query(query) is False
    assert "bid_ntce_no" not in build_retrieval_plan(query).filters


def test_lowercase_bid_number_is_normalized():
    """소문자 공고번호도 대문자로 정규화합니다."""
    assert extract_bid_ntce_no("r26bk01778156 낙찰 결과 알려줘") == _TARGET_NO
    assert (
        build_retrieval_plan("r26bk01778156 낙찰 결과 알려줘").filters.get("bid_ntce_no")
        == _TARGET_NO
    )


def test_bid_number_takes_precedence_over_result_list():
    """개수 표현이 붙어도 공고번호 단건이 목록보다 우선합니다."""
    query = "R26BK01778156 낙찰 결과 5개 보여줘"

    plan = build_retrieval_plan(query)

    assert is_bid_number_query(query) is True
    assert plan.filters.get("bid_ntce_no") == _TARGET_NO
    assert "result_limit" not in plan.filters
    assert "announcement_limit" not in plan.filters

    execution_plan = interpret_request(query)
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("bid_ntce_no") == _TARGET_NO


def test_bid_number_forces_sql_without_vector():
    """공고번호 단건은 정형 조회로만 갑니다."""
    for query in (
        "공고번호 R26BK01778156 낙찰 결과 알려줘",
        "R26BK01778156 낙찰률 높은 편이야?",
    ):
        plan = build_retrieval_plan(query)
        assert plan.use_sql is True, query
        assert plan.use_vector is False, query


def test_single_result_detail_uses_unique_index_condition(isolated_db):
    """단건 조회는 공고번호 등호 조건으로 그 행만 읽습니다."""
    _seed_result(isolated_db, row_id=1, bid_ntce_no=_TARGET_NO)
    _seed_result(isolated_db, row_id=2, bid_ntce_no=_OTHER_NO, rate=95.0)
    isolated_db.commit()

    plan = build_retrieval_plan("공고번호 R26BK01778156 낙찰 결과 알려줘")
    conditions = structured_data._result_conditions(plan, bid_ntce_no=_TARGET_NO)
    compiled = str(
        select(BidResult.id).where(*conditions).compile(compile_kwargs={"literal_binds": True})
    )
    assert "bid_ntce_no = 'R26BK01778156'" in compiled

    result = retrieve_structured_data(isolated_db, plan)
    detail = result["summary"]["bid_detail"]

    assert detail["result"]["bid_ntce_no"] == _TARGET_NO
    assert len(result["summary"]["recent_results"]) == 1
    assert result["summary"]["total_bids"] == 1


def test_single_lookup_condition_excludes_other_filters():
    """단건 조회 WHERE 는 기간·분류·기관 조건 없이 공고번호만 씁니다."""
    plan = build_retrieval_plan(f"{_TARGET_NO} 용역 부산 낙찰 결과 최근 5개 보여줘")
    assert plan.filters.get("category") == "Servc"
    assert plan.filters.get("date_from")

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

    assert "bid_ntce_no = 'R26BK01778156'" in result_sql
    assert "rl_openg_dt" not in result_sql
    assert "category" not in result_sql
    assert "dminstt_nm" not in result_sql
    assert "bid_ntce_no = 'R26BK01778156'" in announcement_sql
    assert "bid_ntce_dt" not in announcement_sql
    assert "category" not in announcement_sql
    assert "dminstt_nm" not in announcement_sql


@pytest.mark.parametrize(
    "query",
    [
        f"{_TARGET_NO} 낙찰 결과 최근",
        f"{_TARGET_NO} 낙찰 결과 알려줘 최근 5개 보여줘 부산",
        f"최근 {_TARGET_NO} 낙찰률 알려줘",
    ],
)
def test_relative_period_marker_does_not_hide_bid_number(isolated_db, query):
    """상대 기간 표지가 붙어도 개찰일이 창 밖인 그 공고를 찾아 답합니다."""
    opened_at = datetime.now() - timedelta(days=60)
    _seed_result(isolated_db, row_id=1, bid_ntce_no=_TARGET_NO, opened_at=opened_at)
    _seed_announcement(isolated_db, row_id=1, bid_ntce_no=_TARGET_NO, ntce_dt=opened_at)
    _seed_result(
        isolated_db,
        row_id=2,
        bid_ntce_no="R26BK01770002",
        rate=90.0,
        opened_at=datetime.now(),
    )
    isolated_db.commit()

    plan = build_retrieval_plan(query)
    assert plan.filters.get("bid_ntce_no") == _TARGET_NO
    assert plan.filters.get("date_from") or plan.filters.get("date_to")
    assert "result_limit" not in plan.filters

    result = retrieve_structured_data(isolated_db, plan)
    detail = result["summary"]["bid_detail"]

    assert detail["result"]["bid_ntce_no"] == _TARGET_NO
    assert detail["announcement"]["bid_ntce_no"] == _TARGET_NO

    answer = _build_bid_detail_answer(plan, result)
    assert "낙찰 결과입니다" in answer
    assert "지나지반기술(주)" in answer
    assert "용역 평균 낙찰률 90.0000%" in answer


def test_single_lookup_ignores_category_filter(isolated_db):
    """질의 분류와 행 분류가 달라도 공고번호가 유일 키이므로 그 행을 찾습니다."""
    _seed_result(
        isolated_db,
        row_id=1,
        bid_ntce_no=_TARGET_NO,
        category="Thng",
        opened_at=datetime.now() - timedelta(days=60),
    )
    isolated_db.commit()

    plan = build_retrieval_plan(f"{_TARGET_NO} 용역 낙찰 결과 최근")
    assert plan.filters.get("category") == "Servc"

    result = retrieve_structured_data(isolated_db, plan)

    assert result["summary"]["bid_detail"]["result"]["bid_ntce_no"] == _TARGET_NO


def test_relative_period_query_answers_without_llm(isolated_db):
    """엔진 사슬도 상대 기간 표지가 붙은 단건 질의를 LLM 없이 답합니다."""
    _seed_result(
        isolated_db,
        row_id=1,
        bid_ntce_no=_TARGET_NO,
        opened_at=datetime.now() - timedelta(days=60),
    )
    isolated_db.commit()

    class _RecordingBackend:
        name = "recording"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *args, **kwargs) -> str:
            self.calls += 1
            return "LLM 응답"

    engine = HybridRAGEngine()
    backend = _RecordingBackend()
    engine._backend_resolved = True
    engine._backend = backend

    bundle = engine.get_answer_sync(f"{_TARGET_NO} 낙찰 결과 최근", db=isolated_db)

    assert backend.calls == 0
    assert _TARGET_NO in bundle.answer
    assert "낙찰 결과입니다" in bundle.answer
    assert "지나지반기술(주)" in bundle.answer


def test_missing_bid_number_does_not_fall_back_to_global_stats(isolated_db):
    """없는 공고번호는 전체 통계로 넓히지 않고 없다고 답합니다."""
    for index in range(3):
        _seed_result(isolated_db, row_id=index + 1, bid_ntce_no=f"R26BK0177000{index}")
    isolated_db.commit()

    missing_no = "R26BK99999999"
    query = f"공고번호 {missing_no} 낙찰 결과 알려줘"
    plan = build_retrieval_plan(query)
    result = retrieve_structured_data(isolated_db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["total_bids"] is None
    assert result["summary"]["bid_detail"] is None
    assert any(missing_no in hint for hint in result["insufficiency_hints"])

    class _RecordingBackend:
        name = "recording"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *args, **kwargs) -> str:
            self.calls += 1
            return "LLM 응답"

    engine = HybridRAGEngine()
    backend = _RecordingBackend()
    engine._backend_resolved = True
    engine._backend = backend

    bundle = engine.get_answer_sync(query, db=isolated_db)

    assert backend.calls == 0
    assert missing_no in bundle.answer
    assert "확인할 수 없습니다" in bundle.answer
    assert "낙찰 3건" not in bundle.answer


def test_comparison_baseline_uses_item_category(isolated_db):
    """비교 기준선은 그 낙찰 행의 분류와 같은 기간 평균입니다."""
    _seed_result(isolated_db, row_id=1, bid_ntce_no=_TARGET_NO, rate=88.0)
    _seed_result(isolated_db, row_id=2, bid_ntce_no="R26BK01770002", rate=90.0)
    _seed_result(isolated_db, row_id=3, bid_ntce_no="R26BK01770003", rate=92.0)
    _seed_result(
        isolated_db,
        row_id=4,
        bid_ntce_no="R26BK01770004",
        rate=50.0,
        category="Thng",
    )
    _seed_result(
        isolated_db,
        row_id=5,
        bid_ntce_no="R26BK01770005",
        rate=40.0,
        category="Thng",
    )
    isolated_db.commit()

    plan = build_retrieval_plan("R26BK01778156 낙찰률 높은 편이야?")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    comparison = summary["bid_detail"]["comparison"]

    assert comparison["category"] == "Servc"
    assert comparison["category_label"] == "용역"
    assert comparison["average_winning_rate"] == 90.0
    assert comparison["sample_count"] == 3
    assert comparison["bid_count"] == 3


def test_announcement_only_bid_number_returns_announcement_detail(isolated_db):
    """낙찰 행이 없어도 공고 행이 있으면 공고 정보를 냅니다."""
    _seed_announcement(isolated_db, row_id=1, bid_ntce_no=_TARGET_NO)
    isolated_db.commit()

    plan = build_retrieval_plan("공고번호 R26BK01778156 알려줘")
    result = retrieve_structured_data(isolated_db, plan)
    summary = result["summary"]
    detail = summary["bid_detail"]

    assert detail["announcement"]["bid_ntce_no"] == _TARGET_NO
    assert detail["announcement"]["presmpt_prce"] == 38_909_091
    assert detail["result"] is None
    assert detail["comparison"] is None
    assert summary["announcement_count"] == 1
    assert summary["total_bids"] == 0
    assert "query_skipped" not in result

    answer = _build_bid_detail_answer(plan, result)
    assert "공고 정보입니다" in answer
    assert "낙찰 결과가 없습니다" in answer
    assert "38,909,091원" in answer


def test_bid_detail_answer_renders_comparison():
    """단건 응답은 낙찰 필드와 같은 분류 평균 대비 문장을 함께 냅니다."""
    plan = RetrievalPlan(filters={"bid_ntce_no": _TARGET_NO})
    structured = {
        "summary": {
            "bid_detail": {
                "bid_ntce_no": _TARGET_NO,
                "announcement": None,
                "result": {
                    "bid_ntce_no": _TARGET_NO,
                    "bid_ntce_nm": "청양군 지반조사 용역",
                    "dminstt_nm": "충청남도 청양군",
                    "bidwinnr_nm": "지나지반기술(주)",
                    "sucsf_bid_amt": 37_751_000,
                    "sucsf_bid_rate": 88.3446,
                    "rl_openg_dt": "2026-10-23 18:18:36",
                    "category": "Servc",
                    "category_label": "용역",
                },
                "comparison": {
                    "category": "Servc",
                    "category_label": "용역",
                    "average_winning_rate": 90.0146,
                    "sample_count": 1234,
                    "bid_count": 1234,
                    "date_from": None,
                    "date_to": None,
                },
            }
        }
    }

    answer = _build_bid_detail_answer(plan, structured)

    assert f"공고번호 {_TARGET_NO} 낙찰 결과입니다." in answer
    assert "| 낙찰업체 | 지나지반기술(주) |" in answer
    assert "| 낙찰률 | 88.3446% |" in answer
    assert "용역 평균 낙찰률 90.0146% 보다 1.67%p 낮습니다." in answer
    assert "표본 1,234건" in answer
