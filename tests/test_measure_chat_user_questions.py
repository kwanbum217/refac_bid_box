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


def test_announcement_latest_fails_when_correct_numbers_carry_absence_phrase() -> None:
    # 리뷰어 반례 (D): 정답 5건 뒤에 "데이터가 확인되지 않습니다" 를 붙이면 실패다.
    answer = ", ".join(ALLOWED) + " 다만 데이터가 확인되지 않습니다."
    result = measure.grade_attempt(
        _announcement_item(), _latest_truth(ALLOWED, 5), _payload(answer)
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["detected_count"] == 5
    assert result["detail"]["data_absent_claimed"] is True
    assert result["detail"]["absence_phrases"] == ["확인되지 않"]


def test_result_latest_fails_when_correct_numbers_carry_absence_phrase() -> None:
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
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["detected_count"] == 5
    assert result["detail"]["data_absent_claimed"] is True


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


def test_bid_lookup_fails_when_number_present_but_result_not_found() -> None:
    # 리뷰어 반례 (C): 공고번호가 맞아도 "낙찰 결과는 조회되지 않습니다" 면 실패다.
    item = {
        "id": "t_lookup",
        "category": "bid_lookup",
        "split": "public",
        "question": "{latest_servc_result_bid_no} 이 공고 낙찰 결과 알려줘",
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
    result = measure.grade_attempt(
        item, truth, _payload("R26BK01778156 공고의 낙찰 결과는 조회되지 않습니다.")
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["bid_no_found"] is True
    assert result["detail"]["data_absent_claimed"] is True
    assert result["detail"]["absence_phrases"] == ["조회되지 않"]


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
    question = "최근 30일 용역 낙찰 몇 건이야?"
    result = measure.grade_attempt(
        _numeric_item(question),
        _numeric_truth(30.0),
        _payload("최근 30일 기준 낙찰 건수는 확인되지 않습니다."),
    )
    assert result["passed"] is False
    assert "data_mismatch" in result["failure_reasons"]
    assert result["detail"]["data_absent_claimed"] is True
    assert result["detail"]["candidate_numbers"] == []


def test_numeric_fact_fails_when_absence_phrase_even_with_matching_number() -> None:
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 총 몇 건이야?"),
        _numeric_truth(3405.0),
        _payload("3,405건은 제공할 수 없습니다."),
    )
    assert result["passed"] is False
    assert result["detail"]["candidate_numbers"] == [3405.0]
    assert result["detail"]["absence_phrases"] == ["없습니다", "제공할 수 없"]


def test_numeric_fact_ignores_dates_times_and_bid_numbers() -> None:
    answer = "2026-10-24 09:30 기준 R26BK01789522 관련 낙찰은 3,405건입니다."
    result = measure.grade_attempt(
        _numeric_item("이번 달 용역 낙찰 몇 건이야?"),
        _numeric_truth(3405.0),
        _payload(answer),
    )
    assert result["passed"] is True
    assert result["detail"]["answer_numbers_sample"] == [3405.0]


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
