"""적격심사 조건 공고 목록·건수 조회를 계획·SQL·응답 계층에서 고정합니다.

적격심사는 제도 정의·차이 질문에도 나오므로 조회 조건 승격은 목록·건수·통계
의도가 있을 때만 일어나야 합니다. SQL 은 공고 원문 raw_data 의
sucsfbidMthdNm 이 "적격심사" 로 시작하는 행만 고르고, 그 조건을 응답의
조건 줄에 표기합니다. 낙찰 결과 쪽은 이번 범위가 아니므로 조건을 버린 사실을
안내 문장으로 남깁니다.
"""

from datetime import date, datetime

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import query_planning
from src.rag.answer_format import (
    EARLY_AWARD_METHOD_NOTE,
    RESULT_AWARD_METHOD_NOTICE,
    _announcement_condition_line,
    _build_announcement_list_answer,
    _build_result_list_answer,
    _build_single_metric_answer,
)
from src.rag.query_planning import _single_metric, build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

TARGET = "현재 최근 입찰 공고중에 용역 분야 적격심사 반영되는 공고 5건만 알려줘"
DEFINITION_QUERIES = (
    "적격심사가 뭐야",
    "적격심사 기준 설명해줘",
    "적격심사와 최저가낙찰제의 차이가 무엇인가요",
)
_FROZEN_TODAY = date(2026, 10, 31)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _seed_announcement(
    session,
    row_id: int,
    method: str | None,
    ntce_dt: datetime,
    *,
    category: str = "Servc",
    name: str = "용역 공고",
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ELIG-{row_id:03d}",
            bid_ntce_ord="000",
            category=category,
            bid_ntce_nm=f"{name} {row_id}",
            dminstt_nm="수요기관",
            presmpt_prce=1000000,
            bid_ntce_dt=ntce_dt,
            raw_data={"sucsfbidMthdNm": method} if method is not None else None,
        )
    )


# ===========================================================================
# 계획
# ===========================================================================


def test_target_utterance_plan_carries_award_method(frozen_today):
    """보고서 5번 발화는 적격심사 조건과 목록 제한을 함께 실어 SQL 로 갑니다."""
    plan = build_retrieval_plan(TARGET)

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.route_reason == "공고 목록 질의"
    assert plan.filters == {
        "date_from": "2026-10-25",
        "date_to": "2026-10-31",
        "award_method": "적격심사",
        "category": "Servc",
        "announcement_limit": 5,
    }
    assert "institution_name" not in plan.filters
    assert "institution_names" not in plan.filters


@pytest.mark.parametrize("query", DEFINITION_QUERIES)
def test_definition_questions_keep_existing_route(query):
    """정의·차이 질문에는 낙찰방법 조건이 붙지 않고 기본 벡터 경로가 유지됩니다."""
    plan = build_retrieval_plan(query)

    assert "award_method" not in plan.filters
    assert plan.use_sql is False
    assert plan.use_vector is True
    assert plan.route_reason == "기본 벡터 질의"
    assert "institution_name" not in plan.filters


def test_eligibility_count_plan_uses_sql_without_institution_filter():
    """건수 질문은 적격심사 조건을 싣고 기관명으로 오추출하지 않습니다."""
    plan = build_retrieval_plan("적격심사 공고 몇 건이야")

    assert plan.use_sql is True
    assert plan.filters.get("award_method") == "적격심사"
    assert "institution_name" not in plan.filters
    assert "institution_names" not in plan.filters


def test_result_list_query_carries_award_method_for_notice():
    """낙찰 결과 질의도 조건 표지를 남겨 응답이 미지원 사실을 밝히게 합니다."""
    plan = build_retrieval_plan("적격심사 낙찰 결과 5건 보여줘")

    assert plan.use_sql is True
    assert plan.filters.get("award_method") == "적격심사"
    assert plan.filters.get("result_limit") == 5


# ===========================================================================
# SQL
# ===========================================================================


def test_structured_data_selects_only_eligibility_announcements(isolated_db):
    """raw_data.sucsfbidMthdNm 이 적격심사로 시작하는 공고만 고릅니다."""
    _seed_announcement(
        isolated_db, 1, "적격심사제-관리규정외 수기심사", datetime(2026, 10, 30, 9, 0)
    )
    _seed_announcement(isolated_db, 2, "적격심사 추정가격 5억원 미만", datetime(2026, 10, 29, 9, 0))
    _seed_announcement(isolated_db, 3, "소액수의견적", datetime(2026, 10, 31, 9, 0))
    _seed_announcement(isolated_db, 4, "협상에의한계약(SW사업)", datetime(2026, 10, 28, 9, 0))
    _seed_announcement(isolated_db, 5, None, datetime(2026, 10, 27, 9, 0))
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "announcement_limit": 5,
            "award_method": "적격심사",
        },
    )
    result = retrieve_structured_data(isolated_db, plan)

    assert result["summary"]["announcement_count"] == 2
    assert [sample["bid_ntce_no"] for sample in result["summary"]["sample_announcements"]] == [
        "ELIG-001",
        "ELIG-002",
    ]


