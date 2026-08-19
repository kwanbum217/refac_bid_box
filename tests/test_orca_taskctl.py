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
    DEFAULT_VERIFICATION_COMMANDS,
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

    assert str(capsule_file) in read_files, (
        "Capsule 자기 경로가 allowed_read_files 에 포함되어야 합니다."
    )
    assert set(write_files).issubset(set(read_files)), (
        "쓰기 범위의 모든 파일이 읽기 범위에 있어야 합니다."
    )
    assert set(write_files) != set(read_files), (
        "읽기 범위는 쓰기 범위와 동일하지 않고 진상위집합이어야 합니다."
    )
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

    items = ["simple.py", 'with "quotes".py', "back\\slash.py"]
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
    assert "review_checklist:" in out
    assert '- id: "C1"' in out
    assert 'question: "질문 1"' in out
    assert 'defect_when: "no"' in out
    assert 'how: "방법 1"' in out
    assert '- id: "C2"' in out
    assert "how:" not in out.split('- id: "C2"')[1]


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

    code = main(
        [
            "expand",
            "--intent",
            str(intent_file),
            "--out",
            str(out_file),
            "--json",
        ]
    )
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

    code = main(
        [
            "expand",
            "--intent",
            str(intent_file),
            "--out",
            str(out_file),
        ]
    )
    assert code == 0

    captured = capsys.readouterr()
    assert "Capsule 생성 완료" in captured.out
    assert "문자 수:" in captured.out


def test_cmd_expand_missing_intent_file(tmp_path: Path):
    """존재하지 않는 Intent 파일 전달 시 종료 코드 2 반환."""
    code = main(
        [
            "expand",
            "--intent",
            str(tmp_path / "nonexistent.yaml"),
            "--out",
            str(tmp_path / "capsule.yaml"),
        ]
    )
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
    assert executed_cmds[0] == [
        "orca",
        "orchestration",
        "worker-start",
        "--task",
        "task_123",
        "--terminal",
        "term_123",
    ]


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

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["dry_run"] is True
    assert data["char_count"] > 0


def test_cmd_dispatch_dry_run_human(tmp_path: Path, capsys: pytest.CaptureFixture):
    """dispatch --dry-run 기본 모드 출력 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--dry-run",
        ]
    )
    assert code == 0

    captured = capsys.readouterr()
    assert "[Dry-run] Capsule:" in captured.out


def test_cmd_dispatch_missing_intent(tmp_path: Path):
    """dispatch 시 Intent 파일 없음 처리."""
    code = main(
        [
            "dispatch",
            "--intent",
            str(tmp_path / "nonexistent.yaml"),
        ]
    )
    assert code == 2


def test_cmd_dispatch_bad_reviewer_intent(tmp_path: Path):
    """dispatch 시 checklist 없는 reviewer Intent 는 2 반환."""
    intent_file = tmp_path / "bad_rev.yaml"
    intent_file.write_text(SAMPLE_REVIEWER_INTENT_NO_CHECKLIST, encoding="utf-8")

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
        ]
    )
    assert code == 2


def test_cmd_dispatch_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """dispatch 성공 시 처리 검증."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def mock_worker_start(**kwargs):
        return 0, '{"status": "dispatched"}', ""

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True}
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--json",
            "--agent",
            "claude",
        ]
    )
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
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True}
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--model",
            "gemini-3.7-flash-high",
            "--agent",
            "claude",
        ]
    )
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
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *args, **kwargs: {"allowed": True}
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--json",
            "--agent",
            "claude",
        ]
    )
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
            return (
                0,
                json.dumps(
                    {"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}
                ),
                "",
            )
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
            return (
                1,
                json.dumps(
                    {
                        "schema": "ORCA_WORKER_DONE_SUMMARY",
                        "violations_count": 2,
                        "digest": "위반 2건",
                    }
                ),
                "",
            )
        if "orca_level1_gate" in script:
            return 0, json.dumps({"verdict": "pass"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=True,
    )
    assert res["exit_code"] == 1


def test_finalize_task_level1_failure_returns_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """level1 게이트 실패 시 finalize 종료 코드는 1."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return (
                0,
                json.dumps(
                    {"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}
                ),
                "",
            )
        if "orca_level1_gate" in script:
            return 1, json.dumps({"verdict": "fail"}), ""
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=True,
    )
    assert res["exit_code"] == 1


def test_finalize_task_reviewer_failure_returns_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """reviewer 검증 실패 시 finalize 종료 코드는 1."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    def mock_run_command(cmd, cwd=None, timeout=30):
        script = cmd[1]
        if "summarize_worker_done" in script:
            return (
                0,
                json.dumps(
                    {"schema": "ORCA_WORKER_DONE_SUMMARY", "violations_count": 0, "digest": "요약"}
                ),
                "",
            )
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


def test_finalize_task_json_parse_error_returns_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_cmd_finalize_json_purity(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
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

    code = main(
        [
            "finalize",
            "--report",
            str(report_file),
            "--capsule",
            str(capsule_file),
            "--json",
        ]
    )
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["exit_code"] == 0
    assert data["level1"]["verdict"] == "pass"


def test_cmd_finalize_human_output(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
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

    code = main(
        [
            "finalize",
            "--report",
            str(report_file),
            "--capsule",
            str(capsule_file),
        ]
    )
    assert code == 0

    captured = capsys.readouterr()
    assert "Worker Done Summary" in captured.out
    assert "Level 1: pass" in captured.out
    assert "Reviewer: pass" in captured.out


def test_cmd_finalize_missing_files(tmp_path: Path):
    """finalize 시 파일 부재 시 종료 코드 2."""
    code = main(
        [
            "finalize",
            "--report",
            str(tmp_path / "nonexistent.json"),
            "--capsule",
            str(tmp_path / "nonexistent.yaml"),
        ]
    )
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


def test_cmd_status_human_and_failure(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
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


def test_check_write_concurrency_excludes_self_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_check_write_concurrency_at_limit_disallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_check_write_concurrency_below_limit_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_check_write_concurrency_run_id_failure_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(capsule_dir),
        ]
    )
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

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(capsule_dir),
            "--json",
        ]
    )
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

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(capsule_dir),
            "--skip-concurrency-check",
            "--agent",
            "claude",
        ]
    )
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

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(capsule_dir),
            "--dry-run",
        ]
    )
    assert code == 0
    assert len(called) == 0, "dry-run 에서는 check_write_concurrency 가 호출되지 않아야 합니다."


