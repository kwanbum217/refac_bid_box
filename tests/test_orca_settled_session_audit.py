"""완료 세션 잔류 감사의 순수 판정 테스트."""

from scripts.orca_settled_session_audit import (
    lingering_settled_sessions,
    parse_tasks,
    parse_terminals,
)


def test_lingering_completed_task_with_live_terminal() -> None:
    tasks = [{"id": "task_a", "status": "completed", "task_title": "J1"}]
    live = {"term_worker": "J1 Gemini"}
    assignees = {"task_a": "term_worker"}
    found = lingering_settled_sessions(tasks, live, assignees, coordinator_handle="term_coord")
    assert len(found) == 1
    assert found[0]["task_id"] == "task_a"
    assert found[0]["handle"] == "term_worker"


def test_completed_task_without_terminal_is_clean() -> None:
    tasks = [{"id": "task_a", "status": "completed"}]
    found = lingering_settled_sessions(tasks, {}, {"task_a": "term_worker"}, "term_coord")
    assert found == []


def test_dispatched_task_is_not_lingering() -> None:
    tasks = [{"id": "task_a", "status": "dispatched"}]
    live = {"term_worker": "active"}
    found = lingering_settled_sessions(tasks, live, {"task_a": "term_worker"}, "term_coord")
    assert found == []


def test_coordinator_handle_is_excluded() -> None:
    tasks = [{"id": "task_a", "status": "completed"}]
    live = {"term_coord": "Grok"}
    found = lingering_settled_sessions(tasks, live, {"task_a": "term_coord"}, "term_coord")
    assert found == []


def test_parse_helpers_accept_result_envelope() -> None:
    tasks = parse_tasks({"result": {"tasks": [{"id": "t1", "status": "completed"}]}})
    assert tasks[0]["id"] == "t1"
    terminals = parse_terminals({"result": {"terminals": [{"handle": "h1", "title": "J1"}]}})
    assert terminals["h1"] == "J1"
