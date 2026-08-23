from scripts import benchmark_latency
from scripts.benchmark_latency import (
    PERF_CONFIG_ALLOWLIST,
    HostLoadMonitor,
    Samples,
    _query_for_round,
    benchmark_predict,
    build_evidence,
    compute_host_load_stats,
    host_load_metadata,
    single_host_load_sample,
)


def test_latency_target_fails_when_any_request_errors():
    samples = Samples("test", values=[10.0, 12.0], errors=1)

    assert samples.report(target_ms=100.0) is False


def test_benchmark_queries_are_unique_across_repeated_base_queries():
    queries = [_query_for_round(index) for index in range(20)]

    assert len(set(queries)) == 20


def test_latency_evidence_contains_raw_values_and_percentiles():
    samples = Samples("test", values=[10.0, 20.0, 30.0])

    evidence = samples.as_dict()

    assert evidence["values_ms"] == [10.0, 20.0, 30.0]
    assert evidence["p95_ms"] == 29.0


def test_reproducibility_metadata_marks_failed_docker_lookup_unknown(monkeypatch):
    def fail_docker(command: list[str]) -> str:
        return "unknown" if command[0] == "docker" else "abc123"

    monkeypatch.setattr(benchmark_latency, "_command_output", fail_docker)

    metadata = benchmark_latency.reproducibility_metadata(strict=False)

    assert metadata["git_sha"] == "abc123"
    assert metadata["docker_image_id"] == "unknown"
    assert metadata["container_id"] == "unknown"
    assert metadata["target_container_image_id"] == "unknown"
    assert metadata["image_digest"] == "unknown"
    assert metadata["container_name"] == "unknown"
    assert set(metadata) == {
        "git_sha",
        "measured_at_utc",
        "python_version",
        "platform",
        "docker_image_id",
        "container_id",
        "target_container_image_id",
        "image_digest",
        "container_name",
        "service_name",
        "base_url",
        "bound_port",
        "port_bindings",
        "target_source_mount",
        "target_source_git_sha",
        "target_source_git_dirty",
        "perf_config",
        "gc",
        "instrumentation",
    }


def test_single_host_load_sample_marks_unavailable_load(monkeypatch):
    monkeypatch.setattr(benchmark_latency.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(benchmark_latency.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError))

    sample = single_host_load_sample()

    assert sample["cpu_count"] == 8
    assert sample["load_1m"] is None
    assert sample["per_core_percent"] is None
    assert "observed_at_utc" in sample


def test_single_host_load_sample_handles_missing_getloadavg(monkeypatch):
    monkeypatch.setattr(benchmark_latency.os, "cpu_count", lambda: 4)
    if hasattr(benchmark_latency.os, "getloadavg"):
        monkeypatch.delattr(benchmark_latency.os, "getloadavg")

    sample = single_host_load_sample()

    assert sample["cpu_count"] == 4
    assert sample["load_1m"] is None
    assert sample["per_core_percent"] is None


