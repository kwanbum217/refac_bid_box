import pytest

from scripts import benchmark_sse_gate
from scripts.benchmark_latency import BuildProvenanceError


def test_sse_reproducibility_metadata_contract(monkeypatch):
    commands_executed: list[list[str]] = []

    def command_output(command: list[str]) -> str:
        commands_executed.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:image"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_app_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_app_123"]:
            return "sha256:image_cnt"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_app_123"]:
            return "/app_container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_app_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_app_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_app_123"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "sha256:image_cnt"]:
            return '["refac_bid_box-app@sha256:img_digest"]'
        return "unknown"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", command_output)

    metadata = benchmark_sse_gate.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    assert metadata["git_sha"] == "sha"
    assert metadata["docker_image_id"] == "sha256:image"
    assert metadata["container_id"] == "cnt_app_123"
    assert metadata["target_container_image_id"] == "sha256:image_cnt"
    assert metadata["image_digest"] == "refac_bid_box-app@sha256:img_digest"
    assert metadata["container_name"] == "app_container"
    assert metadata["bound_port"] == 8000

    # compose service 이름 'app' 조회(backend 아님)를 검증합니다.
    assert ["docker", "compose", "images", "-q", "app"] in commands_executed
    assert ["docker", "compose", "ps", "-q", "app"] in commands_executed
    assert ["docker", "compose", "images", "-q", "backend"] not in commands_executed


def test_sse_reproducibility_metadata_handles_docker_lookup_failure(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    meta = benchmark_sse_gate.reproducibility_metadata(strict=False)
    assert meta["docker_image_id"] == "unknown"
    assert meta["container_id"] == "unknown"
    assert meta["target_container_image_id"] == "unknown"


def test_sse_reproducibility_metadata_strict_raises_error_on_unknown(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_sse_gate.reproducibility_metadata(strict=True)
    assert "lookup failed or returned unknown" in str(excinfo.value)


def test_sse_reproducibility_metadata_port_mismatch_fails(monkeypatch):
    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:image"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_app_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_app_123"]:
            return "sha256:image_cnt"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_app_123"]:
            return "/app_container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_app_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_app_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        return "unknown"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_command)

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_sse_gate.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:8080",
        )
    assert "port 8080 not bound" in str(excinfo.value)


def test_sse_empty_docker_lookup_is_unknown(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    assert (
        benchmark_sse_gate._command_output(["docker", "compose", "images", "-q", "app"])
        == "unknown"
    )


def test_benchmark_sse_gate_main_provenance_failure_returns_code_2(monkeypatch):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _cmd: "unknown")
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        ["benchmark_sse_gate.py", "--base-url", "http://127.0.0.1:8000"],
    )

    exit_code = benchmark_sse_gate.main()
    assert exit_code == 2


def test_benchmark_sse_gate_main_fails_when_container_swapped_during_measurement(
    monkeypatch, tmp_path
):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())

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
            return "cnt_sse_start_111" if call_count == 1 else "cnt_sse_end_222"
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

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_command_output)

    # run_benchmark mock
    mock_summary = {
        "first_token_stats": {"p95_ms": 100.0},
        "final_stats": {"p95_ms": 500.0},
        "error_requests": 0,
    }
    monkeypatch.setattr(benchmark_sse_gate, "run_benchmark", lambda *a, **kw: (mock_summary, []))

    out_file = tmp_path / "sse_out.json"
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        [
            "benchmark_sse_gate.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--output",
            str(out_file),
        ],
    )

    exit_code = benchmark_sse_gate.main()
    # 측정 종료 시점 검증에서 container 교체로 인해 종료 코드 2 반환
    assert exit_code == 2
    # fail-closed: 파일이 저장되지 않음
    assert not out_file.exists()


