"""
scripts/benchmark_read_path_concurrency.py

읽기 경로 동시성 실측 및 A/B 교대 하니스.

목적:
- 낙찰 목록 공고 선채움(N+1 제거)의 순개선 효과를 확정하기 위해 동일 시각에
  선채움을 켠 상태(A)와 끈 상태(B)를 교대로 최소 3 왕복 반복 측정합니다.
- 선채움 영향이 없는 대조군 경로(공고 목록, 대시보드 통계 등)를 함께 측정하여
  배경 부하 및 저장소 잡음의 개입 여부를 판정합니다.
- 단일 요청 웜 스윕(--mode warm), 동시성 c10 스윕(--mode concurrent),
  A/B 교대 스윕(--mode ab)을 지원합니다.
- --dry-run 플래그로 실제 요청 없이 실행 계획(대상 URL, 회차, 동시성, 재시작 명령)을 출력합니다.
- --json 플래그로 측정 결과를 RFC-8259 규격의 JSON 파일로 저장합니다.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import statistics
import subprocess  # nosec B404
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._strict_json import dump_strict_json  # noqa: E402


@dataclass(frozen=True)
class BenchmarkTarget:
    """측정 대상 경로 정의."""

    name: str
    path: str
    is_control: bool  # True: 대조군 (선채움 무관), False: 실험군 (선채움 영향)


# 2026-09-18 회차 정본 사양 8개 경로
TARGETS: list[BenchmarkTarget] = [
    # 대조군: 선채움 변경에 영향받지 않아야 정상 (유효성 검증용)
    BenchmarkTarget(
        name="공고 목록 1쪽",
        path="/api/v1/bids?page=1",
        is_control=True,
    ),
    BenchmarkTarget(
        name="공고 목록 50쪽",
        path="/api/v1/bids?page=50",
        is_control=True,
    ),
    BenchmarkTarget(
        name="공고 목록 용역 필터",
        path="/api/v1/bids?cat=Servc&page=1",
        is_control=True,
    ),
    BenchmarkTarget(
        name="대시보드 통계",
        path="/api/v1/bids/stats",
        is_control=True,
    ),
    BenchmarkTarget(
        name="공고 대비 낙찰 비교 통계",
        path="/api/v1/bids/compare-stats",
        is_control=True,
    ),
    # 실험군: 선채움 켜짐/꺼짐에 직접 영향을 받는 경로
    BenchmarkTarget(
        name="낙찰 목록 1쪽",
        path="/api/v1/bids/results?page=1",
        is_control=False,
    ),
    BenchmarkTarget(
        name="낙찰 목록 50쪽",
        path="/api/v1/bids/results?page=50",
        is_control=False,
    ),
    BenchmarkTarget(
        name="홈 컨텍스트",
        path="/api/v1/bids/home",
        is_control=False,
    ),
]


def calculate_percentile(values: list[float], q: float) -> float:
    """선형 보간을 적용한 백분위 계산 함수 (단일 표본 및 짝수 표본 완벽 지원)."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return float(ordered[0])
    position = (n - 1) * (q / 100.0)
    lower = int(position)
    upper = min(lower + 1, n - 1)
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


