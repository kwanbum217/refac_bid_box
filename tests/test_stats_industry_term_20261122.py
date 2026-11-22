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

from datetime import datetime

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, func, insert, select
from sqlalchemy.dialects import mysql

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data as sd
from src.rag.answer_format import (
    _build_announcement_list_answer,
    _build_comparison_answer,
    _build_result_list_answer,
    _build_single_metric_answer,
)
from src.rag.industry_terms import title_keyword_condition
from src.rag.query_planning import (
    build_retrieval_plan,
    collect_unapplied_industry_conditions,
    collect_unapplied_result_conditions,
    industry_applied_filters,
    unapplied_result_condition_notice,
)
from src.rag.schemas import RetrievalPlan
from src.rag.snapshots import _extract_statistical_snapshot

MYSQL_DIALECT = mysql.dialect()


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 조회 캐시를 시험마다 비워 집계 결과가 섞이지 않게 합니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


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

    for wildcard in ("%", "_"):
        condition = title_keyword_condition(
            table.c.bid_ntce_nm, {"industry_label": "청소", "title_keywords": [wildcard]}
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


def test_single_metric_answer_drops_notice_when_industry_applied():
    """집계가 조건을 붙였다고 표시하면 2단계 응답에 미적용 안내가 남지 않습니다."""
    plan = build_retrieval_plan("인천 청소 용역 낙찰률 알려줘")
    applied_plan = plan.model_copy(
        update={"filters": {**(plan.filters or {}), "industry_applied": True}}
    )
    structured_data = _industry_structured_data()
    structured_data["filters"].update(
        {
            "industry_label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "industry_applied": True,
        }
    )

    answer = _build_single_metric_answer(applied_plan, structured_data)

    assert answer == "최근 5년 인천 청소 용역 평균 낙찰률은 89.50%입니다."
    assert "적용하지 못해" not in answer


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


# 2단계 시험용 표본입니다. 업종(청소) 행과 다른 업종(경비)·잡음(청소차)·무관
# 행을 섞어, 조건이 붙었을 때 업종 행만 세는지 확인합니다.
INDUSTRY_ANNOUNCEMENTS = (
    (1, "2025년 청사 청소 용역", datetime(2025, 5, 1, 9, 0, 0)),
    (2, "2025년 경비 용역", datetime(2025, 5, 2, 9, 0, 0)),
    (3, "2025년 환경미화 용역", datetime(2025, 5, 3, 9, 0, 0)),
    (4, "2025년 청소차 구매", datetime(2025, 5, 4, 9, 0, 0)),
    (5, "2026년 청사 청소 용역", datetime(2026, 3, 1, 9, 0, 0)),
    (6, "2026년 급식 물품 구매", datetime(2026, 3, 2, 9, 0, 0)),
    (7, "2026년 미화 용역", datetime(2026, 3, 3, 9, 0, 0)),
)
INDUSTRY_RESULTS = (
    (1, "청소업체A", 80_000_000, 88.0, datetime(2025, 5, 10, 9, 0, 0)),
    (2, "청소업체B", 70_000_000, 70.0, datetime(2025, 5, 11, 9, 0, 0)),
    (3, "청소업체C", 60_000_000, 90.0, datetime(2025, 5, 12, 9, 0, 0)),
    (4, "청소업체D", 50_000_000, 60.0, datetime(2025, 5, 13, 9, 0, 0)),
    (5, "청소업체E", 40_000_000, 92.0, datetime(2026, 3, 10, 9, 0, 0)),
    (6, "청소업체F", 30_000_000, 65.0, datetime(2026, 3, 11, 9, 0, 0)),
    (7, "청소업체G", 20_000_000, 94.0, datetime(2026, 3, 12, 9, 0, 0)),
)


def _seed_industry_rows(session) -> None:
    for row_id, name, noticed_at in INDUSTRY_ANNOUNCEMENTS:
        session.add(
            BidAnnouncement(
                id=row_id,
                bid_ntce_no=f"IND-ANN-{row_id:03d}",
                bid_ntce_ord="000",
                bid_ntce_nm=name,
                dminstt_nm="인천광역시",
                bid_ntce_dt=noticed_at,
                category="Servc",
                raw_data=None,
            )
        )
    for row_id, winner, amount, rate, opened_at in INDUSTRY_RESULTS:
        session.add(
            BidResult(
                id=row_id,
                bid_ntce_no=f"IND-RES-{row_id:03d}",
                bid_ntce_ord="00",
                bid_ntce_nm=INDUSTRY_ANNOUNCEMENTS[row_id - 1][1],
                dminstt_nm="인천광역시",
                bidwinnr_nm=winner,
                sucsf_bid_amt=amount,
                sucsf_bid_rate=rate,
                rl_openg_dt=opened_at,
                category="Servc",
            )
        )
    session.commit()


def _industry_plan() -> RetrievalPlan:
    return build_retrieval_plan("인천 청소 용역 낙찰률 알려줘")


def test_industry_term_narrows_aggregate_to_keyword_rows(isolated_db):
    """업종어 질문의 공고·낙찰 집계가 청소 공고 행만 셉니다."""
    _seed_industry_rows(isolated_db)

    result = sd.retrieve_structured_data(isolated_db, _industry_plan())

    # 청소(1·5)·환경미화(3)·미화(7) 4건만 남고 경비·급식·청소차는 빠집니다.
    assert result["filters"]["industry_applied"] is True
    assert result["summary"]["announcement_count"] == 4
    assert result["summary"]["total_bids"] == 4
    assert result["summary"]["average_winning_rate"] == 91.0
    assert result["unapplied_conditions"] == []


def test_industry_term_list_query_has_no_unapplied_notice(isolated_db):
    """낙찰 목록 질의도 업종 조건을 붙였으므로 미적용 안내를 만들지 않습니다."""
    _seed_industry_rows(isolated_db)
    plan = build_retrieval_plan("인천 청소 용역 낙찰 결과 보여줘")
    plan = plan.model_copy(update={"filters": {**plan.filters, "result_limit": 10}})

    result = sd.retrieve_structured_data(isolated_db, plan)

    assert result["filters"]["industry_applied"] is True
    assert result["unapplied_conditions"] == []
    assert [row["bid_ntce_nm"] for row in result["summary"]["recent_results"]] == [
        "2026년 미화 용역",
        "2026년 청사 청소 용역",
        "2025년 환경미화 용역",
        "2025년 청사 청소 용역",
    ]


def test_industry_term_answer_states_scope_without_notice(isolated_db):
    """적용된 조회의 문장은 업종 라벨과 거른 수치를 쓰고 미적용 안내가 없습니다."""
    _seed_industry_rows(isolated_db)
    plan = _industry_plan()

    structured = sd.retrieve_structured_data(isolated_db, plan)
    answer = _build_single_metric_answer(plan, structured)

    assert answer == "전체 기간 인천 청소 용역 평균 낙찰률은 91.00%입니다."
    assert "적용하지 못해" not in answer


def test_question_without_industry_term_keeps_compiled_sql(isolated_db):
    """업종어 없는 질문은 조건도 표시도 늘지 않아 종전 SQL·캐시 키가 유지됩니다."""
    plan = build_retrieval_plan("인천 용역 낙찰률 알려줘")
    baseline = RetrievalPlan(
        use_sql=True, filters={"category": "Servc", "institution_name": "인천"}
    )

    def _compiled(target: RetrievalPlan, builder) -> str:
        statement = select(func.count(BidResult.id)).where(*builder(target))
        return str(statement.compile(dialect=MYSQL_DIALECT, compile_kwargs={"literal_binds": True}))

    result_sql = _compiled(plan, sd._result_conditions)
    announcement_sql = _compiled(plan, sd._announcement_conditions)

    assert result_sql == _compiled(baseline, sd._result_conditions)
    assert "bid_ntce_nm LIKE" not in result_sql
    assert "bid_ntce_nm LIKE" not in announcement_sql
    # 업종어가 없으면 응답 필터에도 표시가 붙지 않습니다.
    assert sd._apply_industry_applied(plan.filters) == plan.filters
    assert "industry_applied" not in sd._apply_industry_applied(plan.filters)


def test_industry_term_sql_excludes_noise_terms():
    """업종 조건이 붙은 SQL 은 키워드 OR 와 잡음 NOT 을 함께 씁니다."""
    plan = _industry_plan()

    statement = select(func.count(BidResult.id)).where(*sd._result_conditions(plan))
    compiled = str(statement.compile(dialect=MYSQL_DIALECT, compile_kwargs={"literal_binds": True}))

    assert "bid_ntce_nm LIKE" in compiled
    assert "청소" in compiled
    assert "환경미화" in compiled
    assert "청소차" in compiled
    assert "청소기" in compiled


def test_industry_term_applies_to_period_comparison(isolated_db):
    """기간 비교의 대상별 집계도 같은 업종 조건으로 좁혀집니다."""
    _seed_industry_rows(isolated_db)
    plan = RetrievalPlan(
        use_sql=True,
        semantic_query="인천 청소 용역 2025년 대 2026년 낙찰률 비교",
        filters={
            "category": "Servc",
            "institution_name": "인천",
            "industry_label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "comparison_dimension": "time",
            "comparison_targets": [
                {
                    "key": "2025",
                    "label": "2025년",
                    "date_from": "2025-01-01",
                    "date_to": "2025-12-31",
                },
                {
                    "key": "2026",
                    "label": "2026년",
                    "date_from": "2026-01-01",
                    "date_to": "2026-12-31",
                },
            ],
        },
    )

    result = sd.retrieve_structured_data(isolated_db, plan)
    entries = {entry["key"]: entry for entry in result["summary"]["comparison"]}

    assert result["filters"]["industry_applied"] is True
    assert entries["2025"]["announcement_count"] == 2
    assert entries["2025"]["bid_count"] == 2
    assert entries["2025"]["avg_rate"] == 89.0
    assert entries["2026"]["announcement_count"] == 2
    assert entries["2026"]["bid_count"] == 2
    assert entries["2026"]["avg_rate"] == 93.0


def test_industry_scope_skips_region_index_hints():
    """업종어 조건이 붙으면 공고명 미포함 인덱스 힌트를 생략해 본문 읽기를 피합니다."""
    region_names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 1)]
    announcement_stmt = select(func.count(BidAnnouncement.id)).where(
        BidAnnouncement.dminstt_nm.in_(region_names)
    )
    result_stmt = select(func.count(BidResult.id)).where(BidResult.dminstt_nm.in_(region_names))
    plain_plan = RetrievalPlan(
        use_sql=True, filters={"category": "Servc", "institution_name": "인천"}
    )
    industry_plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "institution_name": "인천",
            "industry_label": "청소",
            "title_keywords": ["청소"],
        },
    )

    def _compiled(statement) -> str:
        compiled = statement.compile(dialect=MYSQL_DIALECT, compile_kwargs={"literal_binds": True})
        return str(compiled)

    assert "FORCE INDEX" in _compiled(
        sd._hint_announcement_resolved_scope(announcement_stmt, region_names, plan=plain_plan)
    )
    assert (
        sd._hint_announcement_resolved_scope(announcement_stmt, region_names, plan=industry_plan)
        is announcement_stmt
    )
    assert "FORCE INDEX" in _compiled(
        sd._hint_result_region_resolved_cover(result_stmt, plain_plan, region_names)
    )
    assert (
        sd._hint_result_region_resolved_cover(result_stmt, industry_plan, region_names)
        is result_stmt
    )


