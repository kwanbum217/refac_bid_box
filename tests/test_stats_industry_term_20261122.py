"""
tests/test_stats_industry_term_20261122.py

통계 질문의 업종어(청소·경비 등)가 계획·응답·스냅숏에 담기고, 집계 조건 연결
전에는 미적용 안내가 나가는지 검증합니다.

배경: "인천 청소 용역 낙찰률 알려줘" 가 "최근 5년 인천 용역 평균 낙찰률" 로
답해 업종어가 사라졌습니다(.orca/stats_industry_report_20261122.md). 1단계는
계획 필터와 조건 함수, 응답·스냅숏 표기, 미적용 안내까지이고
src/rag/structured_data.py 연결은 2단계입니다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from src.rag.answer_format import _build_single_metric_answer
from src.rag.industry_terms import title_keyword_condition
from src.rag.query_planning import (
    build_retrieval_plan,
    collect_unapplied_industry_conditions,
    collect_unapplied_result_conditions,
    unapplied_result_condition_notice,
)
from src.rag.snapshots import _extract_statistical_snapshot

INDUSTRY_QUESTIONS = (
    ("인천 청소 용역 낙찰률 알려줘", "청소", ["청소", "미화", "환경미화"]),
    ("미화 용역 낙찰률 알려줘", "청소", ["청소", "미화", "환경미화"]),
    ("환경미화 용역 공고 건수 알려줘", "청소", ["청소", "미화", "환경미화"]),
    ("경비 용역 낙찰률 알려줘", "경비", ["경비", "보안경비"]),
    ("보안경비 용역 낙찰률 알려줘", "경비", ["경비", "보안경비"]),
    ("시설관리 용역 낙찰률 알려줘", "시설관리", ["시설관리"]),
    ("파견 용역 낙찰률 알려줘", "파견", ["파견"]),
    ("직업소개 용역 낙찰률 알려줘", "직업소개", ["직업소개"]),
    ("위생관리 용역 낙찰률 알려줘", "위생", ["위생", "위생관리"]),
)


@pytest.mark.parametrize(("question", "label", "title_keywords"), INDUSTRY_QUESTIONS)
def test_industry_term_becomes_plan_filters(question, label, title_keywords):
    """업종어마다 라벨과 공고명 키워드가 계획 필터에 담깁니다."""
    plan = build_retrieval_plan(question)

    assert plan.filters.get("industry_label") == label
    assert plan.filters.get("title_keywords") == title_keywords


def test_question_without_industry_term_keeps_filters():
    """업종어가 없는 질문은 필터가 그대로여서 용역 전체 모집단이 유지됩니다."""
    plan = build_retrieval_plan("인천 용역 낙찰률 알려줘")

    assert plan.filters == {"category": "Servc", "institution_name": "인천"}


@pytest.mark.parametrize(
    "question",
    [
        "청소차 구매 공고 보여줘",
        "청소기 구매 공고 보여줘",
        "경비실 보수 공사 공고 보여줘",
        "시설관리공단 용역 낙찰률 알려줘",
        "인천공항시설관리 공고 보여줘",
    ],
)
def test_industry_noise_terms_are_not_recognized(question):
    """물품명·시설명·기관명 일부는 업종 지목이 아니므로 인식하지 않습니다."""
    plan = build_retrieval_plan(question)

    assert "industry_label" not in plan.filters
    assert "title_keywords" not in plan.filters


def _title_table():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "titles",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("bid_ntce_nm", String(200), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(table),
            [
                {"id": 1, "bid_ntce_nm": "2026년 청사 청소 용역"},
                {"id": 2, "bid_ntce_nm": "환경미화 용역"},
                {"id": 3, "bid_ntce_nm": "청소차 구매"},
                {"id": 4, "bid_ntce_nm": "청소기 구매"},
                {"id": 5, "bid_ntce_nm": "경비 용역"},
                {"id": 6, "bid_ntce_nm": "급식 물품 구매"},
            ],
        )
    return engine, table


def test_title_keyword_condition_keeps_only_keyword_rows():
    """키워드 OR 조건은 업종 행만 남기고 잡음 낱말(청소차·청소기)은 걷어냅니다."""
    engine, table = _title_table()
    filters = {"industry_label": "청소", "title_keywords": ["청소", "미화", "환경미화"]}

    condition = title_keyword_condition(table.c.bid_ntce_nm, filters)
    with engine.connect() as connection:
        names = [
            row.bid_ntce_nm
            for row in connection.execute(select(table.c.bid_ntce_nm).where(condition))
        ]

    assert sorted(names) == ["2026년 청사 청소 용역", "환경미화 용역"]


def test_title_keyword_condition_returns_none_without_keywords():
    """업종어 없는 질의에는 조건을 만들지 않아 호출한 쪽이 범위를 좁히지 않습니다."""
    _, table = _title_table()

    assert title_keyword_condition(table.c.bid_ntce_nm, {}) is None
    assert title_keyword_condition(table.c.bid_ntce_nm, {"industry_label": "청소"}) is None


def test_title_keyword_condition_escapes_like_wildcards():
    """질문에서 온 낱말이 LIKE 와일드카드로 동작해 범위를 넓히지 못합니다."""
    engine, table = _title_table()

    condition = title_keyword_condition(
        table.c.bid_ntce_nm, {"industry_label": "청소", "title_keywords": ["%"]}
    )
    with engine.connect() as connection:
        names = list(connection.execute(select(table.c.bid_ntce_nm).where(condition)).scalars())

    assert names == []


def _industry_structured_data() -> dict:
    return {
        "filters": {
            "relative_years": 5,
            "category": "Servc",
            "category_label": "용역",
            "institution_name": "인천",
        },
        "summary": {
            "total_bids": 18050,
            "announcement_count": 31878,
            "average_winning_rate": 89.5017,
            "total_winning_amount": 0.0,
            "top_winners": [],
            "top_institutions": [],
            "top_announcements": [],
            "sample_announcements": [],
            "recent_results": [],
            "latest_available_result_at": None,
            "time_series": [],
        },
        "insufficiency_hints": [],
    }


def test_single_metric_answer_states_industry_and_unapplied_notice():
    """평균 낙찰률 문장에 업종이 남고, 조건 미적용을 같은 답변에서 밝힙니다."""
    plan = build_retrieval_plan("인천 청소 용역 낙찰률 알려줘")

    answer = _build_single_metric_answer(plan, _industry_structured_data())

    head, notice = answer.split("\n")
    assert head == "최근 5년 인천 청소 용역 평균 낙찰률은 89.50%입니다."
    assert notice == (
        "업종 조건(청소)은 적용하지 못해 인천 용역 전체로 조회했습니다. "
        "수치는 해당 업종으로 좁히지 않은 값입니다."
    )


def test_single_metric_answer_without_industry_term_is_unchanged():
    """업종어 없는 질문의 답변 문장과 안내에는 업종 흔적이 없습니다."""
    plan = build_retrieval_plan("인천 용역 낙찰률 알려줘")

    answer = _build_single_metric_answer(plan, _industry_structured_data())

    assert answer == "최근 5년 인천 용역 평균 낙찰률은 89.50%입니다."


def test_statistical_snapshot_marks_unapplied_industry():
    """스냅숏 적용 조건 줄은 업종과 미적용 여부를 함께 적습니다."""
    snapshot = _extract_statistical_snapshot(
        {
            "filters": {
                "relative_years": 5,
                "category": "Servc",
                "category_label": "용역",
                "institution_name": "인천",
                "industry_label": "청소",
            },
            "summary": _industry_structured_data()["summary"],
            "insufficiency_hints": [],
        }
    )

    assert "- 적용 조건: 기간 최근 5년, 분류 용역, 지역 인천, 업종 청소(미적용)" in snapshot


def test_statistical_snapshot_marks_applied_industry_without_suffix():
    """2단계에서 조건이 연결되면 같은 줄이 미적용 표시 없이 업종만 적습니다."""
    snapshot = _extract_statistical_snapshot(
        {
            "filters": {
                "category": "Servc",
                "category_label": "용역",
                "industry_label": "청소",
                "industry_applied": True,
            },
            "summary": _industry_structured_data()["summary"],
            "insufficiency_hints": [],
        }
    )

    assert "업종 청소" in snapshot
    assert "청소(미적용)" not in snapshot


def test_unapplied_industry_condition_is_collected_with_scope():
    """미적용 업종 조건은 모집단 이름과 함께 모여 안내 문장이 됩니다."""
    filters = {
        "category": "Servc",
        "institution_name": "인천",
        "industry_label": "청소",
        "title_keywords": ["청소", "미화", "환경미화"],
    }

    conditions = collect_unapplied_result_conditions(filters)

    assert conditions == [
        {
            "kind": "industry",
            "field": "industry_label",
            "label": "청소",
            "scope": "인천 용역",
        }
    ]
    assert "업종 조건(청소)은 적용하지 못해 인천 용역 전체로 조회했습니다." in (
        unapplied_result_condition_notice(conditions)
    )


def test_applied_industry_condition_has_no_notice():
    """집계가 조건을 붙였다고 표시하면 미적용 항목을 만들지 않습니다."""
    filters = {
        "category": "Servc",
        "institution_name": "인천",
        "industry_label": "청소",
        "title_keywords": ["청소", "미화", "환경미화"],
        "industry_applied": True,
    }

    assert collect_unapplied_industry_conditions(filters) == []
    assert collect_unapplied_result_conditions(filters) == []
    assert unapplied_result_condition_notice(collect_unapplied_result_conditions(filters)) == ""


def test_unapplied_notice_without_region_uses_whole_scope():
    """지역·기관이 없으면 용역 전체 기준임을 밝힙니다."""
    filters = {"industry_label": "경비", "title_keywords": ["경비", "보안경비"]}

    notice = unapplied_result_condition_notice(collect_unapplied_industry_conditions(filters))

    assert notice.startswith("업종 조건(경비)은 적용하지 못해 용역 전체로 조회했습니다.")
