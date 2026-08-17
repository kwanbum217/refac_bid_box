from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.orca_contract import (
    char_len,
    load_capsule,
    load_report,
    parse_capsule_list,
    parse_capsule_scalar,
)
from scripts.orca_taskctl import (
    ACTIVE_TASK_STATUSES,
    DEFAULT_RUN_ID,
    MAX_CONCURRENT_WRITE_WORKERS,
    _format_review_checklist,
    _format_yaml_list,
    _run_command,
    _to_glob,
    check_write_concurrency,
    create_worktree,
    dispatch_worker,
    expand_intent_to_capsule,
    finalize_task,
    list_dispatched_tasks,
    main,
    parse_intent,
    resolve_run_id,
    task_has_write_scope,
    worker_start,
)

SAMPLE_BUILDER_INTENT = """schema: ORCA_TASK_INTENT_V1
role: builder
objective: >
  scripts/orca_taskctl.py 와 tests/test_orca_taskctl.py 를 작성한다.
scope:
  - "scripts/orca_taskctl.py"
  - "tests/test_orca_taskctl.py"
acceptance:
  - "pytest 전량 통과"
  - "ruff 린터 통과"
risk: medium
context: >
  되돌린 3453a3f 의 결함을 고치고 정본 계약을 충족한다.
"""

SAMPLE_REVIEWER_INTENT_VALID = """schema: ORCA_TASK_INTENT_V1
role: reviewer
objective: >
  빌더 산출물에 대한 독립 코드 리뷰를 수행한다.
scope:
  - "scripts/orca_taskctl.py"
review_checklist:
  - id: "C1"
    question: "모든 subprocess.run 호출에 timeout 인자가 있는가?"
    defect_when: "no"
    how: "grep 검사"
  - id: "C2"
    question: "금지 규칙 위반이 존재하는가?"
    defect_when: "yes"
"""

SAMPLE_REVIEWER_INTENT_NO_CHECKLIST = """schema: ORCA_TASK_INTENT_V1
role: reviewer
objective: >
  체크리스트가 없는 부실 리뷰어 의도.
scope:
  - "scripts/orca_taskctl.py"
"""


def test_forbidden_strings():
    """금지 문자열 검증: git worktree add 가 없고 dispatch 에 허구 플래그/잘못된 값이 없어야 함."""
    src_path = Path("scripts/orca_taskctl.py")
    assert src_path.exists(), "scripts/orca_taskctl.py 가 존재해야 합니다."
    source = src_path.read_text(encoding="utf-8")

    assert "git worktree add" not in source, "git worktree add 는 사용 금지입니다."
    # dispatch_worker 명령 조립에서 허구 플래그가 없어야 함
    dispatch_body = source.split("def dispatch_worker")[1].split("def finalize_task")[0]
    assert '"--capsule"' not in dispatch_body
    assert '"--worktree"' not in dispatch_body
    assert '"--model"' not in dispatch_body
    # --inject 는 값을 받지 않는 불리언 플래그여야 함
    assert 'cmd.extend(["--inject"' not in dispatch_body
    assert 'cmd.append("--inject")' in dispatch_body


def test_expand_intent_builder_contract_and_paths(tmp_path: Path):
    """AC1 & AC2: Builder Capsule 확장 시 규약 및 경로 검증."""
    capsule_file = tmp_path / "run_test" / "w1" / "capsule.yaml"
    intent = parse_intent(SAMPLE_BUILDER_INTENT)

    capsule = expand_intent_to_capsule(
        intent,
        task_id="task_test_001",
        run_id="run_test",
        capsule_path=capsule_file,
    )

    # 1. 메타데이터 및 계약 확인
    assert parse_capsule_scalar(capsule, "schema") == "ORCA_TASK_CAPSULE_V2"
    assert parse_capsule_scalar(capsule, "version") == "2.1.0"
    assert parse_capsule_scalar(capsule, "return_contract") == "ORCA_WORKER_DONE_V2"
    assert parse_capsule_scalar(capsule, "role") == "builder"
    assert parse_capsule_scalar(capsule, "mode") == "worker"
    assert parse_capsule_scalar(capsule, "report_path") is not None

    # 2. 범위 검증 (읽기 범위는 쓰기 범위의 진상위집합이어야 함)
    read_files = parse_capsule_list(capsule, "allowed_read_files")
    write_files = parse_capsule_list(capsule, "allowed_write_files")

    assert str(capsule_file) in read_files, "Capsule 자기 경로가 allowed_read_files 에 포함되어야 합니다."
    assert set(write_files).issubset(set(read_files)), "쓰기 범위의 모든 파일이 읽기 범위에 있어야 합니다."
    assert set(write_files) != set(read_files), "읽기 범위는 쓰기 범위와 동일하지 않고 진상위집합이어야 합니다."
    assert set(read_files) > set(write_files)


def test_expand_intent_reviewer_with_checklist(tmp_path: Path):
    """Reviewer Intent 에 review_checklist 가 있으면 정상 확장되어야 함."""
    capsule_file = tmp_path / "run_test" / "rev1" / "capsule.yaml"
    intent = parse_intent(SAMPLE_REVIEWER_INTENT_VALID)

    capsule = expand_intent_to_capsule(
        intent,
        task_id="task_rev_001",
        run_id="run_test",
        capsule_path=capsule_file,
    )

    assert parse_capsule_scalar(capsule, "role") == "reviewer"
    assert parse_capsule_scalar(capsule, "mode") == "reviewer"
    assert parse_capsule_scalar(capsule, "return_contract") == "ORCA_REVIEW_DONE_V2"
    assert "review_checklist:" in capsule
    assert '- id: "C1"' in capsule
    assert '- id: "C2"' in capsule


