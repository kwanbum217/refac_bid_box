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

from scripts import db_readonly_query
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


@pytest.mark.parametrize("path", [PUBLIC_FIXTURE, BLIND_FIXTURE])
def test_out_of_scope_items_declare_forbidden_claims(path: Path) -> None:
    for item in _load(path)["items"]:
        if item["category"] == "out_of_scope":
            assert item["check"]["type"] == "refuse_or_redirect"
            claims = item.get("forbidden_claims")
            assert isinstance(claims, list)
            assert claims
        else:
            assert "forbidden_claims" not in item


def test_validator_requires_forbidden_claims_for_out_of_scope() -> None:
    item = _refusal_item("오늘 서울 날씨 어때?")
    item.pop("forbidden_claims")
    errors = measure.validate_fixture({"split": "public", "items": [item]}, "public", "x")
    assert any("forbidden_claims" in error for error in errors)


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


def test_announcement_latest_fails_when_outside_number() -> None:
    item = _announcement_item()
    answer = ", ".join([*ALLOWED[:4], "R26BK01999999"])
    result = measure.grade_attempt(item, _latest_truth(ALLOWED, 5), _payload(answer))
    assert result["passed"] is False
    assert result["detail"]["outside_allowed"] == ["R26BK01999999"]


def test_principle1_latest_passes_with_absence_phrase() -> None:
    # 원칙 1 (정답 우선): 정답 5건이 모두 있으면 "데이터가 확인되지 않습니다" 가
    # 붙어도 통과다. 부재 문구는 정답이 답변에 없을 때만 실패 근거다.
    answer = ", ".join(ALLOWED) + " 다만 데이터가 확인되지 않습니다."
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(answer)
    )
    assert result["passed"] is True
    assert result["failure_reasons"] == []
    assert result["detail"]["detected_count"] == 5
    assert result["detail"]["absence_phrases"] == ["확인되지 않"]
    assert result["detail"]["absence_ignored"] is True


def test_principle1_announcement_latest_fails_when_numbers_missing_with_absence_phrase() -> None:
    # 원칙 1: 정답이 답변에 없으면 부재 문구와 무관하게 실패다.
    answer = ", ".join(ALLOWED[:4]) + " 나머지는 확인되지 않습니다."
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(answer)
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["detected_count"] == 4


def test_principle1_result_latest_passes_when_top_numbers_present_with_absence_phrase() -> None:
    item = {
        "id": "t_res",
        "category": "result_analysis",
        "split": "public",
        "question": "최근 용역 낙찰 5건 보여줘",
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {"type": "result_latest", "category": "Servc", "limit": 5, "days": 7},
        "must_not_contain": [],
        "repeats": 1,
        "note": "",
    }
    truth = {
        "kind": "result_latest",
        "allowed": set(ALLOWED),
        "expected_count": 5,
        "data_available": True,
        "window_fallback": False,
        "error": None,
    }
    answer = ", ".join(ALLOWED) + " 다만 데이터가 확인되지 않습니다."
    result = measure.grade_attempt(item, truth, _payload(answer))
    assert result["passed"] is True
    assert result["failure_reasons"] == []
    assert result["detail"]["detected_count"] == 5
    assert result["detail"]["absence_ignored"] is True


def test_announcement_latest_still_allows_numbers_when_phrase_is_absent() -> None:
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(", ".join(ALLOWED))
    )
    assert result["passed"] is True
    assert result["detail"]["absence_phrases"] == []


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


def _bid_lookup_item() -> dict[str, Any]:
    return {
        "id": "t_lookup",
        "category": "bid_lookup",
        "split": "public",
        "question": "{latest_servc_result_bid_no} 이 공고 알려줘",
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {"type": "bid_lookup", "bid_no_placeholder": "latest_servc_result_bid_no"},
        "must_not_contain": [],
        "repeats": 1,
        "note": "",
    }


def _bid_lookup_truth() -> dict[str, Any]:
    return {
        "kind": "bid_lookup",
        "bid_no": "R26BK01778156",
        "title": "2026년 공주시 도로정비 공사",
        "winner": "대성건설 주식회사",
        "amount": 123456789,
        "data_available": True,
        "error": None,
    }


