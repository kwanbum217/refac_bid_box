"""
scripts/orca_metrics_ledger.py

설계 23장의 v2 프록시 지표를 append-only JSONL 원장에 기록하고 집계합니다.

하위 명령:
  record  -- Capsule/보고에서 자동 도출한 값과 수동 입력값을 한 행으로 추가합니다.
  summary -- 누적된 행을 집계하여 통계를 출력합니다.

PyYAML 을 사용하지 않습니다. 표준 라이브러리(json, statistics, argparse, datetime)만 씁니다.
공용 파싱 헬퍼는 scripts/orca_contract.py 를 import 해서 씁니다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        char_len,
        load_capsule,
        load_report,
        parse_capsule_scalar,
        string_list,
    )
    from scripts.orca_coordinator_usage import collect_usage, default_transcript_dir
except (ModuleNotFoundError, ImportError):
    # 저장소 루트를 sys.path 에 추가해 python3 scripts/... 직접 실행을 지원합니다.
    # 형제 도구인 orca_level1_gate.py 와 summarize_worker_done.py 와 실행 방식을
    # 맞춥니다. 플레이북이 세 도구를 모두 python3 scripts/... 로 안내합니다.
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.orca_contract import (  # type: ignore[no-redef]
        char_len,
        load_capsule,
        load_report,
        parse_capsule_scalar,
        string_list,
    )
    from scripts.orca_coordinator_usage import (  # type: ignore[no-redef]
        collect_usage,
        default_transcript_dir,
    )

LEDGER_SCHEMA = "ORCA_V2_METRICS_ROW_1"
DEFAULT_LEDGER = "docs/ops/orca_v2_metrics_ledger.jsonl"


# --------------------------------------------------------------------------
# 내부 헬퍼
# --------------------------------------------------------------------------


def _now_iso() -> str:
    """로컬 시각을 ISO 8601 문자열로 반환합니다."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")  # noqa: UP017


def _load_rows(ledger_path: Path) -> tuple[list[dict[str, Any]], int]:
    """원장 파일을 읽고 유효 행과 손상 행 수를 반환합니다.

    파싱 실패 행은 조용히 넘기지 않고 개수를 셉니다.
    """
    rows: list[dict[str, Any]] = []
    corrupt = 0
    if not ledger_path.exists():
        return rows, corrupt
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                corrupt += 1
        except json.JSONDecodeError:
            corrupt += 1
    return rows, corrupt


def _median_or_null(values: list[float]) -> float | None:
    """유효 값이 없으면 None 을 반환합니다."""
    if not values:
        return None
    return statistics.median(values)


def _mean_or_null(values: list[float]) -> float | None:
    """유효 값이 없으면 None 을 반환합니다."""
    if not values:
        return None
    return statistics.mean(values)


def _collect_numeric(rows: list[dict[str, Any]], key: str) -> list[float]:
    """None 이나 불리언이 아닌 유효한 수치 값만 모읍니다."""
    out: list[float] = []
    for row in rows:
        v = row.get(key)
        if v is not None and not isinstance(v, bool):
            with contextlib.suppress(TypeError, ValueError):
                out.append(float(v))
    return out


def _metric_stats(rows: list[dict[str, Any]], key: str, total: int) -> dict[str, Any]:
    """지표 하나의 집계를 구합니다.

    유효 행 수, 중앙값, 평균, 표본 부족 여부를 포함합니다.
    """
    valid = _collect_numeric(rows, key)
    n = len(valid)
    few = n < 3
    return {
        "valid_count": n,
        "total_count": total,
        "median": _median_or_null(valid),
        "mean": _mean_or_null(valid),
        "insufficient_sample": few,
    }


# --------------------------------------------------------------------------
# record 하위 명령
# --------------------------------------------------------------------------


