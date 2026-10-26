"""이번 주 기간 창과 점검 세트 N일 통계 경계 회귀 시험.

"이번 주" 공고·낙찰 목록·통계는 달력 주(월요일~오늘)가 아니라 오늘 포함 7일
(오늘-6일 ~ 오늘)로 읽는다. 마감 창과 다른 기간 표현은 그대로 둔다. 점검 세트
v1 의 N일 통계 기대 SQL 은 오늘 포함 N일이 되도록 INTERVAL N-1 DAY 경계를 쓴다.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_FIXTURE = "data/benchmarks/chat_user_questions_v1.json"
BLIND_FIXTURE = "data/benchmarks/chat_user_questions_blind_v1.json"

WEDNESDAY = date(2026, 10, 21)
SUNDAY = date(2026, 10, 25)
MONDAY = date(2026, 10, 26)

TODAYS = pytest.mark.parametrize(
    "today",
    [WEDNESDAY, SUNDAY, MONDAY],
    ids=["wednesday", "sunday", "monday"],
)

EXPECTED_SQL: dict[str, dict[str, str]] = {
    PUBLIC_FIXTURE: {
        "pub_sta_02": "SELECT COUNT(*) FROM bid_announcements WHERE category = 'Cnstwk' AND bid_ntce_dt >= CURDATE() - INTERVAL 6 DAY",
        "pub_sta_04": "SELECT COUNT(*) FROM bid_announcements WHERE bid_ntce_dt >= CURDATE() - INTERVAL 6 DAY",
        "pub_sta_05": "SELECT COUNT(*) FROM bid_results WHERE category = 'Servc' AND rl_openg_dt >= CURDATE() - INTERVAL 13 DAY",
        "pub_res_14": "SELECT ROUND(AVG(sucsf_bid_rate), 2) FROM bid_results WHERE category = 'Servc' AND rl_openg_dt >= CURDATE() - INTERVAL 59 DAY AND sucsf_bid_rate IS NOT NULL AND dminstt_nm LIKE '%{latest_servc_result_institution}%'",
        "pub_res_16": "SELECT ROUND(AVG(sucsf_bid_rate), 2) FROM bid_results WHERE category = 'Cnstwk' AND rl_openg_dt >= CURDATE() - INTERVAL 13 DAY AND sucsf_bid_rate IS NOT NULL",
        "pub_res_17": "SELECT ROUND(AVG(sucsf_bid_rate), 2) FROM bid_results WHERE category = 'Servc' AND rl_openg_dt >= CURDATE() - INTERVAL 13 DAY AND sucsf_bid_rate IS NOT NULL",
    },
    BLIND_FIXTURE: {
        "blnd_res_03": "SELECT COUNT(*) FROM bid_results WHERE category = 'Frgcpt' AND rl_openg_dt >= CURDATE() - INTERVAL 29 DAY",
        "blnd_res_04": "SELECT COUNT(*) FROM bid_results WHERE category = 'Servc' AND rl_openg_dt >= CURDATE() - INTERVAL 29 DAY",
        "blnd_sta_01": "SELECT COUNT(*) FROM bid_results WHERE category = 'Thng' AND rl_openg_dt >= CURDATE() - INTERVAL 29 DAY",
    },
}


def _freeze(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return today

    monkeypatch.setattr(query_planning, "date", _FrozenDate)


@TODAYS
def test_this_week_announcement_list_uses_today_inclusive_window(monkeypatch, today):
    _freeze(monkeypatch, today)

    plan = build_retrieval_plan("이번 주 건설 공고 열 개 정리해줘")

    assert plan.filters["date_from"] == (today - timedelta(days=6)).isoformat()
    assert plan.filters["date_to"] == today.isoformat()
    assert plan.filters["category"] == "Cnstwk"
    assert plan.filters["announcement_limit"] == 10


@TODAYS
def test_this_week_result_list_uses_today_inclusive_window(monkeypatch, today):
    _freeze(monkeypatch, today)

    plan = build_retrieval_plan("이번 주 낙찰된 용역 5건 목록 보여줘")

    assert plan.filters["date_from"] == (today - timedelta(days=6)).isoformat()
    assert plan.filters["date_to"] == today.isoformat()
    assert plan.filters["category"] == "Servc"
    assert plan.filters["result_limit"] == 5


@TODAYS
def test_this_week_without_space_uses_same_window(monkeypatch, today):
    _freeze(monkeypatch, today)

    plan = build_retrieval_plan("이번주 물품 공고")

    assert plan.filters == {
        "date_from": (today - timedelta(days=6)).isoformat(),
        "date_to": today.isoformat(),
        "category": "Thng",
    }


@TODAYS
def test_this_week_deadline_window_stays_forward_looking(monkeypatch, today):
    _freeze(monkeypatch, today)

    plan = build_retrieval_plan("이번 주 마감되는 용역 공고")

    assert plan.filters["close_from"] == today.isoformat()
    assert plan.filters["close_to"] == (today + timedelta(days=6)).isoformat()
    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters


@TODAYS
def test_other_period_expressions_keep_existing_windows(monkeypatch, today):
    _freeze(monkeypatch, today)

    month_plan = build_retrieval_plan("이번 달 공고")
    assert month_plan.filters == {
        "date_from": today.replace(day=1).isoformat(),
        "date_to": today.isoformat(),
    }

    recent_plan = build_retrieval_plan("최근 일주일 공고")
    assert recent_plan.filters == {
        "date_from": (today - timedelta(days=6)).isoformat(),
        "date_to": today.isoformat(),
    }


def _load_fixture(path: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def _items_by_id(path: str) -> dict[str, Any]:
    return {item["id"]: item for item in _load_fixture(path)["items"]}


def _main_items_by_id(path: str) -> dict[str, Any] | None:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "show", f"main:{path}"],  # noqa: S607
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return {item["id"]: item for item in json.loads(completed.stdout)["items"]}


@pytest.mark.parametrize("fixture_path", [PUBLIC_FIXTURE, BLIND_FIXTURE])
def test_n_day_statistics_sql_includes_today(fixture_path):
    items = _items_by_id(fixture_path)
    expected = EXPECTED_SQL[fixture_path]

    assert set(expected) <= set(items)
    for item_id, sql in expected.items():
        assert items[item_id]["check"]["sql"] == sql


@pytest.mark.parametrize("fixture_path", [PUBLIC_FIXTURE, BLIND_FIXTURE])
def test_only_listed_statistics_sql_differs_from_main(fixture_path):
    baseline = _main_items_by_id(fixture_path)
    if baseline is None:
        pytest.skip("main 기준 점검 세트를 읽을 수 없어 대조를 건너뜁니다")

    items = _items_by_id(fixture_path)
    assert set(items) == set(baseline)

    changed = {
        item_id
        for item_id, item in items.items()
        if item["check"].get("sql") != baseline[item_id]["check"].get("sql")
    }

    assert changed <= set(EXPECTED_SQL[fixture_path])
