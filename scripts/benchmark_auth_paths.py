"""인증이 필요한 읽기 경로의 레이턴시를 단일 웜과 동시성(c10) 조건에서 측정하는 하니스 스크립트.

주요 특징:
1. 회차당 단 1회 로그인하여 발급된 세션 쿠키(bidbox_session)를 추출하고 이후 모든 요청에 재사용합니다.
   (매 요청 로그인 시 login_rate_limiter 에 의해 429 차단이 발생하므로 금지됩니다.)
2. 부작용이 없는 읽기 경로만 선별하여 측정합니다.
   (DB 쓰기, 외부 수집, 배치 작업 등록 엔드포인트는 엄격히 제외됩니다.)
3. 자격 증명(사용자명, 비밀번호)은 인자나 환경변수로 주입받으며 기본값으로 하드코딩되지 않습니다.
4. --dry-run 옵션으로 실제 요청 없이 대상 경로, 회차, 동시성 구성을 확인할 수 있습니다.
5. 단일 웜(워밍업 3회 + 30회)과 동시성(c10, 100회) 두 모드를 지원하며 P50, P95, 최대 레이턴시를 집계합니다.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import json
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SESSION_COOKIE_NAME = "bidbox_session"


@dataclass(frozen=True)
class EndpointSpec:
    """측정 대상 엔드포인트 사양."""

    name: str
    method: str
    path: str
    description: str
    headers: dict[str, str] = field(default_factory=dict)


# 부작용이 없는 순수 읽기 엔드포인트 목록
TARGET_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        name="accounts_me",
        method="GET",
        path="/api/v1/accounts/me",
        description="현재 로그인 사용자 정보 조회 (인증 필수, 부작용 없음)",
    ),
    EndpointSpec(
        name="evaluations_profiles",
        method="GET",
        path="/api/v1/evaluations/profiles",
        description="내 평가 프로필 목록 조회 (인증 필수, 부작용 없음)",
    ),
    EndpointSpec(
        name="evaluations_snapshots",
        method="GET",
        path="/api/v1/evaluations/snapshots",
        description="내 분석 스냅샷 목록 조회 (인증 필수, 부작용 없음)",
    ),
]

# 부작용으로 인해 측정 대상에서 명시적으로 제외된 엔드포인트 및 사유
EXCLUDED_ENDPOINTS: list[dict[str, str]] = [
    {
        "method": "POST",
        "path": "/api/v1/bids/collect",
        "reason": "나라장터 외부 수집을 실행하고 DB에 쓰므로 심각한 부작용 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/evaluations/analyze",
        "reason": "_save_snapshot_async를 통해 BidEvaluationSnapshot/Evidence를 DB에 commit하므로 부작용 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/evaluations/profiles",
        "reason": "새 평가 프로필을 DB에 INSERT 및 commit하므로 부작용 발생",
    },
    {
        "method": "PUT",
        "path": "/api/v1/evaluations/profiles/{profile_id}",
        "reason": "기존 평가 프로필을 DB에 UPDATE 및 commit하므로 부작용 발생",
    },
    {
        "method": "DELETE",
        "path": "/api/v1/evaluations/profiles/{profile_id}",
        "reason": "평가 프로필을 DB에서 DELETE 및 commit하므로 부작용 발생",
    },
    {
        "method": "GET",
        "path": "/api/v1/evaluations/profiles/{profile_id}",
        "reason": "단건 조회 시 특정 profile_id 존재에 의존하며 부재 시 404를 반환하므로 범용 하니스 부적합 (목록 조회로 대체)",
    },
    {
        "method": "POST",
        "path": "/api/v1/evaluations/snapshots",
        "reason": "분석 스냅샷을 DB에 직접 INSERT 및 commit하므로 부작용 발생",
    },
    {
        "method": "GET",
        "path": "/api/v1/evaluations/snapshots/{snapshot_id}",
        "reason": "단건 조회 시 특정 snapshot_id 존재에 의존하며 부재 시 404를 반환하므로 범용 하니스 부적합 (목록 조회로 대체)",
    },
    {
        "method": "DELETE",
        "path": "/api/v1/evaluations/snapshots/{snapshot_id}",
        "reason": "분석 스냅샷을 DB에서 DELETE 및 commit하므로 부작용 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/automation/run/*",
        "reason": "수집/KB갱신/예측검증/재학습 등 백그라운드 태스크 등록 및 DB 쓰기 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/automation/job/{job_id}/confirm",
        "reason": "확인 토큰 소비 및 작업 실행 상태 변경 DB 쓰기 발생",
    },
    {
        "method": "GET",
        "path": "/api/v1/automation/job/{job_id}/status",
        "reason": "sync_automation_status로 인한 상태 동기화 DB 쓰기 발생 및 동적 job_id 의존",
    },
    {
        "method": "POST",
        "path": "/api/v1/automation/job/{job_id}/cancel",
        "reason": "작업 취소 처리 및 DB 쓰기 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/automation/job/{job_id}/callback",
        "reason": "워커 상태 수신 처리 및 DB 쓰기 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/accounts/signup",
        "reason": "새 사용자 계정을 DB에 INSERT 및 commit하므로 부작용 발생",
    },
    {
        "method": "POST",
        "path": "/api/v1/accounts/logout",
        "reason": "세션 저장소에서 세션을 파기하여 이후 측정을 불가능하게 만드는 부작용 발생",
    },
]


def extract_session_cookie_from_response(response: httpx.Response) -> str:
    """로그인 응답에서 bidbox_session 쿠키 값을 추출합니다."""
    # 1. Set-Cookie 헤더 목록에서 추출
    for header_val in response.headers.get_list("set-cookie"):
        for part in header_val.split(";"):
            part = part.strip()
            if part.startswith(f"{SESSION_COOKIE_NAME}="):
                val = part.split("=", 1)[1].strip()
                if val:
                    return val

    # 2. response.cookies 객체에서 추출 (request 가 바인딩된 경우)
    try:
        cookie = response.cookies.get(SESSION_COOKIE_NAME)
        if cookie:
            return cookie
    except (RuntimeError, AttributeError):
        pass

    raise ValueError(f"응답에서 {SESSION_COOKIE_NAME} 쿠키를 찾을 수 없습니다.")


def login_and_obtain_session_cookie(
    base_url: str,
    username: str,
    password: str,
    timeout: float = 10.0,
) -> str:
    """회차당 단 1회 로그인하여 세션 쿠키(bidbox_session)를 발급받습니다.

    주의: login_rate_limiter 가 적용되어 있으므로 매 요청마다 로그인하면 안 됩니다.
    """
    login_url = f"{base_url.rstrip('/')}/api/v1/accounts/login"
    try:
        response = httpx.post(
            login_url,
            json={"username": username, "password": password},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"로그인 요청 실패 ({login_url}): {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"로그인 실패 (HTTP {response.status_code}): {response.text}")

    return extract_session_cookie_from_response(response)


def resolve_credentials(
    username: str | None,
    password: str | None,
    session_cookie: str | None,
) -> tuple[str | None, str | None, str | None]:
    """자격 증명 또는 세션 쿠키를 인자 및 환경변수로부터 해석합니다.

    기본값으로 하드코딩된 계정을 절대 사용하지 않습니다.
    """
    resolved_cookie = session_cookie or os.getenv("BENCHMARK_SESSION_COOKIE")
    if resolved_cookie:
        if resolved_cookie.startswith(f"{SESSION_COOKIE_NAME}="):
            resolved_cookie = resolved_cookie.split("=", 1)[1]
        return None, None, resolved_cookie

    resolved_user = (
        username or os.getenv("BENCHMARK_USERNAME") or os.getenv("BENCHMARK_AUTH_USERNAME")
    )
    resolved_pwd = (
        password or os.getenv("BENCHMARK_PASSWORD") or os.getenv("BENCHMARK_AUTH_PASSWORD")
    )
    return resolved_user, resolved_pwd, None


def calculate_percentile(values: list[float], q: float) -> float:
    """정렬된 표본에서 백분위수를 선형 보간으로 계산합니다."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * (q / 100.0)
    lower = math.floor(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass
class MeasurementResult:
    """개별 엔드포인트의 측정 결과 집계."""

    endpoint_name: str
    method: str
    path: str
    mode: str
    total_requests: int
    successful_requests: int
    error_count: int
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    min_ms: float | None
    mean_ms: float | None
    latencies_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def summarize_latencies(
    endpoint: EndpointSpec,
    mode: str,
    total_requests: int,
    latencies: list[float],
    errors: int,
) -> MeasurementResult:
    """수집된 레이턴시 표본을 백분위수와 통계량으로 요약합니다."""
    if latencies:
        p50 = calculate_percentile(latencies, 50.0)
        p95 = calculate_percentile(latencies, 95.0)
        max_v = max(latencies)
        min_v = min(latencies)
        mean_v = statistics.fmean(latencies)
    else:
        p50 = p95 = max_v = min_v = mean_v = None

    return MeasurementResult(
        endpoint_name=endpoint.name,
        method=endpoint.method,
        path=endpoint.path,
        mode=mode,
        total_requests=total_requests,
        successful_requests=len(latencies),
        error_count=errors,
        p50_ms=round(p50, 2) if p50 is not None else None,
        p95_ms=round(p95, 2) if p95 is not None else None,
        max_ms=round(max_v, 2) if max_v is not None else None,
        min_ms=round(min_v, 2) if min_v is not None else None,
        mean_ms=round(mean_v, 2) if mean_v is not None else None,
        latencies_ms=latencies,
    )


def measure_single_warm(
    client: httpx.Client,
    endpoint: EndpointSpec,
    warmup_rounds: int = 3,
    rounds: int = 30,
) -> MeasurementResult:
    """단일 웜 조건(워밍업 후 순차 반복) 레이턴시를 측정합니다."""
    # 1. 사전 워밍업
    for _ in range(warmup_rounds):
        with contextlib.suppress(httpx.HTTPError):
            client.request(endpoint.method, endpoint.path)

    # 2. 본 측정
    latencies: list[float] = []
    errors = 0
    for _ in range(rounds):
        start = time.perf_counter_ns()
        try:
            resp = client.request(endpoint.method, endpoint.path)
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000.0
            if resp.status_code == 200:
                latencies.append(elapsed_ms)
            else:
                errors += 1
        except httpx.HTTPError:
            errors += 1

    return summarize_latencies(
        endpoint=endpoint,
        mode="single_warm",
        total_requests=rounds,
        latencies=latencies,
        errors=errors,
    )


def measure_concurrency(
    base_url: str,
    cookie_value: str,
    endpoint: EndpointSpec,
    concurrency: int = 10,
    rounds: int = 100,
    timeout: float = 30.0,
) -> MeasurementResult:
    """동시성 조건(c10 풀 기반 병렬 요청) 레이턴시를 측정합니다."""
    cookies = {SESSION_COOKIE_NAME: cookie_value}
    limits = httpx.Limits(
        max_connections=concurrency * 2,
        max_keepalive_connections=concurrency * 2,
    )

    latencies: list[float] = []
    errors = 0

    with httpx.Client(
        base_url=base_url,
        cookies=cookies,
        timeout=timeout,
        limits=limits,
    ) as client:

        def _request_worker(_: int) -> tuple[bool, float]:
            started = time.perf_counter_ns()
            try:
                resp = client.request(endpoint.method, endpoint.path)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
                return resp.status_code == 200, elapsed_ms
            except httpx.HTTPError:
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
                return False, elapsed_ms

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_request_worker, i) for i in range(rounds)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    succeeded, elapsed_ms = future.result()
                    if succeeded:
                        latencies.append(elapsed_ms)
                    else:
                        errors += 1
                except Exception:
                    errors += 1

    return summarize_latencies(
        endpoint=endpoint,
        mode="concurrency",
        total_requests=rounds,
        latencies=latencies,
        errors=errors,
    )


