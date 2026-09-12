#!/usr/bin/env python3
"""스킬 정본을 CLI 별 미러 디렉터리로 복제합니다.

`.agents/skills/` 가 정본이고 `.claude/skills/` 와 `.opencode/skills/` 는 각 CLI 가
스킬을 탐색하는 고정 경로입니다. 세 트리는 바이트 단위로 같아야 하며
`scripts/validate_agent_rules.py` 검사 5 가 그것을 강제합니다.

종전에는 스킬 하나를 고칠 때 세 곳을 손으로 맞췄습니다. 게이트가 어긋남을 막아 주므로
잘못된 상태가 병합되지는 않았지만, 편집자가 매번 같은 복사를 반복해야 했습니다.
이 스크립트가 그 복사를 대신합니다.

심볼릭 링크로 통합하지 않는 이유는 G2(크로스 플랫폼)입니다. Windows 의 Git 은
`core.symlinks` 와 권한이 갖춰지지 않으면 링크를 텍스트 파일로 체크아웃하므로
각 CLI 의 스킬 탐색이 조용히 깨집니다.

사용법:

    python3 scripts/sync_skill_mirrors.py            # 정본을 미러로 복제
    python3 scripts/sync_skill_mirrors.py --check     # 어긋남만 보고 (종료 코드 1)
    python3 scripts/sync_skill_mirrors.py --json      # 기계 판독 출력
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CANONICAL = Path(".agents/skills")
MIRRORS = (Path(".claude/skills"), Path(".opencode/skills"))


def relative_files(root: Path) -> set[Path]:
    """트리 안의 파일을 root 기준 상대 경로 집합으로 돌려줍니다."""
    if not root.is_dir():
        return set()
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def diff_mirror(canonical: Path, mirror: Path) -> dict[str, list[str]]:
    """정본과 미러의 차이를 항목별로 돌려줍니다. 빈 값이면 일치합니다."""
    canonical_files = relative_files(canonical)
    mirror_files = relative_files(mirror)

    missing = sorted(str(p) for p in canonical_files - mirror_files)
    extra = sorted(str(p) for p in mirror_files - canonical_files)
    changed = sorted(
        str(p)
        for p in canonical_files & mirror_files
        if not filecmp.cmp(canonical / p, mirror / p, shallow=False)
    )
    return {"missing": missing, "extra": extra, "changed": changed}


def sync_mirror(canonical: Path, mirror: Path, diff: dict[str, list[str]]) -> list[str]:
    """미러를 정본과 같게 만들고 수행한 조치를 돌려줍니다."""
    actions: list[str] = []
    for rel in diff["missing"] + diff["changed"]:
        src = canonical / rel
        dst = mirror / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        actions.append(f"복제 {mirror / rel}")
    for rel in diff["extra"]:
        target = mirror / rel
        target.unlink()
        actions.append(f"제거 {target}")
        parent = target.parent
        while parent != mirror and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            actions.append(f"빈 디렉터리 제거 {parent}")
            parent = parent.parent
    return actions


def run(root: Path, check_only: bool) -> tuple[int, dict[str, Any]]:
    canonical = root / CANONICAL
    if not canonical.is_dir():
        return 2, {"error": f"스킬 정본이 없습니다: {canonical}"}

    mirrors: dict[str, dict[str, Any]] = {}
    drifted = False
    for mirror_rel in MIRRORS:
        mirror = root / mirror_rel
        diff = diff_mirror(canonical, mirror)
        entry: dict[str, Any] = dict(diff)
        entry["in_sync"] = not any(diff.values())
        if not entry["in_sync"]:
            drifted = True
            if not check_only:
                mirror.mkdir(parents=True, exist_ok=True)
                entry["actions"] = sync_mirror(canonical, mirror, diff)
        mirrors[str(mirror_rel)] = entry

    report: dict[str, Any] = {"canonical": str(CANONICAL), "mirrors": mirrors}
    if check_only:
        return (1 if drifted else 0), report
    return 0, report


def render(report: dict[str, Any], check_only: bool) -> str:
    if "error" in report:
        return f"오류: {report['error']}"
    mirrors: dict[str, dict[str, Any]] = report["mirrors"]
    lines: list[str] = []
    for mirror, entry in mirrors.items():
        if entry["in_sync"]:
            lines.append(f"{mirror}: 정본과 일치")
            continue
        counts = (
            f"누락 {len(entry['missing'])}건, 내용 상이 {len(entry['changed'])}건, "
            f"잔여 {len(entry['extra'])}건"
        )
        if check_only:
            lines.append(f"{mirror}: 어긋남 ({counts})")
            for rel in entry["missing"] + entry["changed"] + entry["extra"]:
                lines.append(f"  - {rel}")
        else:
            lines.append(f"{mirror}: 동기화 완료 ({counts})")
    if check_only and any(not e["in_sync"] for e in mirrors.values()):
        lines.append(
            "해결: python3 scripts/sync_skill_mirrors.py 를 실행하고 결과를 함께 커밋하십시오."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스킬 정본을 CLI 별 미러로 복제합니다.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="복제하지 않고 어긋남만 보고합니다 (어긋나면 종료 코드 1)",
    )
    parser.add_argument("--repo", default=str(PROJECT_ROOT), help="저장소 루트 경로")
    parser.add_argument("--json", action="store_true", help="기계 판독 JSON 출력")
    args = parser.parse_args(argv)

    exit_code, report = run(Path(args.repo).resolve(), args.check)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.check))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