# ---------------------------------------------------------------------------
# 기동 경로 선택 (worker-start vs 터미널 부착 Dispatch)
# ---------------------------------------------------------------------------


def test_extract_cli_error_reads_stdout_error_message():
    """Orca CLI 는 실패 원인을 stdout JSON 의 error.message 로만 주는 경우가 있다."""
    from scripts.orca_taskctl import _extract_cli_error

    stdout = json.dumps(
        {
            "ok": False,
            "error": {"code": "invalid_argument", "message": "New worktrees require --name."},
        }
    )
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


def test_launch_succeeded_rejects_unparsable_output_when_json_expected():
    """--json 을 붙여 호출했는데 JSON 이 아니면 판정 불가이므로 실패로 봅니다."""
    import json as _json

    from scripts.orca_taskctl import _launch_succeeded

    assert _launch_succeeded("사람이 읽는 출력", expect_json=True) is False
    assert _launch_succeeded("", expect_json=True) is False
    assert _launch_succeeded("   ", expect_json=True) is False
    assert _launch_succeeded(_json.dumps({"ok": True}), expect_json=True) is True


def test_terminal_send_and_task_create_expect_json():
    """--json 을 붙이는 호출부는 expect_json 을 켜야 합니다."""
    source = Path("scripts/orca_taskctl.py").read_text(encoding="utf-8")
    assert source.count("_launch_succeeded(stdout, expect_json=True)") == 2
    assert "_launch_succeeded(stdout, expect_json=args.json)" in source


def test_cmd_dispatch_requires_launch_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--agent 도 --terminal 도 없으면 기동을 시도하지 않고 종료 코드 2 로 거부한다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_worker_start(**kwargs):
        raise AssertionError("기동 대상이 없으면 worker_start 를 호출해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", fail_worker_start)
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
        ]
    )
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
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    # 지시 도달 확인은 별도 테스트에서 다룹니다. 여기서는 도달이 확인된 상태를
    # 전제해야 부착 경로 자체를 검증할 수 있습니다.
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl._deliver_capsule_notice",
        lambda *a, **k: {
            "status": "sent",
            "dispatch_id": "d1",
            "chars": 10,
            "delivery_probe": "ORCA_DELIVERY_PROBE_test",
        },
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_abc",
            "--json",
        ]
    )
    assert code == 0
    assert calls["to_handle"] == "term_abc"
    assert calls["inject"] is True


def test_cmd_dispatch_worker_start_passes_worktree_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """new-child 워크트리는 --name 이 필수이므로 이름을 반드시 넘긴다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    calls: dict[str, object] = {}

    def mock_worker_start(**kwargs):
        calls.update(kwargs)
        return 0, json.dumps({"ok": True}), ""

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", mock_worker_start)
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )

    code = main(
        [
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
        ]
    )
    assert code == 0
    assert calls["worktree"] == "new-child"
    assert calls["name"] == "orca-split-probe"


def test_cmd_dispatch_ok_false_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """종료 코드 0 + ok:false 응답을 성공으로 보고하지 않고 stdout 의 원인을 노출한다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    payload = json.dumps({"ok": False, "error": {"message": "New worktrees require --name."}})

    monkeypatch.setattr("scripts.orca_taskctl.worker_start", lambda **k: (0, payload, ""))
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--agent",
            "claude",
        ]
    )
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
    # Windows 에서는 str(Path) 가 역슬래시를 쓰므로 경로 문자열을 못박지 않습니다.
    assert str(Path("/abs/capsules/task_x/capsule.yaml")) in text
    assert "allowed_write_files" in text
    assert "escalation" in text
    assert "ctx_new" in text
    assert (
        "/abs/capsules/task_x/worker_done.json" in text
    )  # report_path 는 문자열 그대로 전달됩니다


def test_build_task_spec_embeds_absolute_capsule_path():
    """spec 은 --inject 가 전달하는 유일한 본문이므로 Capsule 경로를 담아야 합니다."""
    from scripts.orca_taskctl import build_task_spec

    spec = build_task_spec("모듈 A 를 기계적 분할한다", Path("/abs/c/capsule.yaml"))
    assert str(Path("/abs/c/capsule.yaml")) in spec
    assert "모듈 A" in spec


