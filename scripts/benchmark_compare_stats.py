"""GET /api/v1/bids/compare-stats 종단 시간의 쿼리별 귀속 측정 하네스.

src/app/services/dashboard.py 의 get_compare_stats_data 는
settings.LATENCY_SEGMENT_LOGGING 이 켜져 있을 때 요청마다
compare_stats_segments=<JSON> 한 줄을 로그에 남깁니다.

본 하네스는 회차마다 종단 wall time 을 재고, 각 회차 호출 직전에 기억해 둔
로그 위치 이후에 새로 나타난 줄만 후보로 삼아 회차와 짝짓습니다. 후보가
없거나 둘 이상이면 그 회차를 유효한 표본으로 세지 않고 이유와 함께 결과
JSON 에 기록합니다. 조용히 버리거나 추측으로 채우지 않습니다.

결과 JSON 에는 회차별 원값과 구간별 집계(P50, 최소, 최대, 합계)를 모두
남기고 git_sha 와 측정 시각과 캐시 적중 여부를 남깁니다.

주의: 이 하네스는 Redis 키 삭제와 컨테이너 로그 읽기를 하므로 읽기 전용이
아닙니다. scripts/orca_auto_approve.py 의 자동 승인 화이트리스트에 등록하지
마십시오. 캐시 삭제는 --evict-cache 를 줄 때만 하며 기본값은 삭제하지
않습니다.

본 스크립트는 최적화를 하지 않으며 측정 도구만 제공합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

# 구간 이름의 정본은 src/app/core/latency_segments.py 의
# COMPARE_STATS_SEGMENT_NAMES 이며, 하네스가 앱 설정 없이 단독으로 돌 수 있게
# 같은 값을 여기도 적어 둡니다. 이름을 바꾸면 양쪽을 함께 바꾸십시오.
SEGMENT_NAMES: tuple[str, ...] = (
    "announcement_summary",
    "result_summary",
    "cache_lookup",
    "matched_count",
    "announce_by_month",
    "result_by_month",
    "agency_announce_top10",
    "cache_store",
    "result_assembly",
)

LOG_MARKER = "compare_stats_segments="

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CONTAINER = "refac_bid_box-app-1"
DEFAULT_REDIS_CONTAINER = "refac_bid_box-redis-1"
DEFAULT_CACHE_KEY_PATTERN = "dashboard_compare_stats:*"
COMPARE_STATS_PATH = "/api/v1/bids/compare-stats"

REASON_NO_CANDIDATE = "no_candidate"
REASON_AMBIGUOUS = "ambiguous"
REASON_PARSE_ERROR = "parse_error"

__all__ = [
    "COMPARE_STATS_PATH",
    "DEFAULT_BASE_URL",
    "DEFAULT_CACHE_KEY_PATTERN",
    "DEFAULT_CONTAINER",
    "DEFAULT_REDIS_CONTAINER",
    "LOG_MARKER",
    "REASON_AMBIGUOUS",
    "REASON_NO_CANDIDATE",
    "REASON_PARSE_ERROR",
    "SEGMENT_NAMES",
    "build_evict_commands",
    "classify_round",
    "main",
    "pair_round_candidates",
    "parse_compare_stats_line",
    "parse_compare_stats_lines",
    "percentile_ms",
    "send_compare_stats_request",
    "summarize_rounds",
    "summarize_values",
]


def _extract_json_object(text: str) -> str | None:
    """문자열 앞부분의 균형 잡힌 JSON 객체 조각을 떼어냅니다.

    컨테이너 로그는 줄 앞뒤에 시각 같은 접두사나 접미사를 붙이므로, 표시 뒤의
    나머지 전체를 JSON 으로 해석하면 깨집니다. 중괄호 균형을 세어 객체 조각만
    분리합니다.
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
    return None


def parse_compare_stats_line(line: str) -> dict[str, Any] | None:
    """로그 한 줄에서 compare_stats_segments JSON 을 뽑습니다. 없거나 깨졌으면 None 입니다."""
    idx = line.find(LOG_MARKER)
    if idx < 0:
        return None
    rest = line[idx + len(LOG_MARKER) :].strip()
    if not rest:
        return None
    raw = _extract_json_object(rest)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def parse_compare_stats_lines(raw_log: str) -> list[dict[str, Any]]:
    """컨테이너 로그 전체에서 구간 줄만 뽑아 순서대로 돌려줍니다."""
    records: list[dict[str, Any]] = []
    if not raw_log or raw_log == "unknown":
        return records
    for line in raw_log.splitlines():
        if LOG_MARKER not in line:
            continue
        parsed = parse_compare_stats_line(line)
        if parsed is not None:
            records.append(parsed)
    return records


