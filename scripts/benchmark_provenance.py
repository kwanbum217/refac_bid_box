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

import contextlib
import gc
import json
import math
import os
import platform
import shlex
import statistics
import subprocess  # nosec B404
import sys
import threading
import time
import urllib.parse
from collections.abc import Mapping, Sequence
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


# 측정 산출물은 실행되는 코드가 아니므로 dirty 판정에서 제외합니다.
# 제외하지 않으면 회차별 raw 를 저장하는 반복 측정이 자기 산출물 때문에
# 다음 회차에서 fail-closed 로 거부되어 --repetitions 가 완주할 수 없습니다.
MEASUREMENT_ARTIFACT_PREFIXES: tuple[str, ...] = ("data/benchmarks/",)

# 주변 부하 규약 (docs/ops/latency_gate_protocol.md 5.3): 코어당 사용률 중앙값 30% 이하, 최대 50% 이하
LOAD_PROTOCOL_MEDIAN_LIMIT_PERCENT = 30.0
LOAD_PROTOCOL_MAX_LIMIT_PERCENT = 50.0

# 설계서 6장 반복 안정성 임계값 (docs/analysis/arq_calibration_design_20260824.md 6.3/6.4)
CALIBRATION_CV_MAX = 0.05
CALIBRATION_MAD_MEDIAN_MAX = 0.03
CALIBRATION_REGRESSION_FLOOR = 0.06

# provenance 4계층 중 strict 모드에서 "unknown" 을 허용하지 않는 필수 필드 목록.
# 목록 밖의 선택 필드(예: docker.worker_container_id, docker.worker_image 등)는
# 하네스가 해당 항목을 쓰지 않는 경우 None 을 기록하므로 unknown 을 허용합니다.
PROVENANCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "host.python_version",
    "host.platform",
    "host.cpu_count",
    "redis.redis_url",
    "redis.container_id",
    "redis.container_name",
    "redis.image",
    "redis.image_id",
    "redis.server_version",
    "redis.server_mode",
    "arq.arq_version",
    "arq.redis_py_version",
    "arq.benchmark_worker_mode",
    "arq.worker_settings_module",
    "arq.worker_functions",
    "arq.is_synthetic",
    "arq.worker_max_jobs",
    "arq.worker_poll_delay",
    "arq.worker_job_timeout",
    "docker.docker_version",
)


def is_source_dirty(status_porcelain: str) -> bool:
    """`git status --porcelain` 출력에서 실행 코드 기준 dirty 여부를 판정합니다.

    추적되지 않는 측정 산출물만 제외합니다. 추적 파일의 변경과 측정 산출물 밖의
    미추적 파일은 그대로 dirty 로 봅니다. 미추적 `.py` 가 import 될 수 있으므로
    미추적 전체를 무시해서는 안 됩니다.
    """
    for line in status_porcelain.splitlines():
        entry = line.strip()
        if not entry:
            continue
        code, _, path = entry.partition(" ")
        path = path.strip().strip('"')
        if code == "??" and path.startswith(MEASUREMENT_ARTIFACT_PREFIXES):
            continue
        return True
    return False