def test_build_task_spec_truncates_long_objective():
    """objective 가 길어도 spec 이 무한히 커지지 않아야 합니다."""
    from scripts.orca_taskctl import build_task_spec

    spec = build_task_spec("가" * 900, Path("/abs/c/capsule.yaml"))
    assert str(Path("/abs/c/capsule.yaml")) in spec
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

    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), "")
    )
    monkeypatch.setattr("scripts.orca_taskctl.terminal_send", mock_terminal_send)
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: "ctx_live")
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    # 지시 도달 확인은 별도 테스트에서 다룹니다. 여기서는 도달이 확인된 상태를
    # 전제해야 부착 경로 자체를 검증할 수 있습니다.
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_abc",
            "--json",
        ]
    )
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

    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), "")
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.terminal_send",
        lambda *a, **k: (0, json.dumps({"ok": False, "error": {"message": "tab_not_found"}}), ""),
    )
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: None)
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    # 지시 도달 확인은 별도 테스트에서 다룹니다. 여기서는 도달이 확인된 상태를
    # 전제해야 부착 경로 자체를 검증할 수 있습니다.
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_abc",
            "--json",
        ]
    )
    # 고지 전달이 실패했으면 워커가 정본 지시를 못 받았을 수 있으므로 0 이 아니다.
    assert code == 3
    captured = capsys.readouterr()
    assert "tab_not_found" in captured.err
    assert json.loads(captured.out)["capsule_notice"]["status"] == "failed"


def test_cmd_dispatch_no_capsule_notice_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--no-capsule-notice 를 주면 전송을 시도하지 않아야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_send(*a, **k):
        raise AssertionError("--no-capsule-notice 에서는 전송하지 않아야 합니다.")

    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), "")
    )
    monkeypatch.setattr("scripts.orca_taskctl.terminal_send", fail_send)
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    # 지시 도달 확인은 별도 테스트에서 다룹니다. 여기서는 도달이 확인된 상태를
    # 전제해야 부착 경로 자체를 검증할 수 있습니다.
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_abc",
            "--no-capsule-notice",
        ]
    )
    # 고지문을 보내지 않으면 이번 시도의 도달 표지도 없습니다. 증명 수단이
    # 없으므로 성공으로 돌리지 않습니다.
    assert code == 3

    code_allowed = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_abc",
            "--no-capsule-notice",
            "--allow-unverified-delivery",
        ]
    )
    assert code_allowed == 0


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

    code = main(
        [
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
        ]
    )
    assert code == 0
    cmd = calls[0]
    assert cmd[:3] == ["orca", "orchestration", "task-create"]
    spec = cmd[cmd.index("--spec") + 1]
    assert "capsule.yaml" in spec
    assert Path(spec.split("정본 사양(Capsule): ")[1]).is_absolute()
    assert json.loads(capsys.readouterr().out)["task_id"] == "task_created"


def test_cmd_dispatch_reuses_existing_capsule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """--capsule 을 주면 재확장하지 않고 그 파일을 그대로 써야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")
    existing = tmp_path / "premade" / "capsule.yaml"
    existing.parent.mkdir()
    existing.write_text("schema: ORCA_TASK_CAPSULE_V2\nmarker: premade\n", encoding="utf-8")

    def fail_expand(*a, **k):
        raise AssertionError("--capsule 지정 시 재확장해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.expand_intent_to_capsule", fail_expand)
    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker", lambda **k: (0, json.dumps({"ok": True}), "")
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.terminal_send", lambda *a, **k: (0, json.dumps({"ok": True}), "")
    )
    monkeypatch.setattr("scripts.orca_taskctl.resolve_dispatch_id", lambda *a, **k: "ctx_live")
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    # 지시 도달 확인은 별도 테스트에서 다룹니다. 여기서는 도달이 확인된 상태를
    # 전제해야 부착 경로 자체를 검증할 수 있습니다.
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )

    code = main(
        [
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
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["capsule"] == str(existing.resolve())
    assert existing.read_text(encoding="utf-8").endswith("marker: premade\n")


def test_cmd_dispatch_missing_reused_capsule_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """--capsule 이 존재하지 않으면 기동하지 않고 종료 코드 2 로 거부해야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    def fail_dispatch(**k):
        raise AssertionError("Capsule 부재 시 기동해서는 안 됩니다.")

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", fail_dispatch)

    code = main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule",
            str(tmp_path / "nope.yaml"),
            "--terminal",
            "term_abc",
        ]
    )
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

    capsule = expand_intent_to_capsule(
        parse_intent(SAMPLE_REVIEWER_INTENT_VALID), task_id="task_rev"
    )
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


def test_expand_reviewer_has_empty_write_scope():
    """리뷰어는 판정만 하므로 쓰기 범위가 비어 있어야 합니다.

    scope 가 그대로 쓰기 범위가 되면 리뷰어에게 검토 대상을 고칠 권한이
    열립니다. scope 는 검토 대상이므로 읽기로만 갑니다.
    """
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(
        parse_intent(SAMPLE_REVIEWER_INTENT_VALID), task_id="task_rev"
    )
    write_files = parse_capsule_list(capsule, "allowed_write_files")
    read_files = parse_capsule_list(capsule, "allowed_read_files")

    assert write_files == []
    assert "scripts/orca_taskctl.py" in read_files


def test_expand_reviewer_capsule_enumerates_report_fields():
    """계약 이름만으로는 스키마를 모르는 모델을 구속하지 못합니다.

    2026-08-17 측정에서 워커 2대가 checklist_results 대신 checklist 를 쓰고
    verdict 를 객체로 내 기계 집계가 깨졌습니다.
    """
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(
        parse_intent(SAMPLE_REVIEWER_INTENT_VALID), task_id="task_rev"
    )
    assert "report_schema:" in capsule
    assert "checklist_results" in capsule
    assert "checklist 라는 이름을 쓰지 않는다" in capsule
    assert "pass 또는 fail 문자열 하나" in capsule


