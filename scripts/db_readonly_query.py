"""읽기 전용 DB 질의 전용 진입점.

조사 Task 의 워커가 DB 를 볼 때마다 `docker exec ... mysql` 을 손으로 조립하면
두 가지가 어긋납니다.

1. **매번 사람 승인을 기다립니다.** `orca_auto_approve.py` 는 docker 실행 중
   읽기 전용 `mysql -e` 만 승인하는데, 워커가 형태를 조금만 바꾸면
   (`sh -c` 로 감싸기, 환경변수 참조 방식 변경) 화이트리스트를 벗어납니다.
   2026-09-01 에 낙찰하한율 조사 워커가 이 지점에서 반복해서 멈췄습니다.
2. **쓰기를 막을 보장이 없습니다.** 손으로 조립한 명령은 무엇이든 실행할 수
   있고, 승인 판정은 문자열 검사라 우회 여지가 남습니다.

이 스크립트는 두 문제를 한 번에 닫습니다. `uv run python scripts/...` 는 이미
자동 승인 대상이므로 워커가 멈추지 않고, 질의는 파서 수준에서 읽기 전용만
통과시킵니다.

사용법:

    uv run python scripts/db_readonly_query.py --sql "SELECT COUNT(*) FROM bid_results"
    uv run python scripts/db_readonly_query.py --sql-file queries/x.sql --format json
    uv run python scripts/db_readonly_query.py --sql "SHOW TABLES" --limit 50

읽기 전용 보장:

- `SELECT`, `SHOW`, `EXPLAIN`, `DESC(RIBE)`, `WITH` 로 시작하는 문장만 허용합니다.
- 쓰기·DDL 키워드가 어디에든 나타나면 거부합니다(주석과 문자열 리터럴 제거 후 검사).
- MySQL 실행 주석(`/*! ... */`, `/*!50000 ... */`)과 옵티마이저 힌트 주석
  (`/*+ ... */`)이 있으면 거부합니다. 서버가 본문을 실제로 실행하기 때문입니다.
- 여러 문장을 한 번에 보내지 못하게 합니다. 세미콜론으로 이어 붙인 우회를 막습니다.
- 세션을 `READ ONLY` 트랜잭션으로 열어 드라이버 수준에서도 쓰기를 차단합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from src.app.core.config import settings  # noqa: E402

READ_ONLY_STARTS = ("select", "show", "explain", "desc", "describe", "with")

# 어디에 나타나든 거부하는 토큰입니다. 단어 경계로 검사해 컬럼명 오탐을 피합니다.
FORBIDDEN_TOKENS = (
    "insert",
    "update",
    "delete",
    "replace",
    "merge",
    "truncate",
    "drop",
    "create",
    "alter",
    "rename",
    "grant",
    "revoke",
    "commit",
    "rollback",
    "savepoint",
    "lock",
    "unlock",
    "call",
    "do",
    "handler",
    "load",
    "install",
    "uninstall",
    "set",
    "reset",
    "flush",
    "kill",
    "shutdown",
    "start",
    "stop",
    "prepare",
    "execute",
    "deallocate",
    "into",
)

FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_TOKENS) + r")\b", re.IGNORECASE)

# 문장 키워드와 이름이 겹치는 읽기 전용 함수입니다. 함수 호출 형태(이름 바로 뒤에
# 여는 괄호)일 때만 검사에서 제외합니다. `REPLACE(col, ',', '')` 로 콤마를 떼는
# 금액 질의가 이 오탐에 막혔습니다. 문장 형태는 걸러지지 않습니다. REPLACE 문은
# 테이블명이 먼저 와서 여는 괄호가 붙지 않고, 애초에 문장 시작 토큰 검사와
# 다중 문장 금지를 함께 통과할 수 없습니다.
READ_ONLY_FUNCTION_TOKENS = ("replace",)
FUNCTION_CALL_RE = re.compile(
    r"\b(" + "|".join(READ_ONLY_FUNCTION_TOKENS) + r")\s*\(", re.IGNORECASE
)

DEFAULT_LIMIT = 200

# MySQL 은 이 두 주석의 본문을 주석이 아니라 실행 가능한 SQL 로 취급합니다.
# `/* !` 처럼 구분자 사이에 공백이 있으면 일반 주석이므로 대상이 아닙니다.
EXECUTABLE_COMMENT_MARKERS = ("/*!", "/*+")


class UnsafeQueryError(ValueError):
    """읽기 전용이 아닌 질의를 거부할 때 냅니다."""


# 상태 기반 스캐너가 쓰는 인용 문맥과 그 닫는 문자입니다. 백틱은 식별자라
# 백슬래시 이스케이프가 없고, 겹친 백틱(``)이 이스케이프입니다.
QUOTED_STATES = {"single": "'", "double": '"', "backtick": "`"}


def reject_executable_comments(sql: str) -> None:
    """원문을 왼쪽에서 오른쪽으로 한 번 훑어 실행 주석과 힌트 주석을 찾습니다.

    문자열 리터럴 제거와 주석 제거를 정규식으로 따로 돌리면 서로의 경계를
    오인합니다. `SELECT 1 /* ' */ /*! DELETE FROM t */ 'x'` 처럼 블록 주석 안의
    따옴표를 리터럴 시작으로 보면 뒤따르는 실행 주석을 놓치고, 반대로 리터럴
    안의 `/*!` 를 주석 시작으로 보면 정상 질의를 막습니다. 문맥을 유지한 한 번의
    순회는 두 문제를 함께 없앱니다.

    MySQL 은 `/*! ... */` 와 `/*+ ... */` 의 본문을 주석이 아니라 실행할 SQL 로
    취급합니다. `/* !` 처럼 구분자 사이에 공백이 있으면 일반 주석입니다.
    닫히지 않은 리터럴이나 블록 주석도 경계를 신뢰할 수 없으므로 거부합니다.
    """
    state = "normal"
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]

        if state in QUOTED_STATES:
            quote = QUOTED_STATES[state]
            if char == "\\" and state != "backtick":
                index += 2
            elif char == quote:
                if sql.startswith(quote * 2, index):
                    index += 2
                else:
                    state = "normal"
                    index += 1
            else:
                index += 1
            continue

        if state == "block":
            if char == "*" and sql.startswith("*/", index):
                state = "normal"
                index += 2
            else:
                index += 1
            continue

        if state == "line":
            if char == "\n":
                state = "normal"
            index += 1
            continue

        if char in "'\"`":
            state = {"'": "single", '"': "double", "`": "backtick"}[char]
            index += 1
        elif char == "/" and sql.startswith("/*", index):
            if sql.startswith(EXECUTABLE_COMMENT_MARKERS, index):
                raise UnsafeQueryError(
                    "MySQL 실행 주석(/*! */)이나 힌트 주석(/*+ */)은 허용하지 않습니다."
                )
            state = "block"
            index += 2
        elif char == "-" and sql.startswith("--", index):
            state = "line"
            index += 2
        elif char == "#":
            state = "line"
            index += 1
        else:
            index += 1

    if state in QUOTED_STATES or state == "block":
        raise UnsafeQueryError("닫히지 않은 문자열 리터럴이나 주석이 있습니다.")


def strip_sql_noise(sql: str) -> str:
    """주석과 문자열 리터럴을 지운 검사용 사본을 만듭니다.

    금지 토큰 검사를 원문에 그대로 하면 `WHERE name = 'update'` 같은 정상 질의가
    막히고, 반대로 주석 안에 숨긴 구문을 놓칠 수 있습니다.
    """
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_line = re.sub(r"(--|#)[^\n]*", " ", without_block)
    without_strings = re.sub(r"'(?:[^'\\]|\\.)*'", " ", without_line)
    without_strings = re.sub(r'"(?:[^"\\]|\\.)*"', " ", without_strings)
    return without_strings


def assert_read_only(sql: str) -> str:
    """읽기 전용 단일 문장인지 검사하고 정규화한 질의를 돌려줍니다."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise UnsafeQueryError("질의가 비어 있습니다.")

    # 일반 주석 제거(strip_sql_noise)보다 먼저 봐야 합니다. MySQL 실행 주석과
    # 힌트 주석의 본문은 서버가 실행하므로, 주석으로 지우면 검사를 통째로
    # 우회합니다.
    reject_executable_comments(statement)

    probe = strip_sql_noise(statement)

    if ";" in probe:
        raise UnsafeQueryError("한 번에 한 문장만 실행합니다. 세미콜론으로 이어 붙이지 마십시오.")

    lowered = probe.lstrip().lower()
    if not lowered.startswith(READ_ONLY_STARTS):
        head = lowered.split()[0] if lowered.split() else "?"
        raise UnsafeQueryError(
            f"읽기 전용 질의가 아닙니다 (시작 토큰: {head}). 허용: {', '.join(READ_ONLY_STARTS)}"
        )

    # 함수 호출 형태의 읽기 전용 함수는 검사 대상에서 뺍니다. 원문은 그대로 두고
    # 검사용 사본에서만 치환하므로 실행되는 질의는 바뀌지 않습니다.
    probe = FUNCTION_CALL_RE.sub(" __readonly_fn__(", probe)

    found = FORBIDDEN_RE.search(probe)
    if found:
        raise UnsafeQueryError(f"금지 키워드가 포함돼 있습니다: {found.group(1)}")

    return statement