def test_expand_intent_reviewer_without_checklist_rejected(tmp_path: Path):
    """AC3: review_checklist 없는 reviewer Intent 는 거부(종료 코드 2)되어야 함."""
    intent_file = tmp_path / "intent_bad_reviewer.yaml"
    out_file = tmp_path / "capsule_out.yaml"
    intent_file.write_text(SAMPLE_REVIEWER_INTENT_NO_CHECKLIST, encoding="utf-8")

    # 1. 함수 직접 호출 시 ValueError
    intent = parse_intent(SAMPLE_REVIEWER_INTENT_NO_CHECKLIST)
    with pytest.raises(ValueError, match="review_checklist"):
        expand_intent_to_capsule(intent, task_id="task_rev_bad")

    # 2. CLI 실행 시 종료 코드 2
    code = main(["expand", "--intent", str(intent_file), "--out", str(out_file)])
    assert code == 2
    assert not out_file.exists()


def test_expand_intent_budget_warning(capsys: pytest.CaptureFixture):
    """지정된 예산 초과 시 stderr 로 경고가 출력되어야 함."""
    intent = {
        "schema": "ORCA_TASK_INTENT_V1",
        "role": "builder",
        "objective": "A" * 9000,
        "scope": ["src/..."],
        "risk": "medium",
    }
    capsule = expand_intent_to_capsule(intent, task_id="task_large")
    assert char_len(capsule) > 8000
    captured = capsys.readouterr()
    assert "경고: Capsule 크기" in captured.err


def test_yaml_list_formatting_no_empty_bracket_string():
    """AC8: 빈 목록에 - [] 문자열이 생성되지 않고 따옴표/이스케이프가 올바라야 함."""
    empty_res = _format_yaml_list([])
    assert empty_res == ""
    assert "- []" not in empty_res

    items = ['simple.py', 'with "quotes".py', 'back\\slash.py']
    formatted = _format_yaml_list(items)
    lines = formatted.splitlines()
    assert lines[0] == '  - "simple.py"'
    assert lines[1] == '  - "with \\"quotes\\".py"'
    assert lines[2] == '  - "back\\\\slash.py"'


def test_format_review_checklist():
    """체크리스트 YAML 블록 포맷 검증."""
    empty = _format_review_checklist([])
    assert empty == ""

    items = [
        {"id": "C1", "question": "질문 1", "defect_when": "no", "how": "방법 1"},
        {"id": "C2", "question": "질문 2", "defect_when": "yes"},
    ]
    out = _format_review_checklist(items)
    assert 'review_checklist:' in out
    assert '- id: "C1"' in out
    assert 'question: "질문 1"' in out
    assert 'defect_when: "no"' in out
    assert 'how: "방법 1"' in out
    assert '- id: "C2"' in out
    assert 'how:' not in out.split('- id: "C2"')[1]


def test_to_glob_removes_suffixes_correctly():
    """접미사 제거 시 rstrip 오류 없이 안전하게 제거되는지 확인."""
    assert _to_glob("src/...") == "src/**"
    assert _to_glob("src/**") == "src/**"
    assert _to_glob("src/") == "src/**"
    assert _to_glob("src/main.py") == "src/main.py"
    # rstrip 버그 재현 방지: 파일명이 '.' 또는 '/' 로 끝나지 않아도 올바르게 처리
    assert _to_glob("tests/test_a.py") == "tests/test_a.py"


def test_cmd_expand_json_purity(tmp_path: Path, capsys: pytest.CaptureFixture):
    """AC5: expand --json 출력 전체가 순수 JSON 으로 파싱 가능해야 함."""
    intent_file = tmp_path / "intent.yaml"
    out_file = tmp_path / "capsule.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    code = main([
        "expand",
        "--intent",
        str(intent_file),
        "--out",
        str(out_file),
        "--json",
    ])
    assert code == 0

    captured = capsys.readouterr()
    # stdout 은 온전히 JSON 파싱되어야 함
    data = json.loads(captured.out)
    assert data["capsule_path"] == str(out_file)
    assert data["char_count"] > 0
    assert data["role"] == "builder"
    assert char_len(load_capsule(out_file)) == data["char_count"]


def test_cmd_expand_human_output(tmp_path: Path, capsys: pytest.CaptureFixture):
    """expand 기본(사람) 모드 출력 검증."""
    intent_file = tmp_path / "intent.yaml"
    out_file = tmp_path / "capsule.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    code = main([
        "expand",
        "--intent",
        str(intent_file),
        "--out",
        str(out_file),
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "Capsule 생성 완료" in captured.out
    assert "문자 수:" in captured.out


def test_cmd_expand_missing_intent_file(tmp_path: Path):
    """존재하지 않는 Intent 파일 전달 시 종료 코드 2 반환."""
    code = main([
        "expand",
        "--intent",
        str(tmp_path / "nonexistent.yaml"),
        "--out",
        str(tmp_path / "capsule.yaml"),
    ])
    assert code == 2


def test_create_worktree_command(monkeypatch: pytest.MonkeyPatch):
    """create_worktree 가 올바른 orca CLI 서명을 사용하는지 검증."""
    executed_cmds: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        executed_cmds.append(cmd)
        return 0, "/path/to/worktree", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    code, _stdout, _stderr = create_worktree(name="tree_123")
    assert code == 0
    assert len(executed_cmds) == 1
    assert executed_cmds[0] == ["orca", "worktree", "create", "--name", "tree_123"]


