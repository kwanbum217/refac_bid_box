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
    _format_review_checklist,
    _format_yaml_list,
    _run_command,
    _to_glob,
    create_worktree,
    dispatch_worker,
    expand_intent_to_capsule,
    finalize_task,
    main,
    parse_intent,
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
    """금지 문자열 검증: git worktree add 가 없고 dispatch 에 허구 플래그가 없어야 함."""
    src_path = Path("scripts/orca_taskctl.py")
    assert src_path.exists(), "scripts/orca_taskctl.py 가 존재해야 합니다."
    source = src_path.read_text(encoding="utf-8")

    assert "git worktree add" not in source, "git worktree add 는 사용 금지입니다."
    # dispatch_worker 명령 조립에서 허구 플래그가 없어야 함
    assert '"--capsule"' not in source or 'cmd.extend(["--capsule"' not in source
    assert '"--worktree"' not in source or 'dispatch", "--task", task_id' not in source or "--worktree" not in source.split('cmd = ["orca", "orchestration", "dispatch"')[1].split('return _run_command')[0]


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
        inject="some_preamble",
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
        "some_preamble",
        "--dry-run",
        "--return-preamble",
        "--json",
    ]
    assert executed_cmds[0] == expected
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

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--json",
    ])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "dispatched"


def test_cmd_dispatch_failure_prints_command_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """AC6: worker-start 실패 시 fallback 없이 실행 명령을 stderr 에 출력하고 종료 코드 1 반환."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def mock_worker_start(**kwargs):
        return 1, "", "Connection refused"

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--model",
        "gemini-3.7-flash-high",
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

    code = main([
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--json",
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