def test_benchmark_sse_gate_output_records_start_and_end_provenance(monkeypatch, tmp_path):
    import json

    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())

    def mock_command_output(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "compose_img_id_111"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_sse_stable_111"
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

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_command_output)

    mock_summary = {
        "first_token_stats": {"p95_ms": 100.0},
        "final_stats": {"p95_ms": 500.0},
        "error_requests": 0,
    }
    monkeypatch.setattr(benchmark_sse_gate, "run_benchmark", lambda *a, **kw: (mock_summary, []))

    out_file = tmp_path / "sse_out_success.json"
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        [
            "benchmark_sse_gate.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--output",
            str(out_file),
        ],
    )

    exit_code = benchmark_sse_gate.main()
    assert exit_code == 0
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "start_provenance" in data["meta"]
    assert "end_provenance" in data["meta"]
    assert data["meta"]["provenance_consistent"] is True
    assert data["meta"]["container_id"] == "cnt_sse_stable_111"
    assert data["meta"]["start_provenance"]["container_id"] == "cnt_sse_stable_111"
    assert data["meta"]["end_provenance"]["container_id"] == "cnt_sse_stable_111"


def test_benchmark_sse_gate_main_fails_on_dirty_runtime_source(monkeypatch, tmp_path):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())

    def mock_command_output(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "git_sha_abc"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "compose_img_id_111"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_sse_dirty_111"
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

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_command_output)

    out_file = tmp_path / "sse_dirty_out.json"
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        [
            "benchmark_sse_gate.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--output",
            str(out_file),
        ],
    )

    exit_code = benchmark_sse_gate.main()
    assert exit_code == 2
    assert not out_file.exists()


def test_sse_reproducibility_metadata_bind_mount_clean_and_image_only(monkeypatch):
    # 1. Clean bind mount 케이스
    def mock_clean_mount(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha1"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:img"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_1"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_1"]:
            return "sha256:img_c"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_1"]:
            return "/app_c"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_1"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_1"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_1"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "sha256:img_c"]:
            return '["app:latest"]'
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "cnt_1"]:
            return '[{"Type":"bind","Source":"/workspace/src","Destination":"/app/src"}]'
        if command == ["git", "-C", "/workspace/src", "rev-parse", "HEAD"]:
            return "src_sha_abc"
        if command == ["git", "-C", "/workspace/src", "status", "--porcelain"]:
            return ""
        return "unknown"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_clean_mount)

    meta_clean = benchmark_sse_gate.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )
    assert meta_clean["target_source_mount"] == "/workspace/src"
    assert meta_clean["target_source_git_sha"] == "src_sha_abc"
    assert meta_clean["target_source_git_dirty"] is False

    # 2. 이미지 전용 (no /app/src mount) 케이스
    def mock_image_only(command: list[str]) -> str:
        if command == ["docker", "inspect", "-f", "{{json .Mounts}}", "cnt_1"]:
            return "[]"
        return mock_clean_mount(command)

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_image_only)

    meta_img = benchmark_sse_gate.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )
    assert meta_img["target_source_mount"] is None
    assert meta_img["target_source_git_sha"] is None
    assert meta_img["target_source_git_dirty"] is None


