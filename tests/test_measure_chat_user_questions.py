"""챗봇 사용자 질문 점검 세트와 측정기의 단위 시험.

운영 앱과 DB 는 부르지 않는다. HTTP 는 call_fn, DB 는 query_fn 으로 대체한다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import measure_chat_user_questions as measure

PUBLIC_FIXTURE = PROJECT_ROOT / "data/benchmarks/chat_user_questions_v1.json"
BLIND_FIXTURE = PROJECT_ROOT / "data/benchmarks/chat_user_questions_blind_v1.json"

ALLOWED = [f"R26BK01789{index:03d}" for index in range(500, 505)]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _announcement_item(
    *,
    limit: int = 5,
    repeats: int = 1,
    must_not_contain: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": "t_ann",
        "category": "announcement_list",
        "split": "public",
        "question": "최근 용역 공고 5개만 보여줘",
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {"type": "announcement_latest", "category": "Servc", "limit": limit, "days": 7},
        "must_not_contain": (
            ["리스트해 드릴 수 없"] if must_not_contain is None else must_not_contain
        ),
        "repeats": repeats,
        "note": "",
    }


def _payload(answer: str, tools: tuple[str, ...] = ("bid_query_tool",)) -> dict[str, Any]:
    return {
        "ok": True,
        "status": 200,
        "elapsed_ms": 12.0,
        "payload": {
            "intent": "bid_query",
            "mode": "answer",
            "answer": answer,
            "plan_steps": [
                {"step_id": str(index), "kind": "tool", "tool": tool}
                for index, tool in enumerate(tools)
            ],
            "provenance": {"source": "db"},
            "latency_ms": 11.5,
        },
    }


def _latest_truth(
    allowed: list[str], expected_count: int, *, data_available: bool = True
) -> dict[str, Any]:
    return {
        "kind": "announcement_latest",
        "allowed": set(allowed),
        "expected_count": expected_count,
        "data_available": data_available,
        "window_fallback": False,
        "error": None,
    }


def _attempt(passed: bool, reasons: list[str] | None = None) -> dict[str, Any]:
    observed = reasons or ([] if passed else ["data_mismatch"])
    return {
        "passed": passed,
        "failure_reason": observed[0] if observed else "",
        "failure_reasons": observed,
        "tools": [],
        "http_status": 200,
        "latency_ms": 1.0,
        "answer_excerpt": "",
        "retried": False,
        "detail": {},
    }


@pytest.mark.parametrize(
    ("path", "split"),
    [(PUBLIC_FIXTURE, "public"), (BLIND_FIXTURE, "blind")],
)
def test_fixture_schema_is_valid(path: Path, split: str) -> None:
    payload = _load(path)
    assert measure.validate_fixture(payload, split, path) == []


@pytest.mark.parametrize(
    ("path", "split"),
    [(PUBLIC_FIXTURE, "public"), (BLIND_FIXTURE, "blind")],
)
def test_split_field_matches_file(path: Path, split: str) -> None:
    payload = _load(path)
    assert {item["split"] for item in payload["items"]} == {split}


def test_fixture_ids_are_unique_across_files() -> None:
    ids = [item["id"] for path in (PUBLIC_FIXTURE, BLIND_FIXTURE) for item in _load(path)["items"]]
    assert len(ids) == len(set(ids))


def test_category_mix_follows_real_user_questions() -> None:
    counts = Counter(
        item["category"]
        for path in (PUBLIC_FIXTURE, BLIND_FIXTURE)
        for item in _load(path)["items"]
    )
    total = sum(counts.values())
    assert total >= 60
    assert counts["announcement_list"] / total >= 0.25
    assert counts["result_analysis"] / total >= 0.25
    bands = {
        "bid_lookup": (0.04, 0.12),
        "stats": (0.08, 0.16),
        "prediction": (0.04, 0.12),
        "out_of_scope": (0.08, 0.16),
    }
    for category, (low, high) in bands.items():
        share = counts[category] / total
        assert low <= share <= high, f"{category} 비율 {share:.1%}"


def test_fixtures_do_not_hardcode_db_answers() -> None:
    for path in (PUBLIC_FIXTURE, BLIND_FIXTURE):
        for item in _load(path)["items"]:
            assert not measure.BID_NO_PATTERN.search(item["question"])
            check = item["check"]
            if check["type"] == "numeric_fact":
                assert "expected_value" not in check
                assert check["sql"]


def test_announcement_latest_passes_when_all_top_numbers_present() -> None:
    item = _announcement_item()
    result = measure.grade_attempt(item, _latest_truth(ALLOWED, 5), _payload(", ".join(ALLOWED)))
    assert result["passed"] is True
    assert result["failure_reasons"] == []


def test_announcement_latest_fails_with_only_four_numbers() -> None:
    item = _announcement_item()
    result = measure.grade_attempt(
        item, _latest_truth(ALLOWED, 5), _payload(", ".join(ALLOWED[:4]))
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["detected_count"] == 4


def test_announcement_latest_fails_with_outside_number() -> None:
    item = _announcement_item()
    answer = ", ".join([*ALLOWED[:4], "R26BK01999999"])
    result = measure.grade_attempt(item, _latest_truth(ALLOWED, 5), _payload(answer))
    assert result["passed"] is False
    assert result["detail"]["outside_allowed"] == ["R26BK01999999"]


def test_latest_truth_includes_same_timestamp_ties() -> None:
    rows = [(f"R26BK01789{index:03d}", "2026-10-23 10:00:00") for index in range(500, 504)]
    rows.append(("R26BK01789504", "2026-10-23 09:00:00"))
    tie_rows = [("R26BK01789505",), ("R26BK01789506",)]

    def fake_query(sql: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        if "= '2026-10-23 09:00:00'" in sql:
            return ["bid_ntce_no"], tie_rows
        return ["bid_ntce_no", "bid_ntce_dt"], rows

    truth = measure.build_truth(_announcement_item(), {}, query_fn=fake_query)
    assert truth["expected_count"] == 5
    assert {"R26BK01789505", "R26BK01789506"} <= truth["allowed"]


def test_latest_truth_tie_numbers_pass_judgment() -> None:
    allowed = [*ALLOWED[:4], "R26BK01789505", "R26BK01789506"]
    answer = ", ".join([*ALLOWED[:4], "R26BK01789505"])
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(allowed, 5), _payload(answer)
    )
    assert result["passed"] is True


def test_repeats_three_passes_with_two_successes() -> None:
    summary = measure.summarize_item(
        _announcement_item(repeats=3),
        [_attempt(True), _attempt(False), _attempt(True)],
    )
    assert summary["threshold"] == 2
    assert summary["verdict"] == "pass"


def test_repeats_three_fails_with_one_success() -> None:
    summary = measure.summarize_item(
        _announcement_item(repeats=3),
        [_attempt(True), _attempt(False), _attempt(False)],
    )
    assert summary["verdict"] == "fail"
    assert summary["failure_reason"] == "data_mismatch"


def test_rate_limit_is_retried_once_then_passes() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_query(sql: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        rows = [(bid_no, "2026-10-23 10:00:00") for bid_no in ALLOWED]
        return ["bid_ntce_no", "bid_ntce_dt"], rows

    def fake_call(base_url: str, question: str, timeout: float) -> dict[str, Any]:
        calls.append(question)
        if len(calls) == 1:
            return {"ok": False, "status": 429, "elapsed_ms": 1.0, "error": "HTTP 429"}
        return _payload(" ".join(ALLOWED))

    record = measure.run_item(
        _announcement_item(),
        {},
        measure.RunConfig(min_interval_sec=0.0),
        measure.CallPacer(0.0),
        query_fn=fake_query,
        call_fn=fake_call,
        sleep_fn=sleeps.append,
    )
    assert record["verdict"] == "pass"
    assert len(calls) == 2
    assert record["attempts"][0]["retried"] is True
    assert sleeps == [measure.RATE_LIMIT_WAIT_SEC]


def test_persistent_rate_limit_is_classified_as_rate_limited() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_query(sql: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        rows = [(bid_no, "2026-10-23 10:00:00") for bid_no in ALLOWED]
        return ["bid_ntce_no", "bid_ntce_dt"], rows

    def fake_call(base_url: str, question: str, timeout: float) -> dict[str, Any]:
        calls.append(1)
        return {"ok": False, "status": 429, "elapsed_ms": 1.0, "error": "HTTP 429"}

    record = measure.run_item(
        _announcement_item(),
        {},
        measure.RunConfig(min_interval_sec=0.0),
        measure.CallPacer(0.0),
        query_fn=fake_query,
        call_fn=fake_call,
        sleep_fn=sleeps.append,
    )
    assert record["verdict"] == "fail"
    assert record["failure_reason"] == "rate_limited"
    assert record["failure_reasons"] == ["rate_limited"]
    assert len(calls) == 2
    assert sleeps == [measure.RATE_LIMIT_WAIT_SEC]


def test_reported_20261024_answer_fails_as_forbidden_phrase_and_routing() -> None:
    answer = (
        "제공된 검색 컨텍스트에는 최근 용역 공고가 1건만 포함되어 있습니다. "
        "따라서 리스트해 드릴 수 없습니다."
    )
    item = _announcement_item(must_not_contain=["리스트해 드릴 수 없", "제공된 검색 컨텍스트에는"])
    result = measure.grade_attempt(
        item,
        _latest_truth(ALLOWED, 5),
        _payload(answer, tools=("semantic_search_tool",)),
    )
    assert result["passed"] is False
    assert "forbidden_phrase" in result["failure_reasons"]
    assert "routing" in result["failure_reasons"]
    assert result["failure_reason"] == "routing"


def test_numeric_fact_accepts_value_within_tolerance() -> None:
    item = {
        "id": "t_num",
        "category": "stats",
        "split": "public",
        "question": "용역 평균 낙찰률 얼마야?",
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {"type": "numeric_fact", "sql": "SELECT 1", "tolerance_ratio": 0.02},
        "must_not_contain": [],
        "repeats": 1,
        "note": "",
    }
    truth = {"kind": "numeric_fact", "value": 90.57, "data_available": True, "error": None}
    result = measure.grade_attempt(item, truth, _payload("평균 낙찰률은 90.6% 입니다."))
    assert result["passed"] is True

    outside = measure.grade_attempt(item, truth, _payload("평균 낙찰률은 80.1% 입니다."))
    assert outside["passed"] is False
    assert "data_mismatch" in outside["failure_reasons"]


def test_bid_lookup_accepts_bid_number_or_title_fragment() -> None:
    item = {
        "id": "t_lookup",
        "category": "bid_lookup",
        "split": "public",
        "question": "이 공고 알려줘",
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {"type": "bid_lookup", "bid_no_placeholder": "latest_servc_result_bid_no"},
        "must_not_contain": [],
        "repeats": 1,
        "note": "",
    }
    truth = {
        "kind": "bid_lookup",
        "bid_no": "R26BK01778156",
        "title": "2026년 공주시 도로정비 공사",
        "data_available": True,
        "error": None,
    }
    by_number = measure.grade_attempt(item, truth, _payload("R26BK01778156 건입니다."))
    by_title = measure.grade_attempt(item, truth, _payload("2026년 공주시 도로정비 공사입니다."))
    missing = measure.grade_attempt(item, truth, _payload("확인했습니다."))
    assert by_number["passed"] is True
    assert by_title["passed"] is True
    assert missing["passed"] is False


def test_out_of_scope_fails_when_bid_number_is_invented() -> None:
    item = {
        "id": "t_oos",
        "category": "out_of_scope",
        "split": "public",
        "question": "오늘 날씨 어때?",
        "expected_tools": [],
        "forbidden_tools": ["bid_query_tool"],
        "check": {"type": "refuse_or_redirect"},
        "must_not_contain": [],
        "repeats": 3,
        "note": "",
    }
    truth = {"kind": "refuse_or_redirect", "data_available": True, "error": None}
    fabricated = measure.grade_attempt(
        item, truth, _payload("관련 공고 R26BK01999999 를 확인했습니다.", tools=())
    )
    redirected = measure.grade_attempt(
        item, truth, _payload("입찰과 무관한 질문이라 답변드리기 어렵습니다.", tools=())
    )
    assert fabricated["passed"] is False
    assert redirected["passed"] is True


def test_dry_run_does_not_call_http_or_db(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry-run 에서는 HTTP 와 DB 를 호출하지 않습니다")

    monkeypatch.setattr(measure, "send_chat", boom)
    monkeypatch.setattr(measure, "run_query", boom)

    exit_code = measure.main(
        [
            "--dry-run",
            "--fixture",
            str(PUBLIC_FIXTURE),
            "--fixture",
            str(BLIND_FIXTURE),
        ]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "선택 문항: 70" in output