def test_compute_host_load_stats_calculates_min_median_max():
    samples = [
        {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 8, "per_core_percent": 12.5},
        {"observed_at_utc": "t2", "load_1m": 3.0, "cpu_count": 8, "per_core_percent": 37.5},
        {"observed_at_utc": "t3", "load_1m": 2.0, "cpu_count": 8, "per_core_percent": 25.0},
    ]

    stats = compute_host_load_stats(samples)

    assert stats["cpu_count"] == 8
    assert stats["samples"] == samples
    assert stats["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
    assert stats["per_core_percent"] == {"min": 12.5, "median": 25.0, "max": 37.5}


def test_compute_host_load_stats_handles_unsupported_platform():
    samples = [
        {"observed_at_utc": "t1", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
        {"observed_at_utc": "t2", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
        {"observed_at_utc": "t3", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
    ]

    stats = compute_host_load_stats(samples)

    assert stats["cpu_count"] == 8
    assert stats["samples"] == samples
    assert stats["load_1m"] == {"min": None, "median": None, "max": None}
    assert stats["per_core_percent"] == {"min": None, "median": None, "max": None}


def test_host_load_metadata_collects_samples_without_wait(monkeypatch):
    calls = 0

    def mock_sample():
        nonlocal calls
        calls += 1
        return {
            "observed_at_utc": f"t{calls}",
            "load_1m": float(calls),
            "cpu_count": 4,
            "per_core_percent": float(calls) * 25.0,
        }

    monkeypatch.setattr(benchmark_latency, "single_host_load_sample", mock_sample)

    metadata = host_load_metadata(min_samples=3, interval_seconds=0.0)

    assert calls == 3
    assert len(metadata["samples"]) == 3
    assert metadata["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
    assert metadata["per_core_percent"] == {"min": 25.0, "median": 50.0, "max": 75.0}


def test_host_load_monitor_guarantees_minimum_samples():
    monitor = HostLoadMonitor(interval_seconds=0.001, min_samples=3)
    monitor.start()
    summary = monitor.stop()

    assert len(summary["samples"]) >= 3
    assert "min" in summary["load_1m"]
    assert "median" in summary["load_1m"]
    assert "max" in summary["load_1m"]
    assert "min" in summary["per_core_percent"]
    assert "median" in summary["per_core_percent"]
    assert "max" in summary["per_core_percent"]


def test_predict_warmup_matches_concurrency_and_is_excluded(monkeypatch):
    calls: list[int] = []

    class Response:
        status_code = 200

    def post(_url: str, *, json: dict[str, int | str], timeout: float) -> Response:
        calls.append(json["presumed_price"])
        return Response()

    monkeypatch.setattr(benchmark_latency.httpx, "post", post)

    samples = benchmark_predict("http://test", rounds=3, concurrency=2)

    assert len(calls) == 5
    assert len(samples.values) == 3
    assert sorted(calls[:2]) == [499_999_998, 499_999_999]


def test_evidence_records_predict_execution_and_host_load(monkeypatch):
    monkeypatch.setattr(
        benchmark_latency, "reproducibility_metadata", lambda **kwargs: {"git_sha": "abc"}
    )
    mock_host_load = {
        "cpu_count": 8,
        "samples": [
            {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 8, "per_core_percent": 12.5},
            {"observed_at_utc": "t2", "load_1m": 2.0, "cpu_count": 8, "per_core_percent": 25.0},
            {"observed_at_utc": "t3", "load_1m": 1.5, "cpu_count": 8, "per_core_percent": 18.75},
        ],
        "load_1m": {"min": 1.0, "median": 1.5, "max": 2.0},
        "per_core_percent": {"min": 12.5, "median": 18.75, "max": 25.0},
    }
    sample = Samples("test", values=[1.0])

    evidence = build_evidence(
        "http://test",
        600,
        10,
        sample,
        sample,
        sample,
        sample,
        sample,
        host_load=mock_host_load,
    )

    assert evidence["predict_rounds"] == 600
    assert evidence["predict_concurrency"] == 10
    assert evidence["predict_warmup_requests"] == 10
    assert evidence["meta"]["git_sha"] == "abc"
    assert evidence["meta"]["host_load"] == mock_host_load


def test_reproducibility_metadata_marks_empty_docker_lookup_unknown(monkeypatch):
    monkeypatch.setattr(
        benchmark_latency.subprocess, "check_output", lambda _command, **_kwargs: ""
    )

    assert (
        benchmark_latency._command_output(["docker", "compose", "images", "-q", "app"]) == "unknown"
    )


def test_reproducibility_metadata_queries_app_service_and_inspect(monkeypatch):
    commands_executed: list[list[str]] = []

    def mock_command_output(command: list[str]) -> str:
        commands_executed.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return "harness_git_sha_123"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:app_image_aaa"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "container_id_bbb"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "container_id_bbb"]:
            return "sha256:target_container_image_ccc"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "container_id_bbb"]:
            return "/refac_bid_box-app-1"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "container_id_bbb"]:
            return "true"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Ports}}",
            "container_id_bbb",
        ]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{.NetworkSettings.IPAddress}}",
            "container_id_bbb",
        ]:
            return "172.18.0.4"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .RepoDigests}}",
            "sha256:target_container_image_ccc",
        ]:
            return '["refac_bid_box-app@sha256:digest123"]'
        return "unexpected"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command_output)

    metadata = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    assert metadata["git_sha"] == "harness_git_sha_123"
    assert metadata["docker_image_id"] == "sha256:app_image_aaa"
    assert metadata["container_id"] == "container_id_bbb"
    assert metadata["target_container_image_id"] == "sha256:target_container_image_ccc"
    assert metadata["image_digest"] == "refac_bid_box-app@sha256:digest123"
    assert metadata["container_name"] == "refac_bid_box-app-1"
    assert metadata["bound_port"] == 8000

    # compose service 이름 'app' 조회와 inspect 호출을 검증합니다.
    assert ["docker", "compose", "images", "-q", "app"] in commands_executed
    assert ["docker", "compose", "ps", "-q", "app"] in commands_executed
    assert [
        "docker",
        "inspect",
        "-f",
        "{{.Image}}",
        "container_id_bbb",
    ] in commands_executed


