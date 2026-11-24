#!/usr/bin/env python3
"""scripts/orca_gate11_backfill.py

게이트 11(실패→통과 증명)을 과거 병합 참조에 소급 실행합니다.

읽기 전용입니다. 브랜치·참조·작업 트리를 바꾸지 않으며, 기준/브랜치 트리는
임시 디렉터리에 git archive 로 풀었다가 지웁니다. 각 참조에 대해 main 이력에서
두 번째 부모가 그 참조 커밋인 병합 커밋을 찾아 첫 번째 부모를 base 로 쓰고,
찾지 못하면 git merge-base main <ref> 로 대체합니다.

사용 예:
    uv run python scripts/orca_gate11_backfill.py
    uv run python scripts/orca_gate11_backfill.py --refs refs/backup/search-cache-20261124
"""

from __future__ import annotations

import argparse
import datetime
import subprocess  # nosec B404 - 읽기 전용 git 호출에 고정 인자 목록만 씁니다
import sys
from pathlib import Path
from typing import Any

try:
    from scripts._strict_json import dump_strict_json
    from scripts.orca_level1_gate import GateToolError, run_gate11_fail_pass
except ModuleNotFoundError:
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts._strict_json import dump_strict_json
    from scripts.orca_level1_gate import GateToolError, run_gate11_fail_pass

# 2026-11-24 에 main 에 병합된 6건의 백업 참조입니다. 기본값은 이 목록입니다.
DEFAULT_REFS = (
    "refs/backup/dark-suffix-20261124",
    "refs/backup/home-prefs-perf-20261124",
    "refs/backup/kb-count-perf-20261124",
    "refs/backup/kb-result-cleanup-20261124",
    "refs/backup/meili-ranking-20261124",
    "refs/backup/search-cache-20261124",
)

GATE11_BACKFILL_SCHEMA = "GATE11_BACKFILL_V1"
DEFAULT_GIT_TIMEOUT = 60


def _git(repo: Path, args: list[str], timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    """읽기 전용 git 호출을 실행하고 표준출력을 반환합니다."""
    try:
        proc = subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateToolError(f"git {' '.join(args)} 타임아웃 ({timeout}초)") from exc
    except FileNotFoundError as exc:
        raise GateToolError(f"git 실행 파일을 찾을 수 없음: {exc}") from exc
    if proc.returncode != 0:
        raise GateToolError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
    return proc.stdout


def find_base_commit(repo: Path, ref: str, main_ref: str = "main") -> tuple[str, str]:
    """참조를 병합한 커밋의 첫 번째 부모를 base 로 찾습니다.

    반환값은 (base 커밋, 찾은 방법) 입니다. 병합 커밋을 찾지 못하면
    git merge-base main <ref> 로 대체하고 방법을 merge_base 로 남깁니다.
    """
    ref_commit = _git(repo, ["rev-parse", f"{ref}^{{commit}}"]).strip()
    main_merges = _git(repo, ["log", main_ref, "--merges", "--format=%H %P"])
    for line in main_merges.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == ref_commit:
            return parts[1], "merge_parent"
    base = _git(repo, ["merge-base", main_ref, ref]).strip()
    return base, "merge_base"


def collect_ref_result(repo: Path, ref: str, main_ref: str) -> dict[str, Any]:
    """참조 한 건에 게이트 11 을 실행하고 보고서용 항목을 만듭니다."""
    commit = _git(repo, ["rev-parse", f"{ref}^{{commit}}"]).strip()
    base, base_source = find_base_commit(repo, ref, main_ref)
    result = run_gate11_fail_pass(repo=repo, base=base, branch=ref)
    raw = result.raw_data
    base_counts = raw.get("base_counts") or {}
    branch_counts = raw.get("branch_counts") or {}
    return {
        "ref": ref,
        "commit": commit[:8],
        "base": base[:8],
        "base_source": base_source,
        "commit_types": raw.get("commit_types", []),
        "target_test_files": raw.get("target_files", []),
        "verdict": raw.get("verdict", "error"),
        "base_counts": base_counts,
        "branch_counts": branch_counts,
        "duration_seconds": raw.get("duration_seconds"),
        "status": result.status,
        "required": result.required,
        "summary": result.summary,
    }


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="게이트 11 실패→통과 증명 소급 실행 (읽기 전용)",
    )
    parser.add_argument(
        "--refs",
        nargs="+",
        default=list(DEFAULT_REFS),
        help="소급 실행할 git 참조 목록 (기본: 2026-11-24 병합 6건의 백업 참조)",
    )
    parser.add_argument("--main", default="main", help="병합 이력을 찾을 기준 ref (기본: main)")
    parser.add_argument("--repo", default=".", help="저장소 루트 경로 (기본: 현재 디렉터리)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """소급 실행 결과를 JSON 으로 표준출력에 냅니다."""
    args = parse_arguments(argv)
    repo = Path(args.repo).resolve()

    entries: list[dict[str, Any]] = []
    for ref in args.refs:
        try:
            entries.append(collect_ref_result(repo, ref, args.main))
        except Exception as exc:  # 참조 하나의 실패가 나머지 소급 실행을 막지 않게 합니다
            entries.append(
                {
                    "ref": ref,
                    "verdict": "error",
                    "error": str(exc) or exc.__class__.__name__,
                }
            )

    payload = {
        "schema": GATE11_BACKFILL_SCHEMA,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "repo": str(repo),
        "main": args.main,
        "refs": entries,
    }
    print(dump_strict_json(payload, indent=2))
    return 0 if all(entry.get("verdict") != "error" for entry in entries) else 2


if __name__ == "__main__":
    sys.exit(main())
