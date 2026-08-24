"""
scripts/benchmark_provenance.py

벤치마크 하네스 공통 provenance 및 재현성 검증 계층.

주요 기능:
1. Docker 컨테이너 identity, 이미지 식별자, RepoDigest 및 포트 바인딩 결박 검증 (fail-closed)
2. 런타임 소스 bind mount 및 git revision/dirty 상태 검증
3. 측정 시작(start)과 종료(end) 간 identity 일치성 검증 (verify_provenance_consistency)
4. 성능 영향 런타임 설정 허용 목록(PERF_CONFIG_ALLOWLIST) 기반 안전 수집 (비밀값 유출 방지)
5. Docker Config.Cmd 기반 effective_web_workers 정수 파싱 및 사유 기록
6. 크로스플랫폼 안전 호스트 부하 계측 (Windows os.getloadavg 미지원 대응)
"""

from __future__ import annotations

import gc
import json
import os
import platform
import shlex
import statistics
import subprocess  # nosec B404
import sys
import threading
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


def _command_output(
    command: list[str],
    allow_empty: bool = False,
    cwd: Path | None = None,
) -> str:
    """하위 프로세스 명령을 실행하고 출력 문자열을 반환합니다.

    명령 실패나 실행 불가 시 "unknown"을 반환합니다.
    """
    target_cwd = cwd if cwd is not None else PROJECT_ROOT
    try:
        out = subprocess.check_output(  # nosec B603
            command,
            cwd=target_cwd,
            text=True,
        ).strip()
        if not out:
            if allow_empty or (len(command) >= 2 and command[-2:] == ["status", "--porcelain"]):
                return ""
            return "unknown"
        return out
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


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


def _parse_container_command(raw_cmd: str) -> list[str] | str | None:
    """docker inspect의 .Config.Cmd 또는 Entrypoint 문자열/JSON을 파싱합니다."""
    if not raw_cmd or raw_cmd in ("unknown", "null", "[]"):
        return None
    try:
        parsed = json.loads(raw_cmd)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        if isinstance(parsed, str):
            return parsed
    except (ValueError, TypeError):
        pass
    stripped = raw_cmd.strip()
    return stripped if stripped else None


def _parse_effective_workers(cmd: list[str] | str | None) -> tuple[int | None, str | None]:
    """커맨드 라인에서 --workers / -w 플래그를 탐색해 실효 Uvicorn 워커 정수와 판정 사유를 반환합니다.

    Returns:
        tuple[effective_web_workers, reason]
        - 정상 파싱 시: (정수, None)
        - 파싱 불가/누락 시: (None, 사유 문자열)
    """
    if cmd is None:
        return None, "container_command_unavailable"

    tokens: list[str] = []
    if isinstance(cmd, list):
        tokens = cmd
    elif isinstance(cmd, str):
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            return None, "command_parse_error"

    for i, token in enumerate(tokens):
        if token in ("--workers", "-w"):
            if i + 1 < len(tokens):
                candidate = tokens[i + 1]
                try:
                    return int(candidate), None
                except ValueError:
                    return None, f"invalid_workers_value: '{candidate}'"
            return None, "missing_workers_argument"
        if token.startswith(("--workers=", "-w=")):
            _, _, candidate = token.partition("=")
            if not candidate:
                return None, "missing_workers_argument"
            try:
                return int(candidate), None
            except ValueError:
                return None, f"invalid_workers_value: '{candidate}'"

    return None, "workers_flag_not_found"


def runtime_config_snapshot(
    container_id: str,
    command_runner: Any = None,
) -> dict[str, Any]:
    """대상 컨테이너의 성능 관련 런타임 설정 및 실행 커맨드/실효 워커 수를 수집합니다.

    허용 목록(PERF_CONFIG_ALLOWLIST) 환경변수와 Config.Cmd 기반 effective_web_workers만
    기록합니다. 비밀값(SECRET_KEY, DB_PASSWORD 등)은 어떤 경우에도 포함하지 않습니다.

    Returns:
        PERF_CONFIG_ALLOWLIST 키와 container_command, effective_web_workers,
        effective_web_workers_reason이 포함된 딕셔너리.
    """
    cmd_fn = command_runner if command_runner is not None else _command_output

    snapshot: dict[str, Any] = dict.fromkeys(sorted(PERF_CONFIG_ALLOWLIST))
    snapshot["container_command"] = None
    snapshot["effective_web_workers"] = None
    snapshot["effective_web_workers_reason"] = None

    if container_id == "unknown":
        snapshot["effective_web_workers_reason"] = "container_unknown"
        return snapshot

    raw_env = cmd_fn(["docker", "inspect", "-f", "{{json .Config.Env}}", container_id])
    env_dict = _parse_env_vars(raw_env)

    for key in PERF_CONFIG_ALLOWLIST:
        if key in env_dict:
            snapshot[key] = env_dict[key]

    raw_cmd = cmd_fn(["docker", "inspect", "-f", "{{json .Config.Cmd}}", container_id])
    parsed_cmd = _parse_container_command(raw_cmd)
    workers, workers_reason = _parse_effective_workers(parsed_cmd)

    snapshot["container_command"] = parsed_cmd
    snapshot["effective_web_workers"] = workers
    snapshot["effective_web_workers_reason"] = workers_reason

    return snapshot


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

    # 7. 성능 관련 런타임 설정 스냅샷 (허용 목록 방식 + effective workers)
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


def single_host_load_sample(os_module: Any = None) -> dict[str, object]:
    """단일 호스트 부하 스냅샷을 측정합니다.

    os.getloadavg가 없는 플랫폼(Windows 등)에서는 안전하게 None을 기록합니다.
    """
    target_os = os_module if os_module is not None else os
    cpu_count = target_os.cpu_count() if hasattr(target_os, "cpu_count") else None
    load_1m: float | None = None
    getloadavg_fn = getattr(target_os, "getloadavg", None)
    if getloadavg_fn is not None:
        try:
            load_1m, _, _ = getloadavg_fn()
        except OSError:
            load_1m = None

    per_core_percent: float | None = None
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
    sampler: Any = None,
) -> list[dict[str, object]]:
    """지정된 간격으로 호스트 부하 표본을 수집합니다."""
    sample_fn = sampler if sampler is not None else single_host_load_sample
    samples: list[dict[str, object]] = []
    for i in range(count):
        samples.append(sample_fn())
        if i < count - 1 and interval_seconds > 0:
            time.sleep(interval_seconds)
    return samples


def host_load_metadata(
    samples: list[dict[str, object]] | None = None,
    min_samples: int = 3,
    interval_seconds: float = 5.0,
    sampler: Any = None,
) -> dict[str, object]:
    """호스트 부하 표본과 통계(min, median, max)를 보존합니다."""
    if samples is None:
        samples = collect_host_load_samples(
            count=min_samples,
            interval_seconds=interval_seconds,
            sampler=sampler,
        )
    return compute_host_load_stats(samples)


class HostLoadMonitor:
    """벤치마크 실행 동안 지정된 간격으로 호스트 부하를 수집하는 백그라운드 모니터입니다."""

    def __init__(
        self,
        interval_seconds: float = 5.0,
        min_samples: int = 3,
        sampler: Any = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.min_samples = min_samples
        self.sampler = sampler if sampler is not None else single_host_load_sample
        self.samples: list[dict[str, object]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        self.samples.append(self.sampler())

    def _run(self) -> None:
        self._sample()
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def start(self) -> HostLoadMonitor:
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
