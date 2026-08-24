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
    BuildProvenanceError,
    HostLoadMonitor,
    _command_output,
    _parse_container_command,
    _parse_effective_workers,
    compute_host_load_stats,
    host_load_metadata,
    reproducibility_metadata,
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