def test_reproducibility_metadata_raises_build_provenance_error_on_unknown(monkeypatch):
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    # 1. docker_image_id 가 unknown 인 경우
    def mock_fail_image(command: list[str]) -> str:
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "unknown"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_123"]:
            return "sha256:img_123"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_123"]:
            return "true"
        return "git_sha_123"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_fail_image)
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(strict=True)
    assert "docker_image_id" in str(excinfo.value)

    # 2. container_id 가 unknown 인 경우
    def mock_fail_container(command: list[str]) -> str:
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "unknown"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img_123"
        return "git_sha_123"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_fail_container)
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(strict=True)
    assert "container_id" in str(excinfo.value)

    # 3. target_container_image_id 가 unknown 인 경우
    def mock_fail_inspect(command: list[str]) -> str:
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_123"]:
            return "unknown"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_123"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img_123"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_123"]:
            return "true"
        return "git_sha_123"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_fail_inspect)
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(strict=True)
    assert "target_container_image_id" in str(excinfo.value)

    # 4. strict=False 일 때는 예외 없이 unknown 을 반환함을 확인
    non_strict_meta = benchmark_latency.reproducibility_metadata(strict=False)
    assert non_strict_meta["target_container_image_id"] == "unknown"


def test_reproducibility_metadata_detects_port_mismatch(monkeypatch):
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha123"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img123"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt123"]:
            return "sha256:img123"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt123"]:
            return "/app-cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt123"]:
            return "172.18.0.2"
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    # base_url이 9000 포트인데 컨테이너는 8000 포트만 발행한 경우 -> strict 모드에서 실패
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:9000",
        )
    assert "port 9000 not bound" in str(excinfo.value)

    # non-strict 모드에서는 예외 없이 반환
    meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=False,
        base_url="http://127.0.0.1:9000",
    )
    assert meta["bound_port"] == 9000

    # 로컬 Docker provenance만으로 원격 HTTP 대상의 동일성을 증명할 수 없습니다.
    with pytest.raises(BuildProvenanceError, match="port 8000 not bound"):
        benchmark_latency.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://remote-host:8000",
        )


def test_reproducibility_metadata_detects_stopped_container(monkeypatch):
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha123"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img123"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt123"]:
            return "sha256:img123"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt123"]:
            return "/app-cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt123"]:
            return "false"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:8000",
        )
    assert "is not running" in str(excinfo.value)


def test_reproducibility_metadata_supports_explicit_target_container(monkeypatch):
    commands_executed: list[list[str]] = []

    def mock_command(command: list[str]) -> str:
        commands_executed.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha123"
        if command == ["docker", "inspect", "-f", "{{.Id}}", "my_custom_container"]:
            return "custom_cnt_id_999"
        if command == ["docker", "inspect", "-f", "{{.Config.Image}}", "custom_cnt_id_999"]:
            return "custom_image:latest"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "custom_cnt_id_999"]:
            return "sha256:custom_image_hash"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "custom_cnt_id_999"]:
            return "/my_custom_container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "custom_cnt_id_999"]:
            return "true"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Ports}}",
            "custom_cnt_id_999",
        ]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{.NetworkSettings.IPAddress}}",
            "custom_cnt_id_999",
        ]:
            return "172.18.0.9"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .RepoDigests}}",
            "sha256:custom_image_hash",
        ]:
            return "[]"
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    meta = benchmark_latency.reproducibility_metadata(
        target_container="my_custom_container",
        strict=True,
        base_url="http://localhost:8000",
    )

    assert meta["container_id"] == "custom_cnt_id_999"
    assert meta["docker_image_id"] == "custom_image:latest"
    assert meta["target_container_image_id"] == "sha256:custom_image_hash"
    assert meta["image_digest"] == "none (local build)"
    assert meta["container_name"] == "my_custom_container"