def test_expand_builder_capsule_enumerates_report_fields():
    """워커 보고도 같은 이유로 필드명을 열거합니다."""
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(parse_intent(SAMPLE_BUILDER_INTENT), task_id="task_b")
    assert "report_schema:" in capsule
    assert "commit_count" in capsule
    assert "checklist_results" not in capsule


def test_expand_read_scope_included_in_search_globs():
    """읽기 전용 경로도 검색 범위에 있어야 워커가 실제로 열어볼 수 있습니다."""
    from scripts.orca_taskctl import expand_intent_to_capsule, parse_intent

    capsule = expand_intent_to_capsule(parse_intent(READ_SCOPE_INTENT), task_id="task_ro")
    glob_block = capsule.split("allowed_globs:")[1].split("forbidden:")[0]
    assert "src/ml/trainer.py" in glob_block


# ---------------------------------------------------------------------------
# 신뢰 확인 대화창 감지
# ---------------------------------------------------------------------------

TRUST_TAIL = (
    "Do you trust the contents of this project?\n"
    "Antigravity CLI requires permission to read, edit, and execute files here.\n"
    "> Yes, I trust this folder\nNo, exit\n"
)
READY_TAIL = "~/orca/workspaces/refac_bid_box/orca-x\n────────\n> "


def _show_payload(tail: str) -> str:
    return json.dumps({"ok": True, "result": {"terminal": {"tail": tail}}})


def test_has_trust_prompt_detects_dialog():
    from scripts.orca_taskctl import has_trust_prompt

    assert has_trust_prompt(TRUST_TAIL) is True
    assert has_trust_prompt(READY_TAIL) is False


def test_approve_trust_prompt_returns_not_present_when_ready(monkeypatch):
    from scripts import orca_taskctl

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda handle, timeout=30: READY_TAIL)
    sent: list[str] = []
    monkeypatch.setattr(
        orca_taskctl, "terminal_send", lambda h, text, timeout=30: sent.append(text) or (0, "", "")
    )

    assert orca_taskctl.approve_trust_prompt("term_x") == "not_present"
    assert sent == [], "대화창이 없으면 아무것도 보내지 않아야 합니다."


def test_approve_trust_prompt_sends_enter_and_confirms(monkeypatch):
    """빈 텍스트에 Enter 를 보내 승인하고 사라진 것을 확인해야 합니다."""
    from scripts import orca_taskctl

    tails = [TRUST_TAIL, READY_TAIL]
    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda handle, timeout=30: tails.pop(0))
    sent: list[str] = []
    monkeypatch.setattr(
        orca_taskctl, "terminal_send", lambda h, text, timeout=30: sent.append(text) or (0, "", "")
    )

    assert orca_taskctl.approve_trust_prompt("term_x") == "approved"
    assert sent == [""], "기본 선택이 신뢰이므로 빈 텍스트 + Enter 만 보냅니다."


def test_approve_trust_prompt_reports_still_present(monkeypatch):
    """승인이 도달하지 않으면 성공으로 보고하지 않습니다."""
    from scripts import orca_taskctl

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda handle, timeout=30: TRUST_TAIL)
    monkeypatch.setattr(orca_taskctl, "terminal_send", lambda h, text, timeout=30: (0, "", ""))

    assert orca_taskctl.approve_trust_prompt("term_x", attempts=2) == "still_present"


def test_approve_trust_prompt_unreadable(monkeypatch):
    from scripts import orca_taskctl

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda handle, timeout=30: None)
    assert orca_taskctl.approve_trust_prompt("term_x") == "unreadable"


def test_terminal_tail_extracts_text(monkeypatch):
    from scripts import orca_taskctl

    monkeypatch.setattr(
        orca_taskctl, "_run_command", lambda cmd, timeout=30: (0, _show_payload("hello"), "")
    )
    assert orca_taskctl.terminal_tail("term_x") == "hello"


def test_terminal_tail_none_on_not_ok(monkeypatch):
    from scripts import orca_taskctl

    monkeypatch.setattr(
        orca_taskctl,
        "_run_command",
        lambda cmd, timeout=30: (0, json.dumps({"ok": False, "error": {"message": "nope"}}), ""),
    )
    assert orca_taskctl.terminal_tail("term_x") is None


def test_cmd_dispatch_aborts_when_trust_prompt_persists(tmp_path: Path, monkeypatch, capsys):
    """대화창이 남아 있으면 Dispatch 를 만들지 않고 종료 코드 2 로 멈춥니다.

    이 상태로 보내면 주입한 지시와 Capsule 고지문이 대화창에 먹혀 사라지고,
    Dispatch 권한만 소비됩니다.
    """
    from scripts import orca_taskctl

    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    monkeypatch.setattr(orca_taskctl, "approve_trust_prompt", lambda h, **kw: "still_present")
    dispatched: list[str] = []
    monkeypatch.setattr(
        orca_taskctl,
        "dispatch_worker",
        lambda **kw: dispatched.append("called") or (0, "{}", ""),
    )
    monkeypatch.setattr(
        orca_taskctl,
        "check_write_concurrency",
        lambda *a, **k: {"allowed": True, "reason": "읽기 전용"},
    )

    code = orca_taskctl.main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--terminal",
            "term_x",
            "--capsule-dir",
            str(tmp_path / "caps"),
            "--task-id",
            "task_trust",
            "--no-probe",
        ]
    )
    assert code == 2
    assert dispatched == [], "대화창이 남아 있으면 Dispatch 를 만들지 않아야 합니다."
    assert "신뢰 확인 대화창이 남아" in capsys.readouterr().err


