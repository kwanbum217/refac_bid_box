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
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
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
            out = subprocess.check_output(  # nosec B603 B607- shell 없이 고정 인자 목록으로 호출합니다
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
        with urllib.request.urlopen(f"{base_url}/debug/pid", timeout=2) as resp:  # nosec B310 - 로컬 측정 스크립트가 자기 호스트에만 요청합니다
            data = json.loads(resp.read())
            return int(data["pid"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 요청 워커
# ---------------------------------------------------------------------------

# PredictionRequest 계약과 일치해야 합니다. presmpt_prce/category 같은 raw 컬럼명을
# 보내면 422 로 전부 실패하며, 그래도 이 스크립트는 지연을 기록해 정상으로 보입니다.
_SAMPLE_PAYLOAD = json.dumps(
    {
        "presumed_price": 500_000_000,
        "base_price": 495_000_000,
        "category_code": "Thng",
    }
).encode()

_PREDICT_PATH = "/api/v1/predictions/predict"


def _send_one(base_url: str, latencies: list[float], errors: list[int]) -> None:
    url = base_url.rstrip("/") + _PREDICT_PATH
    req = urllib.request.Request(
        url,
        data=_SAMPLE_PAYLOAD,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10):  # nosec B310 - 로컬 측정 스크립트가 자기 호스트에만 요청합니다
            pass
        errors.append(0)
    except Exception as exc:
        # 실패를 빠른 응답으로 착각하지 않도록 건수를 셉니다. 계약이 어긋나면
        # 422 가 즉시 돌아오므로 지연만 보면 개선된 것처럼 보입니다.
        logger.debug("요청 실패: %s", exc)
        errors.append(1)
    latencies.append((time.monotonic() - t0) * 1000.0)


def _worker_loop(
    base_url: str, latencies: list[float], errors: list[int], stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        _send_one(base_url, latencies, errors)


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
    if server_pid is None:
        # /debug/pid 엔드포인트는 이 저장소에 없습니다. 서버가 Docker 안에서
        # 돌면 호스트 ps 로도 보이지 않으므로 RSS 를 잠자코 비워 두지 않고
        # 대체 수단을 알려 줍니다. 조용히 None 을 남기면 지연만 있고 메모리는
        # 없는 결과가 나와 채택 판정에 쓸 수 없습니다.
        print(
            "경고: 서버 PID 를 찾을 수 없어 RSS 를 기록하지 않습니다.\n"
            "  컨테이너 서버는 다음으로 측정하십시오.\n"
            "    docker stats --no-stream --format '{{.MemUsage}}' refac_bid_box-app-1\n"
            "  근거: docs/ops/phase8_predict_gc_verdict_20260814.md",
            file=sys.stderr,
        )

    latencies: list[float] = []
    errors: list[int] = []
    stop_event = threading.Event()
    threads = [
        threading.Thread(
            target=_worker_loop, args=(base_url, latencies, errors, stop_event), daemon=True
        )
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
        "failed_requests": sum(errors),
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
    print(f"총 요청 수: {report['total_requests']} (실패 {report['failed_requests']})")
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
