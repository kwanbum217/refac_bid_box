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

판정 원칙:

- 원칙 1 (정답 우선): 데이터 부재 문구("확인되지 않", "없습니다" 등)는 DB 정답이
  답변에 없을 때만 실패 근거다. 정답이 답변에 있으면 그 문구가 함께 있어도
  통과한다. 예를 들어 DB 값이 123 일 때 "123건입니다. 취소된 건은 없습니다." 는
  통과이고, 정답 5건을 나열한 뒤 "다만 데이터가 확인되지 않습니다." 를 붙인
  답도 통과다. 정답이 빠졌을 때만 실패다.
- 원칙 2 (0건): DB 정답이 0건이면 답변에 0건/없습니다/없음/확인되지 않 중
  하나가 있고, 공고번호 형식이 하나도 없고, 목록 행(표 본문 행과 "- ", "1. "
  로 시작하는 줄)이 없어야 통과다. 목록 행이 없어도 쉼표로 공사명을 늘어놓은
  답(공고명 낱말 "공사|용역|구매|입찰" 이 두 번 이상)은 실패다.
- 원칙 3 (단건): `bid_lookup` 은 질문에 나온 공고번호를 답변에서 지운 뒤, DB 의
  공고명 앞 6자 이상 일부나 낙찰업체명이나 낙찰금액 숫자 중 하나가 있어야
  통과다. 공고번호를 되풀이한 것만으로는 통과하지 못한다.
- 원칙 4 (범위 밖): `refuse_or_redirect` 는 낱말 기반 근사 판정이다. 업무 안내
  표지 또는 안내/거절 표지가 있고 지어낸 수치·공고번호·`forbidden_claims` 가
  없으면 통과로 본다. 이 판정은 근사이므로 결과 JSON 의 해당 문항에
  `heuristic: true` 를 붙인다. 코디네이터가 답변을 직접 읽어 확정해야 한다.

수치 판정(numeric_fact):

- 답변 숫자에서 질문 문장에 나온 숫자(기간 일수, 개수 등)를 먼저 뺀 뒤 비교한다.
  질문의 "30일" 을 답변이 그대로 되풀이한 것을 정답으로 오인하지 않기 위해서다.
- 질문 숫자를 뺀 뒤 DB 값과 허용 오차 안의 수가 있으면 통과다. 데이터 부재
  문구가 함께 있어도 정답 수치가 있으면 통과한다(원칙 1).
- 날짜, 시각, 공고번호, 서수("1위")는 숫자 추출 전에 가린다.

범위 밖 판정(refuse_or_redirect)은 낱말 기반 근사다:

- fixture 문항마다 `forbidden_claims` 를 둔다. 그 질문에 지어낸 답이면 나올
  낱말 목록(날씨라면 "맑", "흐리", "비가", "기온" 등)이고, 답변에 하나라도
  있으면 실패다. 범위 밖 질문에 업무 사실을 섞어 답하는 경우를 잡는다.
- 업무 안내 표지("입찰", "공고", "낙찰", "조달" 중 하나) **또는** 안내/거절
  표지("도와드릴", "안내", "답변드리기 어렵", "범위", "지원하지 않" 중 하나)가
  있으면 통과다. 인사말에 자기소개로 답한 경우도 통과시키기 위해서다.
- 범위 밖 주제의 사실을 단정하거나 공고번호를 지어내면 실패다.
- 낱말 목록에 없는 표현으로 사실을 단정하면 통과로 새는 알려진 한계가 있다.
  그래서 결과 JSON 에 `heuristic: true` 를 남기고 코디네이터가 답변을 직접 읽어
  확정한다.

호출 한도와 정답 계산:

- 익명 한도는 60초당 30회이므로 호출 사이 최소 간격을 둔다(기본 2.5초).
- HTTP 429 는 60초 기다린 뒤 한 번만 재시도하고, 그래도 429 면 그 문항을
  `rate_limited` 로 기록한다. 429 를 라우팅 실패로 세지 않는다.
