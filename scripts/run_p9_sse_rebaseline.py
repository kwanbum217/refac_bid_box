"""
scripts/run_p9_sse_rebaseline.py

P9 SSE c1 n60 기준선 재수립 및 주변 부하 로깅 스크립트.
규약 docs/ops/latency_gate_protocol.md 1.2, 3, 5.3 준수.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess  # nosec B404
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_sse_gate import get_git_sha, run_benchmark  # noqa: E402


class AmbientLoadLogger:
    def __init__(self, output_csv: Path, interval_sec: float = 5.0) -> None:
        self.output_csv = output_csv
        self.interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[dict[str, Any]] = []

        try:
            self.ncpu = int(
                subprocess.check_output(  # nosec B603 B607
                    ["sysctl", "-n", "hw.ncpu"], text=True
                ).strip()
            )
        except Exception:
            self.ncpu = os.cpu_count() or 1

    def _get_load1(self) -> float:
        try:
            out = subprocess.check_output(  # nosec B603 B607
                ["sysctl", "-n", "vm.loadavg"], text=True
            ).strip()
            # format: { 1.83 1.50 1.30 }
            parts = out.strip("{} ").split()
            return float(parts[0])
        except Exception:
            return float(os.getloadavg()[0])

    def _worker(self) -> None:
        sample_idx = 1
        while not self._stop_event.is_set():
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            load1 = self._get_load1()
            core_pct = round(100.0 * load1 / self.ncpu, 2)
            entry = {
                "sample": sample_idx,
                "timestamp": now_str,
                "load1": load1,
                "ncpu": self.ncpu,
                "load_per_core_pct": core_pct,
            }
            self.samples.append(entry)
            sample_idx += 1
            self._stop_event.wait(self.interval_sec)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join()

        # Save to CSV
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["sample", "timestamp", "load1", "ncpu", "load_per_core_pct"]
            )
            writer.writeheader()
            writer.writerows(self.samples)

    def get_stats(self) -> dict[str, float]:
        if not self.samples:
            return {"min": 0.0, "median": 0.0, "max": 0.0}
        pcts = sorted(s["load_per_core_pct"] for s in self.samples)
        n = len(pcts)
        mid = n // 2
        median = pcts[mid] if n % 2 == 1 else (pcts[mid - 1] + pcts[mid]) / 2.0
        return {
            "min": round(min(pcts), 2),
            "median": round(median, 2),
            "max": round(max(pcts), 2),
        }


def run_c1_suite(
    base_url: str = "http://127.0.0.1:8000",
    rounds_per_cycle: int = 60,
    num_cycles: int = 3,
    wait_between_cycles: float = 30.0,
) -> int:
    output_dir = PROJECT_ROOT / "data" / "benchmarks"
    ambient_csv = output_dir / "sse_c1_n60_ambient_20260814.csv"

    print("=" * 70)
    print("작업 1. SSE c1 기준선 재수립 시작 (n=60, 3회차, warmup=1)")
    print(f"주변 부하 로깅 경로: {ambient_csv}")
    print("=" * 70)

    load_logger = AmbientLoadLogger(ambient_csv, interval_sec=5.0)
    load_logger.start()

    summaries = []
    try:
        for r_num in range(1, num_cycles + 1):
            if r_num > 1:
                print(f"\n[대기] 회차 간 간격 {wait_between_cycles}초 대기 중...")
                time.sleep(wait_between_cycles)

            out_json = output_dir / f"sse_c1_n60_r{r_num}_20260814.json"
            summary, records = run_benchmark(
                base_url=base_url,
                concurrency=1,
                rounds=rounds_per_cycle,
                round_num=r_num,
                warmup=True,
            )
            summaries.append(summary)

            # 저장
            payload = {
                "meta": {
                    "git_sha": get_git_sha(),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "base_url": base_url,
                    "concurrency": 1,
                    "rounds": rounds_per_cycle,
                    "round_num": r_num,
                    "warmup": True,
                },
                "summary": summary,
                "records": [asdict(r) for r in records],
            }
            out_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  -> {out_json} 저장 완료")
    finally:
        load_logger.stop()

    stats = load_logger.get_stats()
    print("\n" + "=" * 70)
    print("작업 1 완료 및 부하 통계:")
    print(f"  - 주변 부하 (코어당): 최소 {stats['min']}%, 중앙값 {stats['median']}%, 최대 {stats['max']}%")
    print(f"  - 부하 파일: {ambient_csv}")
    print("=" * 70)

    # 부하 임계값 검증: 중앙값 <= 30%, 최대 <= 50%
    if stats["median"] > 30.0 or stats["max"] > 50.0:
        print("[경고] 주변 부하 임계값 초과! (중앙값 > 30% 또는 최대 > 50%)")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(run_c1_suite())