@dataclass
class MetricStats:
    """단일 경로 측정 결과 집계."""

    name: str
    path: str
    is_control: bool
    count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    mean_ms: float | None
    min_ms: float | None
    max_ms: float | None
    errors: int
    latencies_ms: list[float] = field(default_factory=list)

    @classmethod
    def from_latencies(
        cls,
        name: str,
        path: str,
        is_control: bool,
        latencies: list[float],
        errors: int = 0,
    ) -> MetricStats:
        if not latencies:
            return cls(
                name=name,
                path=path,
                is_control=is_control,
                count=0,
                p50_ms=None,
                p95_ms=None,
                p99_ms=None,
                mean_ms=None,
                min_ms=None,
                max_ms=None,
                errors=errors,
                latencies_ms=[],
            )
        p50 = calculate_percentile(latencies, 50.0)
        p95 = calculate_percentile(latencies, 95.0)
        p99 = calculate_percentile(latencies, 99.0)
        return cls(
            name=name,
            path=path,
            is_control=is_control,
            count=len(latencies),
            p50_ms=round(p50, 2) if not math.isnan(p50) else None,
            p95_ms=round(p95, 2) if not math.isnan(p95) else None,
            p99_ms=round(p99, 2) if not math.isnan(p99) else None,
            mean_ms=round(statistics.fmean(latencies), 2),
            min_ms=round(min(latencies), 2),
            max_ms=round(max(latencies), 2),
            errors=errors,
            latencies_ms=[round(x, 2) for x in latencies],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "is_control": self.is_control,
            "count": self.count,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "mean_ms": self.mean_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "errors": self.errors,
            "latencies_ms": self.latencies_ms,
        }


def get_restart_command_args(variant: str) -> list[str]:
    """A/B 변체에 따른 컨테이너 재시작 명령 인자 목록을 반환합니다."""
    preload_val = "true" if variant.upper() == "A" else "false"
    return [
        "docker",
        "compose",
        "up",
        "-d",
        "--no-deps",
        "-e",
        f"READ_PATH_PRELOAD_ANNOUNCEMENTS={preload_val}",
        "app",
    ]


def get_restart_command(variant: str) -> str:
    """A/B 변체에 따른 컨테이너 재시작 명령 문자열을 반환합니다."""
    return " ".join(get_restart_command_args(variant))


def build_execution_plan(
    mode: str,
    base_url: str,
    rounds: int,
    concurrency: int,
    sample_count: int,
    warmup_count: int,
    targets: list[BenchmarkTarget] | None = None,
) -> dict[str, Any]:
    """실행 계획 딕셔너리를 생성합니다."""
    selected_targets = targets or TARGETS
    control_targets = [t for t in selected_targets if t.is_control]
    treatment_targets = [t for t in selected_targets if not t.is_control]

    sequence: list[dict[str, Any]] = []
    if mode == "warm":
        sequence.append(
            {
                "phase": "warm_sweep",
                "concurrency": 1,
                "warmup_requests": warmup_count,
                "measured_requests": sample_count,
            }
        )
    elif mode == "concurrent":
        sequence.append(
            {
                "phase": "concurrent_sweep",
                "concurrency": concurrency,
                "warmup_requests": warmup_count,
                "measured_requests": sample_count,
            }
        )
    elif mode == "ab":
        for r in range(1, rounds + 1):
            sequence.append(
                {
                    "round": r,
                    "variant": "A",
                    "preload": True,
                    "concurrency": concurrency,
                    "warmup_requests": warmup_count,
                    "measured_requests": sample_count,
                    "restart_command": get_restart_command("A"),
                }
            )
            sequence.append(
                {
                    "round": r,
                    "variant": "B",
                    "preload": False,
                    "concurrency": concurrency,
                    "warmup_requests": warmup_count,
                    "measured_requests": sample_count,
                    "restart_command": get_restart_command("B"),
                }
            )

    return {
        "mode": mode,
        "base_url": base_url,
        "warmup_count": warmup_count,
        "sample_count": sample_count,
        "concurrency": concurrency,
        "ab_rounds": rounds if mode == "ab" else None,
        "target_count": len(selected_targets),
        "control_target_count": len(control_targets),
        "treatment_target_count": len(treatment_targets),
        "targets": [
            {
                "name": t.name,
                "path": t.path,
                "type": "대조군" if t.is_control else "실험군",
            }
            for t in selected_targets
        ],
        "restart_commands": {
            "A_preload_on": get_restart_command("A"),
            "B_preload_off": get_restart_command("B"),
        },
        "execution_sequence": sequence,
    }