def get_git_status(path: Path | str | None = None) -> tuple[str, bool | None]:
    """지정된 디렉터리의 Git SHA 및 dirty 상태를 반환합니다.

    Returns:
        tuple[git_sha, is_dirty]
        - git_sha: 커밋 SHA 또는 "unknown"
        - is_dirty: True (dirty), False (clean), None (unknown/Git 오류)
    """
    target_path = Path(path).resolve() if path is not None else PROJECT_ROOT
    try:
        sha = subprocess.check_output(  # nosec B603 B607
            ["git", "-C", str(target_path), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"

    try:
        status = subprocess.check_output(  # nosec B603 B607
            ["git", "-C", str(target_path), "status", "--porcelain"],
            text=True,
        ).strip()
        is_dirty = is_source_dirty(status)
    except (OSError, subprocess.CalledProcessError):
        is_dirty = None

    return sha, is_dirty


def get_host_memory() -> dict[str, int | None]:
    """호스트 물리 메모리 크기(total, available)를 바이트 단위로 안전하게 수집합니다."""
    total_bytes: int | None = None
    available_bytes: int | None = None

    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(pages, int)
                and isinstance(page_size, int)
                and pages > 0
                and page_size > 0
            ):
                total_bytes = pages * page_size
        except (ValueError, OSError):
            pass
        try:
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(avail_pages, int)
                and isinstance(page_size, int)
                and avail_pages > 0
                and page_size > 0
            ):
                available_bytes = avail_pages * page_size
        except (ValueError, OSError):
            pass

    if total_bytes is None and Path("/proc/meminfo").exists():
        with contextlib.suppress(Exception):
            meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    total_bytes = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    available_bytes = int(line.split()[1]) * 1024

    if total_bytes is None and platform.system() == "Darwin":
        with contextlib.suppress(Exception):
            out = subprocess.check_output(  # nosec B603 B607
                ["sysctl", "-n", "hw.memsize"],
                text=True,
            ).strip()
            total_bytes = int(out)

    return {
        "total_bytes": total_bytes,
        "available_bytes": available_bytes,
    }


def build_provenance_dict(
    *,
    host_cpu_count: int,
    host_load_avg_1m: float | None,
    host_memory: dict[str, int | None],
    redis_url: str,
    redis_container_id: str,
    redis_container_name: str,
    redis_image: str,
    redis_image_id: str,
    redis_server_version: str,
    redis_server_mode: str,
    arq_version: str,
    redis_py_version: str,
    benchmark_worker_mode: str,
    worker_settings_module: str,
    worker_functions: list[str],
    is_synthetic: bool,
    worker_max_jobs: int,
    worker_poll_delay: float,
    worker_job_timeout: int,
    docker_version: str,
    worker_container_id: str | None,
    worker_container_name: str | None,
    worker_image: str | None,
    worker_image_id: str | None,
    source_mount: str | None,
    source_git_sha: str | None,
    source_git_dirty: bool | None,
    network: str | None = None,
) -> dict[str, Any]:
    """공통 4계층 Provenance 딕셔너리 구조를 생성합니다."""
    return {
        "host": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": host_cpu_count,
            "load_avg_1m": host_load_avg_1m,
            "memory_total_bytes": host_memory.get("total_bytes"),
            "memory_available_bytes": host_memory.get("available_bytes"),
        },
        "redis": {
            "redis_url": redis_url,
            "container_id": redis_container_id,
            "container_name": redis_container_name,
            "image": redis_image,
            "image_id": redis_image_id,
            "server_version": redis_server_version,
            "server_mode": redis_server_mode,
        },
        "arq": {
            "arq_version": arq_version,
            "redis_py_version": redis_py_version,
            "benchmark_worker_mode": benchmark_worker_mode,
            "worker_settings_module": worker_settings_module,
            "worker_functions": list(worker_functions),
            "is_synthetic": is_synthetic,
            "worker_max_jobs": worker_max_jobs,
            "worker_poll_delay": worker_poll_delay,
            "worker_job_timeout": worker_job_timeout,
        },
        "docker": {
            "docker_version": docker_version,
            "network": network,
            "worker_container_id": worker_container_id,
            "worker_container_name": worker_container_name,
            "worker_image": worker_image,
            "worker_image_id": worker_image_id,
            "source_mount": source_mount,
            "source_git_sha": source_git_sha,
            "source_git_dirty": source_git_dirty,
        },
    }


