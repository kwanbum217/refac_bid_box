"""
tests/test_notice_kind_filter.py

공고 종류(ntce_kind_nm) 표지 추출과 공고 목록·건수 조회 조건을 검증합니다.
"""

from datetime import date, datetime, timedelta

import pytest

from src.app.models.bids import BidAnnouncement
from src.rag import query_planning
from src.rag.answer_format import _build_announcement_list_answer
from src.rag.query_planning import build_retrieval_plan, extract_notice_kind
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import _snapshot_scope, retrieve_structured_data


@pytest.fixture
def fixed_today(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 25)

    monkeypatch.setattr(query_planning, "date", _FixedDate)
    return _FixedDate(2026, 10, 25)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("최근 한 달 재공고 공고 몇 건이야?", "재공고"),
        ("재공고 용역 공고 5개 보여줘", "재공고"),
        ("취소공고 최근 5건", "취소공고"),
        ("취소된 공고 최근 5건", "취소공고"),
        ("변경공고 몇 건이야", "변경공고"),
        ("변경된 공고 알려줘", "변경공고"),
        ("정정공고 목록 보여줘", "변경공고"),
        ("신규 공고 5건 보여줘", "등록공고"),
        ("등록공고 보여줘", "등록공고"),
    ],
)
def test_extract_notice_kind_matches_kind_markers(query, expected):
    assert extract_notice_kind(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "재공고 방지 용역 공고 5개 보여줘",
        "변경 사항 알려줘",
        "취소 방법 알려줘",
        "최근 용역 공고 5개 보여줘",
    ],
)
def test_extract_notice_kind_ignores_general_words(query):
    assert extract_notice_kind(query) == ""


def test_retrieval_plan_adds_notice_kind_to_count_query(fixed_today):
    plan = build_retrieval_plan("최근 한 달 재공고 공고 몇 건이야?")

    assert plan.use_sql is True
    assert plan.filters.get("notice_kind") == "재공고"
    assert plan.filters.get("date_from") == "2026-09-26"
    assert plan.filters.get("date_to") == "2026-10-25"


def test_retrieval_plan_adds_notice_kind_to_list_query():
    plan = build_retrieval_plan("재공고 용역 공고 5개 보여줘")

    assert plan.use_sql is True
    assert plan.filters.get("notice_kind") == "재공고"
    assert plan.filters.get("category") == "Servc"
    assert plan.filters.get("announcement_limit") == 5


def test_retrieval_plan_keeps_notice_kind_out_of_result_queries():
    plan = build_retrieval_plan("재공고 낙찰 결과 5개 보여줘")

    assert "notice_kind" not in plan.filters


def test_retrieval_plan_without_kind_marker_is_unchanged():
    plan = build_retrieval_plan("최근 용역 공고 5개만 리스트해줘")

    assert "notice_kind" not in plan.filters
    assert plan.filters.get("announcement_limit") == 5


def test_snapshot_scope_is_disabled_when_notice_kind_is_set():
    with_kind = RetrievalPlan(use_sql=True, filters={"category": "Servc", "notice_kind": "재공고"})
    without_kind = RetrievalPlan(use_sql=True, filters={"category": "Servc"})

    assert _snapshot_scope(with_kind) is None
    assert _snapshot_scope(without_kind) == "Servc"


def _seed_announcements(db) -> None:
    rows = (
        ("RE-001", "재공고", datetime(2026, 10, 20)),
        ("RE-002", "재공고", datetime(2026, 10, 10)),
        ("RE-003", "재공고", datetime(2026, 10, 1)),
        ("RE-OLD", "재공고", datetime(2026, 8, 1)),
        ("CAN-001", "취소공고", datetime(2026, 10, 5)),
        ("CHG-001", "변경공고", datetime(2026, 10, 6)),
        ("REG-001", "등록공고", datetime(2026, 10, 7)),
    )
    for index, (bid_ntce_no, notice_kind, announced_at) in enumerate(rows, start=1):
        db.add(
            BidAnnouncement(
                bid_ntce_no=bid_ntce_no,
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm=f"용역 공고 {index}",
                dminstt_nm="수요기관",
                presmpt_prce=1000000 * index,
                bid_ntce_dt=announced_at,
                bid_clse_dt=announced_at + timedelta(days=1),
                collected_at=announced_at,
                ntce_kind_nm=notice_kind,
            )
        )
    db.commit()


def test_notice_kind_count_query_counts_only_matching_kind(isolated_db, fixed_today):
    _seed_announcements(isolated_db)

    plan = build_retrieval_plan("최근 한 달 재공고 공고 몇 건이야?")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["announcement_count"] == 3


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("재공고 몇 건이야", 4),
        ("취소공고 몇 건이야", 1),
        ("변경공고 몇 건이야", 1),
        ("등록공고 몇 건이야", 1),
    ],
)
def test_notice_kind_count_query_uses_each_kind(isolated_db, query, expected):
    _seed_announcements(isolated_db)

    plan = build_retrieval_plan(query)
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert plan.filters.get("notice_kind")
    assert summary["announcement_count"] == expected


def test_notice_kind_list_returns_only_matching_kind(isolated_db):
    _seed_announcements(isolated_db)

    plan = build_retrieval_plan("재공고 용역 공고 5개 보여줘")
    structured_data = retrieve_structured_data(isolated_db, plan)
    samples = structured_data["summary"]["sample_announcements"]

    assert [sample["bid_ntce_no"] for sample in samples] == [
        "RE-001",
        "RE-002",
        "RE-003",
        "RE-OLD",
    ]
    assert structured_data["filters"]["category_label"] == "재공고 용역"
    assert (
        _build_announcement_list_answer(plan, structured_data).splitlines()[0]
        == "최근 재공고 용역 공고 4건입니다."
    )


def test_cancel_kind_list_returns_only_cancel_rows(isolated_db):
    _seed_announcements(isolated_db)

    plan = build_retrieval_plan("취소공고 5건 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert plan.filters.get("notice_kind") == "취소공고"
    assert [sample["bid_ntce_no"] for sample in samples] == ["CAN-001"]


def test_announcement_query_without_notice_kind_keeps_existing_scope(isolated_db):
    _seed_announcements(isolated_db)

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc", "announcement_limit": 5})
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert {sample["bid_ntce_no"] for sample in samples} == {
        "RE-001",
        "RE-002",
        "REG-001",
        "CHG-001",
        "CAN-001",
    }
