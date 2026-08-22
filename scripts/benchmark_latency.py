"""
scripts/benchmark_latency.py

Phase 7 레이턴시 벤치마크.

측정 대상은 네 가지입니다.

| 구간 | 목표 | 근거 |
| --- | --- | --- |
| SSE 첫 토큰 | P95 3초 이내 | REFACTORING_DESIGN.md:651 (legacy 경로 전환 완료) |
| SSE 전체 응답 | P95 20초 이내 | REFACTORING_DESIGN.md:651 |
| 낙찰가 예측 API | P95 100ms 이내 | 싱글톤 모델 로드 효과 확인 |
| 단발 질의 API | 참고값 | 스트리밍 대비 비교용 |

**실제로 기동 중인 서버에 HTTP 로 붙습니다.** TestClient 는 ASGI 를 인프로세스로
호출해 네트워크와 이벤트 루프 경합을 건너뛰므로 체감 레이턴시를 재지 못합니다.

실행:
    make benchmark
    python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000
"""

import argparse
import concurrent.futures
import gc
import json
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

# 캐시 적중으로 측정치가 왜곡되지 않도록 질의를 매번 바꿉니다.
CHAT_QUERIES = [
    "적격심사 기준이 어떻게 되나요",
    "2025년 물품 낙찰 평균 낙찰률 알려줘",
    "공사 부문 최근 낙찰 동향 알려줘",
    "수요기관별 낙찰 금액 상위는 어디야",
    "용역 계약 방법에는 어떤 것이 있나요",
]

FIRST_TOKEN_TARGET_MS = 3_000.0
TOTAL_TARGET_MS = 20_000.0
PREDICT_TARGET_MS = 100.0


def _command_output(command: list[str]) -> str:
    try:
        return (
            subprocess.check_output(  # nosec B603
                command,
                cwd=PROJECT_ROOT,
                text=True,
            ).strip()
            or "unknown"
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def reproducibility_metadata() -> dict[str, object]:
    """원시 측정치를 다른 실행 환경과 대조하기 위한 공통 메타데이터입니다."""
    timer_info = time.get_clock_info("perf_counter")
    return {
        "git_sha": _command_output(["git", "rev-parse", "HEAD"]),
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "docker_image_id": _command_output(["docker", "compose", "images", "-q", "backend"]),
        "gc": {"enabled": gc.isenabled(), "threshold": list(gc.get_threshold())},
        "instrumentation": {
            "timer": "time.perf_counter",
            "timer_resolution_seconds": timer_info.resolution,
            "timer_monotonic": timer_info.monotonic,
        },
    }


def host_load_metadata() -> dict[str, object]:
    """측정 시점의 관찰 가능한 호스트 부하를 보존합니다."""
    cpu_count = os.cpu_count()
    try:
        load_1m, _, _ = os.getloadavg()
    except OSError:
        load_1m = None

    per_core_percent = None
    if load_1m is not None and cpu_count:
        per_core_percent = (load_1m / cpu_count) * 100.0
    return {
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "load_1m": load_1m,
        "cpu_count": cpu_count,
        "per_core_percent": per_core_percent,
    }


def _fmt(milliseconds: float) -> str:
    """1초 미만은 밀리초로 표시합니다. 예측 API 는 자릿수가 크게 달라서입니다."""
    if milliseconds < 1000:
        return f"{milliseconds:.1f}ms"
    return f"{milliseconds / 1000:.2f}s"


@dataclass
class Samples:
    """레이턴시 표본. 값은 모두 밀리초입니다."""

    label: str
    values: list[float] = field(default_factory=list)
    errors: int = 0
    # 어떤 질의가 느린지 봐야 대응이 가능하므로 (질의, 소요시간) 을 함께 남깁니다.
    tagged: list[tuple[str, float]] = field(default_factory=list)

    def add(self, milliseconds: float, tag: str = "") -> None:
        self.values.append(milliseconds)
        if tag:
            self.tagged.append((tag, milliseconds))

    def slowest(self, count: int = 3) -> list[tuple[str, float]]:
        return sorted(self.tagged, key=lambda item: -item[1])[:count]

    def percentile(self, q: float) -> float:
        if not self.values:
            return float("nan")
        ordered = sorted(self.values)
        position = (len(ordered) - 1) * (q / 100.0)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    def report(self, target_ms: float | None = None) -> bool:
        if not self.values:
            print(f"  {self.label}: 표본 없음 (오류 {self.errors}건)")
            return False
        p50 = self.percentile(50)
        p95 = self.percentile(95)
        p99 = self.percentile(99)
        line = (
            f"  {self.label}: n={len(self.values)} "
            f"P50={_fmt(p50)} P95={_fmt(p95)} P99={_fmt(p99)} "
            f"평균={_fmt(statistics.fmean(self.values))}"
        )
        if self.errors:
            line += f" (오류 {self.errors}건)"
        print(line)
        if target_ms is None:
            return True
        passed = p95 <= target_ms and self.errors == 0
        print(f"      목표 P95 {_fmt(target_ms)} -> {'달성' if passed else '미달'}")
        return passed

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "values_ms": self.values,
            "errors": self.errors,
            "p50_ms": self.percentile(50),
            "p95_ms": self.percentile(95),
            "p99_ms": self.percentile(99),
            "tagged": self.tagged,
        }


