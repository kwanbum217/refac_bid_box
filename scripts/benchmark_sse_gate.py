"""
scripts/benchmark_sse_gate.py

레이턴시 게이트 규약(docs/ops/latency_gate_protocol.md)에 맞춘 정본 SSE 챗봇 측정 하네스.

규약 요구사항 반영:
1. Warmup: 동시성 수만큼 선행 실행 후 표본에서 제외.
2. 동시성 제어: c1, c4 등 동시성 수준 지정 가능 (ThreadPoolExecutor).
3. 지표 산출: first_stage_ms, first_token_ms(TTFT), final_ms에 대해
   P50, P95, P99, Max, Min, Mean, 초과 건수/초과율, Wilson 95% 신뢰구간 상한 산출.
4. 원시 측정치 보존: data/benchmarks/sse_gate_c{동시성}_r{회차}_20260814.json 저장.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.benchmark_latency import (
    BuildProvenanceError,
    verify_provenance_consistency,
)
from scripts.benchmark_latency import (
    _command_output as _latency_command_output,
)
from scripts.benchmark_latency import (
    reproducibility_metadata as latency_reproducibility_metadata,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts._strict_json import dump_strict_json
except (ModuleNotFoundError, ImportError):
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

import httpx  # noqa: E402

CHAT_QUERIES = [
    "적격심사 기준이 어떻게 되나요",
    "2025년 물품 낙찰 평균 낙찰률 알려줘",
    "공사 부문 최근 낙찰 동향 알려줘",
    "수요기관별 낙찰 금액 상위는 어디야",
    "용역 계약 방법에는 어떤 것이 있나요",
]

FIRST_TOKEN_TARGET_MS = 3_000.0
FINAL_TARGET_MS = 20_000.0
WILSON_Z_95 = 1.95996


def wilson_score_upper(count: int, total: int, z: float = WILSON_Z_95) -> float:
    """Wilson 95% 신뢰구간 상한(%)을 계산합니다."""
    if total <= 0:
        return 0.0
    p = count / total
    z2 = z * z
    n = total
    center = (p + (z2 / (2 * n))) / (1 + (z2 / n))
    spread = (z * math.sqrt((p * (1 - p) / n) + (z2 / (4 * (n**2))))) / (1 + (z2 / n))
    upper = min(1.0, center + spread)
    return round(upper * 100.0, 3)


def percentile(values: list[float], q: float) -> float:
    """백분위수를 선형 보간으로 계산합니다."""
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * (q / 100.0)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass
class SingleRequestRecord:
    request_index: int
    query: str
    first_stage_ms: float | None
    first_token_ms: float | None
    final_ms: float | None
    success: bool
    error: str | None


def _query_for_index(index: int, round_num: int) -> str:
    base = CHAT_QUERIES[index % len(CHAT_QUERIES)]
    return f"{base} (게이트 표본 r{round_num}-#{index + 1})"


def execute_sse_request(
    base_url: str,
    index: int,
    query: str,
    timeout_sec: float = 180.0,
) -> SingleRequestRecord:
    start_time = time.perf_counter()
    first_stage_ms: float | None = None
    first_token_ms: float | None = None
    final_ms: float | None = None
    seen_stage = False
    seen_token = False
    error: str | None = None

    try:
        with (
            httpx.Client(base_url=base_url, timeout=timeout_sec) as client,
            client.stream(
                "POST",
                "/api/v1/chatbot/chat/stream",
                json={"message": query},
            ) as response,
        ):
            if response.status_code != 200:
                return SingleRequestRecord(
                    request_index=index,
                    query=query,
                    first_stage_ms=None,
                    first_token_ms=None,
                    final_ms=None,
                    success=False,
                    error=f"http_{response.status_code}",
                )

            current_event: str | None = None
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    now = time.perf_counter()
                    elapsed = (now - start_time) * 1000.0
                    if not seen_stage and current_event == "stage":
                        first_stage_ms = round(elapsed, 2)
                        seen_stage = True
                    elif not seen_token and current_event == "token":
                        first_token_ms = round(elapsed, 2)
                        seen_token = True
                    elif current_event == "final":
                        final_ms = round(elapsed, 2)
                    elif current_event == "error":
                        error = "stream_error_event"
    except httpx.HTTPError as exc:
        error = type(exc).__name__
    except Exception as exc:
        error = f"unexpected_{type(exc).__name__}"

    success = error is None and first_token_ms is not None and final_ms is not None

    return SingleRequestRecord(
        request_index=index,
        query=query,
        first_stage_ms=first_stage_ms,
        first_token_ms=first_token_ms,
        final_ms=final_ms,
        success=success,
        error=error,
    )


def compute_metric_stats(
    values: list[float],
    threshold_ms: float | None = None,
) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
            "min_ms": None,
            "mean_ms": None,
            "threshold_ms": threshold_ms,
            "exceeded_count": 0,
            "exceeded_rate_pct": 0.0,
            "wilson_upper_pct": 0.0,
        }

    n = len(values)
    p50 = round(percentile(values, 50.0), 2)
    p95 = round(percentile(values, 95.0), 2)
    p99 = round(percentile(values, 99.0), 2)
    max_val = round(max(values), 2)
    min_val = round(min(values), 2)
    mean_val = round(sum(values) / n, 2)

    exceeded_count = 0
    exceeded_rate_pct = 0.0
    wilson_upper = 0.0
    if threshold_ms is not None:
        exceeded_count = sum(1 for v in values if v > threshold_ms)
        exceeded_rate_pct = round((exceeded_count / n) * 100.0, 3)
        wilson_upper = wilson_score_upper(exceeded_count, n)

    return {
        "n": n,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": max_val,
        "min_ms": min_val,
        "mean_ms": mean_val,
        "threshold_ms": threshold_ms,
        "exceeded_count": exceeded_count,
        "exceeded_rate_pct": exceeded_rate_pct,
        "wilson_upper_pct": wilson_upper,
    }


def run_benchmark(
    base_url: str,
    concurrency: int,
    rounds: int,
    round_num: int,
    warmup: bool = True,
) -> tuple[dict[str, Any], list[SingleRequestRecord]]:
    print(
        f"\n[시작] SSE 게이트 측정 (동시성: c{concurrency}, 표본: {rounds}건, 회차: r{round_num})"
    )

    # 1. Warmup 단계
    if warmup and concurrency > 0:
        print(f"  -> Warmup 실행: {concurrency}회 동시 요청 진행 중 (표본 제외)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            warmup_futures = [
                executor.submit(
                    execute_sse_request,
                    base_url,
                    -1 - w_idx,
                    f"워밍업 질의 {w_idx + 1}",
                )
                for w_idx in range(concurrency)
            ]
            concurrent.futures.wait(warmup_futures)
        print("  -> Warmup 완료")

    # 2. 본 측정 단계
    print(f"  -> 본 측정 시작: {rounds}건 진행 중...")
    records: list[SingleRequestRecord] = []
    completed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_idx = {
            executor.submit(
                execute_sse_request,
                base_url,
                idx,
                _query_for_index(idx, round_num),
            ): idx
            for idx in range(rounds)
        }

        for future in concurrent.futures.as_completed(future_to_idx):
            record = future.result()
            records.append(record)
            completed_count += 1
            print(f"    진행: {completed_count}/{rounds} 완료", end="\r", flush=True)

    print(" " * 40, end="\r")
    records.sort(key=lambda r: r.request_index)

    # 3. 통계 집계
    successful_records = [r for r in records if r.success]
    errors_count = len(records) - len(successful_records)

    first_stage_vals = [
        r.first_stage_ms for r in successful_records if r.first_stage_ms is not None
    ]
    first_token_vals = [
        r.first_token_ms for r in successful_records if r.first_token_ms is not None
    ]
    final_vals = [r.final_ms for r in successful_records if r.final_ms is not None]

    summary = {
        "concurrency": concurrency,
        "rounds": rounds,
        "round_num": round_num,
        "total_requests": len(records),
        "successful_requests": len(successful_records),
        "error_requests": errors_count,
        "first_stage_stats": compute_metric_stats(first_stage_vals),
        "first_token_stats": compute_metric_stats(first_token_vals, FIRST_TOKEN_TARGET_MS),
        "final_stats": compute_metric_stats(final_vals, FINAL_TARGET_MS),
    }

    # 결과 출력
    print("-" * 65)
    print(
        f"  [결과 요약: c{concurrency} r{round_num}] 총 {len(records)}건 (성공 {len(successful_records)}, 오류 {errors_count})"
    )
    ft_stats = summary["first_token_stats"]
    fn_stats = summary["final_stats"]
    st_stats = summary["first_stage_stats"]

    print(
        f"  - 첫 stage: P50={st_stats['p50_ms']}ms, P95={st_stats['p95_ms']}ms, Max={st_stats['max_ms']}ms"
    )
    print(
        f"  - 첫 token (TTFT): P50={ft_stats['p50_ms']}ms, P95={ft_stats['p95_ms']}ms, P99={ft_stats['p99_ms']}ms, Max={ft_stats['max_ms']}ms "
        f"(>3000ms: {ft_stats['exceeded_count']}건 / {ft_stats['exceeded_rate_pct']}%, Wilson 상한: {ft_stats['wilson_upper_pct']}%)"
    )
    print(
        f"  - 완료 (final): P50={fn_stats['p50_ms']}ms, P95={fn_stats['p95_ms']}ms, P99={fn_stats['p99_ms']}ms, Max={fn_stats['max_ms']}ms "
        f"(>20000ms: {fn_stats['exceeded_count']}건 / {fn_stats['exceeded_rate_pct']}%, Wilson 상한: {fn_stats['wilson_upper_pct']}%)"
    )
    print("-" * 65)

    return summary, records


def _command_output(command: list[str]) -> str:
    return _latency_command_output(command)


def reproducibility_metadata(
    service_name: str = "app",
    strict: bool = True,
    base_url: str | None = None,
    target_container: str | None = None,
) -> dict[str, object]:
    """원시 측정치를 다른 실행 환경과 대조하기 위한 공통 메타데이터입니다."""
    return latency_reproducibility_metadata(
        service_name=service_name,
        strict=strict,
        base_url=base_url,
        target_container=target_container,
        command_runner=_command_output,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="SSE 레이턴시 게이트 벤치마크")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="대상 서버 URL")
    parser.add_argument(
        "--target-service", default="app", help="대상 도커 컴포즈 서비스명 (기본: app)"
    )
    parser.add_argument(
        "--target-container",
        default=None,
        help="명시적 대상 도커 컨테이너 이름 또는 ID (기본: None)",
    )
    parser.add_argument(
        "--allow-unknown-provenance",
        action="store_true",
        default=False,
        help="Docker provenance 조회 실패 시에도 측정을 강제 진행합니다 (기본: 거부)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1, choices=[1, 4], help="동시성 수준 (c1 또는 c4)"
    )
    parser.add_argument("--rounds", type=int, default=30, help="회차당 표본 수 (기본 30)")
    parser.add_argument("--round-num", type=int, default=1, help="측정 회차 번호 (1, 2, 3...)")
    parser.add_argument("--no-warmup", action="store_true", help="Warmup 건너뛰기")
    parser.add_argument("--output", type=Path, help="결과 저장 JSON 경로")

    args = parser.parse_args()

    # 헬스체크 확인
    try:
        resp = httpx.get(f"{args.base_url}/api/v1/health/ready", timeout=5.0)
        resp.raise_for_status()
    except Exception as exc:
        print(f"서버 헬스체크 실패 (/api/v1/health/ready): {exc}")
        return 2

    strict_provenance = not args.allow_unknown_provenance
    try:
        start_meta = reproducibility_metadata(
            service_name=args.target_service,
            strict=strict_provenance,
            base_url=args.base_url,
            target_container=args.target_container,
        )
    except BuildProvenanceError as exc:
        print(f"빌드 provenance 검증 실패 (시작 시점): {exc}")
        print(
            "--allow-unknown-provenance 옵션으로 강제할 수 있으나 정본 evidence로 인정되지 않습니다."
        )
        return 2

    summary, records = run_benchmark(
        base_url=args.base_url,
        concurrency=args.concurrency,
        rounds=args.rounds,
        round_num=args.round_num,
        warmup=not args.no_warmup,
    )

    try:
        end_meta = reproducibility_metadata(
            service_name=args.target_service,
            strict=strict_provenance,
            base_url=args.base_url,
            target_container=args.target_container,
        )
        verify_provenance_consistency(start_meta, end_meta, strict=strict_provenance)
    except BuildProvenanceError as exc:
        print(f"빌드 provenance 검증 실패 (종료 시점 / 교체 감지): {exc}")
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta": {
                **start_meta,
                "start_provenance": start_meta,
                "end_provenance": end_meta,
                "provenance_consistent": True,
                "base_url": args.base_url,
                "concurrency": args.concurrency,
                "rounds": args.rounds,
                "round_num": args.round_num,
                "warmup": not args.no_warmup,
            },
            "summary": summary,
            "records": [asdict(r) for r in records],
        }
        args.output.write_text(
            dump_strict_json(payload),
            encoding="utf-8",
        )
        print(f"원시 측정치 저장 완료: {args.output}")

    # 판정 검사 (목표: 첫 토큰 P95 <= 3000ms, final P95 <= 20000ms, errors == 0)
    ft_p95 = summary["first_token_stats"]["p95_ms"]
    fn_p95 = summary["final_stats"]["p95_ms"]
    errs = summary["error_requests"]

    passed = (
        ft_p95 is not None
        and fn_p95 is not None
        and ft_p95 <= FIRST_TOKEN_TARGET_MS
        and fn_p95 <= FINAL_TARGET_MS
        and errs == 0
    )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