def test_worker_start_command(monkeypatch: pytest.MonkeyPatch):
    """worker_start 가 올바른 orca CLI 서명을 사용하는지 검증."""
    executed_cmds: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        executed_cmds.append(cmd)
        return 0, "worker started", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    code, _stdout, _stderr = worker_start(
        task_id="task_123",
        agent_id="agent_abc",
        terminal_handle=None,
        model="gemini-3.7-flash-high",
        worktree="new-child",
        name="worker_inst",
        repo="my-repo",
        as_json=True,
    )
    assert code == 0
    assert len(executed_cmds) == 1
    expected = [
        "orca",
        "orchestration",
        "worker-start",
        "--task",
        "task_123",
        "--agent",
        "agent_abc",
        "--model",
        "gemini-3.7-flash-high",
        "--worktree",
        "new-child",
        "--name",
        "worker_inst",
        "--repo",
        "my-repo",
        "--json",
    ]
    assert executed_cmds[0] == expected


def test_worker_start_with_terminal(monkeypatch: pytest.MonkeyPatch):
    """terminal handle 이 지정된 worker_start 검증."""
    executed_cmds: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        executed_cmds.append(cmd)
        return 0, "worker started", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    code, _stdout, _stderr = worker_start(
        task_id="task_123",
        terminal_handle="term_123",
    )
    assert code == 0
    assert executed_cmds[0] == ["orca", "orchestration", "worker-start", "--task", "task_123", "--terminal", "term_123"]


def test_dispatch_worker_command(monkeypatch: pytest.MonkeyPatch):
    """dispatch_worker 가 허구 플래그 없이 실제 orca CLI 서명만 사용하는지 검증."""
    executed_cmds: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        executed_cmds.append(cmd)
        return 0, "dispatched", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    code, _stdout, _stderr = dispatch_worker(
        task_id="task_123",
        to_handle="term_target",
        from_handle="term_source",
        run_id="run_abc",
        inject=True,
        dry_run=True,
        return_preamble=True,
        as_json=True,
    )
    assert code == 0
    assert len(executed_cmds) == 1
    expected = [
        "orca",
        "orchestration",
        "dispatch",
        "--task",
        "task_123",
        "--to",
        "term_target",
        "--from",
        "term_source",
        "--run",
        "run_abc",
        "--inject",
        "--dry-run",
        "--return-preamble",
        "--json",
    ]
    assert executed_cmds[0] == expected
    # --inject 뒤에 별도의 인자 값이 붙지 않고 불리언 플래그로만 전달됨을 단정
    inject_idx = executed_cmds[0].index("--inject")
    assert executed_cmds[0][inject_idx + 1] in ("--dry-run", "--return-preamble", "--json")
    assert "--capsule" not in executed_cmds[0]
    assert "--worktree" not in executed_cmds[0]
    assert "--model" not in executed_cmds[0]


def test_cmd_dispatch_dry_run_json_purity(tmp_path: Path, capsys: pytest.CaptureFixture):
    """dispatch --dry-run --json 의 출력이 순수 JSON 인지 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--dry-run",
        "--json",
    ])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["dry_run"] is True
    assert data["char_count"] > 0


def test_cmd_dispatch_dry_run_human(tmp_path: Path, capsys: pytest.CaptureFixture):
    """dispatch --dry-run 기본 모드 출력 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--dry-run",
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "[Dry-run] Capsule:" in captured.out


def test_cmd_dispatch_missing_intent(tmp_path: Path):
    """dispatch 시 Intent 파일 없음 처리."""
    code = main([
        "dispatch",
        "--intent",
        str(tmp_path / "nonexistent.yaml"),
    ])
    assert code == 2


def test_cmd_dispatch_bad_reviewer_intent(tmp_path: Path):
    """dispatch 시 checklist 없는 reviewer Intent 는 2 반환."""
    intent_file = tmp_path / "bad_rev.yaml"
    intent_file.write_text(SAMPLE_REVIEWER_INTENT_NO_CHECKLIST, encoding="utf-8")

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
    ])
    assert code == 2


def test_cmd_dispatch_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """dispatch 성공 시 처리 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def mock_worker_start(**kwargs):
        return 0, '{"status": "dispatched"}', ""

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--json",
        "--agent",
        "claude",
    ])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # 기동 응답은 launch 키 아래에 담기고 Capsule 경로가 함께 보고됩니다.
    assert data["launch"]["status"] == "dispatched"
    assert Path(data["capsule"]).is_absolute()


def test_cmd_dispatch_failure_prints_command_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """AC6: worker-start 실패 시 fallback 없이 실행 명령을 stderr 에 출력하고 종료 코드 1 반환."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def mock_worker_start(**kwargs):
        return 1, "", "Connection refused"

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--model",
        "gemini-3.7-flash-high",
        "--agent",
        "claude",
    ])
    assert code == 1

    captured = capsys.readouterr()
    assert "orca orchestration worker-start" in captured.err


