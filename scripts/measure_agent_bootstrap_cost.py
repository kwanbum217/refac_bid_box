#!/usr/bin/env python3
"""
에이전트 부트스트랩 비용(Proxy 지표: 문자 수) 측정 스크립트.

설계 23장 성공 지표 측정 도구:
  - 5개 CLI 진입점(Codex, opencode, Antigravity, Claude Code, Cursor)별로
    자동 주입되는 규칙/설정 문서의 문자 수를 측정합니다.
  - 바이트가 아닌 문자 수(len())를 기준으로 계산하며, 각 진입점별 권장 예산 대비
    사용 비율을 표 및 JSON 형식으로 제공합니다.

사용:
  python3 scripts/measure_agent_bootstrap_cost.py          # 기본 표 출력
  python3 scripts/measure_agent_bootstrap_cost.py --json   # JSON 출력
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 기본 권장 예산 (문자 수 기준)
DEFAULT_BUDGETS: dict[str, int] = {
    "Codex": 8000,
    "opencode": 8000,
    "Antigravity": 12000,
    "Claude Code": 8000,
    "Cursor": 12000,
}


def read_text(path: Path) -> str:
    """UTF-8 텍스트 파일을 안전하게 읽어 반환합니다. 부재 시 빈 문자열."""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def measure_codex_cost(root: Path = PROJECT_ROOT, budget: int | None = None) -> dict[str, Any]:
    """Codex 진입점 측정: AGENTS.md 단일 정본."""
    allocated_budget = budget if budget is not None else DEFAULT_BUDGETS["Codex"]
    rel_path = "AGENTS.md"
    file_path = root / rel_path
    content = read_text(file_path)
    char_count = len(content)
    exists = file_path.exists()
    ratio = round(char_count / allocated_budget, 4) if allocated_budget > 0 else 0.0
    ratio_pct = round(ratio * 100, 2)
    within_budget = char_count <= allocated_budget

    return {
        "cli": "Codex",
        "description": "AGENTS.md 단일 정본",
        "paths": [rel_path],
        "display_path": rel_path,
        "exists": exists,
        "char_count": char_count,
        "budget": allocated_budget,
        "ratio": ratio,
        "ratio_pct": ratio_pct,
        "within_budget": within_budget,
        "status": "PASS" if within_budget else "EXCEEDED",
    }


def measure_opencode_cost(root: Path = PROJECT_ROOT, budget: int | None = None) -> dict[str, Any]:
    """opencode 진입점 측정: opencode.json 에 명시된 instructions 문서."""
    allocated_budget = budget if budget is not None else DEFAULT_BUDGETS["opencode"]
    config_rel = "opencode.json"
    config_path = root / config_rel
    exists = config_path.exists()

    paths: list[str] = []
    char_count = 0

    if exists:
        try:
            cfg = json.loads(read_text(config_path))
            instructions = cfg.get("instructions", [])
            if isinstance(instructions, list):
                paths = [str(item) for item in instructions]
            elif isinstance(instructions, str):
                paths = [instructions]
        except Exception:
            paths = ["AGENTS.md"]
    else:
        paths = ["AGENTS.md"]

    if not paths:
        paths = ["AGENTS.md"]

    for p in paths:
        target = root / p
        char_count += len(read_text(target))

    ratio = round(char_count / allocated_budget, 4) if allocated_budget > 0 else 0.0
    ratio_pct = round(ratio * 100, 2)
    within_budget = char_count <= allocated_budget

    display_path = f"{', '.join(paths)} (via {config_rel})" if exists else ", ".join(paths)

    return {
        "cli": "opencode",
        "description": "opencode.json instructions 자동 주입",
        "paths": paths,
        "config_path": config_rel,
        "display_path": display_path,
        "exists": exists,
        "char_count": char_count,
        "budget": allocated_budget,
        "ratio": ratio,
        "ratio_pct": ratio_pct,
        "within_budget": within_budget,
        "status": "PASS" if within_budget else "EXCEEDED",
    }


def measure_antigravity_cost(
    root: Path = PROJECT_ROOT, budget: int | None = None
) -> dict[str, Any]:
    """Antigravity 진입점 측정: .antigravity/rules.md."""
    allocated_budget = budget if budget is not None else DEFAULT_BUDGETS["Antigravity"]
    rel_path = ".antigravity/rules.md"
    file_path = root / rel_path
    content = read_text(file_path)
    char_count = len(content)
    exists = file_path.exists()
    ratio = round(char_count / allocated_budget, 4) if allocated_budget > 0 else 0.0
    ratio_pct = round(ratio * 100, 2)
    within_budget = char_count <= allocated_budget

    return {
        "cli": "Antigravity",
        "description": ".antigravity/rules.md 자동 주입",
        "paths": [rel_path],
        "display_path": rel_path,
        "exists": exists,
        "char_count": char_count,
        "budget": allocated_budget,
        "ratio": ratio,
        "ratio_pct": ratio_pct,
        "within_budget": within_budget,
        "status": "PASS" if within_budget else "EXCEEDED",
    }


def measure_claude_cost(root: Path = PROJECT_ROOT, budget: int | None = None) -> dict[str, Any]:
    """Claude Code 진입점 측정: CLAUDE.md thin pointer."""
    allocated_budget = budget if budget is not None else DEFAULT_BUDGETS["Claude Code"]
    rel_path = "CLAUDE.md"
    file_path = root / rel_path
    content = read_text(file_path)
    char_count = len(content)
    exists = file_path.exists()
    ratio = round(char_count / allocated_budget, 4) if allocated_budget > 0 else 0.0
    ratio_pct = round(ratio * 100, 2)
    within_budget = char_count <= allocated_budget

    return {
        "cli": "Claude Code",
        "description": "CLAUDE.md thin pointer",
        "paths": [rel_path],
        "display_path": rel_path,
        "exists": exists,
        "char_count": char_count,
        "budget": allocated_budget,
        "ratio": ratio,
        "ratio_pct": ratio_pct,
        "within_budget": within_budget,
        "status": "PASS" if within_budget else "EXCEEDED",
    }


def measure_cursor_cost(root: Path = PROJECT_ROOT, budget: int | None = None) -> dict[str, Any]:
    """Cursor 진입점 측정: .cursor/rules/*.mdc 규칙 파일 모음."""
    allocated_budget = budget if budget is not None else DEFAULT_BUDGETS["Cursor"]
    rules_dir = root / ".cursor" / "rules"
    paths: list[str] = []
    char_count = 0
    exists = rules_dir.exists()

    if exists and rules_dir.is_dir():
        matched_files = sorted(
            [
                p
                for p in rules_dir.iterdir()
                if p.is_file() and (p.suffix == ".mdc" or p.suffix == ".md")
            ]
        )
        for f in matched_files:
            rel = f".cursor/rules/{f.name}"
            paths.append(rel)
            char_count += len(read_text(f))
    else:
        fallback = ".cursor/rules/00-core-guidelines.mdc"
        paths.append(fallback)
        char_count = len(read_text(root / fallback))

    ratio = round(char_count / allocated_budget, 4) if allocated_budget > 0 else 0.0
    ratio_pct = round(ratio * 100, 2)
    within_budget = char_count <= allocated_budget

    display_path = (
        f".cursor/rules/ ({len(paths)}개 파일)"
        if len(paths) > 1
        else (paths[0] if paths else ".cursor/rules/")
    )

    return {
        "cli": "Cursor",
        "description": ".cursor/rules/ 규칙 세트",
        "paths": paths,
        "display_path": display_path,
        "exists": exists,
        "char_count": char_count,
        "budget": allocated_budget,
        "ratio": ratio,
        "ratio_pct": ratio_pct,
        "within_budget": within_budget,
        "status": "PASS" if within_budget else "EXCEEDED",
    }


def measure_all_clis(
    root: Path = PROJECT_ROOT,
    budgets: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """5개 CLI 진입점의 부트스트랩 비용을 순차 측정하여 목록으로 반환합니다."""
    b = budgets or {}
    return [
        measure_codex_cost(root, budget=b.get("Codex")),
        measure_opencode_cost(root, budget=b.get("opencode")),
        measure_antigravity_cost(root, budget=b.get("Antigravity")),
        measure_claude_cost(root, budget=b.get("Claude Code")),
        measure_cursor_cost(root, budget=b.get("Cursor")),
    ]


def build_report(
    root: Path = PROJECT_ROOT,
    budgets: dict[str, int] | None = None,
) -> dict[str, Any]:
    """부트스트랩 측정 전체 보고서 딕셔너리를 생성합니다."""
    entries = measure_all_clis(root, budgets=budgets)
    all_within = all(e["within_budget"] for e in entries)
    total_chars = sum(e["char_count"] for e in entries)
    max_entry = max(entries, key=lambda e: e["char_count"]) if entries else None

    return {
        "schema": "ORCA_BOOTSTRAP_COST_REPORT_V1",
        "version": "1.0.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "total_clis": len(entries),
        "all_within_budget": all_within,
        "total_chars_across_clis": total_chars,
        "max_char_cli": max_entry["cli"] if max_entry else "",
        "max_char_count": max_entry["char_count"] if max_entry else 0,
        "entries": entries,
    }


def format_table(report: dict[str, Any]) -> str:
    """측정 보고서를 터미널 표 형식으로 렌더링합니다."""
    entries: list[dict[str, Any]] = report.get("entries", [])
    lines: list[str] = [
        "=" * 82,
        "에이전트 부트스트랩 비용 측정 (설계 23장 Proxy 지표: 문자 수 기준)",
        "=" * 82,
        f"{'CLI':<14} {'자동 로드 문서 경로':<34} {'문자 수':>8} {'예산':>8} {'사용률':>8} {'상태':>6}",
        "-" * 82,
    ]

    for e in entries:
        cli = e.get("cli", "")
        disp_path = e.get("display_path", "")
        if len(disp_path) > 33:
            disp_path = disp_path[:30] + "..."
        chars = f"{e.get('char_count', 0):,}"
        budget = f"{e.get('budget', 0):,}"
        ratio_pct = f"{e.get('ratio_pct', 0.0):.1f}%"
        status = e.get("status", "PASS")
        lines.append(f"{cli:<14} {disp_path:<34} {chars:>8} {budget:>8} {ratio_pct:>8} {status:>6}")

    lines.append("-" * 82)
    all_within = report.get("all_within_budget", True)
    summary_status = "모두 예산 이내" if all_within else "일부 예산 초과"
    lines.append(f"총 {len(entries)}개 CLI 진입점 측정 완료 ({summary_status}).")
    lines.append("=" * 82)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="에이전트 부트스트랩 비용(문자 수) 측정")
    parser.add_argument("--json", action="store_true", help="JSON 형식으로 출력")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="프로젝트 루트 디렉터리")
    args = parser.parse_args()

    report = build_report(root=args.root)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_table(report))

    return 0 if report.get("all_within_budget", True) else 1


if __name__ == "__main__":
    sys.exit(main())
