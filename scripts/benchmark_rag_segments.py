"""단발 질의 API 의 RAG 구간별 소요를 분리 수집하는 벤치마크 하네스.

`src/rag/engine.py` 는 `LATENCY_SEGMENT_LOGGING` 이 켜져 있을 때 요청마다
`rag_engine_latency: trace_id=... plan_ms=... llm_ms=... total_ms=...` 형태의
구조화 로그를 남깁니다. 계측은 있으나 그 로그를 모아 분위수로 집계하는 도구가
없어 실측이 미뤄져 왔습니다. 이 하네스가 그 자리를 채웁니다.

로그는 서버 쪽에서 나오므로 HTTP 응답만으로는 구간을 알 수 없습니다. 질의를
보낸 뒤 컨테이너 로그에서 `rag_engine_latency:` 줄을 읽어 집계합니다.

구간 합이 total 과 어긋나면 그 차이를 `residual` 로 남깁니다. 조용히 버리면
계측되지 않은 병목을 놓칩니다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._strict_json import dump_strict_json, sanitize_nan_to_none  # noqa: E402
from scripts.benchmark_latency import Samples  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CONTAINER = "refac_bid_box-app-1"
QUERY_PATH = "/api/v1/chatbot/query"

# 캐시 적중으로 측정치가 왜곡되지 않도록 질의를 매번 바꿉니다.
QUERIES = [
    "적격심사 기준이 어떻게 되나요",
    "2025년 물품 낙찰 평균 낙찰률 알려줘",
    "공사 부문 최근 낙찰 동향 알려줘",
    "수요기관별 낙찰 금액 상위는 어디야",
    "용역 계약 방법에는 어떤 것이 있나요",
]

LOG_MARKER = "rag_engine_latency:"

# 구간 이름과 로그 키. prepare_ms 는 앞 다섯 구간의 합이라 중복 집계하지 않습니다.
SEGMENT_KEYS = (
    "plan_ms",
    "sql_ms",
    "vector_ms",
    "kb_ms",
    "assembly_ms",
    "llm_ms",
    "guard_ms",
)
TOTAL_KEY = "total_ms"


class SegmentLoggingDisabledError(RuntimeError):
    """LATENCY_SEGMENT_LOGGING 이 꺼져 있어 구간을 수집할 수 없습니다."""


def docker_since_timestamp(now: datetime | None = None) -> str:
    """`docker logs --since` 에 줄 RFC3339 시각을 만듭니다.

    타임존 표기를 빠뜨리면 docker 가 로컬 시각으로 해석합니다. UTC 값을
    표기 없이 주면 KST 기준으로 9시간 과거가 되어 측정과 무관한 로그가
    집계에 섞입니다. 반드시 Z 를 붙입니다.
    """
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _command_output(command: list[str]) -> str:
    try:
        return subprocess.check_output(  # nosec B603
            command,
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""


def parse_segment_lines(raw_log: str) -> list[dict[str, float | str]]:
    """컨테이너 로그에서 rag_engine_latency 줄을 뽑아 구조로 만듭니다."""
    records: list[dict[str, float | str]] = []
    for line in raw_log.splitlines():
        if LOG_MARKER not in line:
            continue
        payload = line.split(LOG_MARKER, 1)[1]
        record: dict[str, float | str] = {}
        for key, value in re.findall(r"(\w+)=([^\s]+)", payload):
            if key.endswith("_ms"):
                try:
                    record[key] = float(value)
                except ValueError:
                    continue
            else:
                record[key] = value
        if TOTAL_KEY in record:
            records.append(record)
    return records


def container_env_flag(container: str, name: str, command_runner: Any = None) -> str | None:
    """대상 컨테이너의 환경변수 하나를 읽습니다. 없으면 None 입니다."""
    runner = command_runner or _command_output
    raw = runner(["docker", "inspect", "-f", "{{json .Config.Env}}", container])
    if not raw.strip():
        return None
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        return None
    for entry in entries:
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key == name:
            return value
    return None


def assert_segment_logging_enabled(container: str, command_runner: Any = None) -> None:
    """플래그가 꺼진 채 빈 결과를 측정 완료로 착각하는 것을 막습니다."""
    value = container_env_flag(container, "LATENCY_SEGMENT_LOGGING", command_runner)
    if value is None or value.strip().lower() not in {"1", "true", "yes", "on"}:
        raise SegmentLoggingDisabledError(
            f"컨테이너 {container} 의 LATENCY_SEGMENT_LOGGING 이 켜져 있지 않습니다 "
            f"(현재 값: {value!r}). .env 에 LATENCY_SEGMENT_LOGGING=true 를 넣고 "
            "app 을 재기동한 뒤 다시 실행하십시오. 측정 후에는 원래 값으로 되돌리십시오."
        )


def send_query(base_url: str, question: str, timeout_sec: float) -> tuple[float, bool]:
    """단발 질의를 보내고 왕복 시간과 성공 여부를 돌려줍니다."""
    body = json.dumps({"query": question}).encode("utf-8")
    req = urlrequest.Request(  # nosec B310
        f"{base_url}{QUERY_PATH}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as response:  # nosec B310
            response.read()
    except (urlerror.URLError, TimeoutError, OSError):
        return (time.perf_counter() - started) * 1000.0, False
    return (time.perf_counter() - started) * 1000.0, True


def aggregate(records: list[dict[str, float | str]]) -> dict[str, Any]:
    """구간별 분위수와 잔여 구간을 집계합니다."""
    buckets: dict[str, Samples] = {key: Samples(label=key) for key in SEGMENT_KEYS}
    buckets[TOTAL_KEY] = Samples(label=TOTAL_KEY)
    buckets["residual_ms"] = Samples(label="residual_ms")

    for record in records:
        total = float(record.get(TOTAL_KEY, 0.0))
        measured = 0.0
        for key in SEGMENT_KEYS:
            if key in record:
                value = float(record[key])
                buckets[key].add(value)
                measured += value
        buckets[TOTAL_KEY].add(total)
        # 구간 합과 total 의 차이는 계측되지 않은 구간입니다. 버리지 않습니다.
        buckets["residual_ms"].add(total - measured)

    summary: dict[str, Any] = {}
    for name, samples in buckets.items():
        if not samples.values:
            summary[name] = None
            continue
        summary[name] = {
            "n": len(samples.values),
            "p50_ms": samples.percentile(50),
            "p95_ms": samples.percentile(95),
            "p99_ms": samples.percentile(99),
            "min_ms": min(samples.values),
            "max_ms": max(samples.values),
        }
    return summary


def build_environment(container: str, command_runner: Any = None) -> dict[str, Any]:
    runner = command_runner or _command_output
    return {
        "target_container": container,
        "container_id": runner(["docker", "inspect", "-f", "{{.Id}}", container]).strip() or None,
        "image_id": runner(["docker", "inspect", "-f", "{{.Image}}", container]).strip() or None,
        "llm_provider": container_env_flag(container, "LLM_PROVIDER", runner),
        "llm_model": container_env_flag(container, "OLLAMA_MODEL", runner),
        "git_sha": runner(["git", "rev-parse", "HEAD"]).strip() or None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="단발 질의 RAG 구간 분리 계측 하네스")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--target-container", default=DEFAULT_CONTAINER)
    parser.add_argument("--rounds", type=int, default=20, help="보낼 질의 수")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        assert_segment_logging_enabled(args.target_container)
    except SegmentLoggingDisabledError as exc:
        print(f"구간 계측 사전 조건 실패: {exc}")
        return 2

    since = docker_since_timestamp()
    roundtrip = Samples(label="roundtrip_ms")
    failures = 0

    for index in range(args.rounds):
        question = QUERIES[index % len(QUERIES)]
        elapsed_ms, ok = send_query(args.base_url, question, args.timeout_sec)
        if ok:
            roundtrip.add(elapsed_ms, question)
        else:
            failures += 1

    raw_log = _command_output(["docker", "logs", "--since", since, args.target_container])
    records = parse_segment_lines(raw_log)

    if not records:
        print(
            "구간 로그를 한 줄도 찾지 못했습니다. LATENCY_SEGMENT_LOGGING 은 켜져 있으나 "
            "로그가 수집되지 않았습니다. 컨테이너 로그 드라이버와 로그 레벨을 확인하십시오."
        )
        return 2

    summary = aggregate(records)
    summary["roundtrip_ms"] = {
        "n": len(roundtrip.values),
        "p50_ms": roundtrip.percentile(50),
        "p95_ms": roundtrip.percentile(95),
        "p99_ms": roundtrip.percentile(99),
        "min_ms": min(roundtrip.values) if roundtrip.values else None,
        "max_ms": max(roundtrip.values) if roundtrip.values else None,
    }

    payload = {
        "status": "ok" if failures == 0 else "partial",
        "git_sha": build_environment(args.target_container).get("git_sha"),
        "timestamp": datetime.now(UTC).isoformat(),
        "environment": build_environment(args.target_container),
        "config": {
            "base_url": args.base_url,
            "rounds": args.rounds,
            "timeout_sec": args.timeout_sec,
            "queries": QUERIES,
        },
        "summary": summary,
        "errors": failures,
        "segment_records": len(records),
    }

    text = dump_strict_json(sanitize_nan_to_none(payload), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"결과를 {args.output} 에 저장했습니다.")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