def cmd_record(args: argparse.Namespace) -> int:
    """Dispatch 한 건을 원장에 기록합니다."""
    ledger_path = Path(args.ledger)

    # Capsule 로드 및 자동 도출
    capsule_text = load_capsule(args.capsule)
    capsule_chars = char_len(capsule_text)

    # 보고 로드 및 자동 도출
    report_data = load_report(args.report)
    report_text = Path(args.report).read_text(encoding="utf-8")
    report_chars = char_len(report_text)

    read_files = string_list(report_data.get("read_files"))
    read_files_count = len(read_files)

    changed_files = string_list(report_data.get("changed_files"))
    changed_files_count = len(changed_files)

    verification = report_data.get("verification")
    verification_count = len(verification) if isinstance(verification, (list, dict)) else 0

    verdict = report_data.get("verdict") or None
    status = report_data.get("status") or None

    # 중복 검사: 같은 (task_id, dispatch_id) 는 재기록하지 않음
    existing_rows, _ = _load_rows(ledger_path)
    for row in existing_rows:
        if row.get("task_id") == args.task and row.get("dispatch_id") == args.dispatch:
            print(
                f"중복: task_id={args.task}, dispatch_id={args.dispatch} 가 이미 원장에 있습니다. "
                "덮어쓰지 않습니다.",
                file=sys.stderr,
            )
            return 1

    # 수동 입력값 (미지정 시 null)
    roundtrips: int | None = args.roundtrips
    first_useful_seconds: int | None = args.first_useful_seconds
    coordinator_input_tokens: int | None = args.coordinator_input_tokens
    coordinator_output_tokens: int | None = args.coordinator_output_tokens

    # 코디네이터 토큰 사용량 창 및 동시성 메타데이터
    usage_since = getattr(args, "usage_since", None)
    usage_until = getattr(args, "usage_until", None)
    usage_concurrent_arg = getattr(args, "usage_concurrent_dispatches", 1)
    usage_transcript_dir = getattr(args, "usage_transcript_dir", None)

    usage_window_start: str | None = None
    usage_window_end: str | None = None
    usage_concurrent_dispatches: int | None = None

    if usage_since:
        tdir = (
            Path(usage_transcript_dir)
            if usage_transcript_dir
            else default_transcript_dir(Path.cwd())
        )
        session_files = sorted(tdir.glob("*.jsonl")) if tdir.exists() and tdir.is_dir() else []
        if session_files:
            usage_res = collect_usage(session_files, since=usage_since, until=usage_until)
            if coordinator_input_tokens is None:
                coordinator_input_tokens = usage_res["coordinator_input_tokens"]
            if coordinator_output_tokens is None:
                coordinator_output_tokens = usage_res["coordinator_output_tokens"]
        usage_window_start = usage_since
        usage_window_end = usage_until
        usage_concurrent_dispatches = usage_concurrent_arg

    # 자동 도출: Capsule 의 task_id 교차 검증 (불일치 경고)
    capsule_task_id = parse_capsule_scalar(capsule_text, "task_id")
    if capsule_task_id and capsule_task_id != args.task:
        print(
            f"경고: Capsule 의 task_id({capsule_task_id})와 --task({args.task})가 다릅니다.",
            file=sys.stderr,
        )

    row: dict[str, Any] = {
        "ledger_schema": LEDGER_SCHEMA,
        "recorded_at": _now_iso(),
        "run_id": args.run,
        "task_id": args.task,
        "dispatch_id": args.dispatch,
        "role": args.role,
        "model": args.model,
        "capsule_path": str(args.capsule),
        "report_path": str(args.report),
        # 자동 도출
        "capsule_chars": capsule_chars,
        "report_chars": report_chars,
        "read_files_count": read_files_count,
        "changed_files_count": changed_files_count,
        "verification_count": verification_count,
        "verdict": verdict,
        "status": status,
        # 수동 입력 (null 허용)
        "roundtrips": roundtrips,
        "first_useful_seconds": first_useful_seconds,
        "coordinator_input_tokens": coordinator_input_tokens,
        "coordinator_output_tokens": coordinator_output_tokens,
        # 코디네이터 토큰 사용량 창 및 동시성 메타데이터
        "usage_window_start": usage_window_start,
        "usage_window_end": usage_window_end,
        "usage_concurrent_dispatches": usage_concurrent_dispatches,
    }

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
    else:
        print(f"기록 완료: task_id={args.task}, dispatch_id={args.dispatch}")
        print(f"  capsule_chars={capsule_chars}, report_chars={report_chars}")
        print(f"  read_files_count={read_files_count}, changed_files_count={changed_files_count}")
        print(f"  verdict={verdict}, status={status}")

    return 0


