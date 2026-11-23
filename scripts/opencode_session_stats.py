"""OpenCode 세션 내보내기에서 스텝 수·컨텍스트·실제 적용 variant 를 집계합니다.

워커 토큰 비용은 스텝 수와 스텝당 컨텍스트가 결정하고, `--variant` 지정이 실제로
적용됐는지는 화면 상태줄이 아니라 세션 기록의 `model.variant` 로만 확인할 수 있습니다.
이 도구는 2026-11-23 코디네이터가 `opencode session list`/`session export` 결과를
손으로 집계한 방식을 같은 기준으로 재현합니다.

    uv run python scripts/opencode_session_stats.py --export .orca/session_exports/*.json
    uv run python scripts/opencode_session_stats.py --directory-suffix <워크트리 이름> --limit 50

집계 정의:

- 한 스텝은 `tokens` 가 dict 인 메시지입니다. `tokens` 가 없는 메시지는 세지 않습니다.
- 스텝 컨텍스트 = `tokens.input + tokens.cache.read` 이고, 총 읽기는 그 합입니다.
- 평균 컨텍스트는 총 읽기를 스텝 수로 나눈 값, 최대 컨텍스트는 스텝별 최댓값입니다.
- 새 입력 합은 `tokens.input` 합, 출력+추론 합은 `tokens.output + tokens.reasoning` 합입니다.
- variant 집합은 스텝 메시지의 `model.variant` 에서 모읍니다.

`opencode` 호출은 `--directory-suffix` 경로에서만 일어나며, 실패한 세션은 경고를
남기고 건너뜁니다. `--export` 경로는 네트워크도 외부 프로세스도 쓰지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - opencode 를 고정 인자 목록으로만 호출합니다
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OPENCODE_BIN = "opencode"
LIST_FORMAT = "json"
DEFAULT_LIMIT = 50
JSON_SCHEMA = "opencode_session_stats/1"


@dataclass
class SessionStats:
    """세션 하나의 집계 결과입니다."""

    session_id: str
    steps: int = 0
    total_read: int = 0
    max_context: int = 0
    new_input: int = 0
    output: int = 0
    variants: set[str] = field(default_factory=set)

    @property
    def avg_context(self) -> float:
        if not self.steps:
            return 0.0
        return self.total_read / self.steps

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "steps": self.steps,
            "avg_context": self.avg_context,
            "max_context": self.max_context,
            "total_read": self.total_read,
            "new_input": self.new_input,
            "output": self.output,
            "variants": sorted(self.variants),
        }


def _token_dict(message: dict[str, Any]) -> dict[str, Any] | None:
    tokens = message.get("tokens")
    return tokens if isinstance(tokens, dict) else None


def _context_size(tokens: dict[str, Any]) -> int:
    cache = tokens.get("cache")
    cache_read = cache.get("read", 0) if isinstance(cache, dict) else 0
    return int(tokens.get("input") or 0) + int(cache_read or 0)


def summarize_export(data: dict[str, Any], session_id: str = "") -> SessionStats:
    """내보내기 JSON 한 건을 집계합니다."""
    info = data.get("info")
    if isinstance(info, dict) and info.get("id"):
        session_id = str(info["id"])
    stats = SessionStats(session_id=session_id or "(unknown)")
    messages = data.get("messages")
    if not isinstance(messages, list):
        return stats
    for message in messages:
        if not isinstance(message, dict):
            continue
        tokens = _token_dict(message)
        if tokens is None:
            continue
        context = _context_size(tokens)
        stats.steps += 1
        stats.total_read += context
        stats.max_context = max(stats.max_context, context)
        stats.new_input += int(tokens.get("input") or 0)
        stats.output += int(tokens.get("output") or 0) + int(tokens.get("reasoning") or 0)
        model = message.get("model")
        if isinstance(model, dict):
            variant = model.get("variant")
            if variant:
                stats.variants.add(str(variant))
    return stats


def load_export(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("최상위가 객체가 아닙니다")
    return data


def collect_from_exports(paths: list[Path]) -> list[SessionStats]:
    results: list[SessionStats] = []
    for path in paths:
        try:
            data = load_export(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _warn(f"{path} 를 읽지 못해 건너뜁니다: {exc}")
            continue
        results.append(summarize_export(data, session_id=path.stem))
    return results


def _run_opencode(args: list[str]) -> str:
    proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
        [OPENCODE_BIN, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"종료 코드 {proc.returncode}")
    return proc.stdout


def list_sessions(limit: int) -> list[dict[str, Any]]:
    output = _run_opencode(["session", "list", "--format", LIST_FORMAT, "-n", str(limit)])
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"세션 목록 JSON 을 해석하지 못했습니다: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("sessions", data.get("items", []))
    if not isinstance(data, list):
        raise RuntimeError("세션 목록 형식이 배열이 아닙니다")
    return [item for item in data if isinstance(item, dict)]


def export_session(session_id: str) -> dict[str, Any]:
    output = _run_opencode(["session", "export", session_id])
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"세션 내보내기 JSON 을 해석하지 못했습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("세션 내보내기 최상위가 객체가 아닙니다")
    return data


def collect_from_directory(suffix: str, limit: int) -> list[SessionStats]:
    sessions = list_sessions(limit)
    selected = [
        str(item["id"])
        for item in sessions
        if item.get("id") and str(item.get("directory", "")).rstrip("/").endswith(suffix)
    ]
    results: list[SessionStats] = []
    for session_id in selected:
        try:
            data = export_session(session_id)
        except (OSError, RuntimeError) as exc:
            _warn(f"{session_id} 내보내기를 건너뜁니다: {exc}")
            continue
        results.append(summarize_export(data, session_id=session_id))
    return results


def _warn(message: str) -> None:
    print(f"경고: {message}", file=sys.stderr)


def _format_count(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(int(value))


def _format_row(cells: list[str], widths: list[int]) -> str:
    parts = []
    for index, cell in enumerate(cells):
        parts.append(cell.ljust(widths[index]) if index == 0 else cell.rjust(widths[index]))
    return "  ".join(parts).rstrip()


TABLE_HEADERS = [
    "session",
    "steps",
    "avg_ctx",
    "max_ctx",
    "read_total",
    "new_input",
    "output",
    "variant",
]


def format_table(results: list[SessionStats]) -> str:
    rows = [
        [
            stats.session_id,
            str(stats.steps),
            _format_count(stats.avg_context),
            _format_count(stats.max_context),
            _format_count(stats.total_read),
            _format_count(stats.new_input),
            _format_count(stats.output),
            ",".join(sorted(stats.variants)) or "-",
        ]
        for stats in results
    ]
    totals_row = _totals_row(results)
    widths = [
        max(len(row[index]) for row in [TABLE_HEADERS, *rows, totals_row]) for index in range(8)
    ]
    lines = [
        _format_row(TABLE_HEADERS, widths),
        _format_row(["-" * width for width in widths], widths),
    ]
    lines.extend(_format_row(row, widths) for row in rows)
    if len(results) > 1:
        lines.append(_format_row(totals_row, widths))
    return "\n".join(lines)


def _totals(results: list[SessionStats]) -> dict[str, Any]:
    steps = sum(stats.steps for stats in results)
    total_read = sum(stats.total_read for stats in results)
    variants: set[str] = set()
    for stats in results:
        variants |= stats.variants
    return {
        "session_count": len(results),
        "steps": steps,
        "avg_context": total_read / steps if steps else 0.0,
        "max_context": max((stats.max_context for stats in results), default=0),
        "total_read": total_read,
        "new_input": sum(stats.new_input for stats in results),
        "output": sum(stats.output for stats in results),
        "variants": sorted(variants),
    }


def _totals_row(results: list[SessionStats]) -> list[str]:
    totals = _totals(results)
    return [
        "합계",
        str(totals["steps"]),
        _format_count(totals["avg_context"]),
        _format_count(totals["max_context"]),
        _format_count(totals["total_read"]),
        _format_count(totals["new_input"]),
        _format_count(totals["output"]),
        ",".join(totals["variants"]) or "-",
    ]


def build_json(results: list[SessionStats]) -> dict[str, Any]:
    return {
        "schema": JSON_SCHEMA,
        "sessions": [stats.as_dict() for stats in results],
        "totals": _totals(results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenCode 세션 내보내기에서 스텝·컨텍스트·적용 variant 를 집계합니다.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--export",
        nargs="+",
        metavar="파일",
        help="opencode session export 로 받은 JSON 파일 경로 목록",
    )
    source.add_argument(
        "--directory-suffix",
        metavar="문자열",
        help="opencode session list 에서 directory 가 이 접미사로 끝나는 세션만 집계합니다",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"session list 로 조회할 최대 세션 수 (기본 {DEFAULT_LIMIT})",
    )
    parser.add_argument("--json", action="store_true", help="표 대신 JSON 으로 출력합니다")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        print("오류: --limit 은 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.export:
        results = collect_from_exports([Path(path) for path in args.export])
    else:
        try:
            results = collect_from_directory(args.directory_suffix, args.limit)
        except (OSError, RuntimeError) as exc:
            print(f"오류: 세션 목록을 가져오지 못했습니다: {exc}", file=sys.stderr)
            return 2
    if not results:
        print("오류: 집계할 세션이 없습니다.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(build_json(results), ensure_ascii=False, indent=2))
    else:
        print(format_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