def test_strict_json_serialization_sanitizes_nan_to_null():
    import json

    import pytest

    from scripts.benchmark_latency import dump_strict_json, sanitize_nan_to_none

    # 1. Samples 가 비어 있을 때 percentiles 가 None 으로 정규화되는지 확인
    empty_samples = Samples("empty")
    sample_dict = empty_samples.as_dict()
    assert sample_dict["p50_ms"] is None
    assert sample_dict["p95_ms"] is None
    assert sample_dict["p99_ms"] is None

    # 2. sanitize_nan_to_none 이 중첩 구조에서 NaN/Inf 를 None 으로 변환하는지 확인
    raw_data = {
        "nan_val": float("nan"),
        "inf_val": float("inf"),
        "nested_list": [1.0, float("nan"), {"inner": float("nan")}],
        "valid_val": 42.5,
    }
    sanitized = sanitize_nan_to_none(raw_data)
    assert sanitized["nan_val"] is None
    assert sanitized["inf_val"] is None
    assert sanitized["nested_list"] == [1.0, None, {"inner": None}]
    assert sanitized["valid_val"] == 42.5

    # 3. raw_data 에 대해 기본 json.dumps(allow_nan=False) 는 ValueError 를 발생시킴
    with pytest.raises(ValueError):
        json.dumps(raw_data, allow_nan=False)

    # 4. dump_strict_json 은 예외 없이 RFC-8259 준수 strict JSON 문자열을 생성함
    json_str = dump_strict_json(raw_data)
    assert "NaN" not in json_str
    assert "null" in json_str

    # 5. 파싱 결과가 None(null)으로 복원되는지 확인
    parsed = json.loads(json_str)
    assert parsed["nan_val"] is None
    assert parsed["inf_val"] is None
    assert parsed["nested_list"] == [1.0, None, {"inner": None}]


def test_build_evidence_strict_provenance_and_nan_normalization(monkeypatch):
    import json

    from scripts.benchmark_latency import dump_strict_json

    monkeypatch.setattr(
        benchmark_latency,
        "reproducibility_metadata",
        lambda **kwargs: {
            "git_sha": "git123",
            "docker_image_id": "img123",
            "container_id": "cnt123",
            "target_container_image_id": "timg123",
        },
    )

    empty_stage = Samples("empty_stage")
    empty_token = Samples("empty_token")
    empty_final = Samples("empty_final")
    empty_predict = Samples("empty_predict")
    empty_query = Samples("empty_query")

    evidence = build_evidence(
        "http://test",
        100,
        10,
        empty_stage,
        empty_token,
        empty_final,
        empty_predict,
        empty_query,
        host_load={"cpu_count": 4, "load_1m": {"min": None, "median": None, "max": None}},
        strict_provenance=True,
    )

    # NaN 이 없어야 하고 strict dump 가 성공해야 함
    serialized = dump_strict_json(evidence)
    assert "NaN" not in serialized
    parsed = json.loads(serialized)
    assert parsed["samples"]["predict"]["p95_ms"] is None


def test_reproducibility_metadata_direct_container_ip_binding(monkeypatch):
    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha123"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img123"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt123"]:
            return "sha256:img123"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt123"]:
            return "/app-cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt123"]:
            return '{"8000/tcp":null}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt123"]:
            return "172.18.0.2"
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    # 직접 컨테이너 IP로 연결할 때 IP와 내부 포트 일치 검증
    meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://172.18.0.2:8000",
    )
    assert meta["bound_port"] == 8000
    assert meta["container_id"] == "cnt123"


def test_reproducibility_metadata_key_separation(monkeypatch):
    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "compose_img_id_111"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "compose_cnt_id_222"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "compose_cnt_id_222"]:
            return "running_img_id_333"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "compose_cnt_id_222"]:
            return "/refac_app_1"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "compose_cnt_id_222"]:
            return "true"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Ports}}",
            "compose_cnt_id_222",
        ]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{.NetworkSettings.IPAddress}}",
            "compose_cnt_id_222",
        ]:
            return "172.18.0.5"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "running_img_id_333"]:
            return '["registry.example.com/app@sha256:repodigest444"]'
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    # 4가지 식별자 키가 혼동되지 않고 명확히 분리되었는지 검증
    assert meta["git_sha"] == "git_sha_abc"
    assert meta["docker_image_id"] == "compose_img_id_111"
    assert meta["container_id"] == "compose_cnt_id_222"
    assert meta["target_container_image_id"] == "running_img_id_333"
    assert meta["image_digest"] == "registry.example.com/app@sha256:repodigest444"
    assert meta["container_name"] == "refac_app_1"


def test_benchmark_latency_main_provenance_failure_returns_code_2(monkeypatch):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_latency.httpx, "get", lambda *a, **kw: MockHealthResponse())
    monkeypatch.setattr(benchmark_latency, "_command_output", lambda _cmd: "unknown")
    monkeypatch.setattr(
        benchmark_latency.sys,
        "argv",
        ["benchmark_latency.py", "--base-url", "http://127.0.0.1:8000"],
    )

    exit_code = benchmark_latency.main()
    assert exit_code == 2


def test_verify_provenance_consistency_success():
    start_meta = {
        "container_id": "cnt_123",
        "target_container_image_id": "img_123",
        "docker_image_id": "img_123",
        "image_digest": "none (local build)",
        "git_sha": "git_123",
        "container_name": "app-1",
        "service_name": "app",
    }
    end_meta = dict(start_meta)

    assert (
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta, strict=True) is True
    )
    assert (
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta, strict=False) is True
    )