def test_principle3_bid_lookup_fails_when_only_bid_number_is_repeated() -> None:
    # 원칙 3: 질문에 나온 공고번호를 답변에서 지운 뒤 판정한다. 번호를 되풀이한
    # 것만으로는 통과하지 못한다.
    result = measure.grade_attempt(
        _bid_lookup_item(), _bid_lookup_truth(), _payload("R26BK01778156 건입니다.")
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["removed_bid_numbers"] == ["R26BK01778156"]
    assert result["detail"]["title_found"] is False


def test_principle3_bid_lookup_passes_on_title_prefix() -> None:
    result = measure.grade_attempt(
        _bid_lookup_item(), _bid_lookup_truth(), _payload("2026년 공주시 도로정비 공사입니다.")
    )
    assert result["passed"] is True
    assert result["detail"]["title_found"] is True


def test_principle3_bid_lookup_passes_on_winner_name() -> None:
    result = measure.grade_attempt(
        _bid_lookup_item(),
        _bid_lookup_truth(),
        _payload("R26BK01778156 은 대성건설 주식회사가 낙찰받았습니다."),
    )
    assert result["passed"] is True
    assert result["detail"]["winner_found"] is True


def test_principle3_bid_lookup_passes_on_amount() -> None:
    result = measure.grade_attempt(
        _bid_lookup_item(),
        _bid_lookup_truth(),
        _payload("R26BK01778156 낙찰금액은 123,456,789원입니다."),
    )
    assert result["passed"] is True
    assert result["detail"]["amount_found"] is True


def test_principle3_bid_lookup_fails_when_result_not_found_phrase() -> None:
    # 리뷰어 반례 (C): 공고번호가 맞아도 DB 내용이 없으면 실패다.
    result = measure.grade_attempt(
        _bid_lookup_item(),
        _bid_lookup_truth(),
        _payload("R26BK01778156 공고의 낙찰 결과는 조회되지 않습니다."),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["title_found"] is False
    assert result["detail"]["absence_phrases"] == ["조회되지 않"]


def test_principle3_truth_collects_title_winner_and_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_run_query(statement: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        seen.append(statement)
        if "bid_results" in statement:
            return ["bid_ntce_nm", "bidwinnr_nm", "sucsf_bid_amt"], [
                ("2026년 공주시 도로정비 공사", "대성건설 주식회사", 123456789)
            ]
        return ["bid_ntce_nm"], [("2026년 공주시 도로정비 공사",)]

    monkeypatch.setattr(measure, "run_query", fake_run_query)
    truth = measure.build_truth(_bid_lookup_item(), {"latest_servc_result_bid_no": "R26BK01778156"})
    assert truth["title"] == "2026년 공주시 도로정비 공사"
    assert truth["winner"] == "대성건설 주식회사"
    assert truth["amount"] == 123456789
    assert len(seen) == 2
    assert all(statement.startswith("SELECT") for statement in seen)


def _empty_latest_truth() -> dict[str, Any]:
    return _latest_truth([], 0, data_available=False)


def test_principle2_zero_count_passes_on_zero_phrase() -> None:
    # 원칙 2: DB 정답이 0건이면 0건 표현만 있고 목록이 없어야 통과다.
    result = measure.grade_attempt(
        _announcement_item(), _empty_latest_truth(), _payload("최근 7일 내 용역 공고는 0건입니다.")
    )
    assert result["passed"] is True
    assert result["detail"]["db_empty"] is True
    assert result["detail"]["zero_count_phrases"] == ["0건"]


def test_principle2_zero_count_passes_on_none_word() -> None:
    result = measure.grade_attempt(
        _announcement_item(), _empty_latest_truth(), _payload("해당 조건의 공고는 없음")
    )
    assert result["passed"] is True


def test_principle2_zero_count_fails_on_reviewer_comma_list_counterexample() -> None:
    # 리뷰어 반례: 목록 행이 없어도 쉼표로 공사명을 늘어놓으면 실패다.
    answer = "공주시 최근 공고 목록입니다: 공주시 상수도 정비 공사, 공주시 도로 포장 공사."
    result = measure.grade_attempt(_announcement_item(), _empty_latest_truth(), _payload(answer))
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert len(result["detail"]["announcement_name_word_hits"]) >= 2
    assert result["detail"]["list_row_count"] == 0


def test_principle2_zero_count_fails_when_bid_number_present() -> None:
    answer = "0건입니다. 다만 R26BK01789522 는 있습니다."
    result = measure.grade_attempt(_announcement_item(), _empty_latest_truth(), _payload(answer))
    assert result["passed"] is False
    assert result["detail"]["detected_bid_numbers"] == ["R26BK01789522"]


def test_principle2_zero_count_fails_on_list_rows() -> None:
    answer = "0건입니다.\n- 공주시 상수도 정비 공사"
    result = measure.grade_attempt(_announcement_item(), _empty_latest_truth(), _payload(answer))
    assert result["passed"] is False
    assert result["detail"]["list_row_count"] == 1


def test_principle2_zero_count_fails_on_table_row() -> None:
    answer = "0건입니다.\n| 공고번호 | 공고명 |\n|---|---|"
    result = measure.grade_attempt(_announcement_item(), _empty_latest_truth(), _payload(answer))
    assert result["passed"] is False
    assert result["detail"]["list_row_count"] == 1


def test_principle2_zero_count_fails_without_zero_phrase() -> None:
    result = measure.grade_attempt(
        _announcement_item(), _empty_latest_truth(), _payload("확인했습니다. 목록은 비어 있습니다.")
    )
    assert result["passed"] is False
    assert result["detail"]["zero_count_phrases"] == []


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


def _numeric_item(question: str, tolerance_ratio: float = 0.02) -> dict[str, Any]:
    return {
        "id": "t_num",
        "category": "stats",
        "split": "public",
        "question": question,
        "expected_tools": ["bid_query_tool"],
        "forbidden_tools": [],
        "check": {
            "type": "numeric_fact",
            "sql": "SELECT COUNT(*) FROM bid_results",
            "tolerance_ratio": tolerance_ratio,
        },
        "must_not_contain": [],
        "repeats": 1,
        "note": "",
    }


def _refusal_item(question: str, forbidden_claims: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": "t_oos",
        "category": "out_of_scope",
        "split": "public",
        "question": question,
        "expected_tools": [],
        "forbidden_tools": ["bid_query_tool"],
        "check": {"type": "refuse_or_redirect"},
        "must_not_contain": [],
        "forbidden_claims": list(forbidden_claims or []),
        "repeats": 3,
        "note": "",
    }


def _refusal_truth() -> dict[str, Any]:
    return {"kind": "refuse_or_redirect", "data_available": True, "error": None}


WEATHER_CLAIMS = ["맑", "흐리", "비가", "눈이", "기온", "습도", "도입니다", "℃"]


def _numeric_truth(value: float) -> dict[str, Any]:
    return {"kind": "numeric_fact", "value": value, "data_available": True, "error": None}


def test_numeric_fact_subtracts_numbers_that_came_from_question() -> None:
    question = "최근 30일 용역 낙찰 몇 건이야?"
    result = measure.grade_attempt(
        _numeric_item(question),
        _numeric_truth(3405.0),
        _payload("최근 30일 기준 낙찰 건수는 3,405건입니다."),
    )
    assert result["passed"] is True
    assert result["detail"]["question_numbers"] == [30.0]
    assert result["detail"]["candidate_numbers"] == [3405.0]


def test_numeric_fact_fails_on_reviewer_repeated_period_counterexample() -> None:
    # 원칙 1: 질문의 "30일" 을 되풀이한 답은 정답 수치가 아니다. 질문 숫자를 빼면
    # 후보가 비고, DB 값 30 이 답변에 없는 것과 같으므로 실패다.
    question = "최근 30일 용역 낙찰 몇 건이야?"
    result = measure.grade_attempt(
        _numeric_item(question),
        _numeric_truth(30.0),
        _payload("최근 30일 기준 낙찰 건수는 확인되지 않습니다."),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["candidate_numbers"] == []
    assert result["detail"]["absence_phrases"] == ["확인되지 않"]


def test_principle1_numeric_fact_passes_when_value_present_with_absence_phrase() -> None:
    # 원칙 1: DB 값 3405 가 답변에 있으면 "제공할 수 없습니다" 가 함께 있어도
    # 통과다. 리뷰어 예시 "123건입니다. 취소된 건은 없습니다." 와 같은 규칙이다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 총 몇 건이야?"),
        _numeric_truth(3405.0),
        _payload("3,405건은 제공할 수 없습니다."),
    )
    assert result["passed"] is True
    assert result["detail"]["candidate_numbers"] == [3405.0]
    assert result["detail"]["absence_phrases"] == ["없습니다", "제공할 수 없"]
    assert result["detail"]["absence_ignored"] is True


def test_principle1_numeric_fact_passes_on_123_with_cancelled_zero() -> None:
    # 원칙 1 예시 그대로: 123건입니다. 취소된 건은 없습니다. 는 통과다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(123.0),
        _payload("123건입니다. 취소된 건은 없습니다."),
    )
    assert result["passed"] is True
    assert result["detail"]["matched_number"] == 123.0


def test_principle1_numeric_fact_fails_when_answer_has_no_value() -> None:
    # 원칙 1: 정답 수치가 없으면 부재 문구만으로는 통과할 수 없다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(123.0),
        _payload("확인되지 않습니다."),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["candidate_numbers"] == []


def test_numeric_fact_ignores_dates_times_and_bid_numbers() -> None:
    answer = "2026-10-24 09:30 기준 R26BK01789522 관련 낙찰은 3,405건입니다."
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(3405.0),
        _payload(answer),
    )
    assert result["passed"] is True
    assert result["detail"]["answer_numbers_sample"] == [3405.0]


def test_numeric_fact_rejects_year_month_numbers_as_value() -> None:
    # 반려 사유 그대로: DB 값 10, 답변 "2026년 10월 기준 집계가 없습니다" 는
    # 실패다. "2026년" 과 "10월" 의 수는 기간 표기이므로 대조 후보가 아니다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(10.0),
        _payload("2026년 10월 기준 집계가 없습니다"),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["answer_numbers_sample"] == []
    assert result["detail"]["candidate_numbers"] == []


def test_numeric_fact_counts_value_written_next_to_year_month_label() -> None:
    # 같은 기간 표기가 있어도 바로 뒤에 "건" 이 붙은 10 은 집계 값이므로 통과다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(10.0),
        _payload("2026년 10월 낙찰은 10건입니다"),
    )
    assert result["passed"] is True
    assert result["failure_reasons"] == []
    assert result["detail"]["candidate_numbers"] == [10.0]


