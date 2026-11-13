"""cmd(Command Code) 워커의 토큰 효율 A/B 측정 하니스.

과업 정의 JSON 과 조건 목록을 받아 조건 x 과업 x 회차 실행 계획을 세우고,
실행마다 기준 커밋의 임시 git 워크트리에서 cmd -p 로 과업을 수행시킵니다.
결과는 <out-dir>/results.jsonl 에 한 줄씩 남기고, 조건별 평균과 기준 대비
쌍대 부호 순열 검정을 <out-dir>/summary.json 과 표준출력 표로 남깁니다.

사용 예:
    uv run python scripts/token_ab_cmd.py --tasks tasks.json \
      --conditions baseline,no_skills,ponytail --ponytail-dir .claude/skills/ponytail
    uv run python scripts/token_ab_cmd.py --tasks tasks.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shlex
import subprocess  # nosec B404 - 실행 계획의 cmd 와 git 만 고정 인자 목록으로 호출합니다
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

# scripts/ 는 패키지가 아니라서 직접 실행하면 sys.path 에 저장소 루트가 없습니다.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.orca_worker_launch_common import deploy_worker_settings  # noqa: E402

POLICY_SOURCE = (
    Path(__file__).resolve().parent / "orca_policies" / "commandcode_worker_settings.json"
)

CONDITION_BASELINE = "baseline"
CONDITION_CHOICES = (
    CONDITION_BASELINE,
    "no_skills",
    "ponytail",
    "ponytail_no_skills",
)

DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_OUT_ROOT = Path(".cache") / "token_ab_cmd"
DEFAULT_REPS = 3
DEFAULT_PARALLEL = 3
DEFAULT_SEED = 42
DEFAULT_MAX_TURNS = 80
DEFAULT_PERMUTATIONS = 10000

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
METRIC_FIELDS = (*TOKEN_FIELDS, "total_tokens", "duration_ms", "added_lines")
PAIR_METRICS = ("total_tokens", "added_lines")


def condition_extra_args(condition: str, ponytail_dir: str | None) -> list[str]:
    """조건이 cmd 에 덧붙이는 인자를 조립합니다."""
    if condition == CONDITION_BASELINE:
        return []
    if condition == "no_skills":
        return ["--no-skills"]
    if not ponytail_dir:
        raise ValueError(f"{condition} 조건은 --ponytail-dir 가 필요합니다")
    skill_args = ["--skill", Path(ponytail_dir).as_posix()]
    if condition == "ponytail":
        return skill_args
    if condition == "ponytail_no_skills":
        return ["--no-skills", *skill_args]
    raise ValueError(f"알 수 없는 조건입니다: {condition}")


def parse_conditions(raw: str, ponytail_dir: str | None) -> list[str]:
    """쉼표 목록을 검증된 조건 목록으로 바꿉니다."""
    conditions = [token.strip() for token in raw.split(",") if token.strip()]
    if not conditions:
        raise ValueError("--conditions 가 비어 있습니다")
    for condition in conditions:
        if condition not in CONDITION_CHOICES:
            allowed = ", ".join(CONDITION_CHOICES)
            raise ValueError(f"알 수 없는 조건입니다: {condition} ({allowed})")
        condition_extra_args(condition, ponytail_dir)
    return conditions


def build_cmd_args(
    prompt: str,
    *,
    model: str,
    effort: str | None,
    max_turns: int,
    condition: str,
    ponytail_dir: str | None,
) -> list[str]:
    """단발 실행 cmd 인자 배열을 조립합니다."""
    args = ["cmd", "-p", prompt, "--model", model]
    if effort:
        args.extend(["--effort", effort])
    args.extend(["--output-format", "json", "--max-turns", str(max_turns)])
    args.extend(["--trust", "--yolo"])
    args.extend(condition_extra_args(condition, ponytail_dir))
    args.append("--no-session")
    return args


def parse_result_usage(ndjson_text: str) -> dict[str, Any] | None:
    """NDJSON 의 마지막 type=result 줄에서 사용량을 읽습니다. 없으면 None 입니다."""
    result: dict[str, Any] | None = None
    for line in ndjson_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "result":
            result = payload
    if result is None:
        return None

    usage = result.get("usage") or {}
    input_tokens = int(usage.get("inputTokens") or 0)
    output_tokens = int(usage.get("outputTokens") or 0)
    cache_read_tokens = int(usage.get("cacheReadTokens") or 0)
    cache_write_tokens = int(usage.get("cacheWriteTokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": input_tokens + output_tokens + cache_read_tokens + cache_write_tokens,
        "duration_ms": int(result.get("durationMs") or 0),
        "stop_reason": result.get("stopReason") or "",
    }


def sum_added_lines(numstat_text: str) -> int:
    """git diff --numstat 출력의 추가 줄을 합산합니다."""
    total = 0
    for line in numstat_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or parts[0] == "-":
            continue
        total += int(parts[0])
    return total


def parse_pytest_summary(output: str) -> tuple[int, int]:
    """pytest 요약 줄에서 (passed, failed) 를 읽습니다."""
    summary = ""
    for line in output.splitlines():
        stripped = line.strip().strip("=").strip()
        if re.search(r"\d+ (?:passed|failed|error)", stripped):
            summary = stripped
    if not summary:
        return 0, 0
    passed = failed = 0
    matched = re.search(r"(\d+) passed", summary)
    if matched:
        passed = int(matched.group(1))
    for pattern in (r"(\d+) failed", r"(\d+) error"):
        matched = re.search(pattern, summary)
        if matched:
            failed += int(matched.group(1))
    return passed, failed


def paired_permutation_pvalue(
    diffs: Sequence[float],
    *,
    seed: int,
    n_perm: int = DEFAULT_PERMUTATIONS,
) -> float:
    """쌍대 차이의 부호 순열 검정 p 값을 고정 시드로 계산합니다."""
    values = list(diffs)
    if not values:
        return 1.0
    count = len(values)
    observed = abs(sum(values) / count)
    rng = random.Random(seed)  # noqa: S311  # nosec B311 - 순열 검정 재현용 시드입니다
    hits = 0
    for _ in range(n_perm):
        sampled = sum(value if rng.random() < 0.5 else -value for value in values) / count
        if abs(sampled) >= observed:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def make_run_id(task_index: int, task_name: str, condition: str, rep: int) -> str:
    """워크트리와 로그 파일에 쓸 실행 식별자를 만듭니다."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_name).strip("-") or "task"
    return f"{task_index:02d}-{safe}-{condition}-r{rep}"