def test_industry_applied_filters_read_result_scope_not_plan_filters():
    """적용 표시는 plan.filters 사본이 아니라 정형 결과의 industry_scope 정본입니다."""
    plan = build_retrieval_plan("인천 청소 용역 낙찰률 알려줘")
    applied_structured = {
        "filters": {**(plan.filters or {}), "industry_applied": True},
        "industry_scope": {
            "label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "applied": True,
        },
    }

    notice_filters = industry_applied_filters(applied_structured, plan.filters)

    assert notice_filters.get("industry_applied") is True
    assert collect_unapplied_result_conditions(notice_filters) == []
    # 미적용 결과에는 같은 정본이 없으므로 plan.filters 그대로 남습니다.
    assert industry_applied_filters({}, plan.filters) == plan.filters


def test_result_list_answer_drops_notice_when_industry_applied(isolated_db):
    """업종 조건이 붙은 낙찰 목록 답에는 미적용 안내가 붙지 않습니다."""
    _seed_industry_rows(isolated_db)
    plan = build_retrieval_plan("인천 청소 용역 낙찰 결과 10건 보여줘")

    structured = sd.retrieve_structured_data(isolated_db, plan)
    answer = _build_result_list_answer(plan, structured)

    assert structured["industry_scope"]["applied"] is True
    assert "적용하지 못해" not in answer
    assert "청소차" not in answer
    assert "경비 용역" not in answer
    assert "4건입니다" in answer