def test_agent_prompt_ready_markers():
    from scripts.orca_taskctl import agent_prompt_ready

    assert agent_prompt_ready(READY_TAIL) is True
    assert agent_prompt_ready("refac_bid_box % agy --model x") is False
    assert agent_prompt_ready("● Bash(uv run pytest)\n⣾  Running...") is False


def test_approve_trust_prompt_waits_for_dialog_to_appear(monkeypatch):
    """기동 직후 한 번만 보고 판정하면 부팅 중 대화창을 놓칩니다."""
    from scripts import orca_taskctl

    tails = [
        "refac_bid_box % agy --model gemini-3.7-flash-medium",  # 아직 부팅 중
        TRUST_TAIL,  # 대화창 등장
        READY_TAIL,  # 승인 후
    ]
    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda handle, timeout=30: tails.pop(0))
    monkeypatch.setattr(orca_taskctl, "terminal_send", lambda h, text, timeout=30: (0, "", ""))
    monkeypatch.setattr(orca_taskctl.time, "sleep", lambda s: None)

    assert orca_taskctl.approve_trust_prompt("term_x") == "approved"


def test_approve_trust_prompt_not_settled_on_busy_terminal(monkeypatch):
    """이미 작업 중인 터미널은 대화창도 프롬프트도 아니므로 판정을 보류합니다."""
    from scripts import orca_taskctl

    monkeypatch.setattr(
        orca_taskctl, "terminal_tail", lambda handle, timeout=30: "⣾  Generating..."
    )
    monkeypatch.setattr(orca_taskctl.time, "sleep", lambda s: None)

    assert orca_taskctl.approve_trust_prompt("term_x", wait_seconds=0) == "not_settled"


FACTS_INTENT = """schema: ORCA_TASK_INTENT_V1
task_id: f1
role: builder
risk: medium
objective: 동기 호출을 오프로드한다
scope:
  - src/tasks/automation_tasks.py
ground_truth:
  - SessionLocal 세션은 코루틴 사이에 공유되지 않는다
  - src/tasks 에는 to_thread 사용이 0건이다
required_change:
  - runner 호출을 await asyncio.to_thread 로 바꾼다
  - _report 호출을 오프로드한다
acceptance:
  - 전량 테스트 통과
"""


def test_parse_intent_reads_ground_truth_and_required_change():
    intent = parse_intent(FACTS_INTENT)
    assert intent["ground_truth"] == [
        "SessionLocal 세션은 코루틴 사이에 공유되지 않는다",
        "src/tasks 에는 to_thread 사용이 0건이다",
    ]
    assert intent["required_change"] == [
        "runner 호출을 await asyncio.to_thread 로 바꾼다",
        "_report 호출을 오프로드한다",
    ]


def test_expand_injects_coordinator_facts_after_base_facts():
    """코디네이터가 확인한 경계 조건이 Capsule 사실로 실려야 워커가 재조사하지 않습니다."""
    capsule = expand_intent_to_capsule(parse_intent(FACTS_INTENT), run_id="run_x", task_id="f1")
    assert "G1 데이터 무손실" in capsule
    assert "SessionLocal 세션은 코루틴 사이에 공유되지 않는다" in capsule
    assert "src/tasks 에는 to_thread 사용이 0건이다" in capsule
    assert capsule.index("G1 데이터 무손실") < capsule.index("SessionLocal 세션은")


def test_expand_required_change_lists_each_item():
    capsule = expand_intent_to_capsule(parse_intent(FACTS_INTENT), run_id="run_x", task_id="f1")
    assert "runner 호출을 await asyncio.to_thread 로 바꾼다" in capsule
    assert "_report 호출을 오프로드한다" in capsule


def test_expand_falls_back_to_objective_without_required_change():
    text = FACTS_INTENT.split("required_change:")[0] + "acceptance:\n  - 통과\n"
    capsule = expand_intent_to_capsule(parse_intent(text), run_id="run_x", task_id="f1")
    assert "동기 호출을 오프로드한다" in capsule


def test_cmd_dispatch_returns_3_when_delivery_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """워커가 떴어도 지시 도달을 확인하지 못하면 성공(0)으로 보고하지 않습니다.

    2026-08-17 에 신뢰 대화창 때문에 Capsule 지시가 유실된 사고가 있었습니다.
    "워커가 정본 지시를 받았는가" 는 제어 평면의 핵심 불변식이므로 미확인
    상태를 성공과 구분합니다.
    """
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker",
        lambda **kwargs: (0, json.dumps({"ok": True}), ""),
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl._deliver_capsule_notice",
        lambda *a, **k: {
            "status": "sent",
            "dispatch_id": "d1",
            "chars": 10,
            "delivery_probe": "ORCA_DELIVERY_PROBE_test",
        },
    )
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "not_settled")
    # Dispatch 이후에도 주입한 지시가 화면에 나타나지 않은 경우입니다.
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "not_observed"
    )

    argv = [
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--json",
    ]
    assert main(argv) == 3
    assert main([*argv, "--allow-unverified-delivery"]) == 0