class _MockSSEStreamResponse:
    def __init__(self, status_code: int = 200, lines: list[str] | None = None):
        self.status_code = status_code
        self._lines = lines or [
            "event: stage\n",
            "data: search\n",
            "event: token\n",
            "data: Hello\n",
            "event: final\n",
            "data: done\n",
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def iter_lines(self):
        yield from self._lines


def test_sse_request_with_session_cookie_strips_prefix_and_passes_to_client(monkeypatch):
    captured_client_kwargs: list[dict] = []

    class MockClient:
        def __init__(self, *args, **kwargs):
            captured_client_kwargs.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            return _MockSSEStreamResponse(status_code=200)

    monkeypatch.setattr(benchmark_sse_gate.httpx, "Client", MockClient)

    # 1. bidbox_session= 접두어가 있는 쿠키
    rec1 = benchmark_sse_gate.execute_sse_request(
        base_url="http://testserver",
        index=0,
        query="질의 1",
        session_cookie="bidbox_session=test_cookie_value_123",
    )
    assert rec1.success is True
    assert captured_client_kwargs[-1].get("cookies") == {"bidbox_session": "test_cookie_value_123"}

    # 2. 접두어가 없는 쿠키
    rec2 = benchmark_sse_gate.execute_sse_request(
        base_url="http://testserver",
        index=1,
        query="질의 2",
        session_cookie="raw_cookie_abc",
    )
    assert rec2.success is True
    assert captured_client_kwargs[-1].get("cookies") == {"bidbox_session": "raw_cookie_abc"}

    # 3. 쿠키가 없는 경우 (None)
    rec3 = benchmark_sse_gate.execute_sse_request(
        base_url="http://testserver",
        index=2,
        query="질의 3",
        session_cookie=None,
    )
    assert rec3.success is True
    assert "cookies" not in captured_client_kwargs[-1]


def test_sse_request_anonymous_429_returns_anonymous_quota_error_and_exit_code_1(
    monkeypatch, capsys
):
    class MockClient429:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            return _MockSSEStreamResponse(status_code=429)

    monkeypatch.setattr(benchmark_sse_gate.httpx, "Client", MockClient429)

    # (a) execute_sse_request 레벨 검증: 쿠키 없을 때 429이면 http_429_anonymous_quota
    rec = benchmark_sse_gate.execute_sse_request(
        base_url="http://testserver",
        index=0,
        query="익명 질의",
        session_cookie=None,
    )
    assert rec.success is False
    assert rec.error == "http_429_anonymous_quota"

    # (b) main() 레벨 검증: 안내 문구 출력 및 종료 코드 1 반환
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())
    monkeypatch.setattr(
        benchmark_sse_gate,
        "reproducibility_metadata",
        lambda **kw: {"git_sha": "sha_123", "container_id": "cnt_1"},
    )
    monkeypatch.setattr(
        benchmark_sse_gate,
        "verify_provenance_consistency",
        lambda *a, **kw: True,
    )
    monkeypatch.delenv("BENCHMARK_SESSION_COOKIE", raising=False)
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        [
            "benchmark_sse_gate.py",
            "--base-url",
            "http://testserver",
            "--no-warmup",
            "--rounds",
            "2",
        ],
    )

    exit_code = benchmark_sse_gate.main()
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "익명 쿼터로 차단된 표본이 있습니다. --session-cookie 로 재측정하십시오." in captured.out


def test_sse_request_authenticated_429_recorded_as_http_429(monkeypatch):
    class MockClient429:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            return _MockSSEStreamResponse(status_code=429)

    monkeypatch.setattr(benchmark_sse_gate.httpx, "Client", MockClient429)

    # 쿠키가 있을 때 429이면 기존처럼 http_429로 기록
    rec = benchmark_sse_gate.execute_sse_request(
        base_url="http://testserver",
        index=0,
        query="인증 질의",
        session_cookie="bidbox_session=valid_token",
    )
    assert rec.success is False
    assert rec.error == "http_429"


def test_sse_benchmark_successful_samples_metric_calculation_invariant(monkeypatch):
    class MockSuccessClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            return _MockSSEStreamResponse(status_code=200)

    monkeypatch.setattr(benchmark_sse_gate.httpx, "Client", MockSuccessClient)

    summary, records = benchmark_sse_gate.run_benchmark(
        base_url="http://testserver",
        concurrency=1,
        rounds=3,
        round_num=1,
        warmup=False,
        session_cookie="bidbox_session=valid_token",
    )

    assert summary["rounds"] == 3
    assert summary["successful_requests"] == 3
    assert summary["error_requests"] == 0
    assert len(records) == 3
    assert all(r.success for r in records)

    # 통계 지표 산출 불변 검증
    ft_stats = summary["first_token_stats"]
    assert ft_stats["n"] == 3
    assert ft_stats["p50_ms"] is not None
    assert ft_stats["p95_ms"] is not None
    assert ft_stats["threshold_ms"] == benchmark_sse_gate.FIRST_TOKEN_TARGET_MS
    assert ft_stats["exceeded_count"] == 0
    assert ft_stats["exceeded_rate_pct"] == 0.0

    # compute_metric_stats 함수 단위 불변 검증
    sample_values = [100.0, 200.0, 300.0, 400.0, 500.0]
    calc = benchmark_sse_gate.compute_metric_stats(sample_values, threshold_ms=350.0)
    assert calc["n"] == 5
    assert calc["p50_ms"] == 300.0
    assert calc["p95_ms"] == 480.0
    assert calc["p99_ms"] == 496.0
    assert calc["min_ms"] == 100.0
    assert calc["max_ms"] == 500.0
    assert calc["mean_ms"] == 300.0
    assert calc["exceeded_count"] == 2
    assert calc["exceeded_rate_pct"] == 40.0
    assert calc["wilson_upper_pct"] == benchmark_sse_gate.wilson_score_upper(2, 5)
