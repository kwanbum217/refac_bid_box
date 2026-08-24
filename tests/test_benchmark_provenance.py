"""
tests/test_benchmark_provenance.py

scripts/benchmark_provenance.py 공통 레이어 단위 테스트.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts import benchmark_provenance
from scripts.benchmark_provenance import (
    PERF_CONFIG_ALLOWLIST,
    PROVENANCE_REQUIRED_FIELDS,
    BuildProvenanceError,
    HostLoadMonitor,
    _command_output,
    _parse_container_command,
    _parse_effective_workers,
    build_load_protocol_record,
    build_provenance_dict,
    check_ambient_load_protocol,
    compute_baseline_summary,
    compute_host_load_stats,
    enforce_provenance_required_fields,
    get_git_status,
    get_host_memory,
    host_load_metadata,
    is_source_dirty,
    provenance_unknown_required_fields,
    reproducibility_metadata,
    resolve_redis_container,
    runtime_config_snapshot,
    single_host_load_sample,
    verify_provenance_consistency,
)


class TestWorkerParsing:
    """Docker Config.Cmd 기반 effective_web_workers 파싱 테스트."""

    def test_parse_workers_separated_list(self):
        cmd = ["python3", "-m", "uvicorn", "src.app.main:app", "--workers", "4"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 4
        assert reason is None

    def test_parse_workers_separated_short_flag_list(self):
        cmd = ["uvicorn", "main:app", "-w", "2"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 2
        assert reason is None

    def test_parse_workers_equal_sign_list(self):
        cmd = ["python3", "-m", "uvicorn", "src.app.main:app", "--workers=8"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 8
        assert reason is None

    def test_parse_workers_equal_sign_short_flag_list(self):
        cmd = ["uvicorn", "main:app", "-w=3"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 3
        assert reason is None

    def test_parse_workers_separated_string(self):
        cmd = "uvicorn src.app.main:app --host 0.0.0.0 --workers 5"  # nosec B104
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 5
        assert reason is None

    def test_parse_workers_equal_sign_string(self):
        cmd = "uvicorn src.app.main:app -w=6"
        workers, reason = _parse_effective_workers(cmd)
        assert workers == 6
        assert reason is None

    def test_parse_workers_missing_flag(self):
        cmd = [
            "python3",
            "-m",
            "uvicorn",
            "src.app.main:app",
            "--host",
            "0.0.0.0",  # noqa: S104  # nosec B104
        ]
        workers, reason = _parse_effective_workers(cmd)
        assert workers is None
        assert reason == "workers_flag_not_found"

    def test_parse_workers_invalid_value(self):
        cmd = ["uvicorn", "main:app", "--workers", "invalid_int"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers is None
        assert "invalid_workers_value" in reason

    def test_parse_workers_missing_argument(self):
        cmd = ["uvicorn", "main:app", "--workers"]
        workers, reason = _parse_effective_workers(cmd)
        assert workers is None
        assert reason == "missing_workers_argument"

    def test_parse_workers_empty_equal_argument(self):
        cmd = ["uvicorn", "main:app", "--workers="]
        workers, reason = _parse_effective_workers(cmd)
        assert workers is None
        assert reason == "missing_workers_argument"

    def test_parse_workers_unclosed_string_quote(self):
        cmd = "uvicorn main:app --workers 'unclosed"
        workers, reason = _parse_effective_workers(cmd)
        assert workers is None
        assert reason == "command_parse_error"

    def test_parse_workers_none_command(self):
        workers, reason = _parse_effective_workers(None)
        assert workers is None
        assert reason == "container_command_unavailable"


class TestContainerCommandParsing:
    """_parse_container_command JSON 및 문자열 변환 테스트."""

    def test_parse_json_list(self):
        raw = '["python3", "-m", "uvicorn", "src.app.main:app"]'
        parsed = _parse_container_command(raw)
        assert parsed == ["python3", "-m", "uvicorn", "src.app.main:app"]

    def test_parse_json_string(self):
        raw = '"uvicorn main:app"'
        parsed = _parse_container_command(raw)
        assert parsed == "uvicorn main:app"

    def test_parse_plain_string(self):
        raw = "arq src.tasks.worker.WorkerSettings"
        parsed = _parse_container_command(raw)
        assert parsed == "arq src.tasks.worker.WorkerSettings"

    def test_parse_empty_or_unknown(self):
        assert _parse_container_command("") is None
        assert _parse_container_command("unknown") is None
        assert _parse_container_command("null") is None
        assert _parse_container_command("[]") is None


class TestRuntimeConfigSnapshot:
    """runtime_config_snapshot 허용 목록 및 workers 기록 테스트."""

    def test_runtime_config_snapshot_with_command_and_env(self, monkeypatch):
        def mock_command(command: list[str]) -> str:
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{json .Config.Env}}":
                    return json.dumps(
                        [
                            "WEB_CONCURRENCY=2",
                            "PREDICTION_GC_MODE=freeze",
                            "LATENCY_SEGMENT_LOGGING=true",
                            "LLM_PROVIDER=ollama",
                            "OLLAMA_MODEL=gemma4:e4b",
                            "SECRET_KEY=leak_risk_secret",
                            "MYSQL_ROOT_PASSWORD=db_root_secret",
                        ]
                    )
                if command[3] == "{{json .Config.Cmd}}":
                    return json.dumps(
                        [
                            "python3",
                            "-m",
                            "uvicorn",
                            "src.app.main:app",
                            "--workers",
                            "2",
                        ]
                    )
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", mock_command)

        snapshot = runtime_config_snapshot("cnt_test_123")

        # 허용 목록 환경변수 검증
        assert snapshot["WEB_CONCURRENCY"] == "2"
        assert snapshot["PREDICTION_GC_MODE"] == "freeze"
        assert snapshot["LATENCY_SEGMENT_LOGGING"] == "true"
        assert snapshot["LLM_PROVIDER"] == "ollama"
        assert snapshot["OLLAMA_MODEL"] == "gemma4:e4b"

        # 비밀값 누출 방지 검증
        assert "SECRET_KEY" not in snapshot
        assert "MYSQL_ROOT_PASSWORD" not in snapshot

        # 커맨드 및 실효 워커 검증
        assert snapshot["container_command"] == [
            "python3",
            "-m",
            "uvicorn",
            "src.app.main:app",
            "--workers",
            "2",
        ]
        assert snapshot["effective_web_workers"] == 2
        assert snapshot["effective_web_workers_reason"] is None

        # 키 집합 무결성 검증
        assert set(snapshot.keys()) == PERF_CONFIG_ALLOWLIST | {
            "container_command",
            "effective_web_workers",
            "effective_web_workers_reason",
        }

    def test_runtime_config_snapshot_unknown_container(self):
        snapshot = runtime_config_snapshot("unknown")
        for key in PERF_CONFIG_ALLOWLIST:
            assert snapshot[key] is None
        assert snapshot["container_command"] is None
        assert snapshot["effective_web_workers"] is None
        assert snapshot["effective_web_workers_reason"] == "container_unknown"


class TestReproducibilityMetadata:
    """reproducibility_metadata identity 및 포트 바인딩 fail-closed 검증 테스트."""

    def test_strict_mode_success(self, monkeypatch):
        def mock_command(command: list[str]) -> str:
            if command == ["git", "rev-parse", "HEAD"]:
                return "git_sha_123"
            if command == ["docker", "compose", "images", "-q", "app"]:
                return "compose_img_sha"
            if command == ["docker", "compose", "ps", "-q", "app"]:
                return "cnt_id_123"
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{.Image}}":
                    return "target_img_sha"
                if command[3] == "{{.Name}}":
                    return "/refac-app"
                if command[3] == "{{.State.Running}}":
                    return "true"
                if command[3] == "{{json .NetworkSettings.Ports}}":
                    return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
                if command[3] == "{{.NetworkSettings.IPAddress}}":
                    return "172.18.0.3"
                if command[3] == "{{json .RepoDigests}}":
                    return '["refac-app@sha256:digest123"]'
                if command[3] == "{{json .Mounts}}":
                    return '[{"Type":"bind","Source":"/test/src","Destination":"/app/src"}]'
                if command[3] == "{{json .Config.Env}}":
                    return '["PREDICTION_GC_MODE=freeze"]'
                if command[3] == "{{json .Config.Cmd}}":
                    return '["uvicorn", "src.app.main:app", "--workers", "1"]'
            if command == ["git", "-C", "/test/src", "rev-parse", "HEAD"]:
                return "src_sha_123"
            if command == ["git", "-C", "/test/src", "status", "--porcelain"]:
                return ""
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", mock_command)

        meta = reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:8000",
        )

        assert meta["git_sha"] == "git_sha_123"
        assert meta["docker_image_id"] == "compose_img_sha"
        assert meta["container_id"] == "cnt_id_123"
        assert meta["target_container_image_id"] == "target_img_sha"
        assert meta["image_digest"] == "refac-app@sha256:digest123"
        assert meta["container_name"] == "refac-app"
        assert meta["bound_port"] == 8000
        assert meta["target_source_mount"] == "/test/src"
        assert meta["target_source_git_sha"] == "src_sha_123"
        assert meta["target_source_git_dirty"] is False
        assert meta["perf_config"]["effective_web_workers"] == 1

    def test_strict_mode_fails_on_stopped_container(self, monkeypatch):
        def mock_command(command: list[str]) -> str:
            if command == ["git", "rev-parse", "HEAD"]:
                return "git_sha_123"
            if command == ["docker", "compose", "images", "-q", "app"]:
                return "compose_img_sha"
            if command == ["docker", "compose", "ps", "-q", "app"]:
                return "cnt_id_123"
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{.Image}}":
                    return "target_img_sha"
                if command[3] == "{{.Name}}":
                    return "/refac-app"
                if command[3] == "{{.State.Running}}":
                    return "false"
                if command[3] == "{{json .NetworkSettings.Ports}}":
                    return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", mock_command)

        with pytest.raises(BuildProvenanceError, match="is not running"):
            reproducibility_metadata(
                service_name="app", strict=True, base_url="http://127.0.0.1:8000"
            )

    def test_strict_mode_fails_on_dirty_source(self, monkeypatch):
        def mock_command(command: list[str]) -> str:
            if command == ["git", "rev-parse", "HEAD"]:
                return "git_sha_123"
            if command == ["docker", "compose", "images", "-q", "app"]:
                return "compose_img_sha"
            if command == ["docker", "compose", "ps", "-q", "app"]:
                return "cnt_id_123"
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{.Image}}":
                    return "target_img_sha"
                if command[3] == "{{.Name}}":
                    return "/refac-app"
                if command[3] == "{{.State.Running}}":
                    return "true"
                if command[3] == "{{json .NetworkSettings.Ports}}":
                    return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
                if command[3] == "{{json .Mounts}}":
                    return '[{"Type":"bind","Source":"/test/src","Destination":"/app/src"}]'
            if command == ["git", "-C", "/test/src", "rev-parse", "HEAD"]:
                return "src_sha_123"
            if command == ["git", "-C", "/test/src", "status", "--porcelain"]:
                return " M modified_file.py"
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", mock_command)

        with pytest.raises(BuildProvenanceError, match="target_source_git_dirty"):
            reproducibility_metadata(
                service_name="app", strict=True, base_url="http://127.0.0.1:8000"
            )


class TestProvenanceConsistency:
    """verify_provenance_consistency 시작/종료 일치성 검증 테스트."""

    def test_consistency_matching_metadata(self):
        start_meta = {
            "container_id": "cnt_1",
            "target_container_image_id": "timg_1",
            "docker_image_id": "dimg_1",
            "image_digest": "digest_1",
            "git_sha": "git_1",
            "container_name": "app-1",
            "service_name": "app",
            "target_source_mount": "/src",
            "target_source_git_sha": "src_git_1",
            "target_source_git_dirty": False,
        }
        end_meta = dict(start_meta)
        assert verify_provenance_consistency(start_meta, end_meta, strict=True) is True

    def test_consistency_detects_swapped_container_id(self):
        start_meta = {
            "container_id": "cnt_1",
            "target_container_image_id": "timg_1",
            "docker_image_id": "dimg_1",
            "image_digest": "digest_1",
            "git_sha": "git_1",
            "container_name": "app-1",
            "service_name": "app",
            "target_source_mount": None,
            "target_source_git_sha": None,
            "target_source_git_dirty": None,
        }
        end_meta = dict(start_meta)
        end_meta["container_id"] = "cnt_2_swapped"

        with pytest.raises(BuildProvenanceError, match="container_id changed"):
            verify_provenance_consistency(start_meta, end_meta, strict=True)

        assert verify_provenance_consistency(start_meta, end_meta, strict=False) is False


class TestCrossPlatformHostLoad:
    """크로스플랫폼 안전 호스트 부하 계측 테스트."""

    def test_single_host_load_sample_with_getloadavg(self, monkeypatch):
        class MockOS:
            @staticmethod
            def cpu_count():
                return 4

            @staticmethod
            def getloadavg():
                return (1.0, 0.8, 0.5)

        sample = single_host_load_sample(os_module=MockOS)
        assert sample["cpu_count"] == 4
        assert sample["load_1m"] == 1.0
        assert sample["per_core_percent"] == 25.0
        assert "observed_at_utc" in sample

    def test_single_host_load_sample_without_getloadavg_windows(self):
        class MockWindowsOS:
            @staticmethod
            def cpu_count():
                return 8

        sample = single_host_load_sample(os_module=MockWindowsOS)
        assert sample["cpu_count"] == 8
        assert sample["load_1m"] is None
        assert sample["per_core_percent"] is None

    def test_single_host_load_sample_getloadavg_oserror(self):
        class MockFailingOS:
            @staticmethod
            def cpu_count():
                return 4

            @staticmethod
            def getloadavg():
                raise OSError("unsupported syscall")

        sample = single_host_load_sample(os_module=MockFailingOS)
        assert sample["cpu_count"] == 4
        assert sample["load_1m"] is None
        assert sample["per_core_percent"] is None

    def test_compute_host_load_stats(self):
        samples = [
            {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 4, "per_core_percent": 25.0},
            {"observed_at_utc": "t2", "load_1m": 2.0, "cpu_count": 4, "per_core_percent": 50.0},
            {"observed_at_utc": "t3", "load_1m": 3.0, "cpu_count": 4, "per_core_percent": 75.0},
        ]
        stats = compute_host_load_stats(samples)
        assert stats["cpu_count"] == 4
        assert stats["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
        assert stats["per_core_percent"] == {"min": 25.0, "median": 50.0, "max": 75.0}

    def test_host_load_metadata_with_custom_sampler(self):
        call_count = 0

        def custom_sampler():
            nonlocal call_count
            call_count += 1
            return {
                "observed_at_utc": f"t{call_count}",
                "load_1m": float(call_count),
                "cpu_count": 2,
                "per_core_percent": float(call_count) * 50.0,
            }

        meta = host_load_metadata(min_samples=3, interval_seconds=0.0, sampler=custom_sampler)
        assert call_count == 3
        assert len(meta["samples"]) == 3
        assert meta["load_1m"]["min"] == 1.0
        assert meta["load_1m"]["max"] == 3.0

    def test_host_load_monitor_execution(self):
        monitor = HostLoadMonitor(interval_seconds=0.001, min_samples=3)
        monitor.start()
        summary = monitor.stop()
        assert len(summary["samples"]) >= 3
        assert "min" in summary["load_1m"]


class TestSubprocessSafety:
    """_command_output 예외 처리 테스트."""

    def test_command_output_handles_filenotfound(self, monkeypatch):
        def mock_check_output(*args, **kwargs):
            raise FileNotFoundError("docker not installed")

        monkeypatch.setattr(subprocess, "check_output", mock_check_output)
        assert _command_output(["docker", "version"]) == "unknown"

    def test_command_output_handles_calledprocesserror(self, monkeypatch):
        def mock_check_output(*args, **kwargs):
            raise subprocess.CalledProcessError(1, ["docker", "ps"])

        monkeypatch.setattr(subprocess, "check_output", mock_check_output)
        assert _command_output(["docker", "ps"]) == "unknown"


class TestIsSourceDirty:
    """측정 산출물이 자기 다음 회차를 fail-closed 로 막던 회귀를 방지합니다."""

    def test_clean_status_is_not_dirty(self):
        assert is_source_dirty("") is False

    def test_untracked_benchmark_artifact_is_not_dirty(self):
        status = "?? data/benchmarks/arq_container_measure_20260824_r1.json"
        assert is_source_dirty(status) is False

    def test_multiple_untracked_benchmark_artifacts_are_not_dirty(self):
        status = (
            "?? data/benchmarks/run_r1.json\n"
            "?? data/benchmarks/run_r2.json\n"
            "?? data/benchmarks/run_r3.json"
        )
        assert is_source_dirty(status) is False

    def test_modified_tracked_source_is_dirty(self):
        assert is_source_dirty(" M scripts/benchmark_arq_container.py") is True

    def test_untracked_source_outside_benchmarks_is_dirty(self):
        assert is_source_dirty("?? scripts/rogue_patch.py") is True

    def test_modified_tracked_benchmark_file_is_dirty(self):
        assert is_source_dirty(" M data/benchmarks/committed_baseline.json") is True

    def test_benchmark_artifact_mixed_with_source_change_is_dirty(self):
        status = "?? data/benchmarks/run_r1.json\n M src/app/main.py"
        assert is_source_dirty(status) is True


class TestCommonHarnessHelpers:
    """두 하네스가 공유하는 build_provenance_dict / get_git_status / get_host_memory."""

    def test_build_provenance_dict_four_layer_schema(self):
        prov = build_provenance_dict(
            host_cpu_count=8,
            host_load_avg_1m=1.0,
            host_memory={"total_bytes": 1000, "available_bytes": 500},
            redis_url="redis://localhost:6379/0",
            redis_container_id="rcid",
            redis_container_name="rname",
            redis_image="redis:7-alpine",
            redis_image_id="sha256:rimg",
            redis_server_version="7.4.9",
            redis_server_mode="standalone",
            arq_version="0.28.0",
            redis_py_version="5.3.1",
            benchmark_worker_mode="in_process",
            worker_settings_module="in_process:Worker",
            worker_functions=["benchmark_noop_task"],
            is_synthetic=True,
            worker_max_jobs=2,
            worker_poll_delay=0.01,
            worker_job_timeout=10,
            docker_version="Docker version 29.7.2",
            worker_container_id=None,
            worker_container_name=None,
            worker_image=None,
            worker_image_id=None,
            source_mount="/app",
            source_git_sha="sha_test",
            source_git_dirty=False,
        )
        assert set(prov.keys()) == {"host", "redis", "arq", "docker"}
        assert set(prov["redis"].keys()) == {
            "redis_url",
            "container_id",
            "container_name",
            "image",
            "image_id",
            "server_version",
            "server_mode",
        }

    def test_get_git_status_clean_and_dirty(self, tmp_path, monkeypatch):
        import subprocess

        calls = []

        def fake_check_output(cmd, **kwargs):
            calls.append(cmd)
            if "rev-parse" in cmd:
                return "sha123456"
            return " M some_file.py"

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)
        sha, dirty = get_git_status(tmp_path)
        assert sha == "sha123456"
        assert dirty is True

    def test_get_host_memory_structure(self):
        mem = get_host_memory()
        assert isinstance(mem, dict)
        assert "total_bytes" in mem
        assert "available_bytes" in mem


class TestRedisResolutionFailClosed:
    """Redis 컨테이너 명시 지정 및 fail-closed 결박 검증."""

    def test_resolve_with_explicit_target(self, monkeypatch):
        def fake_cmd(command: list[str]) -> str:
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{.Image}}":
                    return "sha256:imgid"
                if command[3] == "{{.Name}}":
                    return "/redis-test"
                if command[3] == "{{.Config.Image}}":
                    return "redis:7-alpine"
                if command[3] == "{{json .NetworkSettings.Ports}}":
                    return '{"6379/tcp":[{"HostIp":"0.0.0.0","HostPort":"6379"}]}'
                if command[3] == "{{json .NetworkSettings.Networks}}":
                    return '{"test_net": {}}'
            if command[0] == "docker" and command[1] == "compose":
                return ""
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", fake_cmd)
        info = resolve_redis_container(
            redis_url="redis://localhost:6379/0",
            target="redis-test",
            strict=True,
        )
        assert info["container_id"] == "redis-test"
        assert info["container_name"] == "redis-test"
        assert info["image"] == "redis:7-alpine"
        assert info["image_id"] == "sha256:imgid"

    def test_redis_url_mismatch_fail_closed(self, monkeypatch):
        def fake_cmd(command: list[str]) -> str:
            if command[0] == "docker" and command[1] == "inspect":
                if command[3] == "{{.Image}}":
                    return "sha256:imgid"
                if command[3] == "{{.Name}}":
                    return "/redis-test"
                if command[3] == "{{.Config.Image}}":
                    return "redis:7-alpine"
                if command[3] == "{{json .NetworkSettings.Ports}}":
                    return '{"6380/tcp":[{"HostIp":"0.0.0.0","HostPort":"6380"}]}'
                if command[3] == "{{json .NetworkSettings.Networks}}":
                    return '{"test_net": {}}'
            if command[0] == "docker" and command[1] == "compose":
                return ""
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", fake_cmd)
        with pytest.raises(BuildProvenanceError, match="does not correspond to redis_url"):
            resolve_redis_container(
                redis_url="redis://localhost:6379/0",
                target="redis-test",
                strict=True,
            )

    def test_ambiguous_candidates_fail_closed(self, monkeypatch):
        def fake_cmd(command: list[str]) -> str:
            if command[0] == "docker" and command[1] == "ps":
                return "abc123\tredis-a\nxyz789\tredis-b\n"
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", fake_cmd)
        with pytest.raises(BuildProvenanceError, match="exactly 1 candidate"):
            resolve_redis_container(redis_url="redis://localhost:6379/0", strict=True)

    def test_zero_candidates_fail_closed(self, monkeypatch):
        monkeypatch.setattr(benchmark_provenance, "_command_output", lambda cmd: "")
        with pytest.raises(BuildProvenanceError, match="exactly 1 candidate"):
            resolve_redis_container(redis_url="redis://localhost:6379/0", strict=True)

    def test_lookup_exception_not_swallowed(self, monkeypatch):
        def fake_cmd(command: list[str]) -> str:
            if command[0] == "docker" and command[1] == "inspect":
                return "unknown"
            if command[0] == "docker" and command[1] == "compose":
                return ""
            if command[0] == "docker" and command[1] == "ps":
                return "abc123\tredis-test\n"
            return "unknown"

        monkeypatch.setattr(benchmark_provenance, "_command_output", fake_cmd)
        with pytest.raises(BuildProvenanceError, match="image_id"):
            resolve_redis_container(redis_url="redis://localhost:6379/0", strict=True)


class TestAmbientLoadProtocol:
    """주변 부하 규약(중앙값 30%, 최대 50%) 강제 검증."""

    def test_compliant_load_passes(self):
        stats = {
            "per_core_percent": {"min": 5.0, "median": 15.0, "max": 40.0},
        }
        compliant, detail = check_ambient_load_protocol(stats)
        assert compliant is True
        assert detail["median_limit_percent"] == 30.0
        assert detail["max_limit_percent"] == 50.0

    def test_median_over_30_fails(self):
        stats = {"per_core_percent": {"min": 5.0, "median": 31.0, "max": 45.0}}
        compliant, detail = check_ambient_load_protocol(stats)
        assert compliant is False
        assert detail["median_percent"] == 31.0

    def test_max_over_50_fails(self):
        stats = {"per_core_percent": {"min": 5.0, "median": 25.0, "max": 51.0}}
        compliant, detail = check_ambient_load_protocol(stats)
        assert compliant is False
        assert detail["max_percent"] == 51.0

    def test_unavailable_load_stats_fails(self):
        compliant, detail = check_ambient_load_protocol({})
        assert compliant is False
        assert detail["reason"] == "load_stats_unavailable"

    def test_build_load_protocol_record_bypass_not_canonical(self):
        record = build_load_protocol_record(
            start_compliant=False,
            start_detail={"median_percent": 50.0, "max_percent": 75.0},
            end_compliant=False,
            end_detail={"median_percent": 50.0, "max_percent": 75.0},
            strict=True,
            allow_violation=True,
        )
        assert record["enforced"] is False
        assert record["bypassed"] is True
        assert record["compliant"] is False
        assert record["canonical_evidence"] is False

    def test_build_load_protocol_record_strict_compliant_is_canonical(self):
        record = build_load_protocol_record(
            start_compliant=True,
            start_detail={"median_percent": 10.0, "max_percent": 20.0},
            end_compliant=True,
            end_detail={"median_percent": 10.0, "max_percent": 20.0},
            strict=True,
            allow_violation=False,
        )
        assert record["enforced"] is True
        assert record["bypassed"] is False
        assert record["canonical_evidence"] is True


class TestBaselineSummaryFormula:
    """설계서 6장 중앙값 기준선 산식 및 반복 안정성 판정 검증."""

    def test_median_and_cv_and_mad_deterministic(self):
        results = []
        # T = [100, 110, 120, 130, 140], P = [50, 55, 60, 65, 70]
        for t, p in zip(
            [100.0, 110.0, 120.0, 130.0, 140.0],
            [50.0, 55.0, 60.0, 65.0, 70.0],
            strict=True,
        ):
            results.append(
                {
                    "summary": {
                        "jobs_per_second": t,
                        "total_enqueued": 10,
                        "failed_jobs": 0,
                        "error_count": 0,
                    },
                    "latency_ms": {"p95_ms": p},
                }
            )

        summary = compute_baseline_summary(results)
        assert summary["n_runs"] == 5
        assert summary["throughput"]["median"] == 120.0
        assert summary["p95_ms"]["median"] == 60.0

        import statistics

        t_values = [100.0, 110.0, 120.0, 130.0, 140.0]
        p_values = [50.0, 55.0, 60.0, 65.0, 70.0]
        t_cv = statistics.stdev(t_values) / statistics.fmean(t_values)
        p_cv = statistics.stdev(p_values) / statistics.fmean(p_values)
        assert summary["throughput"]["cv"] == pytest.approx(t_cv)
        assert summary["p95_ms"]["cv"] == pytest.approx(p_cv)
        assert summary["regression_gate"]["rt"] == pytest.approx(max(3 * t_cv, 0.06))
        assert summary["regression_gate"]["rp"] == pytest.approx(max(3 * p_cv, 0.06))

        # MAD/median 검증
        t_med = statistics.median(t_values)
        t_mad = statistics.median([abs(v - t_med) for v in t_values])
        assert summary["throughput"]["mad_median_ratio"] == pytest.approx(t_mad / t_med)

    def test_stability_verdict_records_violation(self):
        # P95 가 크게 흔들려 CV > 0.05 → 기준선 신뢰 불가 판정 기록
        results = [
            {
                "summary": {
                    "jobs_per_second": 100.0,
                    "total_enqueued": 10,
                    "failed_jobs": 0,
                    "error_count": 0,
                },
                "latency_ms": {"p95_ms": 50.0},
            },
            {
                "summary": {
                    "jobs_per_second": 101.0,
                    "total_enqueued": 10,
                    "failed_jobs": 0,
                    "error_count": 0,
                },
                "latency_ms": {"p95_ms": 200.0},
            },
            {
                "summary": {
                    "jobs_per_second": 100.0,
                    "total_enqueued": 10,
                    "failed_jobs": 0,
                    "error_count": 0,
                },
                "latency_ms": {"p95_ms": 51.0},
            },
        ]
        summary = compute_baseline_summary(results)
        assert summary["stability"]["passed"] is False
        assert summary["stability"]["baseline_trustworthy"] is False
        assert summary["stability"]["verdict"] == "unstable_baseline_not_trustworthy"

    def test_stability_verdict_passes_for_low_variation(self):
        results = []
        for i in range(10):
            results.append(
                {
                    "summary": {
                        "jobs_per_second": 100.0 + i * 0.2,
                        "total_enqueued": 10,
                        "failed_jobs": 0,
                        "error_count": 0,
                    },
                    "latency_ms": {"p95_ms": 50.0 + i * 0.1},
                }
            )
        summary = compute_baseline_summary(results)
        assert summary["stability"]["passed"] is True
        assert summary["stability"]["baseline_trustworthy"] is True
        assert summary["stability"]["verdict"] == "stable"

    def test_failure_baseline_records_max_failure(self):
        results = [
            {
                "summary": {
                    "jobs_per_second": 100.0,
                    "total_enqueued": 10,
                    "failed_jobs": 1,
                    "error_count": 1,
                },
                "latency_ms": {"p95_ms": 50.0},
            },
        ]
        summary = compute_baseline_summary(results)
        assert summary["failure"]["max"] == 0.2


class TestProvenanceRequiredFields:
    """provenance 필수 필드 unknown 자동 기각 검증."""

    def _full_provenance(self) -> dict:
        return {
            "host": {
                "python_version": "3.12.14",
                "platform": "Darwin",
                "cpu_count": 8,
                "load_avg_1m": 1.0,
                "memory_total_bytes": 1000,
                "memory_available_bytes": 500,
            },
            "redis": {
                "redis_url": "redis://localhost:6379/0",
                "container_id": "r1",
                "container_name": "redis-test",
                "image": "redis:7-alpine",
                "image_id": "sha256:rimg",
                "server_version": "7.4.9",
                "server_mode": "standalone",
            },
            "arq": {
                "arq_version": "0.28.0",
                "redis_py_version": "5.3.1",
                "benchmark_worker_mode": "in_process",
                "worker_settings_module": "in_process:Worker",
                "worker_functions": ["benchmark_noop_task"],
                "is_synthetic": True,
                "worker_max_jobs": 2,
                "worker_poll_delay": 0.01,
                "worker_job_timeout": 10,
            },
            "docker": {
                "docker_version": "Docker version 29.7.2",
                "worker_container_id": None,
                "worker_container_name": None,
                "worker_image": None,
                "worker_image_id": None,
                "source_mount": "/app",
                "source_git_sha": "sha_test",
                "source_git_dirty": False,
            },
        }

    def test_required_fields_defined(self):
        assert "host.python_version" in PROVENANCE_REQUIRED_FIELDS
        assert "redis.container_id" in PROVENANCE_REQUIRED_FIELDS
        assert "docker.docker_version" in PROVENANCE_REQUIRED_FIELDS
        # 선택 필드(worker_container_*)는 필수 목록에 없어야 한다 (in-process 에서 None 허용)
        assert "docker.worker_container_id" not in PROVENANCE_REQUIRED_FIELDS
        assert "docker.worker_image" not in PROVENANCE_REQUIRED_FIELDS

    def test_unknown_in_required_field_rejected_in_strict(self):
        prov = self._full_provenance()
        prov["redis"]["server_version"] = "unknown"
        bad = provenance_unknown_required_fields(prov)
        assert bad == ["redis.server_version"]
        with pytest.raises(BuildProvenanceError, match=r"redis\.server_version"):
            enforce_provenance_required_fields(prov, strict=True)

    def test_optional_unknown_allowed(self):
        prov = self._full_provenance()
        # 선택 필드는 unknown 허용
        prov["docker"]["worker_image"] = "unknown"
        assert provenance_unknown_required_fields(prov) == []
        enforce_provenance_required_fields(prov, strict=True)

    def test_missing_required_field_rejected(self):
        prov = self._full_provenance()
        prov["arq"].pop("arq_version")
        bad = provenance_unknown_required_fields(prov)
        assert "arq.arq_version" in bad
        with pytest.raises(BuildProvenanceError, match=r"arq\.arq_version"):
            enforce_provenance_required_fields(prov, strict=True)

    def test_non_strict_does_not_raise(self):
        prov = self._full_provenance()
        prov["redis"]["server_version"] = "unknown"
        enforce_provenance_required_fields(prov, strict=False)