def test_cmd_dispatch_not_settled_alone_is_not_a_delivery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Dispatch 전 상태만으로 전달 실패를 단정하면 오탐입니다.

    CLI 가 아직 뜨는 중이어도 주입은 큐에 남아 정상 도달합니다. 2026-08-19
    Dispatch 3회가 전부 이 오탐으로 종료 코드 3 을 냈고, 세 워커 모두 실제로는
    지시를 받아 작업을 마쳤습니다. 사후 확인으로 도달이 보이면 통과입니다.
    """
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(SAMPLE_BUILDER_INTENT, encoding="utf-8")

    monkeypatch.setattr(
        "scripts.orca_taskctl.dispatch_worker",
        lambda **kwargs: (0, json.dumps({"ok": True}), ""),
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl._deliver_capsule_notice",
        lambda *a, **k: {
            "status": "sent",
            "dispatch_id": "d1",
            "chars": 10,
            "delivery_probe": "ORCA_DELIVERY_PROBE_test",
        },
    )
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "not_settled")
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )

    argv = [
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        "term_abc",
        "--json",
    ]
    assert main(argv) == 0


# ---------------------------------------------------------------------------
# 검증 파이프라인 계약 (2026-08-18)
# ---------------------------------------------------------------------------

FINALIZE_CAPSULE = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
task_id: "task_fin"
allowed_write_files:
  - "src/x.py"
verification_commands:
  - "uv run pytest tests/test_x.py -q"
  - "python3 scripts/validate_agent_rules.py --quiet"
"""

FINALIZE_REPORT = """{
  "schema": "ORCA_WORKER_DONE_V2",
  "version": "2.1.0",
  "task_id": "task_fin",
  "status": "succeeded",
  "branch": "b",
  "commit": "abc",
  "commit_count": 1,
  "changed_files": ["src/x.py"],
  "read_files": [],
  "verification": [],
  "verdict": "candidate",
  "blocking_issues": []
}"""


def _finalize_capturing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    """finalize_task 가 하위 도구에 실제로 넘긴 명령을 모아 돌려줍니다."""
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(FINALIZE_CAPSULE, encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(FINALIZE_REPORT, encoding="utf-8")

    captured: list[list[str]] = []

    def mock_run(cmd, cwd=None, timeout=30):
        captured.append(cmd)
        return 0, '{"effective_verdict": "pass", "verdict": "pass"}', ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run)
    # strict 는 리뷰 검증을 포함해야 하므로 리뷰어를 함께 켭니다. 개별
    # 테스트가 kwargs 로 덮어쓸 수 있습니다.
    kwargs.setdefault("run_reviewer", True)
    result = finalize_task(
        report_path=report,
        capsule_path=capsule,
        repo=tmp_path,
        **kwargs,
    )
    return captured, result


def _args_for(script_name: str, captured: list[list[str]]) -> list[str]:
    for cmd in captured:
        if any(script_name in str(part) for part in cmd):
            return [str(part) for part in cmd[2:]]
    raise AssertionError(f"{script_name} 호출이 없습니다")


def test_finalize_reviewer_args_parse_with_real_reviewer_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """finalize 가 Reviewer 에 넘기는 인자가 실제 Reviewer 파서로 파싱되어야 합니다.

    종전에는 --base/--branch 를 넘겼는데 Reviewer 는 --diff-base/--diff-branch 만
    받아 argparse 오류로 Level 2 가 아예 실행되지 못했습니다. mock 만 쓰던
    기존 테스트는 이 불일치를 잡지 못했습니다.
    """
    from scripts.orca_run_reviewer import _parse_args as reviewer_parse_args

    captured, _ = _finalize_capturing(tmp_path, monkeypatch, run_reviewer=True)
    args = _args_for("orca_run_reviewer.py", captured)

    parsed = reviewer_parse_args(args)
    assert parsed.diff_base == "main"
    assert parsed.diff_branch == "HEAD"