def _query_for_round(index: int) -> str:
    base = CHAT_QUERIES[index % len(CHAT_QUERIES)]
    return f"{base} (성능 측정 표본 {index + 1})"


def benchmark_sse_canonical(base_url: str, rounds: int) -> tuple[Samples, Samples, Samples]:
    """정본 SSE 스트림에서 first_stage_ms, first_token_ms, final_ms를 측정합니다.

    기존 legacy GET /api/v1/chatbot/stream은 제거되었고,
    canonical POST /api/v1/chatbot/chat/stream으로 전환되었습니다.
    """
    first_stage = Samples("정본 SSE 첫 stage (first_stage_ms)")
    first_token = Samples("정본 SSE 첫 token (first_token_ms)")
    final = Samples("정본 SSE 완료 (final_ms)")

    with httpx.Client(base_url=base_url, timeout=180.0) as client:
        for i in range(rounds):
            query = _query_for_round(i)
            start = time.perf_counter()
            seen_stage = False
            seen_token = False
            try:
                with client.stream(
                    "POST", "/api/v1/chatbot/chat/stream", json={"message": query}
                ) as r:
                    if r.status_code != 200:
                        first_stage.errors += 1
                        first_token.errors += 1
                        final.errors += 1
                        continue
                    current_event = None
                    for line in r.iter_lines():
                        if not line:
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            if not seen_stage and current_event == "stage":
                                first_stage.add((time.perf_counter() - start) * 1000.0, query)
                                seen_stage = True
                            if not seen_token and current_event == "token":
                                first_token.add((time.perf_counter() - start) * 1000.0, query)
                                seen_token = True
                            if current_event == "final":
                                final.add((time.perf_counter() - start) * 1000.0, query)
            except httpx.HTTPError:
                first_stage.errors += 1
                first_token.errors += 1
                final.errors += 1
            print(f"    정본 스트리밍 {i + 1}/{rounds} 완료", end="\r", flush=True)
    print(" " * 40, end="\r")
    return first_stage, first_token, final


def benchmark_predict(base_url: str, rounds: int, concurrency: int) -> Samples:
    samples = Samples("낙찰가 예측 API")

    def request(index: int) -> tuple[bool, float]:
        payload = {
            "presumed_price": 500_000_000 + index,
            "base_price": 495_000_000 + index,
            "category_code": "Thng",
        }
        start = time.perf_counter()
        response = httpx.post(
            f"{base_url}/api/v1/predictions/predict",
            json=payload,
            timeout=60.0,
        )
        return response.status_code == 200, (time.perf_counter() - start) * 1000.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        # 모델 로드와 첫 배치를 데우되, 이 요청은 측정 표본에 넣지 않습니다.
        warmup_futures = [executor.submit(request, -1 - index) for index in range(concurrency)]
        for future in concurrent.futures.as_completed(warmup_futures):
            with suppress(httpx.HTTPError):
                future.result()
        futures = [executor.submit(request, index) for index in range(rounds)]
        for future in concurrent.futures.as_completed(futures):
            try:
                succeeded, elapsed = future.result()
            except httpx.HTTPError:
                samples.errors += 1
                continue
            if succeeded:
                samples.add(elapsed)
            else:
                samples.errors += 1
    return samples