def pair_round_candidates(all_lines: list[str], start_index: int) -> list[str]:
    """회차 호출 직전 로그 위치 이후에 새로 나타난 구간 줄만 후보로 삼습니다.

    all_lines 는 호출 이후에 읽은 전체 로그 줄 목록이며, start_index 는 호출
    직전에 기억해 둔 줄 수입니다. 비동기로 쌓이는 로그를 마지막 줄 하나로
    대신 집으면 이전 회차의 것을 집을 수 있으므로, 경계 이후만 봅니다.
    """
    if start_index < 0:
        start_index = 0
    return [line for line in all_lines[start_index:] if LOG_MARKER in line]


def classify_round(index: int, wall_ms: float, candidates: list[str]) -> dict[str, Any]:
    """한 회차의 짝짓기 결과를 판정합니다.

    후보가 정확히 하나일 때만 유효한 표본으로 삼습니다. 후보가 없거나 둘
    이상이면 무효로 기록하고 이유를 남깁니다.
    """
    base: dict[str, Any] = {"index": index, "wall_ms": round(float(wall_ms), 2)}
    if not candidates:
        return {**base, "valid": False, "invalid_reason": REASON_NO_CANDIDATE}
    if len(candidates) > 1:
        return {
            **base,
            "valid": False,
            "invalid_reason": REASON_AMBIGUOUS,
            "candidate_count": len(candidates),
        }
    parsed = parse_compare_stats_line(candidates[0])
    if parsed is None:
        return {**base, "valid": False, "invalid_reason": REASON_PARSE_ERROR}
    segments = parsed.get("segments") if isinstance(parsed, dict) else None
    entry: dict[str, Any] = {
        **base,
        "valid": True,
        "invalid_reason": None,
        "cache_hit": parsed.get("cache_hit"),
        "segments": dict(segments) if isinstance(segments, dict) else {},
        "cursor_ms": parsed.get("cursor_ms"),
        "cursor_count": parsed.get("cursor_count"),
        "total_ms": parsed.get("total_ms"),
        "residual_ms": parsed.get("residual_ms"),
        "raw_line": candidates[0].strip(),
    }
    return entry


