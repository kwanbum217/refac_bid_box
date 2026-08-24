"""단발 질의 API 의 RAG 구간별 소요를 분리 수집하는 벤치마크 하네스.

`src/rag/engine.py` 는 `LATENCY_SEGMENT_LOGGING` 이 켜져 있을 때 요청마다
`rag_engine_latency: trace_id=... plan_ms=... llm_ms=... total_ms=...` 형태의
구조화 로그를 남깁니다.

본 하네스는:
1. 공통 provenance(scripts/benchmark_provenance.py)와 결박하여 base_url 포트 바인딩,
   컨테이너 identity, 이미지 식별자, 런타임 소스 dirty/start-end 일치성, 성능 관련 설정을 fail-closed로 검증합니다.
2. --expected-llm-model 인자를 필수로 요구하며 런타임 OLLAMA_MODEL과 다르면 측정 전 exit 2로 즉시 중단합니다.
3. 각 HTTP 요청 응답의 X-RAG-Trace-Id 헤더와 서버 로그의 trace_id를 1:1로 엄밀히 대조합니다.
4. 성공 요청 수, 고유 trace 수, 세그먼트 로그 레코드 수가 정확히 일치하지 않거나 중복/외부 trace가 있으면
   evidence를 canonical baseline으로 인정하지 않고 비정상 종료(non-zero)합니다.
5. HTTP 부분 실패 시 exit 1로 종료하며 status="partial" 및 canonical_success=false를 명시합니다.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._strict_json import dump_strict_json, sanitize_nan_to_none  # noqa: E402
from scripts.benchmark_latency import Samples  # noqa: E402
from scripts.benchmark_provenance import (  # noqa: E402
    BuildProvenanceError,
    HostLoadMonitor,
    reproducibility_metadata,
    verify_provenance_consistency,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CONTAINER = "refac_bid_box-app-1"
DEFAULT_SERVICE = "app"
QUERY_PATH = "/api/v1/chatbot/query"
TRACE_HEADER_NAME = "X-RAG-Trace-Id"

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


class ModelMismatchError(RuntimeError):
    """기대 LLM 모델과 런타임 모델이 일치하지 않거나 설정되지 않았습니다."""


class TraceCorrelationError(RuntimeError):
    """요청 응답 trace와 서버 로그 trace 간 1:1 정합성 검증이 실패했습니다."""


def docker_since_timestamp(now: datetime | None = None) -> str:
    """`docker logs --since` 에 줄 RFC3339 시각을 만듭니다.

    타임존 표기를 빠뜨리면 docker 가 로컬 시각으로 해석합니다. UTC 값을
    표기 없이 주면 KST 기준으로 9시간 과거가 되어 측정과 무관한 로그가
    집계에 섞입니다. 반드시 Z 를 붙입니다.
    """
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _command_output(
    command: list[str],
    allow_empty: bool = False,
    cwd: Path | None = None,
) -> str:
    target_cwd = cwd if cwd is not None else PROJECT_ROOT
    try:
        out = subprocess.check_output(  # nosec B603
            command,
            cwd=target_cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not out:
            if allow_empty or (len(command) >= 2 and command[-2:] == ["status", "--porcelain"]):
                return ""
            return "unknown"
        return out
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def parse_segment_lines(raw_log: str) -> list[dict[str, float | str]]:
    """컨테이너 로그에서 rag_engine_latency 줄을 뽑아 구조로 만듭니다."""
    records: list[dict[str, float | str]] = []
    if not raw_log or raw_log == "unknown":
        return records
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
    if not raw.strip() or raw == "unknown":
        return None
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry:
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


def assert_expected_model_matches(
    container: str,
    expected_model: str | None,
    start_meta: dict[str, Any] | None = None,
    command_runner: Any = None,
) -> str:
    """기대 LLM 모델이 지정되었는지, 런타임 OLLAMA_MODEL과 일치하는지 fail-closed로 검증합니다."""
    if not expected_model or not str(expected_model).strip():
        raise ModelMismatchError(
            "기대 LLM 모델(--expected-llm-model)이 지정되지 않았습니다. "
            "벤치마크 재현성을 위해 기대 모델을 반드시 명시해야 합니다 (예: --expected-llm-model gemma4:e4b)."
        )
    expected_norm = str(expected_model).strip()

    runtime_model: str | None = None
    if start_meta and isinstance(start_meta.get("perf_config"), dict):
        runtime_model = start_meta["perf_config"].get("OLLAMA_MODEL")

    if not runtime_model:
        runtime_model = container_env_flag(container, "OLLAMA_MODEL", command_runner)

    if not runtime_model:
        raise ModelMismatchError(
            f"컨테이너 '{container}'에서 OLLAMA_MODEL 환경변수를 찾을 수 없습니다."
        )

    runtime_norm = runtime_model.strip()
    if expected_norm != runtime_norm:
        raise ModelMismatchError(
            f"기대 LLM 모델 '{expected_norm}'과 컨테이너 런타임 OLLAMA_MODEL '{runtime_norm}'이 일치하지 않습니다."
        )
    return runtime_norm


def send_query(base_url: str, question: str, timeout_sec: float) -> tuple[float, bool, str | None]:
    """단발 질의를 보내고 왕복 시간, 성공 여부, 응답 헤더의 trace_id를 돌려줍니다."""
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
            headers = response.headers
            trace_id = headers.get("X-RAG-Trace-Id") or headers.get("x-rag-trace-id")
            response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not trace_id or not str(trace_id).strip():
                return elapsed_ms, False, None
            return elapsed_ms, True, str(trace_id).strip()
    except (urlerror.URLError, TimeoutError, OSError):
        return (time.perf_counter() - started) * 1000.0, False, None


def verify_trace_correlation(
    successful_traces: list[str],
    log_records: list[dict[str, float | str]],
    expected_rounds: int,
) -> tuple[bool, str, dict[str, Any]]:
    """성공 요청의 trace_id 집합과 서버 로그의 trace_id 집합을 1:1로 엄밀히 대조합니다.

    검증 조건:
    1. 성공 요청 수 == expected_rounds
    2. 응답 trace_id 고유 수 == 성공 요청 수 (중복 없음)
    3. 세그먼트 로그 레코드 수 == expected_rounds
    4. 모든 로그 레코드에 유효한 trace_id 포함
    5. 로그 trace_id 고유 수 == 레코드 수 (중복 없음)
    6. 응답 trace_id 집합 == 로그 trace_id 집합 (누락/외부 trace 없음)
    """
    log_traces = [str(r["trace_id"]).strip() for r in log_records if "trace_id" in r]
    unique_resp = set(successful_traces)
    unique_logs = set(log_traces)

    dup_resp = len(successful_traces) - len(unique_resp)
    dup_logs = len(log_traces) - len(unique_logs)
    unmatched_logs = sorted(unique_logs - unique_resp)
    missing_logs = sorted(unique_resp - unique_logs)

    details = {
        "expected_rounds": expected_rounds,
        "successful_traces_count": len(successful_traces),
        "unique_successful_traces_count": len(unique_resp),
        "segment_records_count": len(log_records),
        "unique_log_traces_count": len(unique_logs),
        "matched_count": len(unique_resp & unique_logs),
        "duplicate_response_traces": dup_resp,
        "duplicate_log_traces": dup_logs,
        "unmatched_log_traces": unmatched_logs,
        "missing_log_traces": missing_logs,
    }

    if len(successful_traces) != expected_rounds:
        return (
            False,
            f"성공 요청 수({len(successful_traces)})가 기대 라운드({expected_rounds})와 일치하지 않습니다.",
            details,
        )

    if dup_resp > 0:
        return False, f"응답 헤더에 중복 trace_id가 {dup_resp}건 있습니다.", details

    if len(log_records) != expected_rounds:
        return (
            False,
            f"세그먼트 로그 레코드 수({len(log_records)})가 기대 라운드({expected_rounds})와 일치하지 않습니다.",
            details,
        )

    if len(log_traces) != len(log_records):
        return False, "trace_id가 없는 세그먼트 로그 레코드가 존재합니다.", details

    if dup_logs > 0:
        return False, f"로그에 중복 trace_id가 {dup_logs}건 있습니다.", details

    if unmatched_logs:
        return (
            False,
            f"측정 대상이 아닌 외부 로그 trace가 {len(unmatched_logs)}건 발견되었습니다.",
            details,
        )

    if missing_logs:
        return (
            False,
            f"성공 요청 중 로그에 누락된 trace가 {len(missing_logs)}건 있습니다.",
            details,
        )

    return True, "1:1 trace 상관 및 무결성 검증 통과", details


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
    raw_cid = runner(["docker", "inspect", "-f", "{{.Id}}", container])
    raw_img = runner(["docker", "inspect", "-f", "{{.Image}}", container])
    raw_sha = runner(["git", "rev-parse", "HEAD"])
    return {
        "target_container": container,
        "container_id": raw_cid if raw_cid != "unknown" else None,
        "image_id": raw_img if raw_img != "unknown" else None,
        "llm_provider": container_env_flag(container, "LLM_PROVIDER", runner),
        "llm_model": container_env_flag(container, "OLLAMA_MODEL", runner),
        "git_sha": raw_sha if raw_sha != "unknown" else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="단발 질의 RAG 구간 분리 계측 하네스")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--target-container", default=DEFAULT_CONTAINER)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE)
    parser.add_argument("--rounds", type=int, default=20, help="보낼 질의 수")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument(
        "--expected-llm-model",
        type=str,
        default=None,
        help="기대 LLM 모델명 (런타임 OLLAMA_MODEL과 1:1 대조 필수, 예: gemma4:e4b)",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", default=True)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    command_runner: Any = None,
    query_sender: Any = None,
    host_load_sampler: Any = None,
) -> int:
    args = parse_args(argv)
    cmd_fn = command_runner or _command_output
    query_fn = query_sender or send_query

    # 1. LATENCY_SEGMENT_LOGGING 켜짐 여부 사전 검증
    try:
        assert_segment_logging_enabled(args.target_container, command_runner=cmd_fn)
    except SegmentLoggingDisabledError as exc:
        print(f"구간 계측 사전 조건 실패: {exc}")
        return 2

    # 2. 공통 provenance 시작 메타데이터 수집 (포트 바인딩, dirty git, 이미지 identity 결박)
    try:
        start_meta = reproducibility_metadata(
            service_name=args.service_name,
            strict=args.strict,
            base_url=args.base_url,
            target_container=args.target_container,
            command_runner=cmd_fn,
        )
    except BuildProvenanceError as exc:
        print(f"시작 시점 provenance 무결성 검증 실패: {exc}")
        return 2

    # 3. 기대 LLM 모델 vs 런타임 OLLAMA_MODEL 검증 (미지정 또는 불일치 시 exit 2)
    try:
        runtime_model = assert_expected_model_matches(
            container=args.target_container,
            expected_model=args.expected_llm_model,
            start_meta=start_meta,
            command_runner=cmd_fn,
        )
    except ModelMismatchError as exc:
        print(f"LLM 모델 검증 실패: {exc}")
        return 2

    # 4. 호스트 부하 모니터 기동 및 시작 시각 기록
    load_monitor = HostLoadMonitor(
        interval_seconds=5.0,
        min_samples=1,
        sampler=host_load_sampler,
    ).start()

    since = docker_since_timestamp()
    roundtrip = Samples(label="roundtrip_ms")
    successful_traces: list[str] = []
    failures = 0

    # 5. 질의 전송 루프
    for index in range(args.rounds):
        question = QUERIES[index % len(QUERIES)]
        elapsed_ms, ok, trace_id = query_fn(args.base_url, question, args.timeout_sec)
        if ok and trace_id:
            roundtrip.add(elapsed_ms, question)
            successful_traces.append(trace_id)
        else:
            failures += 1

    # 6. 호스트 부하 모니터 정지
    host_load_stats = load_monitor.stop()

    # 7. 컨테이너 로그 수집 및 파싱
    raw_log = cmd_fn(["docker", "logs", "--since", since, args.target_container])
    records = parse_segment_lines(raw_log)

    # 8. 공통 provenance 종료 메타데이터 수집 및 일관성 검증 (컨테이너 교체 등 감지)
    try:
        end_meta = reproducibility_metadata(
            service_name=args.service_name,
            strict=args.strict,
            base_url=args.base_url,
            target_container=args.target_container,
            command_runner=cmd_fn,
        )
        verify_provenance_consistency(start_meta, end_meta, strict=args.strict)
    except BuildProvenanceError as exc:
        print(f"종료 시점 provenance 일관성 검증 실패: {exc}")
        return 2

    # 9. 1:1 Trace 상관 및 무결성 검증
    trace_ok, trace_reason, trace_details = verify_trace_correlation(
        successful_traces=successful_traces,
        log_records=records,
        expected_rounds=args.rounds,
    )

    # 10. Status, Canonical Success 및 종료 코드 판정
    if failures == 0 and trace_ok:
        status = "ok"
        canonical_success = True
        exit_code = 0
        canonical_rationale = (
            "모든 요청 성공 및 1:1 trace 상관 검증 통과 (canonical baseline 자격 충족)"
        )
    else:
        canonical_success = False
        exit_code = 1
        if failures > 0:
            status = "partial"
            canonical_rationale = (
                f"부분 HTTP 실패({failures}/{args.rounds}): canonical baseline 자격 미충족"
            )
        else:
            status = "integrity_error"
            canonical_rationale = (
                f"트레이스 정합성 검증 실패({trace_reason}): canonical baseline 자격 미충족"
            )

    summary = aggregate(records)
    summary["roundtrip_ms"] = {
        "n": len(roundtrip.values),
        "p50_ms": roundtrip.percentile(50) if roundtrip.values else None,
        "p95_ms": roundtrip.percentile(95) if roundtrip.values else None,
        "p99_ms": roundtrip.percentile(99) if roundtrip.values else None,
        "min_ms": min(roundtrip.values) if roundtrip.values else None,
        "max_ms": max(roundtrip.values) if roundtrip.values else None,
    }

    payload = {
        "status": status,
        "canonical_success": canonical_success,
        "canonical_rationale": canonical_rationale,
        "expected_llm_model": args.expected_llm_model,
        "git_sha": start_meta.get("git_sha"),
        "timestamp": datetime.now(UTC).isoformat(),
        "environment": {
            "target_container": args.target_container,
            "container_id": start_meta.get("container_id"),
            "image_id": start_meta.get("target_container_image_id"),
            "llm_provider": (start_meta.get("perf_config") or {}).get("LLM_PROVIDER"),
            "llm_model": runtime_model,
            "git_sha": start_meta.get("git_sha"),
        },
        "provenance": {
            "start": start_meta,
            "end": end_meta,
            "host_load": host_load_stats,
        },
        "config": {
            "base_url": args.base_url,
            "rounds": args.rounds,
            "timeout_sec": args.timeout_sec,
            "expected_llm_model": args.expected_llm_model,
            "queries": QUERIES,
        },
        "summary": summary,
        "errors": failures,
        "successful_traces_count": len(successful_traces),
        "unique_successful_traces_count": len(set(successful_traces)),
        "segment_records_count": len(records),
        "trace_correlation": trace_details,
    }

    text = dump_strict_json(sanitize_nan_to_none(payload), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"결과를 {args.output} 에 저장했습니다.")
    else:
        print(text)

    if exit_code != 0:
        print(f"벤치마크 비정상 종료 (exit {exit_code}): {canonical_rationale}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