def build_plan(
    tasks: Sequence[dict[str, Any]],
    conditions: Sequence[str],
    reps: int,
    seed: int,
) -> list[dict[str, Any]]:
    """조건 x 과업 x 회차 실행 계획을 만들고 고정 시드로 섞습니다."""
    plan: list[dict[str, Any]] = []
    for task_index, task in enumerate(tasks):
        for condition in conditions:
            for rep in range(1, reps + 1):
                plan.append(
                    {
                        "run_id": make_run_id(task_index, str(task["name"]), condition, rep),
                        "condition": condition,
                        "rep": rep,
                        "task": task,
                    }
                )
    random.Random(seed).shuffle(plan)  # noqa: S311  # nosec B311 - 실행 순서 섞기 재현용 시드입니다
    return plan


def load_tasks(path: Path) -> list[dict[str, Any]]:
    """과업 정의 JSON 파일을 읽습니다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("과업 정의는 비어 있지 않은 JSON 목록이어야 합니다")
    return payload


def default_out_dir() -> Path:
    return DEFAULT_OUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")


def run_once(
    spec: dict[str, Any],
    *,
    out_dir: Path,
    model: str,
    effort: str | None,
    max_turns: int,
    ponytail_dir: str | None,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """실행 1회를 수행하고 결과 레코드를 돌려줍니다."""
    run = subprocess.run if runner is None else runner
    run_id = spec["run_id"]
    task = spec["task"]
    worktree = out_dir / "wt" / run_id
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "wt").mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "run_id": run_id,
        "condition": spec["condition"],
        "task": task["name"],
        "rep": spec["rep"],
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "duration_ms": 0,
        "stop_reason": "",
        "added_lines": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "valid": False,
    }

    try:
        added = run(
            ["git", "worktree", "add", "--detach", str(worktree), task["base_commit"]],
            capture_output=True,
            text=True,
        )
        if added.returncode != 0:
            return record

        placed = deploy_worker_settings(worktree, source=POLICY_SOURCE, runner=run)
        if placed is None:
            return record
        args = build_cmd_args(
            task["prompt"],
            model=model,
            effort=effort,
            max_turns=max_turns,
            condition=spec["condition"],
            ponytail_dir=ponytail_dir,
        )
        completed = run(args, cwd=str(worktree), capture_output=True, text=True)
        (runs_dir / f"{run_id}.ndjson").write_text(completed.stdout, encoding="utf-8")

        diff = run(
            ["git", "-C", str(worktree), "diff", "--numstat"],
            capture_output=True,
            text=True,
        )
        record["added_lines"] = sum_added_lines(diff.stdout)

        for hidden in task.get("hidden_tests") or []:
            blob = run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "show",
                    f"{hidden['source_commit']}:{hidden['path']}",
                ],
                capture_output=True,
                text=True,
            )
            if blob.returncode != 0:
                continue
            target = worktree / hidden["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(blob.stdout, encoding="utf-8")

        tests = run(
            shlex.split(task["test_command"]),
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
        record["tests_passed"], record["tests_failed"] = parse_pytest_summary(
            tests.stdout + tests.stderr
        )

        usage = parse_result_usage(completed.stdout)
        if usage is not None:
            record.update(usage)
            record["valid"] = True
        return record
    finally:
        run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            text=True,
        )


def run_plan(
    plan: Sequence[dict[str, Any]],
    *,
    out_dir: Path,
    model: str,
    effort: str | None,
    max_turns: int,
    ponytail_dir: str | None,
    parallel: int,
    runner: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """실행 계획을 병렬로 수행하고 계획 순서대로 결과를 돌려줍니다."""

    def execute(spec: dict[str, Any]) -> dict[str, Any]:
        return run_once(
            spec,
            out_dir=out_dir,
            model=model,
            effort=effort,
            max_turns=max_turns,
            ponytail_dir=ponytail_dir,
            runner=runner,
        )

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return list(pool.map(execute, plan))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(
    records: Sequence[dict[str, Any]],
    *,
    conditions: Sequence[str],
    baseline: str = CONDITION_BASELINE,
    seed: int = DEFAULT_SEED,
    n_perm: int = DEFAULT_PERMUTATIONS,
) -> dict[str, Any]:
    """조건별 평균과 기준 대비 쌍대 순열 검정을 계산합니다."""
    summary: dict[str, Any] = {
        "seed": seed,
        "n_perm": n_perm,
        "conditions": {},
        "comparisons": {},
    }

    for condition in conditions:
        rows = [record for record in records if record["condition"] == condition]
        valid = [record for record in rows if record["valid"]]
        entry: dict[str, Any] = {"runs": len(rows), "valid": len(valid)}
        for field in METRIC_FIELDS:
            entry[f"mean_{field}"] = _mean([record[field] for record in valid])
        entry["tests_passed"] = sum(record["tests_passed"] for record in valid)
        entry["tests_failed"] = sum(record["tests_failed"] for record in valid)
        summary["conditions"][condition] = entry

    baseline_rows = {
        (record["task"], record["rep"]): record
        for record in records
        if record["condition"] == baseline and record["valid"]
    }

    for condition in conditions:
        if condition == baseline:
            continue
        comparison: dict[str, Any] = {}
        for metric in PAIR_METRICS:
            diffs: list[float] = []
            for record in records:
                if record["condition"] != condition or not record["valid"]:
                    continue
                other = baseline_rows.get((record["task"], record["rep"]))
                if other is None:
                    continue
                diffs.append(record[metric] - other[metric])
            comparison[metric] = {
                "pairs": len(diffs),
                "mean_diff": _mean(diffs),
                "p_value": paired_permutation_pvalue(diffs, seed=seed, n_perm=n_perm),
            }
        summary["comparisons"][condition] = comparison

    return summary


def print_plan(
    plan: Sequence[dict[str, Any]],
    conditions: Sequence[str],
    out_dir: Path,
) -> None:
    """실행 계획을 출력합니다. cmd 는 부르지 않습니다."""
    print(f"out-dir: {out_dir.as_posix()}")
    print(f"conditions: {', '.join(conditions)}")
    print(f"runs: {len(plan)}")
    for index, spec in enumerate(plan, start=1):
        print(
            f"{index:03d} run_id={spec['run_id']} "
            f"task={spec['task']['name']} condition={spec['condition']} rep={spec['rep']}"
        )


def print_summary(summary: dict[str, Any]) -> None:
    """조건별 평균과 쌍대 검정 결과를 표로 출력합니다."""
    header = (
        f"{'condition':<20}{'runs':>5}{'valid':>6}{'total':>10}"
        f"{'added':>8}{'passed':>8}{'failed':>8}"
    )
    print(header)
    for condition, entry in summary["conditions"].items():
        print(
            f"{condition:<20}{entry['runs']:>5}{entry['valid']:>6}"
            f"{entry['mean_total_tokens']:>10.1f}{entry['mean_added_lines']:>8.1f}"
            f"{entry['tests_passed']:>8}{entry['tests_failed']:>8}"
        )
    for condition, comparison in summary["comparisons"].items():
        for metric, stats in comparison.items():
            print(
                f"{condition} vs baseline {metric}: "
                f"mean_diff={stats['mean_diff']:.1f} p={stats['p_value']:.4f} "
                f"pairs={stats['pairs']}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="cmd 워커 토큰 효율 A/B 측정 하니스")
    parser.add_argument("--tasks", type=Path, required=True, help="과업 정의 JSON 파일 경로")
    parser.add_argument(
        "--conditions",
        default=",".join(CONDITION_CHOICES),
        help="쉼표 목록. baseline, no_skills, ponytail, ponytail_no_skills",
    )
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--ponytail-dir", default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="실행 계획만 출력하고 cmd 를 부르지 않습니다"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        conditions = parse_conditions(args.conditions, args.ponytail_dir)
        tasks = load_tasks(args.tasks)
    except ValueError as err:
        parser.error(str(err))

    out_dir = args.out_dir if args.out_dir is not None else default_out_dir()
    plan = build_plan(tasks, conditions, args.reps, args.seed)
    if args.dry_run:
        print_plan(plan, conditions, out_dir)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    records = run_plan(
        plan,
        out_dir=out_dir,
        model=args.model,
        effort=args.effort,
        max_turns=args.max_turns,
        ponytail_dir=args.ponytail_dir,
        parallel=args.parallel,
    )

    results_path = out_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = summarize(records, conditions=conditions, seed=args.seed)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