def test_cmd_dispatch_failure_json(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """worker-start 실패 시 --json 출력 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def mock_worker_start(**kwargs):
        return 1, "", "Connection refused"

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--json",
        "--agent",
        "claude",
    ])
    assert code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["exit_code"] == 1
    assert "Connection refused" in data["error"]


def test_finalize_task_all_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """finalize 시 모든 도구가 정상 통과하면 종료 코드 0."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return 0, json.dumps({"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}), ""
        if "orca_level1_gate" in script:
            return 0, json.dumps({"verdict": "pass"}), ""
        if "orca_run_reviewer" in script:
            return 0, json.dumps({"effective_verdict": "pass"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=True,
    )
    assert res["exit_code"] == 0
    assert load_report(report_file)["status"] == "succeeded"


def test_finalize_task_violations_returns_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """AC4: summarize 에서 계약 위반(코드 1)이 발생하면 finalize 종료 코드는 1이어야 함."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            # summarize 가 위반 발견으로 1 반환
            return 1, json.dumps({"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 2, "digest": "위반 2건"}), ""
        if "orca_level1_gate" in script:
            return 0, json.dumps({"verdict": "pass"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
    )
    assert res["exit_code"] == 1


def test_finalize_task_level1_failure_returns_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """level1 게이트 실패 시 finalize 종료 코드는 1."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return 0, json.dumps({"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}), ""
        if "orca_level1_gate" in script:
            return 1, json.dumps({"verdict": "fail"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
    )
    assert res["exit_code"] == 1


def test_finalize_task_reviewer_failure_returns_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """reviewer 검증 실패 시 finalize 종료 코드는 1."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return 0, json.dumps({"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}), ""
        if "orca_level1_gate" in script:
            return 0, json.dumps({"verdict": "pass"}), ""
        if "orca_run_reviewer" in script:
            return 1, json.dumps({"effective_verdict": "fail"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=True,
    )
    assert res["exit_code"] == 1


def test_finalize_task_tool_error_returns_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """도구 오류 / 파싱 실패(코드 2)가 발생하면 finalize 종료 코드는 2이어야 함."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return 2, "", "ContractError: Capsule 파일 없음"
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
    )
    assert res["exit_code"] == 2


def test_finalize_task_json_parse_error_returns_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """도구 출력이 유효한 JSON 이 아니면 finalize 종료 코드는 2."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        return 0, "This is not JSON", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
    )
    assert res["exit_code"] == 2


def test_cmd_finalize_json_purity(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """finalize --json 의 출력이 순수 JSON 인지 검증."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_finalize_task(**kwargs):
        return {
            "summarize": {"digest": "요약"},
            "level1": {"verdict": "pass"},
            "reviewer": None,
            "exit_code": 0,
        }

    monkeypatch.setattr("scripts.orca_taskctl.finalize_task", mock_finalize_task)

    code = main([
        "finalize",
        "--report",
        str(report_file),
        "--capsule",
        str(capsule_file),
        "--json",
    ])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["exit_code"] == 0
    assert data["level1"]["verdict"] == "pass"