def test_verify_provenance_consistency_detects_container_id_swap():
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    start_meta = {
        "container_id": "cnt_123",
        "target_container_image_id": "img_123",
        "docker_image_id": "img_123",
        "image_digest": "none (local build)",
        "git_sha": "git_123",
        "container_name": "app-1",
        "service_name": "app",
    }
    end_meta = dict(start_meta)
    end_meta["container_id"] = "cnt_swapped_456"

    # strict=True: BuildProvenanceError 발생
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta, strict=True)
    assert "container_id changed from 'cnt_123' to 'cnt_swapped_456'" in str(excinfo.value)

    # strict=False: False 반환
    assert (
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta, strict=False) is False
    )


def test_verify_provenance_consistency_detects_image_swap():
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    start_meta = {
        "container_id": "cnt_123",
        "target_container_image_id": "img_123",
        "docker_image_id": "img_123",
        "image_digest": "sha256:digest_aaa",
        "git_sha": "git_123",
        "container_name": "app-1",
        "service_name": "app",
    }

    # 1. target_container_image_id 변경
    end_meta_target_img = dict(start_meta)
    end_meta_target_img["target_container_image_id"] = "img_new_456"
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.verify_provenance_consistency(
            start_meta, end_meta_target_img, strict=True
        )
    assert "target_container_image_id changed" in str(excinfo.value)

    # 2. docker_image_id 변경
    end_meta_docker_img = dict(start_meta)
    end_meta_docker_img["docker_image_id"] = "img_docker_789"
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.verify_provenance_consistency(
            start_meta, end_meta_docker_img, strict=True
        )
    assert "docker_image_id changed" in str(excinfo.value)

    # 3. image_digest 변경
    end_meta_digest = dict(start_meta)
    end_meta_digest["image_digest"] = "sha256:digest_bbb"
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta_digest, strict=True)
    assert "image_digest changed" in str(excinfo.value)


def test_verify_provenance_consistency_detects_git_sha_change():
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    start_meta = {
        "container_id": "cnt_123",
        "target_container_image_id": "img_123",
        "docker_image_id": "img_123",
        "image_digest": "none (local build)",
        "git_sha": "git_123",
        "container_name": "app-1",
        "service_name": "app",
    }
    end_meta = dict(start_meta)
    end_meta["git_sha"] = "git_swapped_999"

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.verify_provenance_consistency(start_meta, end_meta, strict=True)
    assert "git_sha changed from 'git_123' to 'git_swapped_999'" in str(excinfo.value)


def test_build_evidence_stores_start_and_end_provenance(monkeypatch):
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    start_meta = {
        "git_sha": "git123",
        "docker_image_id": "img123",
        "container_id": "cnt123",
        "target_container_image_id": "timg123",
        "image_digest": "digest123",
        "container_name": "app-1",
        "service_name": "app",
        "bound_port": 8000,
    }
    end_meta = dict(start_meta)

    sample = Samples("test", values=[1.0])

    evidence = build_evidence(
        "http://test",
        100,
        10,
        sample,
        sample,
        sample,
        sample,
        sample,
        host_load={"cpu_count": 4, "load_1m": {"min": None, "median": None, "max": None}},
        strict_provenance=True,
        start_meta=start_meta,
        end_meta=end_meta,
    )

    assert evidence["meta"]["start_provenance"] == start_meta
    assert evidence["meta"]["end_provenance"] == end_meta
    assert evidence["meta"]["provenance_consistent"] is True
    assert evidence["meta"]["container_id"] == "cnt123"

    # start와 end가 불일치할 때 build_evidence에서 BuildProvenanceError 발생 검증
    mismatched_end = dict(start_meta)
    mismatched_end["container_id"] = "cnt_changed"
    with pytest.raises(BuildProvenanceError) as excinfo:
        build_evidence(
            "http://test",
            100,
            10,
            sample,
            sample,
            sample,
            sample,
            sample,
            strict_provenance=True,
            start_meta=start_meta,
            end_meta=mismatched_end,
        )
    assert "container_id changed" in str(excinfo.value)


