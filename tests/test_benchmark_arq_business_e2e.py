"""
tests/test_benchmark_arq_business_e2e.py

scripts/benchmark_arq_business_e2e.py 의 단위 테스트.

본 테스트는 Redis 나 Docker 없이 돌아야 한다. 다음을 고정한다.

  (a) 허용 목록 밖 task 이름을 거부하는지
  (b) 데이터 변경 task 이름(collect_bids_task, update_kb_task,
      manual_retrain_task, refresh_data_task, manual_full_task,
      run_retrain_pipeline_task, development_data_refresh_task)이
      각각 거부되는지
  (c) 결과가 0건이면 실패 종료 코드인지
  (d) 실패 회차가 있으면 실패 종료 코드인지
  (e) 지연 백분위 계산이 맞는지
  (f) 격리 큐 이름이 운영 큐 이름과 다른지
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_arq_business_e2e import (
    ALLOWED_BUSINESS_TASKS,
    MUTATING_BUSINESS_TASKS,
    PRODUCTION_QUEUE_NAME,
    BenchmarkArgumentError,
    BusinessE2EConfig,
    aggregate_repetitions,
    aggregate_task_metrics,
    assert_queue_isolation,
    build_arg_parser,
    build_business_e2e_config,
    build_business_e2e_result,
    calculate_latency_percentiles,
    calculate_percentile,
    generate_business_e2e_queue_name,
    main,
    parse_args,
    should_exit_nonzero,
    validate_requested_tasks,
)

# (f) 격리 큐 이름이 운영 큐 이름과 다른지 ---------------------------------


def test_production_queue_constant_value():
    assert PRODUCTION_QUEUE_NAME == "arq:queue"


def test_generate_business_e2e_queue_name_is_unique():
    names = [generate_business_e2e_queue_name() for _ in range(200)]
    assert len(set(names)) == 200
    for name in names:
        assert name.startswith("arq:benchmark:business-e2e:")
        assert name != PRODUCTION_QUEUE_NAME
        assert PRODUCTION_QUEUE_NAME not in name


def test_assert_queue_isolation_blocks_production_queue():
    with pytest.raises(BenchmarkArgumentError, match="격리 큐 이름이 운영 큐"):
        assert_queue_isolation(PRODUCTION_QUEUE_NAME)


def test_assert_queue_isolation_blocks_empty_name():
    with pytest.raises(BenchmarkArgumentError, match="비어"):
        assert_queue_isolation("")


def test_assert_queue_isolation_passes_for_isolated_queue():
    name = generate_business_e2e_queue_name()
    assert_queue_isolation(name)  # 예외 없이 통과해야 함


# (a) 허용 목록 밖 task 거부 -------------------------------------------------


def test_validate_requested_tasks_accepts_allowed_list():
    validated = validate_requested_tasks(["preflight_check_task", "validate_model_task"])
    assert validated == ["preflight_check_task", "validate_model_task"]


def test_validate_requested_tasks_dedupes_preserving_order():
    validated = validate_requested_tasks(
        ["validate_model_task", "preflight_check_task", "validate_model_task"]
    )
    assert validated == ["validate_model_task", "preflight_check_task"]


def test_validate_requested_tasks_rejects_unknown_task():
    with pytest.raises(BenchmarkArgumentError, match="허용되지 않은 task"):
        validate_requested_tasks(["preflight_check_task", "unknown_task"])


def test_validate_requested_tasks_rejects_empty_list():
    with pytest.raises(BenchmarkArgumentError, match="최소 1개"):
        validate_requested_tasks([])


# (b) 데이터 변경 task 들이 각각 거부되는지 ----------------------------------


@pytest.mark.parametrize(
    "mutating_name",
    sorted(MUTATING_BUSINESS_TASKS),
)
def test_validate_requested_tasks_rejects_mutating_tasks(mutating_name: str):
    assert mutating_name not in ALLOWED_BUSINESS_TASKS
    with pytest.raises(BenchmarkArgumentError, match="허용되지 않은 task"):
        validate_requested_tasks(["preflight_check_task", mutating_name])


def test_mutating_tasks_constant_matches_known_data_movers():
    expected = {
        "collect_bids_task",
        "update_kb_task",
        "manual_retrain_task",
        "refresh_data_task",
        "manual_full_task",
        "run_retrain_pipeline_task",
        "development_data_refresh_task",
    }
    assert expected == MUTATING_BUSINESS_TASKS


def test_allowed_list_excludes_every_mutating_task():
    """허용 화이트리스트가 mutating 집합과 직교한다."""
    assert set(ALLOWED_BUSINESS_TASKS).isdisjoint(MUTATING_BUSINESS_TASKS)


# (e) 지연 백분위 계산 -------------------------------------------------------


def test_calculate_percentile_empty_returns_nan():
    assert math.isnan(calculate_percentile([], 50.0))


def test_calculate_percentile_single_value():
    assert calculate_percentile([42.0], 0.0) == 42.0
    assert calculate_percentile([42.0], 50.0) == 42.0
    assert calculate_percentile([42.0], 100.0) == 42.0


def test_calculate_percentile_deterministic():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calculate_percentile(values, 0.0) == 10.0
    assert calculate_percentile(values, 50.0) == 30.0
    assert calculate_percentile(values, 100.0) == 50.0
    # 인덱스 = 4 * 0.95 = 3.8 -> 보간 = 40 * 0.2 + 50 * 0.8 = 48.0
    assert calculate_percentile(values, 95.0) == 48.0


def test_calculate_latency_percentiles_empty():
    res = calculate_latency_percentiles([])
    assert res["p50_ms"] == 0.0
    assert res["p95_ms"] == 0.0
    assert res["min_ms"] == 0.0
    assert res["max_ms"] == 0.0
    assert res["mean_ms"] == 0.0


def test_calculate_latency_percentiles_matches_throughput_convention():
    values = [10.0, 20.0, 30.0]
    res = calculate_latency_percentiles(values)
    assert res["min_ms"] == 10.0
    assert res["max_ms"] == 30.0
    assert res["mean_ms"] == 20.0
    assert res["p50_ms"] == 20.0
    assert res["p95_ms"] == 29.0
    assert res["p99_ms"] == 29.8


# aggregate_task_metrics / build_business_e2e_result ------------------------


def test_aggregate_task_metrics_basic():
    slot = aggregate_task_metrics(
        "validate_model_task",
        latencies_ms=[10.0, 20.0, 30.0],
        successes=3,
        failures=0,
        missing=0,
    )
    assert slot["task"] == "validate_model_task"
    assert slot["enqueued"] == 3
    assert slot["successful"] == 3
    assert slot["failed"] == 0
    assert slot["missing"] == 0
    assert slot["latency_ms"]["p50_ms"] == 20.0


def test_build_business_e2e_result_empty_results_is_failed():
    result = build_business_e2e_result(
        queue_name=generate_business_e2e_queue_name(),
        repetitions=1,
        jobs_per_repetition=5,
        task_names=["preflight_check_task"],
        per_task={
            "preflight_check_task": {
                "latencies_ms": [],
                "successes": 0,
                "failures": 0,
                "missing": 0,
            }
        },
        timeout_sec=10.0,
    )
    assert result["status"] == "failed"
    assert result["summary"]["total_enqueued"] == 0
    assert any("0건" in err for err in result["errors"])
    assert result["is_synthetic"] is False
    assert result["isolated_queue"] != PRODUCTION_QUEUE_NAME


def test_build_business_e2e_result_failure_marks_failed_status():
    queue = generate_business_e2e_queue_name()
    result = build_business_e2e_result(
        queue_name=queue,
        repetitions=1,
        jobs_per_repetition=3,
        task_names=["preflight_check_task", "validate_model_task"],
        per_task={
            "preflight_check_task": {
                "latencies_ms": [10.0, 12.0, 11.0],
                "successes": 3,
                "failures": 0,
                "missing": 0,
            },
            "validate_model_task": {
                "latencies_ms": [20.0, 22.0],
                "successes": 1,
                "failures": 1,
                "missing": 1,
            },
        },
        timeout_sec=10.0,
    )
    assert result["status"] == "failed"
    assert result["summary"]["total_enqueued"] == 6
    assert result["summary"]["successful"] == 4
    assert result["summary"]["failed"] == 1
    assert result["summary"]["missing"] == 1
    assert result["summary"]["error_count"] >= 2
    assert any("누락" in err for err in result["errors"])
    assert any(task["task"] == "validate_model_task" for task in result["per_task"])


def test_build_business_e2e_result_clean_status_is_success():
    queue = generate_business_e2e_queue_name()
    result = build_business_e2e_result(
        queue_name=queue,
        repetitions=1,
        jobs_per_repetition=2,
        task_names=list(ALLOWED_BUSINESS_TASKS),
        per_task={
            "preflight_check_task": {
                "latencies_ms": [5.0, 6.0],
                "successes": 2,
                "failures": 0,
                "missing": 0,
            },
            "validate_model_task": {
                "latencies_ms": [12.0, 14.0],
                "successes": 2,
                "failures": 0,
                "missing": 0,
            },
        },
        timeout_sec=10.0,
    )
    assert result["status"] == "success"
    assert result["summary"]["total_enqueued"] == 4
    assert result["summary"]["failed"] == 0
    assert result["summary"]["missing"] == 0
    assert result["summary"]["error_count"] == 0
    assert result["latency_ms"]["p50_ms"] > 0
    assert result["is_synthetic"] is False
    assert result["target_tasks"] == list(ALLOWED_BUSINESS_TASKS)


def test_build_business_e2e_result_rejects_production_queue():
    with pytest.raises(BenchmarkArgumentError, match="운영 큐"):
        build_business_e2e_result(
            queue_name=PRODUCTION_QUEUE_NAME,
            repetitions=1,
            jobs_per_repetition=1,
            task_names=["preflight_check_task"],
            per_task={},
            timeout_sec=10.0,
        )


# (c) (d) 종료 코드 결정 -----------------------------------------------------


def test_should_exit_nonzero_on_empty_results():
    result = build_business_e2e_result(
        queue_name=generate_business_e2e_queue_name(),
        repetitions=1,
        jobs_per_repetition=1,
        task_names=["preflight_check_task"],
        per_task={},
        timeout_sec=10.0,
    )
    assert should_exit_nonzero(result) is True


def test_should_exit_nonzero_on_failure_round():
    result = build_business_e2e_result(
        queue_name=generate_business_e2e_queue_name(),
        repetitions=1,
        jobs_per_repetition=3,
        task_names=["preflight_check_task"],
        per_task={
            "preflight_check_task": {
                "latencies_ms": [10.0, 11.0],
                "successes": 2,
                "failures": 1,
                "missing": 0,
            }
        },
        timeout_sec=10.0,
    )
    assert should_exit_nonzero(result) is True


def test_should_exit_nonzero_on_missing_round():
    result = build_business_e2e_result(
        queue_name=generate_business_e2e_queue_name(),
        repetitions=1,
        jobs_per_repetition=3,
        task_names=["preflight_check_task"],
        per_task={
            "preflight_check_task": {
                "latencies_ms": [10.0],
                "successes": 1,
                "failures": 0,
                "missing": 2,
            }
        },
        timeout_sec=10.0,
    )
    assert should_exit_nonzero(result) is True


def test_should_exit_nonzero_clean_pass():
    result = build_business_e2e_result(
        queue_name=generate_business_e2e_queue_name(),
        repetitions=1,
        jobs_per_repetition=2,
        task_names=list(ALLOWED_BUSINESS_TASKS),
        per_task={
            "preflight_check_task": {
                "latencies_ms": [5.0, 6.0],
                "successes": 2,
                "failures": 0,
                "missing": 0,
            },
            "validate_model_task": {
                "latencies_ms": [7.0, 8.0],
                "successes": 2,
                "failures": 0,
                "missing": 0,
            },
        },
        timeout_sec=10.0,
    )
    assert should_exit_nonzero(result) is False


# main() 종료 코드 계약 ------------------------------------------------------


def test_main_rejects_mutating_task_with_exit_2(capsys):
    code = main(["--tasks", "preflight_check_task", "collect_bids_task"])
    assert code == 2
    captured = capsys.readouterr()
    assert "허용되지 않은 task" in captured.err


def test_main_rejects_empty_task_list_with_exit_2(capsys):
    # argparse 단계에서 SystemExit 을 통해 exit code 2 로 빠지는 경로도
    # 본질적으로는 잘못된 인자에 대한 거부다. SystemExit 을 잡아 코드와
    # 메시지를 함께 확인한다.
    with pytest.raises(SystemExit) as exc_info:
        main(["--tasks"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "expected at least one argument" in captured.err or "최소 1개" in captured.err


def test_main_rejects_non_positive_repetitions_with_exit_2(capsys):
    code = main(["--repetitions", "0"])
    assert code == 2
    captured = capsys.readouterr()
    assert "repetitions" in captured.err


def test_main_rejects_non_positive_jobs_with_exit_2(capsys):
    code = main(["--jobs", "0"])
    assert code == 2
    captured = capsys.readouterr()
    assert "jobs_per_repetition" in captured.err


# build_business_e2e_config 와 aggregate_repetitions ------------------------


def test_build_business_e2e_config_rejects_mutating_tasks():
    with pytest.raises(BenchmarkArgumentError, match="허용되지 않은 task"):
        build_business_e2e_config(
            task_names=["validate_model_task", "manual_retrain_task"],
            repetitions=1,
            jobs_per_repetition=1,
            timeout_sec=10.0,
        )


def test_build_business_e2e_config_uses_unique_isolated_queue():
    cfg1 = build_business_e2e_config(
        task_names=["preflight_check_task"],
        repetitions=1,
        jobs_per_repetition=1,
        timeout_sec=10.0,
    )
    cfg2 = build_business_e2e_config(
        task_names=["preflight_check_task"],
        repetitions=1,
        jobs_per_repetition=1,
        timeout_sec=10.0,
    )
    assert cfg1.queue_name != cfg2.queue_name
    assert cfg1.queue_name != PRODUCTION_QUEUE_NAME
    assert cfg2.queue_name != PRODUCTION_QUEUE_NAME


def test_aggregate_repetitions_sums_per_task_metrics():
    config = BusinessE2EConfig(
        queue_name=generate_business_e2e_queue_name(),
        task_names=("preflight_check_task", "validate_model_task"),
        repetitions=2,
        jobs_per_repetition=3,
        timeout_sec=10.0,
    )
    rep_results = [
        {
            "repetition_index": 1,
            "duration_sec": 0.5,
            "per_task": {
                "preflight_check_task": {
                    "latencies_ms": [5.0, 6.0, 7.0],
                    "successes": 3,
                    "failures": 0,
                    "missing": 0,
                },
                "validate_model_task": {
                    "latencies_ms": [10.0, 11.0],
                    "successes": 2,
                    "failures": 1,
                    "missing": 0,
                },
            },
            "errors": [],
        },
        {
            "repetition_index": 2,
            "duration_sec": 0.5,
            "per_task": {
                "preflight_check_task": {
                    "latencies_ms": [8.0, 9.0, 10.0],
                    "successes": 3,
                    "failures": 0,
                    "missing": 0,
                },
                "validate_model_task": {
                    "latencies_ms": [12.0, 13.0, 14.0],
                    "successes": 3,
                    "failures": 0,
                    "missing": 0,
                },
            },
            "errors": [],
        },
    ]
    from datetime import UTC, datetime

    started = datetime.now(UTC)
    finished = datetime.now(UTC)
    result = aggregate_repetitions(
        config=config,
        repetition_results=rep_results,
        started_at=started,
        finished_at=finished,
    )
    assert result["summary"]["successful"] == 11
    assert result["summary"]["failed"] == 1
    assert result["summary"]["missing"] == 0
    assert result["summary"]["total_enqueued"] == 12
    assert result["status"] == "failed"  # 실패 1건 때문에 failed


def test_aggregate_repetitions_clean_all_pass():
    config = BusinessE2EConfig(
        queue_name=generate_business_e2e_queue_name(),
        task_names=("preflight_check_task",),
        repetitions=1,
        jobs_per_repetition=2,
        timeout_sec=10.0,
    )
    rep_results = [
        {
            "repetition_index": 1,
            "duration_sec": 0.1,
            "per_task": {
                "preflight_check_task": {
                    "latencies_ms": [1.0, 2.0],
                    "successes": 2,
                    "failures": 0,
                    "missing": 0,
                }
            },
            "errors": [],
        }
    ]
    from datetime import UTC, datetime

    started = datetime.now(UTC)
    finished = datetime.now(UTC)
    result = aggregate_repetitions(
        config=config,
        repetition_results=rep_results,
        started_at=started,
        finished_at=finished,
    )
    assert result["status"] == "success"
    assert result["summary"]["successful"] == 2
    assert result["summary"]["failed"] == 0


# CLI 계약 ------------------------------------------------------------------


def test_parse_args_defaults_match_white_list():
    args = parse_args([])
    assert args.repetitions == 1
    assert args.jobs == 5
    assert args.timeout == 30.0
    assert args.tasks == list(ALLOWED_BUSINESS_TASKS)
    assert args.quiet is False


def test_build_arg_parser_format_help_does_not_raise():
    """help 에 이스케이프되지 않은 % 가 있어도 format_help() 가 예외 없이
    끝까지 동작하는지 검증한다. argparse 가 help 문자열을 % 포맷으로
    해석하기 때문에 회귀가 있으면 ValueError 로 드러난다."""
    help_text = build_arg_parser().format_help()
    assert "--tasks" in help_text
    assert "--repetitions" in help_text
