"""
tests/test_benchmark_arq_throughput.py

운영 격리형 Arq 처리량 벤치마크 하네스의 단위 테스트.
Redis 및 외부 자원 없이 격리 실행되며, 큐 고유성, 통계 집계,
에러 처리, 리소스 정리 및 CLI 계약을 검증합니다.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.benchmark_arq_throughput import (
    BenchmarkConfig,
    BenchmarkResult,
    RedisConnectionError,
    aggregate_benchmark_metrics,
    benchmark_noop_task,
    calculate_percentile,
    calculate_percentiles,
    cleanup_benchmark_resources,
    generate_benchmark_queue_name,
    get_arq_version,
    get_docker_version,
    get_redis_py_version,
    inspect_redis_container,
    main,
    parse_args,
)


def test_unique_queue_name_generation():
    names = [generate_benchmark_queue_name() for _ in range(100)]
    assert len(set(names)) == 100
    for name in names:
        assert name.startswith("arq:benchmark:")
        assert name != "arq:queue"


def test_calculate_percentile_empty_and_single():
    assert math.isnan(calculate_percentile([], 50.0))

    single = [42.0]
    assert calculate_percentile(single, 0.0) == 42.0
    assert calculate_percentile(single, 50.0) == 42.0
    assert calculate_percentile(single, 100.0) == 42.0


def test_calculate_percentile_deterministic():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calculate_percentile(values, 0.0) == 10.0
    assert calculate_percentile(values, 50.0) == 30.0
    assert calculate_percentile(values, 100.0) == 50.0
    # 95 percentile with 5 elements (index = 4 * 0.95 = 3.8 -> 40.0 * 0.2 + 50.0 * 0.8 = 48.0)
    assert calculate_percentile(values, 95.0) == 48.0


def test_calculate_percentiles_summary():
    empty_res = calculate_percentiles([])
    assert empty_res["p50_ms"] == 0.0
    assert empty_res["mean_ms"] == 0.0

    values = [10.0, 20.0, 30.0]
    res = calculate_percentiles(values)
    assert res["min_ms"] == 10.0
    assert res["max_ms"] == 30.0
    assert res["mean_ms"] == 20.0
    assert res["p50_ms"] == 20.0
    assert res["p95_ms"] == 29.0
    assert res["p99_ms"] == 29.8


def test_aggregate_benchmark_metrics_success():
    config = BenchmarkConfig(
        queue_name="arq:benchmark:test1234",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.0,
        redis_url="redis://localhost:6379/0",
    )
    collected = [
        {"job_id": f"job-{i}", "latency_ms": 10.0 + i, "success": True, "error": None}
        for i in range(10)
    ]
    result = aggregate_benchmark_metrics(
        config=config,
        collected_results=collected,
        total_duration_sec=0.5,
        git_sha="testhash123",
    )

    assert result.status == "success"
    assert result.summary["total_enqueued"] == 10
    assert result.summary["successful_jobs"] == 10
    assert result.summary["failed_jobs"] == 0
    assert result.summary["error_count"] == 0
    assert result.summary["jobs_per_second"] == 20.0  # 10 / 0.5
    assert result.summary["total_duration_sec"] == 0.5
    assert result.latency_ms["min_ms"] == 10.0
    assert result.latency_ms["max_ms"] == 19.0
    assert result.report() is True

    # JSON 직렬화 검증
    as_dict = result.as_dict()
    serialized = json.dumps(as_dict)
    assert "arq:benchmark:test1234" in serialized
    assert as_dict["git_sha"] == "testhash123"


def test_aggregate_benchmark_metrics_partial_failure():
    config = BenchmarkConfig(
        queue_name="arq:benchmark:testfailure",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.2,
        redis_url="redis://localhost:6379/0",
    )
    collected = [
        {
            "job_id": f"job-{i}",
            "latency_ms": 10.0,
            "success": (i < 8),
            "error": "SimulatedError" if i >= 8 else None,
        }
        for i in range(10)
    ]
    result = aggregate_benchmark_metrics(
        config=config,
        collected_results=collected,
        total_duration_sec=1.0,
        git_sha="testhash123",
    )

    assert result.status == "failed"
    assert result.summary["successful_jobs"] == 8
    assert result.summary["failed_jobs"] == 2
    assert result.summary["error_count"] == 2
    assert result.summary["jobs_per_second"] == 8.0
    assert len(result.errors) == 2
    assert result.report() is False


def test_aggregate_benchmark_metrics_missing_jobs():
    config = BenchmarkConfig(
        queue_name="arq:benchmark:missing",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.0,
        redis_url="redis://localhost:6379/0",
    )
    # 10개 예상 중 7개만 완료된 상황 (타임아웃 등)
    collected = [
        {"job_id": f"job-{i}", "latency_ms": 15.0, "success": True, "error": None} for i in range(7)
    ]
    extra_errors = ["타임아웃 발생"]
    result = aggregate_benchmark_metrics(
        config=config,
        collected_results=collected,
        total_duration_sec=2.0,
        extra_errors=extra_errors,
    )

    assert result.status == "failed"
    assert result.summary["successful_jobs"] == 7
    assert result.summary["failed_jobs"] == 3  # 누락된 3개 포함
    assert result.summary["error_count"] == 4  # 누락 3개 + extra_error 1개
    assert result.report() is False


@pytest.mark.asyncio
async def test_cleanup_benchmark_resources():
    mock_redis = MagicMock()
    mock_redis.scan = AsyncMock(
        side_effect=[
            (1, [b"arq:benchmark:test:extra1"]),
            (0, [b"arq:benchmark:test:extra2"]),
        ]
    )
    mock_redis.delete = AsyncMock(return_value=6)

    queue_name = "arq:benchmark:test"
    job_ids = ["job1", "job2"]

    deleted = await cleanup_benchmark_resources(mock_redis, queue_name, job_ids)

    assert deleted == 6
    assert mock_redis.delete.called
    called_keys = mock_redis.delete.call_args[0]
    # 필수 키들이 삭제 목록에 포함되었는지 확인
    assert queue_name in called_keys
    assert f"{queue_name}:health-check" in called_keys
    assert "arq:job:job1" in called_keys
    assert "arq:result:job2" in called_keys
    assert "arq:benchmark:test:extra1" in called_keys
    assert "arq:benchmark:test:extra2" in called_keys


@pytest.mark.asyncio
async def test_benchmark_noop_task_success():
    results = []
    completion_event = asyncio.Event()
    ctx = {
        "results": results,
        "total_expected": 2,
        "completion_event": completion_event,
    }

    t0 = 100.0
    with patch("time.perf_counter", side_effect=[100.05]):
        out = await benchmark_noop_task(
            ctx=ctx,
            job_id="job-1",
            enqueue_time_perf=t0,
            simulate_delay_sec=0.0,
            should_fail=False,
        )

    assert out["status"] == "success"
    assert out["job_id"] == "job-1"
    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["job_id"] == "job-1"
    assert not completion_event.is_set()

    with patch("time.perf_counter", side_effect=[100.10]):
        await benchmark_noop_task(
            ctx=ctx,
            job_id="job-2",
            enqueue_time_perf=t0,
            simulate_delay_sec=0.0,
            should_fail=False,
        )

    assert len(results) == 2
    assert completion_event.is_set()


@pytest.mark.asyncio
async def test_benchmark_noop_task_failure():
    results = []
    completion_event = asyncio.Event()
    ctx = {
        "results": results,
        "total_expected": 1,
        "completion_event": completion_event,
    }

    t0 = 100.0
    with (
        patch("time.perf_counter", side_effect=[100.05]),
        pytest.raises(RuntimeError, match="Simulated benchmark failure"),
    ):
        await benchmark_noop_task(
            ctx=ctx,
            job_id="job-fail",
            enqueue_time_perf=t0,
            simulate_delay_sec=0.0,
            should_fail=True,
        )

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["job_id"] == "job-fail"
    assert "Simulated benchmark failure" in results[0]["error"]
    assert completion_event.is_set()


def test_cli_argument_parsing():
    args = parse_args(
        [
            "--jobs",
            "200",
            "--concurrency",
            "15",
            "--job-delay-ms",
            "5.5",
            "--poll-delay",
            "0.02",
            "--simulate-error-rate",
            "0.1",
            "--timeout",
            "120.0",
            "--redis-url",
            "redis://example:6379/1",
            "--output",
            "/tmp/out.json",
            "--quiet",
        ]
    )
    assert args.jobs == 200
    assert args.concurrency == 15
    assert args.job_delay_ms == 5.5
    assert args.poll_delay == 0.02
    assert args.simulate_error_rate == 0.1
    assert args.timeout == 120.0
    assert args.redis_url == "redis://example:6379/1"
    assert args.output == Path("/tmp/out.json")
    assert args.quiet is True


def test_main_argument_validation(capsys):
    assert main(["--jobs", "0"]) == 2
    captured = capsys.readouterr()
    assert "--jobs 는 1 이상" in captured.err

    assert main(["--concurrency", "-1"]) == 2
    captured = capsys.readouterr()
    assert "--concurrency 는 1 이상" in captured.err


def test_main_redis_connection_error_fail_fast(capsys):
    with patch(
        "scripts.benchmark_arq_throughput.run_arq_throughput_benchmark",
        side_effect=RedisConnectionError("Connection refused"),
    ):
        code = main(["--jobs", "10"])
        assert code == 2
        captured = capsys.readouterr()
        assert "Redis 연결 오류" in captured.err


def test_main_success_and_json_output(tmp_path, capsys):
    out_file = tmp_path / "result.json"
    dummy_result = BenchmarkResult(
        status="success",
        git_sha="abc1234",
        timestamp="2026-08-22T04:00:00Z",
        environment={
            "python": "3.12.14",
            "platform": "test",
            "redis_url": "redis://localhost:6379/0",
        },
        config=BenchmarkConfig(
            queue_name="arq:benchmark:mock",
            total_jobs=5,
            concurrency=2,
            job_delay_ms=0.0,
            poll_delay_sec=0.01,
            timeout_sec=10.0,
            simulate_error_rate=0.0,
            redis_url="redis://localhost:6379/0",
        ),
        summary={
            "total_duration_sec": 0.1,
            "jobs_per_second": 50.0,
            "total_enqueued": 5,
            "successful_jobs": 5,
            "failed_jobs": 0,
            "error_count": 0,
        },
        latency_ms={
            "p50_ms": 1.0,
            "p95_ms": 2.0,
            "p99_ms": 2.5,
            "min_ms": 0.5,
            "max_ms": 2.5,
            "mean_ms": 1.2,
            "values_ms": [0.5, 1.0, 1.2, 1.8, 2.5],
        },
        errors=[],
    )

    with patch(
        "scripts.benchmark_arq_throughput.run_arq_throughput_benchmark", return_value=dummy_result
    ):
        code = main(["--jobs", "5", "--output", str(out_file)])
        assert code == 0
        assert out_file.exists()
        saved_data = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved_data["status"] == "success"
        assert saved_data["summary"]["jobs_per_second"] == 50.0
        assert saved_data["latency_ms"]["p95_ms"] == 2.0


def test_get_arq_version_returns_string():
    version = get_arq_version()
    assert isinstance(version, str)
    assert version != ""


def test_get_redis_py_version_returns_string():
    version = get_redis_py_version()
    assert isinstance(version, str)
    assert version != ""


def test_get_docker_version_returns_string():
    version = get_docker_version()
    assert isinstance(version, str)
    assert "Docker version" in version


@patch("scripts.benchmark_arq_throughput.subprocess.check_output")
def test_inspect_redis_container_parses_output(mock_check_output):
    mock_check_output.side_effect = [
        '{"ID": "abc123", "Names": "redis-test", "Image": "redis:7-alpine"}',
        '[{"Image": "sha256:abcdef123456", "NetworkSettings": {"Networks": {"test_net": {}}}}]',
    ]

    info = inspect_redis_container()

    assert info["container_id"] == "abc123"
    assert info["container_name"] == "redis-test"
    assert info["image"] == "redis:7-alpine"
    assert info["image_id"] == "sha256:abcdef123456"
    # Verify the calls were made correctly
    assert mock_check_output.call_count == 2
    # First call: docker ps
    args_1 = mock_check_output.call_args_list[0][0][0]
    assert "docker" in args_1[0]
    assert "ps" in args_1
    # Second call: docker inspect
    args_2 = mock_check_output.call_args_list[1][0][0]
    assert "docker" in args_2[0]
    assert "inspect" in args_2
    assert "abc123" in args_2


@patch(
    "scripts.benchmark_arq_throughput.subprocess.check_output",
    side_effect=OSError("docker not found"),
)
def test_inspect_redis_container_handles_error(mock_check_output):
    info = inspect_redis_container()

    assert info["container_id"] == "unknown"
    assert info["container_name"] == "unknown"
    assert info["image"] == "unknown"
    assert info["image_id"] == "unknown"


def test_aggregate_benchmark_metrics_includes_provenance():
    """aggregate_benchmark_metrics 가 4계층 provenance 환경 필드를 포함하는지 검증."""
    config = BenchmarkConfig(
        queue_name="arq:benchmark:test1234",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.0,
        redis_url="redis://localhost:6379/0",
    )
    collected = [
        {"job_id": f"job-{i}", "latency_ms": 10.0 + i, "success": True, "error": None}
        for i in range(10)
    ]

    with (
        patch("scripts.benchmark_arq_throughput.inspect_redis_container") as mock_inspect,
        patch("scripts.benchmark_arq_throughput.get_arq_version", return_value="0.28.0"),
        patch("scripts.benchmark_arq_throughput.get_redis_py_version", return_value="5.3.1"),
        patch(
            "scripts.benchmark_arq_throughput.get_docker_version",
            return_value="Docker version 29.7.2",
        ),
        patch("os.getloadavg", return_value=[1.5, 1.2, 1.0]),
        patch("os.cpu_count", return_value=8),
    ):
        mock_inspect.return_value = {
            "container_id": "redis-container-123",
            "container_name": "redis-test",
            "image": "redis:7-alpine",
            "image_id": "sha256:abc123",
        }

        result = aggregate_benchmark_metrics(
            config=config,
            collected_results=collected,
            total_duration_sec=0.5,
            git_sha="testhash123",
        )

    env = result.environment

    # 1. Host 계층
    assert "host_cpu_count" in env
    assert env["host_cpu_count"] == 8
    assert "host_load_avg_1m" in env
    assert env["host_load_avg_1m"] == 1.5
    assert "python" in env
    assert "platform" in env

    # 2. Redis 계층
    assert "redis_container_id" in env
    assert env["redis_container_id"] == "redis-container-123"
    assert "redis_image" in env
    assert env["redis_image"] == "redis:7-alpine"
    assert "redis_url" in env

    # 3. Arq 계층
    assert "arq_version" in env
    assert env["arq_version"] == "0.28.0"
    assert "redis_py_version" in env
    assert env["redis_py_version"] == "5.3.1"
    assert "worker_max_jobs" in env
    assert env["worker_max_jobs"] == 2
    assert "worker_poll_delay" in env
    assert env["worker_poll_delay"] == 0.01

    # 4. Docker 계층
    assert "docker_version" in env
    assert env["docker_version"] == "Docker version 29.7.2"

    # benchmark_worker_mode 필드 확인
    assert result.benchmark_worker_mode == "in_process"
    as_dict = result.as_dict()
    assert as_dict["benchmark_worker_mode"] == "in_process"


def test_aggregate_benchmark_metrics_provenance_keys_match_container_harness():
    """in-process 하네스의 environment 키가 container 하네스와 일치하는지 검증 (benchmark_worker_mode 제외)."""
    config = BenchmarkConfig(
        queue_name="arq:benchmark:test1234",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.0,
        redis_url="redis://localhost:6379/0",
    )
    collected = [
        {"job_id": f"job-{i}", "latency_ms": 10.0 + i, "success": True, "error": None}
        for i in range(10)
    ]

    with (
        patch("scripts.benchmark_arq_throughput.inspect_redis_container") as mock_inspect,
        patch("scripts.benchmark_arq_throughput.get_arq_version", return_value="0.28.0"),
        patch("scripts.benchmark_arq_throughput.get_redis_py_version", return_value="5.3.1"),
        patch(
            "scripts.benchmark_arq_throughput.get_docker_version",
            return_value="Docker version 29.7.2",
        ),
        patch("os.getloadavg", return_value=[1.5, 1.2, 1.0]),
        patch("os.cpu_count", return_value=8),
    ):
        mock_inspect.return_value = {
            "container_id": "redis-container-123",
            "container_name": "redis-test",
            "image": "redis:7-alpine",
            "image_id": "sha256:abc123",
        }

        result = aggregate_benchmark_metrics(
            config=config,
            collected_results=collected,
            total_duration_sec=0.5,
            git_sha="testhash123",
        )

    env_keys = set(result.environment.keys())

    # container benchmark_arq_container.py 에서 사용하는 키들
    expected_host_redis_arq_docker_keys = {
        "python",
        "platform",
        "host_cpu_count",
        "host_load_avg_1m",
        "host_memory_total_bytes",
        "host_memory_available_bytes",
        "redis_url",
        "redis_container_id",
        "redis_container_name",
        "redis_image",
        "redis_image_id",
        "redis_server_version",
        "redis_server_mode",
        "arq_version",
        "redis_py_version",
        "benchmark_worker_mode",
        "worker_settings_module",
        "worker_functions",
        "is_synthetic",
        "worker_max_jobs",
        "worker_poll_delay",
        "worker_job_timeout",
        "docker_version",
        "source_mount",
        "source_git_sha",
        "source_git_dirty",
    }

    assert expected_host_redis_arq_docker_keys.issubset(env_keys)
    assert "benchmark_worker_mode" in result.as_dict()
    assert "provenance" in result.as_dict()

    # 4계층 provenance 구조 검증
    prov = result.provenance
    assert set(prov.keys()) == {"host", "redis", "arq", "docker"}
    assert set(prov["host"].keys()) == {
        "python_version",
        "platform",
        "cpu_count",
        "load_avg_1m",
        "memory_total_bytes",
        "memory_available_bytes",
    }
    assert set(prov["redis"].keys()) == {
        "redis_url",
        "container_id",
        "container_name",
        "image",
        "image_id",
        "server_version",
        "server_mode",
    }
    assert set(prov["arq"].keys()) == {
        "arq_version",
        "redis_py_version",
        "benchmark_worker_mode",
        "worker_settings_module",
        "worker_functions",
        "is_synthetic",
        "worker_max_jobs",
        "worker_poll_delay",
        "worker_job_timeout",
    }
    assert set(prov["docker"].keys()) == {
        "docker_version",
        "worker_container_id",
        "worker_container_name",
        "worker_image",
        "worker_image_id",
        "source_mount",
        "source_git_sha",
        "source_git_dirty",
    }


def test_get_host_memory_returns_structure():
    """get_host_memory 가 total_bytes, available_bytes 키를 갖는 dict를 반환하는지 검증."""
    from scripts.benchmark_arq_throughput import get_host_memory

    mem = get_host_memory()
    assert isinstance(mem, dict)
    assert "total_bytes" in mem
    assert "available_bytes" in mem


def test_get_git_status_clean_and_dirty(tmp_path):
    """get_git_status 가 clean 및 dirty 상태를 정확히 판별하는지 검증."""
    from scripts.benchmark_arq_throughput import get_git_status

    with patch("scripts.benchmark_arq_throughput.subprocess.check_output") as mock_out:
        # 1. Clean git repo
        mock_out.side_effect = ["sha123456", ""]
        sha, dirty = get_git_status(tmp_path)
        assert sha == "sha123456"
        assert dirty is False

        # 2. Dirty git repo
        mock_out.side_effect = ["sha123456", " M some_file.py\n?? new_file.py"]
        sha, dirty = get_git_status(tmp_path)
        assert sha == "sha123456"
        assert dirty is True

        # 3. Git error
        mock_out.side_effect = [OSError("git not found"), OSError("git not found")]
        sha, dirty = get_git_status(tmp_path)
        assert sha == "unknown"
        assert dirty is None


@pytest.mark.asyncio
async def test_fetch_redis_server_info_parsing():
    """fetch_redis_server_info 가 INFO server 결과를 올바르게 파싱하는지 검증."""
    from scripts.benchmark_arq_throughput import fetch_redis_server_info

    mock_redis = MagicMock()
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.4.9", "redis_mode": "standalone"})

    info = await fetch_redis_server_info(mock_redis)
    assert info["server_version"] == "7.4.9"
    assert info["server_mode"] == "standalone"


def test_verify_identity_consistency():
    """verify_identity_consistency 가 일치 및 불일치(교체/재시작)를 정확히 판정하는지 검증."""
    from scripts.benchmark_arq_throughput import BuildProvenanceError, verify_identity_consistency

    start_ident = {
        "redis_container_id": "c123",
        "redis_image_id": "img123",
        "redis_server_version": "7.4.9",
        "redis_server_mode": "standalone",
        "source_mount": "/app",
        "source_git_sha": "sha123",
        "source_git_dirty": False,
    }

    # 1. 완벽 일치
    assert verify_identity_consistency(start_ident, dict(start_ident), strict=True) is True

    # 2. Redis 컨테이너 교체
    end_ident = dict(start_ident)
    end_ident["redis_container_id"] = "c999"
    with pytest.raises(BuildProvenanceError, match="redis_container_id changed"):
        verify_identity_consistency(start_ident, end_ident, strict=True)

    assert verify_identity_consistency(start_ident, end_ident, strict=False) is False

    # 3. Git dirty 변경
    end_ident2 = dict(start_ident)
    end_ident2["source_git_dirty"] = True
    with pytest.raises(BuildProvenanceError, match="source_git_dirty changed"):
        verify_identity_consistency(start_ident, end_ident2, strict=True)


def test_main_repetitions_preserves_all_raw_files(tmp_path):
    """repetitions=3 실행 시 _r1, _r2, _r3 파일과 대표 결과가 모두 생성되고 성공하는지 검증."""
    out_file = tmp_path / "measure.json"

    def make_dummy_result(run_idx: int, p95: float) -> BenchmarkResult:
        config = BenchmarkConfig(
            queue_name=f"arq:benchmark:r{run_idx}",
            total_jobs=5,
            concurrency=2,
            job_delay_ms=0.0,
            poll_delay_sec=0.01,
            timeout_sec=10.0,
            simulate_error_rate=0.0,
            redis_url="redis://localhost:6379/0",
        )
        return BenchmarkResult(
            status="success",
            git_sha="sha123",
            timestamp="2026-08-24T00:00:00Z",
            environment={"python": "3.12.14"},
            config=config,
            summary={
                "total_duration_sec": 0.1,
                "jobs_per_second": 50.0,
                "total_enqueued": 5,
                "successful_jobs": 5,
                "failed_jobs": 0,
                "error_count": 0,
            },
            latency_ms={
                "p50_ms": 1.0,
                "p95_ms": p95,
                "p99_ms": 2.0,
                "min_ms": 0.5,
                "max_ms": 2.0,
                "mean_ms": 1.0,
                "values_ms": [1.0, 1.0, 1.0, 1.0, 1.0],
            },
            errors=[],
            provenance={"host": {}, "redis": {}, "arq": {}, "docker": {}},
        )

    results_seq = [
        make_dummy_result(1, 10.0),
        make_dummy_result(2, 25.0),  # 최악 P95 대표
        make_dummy_result(3, 15.0),
    ]

    with patch(
        "scripts.benchmark_arq_throughput.run_arq_throughput_benchmark",
        side_effect=results_seq,
    ):
        code = main(
            [
                "--jobs",
                "5",
                "--repetitions",
                "3",
                "--run-interval-sec",
                "0",
                "--output",
                str(out_file),
                "--allow-unknown-provenance",
            ]
        )
        assert code == 0

        # _r1, _r2, _r3 파일이 모두 생성되었는지 확인
        r1_path = tmp_path / "measure_r1.json"
        r2_path = tmp_path / "measure_r2.json"
        r3_path = tmp_path / "measure_r3.json"
        assert r1_path.exists()
        assert r2_path.exists()
        assert r3_path.exists()
        assert out_file.exists()

        # 대표 결과가 worst P95 (25.0ms)인지 확인
        saved_worst = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved_worst["latency_ms"]["p95_ms"] == 25.0


def test_main_repetitions_fails_closed_if_single_run_fails(tmp_path):
    """repetitions=3 중 1회차라도 실패하면 최종 결과가 실패(exit code 1)하고 fail-closed인지 검증."""
    out_file = tmp_path / "measure_fail.json"

    def make_dummy_result(status: str, error_count: int) -> BenchmarkResult:
        config = BenchmarkConfig(
            queue_name="arq:benchmark:mock",
            total_jobs=5,
            concurrency=2,
            job_delay_ms=0.0,
            poll_delay_sec=0.01,
            timeout_sec=10.0,
            simulate_error_rate=0.0,
            redis_url="redis://localhost:6379/0",
        )
        return BenchmarkResult(
            status=status,
            git_sha="sha123",
            timestamp="2026-08-24T00:00:00Z",
            environment={"python": "3.12.14"},
            config=config,
            summary={
                "total_duration_sec": 0.1,
                "jobs_per_second": 50.0,
                "total_enqueued": 5,
                "successful_jobs": 5 - error_count,
                "failed_jobs": error_count,
                "error_count": error_count,
            },
            latency_ms={"p50_ms": 1.0, "p95_ms": 1.0, "p99_ms": 1.0, "values_ms": [1.0]},
            errors=["Simulated error"] if error_count > 0 else [],
            provenance={"host": {}, "redis": {}, "arq": {}, "docker": {}},
        )

    results_seq = [
        make_dummy_result("success", 0),
        make_dummy_result("failed", 1),  # 2회차 실패
        make_dummy_result("success", 0),
    ]

    with patch(
        "scripts.benchmark_arq_throughput.run_arq_throughput_benchmark",
        side_effect=results_seq,
    ):
        code = main(
            [
                "--jobs",
                "5",
                "--repetitions",
                "3",
                "--run-interval-sec",
                "0",
                "--output",
                str(out_file),
                "--allow-unknown-provenance",
            ]
        )
        assert code == 1