def _detect_container_network(
    nets_raw: str,
    network_default: str,
    strict: bool,
    container: str,
) -> str:
    """NetworkSettings.Networks JSON 문자열에서 컨테이너 네트워크를 감지합니다.

    strict 모드에서 감지 실패(출력 부재/파싱 불가/빈 네트워크)는 하드코딩
    기본값으로 조용히 넘어가지 않고 BuildProvenanceError 로 중단합니다.
    비-strict 모드(우회)에서만 network_default 로 폴백합니다.
    """
    if nets_raw in ("", "unknown"):
        if strict:
            raise BuildProvenanceError(
                f"Redis container '{container}' network detection failed "
                "(NetworkSettings.Networks unavailable). Specify --network explicitly."
            )
        return network_default
    try:
        nets = json.loads(nets_raw)
    except (ValueError, TypeError):
        if strict:
            raise BuildProvenanceError(
                f"Redis container '{container}' network detection failed to parse "
                "NetworkSettings.Networks. Specify --network explicitly."
            ) from None
        return network_default
    if not isinstance(nets, dict) or not nets:
        if strict:
            raise BuildProvenanceError(
                f"Redis container '{container}' network detection returned no networks. "
                "Specify --network explicitly."
            )
        return network_default
    return str(next(iter(nets.keys())))


