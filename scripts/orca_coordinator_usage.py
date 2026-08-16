"""
scripts/orca_coordinator_usage.py

Claude Code 세션 트랜스크립트(.jsonl)에서 지정한 시간 창의 코디네이터 토큰 사용량을 집계합니다.

중복 제거 이유:
  Claude Code 는 스트리밍 청크 및 점진적 도구 실행 시 동일한 message.id 를 가진 레코드를
  여러 줄에 걸쳐 출력합니다. 이를 단순 합산할 경우 토큰이 약 1.9배 이상 과대 계상되므로
  message.id(부재 시 최상위 uuid)를 기준으로 중복을 반드시 제거해야 정확한 토큰 측정이 가능합니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def project_slug(project_dir: Path) -> str:
    """프로젝트 절대 경로의 슬래시(/)와 밑줄(_)을 모두 하이픈(-)으로 변환합니다."""
    resolved = project_dir.resolve()
    path_str = str(resolved)
    return path_str.replace("/", "-").replace("_", "-")


def default_transcript_dir(project_dir: Path) -> Path:
    """기본 Claude Code 프로젝트 트랜스크립트 디렉터리 경로를 반환합니다."""
    slug = project_slug(project_dir)
    return Path.home() / ".claude" / "projects" / slug


def _parse_iso(value: str | datetime | None) -> datetime | None:
    """ISO 8601 일시 문자열을 UTC datetime 으로 변환합니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    val = str(value).strip()
    if not val:
        return None
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def iter_usage_records(path: Path) -> Iterator[tuple[dict[str, Any] | None, bool]]:
    """JSONL 파일을 한 줄씩 읽어 (parsed_record, is_malformed) 튜플을 생성합니다.

    message.usage 가 있는 유효 레코드의 경우 (dict, False)를 반환하고,
    JSON 파싱 실패 시 (None, True)를 반환합니다.
    usage 가 없는 정상 JSON 줄은 무시됩니다.
    """
    if not path.exists() or not path.is_file():
        return

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    yield None, True
                    continue

                if isinstance(obj, dict):
                    msg = obj.get("message")
                    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                        yield obj, False
    except OSError:
        return


