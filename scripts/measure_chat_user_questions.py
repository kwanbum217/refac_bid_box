"""챗봇 사용자 질문 점검 측정기.

실제 사용자가 묻는 형태의 질문을 운영 챗봇 경로(`POST /api/v1/chatbot/chat`)로
보내고, 응답을 **실행 시점 DB 정답**과 기계적으로 대조한다. 정답을 fixture 에
고정하지 않는 이유는 데이터가 매일 바뀌기 때문이다. 판정에 쓰는 기준은 다음과
같다.

- 도구 선택: `plan_steps` 의 `tool` 목록에 `expected_tools` 가 모두 있고
  `forbidden_tools` 가 없어야 한다.
- 데이터 정합: 응답의 공고번호/수치를 측정 시점 DB 조회 결과와 비교한다.
- 금지 문구: 데이터가 있는데도 "리스트해 드릴 수 없습니다" 같은 문구가 나오면
  실패다.
- 반복: LLM 을 거치는 문항은 3회 중 2회 이상 통과해야 통과로 본다.

호출 한도와 정답 계산:

- 익명 한도는 60초당 30회이므로 호출 사이 최소 간격을 둔다(기본 2.5초).
- HTTP 429 는 60초 기다린 뒤 한 번만 재시도하고, 그래도 429 면 그 문항을
  `rate_limited` 로 기록한다. 429 를 라우팅 실패로 세지 않는다.
- DB 정답은 `scripts/db_readonly_query.run_query(statement, limit)` 만 사용한다.
  이 함수는 SELECT 단일 문장만 받고 READ ONLY 트랜잭션으로 실행한다.

사용 예:

    uv run python scripts/measure_chat_user_questions.py --dry-run \
        --fixture data/benchmarks/chat_user_questions_v1.json \
        --fixture data/benchmarks/chat_user_questions_blind_v1.json

    uv run python scripts/measure_chat_user_questions.py \
        --base-url http://localhost:8000 \
        --out .cache/chat_user_questions_20261024.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - git SHA 조회용으로만 쓴다
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.db_readonly_query import run_query
except ModuleNotFoundError:  # pragma: no cover - scripts 디렉터리에서 직접 실행하는 경로
    from db_readonly_query import run_query  # type: ignore[no-redef]

QueryFn = Callable[[str, int], tuple[list[str], list[tuple[Any, ...]]]]

DEFAULT_BASE_URL = "http://localhost:8000"
CHAT_PATH = "/api/v1/chatbot/chat"
DEFAULT_PUBLIC_FIXTURE = Path("data/benchmarks/chat_user_questions_v1.json")
DEFAULT_BLIND_FIXTURE = Path("data/benchmarks/chat_user_questions_blind_v1.json")
DEFAULT_MIN_INTERVAL_SEC = 2.5
DEFAULT_TIMEOUT_SEC = 180.0
DEFAULT_OUT_DIR = Path(".cache")
RATE_LIMIT_WAIT_SEC = 60.0

CATEGORIES = (
    "announcement_list",
    "result_analysis",
    "bid_lookup",
    "stats",
    "prediction",
    "out_of_scope",
)
CATEGORY_CODES = ("Servc", "Cnstwk", "Thng", "Frgcpt")
CHECK_TYPES = (
    "announcement_latest",
    "result_latest",
    "numeric_fact",
    "bid_lookup",
    "refuse_or_redirect",
    "tool_only",
)
SPLITS = ("public", "blind")
FAILURE_PRIORITY = ("routing", "forbidden_phrase", "data_mismatch", "error", "rate_limited")

LATEST_CHECKS = {
    "announcement_latest": ("bid_announcements", "bid_ntce_dt"),
    "result_latest": ("bid_results", "rl_openg_dt"),
}
INSTITUTION_COLUMNS = {
    "bid_announcements": ("dminstt_nm", "ntce_instt_nm"),
    "bid_results": ("dminstt_nm",),
}

# 실제 공고번호 형식은 R26BK01789522 이다. 금액(순수 숫자)과 구분하려고
# 문자 접두를 요구한다.
BID_NO_PATTERN = re.compile(r"\b[A-Za-z]\d{2}[A-Za-z]{2}\d{6,10}\b")
FABRICATED_NUMBER_PATTERN = re.compile(r"\d{8,}")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# 특정 공고번호가 필요한 문항은 번호를 박지 않고 placeholder 로 둔다.
PLACEHOLDER_QUERIES: dict[str, str] = {
    "latest_servc_result_bid_no": (
        "SELECT bid_ntce_no FROM bid_results "
        "WHERE category = 'Servc' AND rl_openg_dt IS NOT NULL "
        "ORDER BY rl_openg_dt DESC, id DESC LIMIT 1"
    ),
    "latest_cnstwk_result_bid_no": (
        "SELECT bid_ntce_no FROM bid_results "
        "WHERE category = 'Cnstwk' AND rl_openg_dt IS NOT NULL "
        "ORDER BY rl_openg_dt DESC, id DESC LIMIT 1"
    ),
    "latest_servc_announcement_bid_no": (
        "SELECT bid_ntce_no FROM bid_announcements "
        "WHERE category = 'Servc' AND bid_ntce_dt IS NOT NULL "
        "ORDER BY bid_ntce_dt DESC, id DESC LIMIT 1"
    ),
    "latest_cnstwk_announcement_bid_no": (
        "SELECT bid_ntce_no FROM bid_announcements "
        "WHERE category = 'Cnstwk' AND bid_ntce_dt IS NOT NULL "
        "ORDER BY bid_ntce_dt DESC, id DESC LIMIT 1"
    ),
    "latest_servc_result_institution": (
        "SELECT dminstt_nm FROM bid_results "
        "WHERE category = 'Servc' AND rl_openg_dt IS NOT NULL "
        "AND dminstt_nm IS NOT NULL AND dminstt_nm <> '' "
        "ORDER BY rl_openg_dt DESC, id DESC LIMIT 1"
    ),
}


class FixtureError(ValueError):
    """fixture 스키마가 계약과 다를 때 냅니다."""


@dataclass(frozen=True)
class RunConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC


def fill_placeholders(text: str, placeholders: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return placeholders.get(name, match.group(0))

    return PLACEHOLDER_PATTERN.sub(_replace, text)


def collect_placeholders(item: dict[str, Any]) -> set[str]:
    names = set(PLACEHOLDER_PATTERN.findall(str(item.get("question") or "")))
    check = item.get("check") or {}
    if isinstance(check.get("sql"), str):
        names.update(PLACEHOLDER_PATTERN.findall(check["sql"]))
    placeholder = check.get("bid_no_placeholder")
    if isinstance(placeholder, str) and placeholder:
        names.add(placeholder)
    return names


def resolve_placeholders(
    names: set[str], query_fn: QueryFn | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """placeholder 를 실행 시점 DB 값으로 채운다. 값이 없으면 missing 에 남긴다."""
    query = query_fn or run_query
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in sorted(names):
        statement = PLACEHOLDER_QUERIES.get(name)
        if statement is None:
            errors[name] = "등록되지 않은 placeholder"
            continue
        try:
            _, rows = query(statement, 1)
        except Exception as exc:
            errors[name] = str(exc)
            continue
        value = str(rows[0][0]) if rows and rows[0][0] is not None else ""
        if value:
            values[name] = value
        else:
            errors[name] = "DB 조회 결과 없음"
    return values, errors


def extract_tools(payload: dict[str, Any]) -> list[str]:
    tools: list[str] = []
    steps = payload.get("plan_steps")
    if not isinstance(steps, list):
        return tools
    for step in steps:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if isinstance(tool, str) and tool:
            tools.append(tool)
    return tools


def extract_bid_numbers(text: str) -> set[str]:
    return {match.upper() for match in BID_NO_PATTERN.findall(text or "")}


def extract_numbers(text: str) -> list[float]:
    normalized = re.sub(r"(?<=\d),(?=\d)", "", text or "")
    numbers: list[float] = []
    for token in NUMBER_PATTERN.findall(normalized):
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    return numbers


def _latest_rows(
    dataset: str,
    date_column: str,
    check: dict[str, Any],
    query: QueryFn,
) -> tuple[list[tuple[Any, ...]], bool]:
    conditions: list[str] = [f"{date_column} IS NOT NULL"]
    category = check.get("category")
    if category:
        conditions.append(f"category = '{category}'")
    institution_like = check.get("institution_like")
    if institution_like:
        columns = INSTITUTION_COLUMNS[dataset]
        like_parts = [f"{column} LIKE '%{institution_like}%'" for column in columns]
        conditions.append(f"({' OR '.join(like_parts)})")
    where = " AND ".join(conditions)
    limit = int(check.get("limit", 5))
    days = int(check.get("days", 7))
    # 보간값은 fixture 상수와 이 모듈의 상수뿐이다. 정답 SQL 은 읽기 전용
    # 실행기(run_query)만 거치며 외부 입력을 받지 않는다.
    statement = (
        f"SELECT bid_ntce_no, {date_column} FROM {dataset} "  # noqa: S608  # nosec B608 - 보간값은 상수다
        f"WHERE {where} AND {date_column} >= CURDATE() - INTERVAL {days} DAY "
        f"ORDER BY {date_column} DESC, id DESC LIMIT {limit}"
    )
    _, rows = query(statement, limit)
    if rows:
        return rows, False
    # 수집 공백으로 최근 창에 행이 없으면 날짜 조건만 풀고 같은 조건으로 다시 본다.
    fallback = (
        f"SELECT bid_ntce_no, {date_column} FROM {dataset} "  # noqa: S608  # nosec B608 - 보간값은 상수다
        f"WHERE {where} ORDER BY {date_column} DESC, id DESC LIMIT {limit}"
    )
    _, fallback_rows = query(fallback, limit)
    return fallback_rows, True


def build_latest_truth(
    kind: str, check: dict[str, Any], query_fn: QueryFn | None = None
) -> dict[str, Any]:
    """공고/낙찰 최신 목록의 정답 집합을 만든다.

    상위 limit 행에 더해, 절단 지점과 같은 일시의 행(동점)을 허용 집합에 넣는다.
    """
    query = query_fn or run_query
    dataset, date_column = LATEST_CHECKS[kind]
    limit = int(check.get("limit", 5))
    try:
        rows, used_fallback = _latest_rows(dataset, date_column, check, query)
    except Exception as exc:
        return {
            "kind": kind,
            "allowed": set(),
            "expected_count": 0,
            "data_available": False,
            "window_fallback": False,
            "error": str(exc),
        }

    allowed = {str(row[0]) for row in rows if row and row[0]}
    expected_count = len(allowed)
    window_fallback = used_fallback and bool(rows)

    if len(rows) == limit and rows:
        cutoff = rows[-1][1]
        cutoff_conditions: list[str] = [f"{date_column} = '{cutoff}'"]
        category = check.get("category")
        if category:
            cutoff_conditions.append(f"category = '{category}'")
        institution_like = check.get("institution_like")
        if institution_like:
            columns = INSTITUTION_COLUMNS[dataset]
            like_parts = [f"{column} LIKE '%{institution_like}%'" for column in columns]
            cutoff_conditions.append(f"({' OR '.join(like_parts)})")
        tie_statement = (
            f"SELECT bid_ntce_no FROM {dataset} "  # noqa: S608  # nosec B608 - 보간값은 상수다
            f"WHERE {' AND '.join(cutoff_conditions)} LIMIT {max(limit * 20, 100)}"
        )
        try:
            _, tie_rows = query(tie_statement, max(limit * 20, 100))
            allowed.update(str(row[0]) for row in tie_rows if row and row[0])
        except Exception as exc:
            tie_error = str(exc)
        else:
            tie_error = None
    else:
        tie_error = None

    return {
        "kind": kind,
        "allowed": allowed,
        "expected_count": expected_count,
        "data_available": expected_count > 0,
        "window_fallback": window_fallback,
        "error": None,
        "tie_error": tie_error,
    }


def _lookup_title(bid_no: str, query: QueryFn) -> str:
    titles: list[str] = []
    for dataset in ("bid_announcements", "bid_results"):
        statement = f"SELECT bid_ntce_nm FROM {dataset} WHERE bid_ntce_no = '{bid_no}' LIMIT 1"  # noqa: S608  # nosec B608 - 보간값은 DB 값이다
        try:
            _, rows = query(statement, 1)
        except Exception:
            titles.append("")
            continue
        titles.append(str(rows[0][0]) if rows and rows[0][0] else "")
    return next((title for title in titles if title), "")


def build_truth(
    item: dict[str, Any],
    placeholders: dict[str, str],
    query_fn: QueryFn | None = None,
) -> dict[str, Any]:
    """문항 하나의 실행 시점 정답을 만든다. HTTP 호출 전에 한 번만 계산한다."""
    query = query_fn or run_query
    check = item["check"]
    kind = check["type"]

    if kind in LATEST_CHECKS:
        return build_latest_truth(kind, check, query)

    if kind == "numeric_fact":
        statement = fill_placeholders(str(check["sql"]), placeholders)
        try:
            _, rows = query(statement, 1)
            raw_value = rows[0][0] if rows else None
            value = None if raw_value is None else float(raw_value)
            return {
                "kind": kind,
                "value": value,
                "sql": statement,
                "data_available": value is not None,
                "error": None,
            }
        except Exception as exc:
            return {
                "kind": kind,
                "value": None,
                "sql": statement,
                "data_available": False,
                "error": str(exc),
            }

    if kind == "bid_lookup":
        name = str(check.get("bid_no_placeholder") or "")
        bid_no = placeholders.get(name, "")
        title = _lookup_title(bid_no, query) if bid_no else ""
        return {
            "kind": kind,
            "bid_no": bid_no,
            "title": title,
            "data_available": bool(bid_no),
            "error": None if bid_no else f"placeholder 미해결: {name}",
        }

    return {"kind": kind, "data_available": True, "error": None}


def _evaluate_latest(truth: dict[str, Any], answer: str) -> tuple[bool, dict[str, Any]]:
    detected = extract_bid_numbers(answer)
    detail: dict[str, Any] = {
        "detected_bid_numbers": sorted(detected),
        "detected_count": len(detected),
        "expected_count": truth.get("expected_count", 0),
        "window_fallback": bool(truth.get("window_fallback")),
    }
    if truth.get("error"):
        detail["db_error"] = truth["error"]
        return False, detail
    if truth.get("expected_count", 0) == 0:
        detail["db_empty"] = True
        return len(detected) == 0, detail
    allowed: set[str] = set(truth.get("allowed") or set())
    outside = sorted(detected - allowed)
    detail["outside_allowed"] = outside
    detail["allowed_sample"] = sorted(allowed)[: int(truth.get("expected_count", 0)) + 5]
    passed = not outside and len(detected) == int(truth["expected_count"])
    return passed, detail


def _evaluate_numeric(
    check: dict[str, Any], truth: dict[str, Any], answer: str
) -> tuple[bool, dict[str, Any]]:
    value = truth.get("value")
    detail: dict[str, Any] = {"db_value": value}
    if truth.get("error"):
        detail["db_error"] = truth["error"]
        return False, detail
    if value is None:
        detail["db_empty"] = True
        return False, detail
    ratio = float(check.get("tolerance_ratio", 0.0))
    tolerance = abs(value) * ratio
    numbers = extract_numbers(answer)
    matched = next((n for n in numbers if abs(n - value) <= tolerance + 1e-9), None)
    detail.update(
        {
            "tolerance_ratio": ratio,
            "tolerance_abs": round(tolerance, 6),
            "matched_number": matched,
            "answer_numbers_sample": numbers[:15],
        }
    )
    return matched is not None, detail


def _evaluate_bid_lookup(truth: dict[str, Any], answer: str) -> tuple[bool, dict[str, Any]]:
    bid_no = str(truth.get("bid_no") or "")
    title = str(truth.get("title") or "")
    detail: dict[str, Any] = {"bid_no": bid_no}
    if not bid_no:
        detail["reason"] = truth.get("error") or "placeholder 미해결"
        return False, detail
    compact_answer = re.sub(r"\s+", "", answer).upper()
    bid_hit = bid_no.upper() in compact_answer
    fragment = re.sub(r"\s+", " ", title).strip()[:15]
    title_hit = len(fragment) >= 6 and fragment in answer
    detail.update({"bid_no_found": bid_hit, "title_fragment": fragment, "title_found": title_hit})
    return bid_hit or title_hit, detail


def _evaluate_refusal(answer: str) -> tuple[bool, dict[str, Any]]:
    fabricated = sorted(set(FABRICATED_NUMBER_PATTERN.findall(answer or "")))
    bid_like = sorted(extract_bid_numbers(answer))
    invented = sorted(set(fabricated) | set(bid_like))
    detail: dict[str, Any] = {
        "fabricated_numbers": invented[:10],
        "answer_chars": len(answer or ""),
    }
    return bool(answer and answer.strip()) and not invented, detail


def evaluate_check(
    check: dict[str, Any],
    truth: dict[str, Any],
    answer: str,
) -> tuple[bool, dict[str, Any]]:
    kind = check["type"]
    if kind in LATEST_CHECKS:
        return _evaluate_latest(truth, answer)
    if kind == "numeric_fact":
        return _evaluate_numeric(check, truth, answer)
    if kind == "bid_lookup":
        return _evaluate_bid_lookup(truth, answer)
    if kind == "refuse_or_redirect":
        return _evaluate_refusal(answer)
    return True, {"note": "도구 선택만 판정"}


def _primary_reason(reasons: list[str]) -> str:
    if not reasons:
        return ""
    counts = Counter(reasons)
    return sorted(
        counts,
        key=lambda reason: (
            -counts[reason],
            FAILURE_PRIORITY.index(reason) if reason in FAILURE_PRIORITY else len(FAILURE_PRIORITY),
        ),
    )[0]


def grade_attempt(
    item: dict[str, Any],
    truth: dict[str, Any],
    outcome: dict[str, Any],
    retried: bool = False,
) -> dict[str, Any]:
    """호출 한 번의 응답을 채점한다. 실패 사유는 겹쳐도 모두 남긴다."""
    status = int(outcome.get("status") or 0)
    elapsed_ms = float(outcome.get("elapsed_ms") or 0.0)

    if not outcome.get("ok"):
        reason = "rate_limited" if status == 429 else "error"
        return {
            "passed": False,
            "failure_reason": reason,
            "failure_reasons": [reason],
            "tools": [],
            "http_status": status,
            "latency_ms": round(elapsed_ms, 3),
            "answer_excerpt": "",
            "retried": retried,
            "detail": {"error": str(outcome.get("error") or "")[:500]},
        }

    payload = outcome.get("payload")
    if not isinstance(payload, dict):
        return {
            "passed": False,
            "failure_reason": "error",
            "failure_reasons": ["error"],
            "tools": [],
            "http_status": status,
            "latency_ms": round(elapsed_ms, 3),
            "answer_excerpt": "",
            "retried": retried,
            "detail": {"error": "응답이 JSON 객체가 아님"},
        }

    missing_keys = [key for key in ("answer", "plan_steps") if key not in payload]
    answer = str(payload.get("answer") or "")
    tools = extract_tools(payload)
    reasons: list[str] = []
    detail: dict[str, Any] = {}

    if missing_keys:
        reasons.append("error")
        detail["missing_keys"] = missing_keys

    expected_tools = [str(tool) for tool in item.get("expected_tools") or []]
    forbidden_tools = [str(tool) for tool in item.get("forbidden_tools") or []]
    missing_tools = [tool for tool in expected_tools if tool not in tools]
    forbidden_hit = [tool for tool in forbidden_tools if tool in tools]
    if missing_tools or forbidden_hit:
        reasons.append("routing")
        detail["missing_tools"] = missing_tools
        detail["forbidden_tools_present"] = forbidden_hit

    if truth.get("data_available", True):
        forbidden_phrases = [
            phrase
            for phrase in item.get("must_not_contain") or []
            if str(phrase) and str(phrase).lower() in answer.lower()
        ]
        if forbidden_phrases:
            reasons.append("forbidden_phrase")
            detail["forbidden_phrases"] = forbidden_phrases

    check_passed, check_detail = evaluate_check(item["check"], truth, answer)
    detail.update(check_detail)
    if not check_passed:
        reasons.append("data_mismatch")

    deduped = list(dict.fromkeys(reasons))
    return {
        "passed": not deduped,
        "failure_reason": _primary_reason(deduped),
        "failure_reasons": deduped,
        "tools": tools,
        "http_status": status,
        "latency_ms": round(float(payload.get("latency_ms") or elapsed_ms), 3),
        "answer_excerpt": answer[:500],
        "retried": retried,
        "detail": detail,
    }


def summarize_item(item: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    repeats = int(item.get("repeats") or 1)
    threshold = repeats // 2 + 1 if repeats > 1 else 1
    passed_attempts = sum(1 for attempt in attempts if attempt["passed"])
    verdict = "pass" if passed_attempts >= threshold else "fail"
    reasons = [reason for attempt in attempts for reason in attempt["failure_reasons"]]
    tool_union = sorted({tool for attempt in attempts for tool in attempt["tools"]})
    return {
        "id": item["id"],
        "category": item["category"],
        "split": item["split"],
        "question": item["question"],
        "repeats": repeats,
        "threshold": threshold,
        "passed_attempts": passed_attempts,
        "verdict": verdict,
        "failure_reason": "" if verdict == "pass" else _primary_reason(reasons),
        "failure_reasons": list(dict.fromkeys(reasons)),
        "tools": tool_union,
        "attempts": attempts,
    }


class CallPacer:
    """호출 사이 최소 간격을 지킨다. 익명 한도(60초당 30회) 회피용이다."""

    def __init__(
        self,
        min_interval_sec: float,
        sleep_fn: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.min_interval_sec = max(0.0, float(min_interval_sec))
        self._sleep = sleep_fn or time.sleep
        self._clock = clock or time.monotonic
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self.min_interval_sec > 0 and self._last is not None:
            remaining = self.min_interval_sec - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


def send_chat(base_url: str, question: str, timeout_sec: float) -> dict[str, Any]:
    """`POST /api/v1/chatbot/chat` 을 호출한다. 본문은 message 하나다."""
    from urllib import error as urlerror
    from urllib import request as urlrequest

    body = json.dumps({"message": question}).encode("utf-8")
    request = urlrequest.Request(
        f"{base_url.rstrip('/')}{CHAT_PATH}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(request, timeout=timeout_sec) as response:  # nosec B310 - base_url 은 호출자가 정한다
            raw = response.read().decode("utf-8")
            status = int(response.status)
        payload = json.loads(raw)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": True, "status": status, "elapsed_ms": elapsed_ms, "payload": payload}
    except urlerror.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        return {
            "ok": False,
            "status": int(exc.code),
            "elapsed_ms": elapsed_ms,
            "error": f"HTTP {exc.code}: {detail}",
        }
    except (urlerror.URLError, TimeoutError, OSError, ValueError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": False, "status": 0, "elapsed_ms": elapsed_ms, "error": str(exc)}


def call_with_rate_limit(
    question: str,
    config: RunConfig,
    pacer: CallPacer,
    call_fn: Callable[[str, str, float], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> tuple[dict[str, Any], bool]:
    call = call_fn or send_chat
    sleep = sleep_fn or time.sleep
    pacer.wait()
    outcome = call(config.base_url, question, config.timeout_sec)
    if outcome.get("status") != 429:
        return outcome, False
    sleep(RATE_LIMIT_WAIT_SEC)
    pacer.wait()
    return call(config.base_url, question, config.timeout_sec), True


def run_item(
    item: dict[str, Any],
    placeholders: dict[str, str],
    config: RunConfig,
    pacer: CallPacer,
    query_fn: QueryFn | None = None,
    call_fn: Callable[[str, str, float], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    question = fill_placeholders(str(item["question"]), placeholders)
    truth = build_truth(item, placeholders, query_fn)
    attempts = []
    for _ in range(int(item.get("repeats") or 1)):
        outcome, retried = call_with_rate_limit(
            question, config, pacer, call_fn=call_fn, sleep_fn=sleep_fn
        )
        attempts.append(grade_attempt(item, truth, outcome, retried=retried))
    return summarize_item(item, attempts)


def _check_required_keys(check: dict[str, Any]) -> list[str]:
    kind = check.get("type")
    errors: list[str] = []
    if kind not in CHECK_TYPES:
        return [f"알 수 없는 check.type: {kind!r}"]
    if kind in LATEST_CHECKS:
        limit = check.get("limit")
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            errors.append("check.limit 은 1~50 정수여야 합니다")
        days = check.get("days")
        if not isinstance(days, int) or days < 0:
            errors.append("check.days 는 0 이상 정수여야 합니다")
        category = check.get("category")
        if category is not None and category not in CATEGORY_CODES:
            errors.append(f"check.category 값이 잘못됐습니다: {category!r}")
    elif kind == "numeric_fact":
        statement = str(check.get("sql") or "")
        if not statement.lower().lstrip().startswith(("select", "with")):
            errors.append("check.sql 은 SELECT/WITH 단일 문장이어야 합니다")
        if ";" in statement.strip().rstrip(";"):
            errors.append("check.sql 에 세미콜론을 쓸 수 없습니다")
        ratio = check.get("tolerance_ratio")
        if not isinstance(ratio, (int, float)) or ratio < 0:
            errors.append("check.tolerance_ratio 는 0 이상 수여야 합니다")
        if "expected_value" in check:
            errors.append("정답을 fixture 에 고정할 수 없습니다. sql 로 계산하십시오")
    elif kind == "bid_lookup":
        placeholder = check.get("bid_no_placeholder")
        if not isinstance(placeholder, str) or not placeholder:
            errors.append("check.bid_no_placeholder 가 필요합니다")
        elif placeholder not in PLACEHOLDER_QUERIES:
            errors.append(f"등록되지 않은 placeholder: {placeholder}")
    return errors


def validate_fixture(payload: dict[str, Any], expected_split: str, path: Path | str) -> list[str]:
    """fixture 스키마를 검사하고 오류 목록을 돌려준다. 비어 있으면 정상이다."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{path}: 최상위가 객체가 아닙니다"]
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return [f"{path}: items 배열이 비어 있습니다"]

    seen: set[str] = set()
    for index, item in enumerate(items):
        where = f"{path}#{index}"
        if not isinstance(item, dict):
            errors.append(f"{where}: 문항이 객체가 아닙니다")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{where}: id 가 필요합니다")
        elif item_id in seen:
            errors.append(f"{where}: id 중복 {item_id}")
        else:
            seen.add(item_id)

        if item.get("split") != expected_split:
            errors.append(f"{where}: split 은 {expected_split!r} 여야 합니다")

        category = item.get("category")
        if category not in CATEGORIES:
            errors.append(f"{where}: 알 수 없는 category {category!r}")

        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{where}: question 이 필요합니다")
        elif BID_NO_PATTERN.search(question):
            errors.append(f"{where}: question 에 공고번호를 고정했습니다. placeholder 를 쓰십시오")

        for key in ("expected_tools", "forbidden_tools", "must_not_contain"):
            value = item.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(f"{where}: {key} 는 문자열 배열이어야 합니다")

        repeats = item.get("repeats")
        if not isinstance(repeats, int) or not 1 <= repeats <= 5:
            errors.append(f"{where}: repeats 는 1~5 정수여야 합니다")

        check = item.get("check")
        if not isinstance(check, dict):
            errors.append(f"{where}: check 객체가 필요합니다")
            continue
        for error in _check_required_keys(check):
            errors.append(f"{where}: {error}")

        for name in sorted(collect_placeholders(item)):
            if name not in PLACEHOLDER_QUERIES:
                errors.append(f"{where}: 등록되지 않은 placeholder {name}")
    return errors