def test_numeric_fact_rejects_quarter_numbers_as_value() -> None:
    # DB 값 3, 답변 "3분기 기준 확인되지 않습니다" 는 실패다.
    result = measure.grade_attempt(
        _numeric_item("이번 분기 용역 낙찰 몇 건이야?"),
        _numeric_truth(3.0),
        _payload("3분기 기준 확인되지 않습니다"),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["candidate_numbers"] == []


def test_numeric_fact_counts_rate_beside_date_in_parentheses() -> None:
    # DB 값 88.12, 답변 "평균 낙찰률은 88.12% 입니다(2026-10-24 기준)" 는 통과다.
    result = measure.grade_attempt(
        _numeric_item("용역 평균 낙찰률 얼마야?"),
        _numeric_truth(88.12),
        _payload("평균 낙찰률은 88.12% 입니다(2026-10-24 기준)"),
    )
    assert result["passed"] is True
    assert result["failure_reasons"] == []
    assert result["detail"]["candidate_numbers"] == [88.12]


@pytest.mark.parametrize(
    "unit",
    ["년", "월", "일", "시", "분", "초", "분기", "주", "개월", "차"],
)
def test_numeric_fact_excludes_number_followed_by_period_unit(unit: str) -> None:
    # 바로 뒤에 년/월/일/시/분/초/분기/주/개월/차 가 붙은 수는 기간 표기다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(3.0),
        _payload(f"3{unit} 기준 집계가 없습니다"),
    )
    assert result["passed"] is False
    assert result["detail"]["candidate_numbers"] == []