def test_finalize_level1_args_carry_capsule_and_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Level 1 호출은 Capsule 경로와 --strict 를 실어 보내야 합니다.

    검증 명령은 게이트가 Capsule 에서 직접 읽습니다. 중간에서 pytest 만 뽑아
    --tests 로 넘기면 npm 등 나머지 검증 명령이 조용히 버려집니다.
    """
    from scripts.orca_level1_gate import parse_arguments as level1_parse_args

    captured, _ = _finalize_capturing(tmp_path, monkeypatch)
    args = _args_for("orca_level1_gate.py", captured)

    parsed = level1_parse_args(args)
    assert parsed.strict is True
    assert parsed.tests == []
    assert parsed.capsule == str(tmp_path / "capsule.yaml")


def test_finalize_allow_skipped_gates_turns_off_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from scripts.orca_level1_gate import parse_arguments as level1_parse_args

    captured, _ = _finalize_capturing(tmp_path, monkeypatch, strict=False)
    parsed = level1_parse_args(_args_for("orca_level1_gate.py", captured))
    assert parsed.strict is False


def test_finalize_rejects_missing_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """없는 작업 트리를 주 저장소로 대체하면 변경분 없는 저장소를 검사하게 됩니다."""
    _captured, result = _finalize_capturing(
        tmp_path, monkeypatch, worktree_path=tmp_path / "does-not-exist"
    )
    assert result["exit_code"] == 2
    assert "작업 트리가 없습니다" in result["level1"]["error"]


def test_worker_report_schema_matches_validator_required_fields():
    """Capsule 이 가르치는 필드와 검증기가 요구하는 필드가 같아야 합니다.

    어긋나면 워커가 지시를 정확히 따를수록 필수 필드 누락으로 거부됩니다.
    """
    from scripts.orca_taskctl import WORKER_REPORT_SCHEMA
    from scripts.summarize_worker_done import REQUIRED_FIELDS

    taught = {
        line.split(":", 1)[0].strip()
        for line in WORKER_REPORT_SCHEMA.splitlines()
        if line.startswith("  ") and ":" in line
    }
    assert set(REQUIRED_FIELDS) <= taught


def test_intent_verification_commands_are_honored():
    """Intent 가 지정한 검증 명령이 템플릿 기본값에 덮이면 안 됩니다."""
    from scripts.orca_taskctl import resolve_verification_commands

    assert resolve_verification_commands(
        {"verification_commands": ["uv run pytest tests/test_x.py -q"]}, ["src/x.py"]
    ) == ["uv run pytest tests/test_x.py -q"]

    # 미지정이면 backend 기본값입니다.
    assert resolve_verification_commands({}, ["src/x.py"]) == DEFAULT_VERIFICATION_COMMANDS


def test_frontend_scope_gets_frontend_verification_commands():
    """frontend 를 고치는 Task 는 frontend 검증 없이 Capsule 이 만들어지면 안 됩니다."""
    from scripts.orca_taskctl import resolve_verification_commands

    commands = resolve_verification_commands({}, ["frontend/src/App.tsx"])
    assert "npm --prefix frontend run test" in commands
    assert "npm --prefix frontend run build" in commands

    # 이미 npm 검증을 직접 지정했으면 덧붙이지 않습니다.
    explicit = resolve_verification_commands(
        {"verification_commands": ["npm --prefix frontend run ci-check"]},
        ["frontend/src/App.tsx"],
    )
    assert explicit == ["npm --prefix frontend run ci-check"]


def test_expand_intent_writes_frontend_verification_into_capsule():
    """Capsule 본문에 frontend 검증 명령이 실제로 실려야 합니다."""
    capsule = expand_intent_to_capsule(
        {"objective": "프론트 수정", "scope": ["frontend/src/App.tsx"]},
        task_id="task_fe",
    )
    commands = parse_capsule_list(capsule, "verification_commands")
    assert "npm --prefix frontend run test" in commands
    assert "npm --prefix frontend run build" in commands


def test_finalize_strict_without_reviewer_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """strict 인데 리뷰어를 돌리지 않으면 리뷰 검증이 통째로 빠집니다.

    Level 1 은 리뷰어보다 먼저 돌아 게이트 5 가 적용 대상이 아니므로, 리뷰
    계약은 리뷰어 실행만이 판정합니다. 그래서 조합을 거부합니다.
    """
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    called: list[str] = []

    def mock_run_command(cmd, cwd=None, timeout=30):
        called.append(cmd[1])
        return 0, "{}", ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=False,
        strict=True,
    )
    assert res["exit_code"] == 2
    assert "--reviewer" in res["level1"]["error"]
    # 거부는 도구를 하나도 돌리기 전에 이루어져야 합니다.
    assert called == []


def test_finalize_non_strict_without_reviewer_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """strict 를 끈 호출은 리뷰어 없이도 기존대로 동작합니다."""
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    seen: list[list[str]] = []

    def mock_run_command(cmd, cwd=None, timeout=30):
        seen.append(cmd)
        if "summarize_worker_done" in cmd[1]:
            return 0, json.dumps({"violations_count": 0, "digest": "요약"}), ""
        return 0, json.dumps({"verdict": "pass"}), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=False,
        strict=False,
    )
    assert res["exit_code"] == 0
    level1_cmd = next(c for c in seen if "orca_level1_gate" in c[1])
    assert "--strict" not in level1_cmd


def test_finalize_never_passes_review_report_to_level1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Level 1 은 리뷰어보다 먼저 돌므로 리뷰 보고 경로를 넘길 수 없습니다.

    넘기도록 되돌리면 아직 만들어지지 않은 파일을 가리켜 도구 오류가 됩니다.
    """
    report_file = tmp_path / "worker_done.json"
    capsule_file = tmp_path / "capsule.yaml"
    report_file.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    capsule_file.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")

    order: list[str] = []

    def mock_run_command(cmd, cwd=None, timeout=30):
        order.append(Path(cmd[1]).stem)
        if "summarize_worker_done" in cmd[1]:
            return 0, json.dumps({"violations_count": 0, "digest": "요약"}), ""
        if "orca_level1_gate" in cmd[1]:
            assert "--review-report" not in cmd
            return 0, json.dumps({"verdict": "pass"}), ""
        return 0, json.dumps({"effective_verdict": "pass"}), ""

    monkeypatch.setattr("scripts.orca_taskctl._run_command", mock_run_command)

    res = finalize_task(
        report_path=report_file,
        capsule_path=capsule_file,
        repo=tmp_path,
        run_reviewer=True,
        strict=True,
    )
    assert res["exit_code"] == 0
    assert order.index("orca_level1_gate") < order.index("orca_run_reviewer")


def test_agent_prompt_ready_recognizes_opencode_status_bar():
    """opencode TUI 는 입력 프롬프트를 단독 `>` 로 그리지 않습니다.

    이 표지를 모르면 opencode 워커가 항상 대기 시간을 다 소진한 뒤
    not_settled 로 판정됩니다. 2026-08-19 Dispatch 3회가 전부 오탐이었습니다.
    """
    from scripts.orca_taskctl import agent_prompt_ready

    antigravity = "배너\n안내\n>"
    opencode = "Build · DeepSeek V4 Flash Free\n  esc interrupt      ctrl+p commands"
    working = "작업 중\n  Generating..."

    assert agent_prompt_ready(antigravity) is True
    assert agent_prompt_ready(opencode) is True
    assert agent_prompt_ready(working) is False


def test_instruction_observed_matches_any_marker():
    from scripts.orca_taskctl import instruction_observed

    text = "=== TASK ===\n정본 사양은 /repo/.orca/capsules/task_abc/capsule.yaml 입니다."
    assert instruction_observed(text, ["/repo/.orca/capsules/task_abc/capsule.yaml"]) is True
    assert instruction_observed(text, ["task_abc"]) is True
    assert instruction_observed(text, ["task_zzz"]) is False
    assert instruction_observed(text, []) is False