def filter_endpoints(names_csv: str | None) -> list[EndpointSpec]:
    """이름 필터에 맞춰 대상 엔드포인트를 선별합니다."""
    if not names_csv:
        return list(TARGET_ENDPOINTS)
    wanted = {name.strip() for name in names_csv.split(",") if name.strip()}
    selected = [ep for ep in TARGET_ENDPOINTS if ep.name in wanted]
    if not selected:
        available = ", ".join(ep.name for ep in TARGET_ENDPOINTS)
        raise ValueError(f"선택된 엔드포인트가 없습니다. 유효한 이름: {available}")
    return selected


def print_dry_run_summary(
    base_url: str,
    endpoints: list[EndpointSpec],
    mode: str,
    warmup_rounds: int,
    warm_rounds: int,
    concurrency: int,
    concurrency_rounds: int,
) -> None:
    """--dry-run 시 계획된 측정 구성을 출력합니다."""
    print("=" * 70)
    print("인증 경로 레이턴시 벤치마크 (DRY RUN)")
    print("=" * 70)
    print(f"대상 서버 기본 URL: {base_url}")
    print(f"측정 모드: {mode}")
    if mode in ("all", "warm"):
        print(f"단일 웜 조건: 워밍업 {warmup_rounds}회 + 본 측정 {warm_rounds}회")
    if mode in ("all", "concurrency"):
        print(f"동시성 조건: c{concurrency} 동시 요청, 총 {concurrency_rounds}회")
    print(
        f"세션 쿠키 발급: POST /api/v1/accounts/login 단 1회 호출 후 {SESSION_COOKIE_NAME} 재사용"
    )
    print("\n[측정 대상 경로 (부작용 없는 읽기 경로)]")
    for ep in endpoints:
        print(f"  - {ep.name}: {ep.method} {ep.path} ({ep.description})")

    print("\n[제외된 경로 및 사유 (DB 쓰기 / 외부 수집 등 부작용 방지)]")
    for item in EXCLUDED_ENDPOINTS:
        print(f"  - {item['method']} {item['path']}: {item['reason']}")

    print("\n드라이런 모드: 실제 네트워크 요청 및 로그인을 수행하지 않고 안전하게 종료합니다.")
    print("=" * 70)


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI 인자 파서를 구성합니다."""
    parser = argparse.ArgumentParser(description="인증 경로 레이턴시 벤치마크 하니스")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="대상 서버 기본 URL (기본: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="인증 계정 사용자명 (미제공 시 BENCHMARK_USERNAME 환경변수)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="인증 계정 비밀번호 (미제공 시 BENCHMARK_PASSWORD 환경변수)",
    )
    parser.add_argument(
        "--session-cookie",
        default=None,
        help="기존 발급된 bidbox_session 쿠키 값 (지정 시 로그인 단계 건너뜀)",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "warm", "concurrency"],
        default="all",
        help="측정 모드 (warm: 단일 웜, concurrency: 동시성 c10, all: 둘 다)",
    )
    parser.add_argument(
        "--warmup-rounds",
        type=int,
        default=3,
        help="단일 웜 사전 워밍업 횟수 (기본: 3)",
    )
    parser.add_argument(
        "--warm-rounds",
        type=int,
        default=30,
        help="단일 웜 본 측정 횟수 (기본: 30)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="동시성 작업자 수 (기본: 10)",
    )
    parser.add_argument(
        "--concurrency-rounds",
        type=int,
        default=100,
        help="동시성 총 요청 횟수 (기본: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="요청 타임아웃 초 (기본: 30.0)",
    )
    parser.add_argument(
        "--endpoints",
        default=None,
        help="쉼표로 구분된 특정 엔드포인트 필터 (예: accounts_me,evaluations_profiles)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="결과 JSON 파일 저장 경로",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        type=Path,
        default=None,
        help="--output 의 별칭 (JSON 파일 경로)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="실제 요청 없이 대상 경로, 회차, 동시성을 출력하고 정상 종료",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        endpoints = filter_endpoints(args.endpoints)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or args.json_output

    # dry-run 처리
    if args.dry_run:
        print_dry_run_summary(
            base_url=args.base_url,
            endpoints=endpoints,
            mode=args.mode,
            warmup_rounds=args.warmup_rounds,
            warm_rounds=args.warm_rounds,
            concurrency=args.concurrency,
            concurrency_rounds=args.concurrency_rounds,
        )
        return 0

    # 자격 증명 해석 (인자 및 환경변수)
    username, password, cookie = resolve_credentials(
        username=args.username,
        password=args.password,
        session_cookie=args.session_cookie,
    )

    if not cookie and (not username or not password):
        print(
            "오류: 자격 증명이 주어지지 않았습니다. "
            "--username 및 --password 인자 또는 환경변수(BENCHMARK_USERNAME, BENCHMARK_PASSWORD)를 지정하십시오. "
            "(또는 --session-cookie 지정)",
            file=sys.stderr,
        )
        return 2

    # 세션 쿠키 확보 (회차당 단 1회 로그인)
    if not cookie:
        print(f"세션 쿠키 발급 시도 중: {args.base_url}/api/v1/accounts/login")
        try:
            cookie = login_and_obtain_session_cookie(
                base_url=args.base_url,
                username=username,  # type: ignore[arg-type]
                password=password,  # type: ignore[arg-type]
                timeout=args.timeout,
            )
            print("세션 쿠키 발급 성공 (쿠키를 재사용합니다)")
        except Exception as exc:
            print(f"세션 쿠키 발급 실패: {exc}", file=sys.stderr)
            return 3

    results: list[MeasurementResult] = []

    # 단일 웜 측정
    if args.mode in ("all", "warm"):
        print("\n--- 단일 웜 측정 시작 (워밍업 3회 + 30회 순차) ---")
        client = httpx.Client(
            base_url=args.base_url,
            cookies={SESSION_COOKIE_NAME: cookie},
            timeout=args.timeout,
        )
        with client:
            for ep in endpoints:
                print(f"  측정 중: {ep.name} ({ep.path})")
                res = measure_single_warm(
                    client=client,
                    endpoint=ep,
                    warmup_rounds=args.warmup_rounds,
                    rounds=args.warm_rounds,
                )
                results.append(res)
                print(
                    f"    결과: P50={res.p50_ms}ms, P95={res.p95_ms}ms, 최대={res.max_ms}ms "
                    f"(성공: {res.successful_requests}/{res.total_requests}, 오류: {res.error_count})"
                )

    # 동시성 측정
    if args.mode in ("all", "concurrency"):
        print(f"\n--- 동시성 측정 시작 (c{args.concurrency}, 총 {args.concurrency_rounds}회) ---")
        for ep in endpoints:
            print(f"  측정 중: {ep.name} ({ep.path})")
            res = measure_concurrency(
                base_url=args.base_url,
                cookie_value=cookie,
                endpoint=ep,
                concurrency=args.concurrency,
                rounds=args.concurrency_rounds,
                timeout=args.timeout,
            )
            results.append(res)
            print(
                f"    결과: P50={res.p50_ms}ms, P95={res.p95_ms}ms, 최대={res.max_ms}ms "
                f"(성공: {res.successful_requests}/{res.total_requests}, 오류: {res.error_count})"
            )

    # 최종 요약 출력
    print("\n" + "=" * 70)
    print("인증 경로 레이턴시 벤치마크 결과 요약")
    print("=" * 70)
    print(
        f"{'모드':<12} {'엔드포인트':<22} {'P50 (ms)':<10} {'P95 (ms)':<10} {'최대 (ms)':<10} {'오류'}"
    )
    print("-" * 70)
    for r in results:
        p50_str = f"{r.p50_ms:.2f}" if r.p50_ms is not None else "-"
        p95_str = f"{r.p95_ms:.2f}" if r.p95_ms is not None else "-"
        max_str = f"{r.max_ms:.2f}" if r.max_ms is not None else "-"
        print(
            f"{r.mode:<12} {r.endpoint_name:<22} {p50_str:<10} {p95_str:<10} {max_str:<10} {r.error_count}"
        )
    print("=" * 70)

    # JSON 저장
    if output_path:
        output_data = {
            "base_url": args.base_url,
            "mode": args.mode,
            "results": [r.to_dict() for r in results],
            "target_endpoints": [
                {"name": ep.name, "method": ep.method, "path": ep.path} for ep in endpoints
            ],
            "excluded_endpoints": EXCLUDED_ENDPOINTS,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n결과가 JSON 파일로 저장되었습니다: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