def build_evidence(
    base_url: str,
    predict_rounds: int,
    predict_concurrency: int,
    first_stage: Samples,
    first_token: Samples,
    final: Samples,
    predict: Samples,
    query: Samples,
) -> dict[str, object]:
    return {
        "meta": {
            **reproducibility_metadata(),
            "host_load": host_load_metadata(),
        },
        "base_url": base_url,
        "predict_rounds": predict_rounds,
        "predict_concurrency": predict_concurrency,
        "predict_warmup_requests": predict_concurrency,
        "samples": {
            "first_stage_new": first_stage.as_dict(),
            "first_token_new": first_token.as_dict(),
            "final_new": final.as_dict(),
            "predict": predict.as_dict(),
            "query": query.as_dict(),
        },
    }


def benchmark_query(base_url: str, rounds: int) -> Samples:
    samples = Samples("단발 질의 API (비스트리밍)")
    with httpx.Client(base_url=base_url, timeout=180.0) as client:
        for i in range(rounds):
            start = time.perf_counter()
            query = _query_for_round(i)
            r = client.post(
                "/api/v1/chatbot/query",
                json={"query": query, "stream": False},
            )
            elapsed = (time.perf_counter() - start) * 1000.0
            if r.status_code == 200:
                samples.add(elapsed, query)
            else:
                samples.errors += 1
            print(f"    단발 질의 {i + 1}/{rounds} 완료", end="\r", flush=True)
    print(" " * 40, end="\r")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="레이턴시 벤치마크")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sse-rounds", type=int, default=20)
    parser.add_argument("--query-rounds", type=int, default=10)
    parser.add_argument("--predict-rounds", type=int, default=100)
    parser.add_argument("--predict-concurrency", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    print("=" * 62)
    print("refac_bid_box Phase 7 레이턴시 벤치마크")
    print(f"대상 서버: {args.base_url}")
    print("=" * 62)

    try:
        httpx.get(f"{args.base_url}/api/v1/health", timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"서버에 접속하지 못했습니다: {exc}")
        print("먼저 서버를 띄우십시오: uvicorn src.app.main:app --port 8000")
        return 2

    print(f"\n[1/3] 낙찰가 예측 API ({args.predict_rounds}회)")
    predict = benchmark_predict(args.base_url, args.predict_rounds, args.predict_concurrency)

    print(f"\n[2/3] 정본 SSE 스트리밍 ({args.sse_rounds}회)")
    first_stage, new_first_token, final = benchmark_sse_canonical(args.base_url, args.sse_rounds)

    print(f"\n[3/3] 단발 질의 API ({args.query_rounds}회)")
    query = benchmark_query(args.base_url, args.query_rounds)

    print("\n" + "-" * 62)
    print("결과")
    results = [
        new_first_token.report(FIRST_TOKEN_TARGET_MS),
        final.report(TOTAL_TARGET_MS),
        first_stage.report(),
        predict.report(PREDICT_TARGET_MS),
    ]
    query.report()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        evidence = build_evidence(
            args.base_url,
            args.predict_rounds,
            args.predict_concurrency,
            first_stage,
            new_first_token,
            final,
            predict,
            query,
        )
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  원시 측정치 저장: {args.output}")

    if final.tagged:
        print("\n  질의별 최장 소요 (SSE 전체)")
        for tag, ms in final.slowest(5):
            print(f"      {_fmt(ms):>8s}  {tag}")

    print("-" * 62)
    if all(results):
        print("레이턴시 목표 전부 달성")
        return 0
    print("레이턴시 목표 미달 항목이 있습니다")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