def run_query(statement: str, limit: int) -> tuple[list[str], list[tuple[Any, ...]]]:
    """READ ONLY 트랜잭션에서 질의를 실행합니다.

    파서 검사를 통과해도 드라이버 수준에서 한 번 더 막습니다. 검사는 문자열
    분석이라 완전하지 않고, 이 계층은 서버가 강제합니다.
    """
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
            result = conn.execute(text(statement))
            columns = list(result.keys())
            rows = result.fetchmany(limit) if limit > 0 else result.fetchall()
            return columns, [tuple(row) for row in rows]
    finally:
        engine.dispose()


def format_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not columns:
        return "(결과 없음)"
    widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))
    lines = [" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
    return "\n".join(lines)


def format_json(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    payload = [dict(zip(columns, (str(v) for v in row), strict=False)) for row in rows]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="읽기 전용 DB 질의 실행기")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql", help="실행할 단일 읽기 전용 질의")
    source.add_argument("--sql-file", help="질의가 담긴 파일 경로")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"반환 행 수 상한 (기본 {DEFAULT_LIMIT}, 0 이면 무제한)",
    )
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)

    sql = args.sql if args.sql else Path(args.sql_file).read_text(encoding="utf-8")

    try:
        statement = assert_read_only(sql)
    except UnsafeQueryError as exc:
        print(f"거부: {exc}", file=sys.stderr)
        return 2

    try:
        columns, rows = run_query(statement, args.limit)
    except Exception as exc:
        print(f"질의 실패: {exc}", file=sys.stderr)
        return 1

    print(format_json(columns, rows) if args.format == "json" else format_table(columns, rows))
    if args.limit > 0 and len(rows) == args.limit:
        print(
            f"\n(상한 {args.limit}행에서 잘렸습니다. --limit 으로 조정하십시오.)", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