def test_cmd_finalize_human_output(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """finalize 사람 모드 출력 검증."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_finalize_task(**kwargs):
        return {
            "summarize": {"digest": "[Worker Done Summary]\n- Status: succeeded"},
            "level1": {"verdict": "pass"},
            "reviewer": {"effective_verdict": "pass"},
            "exit_code": 0,
        }

    monkeypatch.setattr("scripts.orca_taskctl.finalize_task", mock_finalize_task)

    code = main([
        "finalize",
        "--report",
        str(report_file),
        "--capsule",
        str(capsule_file),
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "Worker Done Summary" in captured.out
    assert "Level 1: pass" in captured.out
    assert "Reviewer: pass" in captured.out


def test_cmd_finalize_missing_files(tmp_path: Path):
    """finalize 시 파일 부재 시 종료 코드 2."""
    code = main([
        "finalize",
        "--report",
        str(tmp_path / "nonexistent.json"),
        "--capsule",
        str(tmp_path / "nonexistent.yaml"),
    ])
    assert code == 2


def test_cmd_status_json_purity(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """status --json 의 출력이 순수 JSON 인지 검증."""
    def mock_run_command(cmd, cwd=None, timeout=30):
        return 0, json.dumps({"tasks": [{"id": "task_1", "status": "completed"}]}), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    code = main(["status", "--run-id", "run_test_status", "--json"])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "tasks" in data


def test_cmd_status_human_and_failure(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """status 사람 모드 및 실패 케이스 검증."""
    def mock_run_success(cmd, cwd=None, timeout=30):
        return 0, "task_1 completed", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_success)
    code = main(["status"])
    assert code == 0
    captured_success = capsys.readouterr()
    assert "task_1 completed" in captured_success.out

    def mock_run_fail(cmd, cwd=None, timeout=30):
        return 1, "", "Connection failed"

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_fail)
    code = main(["status", "--json"])
    assert code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["orca_available"] is False


def test_run_command_exceptions(monkeypatch: pytest.MonkeyPatch):
    """_run_command 예외 처리(Timeout, FileNotFoundError, 기타 예외) 검증."""
    def mock_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["test"], timeout=10)

    monkeypatch.setattr("subprocess.run", mock_timeout)
    code, _stdout, _stderr = _run_command(["test"])
    assert code == -1

    def mock_not_found(*args, **kwargs):
        raise FileNotFoundError("not found")

    monkeypatch.setattr("subprocess.run", mock_not_found)
    code, _stdout, stderr = _run_command(["test"])
    assert code == -2
    assert "실행 파일을 찾을 수 없음" in stderr

    def mock_other(*args, **kwargs):
        raise RuntimeError("other error")

    monkeypatch.setattr("subprocess.run", mock_other)
    code, _stdout, stderr = _run_command(["test"])
    assert code == -2
    assert "명령 실행 실패" in stderr


# ---------------------------------------------------------------------------
# 동시 쓰기 워커 상한 Preflight 테스트 (새 규약 반영)
# ---------------------------------------------------------------------------


def test_concurrency_constants():
    """모듈 상수 정의 검증."""
    assert MAX_CONCURRENT_WRITE_WORKERS == 3
    assert frozenset({"dispatched"}) == ACTIVE_TASK_STATUSES


def test_list_dispatched_tasks_filtering(monkeypatch: pytest.MonkeyPatch):
    """(1) dispatched 상태의 Task 만 계상되고 pending/ready/completed/failed/blocked 는 제외된다. snake_case 키 검증."""
    mock_payload = {
        "ok": True,
        "result": {
            "tasks": [
                {"id": "t1", "run_id": "run_1", "status": "dispatched", "task_title": "W1"},
                {"id": "t2", "run_id": "run_1", "status": "pending", "task_title": "W2"},
                {"id": "t3", "run_id": "run_1", "status": "ready", "task_title": "W3"},
                {"id": "t4", "run_id": "run_1", "status": "completed", "task_title": "W4"},
                {"id": "t5", "run_id": "run_1", "status": "failed", "task_title": "W5"},
                {"id": "t6", "run_id": "run_1", "status": "blocked", "task_title": "W6"},
                {"id": "t7", "run_id": "run_1", "status": "dispatched", "task_title": "W7"},
            ]
        },
    }

    def mock_run(cmd, cwd=None, timeout=30):
        return 0, json.dumps(mock_payload), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    tasks, err = list_dispatched_tasks(run_id="run_1")
    assert err is None
    assert len(tasks) == 2
    task_ids = [t["id"] for t in tasks]
    assert task_ids == ["t1", "t7"]


def test_resolve_run_id_explicit():
    """명시적 run_id 가 지정되고 run_auto 가 아니면 그대로 반환한다."""
    resolved, err = resolve_run_id("run_custom_123")
    assert err is None
    assert resolved == "run_custom_123"


def test_resolve_run_id_from_run_current(monkeypatch: pytest.MonkeyPatch):
    """explicit 이 None 또는 DEFAULT_RUN_ID('run_auto')일 때 run-current 로 해석한다."""
    mock_payload = {
        "ok": True,
        "result": {
            "run": {
                "id": "run_current_abc",
                "objective": "테스트",
            }
        },
    }

    def mock_run(cmd, cwd=None, timeout=10):
        assert cmd == ["orca", "orchestration", "run-current", "--json"]
        return 0, json.dumps(mock_payload), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    # 1. explicit=None
    r1, err1 = resolve_run_id(None)
    assert err1 is None
    assert r1 == "run_current_abc"

    # 2. explicit=DEFAULT_RUN_ID ('run_auto')
    r2, err2 = resolve_run_id(DEFAULT_RUN_ID)
    assert err2 is None
    assert r2 == "run_current_abc"


def test_resolve_run_id_failure(monkeypatch: pytest.MonkeyPatch):
    """run-current 실행 실패 또는 run.id 부재 시 (None, 에러메시지) 반환."""
    def mock_run_fail(cmd, cwd=None, timeout=10):
        return 1, "", "No Run is bound"

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_fail)
    resolved, err = resolve_run_id(None)
    assert resolved is None
    assert "run-current 조회 실패" in err


def test_task_has_write_scope_empty_capsule_is_readonly(tmp_path: Path):
    """(3) allowed_write_files 가 빈 Capsule 은 읽기 전용으로 판정된다."""
    task_dir = tmp_path / "task_readonly"
    task_dir.mkdir(parents=True)
    capsule_file = task_dir / "capsule.yaml"
    capsule_file.write_text(
        """schema: ORCA_TASK_CAPSULE_V2
role: reviewer
allowed_write_files: []
""",
        encoding="utf-8",
    )

    is_write = task_has_write_scope("task_readonly", tmp_path)
    assert is_write is False


def test_task_has_write_scope_missing_capsule_is_write_fail_closed(tmp_path: Path):
    """(4) Capsule 파일이 없으면 쓰기로 판정된다 (fail-closed)."""
    is_write = task_has_write_scope("task_non_existent", tmp_path)
    assert is_write is True


def test_check_write_concurrency_excludes_self_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """자기 Task 는 점유 집계에서 제외된다."""
    for tid in ("t_self", "t_other"):
        tdir = tmp_path / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "capsule.yaml").write_text("allowed_write_files:\n  - src/a.py\n", encoding="utf-8")

    def mock_list_dispatched(run_id, timeout=30):
        return [
            {"id": "t_self", "status": "dispatched"},
            {"id": "t_other", "status": "dispatched"},
        ], None

    monkeypatch.setattr("scripts.orca_taskctl.list_dispatched_tasks", mock_list_dispatched)

    # t_self 가 재실행되더라도 자기 자신은 점유에서 빠져 활성 카운트는 1개여야 함
    res = check_write_concurrency("t_self", tmp_path, run_id="run_1", limit=3)
    assert res["allowed"] is True
    assert res["active_write_count"] == 1
    assert res["occupying"] == ["t_other"]


def test_check_write_concurrency_at_limit_disallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(5) 활성 쓰기 워커가 상한과 같으면 allowed=False 다."""
    for tid in ("t1", "t2", "t3", "t_new"):
        tdir = tmp_path / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "capsule.yaml").write_text("allowed_write_files:\n  - src/a.py\n", encoding="utf-8")

    def mock_list_dispatched(run_id, timeout=30):
        return [
            {"id": "t1", "status": "dispatched"},
            {"id": "t2", "status": "dispatched"},
            {"id": "t3", "status": "dispatched"},
        ], None

    monkeypatch.setattr("scripts.orca_taskctl.list_dispatched_tasks", mock_list_dispatched)

    res = check_write_concurrency("t_new", tmp_path, run_id="run_1", limit=3)
    assert res["allowed"] is False
    assert res["active_write_count"] == 3
    assert res["limit"] == 3
    assert res["occupying"] == ["t1", "t2", "t3"]
    assert res["probe_error"] is None
    assert "도달" in res["reason"]


