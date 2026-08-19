"""
tests/test_query_skipped_context.py

조회를 수행하지 않음(query_skipped)과 조회했더니 0건이 LLM 문맥에서
구분되는지 검증합니다.

잘못된 날짜 필터로 조회 자체를 건너뛴 경우 0 통계가 "조회했더니 0건" 처럼
들어가면 사용자가 오독합니다. query_skipped=True 에서는 수치 줄을 하나도
만들지 않고, 정상 조회가 0건일 때만 "- 낙찰 결과 수: 0" 을 남깁니다.
"""

from unittest.mock import MagicMock

from src.rag.snapshots import _extract_statistical_snapshot
from src.rag.structured_data import retrieve_structured_data


def _skipped_structured_data(hint: str = "잘못된 날짜 필터입니다.") -> dict:
    return {
        "summary": {
            "total_bids": None,
            "announcement_count": None,
            "average_winning_rate": None,
            "total_winning_amount": None,
            "top_winners": [],
            "top_institutions": [],
            "top_announcements": [],
            "sample_announcements": [],
            "recent_results": [],
            "latest_available_result_at": None,
            "time_series": [],
        },
        "insufficiency_hints": [hint],
        "query_skipped": True,
    }


def test_query_skipped_snapshot_has_no_zero_stat_lines():
    """조회를 건너뛰었으면 수치 줄이 하나도 없어야 합니다."""
    snapshot = _extract_statistical_snapshot(_skipped_structured_data())

    assert "낙찰 결과 수" not in snapshot
    assert "공고 수" not in snapshot
    assert "평균 낙찰률" not in snapshot
    assert "총 낙찰 금액" not in snapshot
    assert "정형 데이터 집계: 조회를 수행하지 않아 통계가 없습니다." in snapshot


def test_query_skipped_snapshot_keeps_insufficiency_hints():
    """건너뛴 사유는 한계 문구로 남아야 합니다."""
    snapshot = _extract_statistical_snapshot(
        _skipped_structured_data(hint="날짜를 YYYY-MM-DD 형식으로 다시 알려주세요.")
    )

    assert "- 한계: 날짜를 YYYY-MM-DD 형식으로 다시 알려주세요." in snapshot


def test_normal_zero_result_keeps_zero_stat():
    """정상 조회가 0건이면 0 통계가 남습니다. 건너뛰기와 구분됩니다."""
    structured_data = {
        "summary": {
            "total_bids": 0,
            "announcement_count": 0,
            "average_winning_rate": 0.0,
            "total_winning_amount": 0.0,
            "top_winners": [],
            "top_institutions": [],
            "top_announcements": [],
            "sample_announcements": [],
            "recent_results": [],
            "latest_available_result_at": None,
            "time_series": [],
        },
        "insufficiency_hints": ["조건에 맞는 낙찰 결과가 충분하지 않습니다."],
    }

    snapshot = _extract_statistical_snapshot(structured_data)

    assert "- 낙찰 결과 수: 0" in snapshot
    assert "- 공고 수: 0" in snapshot
    assert "조회를 수행하지 않아" not in snapshot


def test_normal_path_none_summary_is_not_rendered_as_zero():
    """정상 경로라도 값이 None 이면 0 으로 표기하지 않고 확인되지 않음으로 둡니다."""
    structured_data = {
        "summary": {
            "total_bids": None,
            "announcement_count": 5,
            "average_winning_rate": None,
            "total_winning_amount": None,
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

    snapshot = _extract_statistical_snapshot(structured_data)

    assert "- 낙찰 결과 수: 확인되지 않음" in snapshot
    assert "- 공고 수: 5" in snapshot
    assert "- 낙찰 결과 수: 0" not in snapshot


def test_bad_date_query_skipped_snapshot_has_no_zero_stat():
    """잘못된 날짜 결과가 스냅샷에서 어디에도 0 통계로 표기되지 않아야 합니다."""
    plan = MagicMock()
    plan.filters = {"date_from": "지난달쯤"}
    db = MagicMock()

    result = retrieve_structured_data(db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["total_bids"] is None
    assert result["summary"]["announcement_count"] is None
    assert result["summary"]["average_winning_rate"] is None
    assert result["summary"]["total_winning_amount"] is None
    snapshot = _extract_statistical_snapshot(result)
    assert "낙찰 결과 수" not in snapshot
    assert "공고 수" not in snapshot
    assert "평균 낙찰률" not in snapshot
    assert "총 낙찰 금액" not in snapshot
    assert "정형 데이터 집계: 조회를 수행하지 않아 통계가 없습니다." in snapshot
    assert "- 한계:" in snapshot


def test_answer_guard_does_not_crash_on_none_summary():
    """summary 값이 None 이면 get 의 기본값이 쓰이지 않아 비교에서 TypeError 가 납니다.

    _empty_result 가 수치를 None 으로 채우도록 바뀌면서 생긴 크래시 경로입니다.
    """
    from src.rag.engine import HybridRAGEngine

    engine = HybridRAGEngine()
    plan = MagicMock()
    plan.filters = {}

    guarded = engine._apply_answer_guard("데이터가 없습니다", _skipped_structured_data(), plan)
    assert "데이터가 없습니다" in guarded

    # query_skipped 가 아니어도 값이 None 이면 크래시하지 않아야 합니다.
    no_flag = _skipped_structured_data()
    del no_flag["query_skipped"]
    assert engine._apply_answer_guard("데이터가 없습니다", no_flag, plan)


def test_skipped_query_produces_no_statistics_evidence():
    """조회하지 않았는데 통계 Source 를 만들면 근거 없는 인용이 생깁니다."""
    from src.rag.answer_format import _build_evidence_items

    items = _build_evidence_items(_skipped_structured_data(), [], None)
    assert not [i for i in items if i.type == "sql_stats"]

    normal = {
        "summary": {"total_bids": 0, "announcement_count": 0, "sample_announcements": []},
        "filters": {},
    }
    normal_items = _build_evidence_items(normal, [], None)
    assert [i for i in normal_items if i.id == "sql_summary"]


def test_fallback_answer_marks_skipped_query():
    """LLM 실패 시 보이는 대체 답변에도 0 통계가 들어가면 안 됩니다."""
    from src.rag.answer_format import _fallback_answer

    plan = MagicMock()
    plan.filters = {}
    plan.route_reason = "테스트"

    text = _fallback_answer("질문", plan, _skipped_structured_data(), [], None)
    assert "조회를 수행하지 않아 통계가 없습니다" in text
    assert "낙찰 결과 0건" not in text
    assert "낙찰 결과 None" not in text


def test_fallback_answer_keeps_zero_for_real_zero_result():
    """정상 조회 0건은 종전대로 0 으로 표기합니다."""
    from src.rag.answer_format import _fallback_answer

    plan = MagicMock()
    plan.filters = {}
    plan.route_reason = "테스트"
    normal = {
        "summary": {"total_bids": 0, "announcement_count": 0, "average_winning_rate": 0.0},
        "filters": {},
    }

    text = _fallback_answer("질문", plan, normal, [], None)
    assert "낙찰 결과 0건" in text
    assert "조회를 수행하지 않아" not in text