# --------------------------------------------------------------------------
# summary 하위 명령
# --------------------------------------------------------------------------


def cmd_summary(args: argparse.Namespace) -> int:
    """원장 전체 또는 필터된 행의 집계를 출력합니다."""
    ledger_path = Path(args.ledger)
    all_rows, corrupt_count = _load_rows(ledger_path)
    total_all = len(all_rows)

    # 필터 적용
    rows = all_rows
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"--since 형식 오류: '{args.since}' (YYYY-MM-DD 필요)", file=sys.stderr)
            return 1
        filtered: list[dict[str, Any]] = []
        for row in rows:
            ra = row.get("recorded_at", "")
            if ra:
                try:
                    row_dt = datetime.fromisoformat(ra)
                    if row_dt.date() >= since_dt.date():
                        filtered.append(row)
                except ValueError:
                    filtered.append(row)
            else:
                filtered.append(row)
        rows = filtered

    if args.role:
        rows = [r for r in rows if r.get("role") == args.role]
    if args.model:
        rows = [r for r in rows if r.get("model") == args.model]

    total = len(rows)

    # 코디네이터 토큰 집계 대상 행 (동시 실행 공유 창 usage_concurrent_dispatches >= 2 제외)
    concurrent_excluded_count = sum(
        1 for r in rows if (r.get("usage_concurrent_dispatches") or 1) >= 2
    )
    coord_rows = [r for r in rows if (r.get("usage_concurrent_dispatches") or 1) < 2]

    # 지표 집계
    numeric_metrics = [
        "capsule_chars",
        "report_chars",
        "read_files_count",
        "changed_files_count",
        "roundtrips",
        "first_useful_seconds",
        "coordinator_input_tokens",
        "coordinator_output_tokens",
    ]
    metric_stats: dict[str, dict[str, Any]] = {}
    for key in numeric_metrics:
        if key in ("coordinator_input_tokens", "coordinator_output_tokens"):
            metric_stats[key] = _metric_stats(coord_rows, key, total)
        else:
            metric_stats[key] = _metric_stats(rows, key, total)

    # verdict 분포
    verdict_dist: dict[str, int] = {}
    for row in rows:
        v = row.get("verdict")
        if v is not None:
            verdict_dist[str(v)] = verdict_dist.get(str(v), 0) + 1

    # 역할별 행 수
    role_counts: dict[str, int] = {}
    for row in rows:
        r = row.get("role") or "unknown"
        role_counts[r] = role_counts.get(r, 0) + 1

    # 모델별 행 수 및 report_chars 중앙값
    model_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        m = row.get("model") or "unknown"
        model_rows.setdefault(m, []).append(row)
    model_stats: dict[str, Any] = {}
    for model, mrows in model_rows.items():
        rc = _collect_numeric(mrows, "report_chars")
        model_stats[model] = {
            "count": len(mrows),
            "report_chars_median": _median_or_null(rc),
        }

    result: dict[str, Any] = {
        "total_rows": total,
        "total_all_rows": total_all,
        "corrupt_rows": corrupt_count,
        "concurrent_excluded_rows": concurrent_excluded_count,
        "metrics": metric_stats,
        "verdict_distribution": verdict_dist,
        "role_counts": role_counts,
        "model_stats": model_stats,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 사람이 읽는 출력
    print(f"원장 행 수: {total} (전체: {total_all}, 손상: {corrupt_count})")
    if corrupt_count > 0:
        print(f"  [주의] 손상된 행 {corrupt_count}개가 집계에서 제외됩니다.")
    if concurrent_excluded_count > 0:
        print(
            f"  [주의] 동시 실행 공유 창(usage_concurrent_dispatches >= 2) 행 "
            f"{concurrent_excluded_count}개는 코디네이터 토큰 집계에서 제외됩니다."
        )
    if total == 0:
        return 0

    print()
    print("지표별 집계:")
    for key in numeric_metrics:
        s = metric_stats[key]
        n = s["valid_count"]
        med = s["median"]
        avg = s["mean"]
        note = " [표본 부족]" if s["insufficient_sample"] else ""
        med_str = f"{med:.1f}" if med is not None else "null"
        avg_str = f"{avg:.1f}" if avg is not None else "null"
        print(f"  {key}: 유효 {n}/{total}행, 중앙값={med_str}, 평균={avg_str}{note}")

    print()
    print("verdict 분포:")
    if verdict_dist:
        for v, cnt in sorted(verdict_dist.items()):
            print(f"  {v}: {cnt}행")
    else:
        print("  (없음)")

    print()
    print("역할별 행 수:")
    for role, cnt in sorted(role_counts.items()):
        print(f"  {role}: {cnt}행")

    print()
    print("모델별 통계:")
    for model, ms in sorted(model_stats.items()):
        med = ms["report_chars_median"]
        med_str = f"{med:.1f}" if med is not None else "null"
        print(f"  {model}: {ms['count']}행, report_chars 중앙값={med_str}")

    return 0


# --------------------------------------------------------------------------
# CLI 진입점
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """ArgumentParser 를 구성합니다."""
    parser = argparse.ArgumentParser(
        prog="orca_metrics_ledger",
        description="Orca v2 프록시 지표 원장 도구",
    )
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"원장 JSONL 파일 경로 (기본: {DEFAULT_LEDGER})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # record
    rec = sub.add_parser("record", help="Dispatch 한 건을 원장에 기록합니다.")
    rec.add_argument("--run", required=True, help="Run ID")
    rec.add_argument("--task", required=True, help="Task ID")
    rec.add_argument("--dispatch", required=True, help="Dispatch ID")
    rec.add_argument(
        "--role",
        required=True,
        choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"],
        help="워커 역할",
    )
    rec.add_argument("--model", required=True, help="모델 식별자")
    rec.add_argument("--capsule", required=True, help="Capsule YAML 파일 경로")
    rec.add_argument("--report", required=True, help="보고 JSON 파일 경로")
    rec.add_argument("--roundtrips", type=int, default=None, help="왕복 횟수 (생략 가능)")
    rec.add_argument(
        "--first-useful-seconds", type=int, default=None, help="첫 유용 산출 소요 초 (생략 가능)"
    )
    rec.add_argument(
        "--coordinator-input-tokens",
        type=int,
        default=None,
        help="코디네이터 입력 토큰 (생략 가능)",
    )
    rec.add_argument(
        "--coordinator-output-tokens",
        type=int,
        default=None,
        help="코디네이터 출력 토큰 (생략 가능)",
    )
    rec.add_argument(
        "--usage-since",
        default=None,
        help="코디네이터 토큰 집계 시작 일시 (ISO 8601)",
    )
    rec.add_argument(
        "--usage-until",
        default=None,
        help="코디네이터 토큰 집계 종료 일시 (ISO 8601)",
    )
    rec.add_argument(
        "--usage-concurrent-dispatches",
        type=int,
        default=1,
        help="해당 시간 창을 공유한 동시 Dispatch 수 (기본: 1)",
    )
    rec.add_argument(
        "--usage-transcript-dir",
        type=Path,
        default=None,
        help="Claude Code 트랜스크립트 디렉터리 경로 (기본: ~/.claude/projects/<slug>)",
    )
    rec.add_argument("--json", action="store_true", help="JSON 형식으로 출력합니다.")

    # summary
    smr = sub.add_parser("summary", help="원장 집계를 출력합니다.")
    smr.add_argument("--since", default=None, help="시작 날짜 필터 (YYYY-MM-DD)")
    smr.add_argument("--role", default=None, help="역할 필터")
    smr.add_argument("--model", default=None, help="모델 필터")
    smr.add_argument("--json", action="store_true", help="JSON 형식으로 출력합니다.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점입니다."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "record":
        return cmd_record(args)
    if args.command == "summary":
        return cmd_summary(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
