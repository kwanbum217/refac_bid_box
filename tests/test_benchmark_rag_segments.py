"""RAG 구간 계측 하네스 및 무결성 회귀 테스트.

실제 스택 없이 주입된 가짜 runner와 query_sender를 통해 다음을 검증합니다:
1. --expected-llm-model 일치성 및 fail-closed exit 2
2. 공통 provenance 바인딩 및 start-end 일관성 fail-closed exit 2
3. 1:1 trace 상관 검증 (중복, 누락, 외부 로그 반례 차단)
4. HTTP 부분 실패 및 integrity error 시 non-zero (exit 1) 및 canonical_success=false
5. 정상 20/20 요청 시 exit 0 및 canonical_success=true
6. segment logger 핸들러 보강 및 로그 유실/중복 방지
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch
from urllib import error as urlerror

import pytest

from scripts.benchmark_latency import Samples
from scripts.benchmark_rag_segments import (
    CANONICAL_FIXTURE_HASHES,
    ModelMismatchError,
    SegmentLoggingDisabledError,
    aggregate,
    assert_expected_model_matches,
    assert_segment_logging_enabled,
    build_query_plan,
    container_env_flag,
    docker_since_timestamp,
    evaluate_canonical,
    load_fixture,
    main,
    parse_segment_lines,
    send_query,
    summarize_measurements,
    verify_trace_correlation,
)
from src.app.core.config import settings
from src.app.main import _enable_latency_segment_logging

SAMPLE_LOG = """
2026-08-23 20:30:01 INFO rag_engine_latency: trace_id=t1 status=ok route=sql use_sql=True use_vector=False use_kb=False plan_ms=12.00 sql_ms=88.00 vector_ms=0.00 kb_ms=0.00 assembly_ms=10.00 prepare_ms=110.00 llm_ms=4800.00 guard_ms=30.00 total_ms=5000.00 backend=ollama
2026-08-23 20:30:07 INFO rag_engine_latency: trace_id=t2 status=ok route=vector use_sql=False use_vector=True use_kb=False plan_ms=8.00 sql_ms=0.00 vector_ms=250.00 kb_ms=5.00 assembly_ms=12.00 prepare_ms=275.00 llm_ms=7000.00 guard_ms=25.00 total_ms=7400.00 backend=ollama
2026-08-23 20:30:09 INFO 관계없는 로그 한 줄
""".strip()


def _runner(env_entries: list[str]):
    def run(command: list[str]) -> str:
        if "inspect" in command and "{{json .Config.Env}}" in command:
            return json.dumps(env_entries)
        return ""

    return run


def test_parse_segment_lines_extracts_only_marked_records():
    records = parse_segment_lines(SAMPLE_LOG)
    assert len(records) == 2
    assert records[0]["trace_id"] == "t1"
    assert records[0]["llm_ms"] == pytest.approx(4800.0)
    assert records[1]["total_ms"] == pytest.approx(7400.0)


def test_parse_segment_lines_ignores_unrelated_output():
    assert parse_segment_lines("아무 관련 없는 줄\n또 다른 줄") == []
    assert parse_segment_lines("") == []
    assert parse_segment_lines("unknown") == []


def test_aggregate_records_residual_instead_of_dropping_it():
    """구간 합과 total 의 차이를 버리면 계측되지 않은 병목을 놓칩니다."""
    records = parse_segment_lines(SAMPLE_LOG)
    summary = aggregate(records)

    # t1: 12+88+0+0+10+4800+30 = 4940, total 5000 -> residual 60
    # t2: 8+0+250+5+12+7000+25 = 7300, total 7400 -> residual 100
    assert summary["residual_ms"]["n"] == 2
    assert summary["residual_ms"]["min_ms"] == pytest.approx(60.0)
    assert summary["residual_ms"]["max_ms"] == pytest.approx(100.0)


def test_aggregate_reports_percentiles_per_segment():
    summary = aggregate(parse_segment_lines(SAMPLE_LOG))
    assert summary["llm_ms"]["n"] == 2
    assert summary["llm_ms"]["min_ms"] == pytest.approx(4800.0)
    assert summary["llm_ms"]["max_ms"] == pytest.approx(7000.0)
    assert summary["total_ms"]["p50_ms"] == pytest.approx(6200.0)


def test_aggregate_handles_empty_records():
    summary = aggregate([])
    assert summary["total_ms"] is None
    assert summary["plan_ms"] is None


def test_container_env_flag_reads_value():
    runner = _runner(["LATENCY_SEGMENT_LOGGING=true", "LLM_PROVIDER=ollama"])
    assert container_env_flag("app", "LLM_PROVIDER", runner) == "ollama"
    assert container_env_flag("app", "MISSING", runner) is None
    assert container_env_flag("app", "LLM_PROVIDER", lambda _: "unknown") is None
    assert container_env_flag("app", "LLM_PROVIDER", lambda _: "invalid json") is None


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_assert_segment_logging_enabled_accepts_truthy_values(value: str):
    runner = _runner([f"LATENCY_SEGMENT_LOGGING={value}"])
    assert_segment_logging_enabled("app", runner)


@pytest.mark.parametrize("entries", [["LATENCY_SEGMENT_LOGGING=false"], ["OTHER=1"], []])
def test_assert_segment_logging_enabled_fails_closed(entries: list[str]):
    """플래그가 꺼진 채 빈 결과를 측정 완료로 착각하면 안 됩니다."""
    with pytest.raises(SegmentLoggingDisabledError) as excinfo:
        assert_segment_logging_enabled("app", _runner(entries))
    assert "LATENCY_SEGMENT_LOGGING" in str(excinfo.value)


def test_assert_segment_logging_enabled_fails_when_inspect_unavailable():
    def run(command: list[str]) -> str:
        return ""

    with pytest.raises(SegmentLoggingDisabledError):
        assert_segment_logging_enabled("app", run)


def test_assert_expected_model_matches_success():
    start_meta = {"perf_config": {"OLLAMA_MODEL": "gemma4:e4b"}}
    matched = assert_expected_model_matches("app", "gemma4:e4b", start_meta=start_meta)
    assert matched == "gemma4:e4b"


def test_assert_expected_model_matches_fallback_to_inspect():
    runner = _runner(["OLLAMA_MODEL=gemma4:e4b"])
    matched = assert_expected_model_matches("app", "gemma4:e4b", command_runner=runner)
    assert matched == "gemma4:e4b"


def test_assert_expected_model_matches_missing_expected_raises():
    with pytest.raises(ModelMismatchError) as excinfo:
        assert_expected_model_matches("app", None)
    assert "--expected-llm-model" in str(excinfo.value)


def test_assert_expected_model_matches_missing_runtime_raises():
    runner = _runner([])
    with pytest.raises(ModelMismatchError) as excinfo:
        assert_expected_model_matches("app", "gemma4:e4b", command_runner=runner)
    assert "찾을 수 없습니다" in str(excinfo.value)


def test_assert_expected_model_matches_mismatch_raises():
    start_meta = {"perf_config": {"OLLAMA_MODEL": "llama3:8b"}}
    with pytest.raises(ModelMismatchError) as excinfo:
        assert_expected_model_matches("app", "gemma4:e4b", start_meta=start_meta)
    assert "일치하지 않습니다" in str(excinfo.value)


def test_docker_since_timestamp_carries_utc_marker():
    """타임존 표기가 없으면 docker 가 로컬 시각으로 해석해 과거 로그를 긁습니다."""
    from datetime import UTC, datetime

    stamp = docker_since_timestamp(datetime(2026, 8, 23, 11, 30, 0, tzinfo=UTC))
    assert stamp == "2026-08-23T11:30:00Z"
    assert stamp.endswith("Z")


def test_docker_since_timestamp_normalizes_local_time_to_utc():
    """로컬 시각을 받아도 UTC 로 변환해 넘겨야 합니다."""
    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    stamp = docker_since_timestamp(datetime(2026, 8, 23, 20, 30, 0, tzinfo=kst))
    assert stamp == "2026-08-23T11:30:00Z"


def test_verify_trace_correlation_exact_match():
    traces = ["t1", "t2", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t2", "total_ms": 110.0},
        {"trace_id": "t3", "total_ms": 120.0},
    ]
    ok, _reason, details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is True
    assert details["matched_count"] == 3
    assert details["duplicate_response_traces"] == 0
    assert details["duplicate_log_traces"] == 0
    assert details["unmatched_log_traces"] == []
    assert details["missing_log_traces"] == []


def test_verify_trace_correlation_count_mismatch():
    traces = ["t1", "t2"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t2", "total_ms": 110.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "성공 요청 수(2)가 기대 라운드(3)" in reason


def test_verify_trace_correlation_duplicate_response_trace():
    traces = ["t1", "t1", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t2", "total_ms": 110.0},
        {"trace_id": "t3", "total_ms": 120.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "응답 헤더에 중복 trace_id" in reason


def test_verify_trace_correlation_duplicate_log_trace():
    traces = ["t1", "t2", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t1", "total_ms": 110.0},
        {"trace_id": "t3", "total_ms": 120.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "로그에 중복 trace_id" in reason


def test_verify_trace_correlation_missing_trace_id_in_log():
    traces = ["t1", "t2", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"total_ms": 110.0},  # missing trace_id
        {"trace_id": "t3", "total_ms": 120.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "trace_id가 없는 세그먼트 로그" in reason


def test_verify_trace_correlation_unmatched_external_log():
    traces = ["t1", "t2", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t2", "total_ms": 110.0},
        {"trace_id": "t_external", "total_ms": 120.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "외부 로그 trace" in reason


def test_verify_trace_correlation_missing_log():
    traces = ["t1", "t2", "t3"]
    records: list[dict[str, float | str]] = [
        {"trace_id": "t1", "total_ms": 100.0},
        {"trace_id": "t2", "total_ms": 110.0},
    ]
    ok, reason, _details = verify_trace_correlation(traces, records, expected_rounds=3)
    assert ok is False
    assert "로그 레코드 수(2)가 기대 라운드(3)" in reason


def test_send_query_success_with_header():
    mock_resp = MagicMock()
    mock_resp.headers = {"X-RAG-Trace-Id": "trace_12345"}
    mock_resp.read.return_value = b'{"response": "ok"}'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        elapsed_ms, ok, trace_id = send_query("http://127.0.0.1:8000", "질문", 10.0)
        assert ok is True
        assert trace_id == "trace_12345"
        assert elapsed_ms >= 0.0


def test_send_query_missing_header_returns_false():
    mock_resp = MagicMock()
    mock_resp.headers = {}
    mock_resp.read.return_value = b'{"response": "ok"}'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        _elapsed_ms, ok, trace_id = send_query("http://127.0.0.1:8000", "질문", 10.0)
        assert ok is False
        assert trace_id is None


def test_send_query_network_error_returns_false():
    with patch("urllib.request.urlopen", side_effect=urlerror.URLError("connection refused")):
        _elapsed_ms, ok, trace_id = send_query("http://127.0.0.1:8000", "질문", 10.0)
        assert ok is False
        assert trace_id is None


def _make_mock_docker_runner(
    env_entries: list[str] | None = None,
    container_id: str = "cid_123",
    image_id: str = "img_123",
    published_port: int = 8000,
    git_sha: str = "sha_abc",
    logs_output: str = "",
):
    env_list = env_entries or [
        "LATENCY_SEGMENT_LOGGING=true",
        "OLLAMA_MODEL=gemma4:e4b",
        "LLM_PROVIDER=ollama",
    ]

    def runner(command: list[str]) -> str:
        if "git" in command and "rev-parse" in command:
            return git_sha
        if "git" in command and "status" in command:
            return ""
        if "inspect" in command and "{{.Id}}" in command:
            return container_id
        if "inspect" in command and "{{.Image}}" in command:
            return image_id
        if "inspect" in command and "{{.Config.Image}}" in command:
            return image_id
        if "inspect" in command and "{{.Name}}" in command:
            return "refac_bid_box-app-1"
        if "inspect" in command and "{{.State.Running}}" in command:
            return "true"
        if "inspect" in command and "{{json .Config.Env}}" in command:
            return json.dumps(env_list)
        if "inspect" in command and "{{json .Config.Cmd}}" in command:
            return json.dumps(["uvicorn", "src.app.main:app", "--workers", "1"])
        if "inspect" in command and "{{json .NetworkSettings.Ports}}" in command:
            return json.dumps(
                {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(published_port)}]}
            )
        if "inspect" in command and "{{.NetworkSettings.IPAddress}}" in command:
            return "172.20.0.5"
        if "inspect" in command and "{{json .Mounts}}" in command:
            return json.dumps([{"Destination": "/app/src", "Source": "/dummy/src"}])
        if "inspect" in command and "{{json .RepoDigests}}" in command:
            return json.dumps(["repo@sha256:1234567890abcdef"])
        if "compose" in command and "ps" in command:
            return container_id
        if "compose" in command and "images" in command:
            return image_id
        if "logs" in command:
            return logs_output
        return ""

    return runner


def test_main_missing_expected_model_exits_2():
    runner = _make_mock_docker_runner()
    code = main(["--rounds", "2"], command_runner=runner)
    assert code == 2


def test_main_model_mismatch_exits_2():
    runner = _make_mock_docker_runner(
        env_entries=["LATENCY_SEGMENT_LOGGING=true", "OLLAMA_MODEL=llama3:8b"]
    )
    code = main(["--expected-llm-model", "gemma4:e4b", "--rounds", "2"], command_runner=runner)
    assert code == 2


def test_main_logging_disabled_exits_2():
    runner = _make_mock_docker_runner(
        env_entries=["LATENCY_SEGMENT_LOGGING=false", "OLLAMA_MODEL=gemma4:e4b"]
    )
    code = main(["--expected-llm-model", "gemma4:e4b", "--rounds", "2"], command_runner=runner)
    assert code == 2


def test_main_port_binding_mismatch_exits_2():
    # base_url is 8000, container publishes 9000
    runner = _make_mock_docker_runner(published_port=9000)
    code = main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--expected-llm-model",
            "gemma4:e4b",
            "--rounds",
            "2",
        ],
        command_runner=runner,
    )
    assert code == 2


def test_main_partial_http_failure_exits_1(tmp_path):
    output_file = tmp_path / "result.json"
    logs = "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
    runner = _make_mock_docker_runner(logs_output=logs)

    # 1 success, 1 failure
    query_call_count = 0

    def mock_query(url, q, timeout):
        nonlocal query_call_count
        query_call_count += 1
        if query_call_count == 1:
            return 500.0, True, "t1"
        return 1000.0, False, None

    code = main(
        [
            "--expected-llm-model",
            "gemma4:e4b",
            "--rounds",
            "2",
            "--output",
            str(output_file),
        ],
        command_runner=runner,
        query_sender=mock_query,
        host_load_sampler=lambda: {
            "observed_at_utc": "2026-08-24T00:00:00Z",
            "load_1m": 0.5,
            "cpu_count": 8,
            "per_core_percent": 6.25,
        },
    )
    assert code == 1
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert payload["canonical_success"] is False
    assert payload["errors"] == 1


def test_main_integrity_error_due_to_external_log_exits_1(tmp_path):
    output_file = tmp_path / "result.json"
    logs = (
        "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
        "2026-08-24 10:00:02 INFO rag_engine_latency: trace_id=t_external plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
    )
    runner = _make_mock_docker_runner(logs_output=logs)

    query_call_count = 0

    def mock_query(url, q, timeout):
        nonlocal query_call_count
        query_call_count += 1
        return 500.0, True, f"t{query_call_count}"

    code = main(
        [
            "--expected-llm-model",
            "gemma4:e4b",
            "--rounds",
            "2",
            "--output",
            str(output_file),
        ],
        command_runner=runner,
        query_sender=mock_query,
        host_load_sampler=lambda: {
            "observed_at_utc": "2026-08-24T00:00:00Z",
            "load_1m": 0.5,
            "cpu_count": 8,
            "per_core_percent": 6.25,
        },
    )
    assert code == 1
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "integrity_error"
    assert payload["canonical_success"] is False


def test_main_adhoc_rounds_exits_0_noncanonical(tmp_path):
    output_file = tmp_path / "result.json"
    logs = (
        "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
        "2026-08-24 10:00:02 INFO rag_engine_latency: trace_id=t2 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=600.0 guard_ms=10.0 total_ms=645.0\n"
    )
    runner = _make_mock_docker_runner(logs_output=logs)

    query_call_count = 0

    def mock_query(url, q, timeout):
        nonlocal query_call_count
        query_call_count += 1
        return 500.0, True, f"t{query_call_count}"

    code = main(
        [
            "--expected-llm-model",
            "gemma4:e4b",
            "--rounds",
            "2",
            "--output",
            str(output_file),
        ],
        command_runner=runner,
        query_sender=mock_query,
        host_load_sampler=lambda: {
            "observed_at_utc": "2026-08-24T00:00:00Z",
            "load_1m": 0.5,
            "cpu_count": 8,
            "per_core_percent": 6.25,
        },
    )
    assert code == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["canonical_success"] is False
    assert (
        "fixture_required" in payload["failed_gates"]
        or "fixture_sha256_canonical" in payload["failed_gates"]
    )
    assert payload["errors"] == 0
    assert payload["successful_traces_count"] == 2
    assert payload["segment_records_count"] == 2
    assert payload["cold_records_count"] == 2
    assert payload["warm_records_count"] == 0
    assert payload["expected_llm_model"] == "gemma4:e4b"
    assert "provenance" in payload
    assert "host_load" in payload["provenance"]
    assert "summary_cold" in payload
    assert "summary_warm" in payload


def test_load_fixture_success(tmp_path):
    fixture_file = tmp_path / "test_fixture.json"
    fixture_file.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "q01", "question": "질문 1"},
                    {"id": "q02", "question": "질문 2"},
                ]
            }
        ),
        encoding="utf-8",
    )
    items, sha256, total = load_fixture(fixture_file)
    assert len(items) == 2
    assert total == 2
    assert sha256 is not None
    assert items[0]["id"] == "q01"


def test_load_fixture_with_limit(tmp_path):
    fixture_file = tmp_path / "test_fixture.json"
    fixture_file.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "q01", "question": "질문 1"},
                    {"id": "q02", "question": "질문 2"},
                    {"id": "q03", "question": "질문 3"},
                ]
            }
        ),
        encoding="utf-8",
    )
    items, _sha, total = load_fixture(fixture_file, limit=2)
    assert len(items) == 2
    assert total == 3


def test_load_fixture_invalid_format(tmp_path):
    fixture_file = tmp_path / "invalid.json"
    fixture_file.write_text(json.dumps({"not_items": 123}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_fixture(fixture_file)
    assert "items 목록을 찾을 수 없습니다" in str(excinfo.value)


def test_build_query_plan_fixture_repetitions_cold_and_warm():
    fixture_items = [
        {"id": "q01", "question": "질문 1"},
        {"id": "q02", "question": "질문 2"},
    ]
    plan = build_query_plan(fixture_items=fixture_items, repetitions=3)
    assert len(plan) == 6
    # Repetition 0 (cold)
    assert plan[0].item_id == "q01"
    assert plan[0].is_cold is True
    assert plan[0].repetition_index == 0

    assert plan[1].item_id == "q02"
    assert plan[1].is_cold is True
    assert plan[1].repetition_index == 0

    # Repetition 1 (warm)
    assert plan[2].item_id == "q01"
    assert plan[2].is_cold is False
    assert plan[2].repetition_index == 1

    assert plan[3].item_id == "q02"
    assert plan[3].is_cold is False
    assert plan[3].repetition_index == 1

    # Repetition 2 (warm)
    assert plan[4].item_id == "q01"
    assert plan[4].is_cold is False
    assert plan[4].repetition_index == 2

    assert plan[5].item_id == "q02"
    assert plan[5].is_cold is False
    assert plan[5].repetition_index == 2


def test_build_query_plan_adhoc_rounds():
    plan = build_query_plan(fixture_items=None, rounds=7)
    assert len(plan) == 7
    # First 5 queries are unique -> cold
    for idx in range(5):
        assert plan[idx].is_cold is True
    # Queries 5 and 6 repeat queries 0 and 1 -> warm
    assert plan[5].is_cold is False
    assert plan[6].is_cold is False


def test_summarize_measurements_structure():
    records: list[dict[str, float | str]] = [
        {
            "trace_id": "t1",
            "plan_ms": 10.0,
            "sql_ms": 20.0,
            "vector_ms": 30.0,
            "kb_ms": 0.0,
            "assembly_ms": 5.0,
            "llm_ms": 500.0,
            "guard_ms": 10.0,
            "total_ms": 575.0,
        }
    ]
    roundtrip = Samples(label="rt")
    roundtrip.add(600.0, "질문")
    summary = summarize_measurements(records, roundtrip)
    assert summary["llm_ms"]["p50_ms"] == pytest.approx(500.0)
    assert summary["roundtrip_ms"]["n"] == 1
    assert summary["roundtrip_ms"]["p50_ms"] == pytest.approx(600.0)


def test_evaluate_canonical_all_pass():
    canonical_hash = next(iter(CANONICAL_FIXTURE_HASHES))
    is_canonical, failed_gates = evaluate_canonical(
        fixture_sha256=canonical_hash,
        limit=0,
        item_count=32,
        total_fixture_items=32,
        repetitions=3,
        request_failures=0,
        start_sha="sha_valid",
        start_dirty=False,
        end_sha="sha_valid",
        end_dirty=False,
        model_mismatch=False,
        port_ok=True,
        allow_unknown_provenance=False,
    )
    assert is_canonical is True
    assert failed_gates == []


def test_evaluate_canonical_failed_gates_isolated():
    canonical_hash = next(iter(CANONICAL_FIXTURE_HASHES))
    base_kwargs = {
        "fixture_sha256": canonical_hash,
        "limit": 0,
        "item_count": 32,
        "total_fixture_items": 32,
        "repetitions": 3,
        "request_failures": 0,
        "start_sha": "sha_valid",
        "start_dirty": False,
        "end_sha": "sha_valid",
        "end_dirty": False,
        "model_mismatch": False,
        "port_ok": True,
        "allow_unknown_provenance": False,
    }

    # Hash mismatch
    ok, failed = evaluate_canonical(**{**base_kwargs, "fixture_sha256": "bad_hash"})
    assert ok is False
    assert "fixture_sha256_canonical" in failed

    # Limit not zero
    ok, failed = evaluate_canonical(**{**base_kwargs, "limit": 5})
    assert ok is False
    assert "limit_zero" in failed

    # Item count partial
    ok, failed = evaluate_canonical(**{**base_kwargs, "item_count": 10})
    assert ok is False
    assert "item_count_full" in failed

    # Repetitions under 3
    ok, failed = evaluate_canonical(**{**base_kwargs, "repetitions": 2})
    assert ok is False
    assert "repetitions_minimum" in failed

    # Request failure
    ok, failed = evaluate_canonical(**{**base_kwargs, "request_failures": 1})
    assert ok is False
    assert "no_request_failures" in failed

    # Git dirty
    ok, failed = evaluate_canonical(**{**base_kwargs, "start_dirty": True})
    assert ok is False
    assert "start_clean" in failed

    # Unknown git sha
    ok, failed = evaluate_canonical(**{**base_kwargs, "start_sha": "unknown"})
    assert ok is False
    assert "start_sha_known" in failed

    # Model mismatch
    ok, failed = evaluate_canonical(**{**base_kwargs, "model_mismatch": True})
    assert ok is False
    assert "model_match_expected" in failed

    # Port invalid
    ok, failed = evaluate_canonical(**{**base_kwargs, "port_ok": False})
    assert ok is False
    assert "port_validated" in failed

    # Allow unknown provenance (non-strict)
    ok, failed = evaluate_canonical(**{**base_kwargs, "allow_unknown_provenance": True})
    assert ok is False
    assert "provenance_strict" in failed


def test_main_fixture_canonical_success_exits_0(tmp_path):
    output_file = tmp_path / "fixture_result.json"
    canonical_hash = next(iter(CANONICAL_FIXTURE_HASHES))

    # Mock fixture file whose contents match canonical_hash
    fixture_file = tmp_path / "canonical_fixture.json"
    fixture_file.write_bytes(b'{"dummy": true}')

    logs = (
        "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
        "2026-08-24 10:00:02 INFO rag_engine_latency: trace_id=t2 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=510.0 guard_ms=10.0 total_ms=555.0\n"
        "2026-08-24 10:00:03 INFO rag_engine_latency: trace_id=t3 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=520.0 guard_ms=10.0 total_ms=565.0\n"
        "2026-08-24 10:00:04 INFO rag_engine_latency: trace_id=t4 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=480.0 guard_ms=10.0 total_ms=525.0\n"
        "2026-08-24 10:00:05 INFO rag_engine_latency: trace_id=t5 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=490.0 guard_ms=10.0 total_ms=535.0\n"
        "2026-08-24 10:00:06 INFO rag_engine_latency: trace_id=t6 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=495.0 guard_ms=10.0 total_ms=540.0\n"
    )
    runner = _make_mock_docker_runner(logs_output=logs)

    query_call_count = 0

    def mock_query(url, q, timeout):
        nonlocal query_call_count
        query_call_count += 1
        return 500.0, True, f"t{query_call_count}"

    with patch(
        "scripts.benchmark_rag_segments.load_fixture",
        return_value=(
            [
                {"id": "q01", "question": "질문 1"},
                {"id": "q02", "question": "질문 2"},
            ],
            canonical_hash,
            2,
        ),
    ):
        code = main(
            [
                "--expected-llm-model",
                "gemma4:e4b",
                "--fixture",
                str(fixture_file),
                "--repetitions",
                "3",
                "--output",
                str(output_file),
            ],
            command_runner=runner,
            query_sender=mock_query,
            host_load_sampler=lambda: {
                "observed_at_utc": "2026-08-24T00:00:00Z",
                "load_1m": 0.5,
                "cpu_count": 8,
                "per_core_percent": 6.25,
            },
        )

    assert code == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["canonical"] is True
    assert payload["canonical_success"] is True
    assert payload["failed_gates"] == []
    assert payload["canonical_failed_gates"] == []
    assert payload["successful_traces_count"] == 6
    assert payload["segment_records_count"] == 6
    assert payload["cold_records_count"] == 2
    assert payload["warm_records_count"] == 4
    assert "summary_cold" in payload
    assert "summary_warm" in payload
    assert payload["summary_cold"]["llm_ms"]["n"] == 2
    assert payload["summary_warm"]["llm_ms"]["n"] == 4
    assert payload["summary"]["cold"]["llm_ms"]["n"] == 2
    assert payload["summary"]["warm"]["llm_ms"]["n"] == 4


def test_load_fixture_item_ids_filtering(tmp_path):
    """(1) 문항 ID 지정 시 해당 문항만 필터링되어 전송 대상이 됩니다."""
    fixture_file = tmp_path / "test_fixture.json"
    fixture_file.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "q01", "question": "질문 1"},
                    {"id": "q03", "question": "질문 3"},
                    {"id": "q08", "question": "질문 8"},
                    {"id": "q25", "question": "질문 25"},
                ]
            }
        ),
        encoding="utf-8",
    )
    items, _sha, total = load_fixture(fixture_file, item_ids="q03,q25")
    assert len(items) == 2
    assert total == 4
    assert [it["id"] for it in items] == ["q03", "q25"]


def test_build_query_plan_same_item_first_cold_subsequent_warm():
    """(2) 같은 문항의 첫 호출이 cold, 이후가 warm 으로 분류됩니다."""
    fixture_items = [
        {"id": "q03", "question": "질문 3"},
        {"id": "q08", "question": "질문 8"},
    ]
    plan = build_query_plan(fixture_items=fixture_items, repetitions=2)
    assert len(plan) == 4
    # 1회차: cold
    assert plan[0].item_id == "q03"
    assert plan[0].is_cold is True
    assert plan[1].item_id == "q08"
    assert plan[1].is_cold is True
    # 2회차: warm
    assert plan[2].item_id == "q03"
    assert plan[2].is_cold is False
    assert plan[3].item_id == "q08"
    assert plan[3].is_cold is False


def test_main_adhoc_rounds_preserves_legacy_output_structure(tmp_path):
    """(3) 문항 지정 없이 --rounds 만 쓰면 기존 산출물 구조가 그대로 유지됩니다."""
    output_file = tmp_path / "legacy_result.json"
    logs = "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
    runner = _make_mock_docker_runner(logs_output=logs)

    code = main(
        [
            "--expected-llm-model",
            "gemma4:e4b",
            "--rounds",
            "1",
            "--output",
            str(output_file),
        ],
        command_runner=runner,
        query_sender=lambda url, q, t: (500.0, True, "t1"),
        host_load_sampler=lambda: {
            "observed_at_utc": "2026-08-24T00:00:00Z",
            "load_1m": 0.5,
            "cpu_count": 8,
            "per_core_percent": 6.25,
        },
    )
    assert code == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    # 기존 필수 키 존재 여부 확인
    legacy_keys = [
        "status",
        "canonical_success",
        "canonical_rationale",
        "expected_llm_model",
        "git_sha",
        "timestamp",
        "environment",
        "provenance",
        "config",
        "summary",
        "errors",
        "successful_traces_count",
        "unique_successful_traces_count",
        "segment_records_count",
        "trace_correlation",
    ]
    for key in legacy_keys:
        assert key in payload
    assert payload["summary"]["total_ms"]["p50_ms"] == pytest.approx(545.0)
    assert payload["summary"]["roundtrip_ms"]["n"] == 1


def test_main_unregistered_fixture_hash_marks_noncanonical_with_failed_gates(tmp_path):
    """(4) 등록되지 않은 fixture 해시에서 canonical=false 와 실패 게이트 이름이 나옵니다."""
    output_file = tmp_path / "unregistered_result.json"
    fixture_file = tmp_path / "unregistered_fixture.json"
    fixture_file.write_text(
        json.dumps({"items": [{"id": "q01", "question": "질문"}]}),
        encoding="utf-8",
    )

    logs = (
        "2026-08-24 10:00:01 INFO rag_engine_latency: trace_id=t1 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
        "2026-08-24 10:00:02 INFO rag_engine_latency: trace_id=t2 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
        "2026-08-24 10:00:03 INFO rag_engine_latency: trace_id=t3 plan_ms=10.0 sql_ms=20.0 vector_ms=0.0 kb_ms=0.0 assembly_ms=5.0 prepare_ms=35.0 llm_ms=500.0 guard_ms=10.0 total_ms=545.0\n"
    )
    runner = _make_mock_docker_runner(logs_output=logs)

    query_count = 0

    def mock_query(url, q, timeout):
        nonlocal query_count
        query_count += 1
        return 500.0, True, f"t{query_count}"

    with patch(
        "scripts.benchmark_rag_segments.load_fixture",
        return_value=(
            [{"id": "q01", "question": "질문"}],
            "unregistered_hash_12345",
            1,
        ),
    ):
        code = main(
            [
                "--expected-llm-model",
                "gemma4:e4b",
                "--fixture",
                str(fixture_file),
                "--repetitions",
                "3",
                "--output",
                str(output_file),
            ],
            command_runner=runner,
            query_sender=mock_query,
            host_load_sampler=lambda: {
                "observed_at_utc": "2026-08-24T00:00:00Z",
                "load_1m": 0.5,
                "cpu_count": 8,
                "per_core_percent": 6.25,
            },
        )

    assert code == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["canonical"] is False
    assert payload["canonical_success"] is False
    assert "fixture_sha256_canonical" in payload["failed_gates"]
    assert "fixture_sha256_canonical" in payload["canonical_failed_gates"]


def test_main_fixture_load_error_exits_2(tmp_path):
    runner = _make_mock_docker_runner()
    non_existent = tmp_path / "non_existent.json"
    code = main(
        [
            "--expected-llm-model",
            "gemma4:e4b",
            "--fixture",
            str(non_existent),
        ],
        command_runner=runner,
    )
    assert code == 2


def test_enable_latency_segment_logging_with_root_handlers():
    """루트 로거에 핸들러가 있어도 segment logger가 자체 핸들러를 획득하고 propagate=False가 되어야 합니다."""
    root = logging.getLogger()
    root_handler = logging.StreamHandler()
    root.addHandler(root_handler)

    segment_logger = logging.getLogger("src.rag.engine")
    segment_logger.handlers.clear()
    segment_logger.propagate = True

    try:
        with patch.object(settings, "LATENCY_SEGMENT_LOGGING", True):
            _enable_latency_segment_logging()

        assert len(segment_logger.handlers) == 1
        assert segment_logger.level == logging.INFO
        assert segment_logger.propagate is False
    finally:
        root.removeHandler(root_handler)
        segment_logger.handlers.clear()


def test_enable_latency_segment_logging_without_root_handlers():
    """루트 로거에 핸들러가 없어도 segment logger가 핸들러를 획득해야 합니다."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    root.handlers.clear()

    segment_logger = logging.getLogger("src.rag.engine")
    segment_logger.handlers.clear()
    segment_logger.propagate = True

    try:
        with patch.object(settings, "LATENCY_SEGMENT_LOGGING", True):
            _enable_latency_segment_logging()

        assert len(segment_logger.handlers) == 1
        assert segment_logger.level == logging.INFO
        assert segment_logger.propagate is False
    finally:
        root.handlers = saved_handlers
        segment_logger.handlers.clear()


def test_enable_latency_segment_logging_disabled():
    """LATENCY_SEGMENT_LOGGING이 False이면 설정을 변경하지 않습니다."""
    segment_logger = logging.getLogger("src.rag.engine")
    segment_logger.handlers.clear()
    segment_logger.propagate = True
    segment_logger.setLevel(logging.NOTSET)

    with patch.object(settings, "LATENCY_SEGMENT_LOGGING", False):
        _enable_latency_segment_logging()

    assert len(segment_logger.handlers) == 0
    assert segment_logger.propagate is True