@pytest.mark.parametrize(
    "answer",
    [
        "2026-10-24 기준 집계가 없습니다",
        "2026.10.24 기준 집계가 없습니다",
        "09:30 기준 집계가 없습니다",
    ],
)
def test_numeric_fact_excludes_date_and_time_format_numbers(answer: str) -> None:
    # YYYY-MM-DD, YYYY.MM.DD, HH:MM 안의 수는 대조 후보에서 뺀다.
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(10.0),
        _payload(answer),
    )
    assert result["passed"] is False
    assert result["detail"]["candidate_numbers"] == []


def test_numeric_fact_question_numbers_are_still_subtracted() -> None:
    # 원칙 1 의 질문 숫자 제거는 그대로다. 답변이 질문의 "30일" 을 되풀이해도
    # 기간 표기 마스크와 무관하게 후보에 남지 않는다.
    result = measure.grade_attempt(
        _numeric_item("최근 30일 용역 낙찰 몇 건이야?"),
        _numeric_truth(3405.0),
        _payload("최근 30일 기준 낙찰은 3,405건입니다"),
    )
    assert result["passed"] is True
    assert result["detail"]["question_numbers"] == [30.0]
    assert result["detail"]["candidate_numbers"] == [3405.0]


def test_refuse_or_redirect_fails_on_reviewer_weather_counterexample() -> None:
    result = measure.grade_attempt(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS),
        _refusal_truth(),
        _payload("오늘 서울은 맑고 기온은 21도입니다.", tools=()),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["domain_terms"] == []
    assert result["detail"]["forbidden_claim_hits"] == ["맑", "기온", "도입니다"]