def test_check_write_concurrency_below_limit_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(6) 활성 쓰기 워커가 상한보다 적으면 allowed=True 다."""
    for tid in ("t1", "t2", "t_new"):
        tdir = tmp_path / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "capsule.yaml").write_text("allowed_write_files:\n  - src/a.py\n", encoding="utf-8")

    def mock_list_dispatched(run_id, timeout=30):
        return [
            {"id": "t1", "status": "dispatched"},
            {"id": "t2", "status": "dispatched"},
        ], None

    monkeypatch.setattr("scripts.orca_taskctl.list_dispatched_tasks", mock_list_dispatched)

    res = check_write_concurrency("t_new", tmp_path, run_id="run_1", limit=3)
    assert res["allowed"] is True
    assert res["active_write_count"] == 2
    assert res["limit"] == 3
    assert res["occupying"] == ["t1", "t2"]
    assert res["probe_error"] is None
    assert "통과" in res["reason"]


def test_check_write_concurrency_run_id_failure_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run ID 해석 실패 시 fail-closed 로 allowed=False 및 probe_error 채움."""
    tdir = tmp_path / "t_write"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "capsule.yaml").write_text("allowed_write_files:\n  - src/a.py\n", encoding="utf-8")

    def mock_resolve_run_id(explicit, timeout=10):
        return None, "Run ID 해석 실패"

    monkeypatch.setattr("scripts.orca_taskctl.resolve_run_id", mock_resolve_run_id)

    res = check_write_concurrency("t_write", tmp_path, limit=3)
    assert res["allowed"] is False
    assert res["probe_error"] == "Run ID 해석 실패"
    assert "Run ID 해석 실패" in res["reason"]


def test_check_write_concurrency_task_list_failure_disallowed_with_probe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(7) task-list 조회 실패 시 allowed=False 이고 probe_error 가 채워진다."""
    tdir = tmp_path / "t_write"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "capsule.yaml").write_text("allowed_write_files:\n  - src/a.py\n", encoding="utf-8")

    def mock_list_dispatched(run_id, timeout=30):
        return [], "Orca CLI 통신 오류 (Connection refused)"

    monkeypatch.setattr("scripts.orca_taskctl.list_dispatched_tasks", mock_list_dispatched)

    res = check_write_concurrency("t_write", tmp_path, run_id="run_1", limit=3)
    assert res["allowed"] is False
    assert res["probe_error"] == "Orca CLI 통신 오류 (Connection refused)"
    assert "조회 실패" in res["reason"]


def test_check_write_concurrency_readonly_task_allowed_even_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(8) 읽기 전용 Task 는 상한을 초과한 상태에서도 통과한다."""
    rdir = tmp_path / "t_reviewer"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "capsule.yaml").write_text("allowed_write_files: []\n", encoding="utf-8")

    def mock_list_dispatched(run_id, timeout=30):
        return [{"id": f"t{i}", "status": "dispatched"} for i in range(10)], None

    monkeypatch.setattr("scripts.orca_taskctl.list_dispatched_tasks", mock_list_dispatched)

    res = check_write_concurrency("t_reviewer", tmp_path, run_id="run_1", limit=3)
    assert res["allowed"] is True
    assert res["active_write_count"] == 0
    assert "면제" in res["reason"]


def test_cmd_dispatch_blocked_by_concurrency_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """CLI: dispatch 실행 시 동시 쓰기 워커 상한 초과로 차단 및 종료 코드 1 반환."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    capsule_dir = tmp_path / "capsules"

    def mock_check(task_id, capsule_dir, run_id=None, limit=3, timeout=30):
        return {
            "allowed": False,
            "active_write_count": 3,
            "limit": 3,
            "occupying": ["t1", "t2", "t3"],
            "probe_error": None,
            "reason": "동시 쓰기 워커 상한(3개)에 도달했습니다.",
        }

    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", mock_check)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(capsule_dir),
    ])
    assert code == 1
    captured = capsys.readouterr()
    assert "동시 쓰기 워커 상한 초과" in captured.err
    assert "t1, t2, t3" in captured.err


def test_cmd_dispatch_blocked_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """CLI: dispatch --json 실행 시 동시 쓰기 상한 초과 JSON 에러 출력 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    capsule_dir = tmp_path / "capsules"

    def mock_check(task_id, capsule_dir, run_id=None, limit=3, timeout=30):
        return {
            "allowed": False,
            "active_write_count": 3,
            "limit": 3,
            "occupying": ["t1", "t2", "t3"],
            "probe_error": None,
            "reason": "동시 쓰기 워커 상한(3개)에 도달했습니다.",
        }

    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", mock_check)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(capsule_dir),
        "--json",
    ])
    assert code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["error"] == "concurrency_limit_exceeded"
    assert data["allowed"] is False
    assert data["active_write_count"] == 3
    assert data["limit"] == 3
    assert data["occupying"] == ["t1", "t2", "t3"]
    assert data["exit_code"] == 1


def test_cmd_dispatch_skip_concurrency_check(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """CLI: --skip-concurrency-check 지정 시 경고를 출력하고 검사를 건너뜀."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")
    capsule_dir = tmp_path / "capsules"

    def mock_worker_start(**kwargs):
        return 0, '{"status": "dispatched"}', ""

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(capsule_dir),
        "--skip-concurrency-check",
        "--agent",
        "claude",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "경고: --skip-concurrency-check" in captured.err


def test_cmd_dispatch_dry_run_skips_concurrency_check(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """CLI: --dry-run 지정 시 check_write_concurrency 를 실행하지 않고 return 0."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")
    capsule_dir = tmp_path / "capsules"

    called = []

    def mock_check(*args, **kwargs):
        called.append(True)
        return {"allowed": False}

    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", mock_check)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(capsule_dir),
        "--dry-run",
    ])
    assert code == 0
    assert len(called) == 0, "dry-run 에서는 check_write_concurrency 가 호출되지 않아야 합니다."





# ---------------------------------------------------------------------------
# 기동 경로 선택 (worker-start vs 터미널 부착 Dispatch)
# ---------------------------------------------------------------------------


