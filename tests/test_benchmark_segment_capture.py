"""정형 구간 계측 파싱과 비교 판정기의 회귀 테스트.

scripts/benchmark_rag_segments.py 가 로그 줄 끝의 structured_sql_segments
JSON 을 결과 산출물에 담는지와 scripts/compare_rag_segments.py 가 세 등급
판정(구조 확정, 구성비 참고, 절대 시간 산포 대비)을 내리는지를 고정한다.
"""

from __future__ import annotations

import json

from scripts.benchmark_rag_segments import (
    parse_segment_lines,
    parse_structured_sql_traces,
    summarize_structured_sql_segments,
)
from scripts.compare_rag_segments import compare_payloads, format_verdict
from scripts.compare_rag_segments import main as compare_main


def _structured_line(trace_id: str, segments: dict, cursor_count: int) -> str:
    blob = {
        "segments": segments,
        "cursor_ms": 113208.0,
        "cursor_count": cursor_count,
        "total_ms": 113300.0,
        "residual_ms": 92.0,
    }
    return (
        "2026-09-10 INFO rag_engine_latency: "
        f"trace_id={trace_id} status=ok route=sql use_sql=True "
        "plan_ms=12.00 sql_ms=113300.00 total_ms=120000.00 backend=none "
        f"structured_sql_segments={json.dumps(blob, ensure_ascii=False)}"
    )


def _trace(
    trace_id: str,
    segments: dict[str, float],
    cursor_count: int,
    is_cold: bool = True,
) -> dict:
    total = sum(segments.values())
    return {
        "trace_id": trace_id,
        "is_cold": is_cold,
        "segments": dict(segments),
        "cursor_ms": total,
        "total_ms": total + 90.0,
        "residual_ms": 90.0,
        "cursor_count": cursor_count,
    }


def test_structured_segments_파싱에서_cursor_count와_segments가_정확하다():
    line = _structured_line(
        "abc",
        {"cache_lookup_ms": 6.5, "top_rows_2": 43852.8, "corrupted_probe_ms": 42990.3},
        12,
    )
    records = parse_segment_lines(line)
    assert len(records) == 1
    blob = records[0]["structured_sql_segments"]
    assert blob["cursor_count"] == 12
    assert blob["segments"]["top_rows_2"] == 43852.8
    assert blob["segments"]["corrupted_probe_ms"] == 42990.3
    assert blob["cursor_ms"] == 113208.0


def test_structured_segments가_없는_옛_로그줄도_예외_없이_처리된다():
    old = (
        "2026-08-23 INFO rag_engine_latency: trace_id=t1 status=ok "
        "plan_ms=12.00 sql_ms=88.00 total_ms=5000.00 backend=ollama"
    )
    records = parse_segment_lines(old)
    assert len(records) == 1
    assert records[0]["trace_id"] == "t1"
    assert records[0]["total_ms"] == 5000.0
    assert "structured_sql_segments" not in records[0]


def test_structured_segments의_중괄호와_공백이_잘리지_않는다():
    line = _structured_line(
        "spaced",
        {"cached_aggregate_2": 22070.1, "top_rows_3": 42613.2},
        11,
    )
    assert "{ " in line or ": " in line
    records = parse_segment_lines(line)
    assert len(records) == 1
    blob = records[0]["structured_sql_segments"]
    assert blob["segments"] == {"cached_aggregate_2": 22070.1, "top_rows_3": 42613.2}
    assert blob["cursor_count"] == 11
    assert records[0]["plan_ms"] == 12.0


def test_structured_segments의_null과_깨진_JSON을_견딘다():
    null_line = (
        "2026-09-10 INFO rag_engine_latency: trace_id=n1 status=ok "
        "plan_ms=1.00 total_ms=100.00 structured_sql_segments=null"
    )
    broken_line = (
        "2026-09-10 INFO rag_engine_latency: trace_id=n2 status=ok "
        'plan_ms=1.00 total_ms=100.00 structured_sql_segments={"cursor_count": 12,'
    )
    records = parse_segment_lines(null_line + "\n" + broken_line)
    assert len(records) == 2
    assert "structured_sql_segments" not in records[0]
    assert "structured_sql_segments" not in records[1]


def test_트레이스와_집계에_비시간_카운터가_담긴다():
    records = parse_segment_lines(
        _structured_line("t1", {"top_rows_2": 100.0, "corrupted_probe_ms": 40.0}, 12)
        + "\n"
        + _structured_line("t2", {"top_rows_2": 120.0, "corrupted_probe_ms": 45.0}, 11)
    )
    traces = parse_structured_sql_traces(records)
    assert [trace["cursor_count"] for trace in traces] == [12, 11]
    summary = summarize_structured_sql_segments(records)
    assert summary["cursor_count"]["values"] == [11, 12]
    assert summary["cursor_count"]["min"] == 11
    assert summary["cursor_count"]["max"] == 12
    assert summary["by_segment"]["top_rows_2"]["n"] == 2
    assert summary["by_segment"]["corrupted_probe_ms"]["max_ms"] == 45.0