def test_build_evidence_records_false_consistency_in_non_strict_mode():
    start_meta = {
        "git_sha": "git123",
        "docker_image_id": "img123",
        "container_id": "cnt123",
        "target_container_image_id": "timg123",
        "image_digest": "digest123",
        "container_name": "app-1",
        "service_name": "app",
        "bound_port": 8000,
    }
    swapped_end = dict(start_meta)
    swapped_end["container_id"] = "cnt_changed"

    sample = Samples("test", values=[1.0])

    evidence = build_evidence(
        "http://test",
        100,
        10,
        sample,
        sample,
        sample,
        sample,
        sample,
        host_load={"cpu_count": 4, "load_1m": {"min": None, "median": None, "max": None}},
        strict_provenance=False,
        start_meta=start_meta,
        end_meta=swapped_end,
    )

    assert evidence["meta"]["provenance_consistent"] is False


def test_benchmark_latency_main_fails_when_container_swapped_during_measurement(
    monkeypatch, tmp_path
):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_latency.httpx, "get", lambda *a, **kw: MockHealthResponse())

    call_count = 0

    def mock_command_output(command: list[str]) -> str:
        nonlocal call_count
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "compose_img_id_111"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            call_count += 1
            # 시작 시점과 종료 시점에 다른 container ID를 반환하여 교체 시뮬레이션
            return "cnt_start_111" if call_count == 1 else "cnt_end_222"
        if command[0] == "docker" and command[1] == "inspect":
            if command[3] == "{{.Image}}":
                return "running_img_id_333"
            if command[3] == "{{.Name}}":
                return "/refac_app_1"
            if command[3] == "{{.State.Running}}":
                return "true"
            if command[3] == "{{json .NetworkSettings.Ports}}":
                return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
            if command[3] == "{{.NetworkSettings.IPAddress}}":
                return "172.18.0.5"
            if command[3] == "{{json .RepoDigests}}":
                return '["registry.example.com/app@sha256:repodigest444"]'
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command_output)

    # 벤치마크 루틴 mock
    sample = Samples("dummy", values=[10.0])
    monkeypatch.setattr(benchmark_latency, "benchmark_predict", lambda *a, **kw: sample)
    monkeypatch.setattr(
        benchmark_latency, "benchmark_sse_canonical", lambda *a, **kw: (sample, sample, sample)
    )
    monkeypatch.setattr(benchmark_latency, "benchmark_query", lambda *a, **kw: sample)

    out_file = tmp_path / "test_out.json"
    monkeypatch.setattr(
        benchmark_latency.sys,
        "argv",
        [
            "benchmark_latency.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--output",
            str(out_file),
        ],
    )

    exit_code = benchmark_latency.main()
    # 측정 종료 시점 검증에서 container 교체로 인해 종료 코드 2 반환
    assert exit_code == 2
    # 측정 실패 시 결과 파일이 생성되지 않아야 함 (fail-closed)
    assert not out_file.exists()


def test_reproducibility_metadata_bind_mount_clean_success(monkeypatch):
    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "harness_git_sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:compose_img"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_123"]:
            return "sha256:running_img"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_123"]:
            return "/app_cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_123"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "sha256:running_img"]:
            return '["app:latest"]'
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "cnt_123"]:
            return '[{"Type":"bind","Source":"/Users/test/workspace/src","Destination":"/app/src"}]'
        if command == ["git", "-C", "/Users/test/workspace/src", "rev-parse", "HEAD"]:
            return "source_git_sha_789"
        if command == ["git", "-C", "/Users/test/workspace/src", "status", "--porcelain"]:
            return ""
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    assert meta["target_source_mount"] == "/Users/test/workspace/src"
    assert meta["target_source_git_sha"] == "source_git_sha_789"
    assert meta["target_source_git_dirty"] is False


def test_reproducibility_metadata_bind_mount_dirty_rejected_in_strict_mode(monkeypatch):
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "harness_git_sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:compose_img"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_123"]:
            return "sha256:running_img"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_123"]:
            return "/app_cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_123"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "cnt_123"]:
            return '[{"Type":"bind","Source":"/Users/test/workspace/src","Destination":"/app/src"}]'
        if command == ["git", "-C", "/Users/test/workspace/src", "rev-parse", "HEAD"]:
            return "source_git_sha_789"
        if command == ["git", "-C", "/Users/test/workspace/src", "status", "--porcelain"]:
            return " M src/app/main.py\n?? src/new_file.py"
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    # strict=True: BuildProvenanceError 발생
    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_latency.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:8000",
        )
    assert "target_source_git_dirty(/Users/test/workspace/src)" in str(excinfo.value)

    # strict=False: 에러 없이 정상 반환하되 dirty=True 기록
    non_strict_meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=False,
        base_url="http://127.0.0.1:8000",
    )
    assert non_strict_meta["target_source_mount"] == "/Users/test/workspace/src"
    assert non_strict_meta["target_source_git_sha"] == "source_git_sha_789"
    assert non_strict_meta["target_source_git_dirty"] is True


