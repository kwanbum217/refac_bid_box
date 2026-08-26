"""
scripts/run_p9_sse_parallel_bench.py

작업 2: OLLAMA_NUM_PARALLEL 효과 측정을 위한 SSE c4 벤치마크 러너.
병렬도 모드(par1 또는 par4)에 따라 60표본 3회차를 측정하고 원시 JSON을 저장합니다.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_arq_throughput import get_git_sha  # noqa: E402
from scripts.benchmark_sse_gate import run_benchmark  # noqa: E402


def run_parallel_suite(
    parallel_mode: int,  # 1 or 4
    base_url: str = "http://127.0.0.1:8000",
    rounds_per_cycle: int = 60,
    num_cycles: int = 3,
    wait_between_cycles: float = 30.0,
) -> int:
    output_dir = PROJECT_ROOT / "data" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(
        f"작업 2. SSE c4 측정 시작 (병렬도: par{parallel_mode}, n={rounds_per_cycle}, {num_cycles}회차, warmup=4)"
    )
    print("=" * 70)

    for r_num in range(1, num_cycles + 1):
        if r_num > 1:
            print(f"\n[대기] 회차 간 간격 {wait_between_cycles}초 대기 중...")
            time.sleep(wait_between_cycles)

        out_json = output_dir / f"sse_c4_par{parallel_mode}_r{r_num}_20260814.json"
        summary, records = run_benchmark(
            base_url=base_url,
            concurrency=4,
            rounds=rounds_per_cycle,
            round_num=r_num,
            warmup=True,
        )

        payload = {
            "meta": {
                "git_sha": get_git_sha(),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "base_url": base_url,
                "concurrency": 4,
                "parallel_mode": parallel_mode,
                "rounds": rounds_per_cycle,
                "round_num": r_num,
                "warmup": True,
            },
            "summary": summary,
            "records": [asdict(r) for r in records],
        }
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {out_json} 저장 완료")

    print("\n" + "=" * 70)
    print(f"작업 2 SSE c4 par{parallel_mode} 3회차 측정 완료!")
    print("=" * 70)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SSE c4 병렬도 벤치마크 러너")
    parser.add_argument(
        "--parallel", type=int, required=True, choices=[1, 4], help="OLLAMA 병렬도 (1 또는 4)"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="대상 서버 URL")
    parser.add_argument("--rounds", type=int, default=60, help="회차당 표본 수")
    parser.add_argument("--cycles", type=int, default=3, help="회차 수")
    args = parser.parse_args()

    return run_parallel_suite(
        parallel_mode=args.parallel,
        base_url=args.base_url,
        rounds_per_cycle=args.rounds,
        num_cycles=args.cycles,
    )


if __name__ == "__main__":
    raise SystemExit(main())
