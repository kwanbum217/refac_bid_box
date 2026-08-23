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
import math
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402


class BuildProvenanceError(RuntimeError):
    """벤치마크 대상 도커 이미지/컨테이너 provenance 조회가 실패하거나 불완전할 때 발생합니다."""


PROVENANCE_IDENTITY_KEYS: tuple[str, ...] = (
    "container_id",
    "target_container_image_id",
    "docker_image_id",
    "image_digest",
    "git_sha",
    "container_name",
    "service_name",
    "target_source_mount",
    "target_source_git_sha",
    "target_source_git_dirty",
)


def verify_provenance_consistency(
    start_meta: dict[str, object],
    end_meta: dict[str, object],
    strict: bool = True,
) -> bool:
    """측정 시작과 종료 시점의 provenance identity 일치 여부를 검증합니다.

    측정 도중 대상 컨테이너나 이미지가 교체되었거나 git_sha/소스 dirty 상태가 변경된 경우
    strict 모드에서 BuildProvenanceError를 발생시키고 fail-closed로 거부합니다.
    """
    mismatches: list[str] = []
    for key in PROVENANCE_IDENTITY_KEYS:
        start_val = start_meta.get(key)
        end_val = end_meta.get(key)
        if start_val != end_val:
            mismatches.append(f"{key} changed from '{start_val}' to '{end_val}'")

    if mismatches:
        err_msg = (
            "Target container/image provenance changed during benchmark measurement: "
            + ", ".join(mismatches)
        )
        if strict:
            raise BuildProvenanceError(err_msg)
        return False
    return True


from scripts._strict_json import (  # noqa: E402
    dump_strict_json,
    sanitize_nan_to_none,
)

# 성능에 영향을 주는 런타임 설정 허용 목록.
# 허용 목록 방식으로만 키를 선별하며, 목록에 없는 환경변수는 값도 이름도 기록하지 않는다.
# 비밀값(SECRET_KEY, DB_PASSWORD, MYSQL_ROOT_PASSWORD, MEILI_MASTER_KEY,
# G2B_SERVICE_KEY, serviceKey, GEMINI_API_KEY)은 어떤 경우에도 포함하지 않는다.
# DATABASE_URL, DB_HOST 등 DSN/접속 정보도 성능 설정이 아니므로 제외한다.
PERF_CONFIG_ALLOWLIST: frozenset[str] = frozenset(
    {
        "WEB_CONCURRENCY",
        "PREDICTION_GC_MODE",
        "LATENCY_SEGMENT_LOGGING",
        "LLM_PROVIDER",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_TEMPERATURE",
        "GEMINI_MODEL",
    }
)

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


def _parse_env_vars(raw_env: str) -> dict[str, str]:
    """docker inspect의 .Config.Env 문자열을 딕셔너리로 파싱합니다.

    Env 리스트 형식: ["KEY1=VALUE1", "KEY2=VALUE2", ...]
    """
    env_dict: dict[str, str] = {}
    if not raw_env or raw_env == "unknown":
        return env_dict
    try:
        env_list = json.loads(raw_env)
        if isinstance(env_list, list):
            for item in env_list:
                if isinstance(item, str) and "=" in item:
                    key, _, value = item.partition("=")
                    if key:
                        env_dict[key] = value
    except (ValueError, TypeError):
        pass
    return env_dict


def runtime_config_snapshot(
    container_id: str,
    command_runner: Any = None,
) -> dict[str, str | None]:
    """대상 컨테이너의 성능 관련 런타임 설정만 허용 목록 방식으로 수집합니다.

    같은 이미지와 소스라도 설정이 다르면 다른 벤치마크임을 증거로 드러내기 위해
    기록합니다. 비밀값은 어떤 경우에도 포함하지 않습니다.

    Returns:
        허용 목록에 있는 키와 해당 값의 딕셔너리. 컨테이너를 조회할 수 없으면
        모든 값이 None인 딕셔너리를 반환합니다.
    """
    cmd_fn = command_runner if command_runner is not None else _command_output

    snapshot: dict[str, str | None] = dict.fromkeys(sorted(PERF_CONFIG_ALLOWLIST))

    if container_id == "unknown":
        return snapshot

    raw_env = cmd_fn(["docker", "inspect", "-f", "{{json .Config.Env}}", container_id])
    env_dict = _parse_env_vars(raw_env)

    for key in PERF_CONFIG_ALLOWLIST:
        if key in env_dict:
            snapshot[key] = env_dict[key]

    return snapshot