def test_reproducibility_metadata_image_only_container_has_null_source_mount(monkeypatch):
    import json

    from scripts.benchmark_latency import dump_strict_json

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "harness_git_sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:compose_img"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_123"]:
            return "sha256:running_img"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_123"]:
            return "/app_cnt"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_123"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "sha256:running_img"]:
            return '["app:latest"]'
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "cnt_123"]:
            # /app/src 마운트가 없는 이미지 전용 컨테이너
            return '[{"Type":"bind","Source":"/data/chroma","Destination":"/app/chroma_db"}]'
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    meta = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    assert meta["target_source_mount"] is None
    assert meta["target_source_git_sha"] is None
    assert meta["target_source_git_dirty"] is None

    # strict JSON 직렬화 시 null 로 기록되는지 확인
    json_str = dump_strict_json(meta)
    parsed = json.loads(json_str)
    assert parsed["target_source_mount"] is None
    assert parsed["target_source_git_sha"] is None
    assert parsed["target_source_git_dirty"] is None


def test_benchmark_latency_main_fails_on_dirty_runtime_source(monkeypatch, tmp_path):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_latency.httpx, "get", lambda *a, **kw: MockHealthResponse())

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "compose_img_id_111"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_app_111"
        if command[0] == "docker" and command[1] == "inspect":
            if command[3] == "{{.Image}}":
                return "running_img_id_333"
            if command[3] == "{{.Name}}":
                return "/refac_app_1"
            if command[3] == "{{.State.Running}}":
                return "true"
            if command[3] == "{{json .NetworkSettings.Ports}}":
                return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
            if command[3] == "{{.NetworkSettings.IPAddress}}":
                return "172.18.0.5"
            if command[3] == "{{json .RepoDigests}}":
                return '["registry.example.com/app@sha256:repodigest444"]'
            if command[3] == "{{json .Mounts}}":
                return '[{"Type":"bind","Source":"/my/dirty/src","Destination":"/app/src"}]'
        if command == ["git", "-C", "/my/dirty/src", "rev-parse", "HEAD"]:
            return "dirty_sha_123"
        if command == ["git", "-C", "/my/dirty/src", "status", "--porcelain"]:
            return " M dirty_code.py"
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    out_file = tmp_path / "test_dirty_out.json"
    monkeypatch.setattr(
        benchmark_latency.sys,
        "argv",
        [
            "benchmark_latency.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--output",
            str(out_file),
        ],
    )

    exit_code = benchmark_latency.main()
    assert exit_code == 2
    assert not out_file.exists()


def test_verify_provenance_consistency_detects_source_mount_and_git_changes():
    import pytest

    from scripts.benchmark_latency import BuildProvenanceError

    start_meta = {
        "container_id": "cnt_123",
        "target_container_image_id": "img_123",
        "docker_image_id": "img_123",
        "image_digest": "none (local build)",
        "git_sha": "git_123",
        "container_name": "app-1",
        "service_name": "app",
        "target_source_mount": "/path/to/src",
        "target_source_git_sha": "src_sha_111",
        "target_source_git_dirty": False,
    }

    # 1. target_source_mount 변경
    end_mount = dict(start_meta)
    end_mount["target_source_mount"] = "/other/path/src"
    with pytest.raises(BuildProvenanceError) as exc:
        benchmark_latency.verify_provenance_consistency(start_meta, end_mount, strict=True)
    assert "target_source_mount changed" in str(exc.value)

    # 2. target_source_git_sha 변경
    end_sha = dict(start_meta)
    end_sha["target_source_git_sha"] = "src_sha_222"
    with pytest.raises(BuildProvenanceError) as exc:
        benchmark_latency.verify_provenance_consistency(start_meta, end_sha, strict=True)
    assert "target_source_git_sha changed" in str(exc.value)

    # 3. target_source_git_dirty 변경 (측정 중 소스 수정)
    end_dirty = dict(start_meta)
    end_dirty["target_source_git_dirty"] = True
    with pytest.raises(BuildProvenanceError) as exc:
        benchmark_latency.verify_provenance_consistency(start_meta, end_dirty, strict=True)
    assert "target_source_git_dirty changed" in str(exc.value)