def print_dry_run_plan(plan: dict[str, Any]) -> None:
    """드라이런 실행 계획을 터미널에 포맷팅하여 출력합니다."""
    print("=" * 70)
    print("읽기 경로 동시성 하니스 실행 계획 (DRY RUN)")
    print("=" * 70)
    print(f"  동작 모드: {plan['mode']}")
    print(f"  대상 URL: {plan['base_url']}")
    print(f"  워밍업 회차: {plan['warmup_count']}회")
    print(f"  측정 회차: {plan['sample_count']}회")
    print(f"  동시성 수준: c{plan['concurrency']}")
    if plan.get("ab_rounds"):
        print(f"  A/B 교대 왕복: {plan['ab_rounds']}회 (총 {plan['ab_rounds'] * 2}회 측정)")
    print("-" * 70)
    print("측정 대상 경로 (총 8개):")
    print("  [대조군: 선채움 무관, 배경 잡음 검증용]")
    for t in plan["targets"]:
        if t["type"] == "대조군":
            print(f"    - {t['name']}: {t['path']}")
    print("  [실험군: 선채움 직접 영향]")
    for t in plan["targets"]:
        if t["type"] == "실험군":
            print(f"    - {t['name']}: {t['path']}")
    print("-" * 70)
    print("컨테이너 재시작 명령:")
    print(f"  A (선채움 ON):  {plan['restart_commands']['A_preload_on']}")
    print(f"  B (선채움 OFF): {plan['restart_commands']['B_preload_off']}")
    print("-" * 70)
    print("실행 순서:")
    for step in plan["execution_sequence"]:
        if plan["mode"] == "ab":
            print(
                f"  왕복 {step['round']} [{step['variant']}: 선채움 {'ON' if step['preload'] else 'OFF'}] "
                f"워밍업 {step['warmup_requests']}회 -> c{step['concurrency']} {step['measured_requests']}회 측정"
            )
            print(f"    재시작 명령: {step['restart_command']}")
        else:
            print(
                f"  {step['phase']}: 워밍업 {step['warmup_requests']}회 -> "
                f"c{step['concurrency']} {step['measured_requests']}회 측정"
            )
    print("=" * 70)
    print("실제 HTTP 요청이나 Docker 조작을 수행하지 않고 안전하게 종료합니다.")


def request_single(client: httpx.Client, url: str) -> tuple[float, bool]:
    """단일 HTTP 요청의 지연시간(ms)과 성공 여부를 반환합니다."""
    started = time.perf_counter_ns()
    success = False
    try:
        resp = client.get(url, timeout=60.0)
        success = resp.status_code == 200
    except httpx.HTTPError:
        success = False
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return elapsed_ms, success


def measure_target_single_sweep(
    client: httpx.Client,
    base_url: str,
    target: BenchmarkTarget,
    warmup_count: int = 3,
    sample_count: int = 30,
) -> MetricStats:
    """단일 요청 웜 스윕 측정."""
    full_url = f"{base_url.rstrip('/')}{target.path}"
    # 워밍업
    for _ in range(warmup_count):
        request_single(client, full_url)

    # 본 측정
    latencies: list[float] = []
    errors = 0
    for _ in range(sample_count):
        lat_ms, ok = request_single(client, full_url)
        if ok:
            latencies.append(lat_ms)
        else:
            errors += 1
    return MetricStats.from_latencies(
        name=target.name,
        path=target.path,
        is_control=target.is_control,
        latencies=latencies,
        errors=errors,
    )


def measure_target_concurrent_sweep(
    base_url: str,
    target: BenchmarkTarget,
    concurrency: int = 10,
    sample_count: int = 100,
    warmup_count: int = 3,
) -> MetricStats:
    """동시성 c10 스윕 측정."""
    full_url = f"{base_url.rstrip('/')}{target.path}"
    # 워밍업
    with httpx.Client() as warmup_client:
        for _ in range(warmup_count):
            request_single(warmup_client, full_url)

    # 동시 요청 측정
    latencies: list[float] = []
    errors = 0

    def _worker() -> tuple[float, bool]:
        with httpx.Client() as c:
            return request_single(c, full_url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_worker) for _ in range(sample_count)]
        for f in concurrent.futures.as_completed(futures):
            lat_ms, ok = f.result()
            if ok:
                latencies.append(lat_ms)
            else:
                errors += 1

    return MetricStats.from_latencies(
        name=target.name,
        path=target.path,
        is_control=target.is_control,
        latencies=latencies,
        errors=errors,
    )