- DB 정답은 `scripts/db_readonly_query.run_query(statement, limit)` 만 사용한다.
  이 함수는 SELECT 단일 문장만 받고 READ ONLY 트랜잭션으로 실행한다.
- `run_query` 호출은 `scripts/db_readonly_query.assert_read_only(sql)` 를 먼저
  통과해야만 한다. 검사기는 이 모듈에 사본을 두지 않고 공용 도구에서 import 해
  쓴다(같은 모듈 `_run_read_only` 가 유일한 통로다). 공용 도구의 검사 규칙이
  바뀌면 측정기도 같은 규칙을 따른다.

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
import math
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
    from scripts.db_readonly_query import UnsafeQueryError as UnsafeQueryError
    from scripts.db_readonly_query import assert_read_only, run_query
except ModuleNotFoundError:  # pragma: no cover - scripts 디렉터리에서 직접 실행하는 경로
    from db_readonly_query import UnsafeQueryError as UnsafeQueryError  # type: ignore[no-redef]
    from db_readonly_query import assert_read_only, run_query  # type: ignore[no-redef]

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
# 문자 접두를 요구한다. 경계는 \b 대신 ASCII 둘러보기를 쓴다. 파이썬 유니코드
# 정규식의 \b 는 한글도 단어 문자로 보므로 "R26BK01775039입니다" 처럼 조사가
# 붙은 번호를 놓친다. 앞에는 영숫자가, 뒤에는 숫자가 붙지 않은 경우만 잡는다.
BID_NO_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]\d{2}[A-Za-z]{2}\d{6,10}(?![0-9])")
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


# 데이터 부재 문구. 원칙 1 에 따라 이 문구는 DB 정답이 답변에 없을 때만 실패
# 근거다. 정답 수치나 공고번호가 답변에 있으면 문구가 함께 있어도 통과한다.
# 그래서 판정 결과에는 참고 정보(absence_phrases)로만 남긴다.
DATA_ABSENCE_PHRASES = (
    "확인되지 않",
    "조회되지 않",
    "없습니다",
    "찾을 수 없",
    "제공할 수 없",
    "알 수 없",
)

# 원칙 2: DB 정답이 0건일 때 통과에 필요한 0건 표현. "0건" 은 "10건" 의 부분
# 문자열이므로 앞에 숫자가 붙지 않은 경우만 인정한다.
ZERO_COUNT_PATTERNS = (
    re.compile(r"(?<!\d)0\s*건"),
    re.compile(r"없습니다"),
    re.compile(r"없음"),
    re.compile(r"확인되지 않"),
)

# 원칙 2: 0건 답변에 있으면 목록을 나열한 것으로 보는 행.
LIST_ROW_PATTERNS = (
    re.compile(r"^\|"),
    re.compile(r"^-\s"),
    re.compile(r"^\d+\.\s"),
)
TABLE_SEPARATOR_PATTERN = re.compile(r"^[|\-: ]+$")

# 원칙 2: 목록 행이 없어도 쉼표로 공고명을 늘어놓은 답을 잡는다.
ANNOUNCEMENT_NAME_WORD_PATTERN = re.compile(r"공사|용역|구매|입찰")

# 범위 밖 질문의 통과 조건: 업무 영역 표지 또는 안내/거절 표지 중 하나.
REDIRECT_DOMAIN_TERMS = ("입찰", "공고", "낙찰", "조달")
REDIRECT_MARKERS = (
    "도와드릴",
    "안내",
    "답변드리기 어렵",
    "범위",
    "지원하지 않",
)

