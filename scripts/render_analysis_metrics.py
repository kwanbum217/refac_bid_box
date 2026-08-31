#!/usr/bin/env python3
"""
scripts/render_analysis_metrics.py

원시 측정 JSON 에서 마크다운 표 블록을 생성하고,
마커가 삽입된 문서를 원시 JSON 과 대조해 수치 일탈을 검사한다.

사용:
  # 표 블록 생성 (표준 출력)
  python3 scripts/render_analysis_metrics.py generate \\
    --json data/benchmarks/example.json \\
    --keys summary_cold.total_ms.p99_ms,summary_cold.sql_ms.max_ms

  # 문서 수치 검증 (마커 기반)
  python3 scripts/render_analysis_metrics.py verify \\
    --doc docs/analysis/example.md

종료 코드:
  0 - 통과
  1 - 수치 불일치 (verify 하위 명령)
  2 - 파일 없음 또는 키 경로 없음
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# 마커 패턴. 문서 안에 삽입되는 시작/끝 주석.
# <!-- METRICS_BEGIN json=<path> hash=<sha256_hex> -->
# <!-- METRICS_END -->
_MARKER_BEGIN_RE = re.compile(r"<!--\s*METRICS_BEGIN\s+json=(\S+)\s+hash=([0-9a-f]+)\s*-->")
_MARKER_END = "<!-- METRICS_END -->"


def _get_nested(obj: Any, key_path: str) -> Any:
    """점('.') 구분 키 경로로 중첩 값을 반환한다. 경로가 없으면 KeyError 를 올린다."""
    parts = key_path.split(".")
    cur = obj
    for part in parts:
        if not isinstance(cur, dict):
            raise KeyError(f"'{part}' 위 값이 dict 가 아님 (경로: {key_path})")
        if part not in cur:
            raise KeyError(f"키 없음: '{part}' (경로: {key_path})")
        cur = cur[part]
    return cur


def _file_hash(path: Path) -> str:
    """파일 내용의 SHA-256 16진수 문자열을 반환한다."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def _fmt_value(v: Any) -> str:
    """값을 마크다운 표 셀 문자열로 변환한다.

    정수로 딱 떨어지는 부동소수점은 정수로 표시하고,
    그 외는 Python repr 방식으로 유효 자릿수를 최대한 보존한다.
    """
    if isinstance(v, float):
        if not math.isnan(v) and v == int(v):
            return str(int(v))
        # repr 은 파이썬이 round-trip 보장하는 최소 자릿수를 사용한다.
        s = repr(v)
        return s

    return str(v)


def _build_table(data: dict[str, Any], key_paths: list[str]) -> str:
    """key_paths 목록에서 마크다운 표를 생성한다."""
    rows: list[tuple[str, str]] = []
    for kp in key_paths:
        val = _get_nested(data, kp)
        rows.append((kp, _fmt_value(val)))

    lines: list[str] = []
    lines.append("| 지표 | 값 |")
    lines.append("| --- | ---: |")
    for kp, val in rows:
        lines.append(f"| `{kp}` | {val} |")
    return "\n".join(lines)