def test_refuse_or_redirect_passes_with_domain_term_and_marker() -> None:
    answer = "저는 입찰 공고와 낙찰 정보를 안내합니다. 날씨 질문은 답변드리기 어렵습니다."
    result = measure.grade_attempt(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is True
    assert result["detail"]["domain_terms"] == ["입찰", "공고", "낙찰"]
    assert result["detail"]["forbidden_claim_hits"] == []


def test_refuse_or_redirect_passes_with_marker_only() -> None:
    answer = "죄송합니다. 그 질문은 답변드리기 어렵습니다."
    result = measure.grade_attempt(
        _refusal_item("내일 점심 뭐 먹을까?", ["김치찌개", "비빔밥", "식당", "맛집"]),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is True
    assert result["detail"]["domain_terms"] == []
    assert result["detail"]["redirect_markers"] == ["답변드리기 어렵"]


def test_refuse_or_redirect_fails_when_fact_is_asserted_alongside_redirect() -> None:
    answer = "입찰 공고 범위는 안내하지만 오늘 서울은 맑고 기온은 21도입니다."
    result = measure.grade_attempt(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is False
    assert result["detail"]["domain_terms"]
    assert result["detail"]["forbidden_claim_hits"]


def test_refuse_or_redirect_fails_on_domain_answer_with_weather_claim() -> None:
    # 리뷰어 반례: 업무 표지와 안내 표지가 모두 있어도 범위 밖 사실을 단정하면 실패다.
    answer = "입찰 공고 범위 밖 질문이지만 오늘 서울은 맑습니다."
    result = measure.grade_attempt(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is False
    assert result["detail"]["domain_terms"]
    assert result["detail"]["redirect_markers"] == ["범위"]
    assert result["detail"]["forbidden_claim_hits"] == ["맑"]


def test_refuse_or_redirect_passes_on_greeting_self_introduction() -> None:
    # 과엄격 반례: 인사에 자기소개로 답한 경우는 통과해야 한다.
    answer = "안녕하세요, 저는 입찰 공고 정보를 안내하는 챗봇입니다. 무엇을 도와드릴까요?"
    result = measure.grade_attempt(
        _refusal_item("안녕하세요, 너는 누구야?", ["GPT", "언어 모델", "학습 데이터", "파라미터"]),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is True
    assert result["detail"]["forbidden_claim_hits"] == []
    assert "도와드릴" in result["detail"]["redirect_markers"]


STOCK_CLAIMS = ["코스피", "코스닥", "주가", "지수", "상승", "하락", "매수", "매도"]


def test_principle4_out_of_scope_records_heuristic_flag() -> None:
    # 원칙 4: 범위 밖 판정은 낱말 기반 근사이므로 결과 JSON 에 표시를 남긴다.
    summary = measure.summarize_item(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS), [_attempt(True)]
    )
    assert summary["heuristic"] is True


def test_principle4_non_out_of_scope_has_no_heuristic_flag() -> None:
    summary = measure.summarize_item(_announcement_item(), [_attempt(True)])
    assert "heuristic" not in summary


def test_summary_table_notes_out_of_scope_heuristic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    measure.print_summary_table({"out_of_scope": {"passed": 1, "total": 2, "pass_rate": 0.5}})
    output = capsys.readouterr().out
    assert "낱말 기반 근사" in output
    assert "heuristic: true" in output


@pytest.mark.xfail(
    strict=True,
    reason="낱말 기반 범위 밖 판정의 알려진 한계, 코디네이터 수동 확정",
)
def test_principle4_known_limit_weather_news_slips_through() -> None:
    # 리뷰어 반례 (1-a). "비가" 가 아니라 "비 소식" 이라 낱말 목록을 피했고
    # 업무 표지가 있어 현재 규칙에서는 통과로 샌다. 이상적 판정은 실패다.
    answer = "오늘 서울은 비 소식이 있습니다. 입찰 공고 범위 밖이라 안내는 어렵습니다."
    result = measure.grade_attempt(
        _refusal_item("오늘 서울 날씨 어때?", WEATHER_CLAIMS),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is False


@pytest.mark.xfail(
    strict=True,
    reason="낱말 기반 범위 밖 판정의 알려진 한계, 코디네이터 수동 확정",
)
def test_principle4_known_limit_stock_forecast_slips_through() -> None:
    # 리뷰어 반례 (1-b). "전망", "호황" 이 낱말 목록에 없어 주식 전망을 단정한
    # 답이 통과로 샌다. 이상적 판정은 실패다.
    answer = "내년에는 반도체 호황이 이어질 전망입니다. 다만 입찰 공고 안내는 도와드릴 수 있습니다."
    result = measure.grade_attempt(
        _refusal_item("주식 시장 전망 알려줘", STOCK_CLAIMS),
        _refusal_truth(),
        _payload(answer, tools=()),
    )
    assert result["passed"] is False


def test_assert_read_only_is_the_shared_db_tool_object() -> None:
    # 측정기는 읽기 전용 검사기를 복사하지 않고 공용 도구에서 import 해 쓴다.
    # 사본을 두면 공용 도구의 결함 수정이 측정기에 반영되지 않는다.
    assert measure.assert_read_only is db_readonly_query.assert_read_only


def test_assert_read_only_accepts_select_and_rejects_writes() -> None:
    assert measure.assert_read_only("SELECT 1") == "SELECT 1"
    assert measure.assert_read_only("WITH t AS (SELECT 1) SELECT * FROM t").startswith("WITH")
    unsafe = (
        "DELETE FROM bid_results",
        "UPDATE bid_results SET bidwinnr_nm = 'x'",
        "SELECT 1; DROP TABLE bid_results",
        "SELECT * FROM bid_results INTO OUTFILE '/tmp/x'",
        "",
    )
    for statement in unsafe:
        with pytest.raises(measure.UnsafeQueryError):
            measure.assert_read_only(statement)


def test_db_write_never_reaches_run_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run_query(statement: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        seen.append(statement)
        return [], []

    monkeypatch.setattr(measure, "run_query", fake_run_query)
    item = _numeric_item("이번 달 용역 낙찰 몇 건이야?")
    item["check"]["sql"] = "DELETE FROM bid_results"
    truth = measure.build_truth(item, {})
    assert seen == []
    assert truth["data_available"] is False
    assert "읽기 전용" in str(truth["error"])


def test_db_read_reaches_run_query_only_after_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run_query(statement: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        seen.append(statement)
        return ["count"], [(3405,)]

    monkeypatch.setattr(measure, "run_query", fake_run_query)
    truth = measure.build_truth(_numeric_item("이번 달 용역 낙찰 몇 건이야?"), {})
    assert truth["value"] == 3405.0
    assert seen == ["SELECT COUNT(*) FROM bid_results"]


def test_placeholder_resolution_passes_read_only_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    guarded: list[str] = []
    original = measure.assert_read_only

    def spy(statement: str) -> str:
        guarded.append(statement)
        return original(statement)

    def fake_run_query(statement: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
        return ["bid_ntce_no"], [("R26BK01778156",)]

    monkeypatch.setattr(measure, "assert_read_only", spy)
    monkeypatch.setattr(measure, "run_query", fake_run_query)
    values, errors = measure.resolve_placeholders({"latest_servc_result_bid_no"})
    assert errors == {}
    assert values["latest_servc_result_bid_no"] == "R26BK01778156"
    assert guarded
    assert guarded[0].startswith("SELECT")


ATTACHED_BID_NO = "R26BK01775039"


@pytest.mark.parametrize(
    "text",
    [
        "R26BK01775039입니다",
        "R26BK01775039은 낙찰",
        "R26BK01775039번",
        "| R26BK01775039 |",
        "(R26BK01775039-000)",
        "공고번호:R26BK01775039",
    ],
)
def test_bid_number_pattern_accepts_attached_particles_and_delimiters(text: str) -> None:
    # \b 는 한글을 단어 문자로 보므로 조사가 붙은 번호를 놓친다. ASCII 둘러보기는
    # 뒤에 조사, 차수(-000), 공백, |, 괄호가 와도 번호를 잡는다.
    assert measure.extract_bid_numbers(text) == {ATTACHED_BID_NO}


@pytest.mark.parametrize(
    "text",
    [
        "XR26BK01775039",
        "R26BK017750391234567",
    ],
)
def test_bid_number_pattern_rejects_letters_or_longer_digits(text: str) -> None:
    # 앞에 영숫자가 붙거나 숫자가 10자리를 넘으면 공고번호가 아니다.
    assert measure.extract_bid_numbers(text) == set()


def test_attached_bid_number_no_longer_passes_zero_count_announcement_latest() -> None:
    # 리뷰어 재현 1: 답변이 붙여 쓴 공고번호를 담았는데 이전 \b 패턴이 이를 놓쳐
    # 0건 판정과 announcement_latest 판정이 모두 통과했다. 지금은 번호를 인식해
    # data_mismatch 로 실패해야 한다.
    answer = "최근 7일 용역 공고는 0건입니다. 참고로 R26BK01789522은 다른 유형입니다."
    result = measure.grade_attempt(_announcement_item(), _empty_latest_truth(), _payload(answer))
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["db_empty"] is True
    assert result["detail"]["zero_count_phrases"] == ["0건"]
    assert result["detail"]["detected_bid_numbers"] == ["R26BK01789522"]


def test_attached_fabricated_bid_number_no_longer_passes_announcement_latest() -> None:
    # 같은 원인의 다른 증상: 정답 5건을 담은 답에 붙여 쓴 다른 번호가 섞여도
    # 이전 패턴은 이를 놓쳐 통과시켰다. 지금은 허용 집합 밖 번호로 실패한다.
    answer = ", ".join([*ALLOWED, "R26BK01999999입니다"])
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(answer)
    )
    assert result["passed"] is False
    assert result["detail"]["detected_count"] == 6
    assert result["detail"]["outside_allowed"] == ["R26BK01999999"]


def test_attached_bid_numbers_no_longer_drop_a_correct_answer() -> None:
    # 리뷰어 재현 2: 정답 5건을 조사와 붙여 쓴 정상 답이 이전 \b 패턴에서는 0건으로
    # 보여 실패했다. 지금은 5건 모두 인식해 통과해야 한다.
    answer = ", ".join(f"{bid_no}입니다" for bid_no in ALLOWED)
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(answer)
    )
    assert result["passed"] is True
    assert result["failure_reasons"] == []
    assert result["detail"]["detected_count"] == 5
    assert result["detail"]["outside_allowed"] == []


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
