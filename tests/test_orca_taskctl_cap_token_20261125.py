"""동시 쓰기 상한의 읽기 전용 판정과 Capsule 토큰 절약 기본 사실을 검증합니다."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_capsule(capsule_dir: Path, task_id: str, write_files: list[str]) -> None:
    task_dir = capsule_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    if write_files:
        lines = ["schema: ORCA_TASK_CAPSULE_V2", "allowed_write_files:"]
        lines.extend(f"  - {item}" for item in write_files)
    else:
        lines = ["schema: ORCA_TASK_CAPSULE_V2", "allowed_write_files: []"]
    (task_dir / "capsule.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stub_run_probe(monkeypatch: pytest.MonkeyPatch, tasks: list[dict[str, str]]) -> None:
    monkeypatch.setattr(
        "scripts.orca_taskctl.list_dispatched_tasks", lambda run_id, timeout=30: (tasks, None)
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.resolve_run_id", lambda explicit, timeout=10: ("run_1", None)
    )


def test_orca_report_only_task_is_readonly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(a) allowed_write_files 가 .orca/ 아래뿐인 dispatched Task 는 점유에서 빠진다."""
    from scripts.orca_taskctl import check_write_concurrency

    _write_capsule(tmp_path, "t_current", ["src/current.py"])
    _write_capsule(tmp_path, "t_writer_a", ["src/a.py"])
    _write_capsule(tmp_path, "t_writer_b", ["src/b.py"])
    _write_capsule(tmp_path, "t_investigator", [".orca/reports/investigation_20261125.md"])
    _stub_run_probe(
        monkeypatch,
        [
            {"id": "t_writer_a", "status": "dispatched"},
            {"id": "t_writer_b", "status": "dispatched"},
            {"id": "t_investigator", "status": "dispatched"},
        ],
    )

    res = check_write_concurrency("t_current", tmp_path, run_id="run_1", limit=3)

    assert res["allowed"] is True
    assert res["active_write_count"] == 2
    assert res["occupying"] == ["t_writer_a", "t_writer_b"]


def test_write_outside_orca_still_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(b) .orca/ 밖 경로가 하나라도 있으면 그 Task 는 점유로 센다."""
    from scripts.orca_taskctl import check_write_concurrency

    _write_capsule(tmp_path, "t_new", ["src/new.py"])
    _write_capsule(tmp_path, "t_writer", ["src/writer.py"])
    _write_capsule(tmp_path, "t_mixed", [".orca/reports/review_20261125.md", "docs/ops/note.md"])
    _stub_run_probe(
        monkeypatch,
        [
            {"id": "t_writer", "status": "dispatched"},
            {"id": "t_mixed", "status": "dispatched"},
        ],
    )

    res = check_write_concurrency("t_new", tmp_path, run_id="run_1", limit=2)

    assert res["allowed"] is False
    assert res["active_write_count"] == 2
    assert res["occupying"] == ["t_writer", "t_mixed"]


def test_orca_report_only_current_task_skips_cap_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(c) 이번 Task 가 .orca/ 아래만 쓰면 상한 검사를 면제받는다."""
    from scripts.orca_taskctl import check_write_concurrency

    _write_capsule(tmp_path, "t_reviewer", [".orca/reports/review_20261125.md"])
    _stub_run_probe(
        monkeypatch,
        [{"id": f"t_writer_{index}", "status": "dispatched"} for index in range(10)],
    )

    res = check_write_concurrency("t_reviewer", tmp_path, run_id="run_1", limit=3)

    assert res["allowed"] is True
    assert res["active_write_count"] == 0
    assert "면제" in res["reason"]


def test_expanded_capsule_includes_new_token_rules():
    """(d) 확장된 Capsule ground_truth 에 새 토큰 절약 규칙이 포함된다."""
    from scripts.orca_taskctl import expand_intent_to_capsule

    intent = {
        "objective": "토큰 규칙 확인",
        "role": "builder",
        "scope": ["src/example.py"],
    }
    capsule = expand_intent_to_capsule(intent, task_id="task_token_rule", run_id="run_test")

    assert "토큰 절약(탐색 배칭·확인 회차 상한)" in capsule
    assert "grep -n 으로 필요한 위치를 모두 찾은 뒤 한 번에 필요한 구간을 읽는다" in capsule
    assert "같은 확인을 연달아 반복하지 않는다" in capsule
    assert 'evidence: "docs/ops/orca_worker_model_pool.md"' in capsule
