"""
tests/test_chat_region_comparison.py

지역·기관 비교 질의의 판정, 집계, 단일 지표 응답 계약을 검증합니다.

- 비교 표지는 있지만 두 대상이 아닌 질의(낙찰금액과 추정가격의 차이, 여행 코스)를
  비교로 오인하지 않습니다.
- 지역 비교는 기관명 부분 일치와 정식 명칭 별칭을 함께 잡고, 기관명 해석 상한을
  넘어도 contains 로 범위를 유지해 전체 통계로 넓어지지 않습니다.
- 응답 표는 요청한 지표 하나만 냅니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.answer_format import _build_comparison_answer
from src.rag.engine import HybridRAGEngine
from src.rag.query_planning import _extract_comparison_targets, build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

_NOW = datetime(2026, 5, 10, 9, 0, 0)


def _seed_announcement(
    session,
    *,
    row_id: int,
    institution: str,
    ntce_dt: datetime = _NOW,
    category: str = "Thng",
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ANN-{row_id}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bid_ntce_dt=ntce_dt,
            category=category,
            raw_data=None,
        )
    )


def _seed_result(
    session,
    *,
    row_id: int,
    institution: str,
    opened_at: datetime = _NOW,
    rate: float | None = 90.0,
    category: str = "Thng",
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=1_000_000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def _comparison_map(summary: dict) -> dict[str, dict]:
    return {item["label"]: item for item in summary.get("comparison") or []}


@pytest.mark.parametrize(
    ("query", "regions", "metric"),
    [
        ("부산이랑 대구 공고 건수 비교해줘", ["부산", "대구"], "announcement_count"),
        ("부산과 대구 공고 건수 비교해줘", ["부산", "대구"], "announcement_count"),
        ("서울시랑 부산시 낙찰 결과 비교해줘", ["서울", "부산"], "bid_count"),
        ("부산 대구 공고 건수 비교", ["부산", "대구"], "announcement_count"),
        ("충북이랑 충남 공고 건수 비교해줘", ["충북", "충남"], "announcement_count"),
    ],
)
def test_comparison_extracts_two_regions(query, regions, metric):
    """비교 표지와 두 지역이 있으면 지역 비교로 판정하고 지표를 기록합니다."""
    assert _extract_comparison_targets(query) == (regions, [])

    filters = build_retrieval_plan(query).filters

    assert filters.get("region_names") == regions
    assert filters.get("metric") == metric
    assert "institution_name" not in filters
    assert "institution_names" not in filters


def test_comparison_rejects_non_bidding_and_single_target_questions():
    """단일 지역·축 질의·비입찰 비교는 기존 경로를 그대로 씁니다."""
    false_cases = (
        "낙찰금액과 추정가격의 차이를 설명해줘",
        "부산 공고 건수 알려줘",
        "부산이랑 대구 여행 코스 비교해줘",
        "공고번호 R26BK01778156 낙찰 결과 알려줘",
        "분류별 공고 건수 비교해줘",
        "서울 지역 기관 평균 낙찰률 알려줘",
    )
    for query in false_cases:
        filters = build_retrieval_plan(query).filters
        assert "region_names" not in filters, query
        assert "institution_names" not in filters, query

    assert build_retrieval_plan("부산 공고 건수 알려줘").filters.get("institution_name") == "부산"
    assert build_retrieval_plan("분류별 공고 건수 비교해줘").filters.get("group_by") == "category"
    assert (
        build_retrieval_plan("서울 지역 기관 평균 낙찰률 알려줘").filters.get("institution_name")
        == "서울"
    )


def test_region_alias_matches_full_name(isolated_db):
    """충북 라벨이 충청북도로 시작하는 기관과 충북대학교를 함께 집계합니다."""
    _seed_announcement(isolated_db, row_id=1, institution="충청북도교육청")
    _seed_announcement(isolated_db, row_id=2, institution="충청북도교육청")
    _seed_announcement(isolated_db, row_id=3, institution="충북대학교")
    _seed_announcement(isolated_db, row_id=4, institution="충청남도")
    _seed_announcement(isolated_db, row_id=5, institution="서울특별시")
    isolated_db.commit()

    plan = build_retrieval_plan("충북이랑 충남 공고 건수 비교해줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    entries = _comparison_map(summary)

    assert entries["충북"]["announcement_count"] == 3
    assert entries["충남"]["announcement_count"] == 1
    assert summary["announcement_count"] == 4
    assert summary["comparison_meta"]["metric"] == "announcement_count"


def test_unresolved_region_falls_back_to_contains(isolated_db, monkeypatch):
    """기관명 해석 상한을 넘어도 지역 비교는 contains 범위를 유지합니다."""
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)
    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=2, institution="부산대학교")
    _seed_announcement(isolated_db, row_id=3, institution="부산시설공단")
    _seed_announcement(isolated_db, row_id=4, institution="대구광역시청")
    _seed_announcement(isolated_db, row_id=5, institution="대구광역시청")
    _seed_announcement(isolated_db, row_id=6, institution="서울특별시")
    isolated_db.commit()

    plan = build_retrieval_plan("부산이랑 대구 공고 건수 비교해줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    entries = _comparison_map(summary)

    assert entries["부산"]["announcement_count"] == 3
    assert entries["대구"]["announcement_count"] == 2
    # 전체 통계(6건)로 넓어지지 않아야 합니다.
    assert summary["announcement_count"] == 5


def test_region_comparison_ignores_tool_single_region_param(isolated_db):
    """bid_query_tool 이 더한 institution_name 하나가 두 번째 지역을 지우지 않습니다."""
    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=2, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청")
    _seed_announcement(isolated_db, row_id=4, institution="대구광역시청")
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "region_names": ["부산", "대구"],
            "institution_name": "부산",
            "metric": "announcement_count",
        },
    )
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    entries = _comparison_map(summary)

    assert entries["부산"]["announcement_count"] == 2
    assert entries["대구"]["announcement_count"] == 2
    assert summary["announcement_count"] == 4


def test_bid_query_tool_region_comparison_keeps_both_regions(isolated_db):
    """bid_query_tool 의 플래너 파라미터가 섞여도 두 지역 표가 유지됩니다."""
    from src.app.services.tools.bid_query_tool import execute

    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=2, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청")
    isolated_db.commit()

    result = execute(
        db=isolated_db,
        query="부산이랑 대구 공고 건수 비교해줘",
        institution_name="부산",
        years=5,
    )
    summary = result["result"]["summary"]
    entries = _comparison_map(summary)

    assert entries["부산"]["announcement_count"] == 2
    assert entries["대구"]["announcement_count"] == 1
    assert "institution_name" not in result["result"]["filters"]


def test_comparison_uses_announcement_metric_only(isolated_db):
    """공고 건수 비교는 공고 건수만 집계하고 낙찰 건수는 표에 내지 않습니다."""
    for index in range(2):
        _seed_announcement(isolated_db, row_id=index + 1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청")
    for index in range(50):
        _seed_result(isolated_db, row_id=100 + index, institution="부산광역시청")
    for index in range(40):
        _seed_result(isolated_db, row_id=200 + index, institution="대구광역시청")
    isolated_db.commit()

    plan = build_retrieval_plan("부산이랑 대구 공고 건수 비교해줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    entries = _comparison_map(summary)

    assert entries["부산"]["announcement_count"] == 2
    assert entries["대구"]["announcement_count"] == 1
    assert entries["부산"]["bid_count"] == 50
    assert entries["대구"]["bid_count"] == 40
    assert summary["comparison_meta"]["metric"] == "announcement_count"

    answer = _build_comparison_answer(plan, {"summary": summary})
    assert "| 부산 | 2 |" in answer
    assert "| 대구 | 1 |" in answer
    assert "낙찰 건수" not in answer
    assert "50" not in answer
    assert "40" not in answer


def test_comparison_answer_renders_single_metric():
    """비교 표는 comparison_meta 의 지표 열 하나만 냅니다."""
    plan = RetrievalPlan(filters={"region_names": ["부산", "대구"], "metric": "bid_count"})
    structured = {
        "summary": {
            "comparison": [
                {
                    "label": "부산",
                    "key": "부산",
                    "announcement_count": 1486,
                    "bid_count": 1384,
                    "avg_rate": 90.1,
                    "sample_count": 1384,
                },
                {
                    "label": "대구",
                    "key": "대구",
                    "announcement_count": 1075,
                    "bid_count": 1036,
                    "avg_rate": 89.0,
                    "sample_count": 1036,
                },
            ],
            "comparison_meta": {
                "dimension": "region",
                "metric": "bid_count",
                "targets": ["부산", "대구"],
            },
        }
    }

    answer = _build_comparison_answer(plan, structured)

    assert "지역별 낙찰 건수 비교입니다." in answer
    assert "| 지역 | 낙찰 건수 |" in answer
    assert "| 부산 | 1,384 |" in answer
    assert "| 대구 | 1,036 |" in answer
    assert "공고 건수" not in answer
    assert "1,486" not in answer
    assert "1,075" not in answer


def test_amount_difference_question_is_not_comparison():
    """금액·가격 차이 설명은 지역·기관 비교가 아닙니다."""
    query = "낙찰금액과 추정가격의 차이를 설명해줘"

    assert _extract_comparison_targets(query) == ([], [])
    filters = build_retrieval_plan(query).filters
    assert "region_names" not in filters
    assert "institution_names" not in filters


def test_multi_institution_overflow_does_not_broaden_to_global_stats(isolated_db, monkeypatch):
    """해석 상한을 넘은 기관 후보는 contains 로 범위를 유지하고 전체 통계로 넓어지지 않습니다."""
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)
    _seed_result(isolated_db, row_id=1, institution="가나교육청")
    _seed_result(isolated_db, row_id=2, institution="가나도서관")
    _seed_result(isolated_db, row_id=3, institution="다라교육청")
    _seed_result(isolated_db, row_id=4, institution="다라도서관")
    _seed_result(isolated_db, row_id=5, institution="마바교육청")
    _seed_result(isolated_db, row_id=6, institution="마바교육청")
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"institution_names": ["가나", "다라"]})
    result = retrieve_structured_data(isolated_db, plan)
    summary = result["summary"]
    by_institution = summary["by_institution"]

    assert [item["institution_name"] for item in by_institution] == ["가나", "다라"]
    assert [item["bid_count"] for item in by_institution] == [2, 2]
    # 대상 밖 기관 2건이 섞인 전체 통계(6건)가 아니어야 합니다.
    assert summary["total_bids"] == 4


def test_unresolved_multi_institution_does_not_fall_back_to_global_stats(isolated_db):
    """대상을 하나도 확정하지 못하면 전체 통계 대신 빈 결과와 안내를 냅니다."""
    _seed_result(isolated_db, row_id=1, institution="서울특별시교육청")
    _seed_result(isolated_db, row_id=2, institution="부산광역시교육청")
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={"institution_names": ["완전히없는기관A", "완전히없는기관B"]},
    )
    result = retrieve_structured_data(isolated_db, plan)
    summary = result["summary"]

    assert result["query_skipped"] is True
    assert summary["total_bids"] is None
    assert "by_institution" not in summary
    assert any("확정하지 못했습니다" in hint for hint in result["insufficiency_hints"])


class _RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args, **kwargs) -> str:
        self.calls += 1
        return "LLM 응답"


def test_comparison_engine_returns_direct_table_without_llm():
    """비교 응답은 LLM 앞에서 결정론적 표로 조립됩니다."""
    structured = {
        "filters": {"region_names": ["부산", "대구"], "metric": "announcement_count"},
        "summary": {
            "comparison": [
                {
                    "label": "부산",
                    "key": "부산",
                    "announcement_count": 1486,
                    "bid_count": 1384,
                    "avg_rate": 90.1,
                    "sample_count": 1384,
                },
                {
                    "label": "대구",
                    "key": "대구",
                    "announcement_count": 1075,
                    "bid_count": 1036,
                    "avg_rate": 89.0,
                    "sample_count": 1036,
                },
            ],
            "comparison_meta": {
                "dimension": "region",
                "metric": "announcement_count",
                "targets": ["부산", "대구"],
            },
        },
        "insufficiency_hints": [],
    }

    engine = HybridRAGEngine()
    backend = _RecordingBackend()
    engine._backend_resolved = True
    engine._backend = backend

    bundle = engine.get_answer_sync(
        "부산이랑 대구 공고 건수 비교해줘",
        tool_context={"tool_results": {"bid_query": {"result": structured}}},
    )

    assert backend.calls == 0
    assert "지역별 공고 건수 비교입니다." in bundle.answer
    assert "| 부산 | 1,486 |" in bundle.answer
    assert "| 대구 | 1,075 |" in bundle.answer
    assert "1,384" not in bundle.answer