def percentile_ms(values: list[float], pct: float) -> float | None:
    """선형 보간 분위수를 구합니다. 값이 없으면 None 입니다."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def summarize_values(values: list[float]) -> dict[str, Any] | None:
    """한 지표의 관측값 목록을 집계합니다. 값이 없으면 None 입니다."""
    if not values:
        return None
    return {
        "n": len(values),
        "p50_ms": percentile_ms(values, 50),
        "min_ms": min(values),
        "max_ms": max(values),
        "sum_ms": sum(values),
    }


def summarize_rounds(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """유효한 회차만 모아 wall time 과 구간별 집계를 만듭니다.

    무효 회차는 집계에서 제외되며, 제외 내역은 invalid_rounds 에 남습니다.
    """
    valid = [entry for entry in rounds if entry.get("valid")]
    by_segment: dict[str, Any] = {}
    for name in SEGMENT_NAMES:
        values: list[float] = []
        for entry in valid:
            segments = entry.get("segments") or {}
            try:
                values.append(float(segments[name]))  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                continue
        summary = summarize_values(values)
        if summary is not None:
            by_segment[name] = summary
    wall_values = [float(entry["wall_ms"]) for entry in valid]
    cursor_values: list[float] = []
    for entry in valid:
        try:
            cursor_values.append(float(entry["cursor_ms"]))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return {
        "valid_rounds": len(valid),
        "invalid_rounds": len(rounds) - len(valid),
        "wall_ms": summarize_values(wall_values),
        "by_segment": by_segment,
        "cursor_ms": summarize_values(cursor_values),
    }


def send_compare_stats_request(base_url: str, timeout_sec: float) -> tuple[float, bool, str | None]:
    """compare-stats 한 회차를 호출하고 wall time, 성공 여부, 오류 메시지를 돌려줍니다."""
    req = urlrequest.Request(  # nosec B310
        f"{base_url.rstrip('/')}{COMPARE_STATS_PATH}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as response:  # nosec B310
            response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return elapsed_ms, True, None
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        reason = (
            "timeout"
            if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
            else (
                "transport_error"
                if isinstance(exc, (urlerror.URLError, OSError))
                else type(exc).__name__
            )
        )
        return elapsed_ms, False, f"{reason}: {exc}"


def build_evict_commands(redis_container: str, pattern: str) -> list[list[str]]:
    """비교 통계 캐시 키 삭제에 쓸 docker 명령 목록을 만듭니다. 실행하지는 않습니다."""
    return [
        ["docker", "exec", redis_container, "redis-cli", "KEYS", pattern],
    ]


def _command_output(command: list[str], cwd: Path | None = None) -> str:
    project_root = Path(__file__).resolve().parents[1]
    target = cwd if cwd is not None else project_root
    try:
        out = subprocess.check_output(  # nosec B603
            command,
            cwd=target,
            text=True,
            stderr=subprocess.STDOUT,
        )
        return out if out.strip() else "unknown"
    except (OSError, subprocess.CalledProcessError) as exc:
        output = getattr(exc, "output", "") or ""
        return output if isinstance(output, str) and output.strip() else "unknown"


def _fetch_log_lines(container: str, command_runner: Any = None) -> list[str]:
    runner = command_runner or _command_output
    raw = runner(["docker", "logs", container])
    if not isinstance(raw, str) or not raw.strip() or raw == "unknown":
        return []
    return raw.splitlines()


def _container_env_flag(container: str, name: str, command_runner: Any = None) -> str | None:
    runner = command_runner or _command_output
    raw = runner(["docker", "inspect", "-f", "{{json .Config.Env}}", container])
    if not isinstance(raw, str) or not raw.strip() or raw == "unknown":
        return None
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key == name:
            return value
    return None


def _evict_compare_stats_cache(
    redis_container: str, pattern: str, command_runner: Any = None
) -> dict[str, Any]:
    """비교 통계 캐시 키를 삭제합니다. --evict-cache 를 줄 때만 호출됩니다."""
    runner = command_runner or _command_output
    raw = runner(["docker", "exec", redis_container, "redis-cli", "KEYS", pattern])
    if not isinstance(raw, str) or not raw.strip() or raw == "unknown":
        return {"deleted": 0, "keys": [], "error": "키 목록 조회 실패"}
    keys = [line.strip() for line in raw.splitlines() if line.strip()]
    if not keys:
        return {"deleted": 0, "keys": [], "error": None}
    deleted = 0
    for key in keys:
        result = runner(["docker", "exec", redis_container, "redis-cli", "DEL", key])
        if isinstance(result, str) and result.strip().startswith("1"):
            deleted += 1
    return {"deleted": deleted, "keys": keys, "error": None}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="compare-stats 구간 귀속 측정 하네스")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--rounds", type=int, default=5, help="측정 회차 수")
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--target-container", default=DEFAULT_CONTAINER)
    parser.add_argument("--redis-container", default=DEFAULT_REDIS_CONTAINER)
    parser.add_argument("--cache-key-pattern", default=DEFAULT_CACHE_KEY_PATTERN)
    parser.add_argument(
        "--evict-cache",
        action="store_true",
        default=False,
        help="각 회차 전에 비교 통계 캐시 키를 삭제해 미적중을 만듭니다. 기본값은 삭제하지 않음",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    command_runner: Any = None,
    request_sender: Any = None,
) -> int:
    args = parse_args(argv)
    if args.rounds < 1:
        print("회차 수(--rounds)는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    cmd_fn = command_runner or _command_output
    request_fn = request_sender or send_compare_stats_request

    flag = _container_env_flag(args.target_container, "LATENCY_SEGMENT_LOGGING", cmd_fn)
    if flag is None or flag.strip().lower() not in {"1", "true", "yes", "on"}:
        print(
            f"컨테이너 {args.target_container} 의 LATENCY_SEGMENT_LOGGING 이 켜져 있지 않습니다 "
            f"(현재 값: {flag!r}). 구간 줄이 없으면 회차 짝짓기가 전부 무효가 되므로 "
            "측정 전에 플래그를 켜고 app 을 재기동하십시오."
        )
        return 2

    git_sha = cmd_fn(["git", "rev-parse", "HEAD"])
    if git_sha == "unknown":
        git_sha = None

    rounds: list[dict[str, Any]] = []
    for index in range(args.rounds):
        if args.evict_cache:
            _evict_compare_stats_cache(args.redis_container, args.cache_key_pattern, cmd_fn)
        lines_before = _fetch_log_lines(args.target_container, cmd_fn)
        start_index = len(lines_before)
        wall_ms, ok, error = request_fn(args.base_url, args.timeout_sec)
        lines_after = _fetch_log_lines(args.target_container, cmd_fn)
        candidates = pair_round_candidates(lines_after, start_index)
        entry = classify_round(index, wall_ms, candidates)
        entry["http_ok"] = bool(ok)
        entry["http_error"] = error
        rounds.append(entry)

    summary = summarize_rounds(rounds)
    payload = {
        "git_sha": git_sha,
        "measured_at": datetime.now(UTC).isoformat(),
        "config": {
            "base_url": args.base_url,
            "rounds": args.rounds,
            "timeout_sec": args.timeout_sec,
            "target_container": args.target_container,
            "redis_container": args.redis_container,
            "cache_key_pattern": args.cache_key_pattern,
            "evict_cache": bool(args.evict_cache),
        },
        "rounds": rounds,
        "summary": summary,
        "cache_hits": sum(1 for entry in rounds if entry.get("cache_hit") is True),
        "cache_misses": sum(1 for entry in rounds if entry.get("cache_hit") is False),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"결과를 {args.output} 에 저장했습니다.")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