def test_runtime_config_snapshot_returns_allowlisted_keys_only(monkeypatch):
    """허용 목록에 없는 환경변수는 값도 이름도 기록되지 않는다."""
    import json

    def mock_command(command: list[str]) -> str:
        if command[0] == "docker" and "inspect" in command and command[3] == "{{json .Config.Env}}":
            env_list = [
                "WEB_CONCURRENCY=4",
                "PREDICTION_GC_MODE=freeze",
                "LATENCY_SEGMENT_LOGGING=true",
                "LLM_PROVIDER=ollama",
                "OLLAMA_MODEL=gemma4:e4b",
                "SECRET_KEY=super_secret_value_12345",
                "DB_PASSWORD=my_database_password",
                "MYSQL_ROOT_PASSWORD=root_secret",
                "MEILI_MASTER_KEY=meili_secret_key",
                "DATABASE_URL=mysql+pymysql://root:secret@db:3306/procurement",
                "GEMINI_API_KEY=gemini_secret_api_key",
                "CUSTOM_UNRELATED_VAR=some_value",
            ]
            return json.dumps(env_list)
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    snapshot = benchmark_latency.runtime_config_snapshot("cnt_123")

    # 허용 목록에 있는 키만 기록된다
    assert snapshot["WEB_CONCURRENCY"] == "4"
    assert snapshot["PREDICTION_GC_MODE"] == "freeze"
    assert snapshot["LATENCY_SEGMENT_LOGGING"] == "true"
    assert snapshot["LLM_PROVIDER"] == "ollama"
    assert snapshot["OLLAMA_MODEL"] == "gemma4:e4b"

    # 비밀값은 절대 포함되지 않는다
    assert "SECRET_KEY" not in snapshot
    assert "DB_PASSWORD" not in snapshot
    assert "MYSQL_ROOT_PASSWORD" not in snapshot
    assert "MEILI_MASTER_KEY" not in snapshot
    assert "DATABASE_URL" not in snapshot
    assert "GEMINI_API_KEY" not in snapshot

    # 허용 목록에 없는 키는 반환되지 않는다
    assert "CUSTOM_UNRELATED_VAR" not in snapshot
    assert len(snapshot) == len(PERF_CONFIG_ALLOWLIST)


def test_runtime_config_snapshot_handles_unknown_container():
    """컨테이너가 없거나 환경변수를 못 읽는 경우에도 모든 값이 None으로 기록된다."""
    snapshot = benchmark_latency.runtime_config_snapshot("unknown")

    assert len(snapshot) == len(PERF_CONFIG_ALLOWLIST)
    assert all(v is None for v in snapshot.values())
    for key in PERF_CONFIG_ALLOWLIST:
        assert key in snapshot


def test_runtime_config_snapshot_in_reproducibility_metadata(monkeypatch):
    """reproducibility_metadata에 perf_config 키로 설정 스냅샷이 포함된다."""
    import json

    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:app_image"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "container_id_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "container_id_123"]:
            return "sha256:target_image"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "container_id_123"]:
            return "/app-container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "container_id_123"]:
            return "true"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Ports}}",
            "container_id_123",
        ]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{.NetworkSettings.IPAddress}}",
            "container_id_123",
        ]:
            return "172.18.0.2"
        if command == [
            "docker",
            "inspect",
            "-f",
            "{{json .RepoDigests}}",
            "sha256:target_image",
        ]:
            return '["app:latest"]'
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "container_id_123"]:
            return "[]"
        if command[0] == "docker" and "inspect" in command and command[3] == "{{json .Config.Env}}":
            env_list = [
                "WEB_CONCURRENCY=2",
                "PREDICTION_GC_MODE=freeze",
                "SECRET_KEY=secret_value",
            ]
            return json.dumps(env_list)
        return "unknown"

    monkeypatch.setattr(benchmark_latency, "_command_output", mock_command)

    metadata = benchmark_latency.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    # perf_config 키가 존재하고 올바르게 기록된다
    assert "perf_config" in metadata
    assert metadata["perf_config"]["WEB_CONCURRENCY"] == "2"
    assert metadata["perf_config"]["PREDICTION_GC_MODE"] == "freeze"
    # 비밀값은 포함되지 않는다
    assert "SECRET_KEY" not in metadata["perf_config"]


def test_perf_config_allowlist_contains_expected_keys():
    """성능 관련 설정 허용 목록에 예상되는 키가 모두 포함되어 있다."""
    expected_keys = {
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
    assert expected_keys == PERF_CONFIG_ALLOWLIST


def test_perf_config_allowlist_excludes_secrets():
    """비밀값 관련 키가 허용 목록에 절대 포함되지 않는다."""
    secret_patterns = [
        "SECRET",
        "PASSWORD",
        "KEY",
        "TOKEN",
        "DSN",
        "CREDENTIAL",
    ]
    for key in PERF_CONFIG_ALLOWLIST:
        for pattern in secret_patterns:
            assert pattern not in key.upper(), (
                f"Secret pattern '{pattern}' found in allowlist key '{key}'"
            )