def test_structured_data_count_uses_eligibility_condition(isolated_db):
    """공고 건수 집계도 같은 낙찰방법 조건을 씁니다."""
    _seed_announcement(isolated_db, 1, "적격심사제-수기심사", datetime(2026, 10, 30, 9, 0))
    _seed_announcement(isolated_db, 2, "소액수의견적", datetime(2026, 10, 31, 9, 0))
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"award_method": "적격심사"})
    result = retrieve_structured_data(isolated_db, plan)

    assert result["summary"]["announcement_count"] == 1


def test_result_conditions_ignore_award_method(isolated_db):
    """낙찰 결과 테이블은 이번 범위가 아니므로 조건을 걸지 않습니다."""
    for row_id in (1, 2):
        isolated_db.add(
            BidResult(
                id=row_id,
                bid_ntce_no=f"RES-{row_id:03d}",
                bid_ntce_ord="00",
                bid_ntce_nm=f"낙찰 공고 {row_id}",
                dminstt_nm="수요기관",
                bidwinnr_nm=f"업체{row_id}",
                sucsf_bid_amt=1000,
                sucsf_bid_rate=90.0,
                rl_openg_dt=datetime(2026, 10, 20 + row_id, 9, 0),
                category="Servc",
            )
        )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={"category": "Servc", "result_limit": 2, "award_method": "적격심사"},
    )
    result = retrieve_structured_data(isolated_db, plan)

    assert result["summary"]["total_bids"] == 2
    assert len(result["summary"]["recent_results"]) == 2


# ===========================================================================
# 응답
# ===========================================================================


def _sample(index: int) -> dict:
    return {
        "bid_ntce_no": f"ELIG-{index:03d}",
        "bid_ntce_nm": f"적격심사 용역 공고 {index}",
        "dminstt_nm": "수요기관",
        "presmpt_prce": 1000000 * index,
        "bid_ntce_dt": f"2026-10-{index:02d} 09:00:00",
        "bid_clse_dt": f"2026-10-{index + 1:02d} 18:00:00",
    }


def test_condition_line_states_award_method():
    assert _announcement_condition_line({"award_method": "적격심사"}) == (
        "적용 조건: 낙찰방법: 적격심사"
    )


def test_announcement_list_answer_shows_award_method_condition():
    """목록 응답은 머리 문장과 조건 줄에 적격심사 조건을 표시합니다."""
    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "announcement_limit": 1,
            "award_method": "적격심사",
            "date_from": "2026-10-25",
            "date_to": "2026-10-31",
        },
    )
    structured_data = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {"sample_announcements": [_sample(1)]},
    }

    answer = _build_announcement_list_answer(plan, structured_data)

    assert answer.splitlines()[0] == "조건에 맞는 용역 공고 1건입니다."
    assert "적용 조건: 낙찰방법: 적격심사" in answer
    assert EARLY_AWARD_METHOD_NOTE not in answer


def test_announcement_list_answer_notes_pre_2024_window():
    """2024년 이전 창을 포함하면 부분 집계 가능성을 한 문장으로 밝힙니다."""
    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "announcement_limit": 1,
            "award_method": "적격심사",
            "date_from": "2023-01-01",
            "date_to": "2026-10-31",
        },
    )
    structured_data = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {"sample_announcements": [_sample(1)]},
    }

    answer = _build_announcement_list_answer(plan, structured_data)

    assert EARLY_AWARD_METHOD_NOTE in answer


def test_announcement_count_answer_states_award_method():
    """건수 응답도 문장 안에 적격심사 조건을 밝힙니다."""
    plan = RetrievalPlan(
        use_sql=True,
        semantic_query="적격심사 공고 몇 건이야",
        filters={"award_method": "적격심사"},
    )
    assert _single_metric(plan.semantic_query.lower()) == "announcement_count"

    answer = _build_single_metric_answer(
        plan,
        {"filters": {}, "summary": {"announcement_count": 379}, "insufficiency_hints": []},
    )

    assert answer.splitlines()[0] == "전체 기간 적격심사 공고는 379건입니다."
    # 기간이 없으면 전체 기간이므로 2024년 이전 창을 포함합니다.
    assert EARLY_AWARD_METHOD_NOTE in answer


def test_result_list_answer_reports_unsupported_award_method(frozen_today):
    """낙찰 결과 응답은 낙찰방법 조건을 적용하지 못했음을 밝힙니다."""
    plan = build_retrieval_plan("적격심사 낙찰 결과 5건 보여줘")
    structured_data = {
        "filters": {},
        "summary": {"recent_results": [], "latest_available_result_at": None},
    }

    answer = _build_result_list_answer(plan, structured_data)

    assert RESULT_AWARD_METHOD_NOTICE in answer