# 숫자 추출 전에 가릴 토큰. 날짜/시각/공고번호/서수를 수치 정답으로 오인하지
# 않기 위해서다.
NUMBER_MASK_PATTERNS = (
    BID_NO_PATTERN,
    re.compile(r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?"),
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    re.compile(r"\d+\s*위"),
)


def _run_read_only(
    statement: str, limit: int, query: QueryFn
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """읽기 전용 검사를 통과한 질의만 실행한다.

    이 함수가 `run_query` 를 부르는 유일한 통로다. 검사는 공용 도구
    `db_readonly_query.assert_read_only` 한 벌만 쓰며, 이 모듈에 사본을 두지
    않는다. 검사를 우회하는 새 호출을 추가하지 말 것.
    """
    return query(assert_read_only(statement), limit)


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
            _, rows = _run_read_only(statement, 1, query)
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
    """답변/질문 문장의 수치를 뽑는다. 날짜, 시각, 공고번호, 서수는 가린다."""
    normalized = text or ""
    for pattern in NUMBER_MASK_PATTERNS:
        normalized = pattern.sub(" ", normalized)
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    numbers: list[float] = []
    for token in NUMBER_PATTERN.findall(normalized):
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    return numbers


def subtract_question_numbers(
    answer_numbers: list[float], question_numbers: list[float]
) -> list[float]:
    """답변 수치에서 질문에 이미 나온 수치를 뺀다.

    질문의 기간(30일)이나 개수(5건)를 답변이 되풀이한 것을 DB 정답으로 오인하지
    않기 위해서다. 같은 값이 여러 번 나오면 등장 횟수만큼만 뺀다.
    """
    remaining = list(answer_numbers)
    for question_number in question_numbers:
        for index, candidate in enumerate(remaining):
            if math.isclose(candidate, question_number, rel_tol=1e-9, abs_tol=1e-9):
                remaining.pop(index)
                break
    return remaining


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
    _, rows = _run_read_only(statement, limit, query)
    if rows:
        return rows, False
    # 수집 공백으로 최근 창에 행이 없으면 날짜 조건만 풀고 같은 조건으로 다시 본다.
    fallback = (
        f"SELECT bid_ntce_no, {date_column} FROM {dataset} "  # noqa: S608  # nosec B608 - 보간값은 상수다
        f"WHERE {where} ORDER BY {date_column} DESC, id DESC LIMIT {limit}"
    )
    _, fallback_rows = _run_read_only(fallback, limit, query)
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
    tie_error: str | None = None

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
            _, tie_rows = _run_read_only(tie_statement, max(limit * 20, 100), query)
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


def _lookup_bid_record(bid_no: str, query: QueryFn) -> dict[str, Any]:
    """원칙 3 의 정답 근거를 DB 에서 모은다.

    공고명 일부, 낙찰업체명, 낙찰금액 셋 중 하나가 답변에 있어야 통과다.
    공고번호를 되풀이한 것만으로는 통과시키지 않기 위해서다.
    """
    record: dict[str, Any] = {"title": "", "winner": "", "amount": None}
    statements = (
        # 보간값은 placeholder 해석으로 얻은 DB 값이다.
        f"SELECT bid_ntce_nm, bidwinnr_nm, sucsf_bid_amt FROM bid_results "  # noqa: S608  # nosec B608
        f"WHERE bid_ntce_no = '{bid_no}' LIMIT 1",
        f"SELECT bid_ntce_nm FROM bid_announcements WHERE bid_ntce_no = '{bid_no}' LIMIT 1",  # noqa: S608  # nosec B608 - 보간값은 DB 값이다
    )
    for statement in statements:
        columns: list[str] = []
        rows: list[tuple[Any, ...]] = []
        try:
            columns, rows = _run_read_only(statement, 1, query)
        except Exception:
            rows = []
        if not rows:
            continue
        values = dict(zip(columns, rows[0], strict=False))
        title = values.get("bid_ntce_nm")
        winner = values.get("bidwinnr_nm")
        amount = values.get("sucsf_bid_amt")
        if not record["title"] and title:
            record["title"] = str(title)
        if not record["winner"] and winner:
            record["winner"] = str(winner)
        if record["amount"] is None and amount not in (None, ""):
            try:
                record["amount"] = int(amount)
            except (TypeError, ValueError):
                record["amount"] = None
    return record


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
            _, rows = _run_read_only(statement, 1, query)
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
        record = (
            _lookup_bid_record(bid_no, query)
            if bid_no
            else {
                "title": "",
                "winner": "",
                "amount": None,
            }
        )
        return {
            "kind": kind,
            "bid_no": bid_no,
            "title": record["title"],
            "winner": record["winner"],
            "amount": record["amount"],
            "data_available": bool(bid_no),
            "error": None if bid_no else f"placeholder 미해결: {name}",
        }

    return {"kind": kind, "data_available": True, "error": None}


def _absence_hits(answer: str) -> list[str]:
    """답변에 든 데이터 부재 문구를 돌려준다.

    원칙 1 에 따라 이 문구는 판정 근거가 아니라 참고 정보다. DB 정답이 답변에
    있는지는 각 판정 함수가 따로 본다.
    """
    return [phrase for phrase in DATA_ABSENCE_PHRASES if phrase in (answer or "")]


def _list_row_lines(answer: str) -> list[str]:
    """원칙 2: 답변이 목록을 나열한 것으로 보이는 행을 모은다."""
    rows: list[str] = []
    for line in (answer or "").splitlines():
        stripped = line.strip()
        if not stripped or TABLE_SEPARATOR_PATTERN.match(stripped):
            continue
        if any(pattern.match(stripped) for pattern in LIST_ROW_PATTERNS):
            rows.append(stripped)
    return rows


def _evaluate_empty_latest(answer: str) -> tuple[bool, dict[str, Any]]:
    """원칙 2: DB 정답이 0건일 때의 판정.

    0건 표현이 있고 공고번호도 목록 행도 없어야 통과다. 목록 행이 없어도
    쉼표로 공고명을 늘어놓은 답은 실패로 본다.
    """
    text = answer or ""
    detected = extract_bid_numbers(text)
    zero_hits = [
        match.group(0) for pattern in ZERO_COUNT_PATTERNS if (match := pattern.search(text))
    ]
    rows = _list_row_lines(text)
    name_words = ANNOUNCEMENT_NAME_WORD_PATTERN.findall(text)
    detail: dict[str, Any] = {
        "db_empty": True,
        "zero_count_phrases": zero_hits,
        "detected_bid_numbers": sorted(detected),
        "detected_count": len(detected),
        "list_row_count": len(rows),
        "list_rows_sample": rows[:5],
        "announcement_name_word_hits": name_words[:10],
        "absence_phrases": _absence_hits(text),
    }
    passed = (
        bool(text.strip()) and bool(zero_hits) and not detected and not rows and len(name_words) < 2
    )
    return passed, detail


def _evaluate_latest(truth: dict[str, Any], answer: str) -> tuple[bool, dict[str, Any]]:
    """원칙 1/2: 최신 목록 판정.

    DB 정답이 1건 이상이면 정답 공고번호가 limit 개(동점 포함) 모두 있어야
    통과다. 부재 문구는 판정에 쓰지 않는다. 0건이면 원칙 2 로 넘긴다.
    """
    absence = _absence_hits(answer)
    if truth.get("error"):
        return False, {
            "db_error": truth["error"],
            "absence_phrases": absence,
            "absence_ignored": True,
        }

    expected = int(truth.get("expected_count") or 0)
    if expected == 0:
        empty_passed, empty_detail = _evaluate_empty_latest(answer)
        empty_detail["absence_ignored"] = True
        return empty_passed, empty_detail

    detected = extract_bid_numbers(answer)
    allowed: set[str] = set(truth.get("allowed") or set())
    outside = sorted(detected - allowed)
    detail: dict[str, Any] = {
        "detected_bid_numbers": sorted(detected),
        "detected_count": len(detected),
        "expected_count": expected,
        "window_fallback": bool(truth.get("window_fallback")),
        "absence_phrases": absence,
        "absence_ignored": True,
        "outside_allowed": outside,
        "allowed_sample": sorted(allowed)[: expected + 5],
    }
    passed = not outside and len(detected) == expected
    return passed, detail


def _evaluate_numeric(
    check: dict[str, Any], truth: dict[str, Any], answer: str, question: str = ""
) -> tuple[bool, dict[str, Any]]:
    """원칙 1: 질문 숫자를 뺀 답변 수치가 DB 값과 허용 오차 안이면 통과다."""
    value = truth.get("value")
    question_numbers = extract_numbers(question)
    answer_numbers = extract_numbers(answer)
    candidates = subtract_question_numbers(answer_numbers, question_numbers)
    detail: dict[str, Any] = {
        "db_value": value,
        "question_numbers": question_numbers[:15],
        "answer_numbers_sample": answer_numbers[:15],
        "candidate_numbers": candidates[:15],
        "absence_phrases": _absence_hits(answer),
        "absence_ignored": True,
    }

    if truth.get("error"):
        detail["db_error"] = truth["error"]
        return False, detail
    if value is None:
        detail["db_empty"] = True
        return False, detail

    ratio = float(check.get("tolerance_ratio", 0.0))
    tolerance = abs(value) * ratio
    matched = next((n for n in candidates if abs(n - value) <= tolerance + 1e-9), None)
    detail.update(
        {
            "tolerance_ratio": ratio,
            "tolerance_abs": round(tolerance, 6),
            "matched_number": matched,
        }
    )
    return matched is not None, detail


def _title_prefix_hit(title: str, text: str) -> str:
    """원칙 3: 공고명 앞 6자 이상 일부가 답변에 있으면 그 조각을 돌려준다."""
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if len(normalized) < 6:
        return ""
    collapsed = re.sub(r"\s+", " ", text or "")
    for length in (40, 30, 20, 12, 8, 6):
        prefix = normalized[: min(len(normalized), length)]
        if len(prefix) >= 6 and prefix in collapsed:
            return prefix
    return ""


def _evaluate_bid_lookup(
    truth: dict[str, Any], answer: str, question: str = ""
) -> tuple[bool, dict[str, Any]]:
    """원칙 3: 질문의 공고번호를 지운 뒤 DB 내용이 답변에 있어야 통과다."""
    bid_no = str(truth.get("bid_no") or "")
    text = answer or ""
    detail: dict[str, Any] = {
        "bid_no": bid_no,
        "absence_phrases": _absence_hits(text),
        "absence_ignored": True,
    }
    if not bid_no:
        detail["reason"] = truth.get("error") or "placeholder 미해결"
        return False, detail

    removed = set(extract_bid_numbers(question))
    removed.add(bid_no.upper())
    cleaned = text
    for number in sorted(removed, key=len, reverse=True):
        cleaned = re.sub(re.escape(number), " ", cleaned, flags=re.IGNORECASE)

    title = str(truth.get("title") or "")
    winner = str(truth.get("winner") or "")
    amount = truth.get("amount")
    title_prefix = _title_prefix_hit(title, cleaned)
    winner_hit = bool(winner) and winner in cleaned
    amount_hit = False
    if amount is not None:
        integer_amount = int(amount)
        amount_hit = integer_amount in {
            int(number) for number in extract_numbers(cleaned) if float(number).is_integer()
        }
    detail.update(
        {
            "removed_bid_numbers": sorted(removed),
            "title_prefix": title_prefix,
            "title_found": bool(title_prefix),
            "winner": winner,
            "winner_found": winner_hit,
            "amount": amount,
            "amount_found": amount_hit,
        }
    )
    return bool(title_prefix) or winner_hit or amount_hit, detail


def _evaluate_refusal(
    answer: str, forbidden_claims: tuple[str, ...] | list[str] = ()
) -> tuple[bool, dict[str, Any]]:
    text = answer or ""
    fabricated = sorted(set(FABRICATED_NUMBER_PATTERN.findall(text)))
    bid_like = sorted(extract_bid_numbers(text))
    invented = sorted(set(fabricated) | set(bid_like))
    domain_hits = [term for term in REDIRECT_DOMAIN_TERMS if term in text]
    marker_hits = [marker for marker in REDIRECT_MARKERS if marker in text]
    claim_hits = [claim for claim in forbidden_claims if claim and claim in text]
    detail: dict[str, Any] = {
        "fabricated_numbers": invented[:10],
        "answer_chars": len(text),
        "domain_terms": domain_hits,
        "redirect_markers": marker_hits,
        "forbidden_claim_hits": claim_hits,
    }
    # 업무 영역 표지나 안내/거절 표지 중 하나만 있어도 안내로 본다. 대신 그
    # 질문에 지어낸 답이면 나올 낱말(forbidden_claims)을 문항별로 걸러, 범위 밖
    # 주제의 사실을 섞어 답하는 경우를 잡는다.
    redirected = bool(domain_hits) or bool(marker_hits)
    passed = bool(text.strip()) and redirected and not invented and not claim_hits
    return passed, detail


def evaluate_check(
    check: dict[str, Any],
    truth: dict[str, Any],
    answer: str,
    question: str = "",
    forbidden_claims: tuple[str, ...] | list[str] = (),
) -> tuple[bool, dict[str, Any]]:
    kind = check["type"]
    if kind in LATEST_CHECKS:
        return _evaluate_latest(truth, answer)
    if kind == "numeric_fact":
        return _evaluate_numeric(check, truth, answer, question)
    if kind == "bid_lookup":
        return _evaluate_bid_lookup(truth, answer, question)
    if kind == "refuse_or_redirect":
        return _evaluate_refusal(answer, forbidden_claims)
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
    question: str | None = None,
) -> dict[str, Any]:
    """호출 한 번의 응답을 채점한다. 실패 사유는 겹쳐도 모두 남긴다.

    `question` 은 placeholder 를 채운 실제 전송 문장이다. 숫자 판정에서 질문에
    나온 수치를 빼려면 원문이 아니라 전송 문장이 필요하다.
    """
    prompt = str(item.get("question") or "") if question is None else question
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

    forbidden_claims = [str(claim) for claim in item.get("forbidden_claims") or []]
    check_passed, check_detail = evaluate_check(
        item["check"], truth, answer, prompt, forbidden_claims
    )
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
    record: dict[str, Any] = {
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
    # 원칙 4: 범위 밖 판정은 낱말 기반 근사다. 코디네이터가 답변을 직접 읽어
    # 확정할 수 있도록 결과에 표시를 남긴다.
    if item.get("category") == "out_of_scope" or item["check"]["type"] == "refuse_or_redirect":
        record["heuristic"] = True
    return record


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
        attempts.append(grade_attempt(item, truth, outcome, retried=retried, question=question))
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

        claims = item.get("forbidden_claims")
        if category == "out_of_scope":
            # 범위 밖 문항은 지어낸 답을 걸러낼 낱말 목록을 반드시 가져야 한다.
            # 비어 있으면 사실을 단정하는 답도 통과해 판정이 느슨해진다.
            if (
                not isinstance(claims, list)
                or not claims
                or not all(isinstance(claim, str) and claim for claim in claims)
            ):
                errors.append(
                    f"{where}: out_of_scope 문항에는 forbidden_claims 문자열 배열이 필요합니다"
                )
        elif claims is not None:
            errors.append(f"{where}: forbidden_claims 는 out_of_scope 문항에만 쓸 수 있습니다")

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
    if "out_of_scope" in summary:
        print(
            "\n참고: out_of_scope 판정은 낱말 기반 근사입니다(결과 JSON 의 heuristic: true). "
            "코디네이터가 답변을 직접 읽어 확정하십시오."
        )


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
