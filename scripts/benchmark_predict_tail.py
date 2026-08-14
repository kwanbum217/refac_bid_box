"""`/predict` c10 tail 요청의 구간 구성과 배치 크기를 수집합니다.

두 가지 모드로 동작합니다. `main` 에는 구간 계측이 들어 있지 않으므로 여기서는
end-to-end 지연만 수집합니다(`trace_id` 가 `None` 으로 남습니다). 구간 분해가
필요하면 계측이 살아 있는 `perf/predict-tail` 브랜치에서 서버를
`PREDICTION_TAIL_TRACE=true`로 띄우고 `--trace-log`를 지정하십시오. 계측을 `main`
hot path 에 넣지 않는 근거는 `docs/ops/phase8_predict_tail_merge_verdict_20260814.md`
에 있습니다.

측정 중에는 다른 수집·LLM 작업을 실행하지 않습니다.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

import httpx


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def request_once(base_url: str, index: int) -> dict:
    payload = {
        "presumed_price": 500_000_000 + index,
        "base_price": 495_000_000 + index,
        "category_code": "Thng",
    }
    started = time.perf_counter_ns()
    try:
        response = httpx.post(
            f"{base_url}/api/v1/predictions/predict",
            json=payload,
            timeout=60.0,
        )
        error = None if response.status_code == 200 else f"http_{response.status_code}"
        trace_id = response.headers.get("x-prediction-trace-id")
    except httpx.HTTPError as exc:
        error = type(exc).__name__
        trace_id = None
    return {
        "request_index": index,
        "latency_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
        "trace_id": int(trace_id) if trace_id and trace_id.isdigit() else None,
        "error": error,
    }


def read_traces(path: Path) -> dict[int, dict]:
    traces = {}
    marker = "prediction_tail_trace="
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        try:
            trace = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(trace.get("trace_id"), int):
            traces[trace["trace_id"]] = trace
    return traces


def summarize(records: list[dict]) -> dict:
    successful = [item for item in records if not item["error"]]
    latencies = [float(item["latency_ms"]) for item in successful]
    tail_cutoff = percentile(latencies, 95.0)
    tail = [item for item in successful if item["latency_ms"] >= tail_cutoff]
    segments = [
        "enqueue_to_pick_ms",
        "batch_window_ms",
        "lightgbm_call_ms",
        "residual_after_model_ms",
    ]
    segment_summary = {}
    for name in segments:
        values = [float(item["trace"][name]) for item in tail if item.get("trace")]
        segment_summary[name] = {
            "n": len(values),
            "mean_ms": statistics.fmean(values) if values else None,
            "median_ms": statistics.median(values) if values else None,
            "p95_ms": percentile(values, 95.0) if values else None,
            "max_ms": max(values) if values else None,
        }
    batch_sizes = Counter(
        str(item["trace"].get("batch_size"))
        for item in successful
        if item.get("trace")
    )
    tail_batch_sizes = Counter(
        str(item["trace"].get("batch_size"))
        for item in tail
        if item.get("trace")
    )
    gc_tail = [
        int(item["trace"].get("gc_collections_during", 0))
        for item in tail
        if item.get("trace")
    ]
    gc_tail_events = [
        int(item["trace"].get("gc_event_count", 0))
        for item in tail
        if item.get("trace")
    ]
    gc_tail_overlap = [
        float(item["trace"].get("gc_overlap_ms", 0.0))
        for item in tail
        if item.get("trace")
    ]
    return {
        "n": len(records),
        "successful": len(successful),
        "errors": len(records) - len(successful),
        "p50_ms": percentile(latencies, 50.0),
        "p95_ms": percentile(latencies, 95.0),
        "p99_ms": percentile(latencies, 99.0),
        "tail_cutoff_ms": tail_cutoff,
        "tail_n": len(tail),
        "tail_request_indices": [item["request_index"] for item in tail],
        "tail_segment_summary": segment_summary,
        "tail_batch_dispatch_ms": [
            float(item["trace"]["batch_dispatch_ms"])
            for item in tail
            if item.get("trace")
        ],
        "tail_lightgbm_thread_cpu_ms": [
            float(item["trace"]["lightgbm_thread_cpu_ms"])
            for item in tail
            if item.get("trace")
        ],
        "tail_batch_dispatch_thread_cpu_ms": [
            float(item["trace"]["batch_dispatch_thread_cpu_ms"])
            for item in tail
            if item.get("trace")
        ],
        "batch_size_distribution": dict(sorted(batch_sizes.items(), key=lambda item: int(item[0]))),
        "tail_batch_size_distribution": dict(
            sorted(tail_batch_sizes.items(), key=lambda item: int(item[0]))
        ),
        "tail_gc_collections_during": {
            "values": gc_tail,
            "nonzero_count": sum(value > 0 for value in gc_tail),
        },
        "tail_gc_events": {
            "counts": gc_tail_events,
            "max_count": max(gc_tail_events) if gc_tail_events else 0,
            "overlap_ms": gc_tail_overlap,
            "max_overlap_ms": max(gc_tail_overlap) if gc_tail_overlap else 0.0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="c10 predict tail 계측 벤치마크")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--rounds", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--trace-log", type=Path, required=True)
    parser.add_argument(
        "--trace-optional",
        action="store_true",
        help="trace 비활성 대조군에서 서버 trace 누락을 허용합니다.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=5.0) as client:
        client.get("/api/v1/health/ready").raise_for_status()

    # 모델·모듈을 데운 뒤 c10 표본에 포함하지 않습니다.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        warmup = list(pool.map(lambda index: request_once(args.base_url, index), range(args.concurrency)))
    if any(item["error"] for item in warmup):
        raise RuntimeError(f"warmup 실패: {warmup}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(request_once, args.base_url, index)
            for index in range(args.rounds)
        ]
        records = [future.result() for future in futures]

    traces = read_traces(args.trace_log)
    for item in records:
        item["trace"] = traces.get(item["trace_id"])
    missing = [item["request_index"] for item in records if item.get("trace") is None]
    if missing and not args.trace_optional:
        raise RuntimeError(f"trace 누락 {len(missing)}건: {missing[:10]}")

    evidence = {
        "base_url": args.base_url,
        "rounds": args.rounds,
        "concurrency": args.concurrency,
        "warmup_rounds": args.concurrency,
        "summary": summarize(records),
        "requests": records,
        "trace_log": str(args.trace_log),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