def test_result_list_answer_keeps_notice_when_industry_not_applied():
    """정형 결과에 적용 표시가 없으면 낙찰 목록 답에 미적용 안내가 남습니다."""
    plan = RetrievalPlan(
        use_sql=True,
        semantic_query="인천 청소 용역 낙찰 결과 보여줘",
        filters={
            "category": "Servc",
            "institution_name": "인천",
            "industry_label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "result_limit": 5,
        },
    )
    structured = _industry_structured_data()
    structured["summary"]["recent_results"] = [
        {
            "bid_ntce_no": "IND-RES-001",
            "bid_ntce_nm": "2025년 청사 청소 용역",
            "dminstt_nm": "인천광역시",
            "bidwinnr_nm": "청소업체A",
            "sucsf_bid_amt": 80_000_000,
            "sucsf_bid_rate": 88.0,
            "rl_openg_dt": "2025-05-10 09:00:00",
        }
    ]

    answer = _build_result_list_answer(plan, structured)

    assert "업종 조건(청소)은 적용하지 못해 인천 용역 전체로 조회했습니다." in answer


def test_announcement_list_answer_drops_notice_when_industry_applied(isolated_db):
    """업종 조건이 붙은 공고 목록 답에도 미적용 안내가 붙지 않습니다."""
    _seed_industry_rows(isolated_db)
    plan = build_retrieval_plan("인천 청소 용역 공고 보여줘")

    structured = sd.retrieve_structured_data(isolated_db, plan)
    answer = _build_announcement_list_answer(plan, structured)

    assert structured["industry_scope"]["applied"] is True
    assert "적용하지 못해" not in answer
    assert "청소차" not in answer
    assert {item["bid_ntce_nm"] for item in structured["summary"]["sample_announcements"]} == {
        "2025년 청사 청소 용역",
        "2025년 환경미화 용역",
        "2026년 청사 청소 용역",
        "2026년 미화 용역",
    }