def test_extract_cli_error_reads_stdout_error_message():
    """Orca CLI 는 실패 원인을 stdout JSON 의 error.message 로만 주는 경우가 있다."""
    from scripts.orca_taskctl import _extract_cli_error

    stdout = json.dumps({"ok": False, "error": {"code": "invalid_argument", "message": "New worktrees require --name."}})
    assert _extract_cli_error(stdout) == "New worktrees require --name."
    assert _extract_cli_error("") is None
    assert _extract_cli_error("not json") is None
    assert _extract_cli_error(json.dumps({"ok": True})) is None


def test_launch_succeeded_rejects_ok_false():
    """종료 코드 0 이어도 ok 가 false 면 성공으로 보지 않는다."""
    from scripts.orca_taskctl import _launch_succeeded

    assert _launch_succeeded(json.dumps({"ok": True})) is True
    assert _launch_succeeded(json.dumps({"ok": False, "error": {"message": "x"}})) is False
    assert _launch_succeeded("사람이 읽는 출력") is True


def test_cmd_dispatch_requires_launch_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--agent 도 --terminal 도 없으면 기동을 시도하지 않고 종료 코드 2 로 거부한다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_worker_start(**kwargs):
        raise AssertionError("기동 대상이 없으면 worker_start 를 호출해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", fail_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
    ])
    assert code == 2


def test_cmd_dispatch_terminal_uses_attach_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--terminal 이 있으면 worker-start 가 아니라 dispatch --to --inject 로 부착한다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    calls: dict[str, object] = {}

    def mock_dispatch_worker(**kwargs):
        calls.update(kwargs)
        return 0, json.dumps({"ok": True}), ""

    def fail_worker_start(**kwargs):
        raise AssertionError("터미널 부착 경로에서는 worker_start 를 호출해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", mock_dispatch_worker)
    monkeypatch.setattr("scripts.orca_taskctl.worker_start", fail_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--json",
    ])
    assert code == 0
    assert calls["to_handle"] == "term_abc"
    assert calls["inject"] is True


def test_cmd_dispatch_worker_start_passes_worktree_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """new-child 워크트리는 --name 이 필수이므로 이름을 반드시 넘긴다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    calls: dict[str, object] = {}

    def mock_worker_start(**kwargs):
        calls.update(kwargs)
        return 0, json.dumps({"ok": True}), ""

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--agent",
        "claude",
        "--worktree-name",
        "orca-split-probe",
        "--json",
    ])
    assert code == 0
    assert calls["worktree"] == "new-child"
    assert calls["name"] == "orca-split-probe"


def test_cmd_dispatch_ok_false_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """종료 코드 0 + ok:false 응답을 성공으로 보고하지 않고 stdout 의 원인을 노출한다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    payload = json.dumps({"ok": False, "error": {"message": "New worktrees require --name."}})

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", lambda **k: (0, payload, ""))
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--agent",
        "claude",
    ])
    assert code == 1
    assert "New worktrees require --name." in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Capsule 경로 주입
# ---------------------------------------------------------------------------


def test_build_capsule_notice_carries_path_contract_and_dispatch_id():
    """고지문은 경로, 커밋 계약, 유효 dispatchId 를 함께 담아야 합니다."""
    from scripts.orca_taskctl import build_capsule_notice

    text = build_capsule_notice(
        Path("/abs/capsules/task_x/capsule.yaml"),
        report_path="/abs/capsules/task_x/worker_done.json",
        dispatch_id="ctx_new",
    )
    assert "/abs/capsules/task_x/capsule.yaml" in text
    assert "allowed_write_files" in text
    assert "escalation" in text
    assert "ctx_new" in text
    assert "/abs/capsules/task_x/worker_done.json" in text


def test_build_task_spec_embeds_absolute_capsule_path():
    """spec 은 --inject 가 전달하는 유일한 본문이므로 Capsule 경로를 담아야 합니다."""
    from scripts.orca_taskctl import build_task_spec

    spec = build_task_spec("모듈 A 를 기계적 분할한다", Path("/abs/c/capsule.yaml"))
    assert "/abs/c/capsule.yaml" in spec
    assert "모듈 A" in spec


def test_build_task_spec_truncates_long_objective():
    """objective 가 길어도 spec 이 무한히 커지지 않아야 합니다."""
    from scripts.orca_taskctl import build_task_spec

    spec = build_task_spec("가" * 900, Path("/abs/c/capsule.yaml"))
    assert "/abs/c/capsule.yaml" in spec
    assert len(spec) < 600


def test_cmd_dispatch_sends_capsule_notice_on_attach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """터미널 부착 성공 후 Capsule 고지문이 자동 전송되어야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    sent: dict[str, str] = {}

    def mock_terminal_send(handle, text, timeout=30):
        sent["handle"] = handle
        sent["text"] = text
        return 0, json.dumps({"ok": True}), ""

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), ""))
    monkeypatch.setattr("scripts.orca_taskctl.terminal_send", mock_terminal_send)
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: "ctx_live")
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--json",
    ])
    assert code == 0
    assert sent["handle"] == "term_abc"
    assert "capsule.yaml" in sent["text"]
    assert "ctx_live" in sent["text"]
    data = json.loads(capsys.readouterr().out)
    assert data["capsule_notice"]["status"] == "sent"
    assert Path(data["capsule"]).is_absolute()


def test_cmd_dispatch_capsule_notice_failure_is_surfaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """고지문 전송 실패를 조용히 넘기지 않아야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), ""))
    monkeypatch.setattr(
        "scripts.orca_taskctl.terminal_send",
        lambda *a, **k: (0, json.dumps({"ok": False, "error": {"message": "tab_not_found"}}), ""),
    )
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: None)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--json",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "tab_not_found" in captured.err
    assert json.loads(captured.out)["capsule_notice"]["status"] == "failed"