def _command_output(command: list[str], allow_empty: bool = False) -> str:
    try:
        out = subprocess.check_output(  # nosec B603
            command,
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()
        if not out:
            if allow_empty or (len(command) >= 2 and command[-2:] == ["status", "--porcelain"]):
                return ""
            return "unknown"
        return out
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _parse_source_mount(raw_mounts: str, target_destination: str = "/app/src") -> str | None:
    """docker inspect의 .Mounts JSON 문자열에서 target_destination에 해당하는 host Source 경로를 찾습니다."""
    if not raw_mounts or raw_mounts == "unknown":
        return None
    try:
        mounts_json = json.loads(raw_mounts)
        if isinstance(mounts_json, list):
            target_norm = target_destination.rstrip("/")
            for mount in mounts_json:
                if isinstance(mount, dict):
                    dest = mount.get("Destination")
                    if isinstance(dest, str) and dest.rstrip("/") == target_norm:
                        source = mount.get("Source")
                        if source:
                            return str(source)
    except (ValueError, TypeError):
        pass
    return None


def _parse_port_bindings(raw_ports: str) -> tuple[list[dict[str, object]], set[int], set[int]]:
    """NetworkSettings.Ports JSON 문자열에서 매핑 정보를 파싱합니다."""
    port_bindings: list[dict[str, object]] = []
    published_host_ports: set[int] = set()
    container_internal_ports: set[int] = set()
    if raw_ports and raw_ports != "unknown":
        try:
            ports_json = json.loads(raw_ports)
            if isinstance(ports_json, dict):
                for k, v in ports_json.items():
                    c_port = (
                        int(k.split("/")[0]) if "/" in k and k.split("/")[0].isdigit() else None
                    )
                    if c_port is not None:
                        container_internal_ports.add(c_port)
                    if isinstance(v, list):
                        for binding in v:
                            if isinstance(binding, dict):
                                h_ip = binding.get("HostIp", "")
                                h_port_str = binding.get("HostPort", "")
                                if h_port_str and str(h_port_str).isdigit():
                                    h_port = int(h_port_str)
                                    published_host_ports.add(h_port)
                                    port_bindings.append(
                                        {
                                            "container_port": c_port,
                                            "host_ip": h_ip,
                                            "host_port": h_port,
                                        }
                                    )
        except (ValueError, TypeError):
            pass
    return port_bindings, published_host_ports, container_internal_ports


def reproducibility_metadata(
    service_name: str = "app",
    strict: bool = True,
    base_url: str | None = None,
    target_container: str | None = None,
    command_runner: Any = None,
) -> dict[str, object]:
    """원시 측정치를 다른 실행 환경과 대조하기 위한 공통 메타데이터입니다.

    HTTP base_url과 실제 측정 대상 Docker 컨테이너의 identity/포트 매핑을 fail-closed로 검증합니다.
    """
    import urllib.parse

    cmd_fn = command_runner if command_runner is not None else _command_output
    timer_info = time.get_clock_info("perf_counter")
    git_sha = cmd_fn(["git", "rev-parse", "HEAD"])

    # 1. 컨테이너 ID 및 이미지 식별자 조회
    if target_container:
        container_id = cmd_fn(["docker", "inspect", "-f", "{{.Id}}", target_container])
        if container_id == "unknown":
            container_id = cmd_fn(["docker", "ps", "-q", "-f", f"name={target_container}"])
    else:
        container_id = cmd_fn(["docker", "compose", "ps", "-q", service_name])

    if service_name and not target_container:
        docker_image_id = cmd_fn(["docker", "compose", "images", "-q", service_name])
    elif container_id != "unknown":
        docker_image_id = cmd_fn(["docker", "inspect", "-f", "{{.Config.Image}}", container_id])
    else:
        docker_image_id = "unknown"

    # 2. 실행 중 컨테이너 상세 정보 조회
    if container_id != "unknown":
        target_container_image_id = cmd_fn(["docker", "inspect", "-f", "{{.Image}}", container_id])
        container_name = cmd_fn(["docker", "inspect", "-f", "{{.Name}}", container_id])
        if container_name.startswith("/"):
            container_name = container_name[1:]
        is_running_raw = cmd_fn(["docker", "inspect", "-f", "{{.State.Running}}", container_id])
        raw_ports = cmd_fn(
            ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", container_id]
        )
        raw_ip = cmd_fn(["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", container_id])
        raw_mounts = cmd_fn(["docker", "inspect", "-f", "{{json .Mounts}}", container_id])
    else:
        target_container_image_id = "unknown"
        container_name = "unknown"
        is_running_raw = "unknown"
        raw_ports = "unknown"
        raw_ip = "unknown"
        raw_mounts = "unknown"

    # 3. 이미지 repo digest 조회 (image ID와 구분)
    image_digest = "unknown"
    digest_source_id = (
        target_container_image_id if target_container_image_id != "unknown" else docker_image_id
    )
    if digest_source_id != "unknown":
        raw_digests = cmd_fn(["docker", "inspect", "-f", "{{json .RepoDigests}}", digest_source_id])
        if raw_digests != "unknown":
            try:
                parsed_digests = json.loads(raw_digests)
                if (
                    isinstance(parsed_digests, list)
                    and len(parsed_digests) > 0
                    and parsed_digests[0]
                ):
                    image_digest = str(parsed_digests[0])
                else:
                    image_digest = "none (local build)"
            except (ValueError, TypeError):
                image_digest = "unknown"

    # 4. 소스 bind mount 및 runtime git 상태 조회
    target_source_mount = _parse_source_mount(raw_mounts, "/app/src")
    target_source_git_sha: str | None = None
    target_source_git_dirty: bool | None = None

    if target_source_mount is not None:
        target_source_git_sha = cmd_fn(["git", "-C", target_source_mount, "rev-parse", "HEAD"])
        status_raw = cmd_fn(["git", "-C", target_source_mount, "status", "--porcelain"])
        if status_raw == "unknown":
            target_source_git_dirty = None
        elif status_raw == "":
            target_source_git_dirty = False
        else:
            target_source_git_dirty = True

    # 5. 포트 바인딩 및 base_url 결박 검증
    port_bindings, published_host_ports, container_internal_ports = _parse_port_bindings(raw_ports)
    is_running = is_running_raw.strip().lower() == "true"

    req_port = None
    port_matched = True
    if base_url:
        parsed_url = urllib.parse.urlparse(base_url)
        req_host = parsed_url.hostname or "127.0.0.1"
        req_port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        is_loopback = req_host in (
            "127.0.0.1",
            "localhost",
            "0.0.0.0",  # noqa: S104  # nosec B104 - 허용된 loopback 대체 표기 비교
            "::1",
            "localhost.localdomain",
        )

        if is_loopback:
            port_matched = req_port in published_host_ports
        else:
            if raw_ip and req_host == raw_ip and req_port in container_internal_ports:
                port_matched = True
            else:
                port_matched = False

    # 6. Strict 모드 검증 및 fail-closed 거부
    if strict:
        failures = []
        if git_sha == "unknown":
            failures.append("git_sha(harness)")
        target_label = (
            f"target container '{target_container}'"
            if target_container
            else f"compose service '{service_name}'"
        )
        if docker_image_id == "unknown":
            failures.append(f"docker_image_id({target_label})")
        if container_id == "unknown":
            failures.append(f"container_id({target_label})")
        if target_container_image_id == "unknown":
            failures.append(f"target_container_image_id(container '{container_id}')")
        if container_id != "unknown":
            if not is_running:
                failures.append(
                    f"container '{container_id}' is not running (state: {is_running_raw})"
                )
            if base_url and not port_matched:
                failures.append(
                    f"base_url port {req_port} not bound to target container '{container_id}' "
                    f"(published host ports: {sorted(published_host_ports) if published_host_ports else 'none'})"
                )
            if target_source_mount is not None:
                if target_source_git_sha == "unknown":
                    failures.append(f"target_source_git_sha({target_source_mount})")
                if target_source_git_dirty is None:
                    failures.append(f"target_source_git_dirty_unknown({target_source_mount})")
                elif target_source_git_dirty is True:
                    failures.append(f"target_source_git_dirty({target_source_mount})")
        if failures:
            raise BuildProvenanceError(
                f"Docker/Git provenance lookup failed or returned unknown for: {', '.join(failures)}"
            )

    # 7. 성능 관련 런타임 설정 스냅샷 (허용 목록 방식)
    perf_config = runtime_config_snapshot(container_id, command_runner=cmd_fn)

    return {
        "git_sha": git_sha,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "docker_image_id": docker_image_id,
        "container_id": container_id,
        "target_container_image_id": target_container_image_id,
        "image_digest": image_digest,
        "container_name": container_name,
        "service_name": service_name,
        "base_url": base_url,
        "bound_port": req_port,
        "port_bindings": port_bindings,
        "target_source_mount": target_source_mount,
        "target_source_git_sha": target_source_git_sha,
        "target_source_git_dirty": target_source_git_dirty,
        "perf_config": perf_config,
        "gc": {"enabled": gc.isenabled(), "threshold": list(gc.get_threshold())},
        "instrumentation": {
            "timer": "time.perf_counter",
            "timer_resolution_seconds": timer_info.resolution,
            "timer_monotonic": timer_info.monotonic,
        },
    }


def single_host_load_sample() -> dict[str, object]:
    """단일 호스트 부하 스냅샷을 측정합니다."""
    cpu_count = os.cpu_count()
    load_1m = None
    if hasattr(os, "getloadavg"):
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


def compute_host_load_stats(samples: list[dict[str, object]]) -> dict[str, object]:
    """호스트 부하 표본 리스트로부터 min/median/max 통계를 계산합니다."""
    load_values = [float(s["load_1m"]) for s in samples if s.get("load_1m") is not None]
    pct_values = [
        float(s["per_core_percent"]) for s in samples if s.get("per_core_percent") is not None
    ]

    if load_values:
        load_stats = {
            "min": min(load_values),
            "median": statistics.median(load_values),
            "max": max(load_values),
        }
    else:
        load_stats = {"min": None, "median": None, "max": None}

    if pct_values:
        pct_stats = {
            "min": min(pct_values),
            "median": statistics.median(pct_values),
            "max": max(pct_values),
        }
    else:
        pct_stats = {"min": None, "median": None, "max": None}

    cpu_count = samples[0].get("cpu_count") if samples else os.cpu_count()

    return {
        "cpu_count": cpu_count,
        "samples": samples,
        "load_1m": load_stats,
        "per_core_percent": pct_stats,
    }


def collect_host_load_samples(
    count: int = 3,
    interval_seconds: float = 5.0,
) -> list[dict[str, object]]:
    """지정된 간격으로 호스트 부하 표본을 수집합니다."""
    samples: list[dict[str, object]] = []
    for i in range(count):
        samples.append(single_host_load_sample())
        if i < count - 1 and interval_seconds > 0:
            time.sleep(interval_seconds)
    return samples


def host_load_metadata(
    samples: list[dict[str, object]] | None = None,
    min_samples: int = 3,
    interval_seconds: float = 5.0,
) -> dict[str, object]:
    """호스트 부하 표본과 통계(min, median, max)를 보존합니다."""
    if samples is None:
        samples = collect_host_load_samples(count=min_samples, interval_seconds=interval_seconds)
    return compute_host_load_stats(samples)


class HostLoadMonitor:
    """벤치마크 실행 동안 5초 간격으로 호스트 부하를 수집하는 백그라운드 모니터입니다."""

    def __init__(self, interval_seconds: float = 5.0, min_samples: int = 3) -> None:
        self.interval_seconds = interval_seconds
        self.min_samples = min_samples
        self.samples: list[dict[str, object]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        self.samples.append(single_host_load_sample())

    def _run(self) -> None:
        self._sample()
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def start(self) -> "HostLoadMonitor":
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, object]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        while len(self.samples) < self.min_samples:
            if self.interval_seconds > 0:
                time.sleep(self.interval_seconds)
            self._sample()
        return self.summary()

    def summary(self) -> dict[str, object]:
        return compute_host_load_stats(self.samples)


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
        p50 = self.percentile(50)
        p95 = self.percentile(95)
        p99 = self.percentile(99)
        return {
            "label": self.label,
            "values_ms": self.values,
            "errors": self.errors,
            "p50_ms": None if math.isnan(p50) else p50,
            "p95_ms": None if math.isnan(p95) else p95,
            "p99_ms": None if math.isnan(p99) else p99,
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
    host_load: dict[str, object] | None = None,
    strict_provenance: bool = True,
    service_name: str = "app",
    target_container: str | None = None,
    meta: dict[str, object] | None = None,
    start_meta: dict[str, object] | None = None,
    end_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    if start_meta is None and end_meta is None:
        if meta is None:
            meta = reproducibility_metadata(
                service_name=service_name,
                strict=strict_provenance,
                base_url=base_url,
                target_container=target_container,
            )
        start_meta = meta
        end_meta = meta
    elif start_meta is not None and end_meta is None:
        end_meta = start_meta
    elif start_meta is None and end_meta is not None:
        start_meta = end_meta

    provenance_consistent = verify_provenance_consistency(
        start_meta, end_meta, strict=strict_provenance
    )

    base_meta = dict(start_meta)
    if meta is not None:
        base_meta.update(meta)

    evidence_meta = {
        **base_meta,
        "start_provenance": start_meta,
        "end_provenance": end_meta,
        "provenance_consistent": provenance_consistent,
        "host_load": host_load if host_load is not None else host_load_metadata(),
    }

    evidence = {
        "meta": evidence_meta,
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
    return sanitize_nan_to_none(evidence)


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
    parser.add_argument(
        "--target-service", default="app", help="대상 도커 컴포즈 서비스명 (기본: app)"
    )
    parser.add_argument(
        "--target-container",
        default=None,
        help="명시적 대상 도커 컨테이너 이름 또는 ID (기본: None)",
    )
    parser.add_argument("--sse-rounds", type=int, default=20)
    parser.add_argument("--query-rounds", type=int, default=10)
    parser.add_argument("--predict-rounds", type=int, default=100)
    parser.add_argument("--predict-concurrency", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-unknown-provenance",
        action="store_true",
        default=False,
        help="Docker provenance 조회 실패 시에도 측정을 강제 진행합니다 (기본: 거부)",
    )
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

    load_monitor = HostLoadMonitor(interval_seconds=5.0, min_samples=3).start()

    print(f"\n[1/3] 낙찰가 예측 API ({args.predict_rounds}회)")
    predict = benchmark_predict(args.base_url, args.predict_rounds, args.predict_concurrency)

    print(f"\n[2/3] 정본 SSE 스트리밍 ({args.sse_rounds}회)")
    first_stage, new_first_token, final = benchmark_sse_canonical(args.base_url, args.sse_rounds)

    print(f"\n[3/3] 단발 질의 API ({args.query_rounds}회)")
    query = benchmark_query(args.base_url, args.query_rounds)

    host_load = load_monitor.stop()

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
            host_load=host_load,
            strict_provenance=strict_provenance,
            service_name=args.target_service,
            target_container=args.target_container,
            start_meta=start_meta,
            end_meta=end_meta,
        )
        args.output.write_text(
            dump_strict_json(evidence),
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