def test_delivery_probe_is_unique_per_dispatch():
    """같은 Task 를 재 Dispatch 해도 표지는 매번 달라야 합니다."""
    from scripts.orca_taskctl import DELIVERY_PROBE_PREFIX, new_delivery_probe

    probes = {new_delivery_probe() for _ in range(50)}
    assert len(probes) == 50
    assert all(p.startswith(DELIVERY_PROBE_PREFIX) for p in probes)


def test_capsule_notice_carries_delivery_probe(tmp_path: Path):
    """표지가 고지문에 실려야 사후 화면에서 찾을 수 있습니다."""
    from scripts.orca_taskctl import build_capsule_notice

    text = build_capsule_notice(tmp_path / "capsule.yaml", delivery_probe="ORCA_DELIVERY_PROBE_abc")
    assert "ORCA_DELIVERY_PROBE_abc" in text

    plain = build_capsule_notice(tmp_path / "capsule.yaml")
    assert "ORCA_DELIVERY_PROBE" not in plain


def test_stale_screen_with_old_task_id_is_not_accepted_as_delivery(
    monkeypatch: pytest.MonkeyPatch,
):
    """이전 시도의 잔상을 새 전달로 인정하면 fail-open 입니다.

    task_id 나 Capsule 경로로 판정하면 재 Dispatch 시 화면에 남아 있는 옛
    흔적이 그대로 통과합니다. 실제로는 지시가 도달하지 않았는데 성공으로
    보고됩니다.
    """
    from scripts import orca_taskctl

    stale = "OLD SCREEN: task_abc /tmp/capsule.yaml (이전 시도 잔상)"
    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda h, timeout=30: stale)

    # 이번 시도의 표지는 화면에 없습니다.
    assert (
        orca_taskctl.verify_instruction_delivered(
            "term_x", ["ORCA_DELIVERY_PROBE_new123"], wait_seconds=0
        )
        == "not_observed"
    )

    # 표지가 실제로 도착하면 통과합니다.
    monkeypatch.setattr(
        orca_taskctl,
        "terminal_tail",
        lambda h, timeout=30: stale + " ORCA_DELIVERY_PROBE_new123",
    )
    assert (
        orca_taskctl.verify_instruction_delivered(
            "term_x", ["ORCA_DELIVERY_PROBE_new123"], wait_seconds=0
        )
        == "delivered"
    )


def test_verify_instruction_delivered_returns_delivered(monkeypatch: pytest.MonkeyPatch):
    from scripts import orca_taskctl

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda h, timeout=30: "TASK task_abc 도착")
    assert (
        orca_taskctl.verify_instruction_delivered("term_x", ["task_abc"], wait_seconds=0)
        == "delivered"
    )


def test_verify_instruction_delivered_distinguishes_unreadable_from_not_observed(
    monkeypatch: pytest.MonkeyPatch,
):
    """읽지 못한 것과 읽었는데 없는 것은 다릅니다."""
    from scripts import orca_taskctl

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda h, timeout=30: None)
    assert (
        orca_taskctl.verify_instruction_delivered("term_x", ["task_abc"], wait_seconds=0)
        == "unreadable"
    )

    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda h, timeout=30: "다른 내용")
    assert (
        orca_taskctl.verify_instruction_delivered("term_x", ["task_abc"], wait_seconds=0)
        == "not_observed"
    )


def test_status_bar_readiness_requires_settle_time(monkeypatch: pytest.MonkeyPatch):
    """상태줄 표지는 TUI 가 그려지자마자 나타나므로 즉시 준비로 보면 안 됩니다.

    백엔드가 아직 연결 중인 상태에 주입하면 지시가 삼켜집니다. 2026-08-19 에
    opencode 워커가 실제로 이렇게 지시를 잃었습니다.
    """
    from scripts import orca_taskctl

    clock = {"t": 0.0}
    monkeypatch.setattr(orca_taskctl.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        orca_taskctl.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s)
    )
    monkeypatch.setattr(
        orca_taskctl,
        "terminal_tail",
        lambda h, timeout=30: "본문\n  esc interrupt  ctrl+p commands",
    )

    status = orca_taskctl.approve_trust_prompt("term_x", wait_seconds=60, poll_seconds=1)
    assert status == "not_present"
    # 표지를 처음 본 순간이 아니라 안정화 시간이 지난 뒤에 인정해야 합니다.
    assert clock["t"] >= orca_taskctl.AGENT_READY_SETTLE_SECONDS


def test_input_caret_readiness_is_immediate(monkeypatch: pytest.MonkeyPatch):
    """단독 `>` 프롬프트는 입력 대기가 확실하므로 기다리지 않습니다."""
    from scripts import orca_taskctl

    clock = {"t": 0.0}
    monkeypatch.setattr(orca_taskctl.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        orca_taskctl.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s)
    )
    monkeypatch.setattr(orca_taskctl, "terminal_tail", lambda h, timeout=30: "배너\n>")

    assert (
        orca_taskctl.approve_trust_prompt("term_x", wait_seconds=60, poll_seconds=1)
        == "not_present"
    )
    assert clock["t"] == 0.0


def test_delivery_probe_polling_is_frequent_enough():
    """표지는 워커 출력에 금방 밀려나므로 폴링이 촘촘해야 합니다.

    2026-08-19 실측에서 3초 간격으로는 Gemini 워커의 표지를 놓쳐 도달했는데도
    not_observed 로 판정했습니다.
    """
    import inspect as _inspect

    from scripts.orca_taskctl import verify_instruction_delivered

    default = _inspect.signature(verify_instruction_delivered).parameters["poll_seconds"].default
    assert default <= 1.0