def test_cmd_dispatch_no_capsule_notice_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--no-capsule-notice 를 주면 전송을 시도하지 않아야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_send(*a, **k):
        raise AssertionError("--no-capsule-notice 에서는 전송하지 않아야 합니다.")

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), ""))
    monkeypatch.setattr("scripts.orca_taskctl.terminal_send", fail_send)
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--no-capsule-notice",
    ])
    assert code == 0


def test_cmd_create_puts_capsule_path_in_task_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """create 는 Capsule 절대 경로를 Orca Task spec 에 넣어야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    calls: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        calls.append(cmd)
        return 0, json.dumps({"ok": True, "result": {"task": {"id": "task_created"}}}), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)

    code = main([
        "create",
        "--intent",
        str(intent_file),
        "--run-id",
        "run_x",
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--task-title",
        "제목",
        "--json",
    ])
    assert code == 0
    cmd = calls[0]
    assert cmd[:3] == ["orca", "orchestration", "task-create"]
    spec = cmd[cmd.index("--spec") + 1]
    assert "capsule.yaml" in spec
    assert Path(spec.split("정본 사양(Capsule): ")[1]).is_absolute()
    assert json.loads(capsys.readouterr().out)["task_id"] == "task_created"


def test_cmd_dispatch_reuses_existing_capsule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """--capsule 을 주면 재확장하지 않고 그 파일을 그대로 써야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")
    existing = tmp_path / "premade" / "capsule.yaml"
    existing.parent.mkdir()
    existing.write_text("schema: ORCA_TASK_CAPSULE_V2\nmarker: premade\n", encoding="utf-8")

    def fail_expand(*a, **k):
        raise AssertionError("--capsule 지정 시 재확장해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.expand_intent_to_capsule", fail_expand)
    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), ""))
    monkeypatch.setattr("scripts.orca_taskctl.terminal_send", lambda *a, **k: (0, json.dumps({"ok": True}), ""))
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: "ctx_live")
    monkeypatch.setattr("scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True})

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule",
        str(existing),
        "--task-id",
        "task_real_orca_id",
        "--terminal",
        "term_abc",
        "--json",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["capsule"] == str(existing.resolve())
    assert existing.read_text(encoding="utf-8").endswith("marker: premade\n")


def test_cmd_dispatch_missing_reused_capsule_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--capsule 이 존재하지 않으면 기동하지 않고 종료 코드 2 로 거부해야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_dispatch(**k):
        raise AssertionError("Capsule 부재 시 기동해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", fail_dispatch)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule",
        str(tmp_path / "nope.yaml"),
        "--terminal",
        "term_abc",
    ])
    assert code == 2


def test_expand_includes_analysis_artifact_in_write_scope():
    """템플릿이 지시하는 분석 문서 경로가 쓰기 범위에 있어야 합니다.

    없으면 워커가 템플릿을 따라 만든 산출물이 Level 1 범위 게이트에서
    초과로 거부됩니다 (반복 금지 4.7.2).
    """
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(parse_intent(SAMPLE_BUILDER_INTENT), task_id="task_abc")
    write_block = capsule.split("allowed_write_files:")[1].split("search_scope:")[0]
    assert "docs/analysis/task_abc.md" in write_block
    artifact_block = capsule.split("artifact_paths:")[1].split("escalate_when:")[0]
    assert "docs/analysis/task_abc.md" in artifact_block


def test_expand_reviewer_scope_excludes_analysis_artifact():
    """리뷰어는 문서를 쓰지 않으므로 분석 문서 경로를 넣지 않습니다."""
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(parse_intent(SAMPLE_REVIEWER_INTENT_VALID), task_id="task_rev")
    write_block = capsule.split("allowed_write_files:")[1].split("search_scope:")[0]
    assert "docs/analysis" not in write_block


READ_SCOPE_INTENT = """schema: ORCA_TASK_INTENT_V1
role: investigator
objective: >
  src/ml/trainer.py 분할 후보를 판정한다.
scope:
  - "docs/analysis/audit.md"
read_scope:
  - "src/ml/trainer.py"
  - "src/ml/features.py"
acceptance:
  - "판정 근거를 남긴다"
risk: low
"""


def test_expand_read_scope_reads_without_write_permission():
    """read_scope 는 읽기 범위에만 들어가고 쓰기 범위에는 들어가지 않습니다.

    감사 대상을 scope 에 넣으면 쓰기까지 열려 범위 게이트가 무단 수정을
    잡지 못합니다.
    """
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    intent = parse_intent(READ_SCOPE_INTENT)
    assert intent["read_scope"] == ["src/ml/trainer.py", "src/ml/features.py"]

    capsule = expand_intent_to_capsule(intent, task_id="task_ro")
    read_block = capsule.split("allowed_read_files:")[1].split("allowed_write_files:")[0]
    write_block = capsule.split("allowed_write_files:")[1].split("search_scope:")[0]

    assert "src/ml/trainer.py" in read_block
    assert "src/ml/features.py" in read_block
    assert "src/ml/trainer.py" not in write_block
    assert "src/ml/features.py" not in write_block


def test_expand_read_scope_included_in_search_globs():
    """읽기 전용 경로도 검색 범위에 있어야 워커가 실제로 열어볼 수 있습니다."""
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(parse_intent(READ_SCOPE_INTENT), task_id="task_ro")
    glob_block = capsule.split("allowed_globs:")[1].split("forbidden:")[0]
    assert "src/ml/trainer.py" in glob_block