def resolve_redis_container(
    redis_url: str,
    target: str | None = None,
    strict: bool = True,
    command_runner: Any = None,
    network_default: str = "arq-docker-measure_default",
) -> dict[str, Any]:
    """대상 Redis 컨테이너 identity 를 명시 지정 또는 fail-closed 자동 결박으로 식별합니다.

    - target(컨테이너 이름/ID 또는 docker compose 서비스명)이 주어지면 그대로 사용합니다.
    - target 이 없으면 `docker ps --filter name=redis` 로 후보를 수집합니다.
      후보가 정확히 1개일 때만 채택하며, 0개 또는 2개 이상이면 자동 선택하지 않고
      BuildProvenanceError 로 중단합니다 (fail-closed).
    - strict 모드에서는 redis_url 의 호스트/포트가 선택된 컨테이너의 발행 포트와
      대응하는지 검증하고, 대응을 확인할 수 없으면 BuildProvenanceError 로 중단합니다.
    - 조회 예외는 unknown 으로 흡수하지 않고 BuildProvenanceError 로 중단합니다.
    """
    cmd_fn = command_runner if command_runner is not None else _command_output

    def require(raw: str, what: str) -> str:
        if raw in ("", "unknown"):
            raise BuildProvenanceError(
                f"Redis container '{what}' lookup failed (command returned unknown/empty)"
            )
        return raw

    def inspect_container(cid: str) -> dict[str, Any]:
        raw_image_id = require(cmd_fn(["docker", "inspect", "-f", "{{.Image}}", cid]), "image_id")
        raw_name = require(cmd_fn(["docker", "inspect", "-f", "{{.Name}}", cid]), "name")
        name = raw_name[1:] if raw_name.startswith("/") else raw_name
        raw_ports = cmd_fn(["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", cid])
        nets_raw = cmd_fn(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", cid])
        network = _detect_container_network(
            nets_raw,
            network_default=network_default,
            strict=strict,
            container=cid,
        )
        return {
            "container_id": cid,
            "container_name": name,
            "image": require(
                cmd_fn(["docker", "inspect", "-f", "{{.Config.Image}}", cid]), "image"
            ),
            "image_id": raw_image_id,
            "network": network,
            "published_host_ports": _parse_published_host_ports(raw_ports),
        }

    resolved_target: str | None = None
    if target:
        compose_id = cmd_fn(["docker", "compose", "ps", "-q", target])
        resolved_target = compose_id if compose_id not in ("", "unknown") else target
    else:
        ps_raw = cmd_fn(
            [
                "docker",
                "ps",
                "--filter",
                "name=redis",
                "--format",
                "{{.ID}}\t{{.Names}}",
            ]
        )
        lines = [ln for ln in ps_raw.splitlines() if ln.strip()]
        if len(lines) != 1:
            raise BuildProvenanceError(
                f"Redis container auto-selection requires exactly 1 candidate "
                f"(name=redis), found {len(lines)}. Specify --redis-container explicitly."
            )
        resolved_target = lines[0].split("\t")[0].strip()

    info = inspect_container(resolved_target)

    if strict and redis_url:
        parsed = urllib.parse.urlparse(redis_url)
        req_host = parsed.hostname or "127.0.0.1"
        req_port = parsed.port or (6379)
        is_loopback = req_host in (
            "127.0.0.1",
            "localhost",
            "0.0.0.0",  # noqa: S104  # nosec B104 - 허용된 loopback 대체 표기 비교
            "::1",
            "localhost.localdomain",
        )
        matched = req_port in info["published_host_ports"] if is_loopback else False
        if not matched:
            raise BuildProvenanceError(
                f"Redis container '{info['container_name']}' does not correspond to "
                f"redis_url host {req_host}:{req_port} (published host ports: "
                f"{sorted(info['published_host_ports'])})."
            )

    info.pop("published_host_ports", None)
    return info


def _parse_published_host_ports(raw_ports: str) -> set[int]:
    """NetworkSettings.Ports JSON 문자열에서 발행된 호스트 포트 집합을 파싱합니다."""
    host_ports: set[int] = set()
    if raw_ports and raw_ports != "unknown":
        try:
            ports_json = json.loads(raw_ports)
            if isinstance(ports_json, dict):
                for _k, v in ports_json.items():
                    if isinstance(v, list):
                        for binding in v:
                            if isinstance(binding, dict):
                                h_port_str = binding.get("HostPort", "")
                                if h_port_str and str(h_port_str).isdigit():
                                    host_ports.add(int(h_port_str))
        except (ValueError, TypeError):
            pass
    return host_ports


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
        target_source_git_dirty = None if status_raw == "unknown" else is_source_dirty(status_raw)

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
    load_values: list[float] = []
    for sample in samples:
        load_1m = sample.get("load_1m")
        if isinstance(load_1m, (int, float)):
            load_values.append(float(load_1m))
    pct_values: list[float] = []
    for sample in samples:
        per_core_percent = sample.get("per_core_percent")
        if isinstance(per_core_percent, (int, float)):
            pct_values.append(float(per_core_percent))

    if load_values:
        load_stats: dict[str, float | None] = {
            "min": min(load_values),
            "median": statistics.median(load_values),
            "max": max(load_values),
        }
    else:
        load_stats = {"min": None, "median": None, "max": None}

    if pct_values:
        pct_stats: dict[str, float | None] = {
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


def check_ambient_load_protocol(load_stats: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """주변 부하 규약 준수 여부를 판정합니다.

    load_stats 는 compute_host_load_stats() 산출물로, per_core_percent 의
    median/max 가 코어당 사용률(%)입니다. 규약 임계(중앙값 30%, 최대 50%)를
    초과하면 (False, detail) 를 반환합니다. 부하 표본이 없으면 False 를 반환합니다.

    Returns:
        tuple[compliant, detail] - detail 에는 median_percent, max_percent,
        median_limit_percent, max_limit_percent 가 포함됩니다.
    """
    pct = load_stats.get("per_core_percent") or {}
    median_pct = pct.get("median")
    max_pct = pct.get("max")
    detail: dict[str, Any] = {
        "median_percent": median_pct,
        "max_percent": max_pct,
        "median_limit_percent": LOAD_PROTOCOL_MEDIAN_LIMIT_PERCENT,
        "max_limit_percent": LOAD_PROTOCOL_MAX_LIMIT_PERCENT,
    }
    if median_pct is None or max_pct is None:
        detail["reason"] = "load_stats_unavailable"
        return False, detail
    compliant = (
        float(median_pct) <= LOAD_PROTOCOL_MEDIAN_LIMIT_PERCENT
        and float(max_pct) <= LOAD_PROTOCOL_MAX_LIMIT_PERCENT
    )
    return compliant, detail


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


def compute_baseline_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """반복 측정 결과에 설계서 6장 중앙값 기준선 산식을 자동 적용합니다.

    median(T), median(P), CV(T), CV(P), MAD/median, rt, rp 를 계산하고 반복
    안정성 판정(CV <= 0.05, MAD/median <= 0.03)을 함께 기록합니다. 위반 시
    기준선을 신뢰할 수 없다는 판정을 명시합니다.

    입력 회차의 load_protocol.canonical_evidence 가 False 인 회차는 규약 위반
    측정이므로 raw 는 보존하되 기준선 도출에서 제외되어야 합니다. non-canonical
    회차가 하나라도 있으면 baseline_trustworthy 를 False 로 내리고 verdict 에
    CV/MAD 판정과 구분되는 사유를 기록합니다.
    """
    t_values: list[float] = []
    p_values: list[float] = []
    failure_max = 0.0
    non_canonical_runs: list[dict[str, Any]] = []
    for idx, r in enumerate(results, start=1):
        summary = r.get("summary") or {}
        latency = r.get("latency_ms") or {}
        t = summary.get("jobs_per_second")
        p = latency.get("p95_ms")
        if isinstance(t, (int, float)) and math.isfinite(float(t)):
            t_values.append(float(t))
        if isinstance(p, (int, float)) and math.isfinite(float(p)):
            p_values.append(float(p))
        total = summary.get("total_enqueued")
        failed = summary.get("failed_jobs") or 0
        errors = summary.get("error_count") or 0
        if isinstance(total, (int, float)) and float(total) > 0:
            failure_max = max(failure_max, (failed + errors) / float(total))
        else:
            failure_max = 1.0

        load_protocol = r.get("load_protocol")
        if isinstance(load_protocol, Mapping) and load_protocol.get("canonical_evidence") is False:
            ident: dict[str, Any] = {"run_index": idx}
            if "git_sha" in r:
                ident["git_sha"] = r["git_sha"]
            if "timestamp" in r:
                ident["timestamp"] = r["timestamp"]
            non_canonical_runs.append(ident)

    def _median(values: list[float]) -> float | None:
        return statistics.median(values) if values else None

    def _cv(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        mean = statistics.fmean(values)
        if mean == 0:
            return None
        return statistics.stdev(values) / mean

    def _mad_median_ratio(values: list[float]) -> float | None:
        med = _median(values)
        if med is None or med == 0:
            return None
        deviations = [abs(v - med) for v in values]
        mad = _median(deviations)
        if mad is None:
            return None
        return mad / med

    t_median = _median(t_values)
    p_median = _median(p_values)
    t_cv = _cv(t_values)
    p_cv = _cv(p_values)
    t_mad_ratio = _mad_median_ratio(t_values)
    p_mad_ratio = _mad_median_ratio(p_values)

    rt = max(3.0 * t_cv, CALIBRATION_REGRESSION_FLOOR) if t_cv is not None else None
    rp = max(3.0 * p_cv, CALIBRATION_REGRESSION_FLOOR) if p_cv is not None else None

    cv_ok = (
        t_cv is not None
        and p_cv is not None
        and t_cv <= CALIBRATION_CV_MAX
        and p_cv <= CALIBRATION_CV_MAX
    )
    mad_ok = (
        t_mad_ratio is not None
        and p_mad_ratio is not None
        and t_mad_ratio <= CALIBRATION_MAD_MEDIAN_MAX
        and p_mad_ratio <= CALIBRATION_MAD_MEDIAN_MAX
    )
    stable = cv_ok and mad_ok
    has_non_canonical = bool(non_canonical_runs)
    trustworthy = stable and not has_non_canonical

    if has_non_canonical:
        verdict = "unstable_non_canonical_runs_present"
    elif stable:
        verdict = "stable"
    else:
        verdict = "unstable_baseline_not_trustworthy"

    return {
        "n_runs": len(results),
        "throughput_baseline": t_median,
        "p95_baseline": p_median,
        "throughput": {
            "median": t_median,
            "cv": t_cv,
            "mad_median_ratio": t_mad_ratio,
        },
        "p95_ms": {
            "median": p_median,
            "cv": p_cv,
            "mad_median_ratio": p_mad_ratio,
        },
        "failure": {"max": failure_max},
        "non_canonical_runs": non_canonical_runs,
        "regression_gate": {
            "rt": rt,
            "rp": rp,
            "floor": CALIBRATION_REGRESSION_FLOOR,
        },
        "stability": {
            "cv_ok": cv_ok,
            "mad_ratio_ok": mad_ok,
            "passed": stable,
            "baseline_trustworthy": trustworthy,
            "verdict": verdict,
            "thresholds": {
                "cv_max": CALIBRATION_CV_MAX,
                "mad_median_max": CALIBRATION_MAD_MEDIAN_MAX,
            },
        },
    }


def provenance_unknown_required_fields(provenance: Mapping[str, Any]) -> list[str]:
    """필수 provenance 필드 중 unknown 이거나 누락된 dot-path 목록을 반환합니다."""
    bad: list[str] = []
    for path in PROVENANCE_REQUIRED_FIELDS:
        node: Any = provenance
        resolved = True
        for key in path.split("."):
            if not isinstance(node, Mapping) or key not in node:
                resolved = False
                break
            node = node[key]
        if not resolved or node == "unknown":
            bad.append(path)
    return bad


def enforce_provenance_required_fields(provenance: Mapping[str, Any], strict: bool = True) -> None:
    """strict 모드에서 필수 provenance 필드의 unknown 을 BuildProvenanceError 로 기각합니다."""
    if not strict:
        return
    bad = provenance_unknown_required_fields(provenance)
    if bad:
        raise BuildProvenanceError(
            "Required provenance field(s) are unknown or missing: " + ", ".join(bad)
        )


def build_load_protocol_record(
    start_compliant: bool,
    start_detail: Mapping[str, Any],
    end_compliant: bool,
    end_detail: Mapping[str, Any],
    strict: bool,
    allow_violation: bool,
) -> dict[str, Any]:
    """주변 부하 규약 적용 상태와 판정을 결과 JSON 에 기록할 구조체를 만듭니다.

    우회(allow_violation) 또는 strict 미적용 시 canonical_evidence 는 False 로
    기록되어 정본 evidence 가 아님을 명시합니다.
    """
    enforced = strict and not allow_violation
    compliant = start_compliant and end_compliant
    return {
        "enforced": enforced,
        "bypassed": bool(allow_violation),
        "compliant": compliant,
        "canonical_evidence": enforced and compliant,
        "start": dict(start_detail),
        "end": dict(end_detail),
    }


def frozen_baseline_path(
    mode: str,
    git_sha: str,
    root: Path | str | None = None,
    timestamp: datetime | None = None,
) -> Path:
    """frozen baseline 저장 경로 규약(설계서 5.1)을 구성합니다.

    경로 형태: <root>/arq/<mode>/<git_sha_short>/<YYYYMMDD_HHMMSS>_arq_<mode>_baseline.json
    - root 기본값: PROJECT_ROOT/data/benchmarks/frozen
    - mode: 'inprocess' 또는 'container'
    - git_sha_short: git_sha 의 앞 7자
    중간 디렉터리는 이 함수가 만들지 않지만, 하네스는 저장 시
    mkdir(parents=True) 로 자동 생성하므로 운영자가 사전 mkdir 할 필요가 없습니다.
    """
    root_path = Path(root) if root is not None else PROJECT_ROOT / "data" / "benchmarks" / "frozen"
    sha_short = (git_sha or "unknown")[:7]
    ts = timestamp if timestamp is not None else datetime.now(UTC)
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    filename = f"{ts_str}_arq_{mode}_baseline.json"
    return root_path / "arq" / mode / sha_short / filename


def verify_network_record(
    used_network: str | None,
    provenance_network: str | None,
    strict: bool = True,
) -> bool:
    """측정에 실제로 쓰인 네트워크와 provenance 기록의 일치를 검증합니다.

    worker 컨테이너를 띄운 네트워크(used_network)와 provenance 의
    docker.network 가 다르면 strict 모드에서 BuildProvenanceError 로 중단합니다.
    """
    if used_network != provenance_network:
        if strict:
            raise BuildProvenanceError(
                f"Network provenance mismatch: used '{used_network}' but "
                f"provenance records '{provenance_network}'"
            )
        return False
    return True