def cmd_generate(args: argparse.Namespace) -> int:
    """generate 하위 명령: 마크다운 표 블록을 표준 출력으로 낸다."""
    json_path = Path(args.json)
    if not json_path.exists():
        print(f"오류: JSON 파일 없음: {json_path}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"오류: JSON 파싱 실패: {exc}", file=sys.stderr)
        return 2

    key_paths = [k.strip() for k in args.keys.split(",") if k.strip()]
    if not key_paths:
        print("오류: --keys 가 비어 있음", file=sys.stderr)
        return 2

    for kp in key_paths:
        try:
            _get_nested(raw, kp)
        except KeyError as exc:
            print(f"오류: 키 경로 없음: {exc}", file=sys.stderr)
            return 2

    file_hash = _file_hash(json_path)
    table = _build_table(raw, key_paths)

    print(f"<!-- METRICS_BEGIN json={json_path} hash={file_hash} -->")
    print(table)
    print(_MARKER_END)
    return 0


def _extract_blocks(doc_text: str) -> list[dict[str, Any]]:
    """문서 텍스트에서 METRICS 블록을 추출한다."""
    blocks: list[dict[str, Any]] = []
    lines = doc_text.splitlines()
    i = 0
    while i < len(lines):
        m = _MARKER_BEGIN_RE.match(lines[i].strip())
        if m:
            json_path_str, recorded_hash = m.group(1), m.group(2)
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                if lines[j].strip() == _MARKER_END:
                    break
                block_lines.append(lines[j])
                j += 1
            blocks.append(
                {
                    "json_path": json_path_str,
                    "recorded_hash": recorded_hash,
                    "block_lines": block_lines,
                    "begin_lineno": i + 1,  # 1-indexed
                }
            )
            i = j + 1
        else:
            i += 1
    return blocks


def _parse_table_rows(block_lines: list[str]) -> dict[str, str]:
    """마크다운 표 행에서 {key_path: value} 맵을 파싱한다."""
    rows: dict[str, str] = {}
    for line in block_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        kp_cell = cells[0].strip("`").strip()
        val_cell = cells[1].strip()
        # 헤더 및 구분선 건너뜀
        if kp_cell in ("지표", "---", "") or val_cell in ("값", "---:", "---"):
            continue
        rows[kp_cell] = val_cell
    return rows


def cmd_verify(args: argparse.Namespace) -> int:
    """verify 하위 명령: 마커 블록을 원시 JSON 과 대조한다."""
    doc_path = Path(args.doc)
    if not doc_path.exists():
        print(f"오류: 문서 없음: {doc_path}", file=sys.stderr)
        return 2

    doc_text = doc_path.read_text(encoding="utf-8")
    blocks = _extract_blocks(doc_text)

    if not blocks:
        # 마커 없는 문서는 대상 아님 -> 통과
        return 0

    any_error = False
    for blk in blocks:
        json_path = Path(blk["json_path"])
        recorded_hash = blk["recorded_hash"]

        if not json_path.exists():
            print(
                f"오류: 원시 JSON 없음 (문서 {doc_path}, 줄 {blk['begin_lineno']}): {json_path}",
                file=sys.stderr,
            )
            return 2

        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"오류: JSON 파싱 실패 ({json_path}): {exc}", file=sys.stderr)
            return 2

        # 해시 검증
        actual_hash = _file_hash(json_path)
        if actual_hash != recorded_hash:
            print(
                f"[해시 불일치] {json_path}\n"
                f"  기록된 해시: {recorded_hash}\n"
                f"  실제 해시:   {actual_hash}"
            )
            # 해시 불일치는 경고이지 종료 아님. 수치도 계속 검사한다.
            any_error = True

        # 문서에 기록된 행 파싱
        doc_rows = _parse_table_rows(blk["block_lines"])
        if not doc_rows:
            continue

        # 원시 JSON 에서 재생성
        diffs: list[str] = []
        missing_keys: list[str] = []
        for kp, doc_val in doc_rows.items():
            try:
                actual_val = _get_nested(raw, kp)
            except KeyError as exc:
                missing_keys.append(f"{kp}: {exc}")
                continue
            actual_str = _fmt_value(actual_val)
            if actual_str != doc_val:
                diffs.append(f"  {kp}: 문서={doc_val!r}  원시JSON={actual_str!r}")

        if missing_keys:
            for mk in missing_keys:
                print(f"오류: 키 경로 없음: {mk}", file=sys.stderr)
            return 2

        if diffs:
            print(f"[수치 불일치] 문서={doc_path}, JSON={json_path}")
            for d in diffs:
                print(d)
            any_error = True

    return 1 if any_error else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="원시 측정 JSON 에서 마크다운 표를 생성하고 문서 수치를 검증한다."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="마크다운 표 블록을 표준 출력으로 낸다")
    gen.add_argument("--json", required=True, help="원시 측정 JSON 경로")
    gen.add_argument(
        "--keys",
        required=True,
        help="쉼표(',') 구분 키 경로 목록 (예: summary_cold.total_ms.p99_ms)",
    )

    ver = sub.add_parser("verify", help="마커 블록을 원시 JSON 과 대조한다")
    ver.add_argument("--doc", required=True, help="검증할 마크다운 문서 경로")

    args = parser.parse_args()
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "verify":
        return cmd_verify(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