def test_announcement_list_answer_keeps_notice_when_industry_not_applied():
    """정형 결과에 적용 표시가 없으면 공고 목록 답에 미적용 안내가 남습니다."""
    plan = RetrievalPlan(
        use_sql=True,
        semantic_query="인천 청소 용역 공고 보여줘",
        filters={
            "category": "Servc",
            "institution_name": "인천",
            "industry_label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "announcement_limit": 5,
        },
    )
    structured = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {
            "sample_announcements": [
                {
                    "bid_ntce_no": "IND-ANN-001",
                    "bid_ntce_nm": "2025년 청사 청소 용역",
                    "dminstt_nm": "인천광역시",
                    "presmpt_prce": 80_000_000,
                    "bid_ntce_dt": "2025-05-01 09:00:00",
                    "bid_clse_dt": "2025-05-05 18:00:00",
                }
            ]
        },
    }

    answer = _build_announcement_list_answer(plan, structured)

    assert "업종 조건(청소)은 적용하지 못해 인천 용역 전체로 조회했습니다." in answer


def test_comparison_answer_uses_industry_scope_for_notice():
    """비교 답도 같은 정본으로 안내 여부를 정합니다."""
    filters = {
        "category": "Servc",
        "industry_label": "청소",
        "title_keywords": ["청소", "미화", "환경미화"],
    }
    plan = RetrievalPlan(use_sql=True, filters=filters)
    summary = {
        "comparison": [{"label": "인천", "announcement_count": 4}],
        "comparison_meta": {
            "dimension": "region",
            "metric": "announcement_count",
            "targets": ["인천"],
        },
    }
    applied = {
        "filters": {**filters, "industry_applied": True},
        "summary": summary,
        "industry_scope": {
            "label": "청소",
            "title_keywords": ["청소", "미화", "환경미화"],
            "applied": True,
        },
    }

    applied_answer = _build_comparison_answer(plan, applied)
    unapplied_answer = _build_comparison_answer(
        plan, {"filters": dict(filters), "summary": summary}
    )

    assert "적용하지 못해" not in applied_answer
    assert "업종 조건(청소)은 적용하지 못해 용역 전체로 조회했습니다." in unapplied_answer
