"""낙찰 지표 시계열은 LLM 을 거치지 않고 DB 시계열 표로 답합니다."""

from datetime import date

from src.rag.answer_format import _build_series_answer
from src.rag.schemas import RetrievalPlan


def _shift_quarter(year: int, quarter: int, offset: int) -> tuple[int, int]:
    index = year * 4 + (quarter - 1) + offset
    return index // 4, index % 4 + 1


def _quarter_label(year: int, quarter: int) -> str:
    return f"{year}년 {quarter}분기"


def _current_quarter() -> tuple[int, int]:
    today = date.today()
    return today.year, (today.month - 1) // 3 + 1


def test_quarter_avg_rate_series_renders_rate_and_count_columns():
    """분기 평균 낙찰률은 소수 둘째 자리 %로, 낙찰 건수와 함께 표에 냅니다."""
    year, quarter = _current_quarter()
    previous_two = _shift_quarter(year, quarter, -2)
    previous_one = _shift_quarter(year, quarter, -1)
    plan = RetrievalPlan(
        filters={"group_by": "time", "metric": "avg_rate", "time_bucket": "quarter"}
    )
    structured = {
        "filters": {},
        "summary": {
            "time_series": [
                {
                    "label": _quarter_label(*previous_two),
                    "period": "quarter",
                    "avg_rate": 90.1746,
                    "bid_count": 79981,
                    "announcement_count": 134037,
                },
                {
                    "label": _quarter_label(*previous_one),
                    "period": "quarter",
                    "avg_rate": 89.5,
                    "bid_count": 1234,
                    "announcement_count": 5000,
                },
                {
                    "label": _quarter_label(year, quarter),
                    "period": "quarter",
                    "avg_rate": 88.1255,
                    "bid_count": 7,
                    "announcement_count": 9,
                },
            ],
            "aggregate_meta": {"group_by": "time", "metric": "avg_rate"},
        },
    }

    answer = _build_series_answer(plan, structured)

    assert answer.startswith("분기별 평균 낙찰률 추이입니다.")
    assert "| 분기 | 평균 낙찰률 | 낙찰 건수 |" in answer
    assert f"| {_quarter_label(*previous_two)} | 90.17% | 79,981 |" in answer
    assert f"| {_quarter_label(*previous_one)} | 89.50% | 1,234 |" in answer
    assert "88.13% | 7 |" in answer
    assert "avg_rate" not in answer
    assert "bid_count" not in answer
    assert "컨텍스트" not in answer
    assert len([line for line in answer.splitlines() if line.startswith("| 20")]) == 3


def test_current_quarter_is_marked_in_progress():
    """오늘이 속한 분기에만 진행 중 표기를 붙입니다."""
    year, quarter = _current_quarter()
    previous = _shift_quarter(year, quarter, -1)
    plan = RetrievalPlan(
        filters={"group_by": "time", "metric": "avg_rate", "time_bucket": "quarter"}
    )
    structured = {
        "summary": {
            "time_series": [
                {
                    "label": _quarter_label(*previous),
                    "period": "quarter",
                    "avg_rate": 89.0,
                    "bid_count": 10,
                },
                {
                    "label": _quarter_label(year, quarter),
                    "period": "quarter",
                    "avg_rate": 90.0,
                    "bid_count": 20,
                },
            ],
            "aggregate_meta": {"group_by": "time", "metric": "avg_rate"},
        }
    }

    answer = _build_series_answer(plan, structured)

    assert f"| {_quarter_label(*previous)} | 89.00% |" in answer
    assert f"| {_quarter_label(year, quarter)} (진행 중) | 90.00% |" in answer
    assert answer.count("(진행 중)") == 1


def test_monthly_bid_count_series_renders_bid_count_only():
    """월별 낙찰 건수 질문은 낙찰 건수 한 열만 냅니다."""
    plan = RetrievalPlan(filters={"analysis_mode": "trend", "metric": "bid_count"})
    structured = {
        "summary": {
            "time_series": [
                {"label": "2025-01", "period": "month", "avg_rate": 91.0, "bid_count": 1234},
                {"label": "2025-02", "period": "month", "avg_rate": 92.5, "bid_count": 5678},
            ]
        }
    }

    answer = _build_series_answer(plan, structured)

    assert answer.startswith("월별 낙찰 건수 추이입니다.")
    assert "| 월 | 낙찰 건수 |" in answer
    assert "| 2025-01 | 1,234 |" in answer
    assert "| 2025-02 | 5,678 |" in answer
    assert "91.00%" not in answer
    assert "avg_rate" not in answer
    assert "bid_count" not in answer


def test_announcement_count_series_keeps_existing_output():
    """공고 건수 시계열 출력은 기존 계약과 같은 문자열입니다."""
    plan = RetrievalPlan(filters={"group_by": "time", "metric": "announcement_count"})
    structured = {
        "summary": {
            "time_series": [
                {
                    "label": "2026년 1분기",
                    "period": "quarter",
                    "avg_rate": 88.0,
                    "bid_count": 79981,
                    "announcement_count": 134037,
                },
                {
                    "label": "2026년 2분기",
                    "period": "quarter",
                    "avg_rate": 89.0,
                    "bid_count": 85820,
                    "announcement_count": 135823,
                },
            ],
            "aggregate_meta": {"group_by": "time", "metric": "announcement_count"},
        }
    }

    answer = _build_series_answer(plan, structured)

    assert answer == (
        "분기별 공고 건수입니다.\n"
        "\n"
        "| 분기 | 공고 건수 |\n"
        "| --- | ---: |\n"
        "| 2026년 1분기 | 134,037 |\n"
        "| 2026년 2분기 | 135,823 |"
    )


def test_default_window_adds_period_line():
    """기본 기간 창이 적용되었으면 표 위에 기간을 한 줄 적습니다."""
    plan = RetrievalPlan(
        filters={
            "group_by": "time",
            "metric": "avg_rate",
            "time_bucket": "quarter",
            "relative_years": 3,
        }
    )
    structured = {
        "filters": {},
        "summary": {
            "time_series": [
                {
                    "label": "2025년 1분기",
                    "period": "quarter",
                    "avg_rate": 90.0,
                    "bid_count": 10,
                }
            ],
            "aggregate_meta": {"group_by": "time", "metric": "avg_rate"},
        },
    }

    answer = _build_series_answer(plan, structured)

    assert answer.splitlines()[0] == "분기별 평균 낙찰률 추이입니다."
    assert answer.splitlines()[1] == "기간: 최근 3년"


def test_empty_series_returns_empty_string():
    plan = RetrievalPlan(filters={"group_by": "time", "metric": "avg_rate"})
    structured = {"summary": {"time_series": []}}

    assert _build_series_answer(plan, structured) == ""


def test_all_none_values_return_empty_string():
    plan = RetrievalPlan(filters={"group_by": "time", "metric": "avg_rate"})
    structured = {
        "summary": {
            "time_series": [
                {"label": "2025년 1분기", "period": "quarter", "avg_rate": None, "bid_count": None},
                {"label": "2025년 2분기", "period": "quarter", "avg_rate": None, "bid_count": None},
            ],
            "aggregate_meta": {"group_by": "time", "metric": "avg_rate"},
        }
    }

    assert _build_series_answer(plan, structured) == ""
