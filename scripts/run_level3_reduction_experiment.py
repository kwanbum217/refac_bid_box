#!/usr/bin/env python3
"""
scripts/run_level3_reduction_experiment.py

Level 3 코디네이터 검토 축소 가능성을 실측으로 검증하기 위한 벤치마크 실행 하네스입니다.
임시 git 저장소를 생성하여 clean/defective 픽스처 간의 diff를 만들고,
팔 A(현행 규약 의무 범위)와 팔 B(개선안 계약)로 독립 리뷰어를 실행하여
원문 보고서와 출력을 보존합니다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from scripts.orca_run_reviewer import DEFAULT_MODEL, run_reviewer
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_run_reviewer import DEFAULT_MODEL, run_reviewer


FIXTURES_DIR = Path("tests/fixtures/level3_reduction")
CLEAN_FIXTURE = FIXTURES_DIR / "seeded_target_clean.py"
DEFECTIVE_FIXTURE = FIXTURES_DIR / "seeded_target_defective.py"
ARM_A_CAPSULE = FIXTURES_DIR / "arm_a_capsule.yaml"
ARM_B_CAPSULE = FIXTURES_DIR / "arm_b_capsule.yaml"


def create_seeded_repo(
    clean_source: Path,
    defective_source: Path,
    target_rel_path: str = "src/audit_metric_collector.py",
) -> tuple[tempfile.TemporaryDirectory[str], Path, str, str]:
    """임시 git 저장소를 생성하고 clean 커밋(base)과 defective 커밋(branch)을 구성합니다.

    반환: (temp_dir_obj, repo_path, base_ref, branch_ref)
    """
    tmp_dir = tempfile.TemporaryDirectory(prefix="orca_level3_bench_")
    repo_path = Path(tmp_dir.name)

    # 1. git init & user config
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Orca Benchmark"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "benchmark@orca.local"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    target_file = repo_path / target_rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)

    # 2. Base commit (clean)
    shutil.copy2(clean_source, target_file)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial clean code"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    base_ref = "main"

    # 3. Branch commit (defective)
    subprocess.run(
        ["git", "checkout", "-b", "feature/defects"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    shutil.copy2(defective_source, target_file)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: seeded defective code"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    branch_ref = "feature/defects"

    return tmp_dir, repo_path, base_ref, branch_ref


def run_single_benchmark_iteration(
    capsule_path: Path,
    repo_path: Path,
    base_ref: str,
    branch_ref: str,
    out_json_path: Path,
    model: str,
    timeout: int,
    dry_run: bool,
    reviewer_runner: Callable[..., tuple[int, str]] = run_reviewer,
) -> tuple[int, str, dict[str, Any] | None]:
    """단일 리뷰어 벤치마크 반복을 실행합니다."""
    code, output = reviewer_runner(
        capsule=capsule_path,
        out=out_json_path,
        diff_base=base_ref,
        diff_branch=branch_ref,
        repo=repo_path,
        model=model,
        timeout=timeout,
        dry_run=dry_run,
        as_json=False,
    )

    report_data = None
    if out_json_path.exists():
        try:
            report_data = json.loads(out_json_path.read_text(encoding="utf-8"))
        except Exception:
            report_data = None

    return code, output, report_data


def run_experiment(
    arm: str = "both",
    runs: int = 3,
    results_dir: Path | str = "./results",
    model: str = DEFAULT_MODEL,
    timeout: int = 600,
    dry_run: bool = False,
    as_json: bool = False,
    reviewer_runner: Callable[..., tuple[int, str]] = run_reviewer,
) -> tuple[int, dict[str, Any]]:
    """Level 3 축소 실험을 실행하고 결과를 수집하여 보존합니다."""
    results_path = Path(results_dir).resolve()
    results_path.mkdir(parents=True, exist_ok=True)

    target_arms: list[str]
    if arm.lower() == "a":
        target_arms = ["a"]
    elif arm.lower() == "b":
        target_arms = ["b"]
    else:
        target_arms = ["a", "b"]

    # 임시 git 저장소 생성
    tmp_repo_holder, repo_path, base_ref, branch_ref = create_seeded_repo(
        clean_source=CLEAN_FIXTURE.resolve(),
        defective_source=DEFECTIVE_FIXTURE.resolve(),
    )

    summary_data: dict[str, Any] = {
        "model": model,
        "runs_requested_per_arm": runs,
        "dry_run": dry_run,
        "results_dir": str(results_path),
        "arms": {},
    }

    total_valid_runs = 0
    total_invalid_runs = 0

    try:
        for cur_arm in target_arms:
            capsule_file = ARM_A_CAPSULE.resolve() if cur_arm == "a" else ARM_B_CAPSULE.resolve()
            arm_results: list[dict[str, Any]] = []
            valid_count = 0
            invalid_count = 0
            retries_used = 0
            max_retries = 2  # 팔당 최대 2회 재시도

            run_idx = 1
            while run_idx <= runs:
                out_file = results_path / f"arm_{cur_arm}_run_{run_idx}.json"
                stdout_file = results_path / f"arm_{cur_arm}_run_{run_idx}.stdout.txt"

                code, output, report_data = run_single_benchmark_iteration(
                    capsule_path=capsule_file,
                    repo_path=repo_path,
                    base_ref=base_ref,
                    branch_ref=branch_ref,
                    out_json_path=out_file,
                    model=model,
                    timeout=timeout,
                    dry_run=dry_run,
                    reviewer_runner=reviewer_runner,
                )

                # 출력 텍스트 보존
                stdout_file.write_text(output, encoding="utf-8")

                # 종료 코드 0 또는 1은 정상 완료 (0: pass, 1: fail/defect detected)
                # 종료 코드 2는 도구/파싱/타임아웃 오류로 무효(invalid)
                is_valid = code in (0, 1) or (dry_run and code == 0)

                if not is_valid and not dry_run and retries_used < max_retries:
                    retries_used += 1
                    sys.stderr.write(
                        f"[경고] 팔 {cur_arm.upper()} 실행 {run_idx} 오류 (코드 {code}). "
                        f"재시도 ({retries_used}/{max_retries})...\n"
                    )
                    continue

                if is_valid:
                    valid_count += 1
                else:
                    invalid_count += 1

                run_record: dict[str, Any] = {
                    "run_index": run_idx,
                    "exit_code": code,
                    "valid": is_valid,
                    "out_file": str(out_file),
                    "stdout_file": str(stdout_file),
                    "verdict": report_data.get("verdict") if report_data else None,
                    "blocking_count": len(report_data.get("blocking_issues", []))
                    if report_data
                    else 0,
                }
                arm_results.append(run_record)
                run_idx += 1

            total_valid_runs += valid_count
            total_invalid_runs += invalid_count

            summary_data["arms"][f"arm_{cur_arm}"] = {
                "capsule": str(capsule_file),
                "total_runs": len(arm_results),
                "valid_runs": valid_count,
                "invalid_runs": invalid_count,
                "retries_used": retries_used,
                "runs": arm_results,
            }
    finally:
        tmp_repo_holder.cleanup()

    # 요약 메타데이터 저장
    summary_path = results_path / "experiment_summary.json"
    summary_path.write_text(
        json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    exit_code = 0 if total_invalid_runs == 0 else 1
    return exit_code, summary_data


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Level 3 코디네이터 검토 축소 실측 벤치마크 실행 도구",
    )
    parser.add_argument(
        "--arm",
        choices=["a", "b", "both"],
        default="both",
        help="실행할 실험 팔 (a: 현행 의무, b: 개선안, both: 둘 다, 기본: both)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="팔당 반복 실행 횟수 (기본: 3)",
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        help="실행 결과 JSON 및 출력을 보존할 디렉터리 경로 (필수)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"사용할 리뷰어 모델 (기본: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="모델 호출 타임아웃 초 (기본: 600)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="실행 요약을 JSON 형식으로 출력",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="모델을 호출하지 않고 임시 저장소 구성과 호출까지만 검증",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    code, summary = run_experiment(
        arm=args.arm,
        runs=args.runs,
        results_dir=args.results_dir,
        model=args.model,
        timeout=args.timeout,
        dry_run=args.dry_run,
        as_json=args.json,
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Level 3 코디네이터 검토 축소 벤치마크 실행 완료")
        print("=" * 60)
        print(f"사용 모델:          {summary['model']}")
        print(f"결과 보존 경로:     {summary['results_dir']}")
        print(f"Dry-run 모드:       {summary['dry_run']}")
        for arm_name, arm_info in summary["arms"].items():
            print(
                f"- {arm_name.upper()}: 총 {arm_info['total_runs']}회 실행 "
                f"(유효: {arm_info['valid_runs']}회, 무효: {arm_info['invalid_runs']}회, "
                f"재시도: {arm_info['retries_used']}회)"
            )
        print("=" * 60)
        print(
            "결과 보고서 채점은 tests/fixtures/level3_reduction/scoring_rule.md 에 따라 수행하십시오."
        )

    return code


if __name__ == "__main__":
    sys.exit(main())
