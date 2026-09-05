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


def test_lingering_unsupervised_task_detected_via_receipt() -> None:
    """O-06: 비감독 Dispatch 세션(dispatch row 없음)도 receipt 가 있으면 잔류를 검출합니다."""
    tasks = [
        {"id": "task_unsupervised", "status": "completed", "task_title": "Unsupervised Worker"}
    ]
    live = {"term_unsupervised": "Agy Worker"}
    # Orca dispatch row 가 없어 assignees 는 None
    assignees = {"task_unsupervised": None}
    receipts = {
        "task_unsupervised": {
            "task_id": "task_unsupervised",
            "dispatch_id": "ctx_unsup_123",
            "terminal": "term_unsupervised",
            "supervised": False,
        }
    }
    found = lingering_settled_sessions(
        tasks, live, assignees, coordinator_handle="term_coord", receipts=receipts
    )
    assert len(found) == 1
    assert found[0]["task_id"] == "task_unsupervised"
    assert found[0]["handle"] == "term_unsupervised"
    assert found[0]["supervised"] is False


def test_load_unsupervised_receipts_reads_dispatch_receipts(tmp_path) -> None:
    """O-06: dispatch_receipts 디렉터리의 receipt 파일을 정상적으로 로드합니다."""
    import json

    from scripts.orca_settled_session_audit import load_unsupervised_receipts

    receipt_dir = tmp_path / ".orca" / "dispatch_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    rec_file = receipt_dir / "task_x.json"
    rec_data = {
        "task_id": "task_x",
        "dispatch_id": "ctx_999",
        "terminal": "term_x",
        "worktree": "/tmp/wt",
        "started_at": 1000.0,
        "supervised": False,
    }
    rec_file.write_text(json.dumps(rec_data), encoding="utf-8")

    loaded = load_unsupervised_receipts(repo_root=tmp_path)
    assert "task_x" in loaded
    assert loaded["task_x"]["dispatch_id"] == "ctx_999"
    assert loaded["task_x"]["supervised"] is False


def test_audit_lingering_sessions_detects_unsupervised_session(tmp_path, monkeypatch) -> None:
    """O-06: audit_lingering_sessions 가 비감독 receipt 로 완료된 세션 잔류를 검출합니다."""
    import json

    from scripts.orca_settled_session_audit import audit_lingering_sessions

    # 1. receipt 파일 작성
    receipt_dir = tmp_path / ".orca" / "dispatch_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "task_u.json").write_text(
        json.dumps(
            {
                "task_id": "task_u",
                "dispatch_id": "ctx_u",
                "terminal": "term_u",
                "worktree": str(tmp_path),
                "started_at": 1000.0,
                "supervised": False,
            }
        ),
        encoding="utf-8",
    )

    # 2. orca CLI 모킹
    def mock_orca_json(args, timeout=30):
        if args[:2] == ["orchestration", "task-list"]:
            return {
                "result": {"tasks": [{"id": "task_u", "status": "completed", "task_title": "U"}]}
            }
        elif args[:2] == ["terminal", "list"]:
            return {"result": {"terminals": [{"handle": "term_u", "title": "Unsupervised"}]}}
        elif args[:2] == ["orchestration", "run-current"]:
            return {"result": {"run": {"coordinator_handle": "term_c"}}}
        elif args[:2] == ["orchestration", "dispatch-show"]:
            # dispatch row 가 없음 (RuntimeError 발생)
            raise RuntimeError("no dispatch found")
        return {}

    monkeypatch.setattr("scripts.orca_settled_session_audit._orca_json", mock_orca_json)

    res = audit_lingering_sessions(repo_root=tmp_path)
    assert res["allowed"] is False
    assert res["count"] == 1
    assert res["lingering"][0]["task_id"] == "task_u"
    assert res["lingering"][0]["handle"] == "term_u"
    assert res["lingering"][0]["supervised"] is False