def format_stats_table(stats_list: list[MetricStats]) -> str:
    """지표 목록을 가독성 있는 마크다운 테이블 문자열로 변환합니다."""
    lines: list[str] = [
        "| 구분 | 경로 | P50 (ms) | P95 (ms) | P99 (ms) | 평균 (ms) | 최대 (ms) | 오류 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in stats_list:
        grp = "대조군" if s.is_control else "실험군"
        p50 = f"{s.p50_ms:.2f}" if s.p50_ms is not None else "-"
        p95 = f"{s.p95_ms:.2f}" if s.p95_ms is not None else "-"
        p99 = f"{s.p99_ms:.2f}" if s.p99_ms is not None else "-"
        mean = f"{s.mean_ms:.2f}" if s.mean_ms is not None else "-"
        max_v = f"{s.max_ms:.2f}" if s.max_ms is not None else "-"
        lines.append(
            f"| {grp} | {s.name} | {p50} | {p95} | {p99} | {mean} | {max_v} | {s.errors} |"
        )
    return "\n".join(lines)


def format_round_comparison(
    round_idx: int,
    stats_a: dict[str, MetricStats],
    stats_b: dict[str, MetricStats],
) -> tuple[str, dict[str, Any]]:
    """A와 B의 왕복별 비교 테이블 및 데이터 딕셔너리를 생성합니다."""
    lines: list[str] = [
        f"\n### [왕복 {round_idx}] A (선채움 ON) vs B (선채움 OFF) P95 비교",
        "| 구분 | 경로 | A P95 (ms) | B P95 (ms) | 차이 (A - B) | 변화율 (%) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    diff_records: dict[str, Any] = {}
    for t in TARGETS:
        sa = stats_a.get(t.name)
        sb = stats_b.get(t.name)
        a_p95 = sa.p95_ms if sa else None
        b_p95 = sb.p95_ms if sb else None

        if a_p95 is not None and b_p95 is not None:
            diff = round(a_p95 - b_p95, 2)
            pct = round(((a_p95 - b_p95) / b_p95) * 100.0, 1) if b_p95 > 0 else 0.0
            diff_str = f"{diff:+.2f}ms"
            pct_str = f"{pct:+.1f}%"
        else:
            diff = None
            pct = None
            diff_str = "-"
            pct_str = "-"

        grp = "대조군" if t.is_control else "실험군"
        lines.append(
            f"| {grp} | {t.name} | "
            f"{a_p95 if a_p95 is not None else '-'} | "
            f"{b_p95 if b_p95 is not None else '-'} | "
            f"{diff_str} | {pct_str} |"
        )
        diff_records[t.name] = {
            "is_control": t.is_control,
            "a_p95_ms": a_p95,
            "b_p95_ms": b_p95,
            "diff_ms": diff,
            "pct_change": pct,
        }
    return "\n".join(lines), diff_records


def run_ab_benchmark(
    base_url: str,
    rounds: int = 3,
    concurrency: int = 10,
    sample_count: int = 100,
    warmup_count: int = 3,
    auto_restart: bool = False,
) -> dict[str, Any]:
    """A/B 교대 반복 하니스 실행 엔진.

    교대로 최소 3 왕복(A1, B1, A2, B2, A3, B3)을 실행하고
    각 왕복별 수치, 차이, 대조군 변동을 모두 기록합니다.
    """
    if rounds < 3:
        raise ValueError(f"A/B 하니스는 최소 3 왕복이어야 합니다 (현재 지정값: {rounds})")

    round_results: list[dict[str, Any]] = []

    for r in range(1, rounds + 1):
        print(f"\n>>> [왕복 {r}/{rounds}] A (선채움 ON) 측정 준비")
        if auto_restart:
            cmd_args = get_restart_command_args("A")
            print(f"컨테이너 재시작 실행: {' '.join(cmd_args)}")
            subprocess.run(cmd_args, check=True)  # nosec B603
            time.sleep(5)  # 기동 대기

        stats_a: dict[str, MetricStats] = {}
        for t in TARGETS:
            stats_a[t.name] = measure_target_concurrent_sweep(
                base_url,
                t,
                concurrency=concurrency,
                sample_count=sample_count,
                warmup_count=warmup_count,
            )

        print(f"\n>>> [왕복 {r}/{rounds}] B (선채움 OFF) 측정 준비")
        if auto_restart:
            cmd_args = get_restart_command_args("B")
            print(f"컨테이너 재시작 실행: {' '.join(cmd_args)}")
            subprocess.run(cmd_args, check=True)  # nosec B603
            time.sleep(5)  # 기동 대기

        stats_b: dict[str, MetricStats] = {}
        for t in TARGETS:
            stats_b[t.name] = measure_target_concurrent_sweep(
                base_url,
                t,
                concurrency=concurrency,
                sample_count=sample_count,
                warmup_count=warmup_count,
            )

        table_str, diff_data = format_round_comparison(r, stats_a, stats_b)
        print(table_str)

        round_results.append(
            {
                "round": r,
                "stats_a": {k: v.to_dict() for k, v in stats_a.items()},
                "stats_b": {k: v.to_dict() for k, v in stats_b.items()},
                "comparison": diff_data,
            }
        )

    # 전체 왕복 요약 집계
    summary: dict[str, Any] = {}
    for t in TARGETS:
        a_p95_vals = [
            round_results[i]["stats_a"][t.name]["p95_ms"]
            for i in range(rounds)
            if round_results[i]["stats_a"][t.name]["p95_ms"] is not None
        ]
        b_p95_vals = [
            round_results[i]["stats_b"][t.name]["p95_ms"]
            for i in range(rounds)
            if round_results[i]["stats_b"][t.name]["p95_ms"] is not None
        ]
        med_a = statistics.median(a_p95_vals) if a_p95_vals else None
        med_b = statistics.median(b_p95_vals) if b_p95_vals else None
        diff = round(med_a - med_b, 2) if med_a is not None and med_b is not None else None
        pct = (
            round(((med_a - med_b) / med_b) * 100.0, 1)
            if med_a is not None and med_b is not None and med_b > 0
            else None
        )
        summary[t.name] = {
            "is_control": t.is_control,
            "median_a_p95_ms": round(med_a, 2) if med_a is not None else None,
            "median_b_p95_ms": round(med_b, 2) if med_b is not None else None,
            "diff_ms": diff,
            "pct_change": pct,
        }

    return {
        "mode": "ab",
        "base_url": base_url,
        "rounds": rounds,
        "concurrency": concurrency,
        "sample_count": sample_count,
        "round_results": round_results,
        "summary": summary,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인수 파서 구성."""
    parser = argparse.ArgumentParser(
        description="읽기 경로 동시성 측정 및 선채움 A/B 교대 하니스",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["warm", "concurrent", "ab"],
        default="ab",
        help="측정 모드: warm (단일 요청 웜 30회), concurrent (c10 100회), ab (선채움 A/B 교대 최소 3왕복, 기본값)",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="대상 서버 주소 (기본값: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 요청이나 컨테이너 재시작 없이 실행 계획만 출력",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="A/B 교대 왕복 횟수 (최소 3, 기본값: 3)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="동시성 요청 수 (기본값: 10)",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=None,
        help="회차별 측정 요청 수 (warm: 30, concurrent/ab: 100 기본값)",
    )
    parser.add_argument(
        "--warmup-count",
        type=int,
        default=3,
        help="회차별 워밍업 요청 수 (기본값: 3)",
    )
    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="A/B 교대 시 Docker 컨테이너 재시작 명령 자동 실행 (코디네이터 실측용)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=str,
        nargs="?",
        const="artifacts/read_path_concurrency.json",
        default=None,
        help="측정 결과 또는 실행 계획을 JSON 파일로 저장할 경로",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.sample_count is None:
        sample_count = 30 if args.mode == "warm" else 100
    else:
        sample_count = args.sample_count

    if args.mode == "ab" and args.rounds < 3:
        print(f"[오류] ab 모드는 최소 3 왕복이어야 합니다 (입력값: {args.rounds})", file=sys.stderr)
        return 1

    plan = build_execution_plan(
        mode=args.mode,
        base_url=args.base_url,
        rounds=args.rounds,
        concurrency=args.concurrency if args.mode != "warm" else 1,
        sample_count=sample_count,
        warmup_count=args.warmup_count,
    )

    if args.dry_run:
        print_dry_run_plan(plan)
        if args.json_path:
            json_file = Path(args.json_path)
            json_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"dry_run": True, "plan": plan}
            json_file.write_text(dump_strict_json(payload), encoding="utf-8")
            print(f"드라이런 실행 계획을 JSON으로 저장했습니다: {args.json_path}")
        return 0

    print(f"=== 읽기 경로 동시성 측정 시작 (모드: {args.mode}) ===")
    results_payload: dict[str, Any] = {}

    if args.mode == "warm":
        with httpx.Client() as client:
            stats = [
                measure_target_single_sweep(
                    client,
                    args.base_url,
                    t,
                    warmup_count=args.warmup_count,
                    sample_count=sample_count,
                )
                for t in TARGETS
            ]
        print(format_stats_table(stats))
        results_payload = {
            "mode": "warm",
            "base_url": args.base_url,
            "sample_count": sample_count,
            "stats": [s.to_dict() for s in stats],
        }

    elif args.mode == "concurrent":
        stats = [
            measure_target_concurrent_sweep(
                args.base_url,
                t,
                concurrency=args.concurrency,
                sample_count=sample_count,
                warmup_count=args.warmup_count,
            )
            for t in TARGETS
        ]
        print(format_stats_table(stats))
        results_payload = {
            "mode": "concurrent",
            "base_url": args.base_url,
            "concurrency": args.concurrency,
            "sample_count": sample_count,
            "stats": [s.to_dict() for s in stats],
        }

    elif args.mode == "ab":
        results_payload = run_ab_benchmark(
            base_url=args.base_url,
            rounds=args.rounds,
            concurrency=args.concurrency,
            sample_count=sample_count,
            warmup_count=args.warmup_count,
            auto_restart=args.auto_restart,
        )
        print("\n=== A/B 교대 측정 최종 요약 (전체 왕복 중앙값) ===")
        print(
            "| 구분 | 경로 | A P95 중앙값 (ms) | B P95 중앙값 (ms) | 순차이 (A - B) | 순개선율 (%) |"
        )
        print("| --- | --- | ---: | ---: | ---: | ---: |")
        for t in TARGETS:
            sm = results_payload["summary"][t.name]
            grp = "대조군" if t.is_control else "실험군"
            med_a = f"{sm['median_a_p95_ms']:.2f}" if sm["median_a_p95_ms"] is not None else "-"
            med_b = f"{sm['median_b_p95_ms']:.2f}" if sm["median_b_p95_ms"] is not None else "-"
            diff = f"{sm['diff_ms']:+.2f}ms" if sm["diff_ms"] is not None else "-"
            pct = f"{sm['pct_change']:+.1f}%" if sm["pct_change"] is not None else "-"
            print(f"| {grp} | {t.name} | {med_a} | {med_b} | {diff} | {pct} |")

    if args.json_path:
        json_file = Path(args.json_path)
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(dump_strict_json(results_payload), encoding="utf-8")
        print(f"\n측정 결과를 JSON으로 저장했습니다: {args.json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
