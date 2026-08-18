"""Analyze /predict c10 P95 latency sample size effect and tail metrics.

This script processes phase8_predict_tail_*.json benchmark files,
conducts bootstrap resampling to evaluate how sample size affects P95 estimates,
computes 100ms violation rates with Wilson score confidence intervals,
and compares instrumented vs uninstrumented latency distributions.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def wilson_score_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion.

    Returns:
        tuple of (point_estimate, lower_bound, upper_bound).
    """
    if total == 0:
        return 0.0, 0.0, 0.0
    z = 1.959963984540054 if abs(confidence - 0.95) < 1e-4 else 1.95996
    p_hat = successes / total
    denominator = 1.0 + (z**2) / total
    center = (p_hat + (z**2) / (2.0 * total)) / denominator
    spread = (
        z * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z**2) / (4.0 * total**2))
    ) / denominator
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return p_hat, lower, upper


def linear_percentile(values: list[float] | np.ndarray, q: float) -> float:
    """Compute percentile using Type 7 linear interpolation (numpy/R default).

    position = (N - 1) * q / 100.0
    Interpolates linearly between floor(position) and ceil(position).
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return float("nan")
    return float(np.percentile(arr, q, method="linear"))


def load_benchmark_files(pattern: str) -> list[dict[str, Any]]:
    """Load all matching benchmark JSON files."""
    matched_paths = sorted(glob.glob(pattern))
    results = []
    for p in matched_paths:
        path_obj = Path(p)
        with path_obj.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        data["_filepath"] = str(path_obj)
        data["_filename"] = path_obj.name
        results.append(data)
    return results


def run_bootstrap_analysis(
    latencies: np.ndarray,
    sample_sizes: list[int] | None = None,
    iterations: int = 1000,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Run bootstrap resampling on latency array for various sample sizes."""
    if sample_sizes is None:
        sample_sizes = [100, 300, 600, 1000]

    rng = np.random.default_rng(seed)
    results = []

    for n in sample_sizes:
        p95_dist = np.empty(iterations, dtype=np.float64)
        for i in range(iterations):
            subsample = rng.choice(latencies, size=n, replace=True)
            p95_dist[i] = linear_percentile(subsample, 95.0)

        mean_val = float(np.mean(p95_dist))
        std_val = float(np.std(p95_dist, ddof=1))
        p5_val = float(np.percentile(p95_dist, 5.0, method="linear"))
        med_val = float(np.median(p95_dist))
        p95_val = float(np.percentile(p95_dist, 95.0, method="linear"))
        iqr_val = float(
            np.percentile(p95_dist, 75.0, method="linear")
            - np.percentile(p95_dist, 25.0, method="linear")
        )
        prob_over_60 = float(np.mean(p95_dist > 60.0) * 100.0)

        results.append(
            {
                "n": n,
                "mean_ms": mean_val,
                "std_ms": std_val,
                "p5_ms": p5_val,
                "median_ms": med_val,
                "p95_ms": p95_val,
                "iqr_ms": iqr_val,
                "prob_over_60_pct": prob_over_60,
            }
        )

    return results