def test_비교기가_구간_소멸을_확정으로_판정한다():
    before = {
        "structured_sql_traces": [
            _trace("a1", {"top_rows_2": 43852.0, "corrupted_probe_ms": 42990.0}, 12),
            _trace("a2", {"top_rows_2": 40000.0, "corrupted_probe_ms": 39000.0}, 11),
        ]
    }
    after = {
        "structured_sql_traces": [
            _trace("b1", {"top_rows_2": 19536.0}, 9),
            _trace("b2", {"top_rows_2": 3341.0}, 9),
        ]
    }
    verdict = compare_payloads(before, after, scope="cold", min_samples=2)
    gone = [item for item in verdict["structural"] if item["kind"] == "구간 소멸"]
    assert len(gone) == 1
    assert gone[0]["name"] == "corrupted_probe_ms"
    assert gone[0]["verdict"] == "확정"


def test_비교기가_정수_카운터_변화를_확정으로_판정한다():
    before = {
        "structured_sql_traces": [
            _trace("a1", {"top_rows_2": 100.0}, 12),
            _trace("a2", {"top_rows_2": 110.0}, 11),
        ]
    }
    after = {
        "structured_sql_traces": [
            _trace("b1", {"top_rows_2": 105.0}, 9),
            _trace("b2", {"top_rows_2": 108.0}, 9),
        ]
    }
    verdict = compare_payloads(before, after, scope="cold", min_samples=2)
    counter = [item for item in verdict["structural"] if item["name"] == "cursor_count"]
    assert len(counter) == 1
    assert counter[0]["verdict"] == "확정"


def test_비교기가_산포_안_시간차를_구별_불가로_판정한다():
    before = {
        "structured_sql_traces": [
            _trace("a1", {"cached_aggregate_2": 22070.0}, 12),
            _trace("a2", {"cached_aggregate_2": 1665.0}, 12),
        ]
    }
    after = {
        "structured_sql_traces": [
            _trace("b1", {"cached_aggregate_2": 40984.0}, 9),
            _trace("b2", {"cached_aggregate_2": 1665.0}, 9),
        ]
    }
    verdict = compare_payloads(before, after, scope="cold", min_samples=2)
    target = [item for item in verdict["time"] if item["name"] == "cached_aggregate_2"]
    assert len(target) == 1
    assert target[0]["verdict"] == "구별 불가"
    text = format_verdict(verdict)
    assert "구별 불가" in text
    assert "개선" not in text


def test_비교기가_산포를_넘는_시간차도_확정으로_올리지_않는다():
    """범위가 안 겹치고 평균차가 산포 합을 넘어도 참고까지만 간다.

    시간 분기에는 확정도 개선도 없다는 것이 이 도구의 핵심 계약이다.
    표본이 적을 때 우연히 두 덩어리가 갈리는 일은 일어날 수 있으므로,
    그때 나오는 문구가 확정이나 개선이 아님을 못박는다.
    """
    before = {
        "structured_sql_traces": [
            _trace("a1", {"top_rows_2": 100.0}, 12),
            _trace("a2", {"top_rows_2": 110.0}, 12),
        ]
    }
    after = {
        "structured_sql_traces": [
            _trace("b1", {"top_rows_2": 1000.0}, 12),
            _trace("b2", {"top_rows_2": 1010.0}, 12),
        ]
    }
    verdict = compare_payloads(before, after, scope="cold", min_samples=2)
    target = [item for item in verdict["time"] if item["name"] == "top_rows_2"]
    assert len(target) == 1
    assert target[0]["verdict"] == "산포 초과(참고)"
    assert "확정" not in target[0]["verdict"]
    text = format_verdict(verdict)
    assert "개선" not in text


def test_비교기가_표본_부족을_판정_불가로_구분한다():
    before = {"structured_sql_traces": [_trace("a1", {"top_rows_2": 100.0}, 12)]}
    after = {"structured_sql_traces": [_trace("b1", {"top_rows_2": 90.0}, 9)]}
    verdict = compare_payloads(before, after, scope="cold", min_samples=2)
    target = [item for item in verdict["time"] if item["name"] == "top_rows_2"]
    assert len(target) == 1
    assert target[0]["verdict"] == "판정 불가"
    assert target[0]["verdict"] != "구별 불가"
    text = format_verdict(verdict)
    assert "판정 불가" in text


def test_비교기_CLI가_두_JSON을_읽고_판정을_출력한다(tmp_path, capsys):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(
        json.dumps(
            {
                "structured_sql_traces": [
                    _trace("a1", {"top_rows_2": 100.0}, 12),
                    _trace("a2", {"top_rows_2": 110.0}, 12),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    after_path.write_text(
        json.dumps(
            {
                "structured_sql_traces": [
                    _trace("b1", {"top_rows_2": 105.0}, 9),
                    _trace("b2", {"top_rows_2": 108.0}, 9),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before_snapshot = before_path.read_text(encoding="utf-8")
    after_snapshot = after_path.read_text(encoding="utf-8")
    code = compare_main([str(before_path), str(after_path), "--scope", "cold"])
    assert code == 0
    output = capsys.readouterr().out
    assert "구조" in output
    assert "산포" in output
    assert "cursor_count" in output
    assert before_path.read_text(encoding="utf-8") == before_snapshot
    assert after_path.read_text(encoding="utf-8") == after_snapshot
    assert [path.name for path in tmp_path.iterdir()].count("before.json") == 1
