"""
tests/test_benchmark_arq_container.py

실제 Docker 컨테이너 Arq 워커 처리량 및 지연 벤치마크 하네스의 단위 테스트.
컨테이너 수명주기, 호스트 소스 바인드 마운트 무결성, Git SHA/dirty 검증,
시작-종료 identity 일치성 검증, 합성 vs 운영 워커 메타데이터 구분,
반복 회차 raw 보존 계약 및 공통 Provenance 스키마 정합성을 검증합니다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.benchmark_arq_container import (
    BenchmarkResult,
    BuildProvenanceError,
    ContainerBenchmarkConfig,
    ContainerLifecycleError,
    DockerWorkerContainerManager,
    generate_benchmark_queue_name,
    inspect_image_id,
    main,
    run_container_worker_benchmark,
    verify_identity_consistency,
)
from scripts.benchmark_arq_throughput import (
    BenchmarkConfig as InProcessConfig,
)
from scripts.benchmark_arq_throughput import (
    aggregate_benchmark_metrics as inprocess_aggregate,
)


def test_unique_container_benchmark_queue_name():
    names = [generate_benchmark_queue_name("arq:container-bench") for _ in range(100)]
    assert len(set(names)) == 100
    for name in names:
        assert name.startswith("arq:container-bench:")
        assert name != "arq:queue"


def test_docker_worker_container_manager_lifecycle():
    mgr = DockerWorkerContainerManager(
        image="refac_bid_box-worker:latest",
        network="test-net",
        queue_name="arq:container-bench:test1234",
        concurrency=4,
        poll_delay_sec=0.01,
        container_redis_url="redis://redis:6379/0",
        source_mount="/test/app",
    )

    with patch("scripts.benchmark_arq_container.subprocess.check_output") as mock_out:
        mock_out.side_effect = [
            "cid123456789012\n",  # docker run
            '[{"Destination": "/app", "Source": "/test/app"}]',  # docker inspect mounts
        ]
        cid = mgr.start()
        assert cid == "cid123456789012"
        assert mgr.container_id == "cid123456789012"
        assert mgr.mounted_source == "/test/app"

    # wait_ready success
    with patch("scripts.benchmark_arq_container.subprocess.check_output") as mock_logs:
        mock_logs.return_value = "Starting worker for 1 functions\n"
        assert mgr.wait_ready(timeout_sec=1.0) is True

    # stop_and_remove
    with patch("scripts.benchmark_arq_container.subprocess.run") as mock_run:
        mgr.stop_and_remove()
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "rm" in args
        assert "-f" in args
        assert mgr.container_name in args


def test_docker_worker_container_manager_wait_ready_timeout():
    mgr = DockerWorkerContainerManager(
        image="refac_bid_box-worker:latest",
        network="test-net",
        queue_name="arq:container-bench:test1234",
    )
    with (
        patch(
            "scripts.benchmark_arq_container.subprocess.check_output",
            return_value="Some other log output",
        ),
        pytest.raises(ContainerLifecycleError, match="준비 상태에 도달하지 못했습니다"),
    ):
        mgr.wait_ready(timeout_sec=0.2)


def test_inspect_image_id_success_and_error():
    with patch(
        "scripts.benchmark_arq_container.subprocess.check_output",
        return_value="sha256:d88574a908269e84",
    ):
        img_id = inspect_image_id("refac_bid_box-worker:latest")
        assert img_id == "sha256:d88574a908269e84"

    with patch(
        "scripts.benchmark_arq_container.subprocess.check_output",
        side_effect=OSError("docker error"),
    ):
        img_id = inspect_image_id("refac_bid_box-worker:latest")
        assert img_id == "unknown"


def test_verify_identity_consistency_container_mismatch():
    start_ident = {
        "worker_container_id": "cid_001",
        "worker_image_id": "sha256:img1",
        "redis_container_id": "redis_001",
        "redis_image_id": "sha256:redis1",
        "redis_server_version": "7.4.9",
        "redis_server_mode": "standalone",
        "source_mount": "/app",
        "source_git_sha": "sha_aaa",
        "source_git_dirty": False,
    }

    # 1. 일치
    assert verify_identity_consistency(start_ident, dict(start_ident), strict=True) is True

    # 2. Worker Container 교체 감지
    end_ident = dict(start_ident)
    end_ident["worker_container_id"] = "cid_002"
    with pytest.raises(BuildProvenanceError, match="worker_container_id changed"):
        verify_identity_consistency(start_ident, end_ident, strict=True)

    # 3. Source Git SHA 변경 감지
    end_ident2 = dict(start_ident)
    end_ident2["source_git_sha"] = "sha_bbb"
    with pytest.raises(BuildProvenanceError, match="source_git_sha changed"):
        verify_identity_consistency(start_ident, end_ident2, strict=True)


@pytest.mark.asyncio
async def test_run_container_worker_benchmark_strict_fail_on_dirty(tmp_path):
    """strict 모드에서 Git dirty 상태일 경우 측정을 즉시 거부(fail-closed)하는지 검증."""
    with (
        patch("scripts.benchmark_arq_container.get_git_status", return_value=("sha123", True)),
        pytest.raises(BuildProvenanceError, match="Host/Git provenance check failed"),
    ):
        await run_container_worker_benchmark(
            total_jobs=10,
            concurrency=2,
            strict=True,
            source_mount=tmp_path,
        )


@pytest.mark.asyncio
async def test_run_container_worker_benchmark_mocked_success(tmp_path):
    """모킹된 컨테이너 및 Redis 환경에서 run_container_worker_benchmark 정상 실행 및 스키마 검증."""
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.4.9", "redis_mode": "standalone"})
    mock_redis.enqueue_job = AsyncMock(return_value=None)
    mock_redis.scan = AsyncMock(return_value=(0, []))
    mock_redis.delete = AsyncMock(return_value=0)
    mock_redis.aclose = AsyncMock(return_value=None)

    # done 큐 팝 응답 모킹
    done_payload = json.dumps({"job_id": "cntr-test-0", "success": True, "error": None}).encode(
        "utf-8"
    )
    mock_redis.blpop = AsyncMock(side_effect=[("done_key", done_payload), None])
    mock_redis.lpop = AsyncMock(return_value=[])

    with (
        patch("scripts.benchmark_arq_container.create_pool", return_value=mock_redis),
        patch("scripts.benchmark_arq_container.get_git_status", return_value=("sha123456", False)),
        patch(
            "scripts.benchmark_arq_container.inspect_redis_container",
            return_value={
                "container_id": "redis_cid",
                "container_name": "redis_test",
                "image": "redis:7-alpine",
                "image_id": "sha256:redisimg",
                "network": "test_net",
            },
        ),
        patch(
            "scripts.benchmark_arq_container.inspect_image_id",
            return_value="sha256:workerimg",
        ),
        patch.object(DockerWorkerContainerManager, "start", return_value="worker_cid_123"),
        patch.object(DockerWorkerContainerManager, "wait_ready", return_value=True),
        patch.object(DockerWorkerContainerManager, "stop_and_remove", return_value=None),
    ):
        result = await run_container_worker_benchmark(
            total_jobs=1,
            concurrency=1,
            strict=False,
            source_mount=tmp_path,
        )

        assert result.status == "success"
        assert result.benchmark_worker_mode == "docker_container"
        assert result.summary["total_enqueued"] == 1
        assert result.summary["successful_jobs"] == 1
        assert result.summary["failed_jobs"] == 0

        # Provenance 검증
        prov = result.provenance
        assert prov["arq"]["benchmark_worker_mode"] == "docker_container"
        assert (
            prov["arq"]["worker_settings_module"] == "scripts._bench_worker_settings.WorkerSettings"
        )
        assert prov["arq"]["is_synthetic"] is True
        assert prov["docker"]["worker_container_id"] == "worker_cid_123"
        assert prov["redis"]["server_version"] == "7.4.9"


def test_synthetic_vs_production_worker_settings_labeling():
    """synthetic benchmark WorkerSettings 와 production WorkerSettings 의 명확한 구분 검증."""
    from scripts._bench_worker_settings import WorkerSettings as BenchWorkerSettings
    from src.tasks.worker import WorkerSettings as ProdWorkerSettings

    # Benchmark WorkerSettings
    assert BenchWorkerSettings.is_synthetic is True
    assert BenchWorkerSettings.benchmark_worker_mode == "docker_container"
    assert (
        BenchWorkerSettings.worker_settings_module
        == "scripts._bench_worker_settings.WorkerSettings"
    )
    assert len(BenchWorkerSettings.functions) == 1
    assert BenchWorkerSettings.functions[0].__name__ == "benchmark_noop_task"

    # Production WorkerSettings (실제 비즈니스 태스크)
    assert len(ProdWorkerSettings.functions) >= 5
    func_names = [f.__name__ for f in ProdWorkerSettings.functions]
    assert "preflight_check_task" in func_names
    assert "collect_bids_task" in func_names
    assert "benchmark_noop_task" not in func_names


def test_provenance_schema_equality_between_inprocess_and_container():
    """in-process 와 container 하네스가 완전히 동일한 4계층 provenance 카테고리와 키 세트를 가지는지 검증."""
    # 1. In-process provenance 생성
    inproc_config = InProcessConfig(
        queue_name="arq:benchmark:inproc",
        total_jobs=10,
        concurrency=2,
        job_delay_ms=0.0,
        poll_delay_sec=0.01,
        timeout_sec=10.0,
        simulate_error_rate=0.0,
        redis_url="redis://localhost:6379/0",
    )
    inproc_res = inprocess_aggregate(
        config=inproc_config,
        collected_results=[
            {"job_id": f"j{i}", "latency_ms": 10.0, "success": True, "error": None}
            for i in range(10)
        ],
        total_duration_sec=0.5,
        git_sha="sha_test",
        redis_server_version="7.4.9",
        redis_server_mode="standalone",
    )

    # 2. Container provenance 생성 (더미 객체)
    from scripts.benchmark_arq_container import build_provenance_dict

    container_prov = build_provenance_dict(
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
        benchmark_worker_mode="docker_container",
        worker_settings_module="scripts._bench_worker_settings.WorkerSettings",
        worker_functions=["benchmark_noop_task"],
        is_synthetic=True,
        worker_max_jobs=4,
        worker_poll_delay=0.01,
        worker_job_timeout=60,
        docker_version="Docker version 29.7.2",
        worker_container_id="wcid",
        worker_container_name="wname",
        worker_image="refac_bid_box-worker:latest",
        worker_image_id="sha256:wimg",
        source_mount="/app",
        source_git_sha="sha_test",
        source_git_dirty=False,
    )

    inproc_prov = inproc_res.provenance

    # Top-level 카테고리 일치 확인
    assert set(inproc_prov.keys()) == {"host", "redis", "arq", "docker"}
    assert set(container_prov.keys()) == {"host", "redis", "arq", "docker"}

    # 각 서브 카테고리의 모든 키 세트 100% 동일 확인
    assert set(inproc_prov["host"].keys()) == set(container_prov["host"].keys())
    assert set(inproc_prov["redis"].keys()) == set(container_prov["redis"].keys())
    assert set(inproc_prov["arq"].keys()) == set(container_prov["arq"].keys())
    assert set(inproc_prov["docker"].keys()) == set(container_prov["docker"].keys())


def test_container_main_repetitions_preserves_raw_files(tmp_path):
    """container 하네스의 main repetitions=3 계약 검증 (_r1, _r2, _r3, representative)."""
    out_file = tmp_path / "cntr_measure.json"

    def make_dummy_result(run_idx: int, p95: float) -> BenchmarkResult:
        config = ContainerBenchmarkConfig(
            queue_name=f"arq:container-bench:r{run_idx}",
            total_jobs=5,
            concurrency=4,
            job_delay_ms=0.0,
            poll_delay_sec=0.01,
            timeout_sec=10.0,
            simulate_error_rate=0.0,
            redis_url="redis://localhost:6379/0",
            container_image="refac_bid_box-worker:latest",
            container_network="default",
            source_mount=str(tmp_path),
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
            latency_ms={"p50_ms": 1.0, "p95_ms": p95, "p99_ms": 2.0, "values_ms": [1.0]},
            errors=[],
            benchmark_worker_mode="docker_container",
            provenance={"host": {}, "redis": {}, "arq": {}, "docker": {}},
        )

    results_seq = [
        make_dummy_result(1, 10.0),
        make_dummy_result(2, 30.0),  # 최악 대표
        make_dummy_result(3, 20.0),
    ]

    with patch(
        "scripts.benchmark_arq_container.run_container_worker_benchmark",
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

        assert (tmp_path / "cntr_measure_r1.json").exists()
        assert (tmp_path / "cntr_measure_r2.json").exists()
        assert (tmp_path / "cntr_measure_r3.json").exists()
        assert out_file.exists()

        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["latency_ms"]["p95_ms"] == 30.0