def build_file_records(benchmark_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute summary statistics and Wilson CIs for each benchmark file."""
    records = []
    for item in benchmark_data:
        reqs = item.get("requests", [])
        lats = [r["latency_ms"] for r in reqs]
        n = len(lats)
        over_100_count = sum(1 for x in lats if x > 100.0)
        p_hat, low_ci, upp_ci = wilson_score_interval(over_100_count, n)
        p50 = linear_percentile(lats, 50.0)
        p90 = linear_percentile(lats, 90.0)
        p95 = linear_percentile(lats, 95.0)
        p99 = linear_percentile(lats, 99.0)
        max_lat = max(lats) if lats else 0.0

        records.append(
            {
                "filename": item["_filename"],
                "n": n,
                "p50_ms": p50,
                "p90_ms": p90,
                "p95_ms": p95,
                "p99_ms": p99,
                "max_ms": max_lat,
                "over_100_count": over_100_count,
                "over_100_rate_pct": p_hat * 100.0,
                "ci_lower_pct": low_ci * 100.0,
                "ci_upper_pct": upp_ci * 100.0,
            }
        )
    return records


def build_group_records(benchmark_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute group-level comparison statistics."""
    group_defs = {
        "Uninstrumented": [
            "phase8_predict_tail_uninstrumented_c10_20260814.json",
            "phase8_predict_tail_uninstrumented_c10_r600_20260814.json",
        ],
        "Instrumented (Full Trace)": [
            "phase8_predict_tail_instrumented_c10_20260814.json",
            "phase8_predict_tail_instrumented_c10_r1_20260814.json",
            "phase8_predict_tail_instrumented_c10_r2_20260814.json",
            "phase8_predict_tail_instrumented_c10_r3_20260814.json",
            "phase8_predict_tail_instrumented_c10_r4_600_20260814.json",
            "phase8_predict_tail_instrumented_c10_final_20260814.json",
            "phase8_predict_tail_instrumented_c10_long_20260814.json",
        ],
        "Baseline c10 (r1-r12)": [
            f"phase8_predict_tail_c10_{suffix}20260814.json"
            for suffix in [
                "",
                "r2_",
                "r3_",
                "r4_",
                "r5_",
                "r6_",
                "r7_",
                "r8_",
                "r9_",
                "r10_",
                "r11_",
                "r12_",
            ]
        ],
        "GC Disabled": [
            "phase8_predict_tail_gc_disabled_c10_20260814.json",
        ],
    }

    records = []
    for grp_name, fnames in group_defs.items():
        grp_lats = []
        for fn in fnames:
            item = next((b for b in benchmark_data if b["_filename"] == fn), None)
            if item:
                grp_lats.extend([r["latency_ms"] for r in item["requests"]])
        arr = np.array(grp_lats, dtype=np.float64)
        total_n = len(arr)
        over_100 = int(np.sum(arr > 100.0))
        p_hat, low_ci, upp_ci = wilson_score_interval(over_100, total_n)
        p50 = linear_percentile(arr, 50.0)
        p90 = linear_percentile(arr, 90.0)
        p95 = linear_percentile(arr, 95.0)
        p99 = linear_percentile(arr, 99.0)
        max_v = float(np.max(arr)) if len(arr) > 0 else 0.0

        records.append(
            {
                "group_name": grp_name,
                "file_count": len(fnames),
                "total_n": total_n,
                "p50_ms": p50,
                "p90_ms": p90,
                "p95_ms": p95,
                "p99_ms": p99,
                "max_ms": max_v,
                "over_100_count": over_100,
                "over_100_rate_pct": p_hat * 100.0,
                "ci_lower_pct": low_ci * 100.0,
                "ci_upper_pct": upp_ci * 100.0,
            }
        )
    return records


def main() -> None:
    """Execute analysis and print summary tables."""
    parser = argparse.ArgumentParser(description="Analyze /predict c10 P95 sample size effect.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/benchmarks"),
        help="Directory containing benchmark JSON files",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for bootstrap reproducibility",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1000,
        help="Number of bootstrap iterations",
    )
    args = parser.parse_args()

    pattern = str(args.data_dir / "phase8_predict_tail_*.json")
    benchmark_data = load_benchmark_files(pattern)

    print(f"Loaded {len(benchmark_data)} benchmark files.")

    # 1. Schema check
    if benchmark_data:
        first_req = benchmark_data[0].get("requests", [{}])[0]
        print(f"Request schema keys: {list(first_req.keys())}")
        print("Latency field: 'latency_ms'")

    # 2. File-by-file metrics
    file_records = build_file_records(benchmark_data)
    print("\n=== File-by-file Summary & 100ms Violation Rates ===")
    print(
        f"{'Filename':62s} | {'N':5s} | {'P50':7s} | {'P95':7s} | "
        f"{'Max':7s} | {'>100ms':6s} | {'Rate(%)':7s} | {'95% Wilson CI':18s}"
    )
    print("-" * 135)
    for r in file_records:
        ci_str = f"[{r['ci_lower_pct']:5.2f}%, {r['ci_upper_pct']:5.2f}%]"
        print(
            f"{r['filename']:62s} | {r['n']:5d} | {r['p50_ms']:7.2f} | "
            f"{r['p95_ms']:7.2f} | {r['max_ms']:7.2f} | {r['over_100_count']:6d} | "
            f"{r['over_100_rate_pct']:6.2f}% | {ci_str:18s}"
        )

    # 3. Largest uninstrumented file bootstrap
    uninst_file = "phase8_predict_tail_uninstrumented_c10_r600_20260814.json"
    target_item = next((b for b in benchmark_data if b["_filename"] == uninst_file), None)

    if target_item is not None:
        target_lats = np.array([r["latency_ms"] for r in target_item["requests"]], dtype=np.float64)
        print(f"\n=== Bootstrap Resampling on {uninst_file} (N={len(target_lats)}) ===")
        print("Percentile Interpolation: Linear (Type 7 / numpy default)")
        print(f"Iterations per sample size: {args.iterations:,} (Seed: {args.seed})")
        print(
            f"{'Sample Size (n)':16s} | {'Mean(ms)':9s} | {'Std(ms)':8s} | "
            f"{'P5(ms)':8s} | {'Median(ms)':11s} | {'P95(ms)':8s} | "
            f"{'IQR(ms)':8s} | {'P(P95>60ms)':11s}"
        )
        print("-" * 95)
        bootstrap_results = run_bootstrap_analysis(
            target_lats,
            [100, 300, 600, 1000],
            iterations=args.iterations,
            seed=args.seed,
        )
        for b in bootstrap_results:
            print(
                f"{b['n']:16d} | {b['mean_ms']:9.3f} | {b['std_ms']:8.3f} | "
                f"{b['p5_ms']:8.3f} | {b['median_ms']:11.3f} | {b['p95_ms']:8.3f} | "
                f"{b['iqr_ms']:8.3f} | {b['prob_over_60_pct']:10.1f}%"
            )

    # 4. Instrumented vs Uninstrumented Group Comparison
    group_records = build_group_records(benchmark_data)
    print("\n=== Group-level Latency & Overhead Comparison ===")
    print(
        f"{'Group':26s} | {'Files':5s} | {'Total N':7s} | {'P50':7s} | "
        f"{'P90':7s} | {'P95':7s} | {'P99':7s} | {'Max':7s} | "
        f"{'>100ms':6s} | {'95% Wilson CI':18s}"
    )
    print("-" * 125)

    for g in group_records:
        # 계측 활성 원시 측정치는 진단 브랜치 perf/predict-tail 에만 있습니다.
        # main 에서는 해당 그룹이 비어 nan 이 되므로 이유를 밝혀 출력합니다.
        if g["total_n"] == 0:
            print(
                f"{g['group_name']:26s} | {g['file_count']:5d} | "
                f"{'-':>7s} | 원시 측정치가 이 브랜치에 없습니다 "
                "(perf/predict-tail 참조)"
            )
            continue
        ci_str = f"[{g['ci_lower_pct']:5.2f}%, {g['ci_upper_pct']:5.2f}%]"
        print(
            f"{g['group_name']:26s} | {g['file_count']:5d} | {g['total_n']:7d} | "
            f"{g['p50_ms']:7.2f} | {g['p90_ms']:7.2f} | {g['p95_ms']:7.2f} | "
            f"{g['p99_ms']:7.2f} | {g['max_ms']:7.2f} | {g['over_100_count']:6d} | "
            f"{ci_str:18s}"
        )


if __name__ == "__main__":
    main()
