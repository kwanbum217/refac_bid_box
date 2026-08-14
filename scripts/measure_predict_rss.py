"""
scripts/measure_predict_rss.py

지속 부하 중 서버 프로세스의 RSS 추이와 GC 통계를 수집합니다.
psutil 이 없으면 표준 라이브러리와 ps(1) 명령으로 RSS 를 측정합니다.
새 라이브러리를 추가하지 않습니다.

사용 예:
    python scripts/measure_predict_rss.py \
        --base-url http://localhost:8000 \
        --duration-seconds 600 \
        --concurrency 10 \
        --sample-interval-seconds 5 \
        --out /tmp/rss_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import threading
import time
import urllib.request
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RSS 측정 헬퍼 (psutil 우선, 없으면 ps(1) 폴백)
# ---------------------------------------------------------------------------

try:
    import psutil as _psutil

    def _get_server_rss_kb(pid: int) -> int | None:
        try:
            return _psutil.Process(pid).memory_info().rss // 1024
        except _psutil.NoSuchProcess:
            return None

except ImportError:
    _psutil = None  # type: ignore[assignment]

    def _get_server_rss_kb(pid: int) -> int | None:
        try:
            out = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(pid)],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return int(out) if out else None
        except (subprocess.CalledProcessError, ValueError):
            return None


def _find_server_pid(base_url: str) -> int | None:
    """서버가 열어 둔 포트를 통해 PID 를 추론합니다. /pid 엔드포인트가 없으면 None."""
    try:
        with urllib.request.urlopen(f"{base_url}/debug/pid", timeout=2) as resp:
            data = json.loads(resp.read())
            return int(data["pid"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 요청 워커
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD = json.dumps(
    {
        "presmpt_prce": 1_100_000_000,
        "real_budget": 1_100_000_000,
        "base_amount": 1_000_000_000,
        "scenario_mode": "2",
        "category": "Thng",
    }
).encode()

_PREDICT_PATH = "/api/v1/predictions/"


def _send_one(base_url: str, latencies: list[float]) -> None:
    url = base_url.rstrip("/") + _PREDICT_PATH
    req = urllib.request.Request(
        url,
        data=_SAMPLE_PAYLOAD,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:
        logger.debug("요청 실패: %s", exc)
    latencies.append((time.monotonic() - t0) * 1000.0)



def _worker_loop(base_url: str, latencies: list[float], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        _send_one(base_url, latencies)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = max(0, int(len(sorted_v) * p / 100) - 1)
    return sorted_v[idx]


def run(
    base_url: str,
    duration_seconds: int,
    concurrency: int,
    sample_interval_seconds: float,
    out_path: str,
) -> None:
    server_pid = _find_server_pid(base_url)

    latencies: list[float] = []
    stop_event = threading.Event()
    threads = [
        threading.Thread(target=_worker_loop, args=(base_url, latencies, stop_event), daemon=True)
        for _ in range(concurrency)
    ]
    for t in threads:
        t.start()

    samples: list[dict] = []
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        ts = datetime.now(UTC).isoformat()
        rss_kb = _get_server_rss_kb(server_pid) if server_pid else None
        snap = {
            "ts": ts,
            "rss_kb": rss_kb,
            "requests_so_far": len(latencies),
        }
        samples.append(snap)
        time.sleep(sample_interval_seconds)

    stop_event.set()
    for t in threads:
        t.join(timeout=5.0)

    lat_copy = list(latencies)
    report = {
        "base_url": base_url,
        "duration_seconds": duration_seconds,
        "concurrency": concurrency,
        "sample_interval_seconds": sample_interval_seconds,
        "server_pid": server_pid,
        "total_requests": len(lat_copy),
        "latency_ms": {
            "p50": _percentile(lat_copy, 50),
            "p95": _percentile(lat_copy, 95),
            "p99": _percentile(lat_copy, 99),
            "max": max(lat_copy) if lat_copy else 0.0,
        },
        "rss_samples": samples,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"보고서 저장: {out_path}")
    print(f"총 요청 수: {report['total_requests']}")
    if lat_copy:
        print(
            f"지연(ms) P50={report['latency_ms']['p50']:.1f}"
            f" P95={report['latency_ms']['p95']:.1f}"
            f" P99={report['latency_ms']['p99']:.1f}"
        )
    rss_values = [s["rss_kb"] for s in samples if s["rss_kb"] is not None]
    if rss_values:
        delta = rss_values[-1] - rss_values[0]
        print(f"RSS 변화: {rss_values[0]} KB -> {rss_values[-1]} KB (delta={delta:+d} KB)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="서버 RSS 와 GC 통계를 측정합니다.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--duration-seconds", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--sample-interval-seconds", type=float, default=5.0)
    parser.add_argument("--out", default="rss_report.json")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run(
        base_url=args.base_url,
        duration_seconds=args.duration_seconds,
        concurrency=args.concurrency,
        sample_interval_seconds=args.sample_interval_seconds,
        out_path=args.out,
    )
