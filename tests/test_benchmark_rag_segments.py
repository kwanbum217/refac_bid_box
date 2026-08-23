"""RAG 구간 계측 하네스 회귀 테스트.

실제 스택 없이 돕니다. 서버 로그와 docker inspect 는 주입한 가짜로 대체합니다.
"""

from __future__ import annotations

import json

import pytest

from scripts.benchmark_rag_segments import (
    SegmentLoggingDisabledError,
    aggregate,
    assert_segment_logging_enabled,
    container_env_flag,
    parse_segment_lines,
)

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


def test_container_env_flag_reads_value():
    runner = _runner(["LATENCY_SEGMENT_LOGGING=true", "LLM_PROVIDER=ollama"])
    assert container_env_flag("app", "LLM_PROVIDER", runner) == "ollama"
    assert container_env_flag("app", "MISSING", runner) is None


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