def load_fixtures(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        split = "public" if path == DEFAULT_PUBLIC_FIXTURE else ""
        if not split:
            split = str(payload.get("split") or "")
        if split not in SPLITS:
            errors.append(f"{path}: fixture 최상위에 split(public|blind) 이 필요합니다")
            continue
        errors.extend(validate_fixture(payload, split, path))
        for item in payload.get("items") or []:
            if isinstance(item, dict) and item.get("id") in seen:
                errors.append(f"{path}: 다른 fixture 와 id 중복 {item.get('id')}")
            elif isinstance(item, dict):
                seen.add(str(item.get("id")))
                items.append(item)
    return items, errors


def _category_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        scoped = [record for record in records if record["category"] == category]
        if not scoped:
            continue
        passed = sum(1 for record in scoped if record["verdict"] == "pass")
        total = len(scoped)
        summary[category] = {
            "passed": passed,
            "total": total,
            "pass_rate": round(passed / total, 4),
        }
    return summary


def print_summary_table(summary: dict[str, dict[str, Any]]) -> None:
    print("\n유형별 통과율")
    print(f"{'category':<20}{'passed':>8}{'total':>8}{'rate':>9}")
    for category, stats in summary.items():
        rate = f"{stats['pass_rate'] * 100:.1f}%"
        print(f"{category:<20}{stats['passed']:>8}{stats['total']:>8}{rate:>9}")
    passed = sum(stats["passed"] for stats in summary.values())
    total = sum(stats["total"] for stats in summary.values())
    rate = f"{(passed / total * 100) if total else 0.0:.1f}%"
    print(f"{'TOTAL':<20}{passed:>8}{total:>8}{rate:>9}")


def current_git_commit() -> str:
    try:
        return subprocess.check_output(  # nosec B603 B607 - 고정 인자만 쓴다
            ["git", "rev-parse", "HEAD"],
            text=True,
            timeout=10,
            cwd=PROJECT_ROOT,
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _select_items(
    items: list[dict[str, Any]], only_categories: list[str] | None, limit: int
) -> list[dict[str, Any]]:
    selected = items
    if only_categories:
        wanted = set(only_categories)
        selected = [item for item in selected if item["category"] in wanted]
    if limit and limit > 0:
        selected = selected[:limit]
    return selected


def run_measurement(
    fixtures: list[Path],
    config: RunConfig,
    only_categories: list[str] | None,
    limit: int,
    out_path: Path,
) -> int:
    items, errors = load_fixtures(fixtures)
    if errors:
        for error in errors:
            print(f"fixture 오류: {error}", file=sys.stderr)
        return 2
    selected = _select_items(items, only_categories, limit)
    if not selected:
        print("선택된 문항이 없습니다.", file=sys.stderr)
        return 2

    started_at = datetime.now(UTC).isoformat()
    placeholder_names = set()
    for item in selected:
        placeholder_names |= collect_placeholders(item)
    placeholders, placeholder_errors = resolve_placeholders(placeholder_names, run_query)
    for name, reason in sorted(placeholder_errors.items()):
        print(f"경고: placeholder {name} 미해결 - {reason}", file=sys.stderr)

    pacer = CallPacer(config.min_interval_sec)
    records: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        record = run_item(item, placeholders, config, pacer)
        records.append(record)
        print(
            f"[{index}/{len(selected)}] {record['id']} {record['verdict']}"
            f" reason={record['failure_reason'] or '-'}",
            flush=True,
        )

    summary = _category_summary(records)
    failures = [
        {
            "id": record["id"],
            "category": record["category"],
            "failure_reason": record["failure_reason"],
            "failure_reasons": record["failure_reasons"],
        }
        for record in records
        if record["verdict"] == "fail"
    ]
    overall_passed = sum(1 for record in records if record["verdict"] == "pass")
    payload = {
        "schema": "CHAT_USER_QUESTIONS_MEASURE_V1",
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "git_commit": current_git_commit(),
        "base_url": config.base_url,
        "min_interval_sec": config.min_interval_sec,
        "timeout_sec": config.timeout_sec,
        "fixtures": [str(path) for path in fixtures],
        "placeholder_errors": placeholder_errors,
        "item_count": len(records),
        "overall": {
            "passed": overall_passed,
            "total": len(records),
            "pass_rate": round(overall_passed / len(records), 4) if records else 0.0,
        },
        "categories": summary,
        "failures": failures,
        "items": records,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary_table(summary)
    print(f"\n결과 저장: {out_path}")
    return 0


def run_dry_run(fixtures: list[Path], only_categories: list[str] | None, limit: int) -> int:
    items, errors = load_fixtures(fixtures)
    if errors:
        for error in errors:
            print(f"fixture 오류: {error}", file=sys.stderr)
        return 2

    print("dry-run: HTTP 및 DB 호출 없이 fixture 만 검사합니다.")
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        counts = Counter(item["category"] for item in payload.get("items") or [])
        print(f"\n{path} ({len(payload.get('items') or [])}문항)")
        for category in CATEGORIES:
            if counts.get(category):
                print(f"  {category:<20}{counts[category]:>4}")

    selected = _select_items(items, only_categories, limit)
    print(f"\n선택 문항: {len(selected)}")
    print("placeholder 목록")
    for name in sorted({name for item in selected for name in collect_placeholders(item)}):
        print(f"  {name}")

    missing = [
        name
        for name in sorted({name for item in selected for name in collect_placeholders(item)})
        if name not in PLACEHOLDER_QUERIES
    ]
    if missing:
        print(f"등록되지 않은 placeholder: {', '.join(missing)}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="챗봇 사용자 질문 점검 측정기")
    parser.add_argument(
        "--fixture",
        type=Path,
        action="append",
        default=None,
        help="질문 세트 경로(반복 가능). 기본값은 공개 세트",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-interval-sec", type=float, default=DEFAULT_MIN_INTERVAL_SEC)
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument(
        "--only-category",
        action="append",
        default=None,
        choices=CATEGORIES,
        help="지정 유형만 측정(반복 가능)",
    )
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N문항만 측정")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="HTTP 와 DB 를 호출하지 않고 fixture 스키마와 placeholder 만 검사",
    )
    parser.add_argument("--out", type=Path, default=None, help="결과 JSON 경로")
    args = parser.parse_args(argv)

    fixtures = args.fixture or [DEFAULT_PUBLIC_FIXTURE]
    if args.dry_run:
        return run_dry_run(fixtures, args.only_category, args.limit)

    out_path = args.out
    if out_path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out_path = DEFAULT_OUT_DIR / f"chat_user_questions_{stamp}.json"

    config = RunConfig(
        base_url=args.base_url,
        timeout_sec=args.timeout_sec,
        min_interval_sec=args.min_interval_sec,
    )
    return run_measurement(fixtures, config, args.only_category, args.limit, out_path)


if __name__ == "__main__":
    raise SystemExit(main())