def collect_usage(
    paths: list[Path] | Path,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    include_sidechain: bool = False,
) -> dict[str, Any]:
    """트랜스크립트 파일들에서 중복을 제거하고 시간 창 내의 코디네이터 토큰 사용량을 집계합니다."""
    file_list: list[Path] = [paths] if isinstance(paths, Path) else list(paths)

    since_dt = _parse_iso(since)
    until_dt = _parse_iso(until)
    has_window = since_dt is not None or until_dt is not None

    seen_ids: set[str] = set()
    contributing_sessions: set[str] = set()

    uncached_in = 0
    cache_create_in = 0
    cache_read_in = 0
    total_out = 0
    messages_counted = 0
    duplicates_dropped = 0
    malformed_lines = 0
    undated_skipped = 0
    sidechain_skipped = 0

    collected_timestamps: list[datetime] = []

    for fpath in file_list:
        for record, is_malformed in iter_usage_records(fpath):
            if is_malformed:
                malformed_lines += 1
                continue
            if record is None:
                continue

            msg = record.get("message", {})
            rec_id = msg.get("id") or record.get("uuid")
            if not rec_id:
                rec_id = record.get("requestId")
            if not rec_id:
                continue

            rec_id_str = str(rec_id)
            if rec_id_str in seen_ids:
                duplicates_dropped += 1
                continue

            # sidechain 필터
            if record.get("isSidechain") and not include_sidechain:
                sidechain_skipped += 1
                continue

            # timestamp 필터
            ts_val = record.get("timestamp")
            dt = _parse_iso(ts_val)

            if has_window and dt is None:
                undated_skipped += 1
                continue

            if since_dt is not None and dt is not None and dt < since_dt:
                continue
            if until_dt is not None and dt is not None and dt > until_dt:
                continue

            # 창 안에 포함된 고유 메시지 확정
            seen_ids.add(rec_id_str)
            contributing_sessions.add(fpath.name)
            messages_counted += 1
            if dt is not None:
                collected_timestamps.append(dt)

            usage = msg.get("usage", {})
            u_in = int(usage.get("input_tokens") or 0)
            u_cc = int(usage.get("cache_creation_input_tokens") or 0)
            u_cr = int(usage.get("cache_read_input_tokens") or 0)
            u_out = int(usage.get("output_tokens") or 0)

            uncached_in += u_in
            cache_create_in += u_cc
            cache_read_in += u_cr
            total_out += u_out

    if messages_counted > 0:
        total_in = uncached_in + cache_create_in + cache_read_in
        coord_in: int | None = total_in
        coord_out: int | None = total_out
        uncached_res: int | None = uncached_in
        cache_create_res: int | None = cache_create_in
        cache_read_res: int | None = cache_read_in
    else:
        coord_in = None
        coord_out = None
        uncached_res = None
        cache_create_res = None
        cache_read_res = None

    first_ts = min(collected_timestamps).isoformat() if collected_timestamps else None
    last_ts = max(collected_timestamps).isoformat() if collected_timestamps else None

    return {
        "coordinator_input_tokens": coord_in,
        "coordinator_output_tokens": coord_out,
        "uncached_input_tokens": uncached_res,
        "cache_creation_input_tokens": cache_create_res,
        "cache_read_input_tokens": cache_read_res,
        "messages_counted": messages_counted,
        "duplicates_dropped": duplicates_dropped,
        "malformed_lines": malformed_lines,
        "undated_skipped": undated_skipped,
        "sidechain_skipped": sidechain_skipped,
        "sessions": sorted(contributing_sessions),
        "window_start": since_dt.isoformat() if since_dt else None,
        "window_end": until_dt.isoformat() if until_dt else None,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """ArgumentParser 를 생성합니다."""
    parser = argparse.ArgumentParser(
        prog="orca_coordinator_usage",
        description="Claude Code 트랜스크립트에서 코디네이터 토큰 사용량을 집계합니다.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="프로젝트 디렉터리 경로 (기본: 현재 작업 디렉터리)",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        default=None,
        help="트랜스크립트 디렉터리 경로 (기본: ~/.claude/projects/<slug>)",
    )
    parser.add_argument(
        "--session",
        action="append",
        default=None,
        help="집계할 특정 세션 ID 또는 세션 파일명 (여러 번 지정 가능)",
    )
    parser.add_argument(
        "--all-sessions",
        action="store_true",
        help="디렉터리 내 모든 세션 파일을 집계에 포함합니다.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="시작 일시 필터 (ISO 8601)",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="종료 일시 필터 (ISO 8601)",
    )
    parser.add_argument(
        "--include-sidechain",
        action="store_true",
        help="사이드체인(isSidechain=True) 메시지를 집계에 포함합니다.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="결과를 순수 JSON 형식으로 stdout 에 출력합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점입니다."""
    parser = build_parser()
    args = parser.parse_args(argv)

    transcript_dir = (
        args.transcript_dir
        if args.transcript_dir is not None
        else default_transcript_dir(args.project_dir)
    )

    if not transcript_dir.exists() or not transcript_dir.is_dir():
        if not args.json:
            print(f"오류: 트랜스크립트 디렉터리가 없습니다: {transcript_dir}", file=sys.stderr)
        return 2

    # 세션 파일 결정
    if args.session:
        target_files: list[Path] = []
        for s in args.session:
            fname = s if s.endswith(".jsonl") else f"{s}.jsonl"
            p = transcript_dir / fname if not Path(s).is_absolute() else Path(s)
            if not p.exists():
                if not args.json:
                    print(f"오류: 세션 파일을 찾을 수 없습니다: {p}", file=sys.stderr)
                return 2
            target_files.append(p)
    elif args.all_sessions:
        target_files = sorted(transcript_dir.glob("*.jsonl"))
        if not target_files:
            if not args.json:
                print(
                    f"오류: 디렉터리에 트랜스크립트 파일이 없습니다: {transcript_dir}",
                    file=sys.stderr,
                )
            return 2
    else:
        all_jsonl = list(transcript_dir.glob("*.jsonl"))
        if not all_jsonl:
            if not args.json:
                print(
                    f"오류: 디렉터리에 트랜스크립트 파일이 없습니다: {transcript_dir}",
                    file=sys.stderr,
                )
            return 2
        # 가장 최근 수정된 세션 파일 하나 선택
        all_jsonl.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        newest = all_jsonl[0]
        target_files = [newest]
        print(f"단일 최신 세션 선택: {newest.name}", file=sys.stderr)

    usage = collect_usage(
        paths=target_files,
        since=args.since,
        until=args.until,
        include_sidechain=args.include_sidechain,
    )

    if args.json:
        print(json.dumps(usage, ensure_ascii=False, indent=2))
    else:
        print("============================================================")
        print("Claude Code 코디네이터 토큰 사용량 집계")
        print("============================================================")
        print(f"집계 세션 파일: {', '.join(usage['sessions']) or '(없음)'}")
        print(f"집계 메시지 수: {usage['messages_counted']:,}건")
        print(f"중복 제거 건수: {usage['duplicates_dropped']:,}건")
        print(f"손상 행 건수:   {usage['malformed_lines']:,}건")
        print(f"일시 미상 제외: {usage['undated_skipped']:,}건")
        print(f"사이드체인 제외: {usage['sidechain_skipped']:,}건")
        print("------------------------------------------------------------")
        if usage["coordinator_input_tokens"] is not None:
            print(f"  Uncached Input Tokens:      {usage['uncached_input_tokens']:>12,}")
            print(f"  Cache Creation Tokens:      {usage['cache_creation_input_tokens']:>12,}")
            print(f"  Cache Read Tokens:          {usage['cache_read_input_tokens']:>12,}")
            print(f"  Total Input Tokens (총입력): {usage['coordinator_input_tokens']:>12,}")
            print(f"  Output Tokens (출력):        {usage['coordinator_output_tokens']:>12,}")
        else:
            print("  창 내 메시지가 없어 토큰 값이 null 입니다.")
        print("============================================================")

    if usage["messages_counted"] > 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
