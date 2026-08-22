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
