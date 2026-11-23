"""opencode_session_stats 가 스텝·컨텍스트·variant 를 같은 기준으로 집계하는지 검증합니다."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.opencode_session_stats import (
    JSON_SCHEMA,
    build_json,
    collect_from_directory,
    format_table,
    main,
    summarize_export,
)


def _step(input_tokens: int, cache_read: int, variant: str, output: int = 0, reasoning: int = 0):
    return {
        "id": f"msg_{variant}_{input_tokens}",
        "type": "assistant",
        "model": {"id": "deepseek-v4.1-flash", "providerID": "opencode-go", "variant": variant},
        "tokens": {
            "input": input_tokens,
            "output": output,
            "reasoning": reasoning,
            "cache": {"read": cache_read, "write": 0},
        },
    }


def _export(session_id: str, messages: list[dict]) -> dict:
    return {"info": {"id": session_id}, "messages": messages}


@pytest.fixture
def sample_export() -> dict:
    return _export(
        "ses_sample",
        [
            {"id": "msg_user", "type": "user", "text": "작업 지시"},
            _step(100, 900, "high", output=20, reasoning=5),
            _step(200, 1800, "low", output=10),
            {"id": "msg_idle", "type": "idle", "outcome": "succeeded"},
        ],
    )


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_summarize_steps_context_and_variants(sample_export):
    stats = summarize_export(sample_export)

    assert stats.session_id == "ses_sample"
    assert stats.steps == 2
    assert stats.total_read == 3000
    assert stats.avg_context == 1500
    assert stats.max_context == 2000
    assert stats.new_input == 300
    assert stats.output == 35
    assert stats.variants == {"high", "low"}


def test_messages_without_tokens_are_not_steps(sample_export):
    stats = summarize_export(sample_export)
    assert stats.steps == len(sample_export["messages"]) - 2

    no_tokens = _export(
        "ses_none", [{"id": "msg_1", "type": "user"}, {"id": "msg_2", "type": "idle"}]
    )
    empty = summarize_export(no_tokens)
    assert empty.steps == 0
    assert empty.avg_context == 0.0
    assert empty.total_read == 0


def test_json_output_structure(sample_export, tmp_path: Path, capsys):
    path = _write(tmp_path / "ses_sample.json", sample_export)

    assert main(["--export", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == JSON_SCHEMA
    assert len(payload["sessions"]) == 1
    session = payload["sessions"][0]
    assert session == {
        "session_id": "ses_sample",
        "steps": 2,
        "avg_context": 1500.0,
        "max_context": 2000,
        "total_read": 3000,
        "new_input": 300,
        "output": 35,
        "variants": ["high", "low"],
    }
    assert payload["totals"]["session_count"] == 1
    assert payload["totals"]["steps"] == 2
    assert payload["totals"]["total_read"] == 3000
    assert payload["totals"]["variants"] == ["high", "low"]


def test_json_totals_aggregate_multiple_sessions(sample_export, tmp_path: Path):
    other = _export("ses_other", [_step(10, 40, "max", output=1)])
    path_a = _write(tmp_path / "a.json", sample_export)
    path_b = _write(tmp_path / "b.json", other)

    payload = build_json(
        [
            summarize_export(json.loads(path_a.read_text(encoding="utf-8"))),
            summarize_export(json.loads(path_b.read_text(encoding="utf-8"))),
        ]
    )

    assert payload["totals"]["session_count"] == 2
    assert payload["totals"]["steps"] == 3
    assert payload["totals"]["total_read"] == 3050
    assert payload["totals"]["max_context"] == 2000
    assert payload["totals"]["new_input"] == 310
    assert payload["totals"]["output"] == 36
    assert payload["totals"]["variants"] == ["high", "low", "max"]


def test_table_ends_with_totals_row(sample_export):
    other = _export("ses_other", [_step(10, 40, "max")])
    table = format_table([summarize_export(sample_export), summarize_export(other)]).splitlines()

    assert "steps" in table[0]
    assert table[-1].startswith("합계")
    assert "3" in table[-1]


def test_directory_suffix_filters_and_skips_failed_export(capsys):
    listed = [
        {"id": "ses_keep", "directory": "/work/oc-stats"},
        {"id": "ses_other", "directory": "/work/other"},
        {"id": "ses_broken", "directory": "/work/oc-stats/"},
    ]
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs.get("check") is False
        if cmd[1:3] == ["session", "list"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(listed), "")
        session_id = cmd[3]
        if session_id == "ses_broken":
            return subprocess.CompletedProcess(cmd, 1, "", "세션을 찾을 수 없습니다")
        return subprocess.CompletedProcess(
            cmd, 0, json.dumps(_export(session_id, [_step(5, 95, "high")])), ""
        )

    with patch("scripts.opencode_session_stats.subprocess.run", side_effect=fake_run):
        results = collect_from_directory("oc-stats", 7)

    assert [stats.session_id for stats in results] == ["ses_keep"]
    assert results[0].total_read == 100
    assert calls[0][1:5] == ["session", "list", "--format", "json"]
    assert "-n" in calls[0]
    assert calls[0][calls[0].index("-n") + 1] == "7"
    exported = [cmd[3] for cmd in calls if cmd[1:3] == ["session", "export"]]
    assert exported == ["ses_keep", "ses_broken"]
    assert "ses_broken" in capsys.readouterr().err


def test_directory_mode_reports_list_failure(capsys):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "opencode 를 찾을 수 없습니다")

    with patch("scripts.opencode_session_stats.subprocess.run", side_effect=fake_run):
        assert main(["--directory-suffix", "oc-stats"]) == 2

    assert "세션 목록" in capsys.readouterr().err
