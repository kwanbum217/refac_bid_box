from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.orca_contract import char_len
from scripts.orca_run_reviewer import (
    DEFAULT_MAX_DIFF_CHARS,
    _extract_capsule_context,
    _parse_args,
    build_prompt,
    extract_json_from_response,
    get_git_diff_and_files,
    main,
    run_reviewer,
)

SAMPLE_CAPSULE_VALID = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: reviewer
task_id: "task_test_001"

review_checklist:
  - id: "C1"
    question: "테스트가 모두 작성되었는가?"
    defect_when: "no"
  - id: "C2"
    question: "금지 행위를 위반하였는가?"
    defect_when: "yes"
"""

SAMPLE_CAPSULE_EMPTY_CHECKLIST = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: reviewer
task_id: "task_test_002"

review_checklist: []
"""

SAMPLE_VALID_REPORT = {
    "schema": "ORCA_REVIEW_DONE_V2",
    "version": "2.1.0",
    "verdict": "pass",
    "checklist_results": [
        {
            "id": "C1",
            "answer": "yes",
            "evidence": "tests/test_foo.py:10 - 테스트 존재 확인",
        },
        {
            "id": "C2",
            "answer": "no",
            "evidence": "AGENTS.md 금지 규칙 위반 없음 확인",
        },
    ],
    "blocking_issues": [],
    "unverified_claims": [],
    "missing_tests": [],
}


@pytest.fixture
def mock_git(monkeypatch):
    """git 호출을 가로채서 더미 변경 파일과 diff 를 돌려줍니다."""
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (
            ["scripts/new_file.py", "tests/test_new_file.py"],
            "diff --git a/scripts/new_file.py b/scripts/new_file.py\n+def foo(): pass\n",
        ),
    )


def test_zero_checklist_exits_code_2_without_model_call(tmp_path, mock_git):
    """(1) 체크리스트가 0개이면 모델을 호출하지 않고 종료 코드 2로 종료합니다."""
    capsule_file = tmp_path / "capsule_empty.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_EMPTY_CHECKLIST, encoding="utf-8")
    out_file = tmp_path / "out.json"

    model_called = False

    def dummy_runner(prompt, model, timeout):
        nonlocal model_called
        model_called = True
        return 0, "{}", ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 2
    assert not model_called
    assert "review_checklist" in output or "0개" in output


def test_successful_review_writes_json_and_exits_0(tmp_path, mock_git):
    """(2) 정상 응답이면 --out 에 JSON 이 쓰이고 종료 코드 0으로 종료합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    response_json = json.dumps(SAMPLE_VALID_REPORT, ensure_ascii=False)

    def dummy_runner(prompt, model, timeout):
        return 0, response_json, ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["schema"] == "ORCA_REVIEW_DONE_V2"
    assert saved["verdict"] == "pass"
    assert "Orca Level 2 Reviewer 판정 결과" in output
    assert "최종 판정: 통과 (pass)" in output


def test_defect_without_blocking_issues_fails_contract_with_exit_1(tmp_path, mock_git):
    """(3) 결함을 답했는데 blocking_issues 에 id 가 없으면 계약 위반으로 종료 코드 1이 됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    defect_report = {
        "schema": "ORCA_REVIEW_DONE_V2",
        "version": "2.1.0",
        "verdict": "fail",
        "checklist_results": [
            {
                "id": "C1",
                "answer": "no",  # defect_when is "no" -> defect!
                "evidence": "테스트 누락됨",
            },
            {
                "id": "C2",
                "answer": "no",
                "evidence": "규칙 준수",
            },
        ],
        "blocking_issues": [],  # C1 should be here, but missing -> Condition 3 violation!
    }

    def dummy_runner(prompt, model, timeout):
        return 0, json.dumps(defect_report), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 1
    assert "조건3 위반: C1 이 결함인데 blocking_issues 에 없음" in output
    assert "최종 판정: 반려/위반 (fail)" in output


def test_json_extraction_from_code_fence(tmp_path, mock_git):
    """(4) 마크다운 코드펜스(```json)로 감싼 응답에서도 JSON 추출이 성공합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    raw_response = f"""리뷰 결과를 보고합니다.
```json
{json.dumps(SAMPLE_VALID_REPORT, ensure_ascii=False, indent=2)}
```
이상입니다."""

    def dummy_runner(prompt, model, timeout):
        return 0, raw_response, ""

    code, _output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["schema"] == "ORCA_REVIEW_DONE_V2"


def test_json_extraction_with_surrounding_text(tmp_path, mock_git):
    """(5) 앞뒤에 설명 텍스트가 붙은 응답에서도 JSON 추출이 성공합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    raw_response = (
        "다음은 검토 결과 JSON 입니다.\n\n"
        + json.dumps(SAMPLE_VALID_REPORT, ensure_ascii=False)
        + "\n\n검토 완료되었습니다."
    )

    def dummy_runner(prompt, model, timeout):
        return 0, raw_response, ""

    code, _output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert out_file.exists()


def test_broken_json_saves_raw_file_and_exits_2(tmp_path, mock_git):
    """(6) 깨진 JSON 이면 .raw 파일이 남고 종료 코드 2로 종료합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"
    raw_file = Path(str(out_file) + ".raw")

    broken_response = '{"schema": "ORCA_REVIEW_DONE_V2", "invalid": \\D}'

    def dummy_runner(prompt, model, timeout):
        return 0, broken_response, ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 2
    assert raw_file.exists()
    assert raw_file.read_text(encoding="utf-8") == broken_response
    assert "JSON 파싱 실패" in output


def test_diff_exceeding_max_diff_chars_is_truncated_and_flagged(tmp_path, monkeypatch):
    """(7) diff 가 상한을 넘으면 프롬프트에 절단 표시가 들어가고 판정 블록에도 표시됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    huge_diff = "diff --git a/huge.py b/huge.py\n" + ("+line\n" * 20000)

    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (["huge.py"], huge_diff),
    )

    captured_prompt = ""

    def dummy_runner(prompt, model, timeout):
        nonlocal captured_prompt
        captured_prompt = prompt
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        max_diff_chars=500,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert "절단되었습니다" in captured_prompt
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output


def test_massive_violations_respects_max_chars_and_keeps_total_count(
    tmp_path, mock_git, monkeypatch
):
    """(8) 거대한 위반 목록에도 사람 출력이 --max-chars 이하이고 위반 총건수가 남습니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    # evaluate 결과를 30개의 긴 위반 목록으로 조작
    many_violations = [f"조건1 위반: 긴 위반 설명 메시지 번호 {i} " + "A" * 50 for i in range(30)]
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.evaluate",
        lambda cl, rep: {
            "checklist_count": 2,
            "results_count": 2,
            "defect_ids": [],
            "blocking_count": 0,
            "declared_verdict": "pass",
            "effective_verdict": "fail",
            "violations": many_violations,
            "ok": False,
        },
    )

    def dummy_runner(prompt, model, timeout):
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    max_limit = 800
    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        max_chars=max_limit,
        model_runner=dummy_runner,
    )

    assert code == 1
    assert char_len(output) <= max_limit
    assert "계약 위반 (30건):" in output
    assert "... 외" in output
    assert "생략" in output


def test_dry_run_does_not_call_model(tmp_path, mock_git):
    """(9) --dry-run 은 모델을 호출하지 않고 조립된 프롬프트와 문자 수를 출력합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    model_called = False

    def dummy_runner(prompt, model, timeout):
        nonlocal model_called
        model_called = True
        return 0, "{}", ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        dry_run=True,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert not model_called
    assert "[Dry-run 완료] 프롬프트 문자 수:" in output
    assert "=== 검토 대상 변경 파일 목록 ===" in output


def test_model_call_timeout_returns_code_2(tmp_path, mock_git):
    """(10) 모델 호출 타임아웃 발생 시 종료 코드 2를 반환합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    def dummy_runner(prompt, model, timeout):
        return -1, "", "Timeout expired"

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        timeout=10,
        model_runner=dummy_runner,
    )

    assert code == 2
    assert "타임아웃" in output


def test_json_output_mode_returns_valid_json(tmp_path, mock_git):
    """(11) --json 옵션 사용 시 유효한 JSON 형식으로 결과를 출력합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    def dummy_runner(prompt, model, timeout):
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        as_json=True,
        model_runner=dummy_runner,
    )

    assert code == 0
    parsed = json.loads(output)
    assert parsed["model"] == "gemini-3.7-flash-high"
    assert parsed["checklist_count"] == 2
    assert parsed["ok"] is True
    assert parsed["exit_code"] == 0
    assert parsed["declared_verdict"] == "pass"
    assert parsed["effective_verdict"] == "pass"


def test_extract_json_from_response_edge_cases():
    """JSON 추출 함수의 다양한 엣지 케이스를 검증합니다."""
    # 1. 빈 문자열
    data, err = extract_json_from_response("")
    assert data is None
    assert "비어 있음" in err

    # 2. 중괄호 없음
    data, err = extract_json_from_response("no json here")
    assert data is None
    assert "중괄호" in err

    # 3. 배열 형태
    data, err = extract_json_from_response("[1, 2, 3]")
    assert data is None
    assert "객체" in err

    # 4. 정상 파싱
    data, err = extract_json_from_response('prefix {"a": 1, "b": "hello"} suffix')
    assert data == {"a": 1, "b": "hello"}
    assert err == ""


def test_main_cli_invocation(tmp_path, monkeypatch):
    """main() CLI 진입점의 인자 파싱 및 정상 실행을 검증합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (["file.py"], "diff"),
    )
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.run_model",
        lambda prompt, model, timeout: (0, json.dumps(SAMPLE_VALID_REPORT), ""),
    )

    code = main(
        [
            "--capsule",
            str(capsule_file),
            "--out",
            str(out_file),
            "--dry-run",
        ]
    )
    assert code == 0


def test_default_max_diff_chars_is_20000():
    """(12) DEFAULT_MAX_DIFF_CHARS 가 설계 권장값인 20000 이어야 합니다."""
    assert DEFAULT_MAX_DIFF_CHARS == 20000


def test_build_prompt_includes_how_field_when_present():
    """(13) checklist 항목에 how 필드가 있으면 build_prompt 출력에 검증 방법(how) 이 포함됩니다."""
    checklist = [
        {
            "id": "C1",
            "question": "테스트가 모두 작성되었는가?",
            "defect_when": "no",
            "how": "tests/ 디렉터리에서 신규 함수 대응 테스트 파일 존재 확인",
        }
    ]
    prompt = build_prompt(checklist=checklist, changed_files=[], diff_text="diff sample")
    assert "검증 방법(how): tests/ 디렉터리에서 신규 함수 대응 테스트 파일 존재 확인" in prompt
    assert "결함 조건(defect_when): no" in prompt


def test_build_prompt_excludes_how_section_when_absent():
    """(14) checklist 항목에 how 필드가 없으면 검증 방법 행 자체가 출력되지 않습니다."""
    checklist = [{"id": "C1", "question": "규칙을 준수하였는가?", "defect_when": "no"}]
    prompt = build_prompt(checklist=checklist, changed_files=[], diff_text="diff sample")
    assert "검증 방법(how):" not in prompt


def test_build_prompt_includes_capsule_context_fields():
    """(15) capsule_context 에 objective, acceptance, ground_truth, allowed_write_files 가 있으면
    프롬프트에 Task 컨텍스트 섹션과 해당 값들이 포함됩니다."""
    checklist = [{"id": "C1", "question": "Q?", "defect_when": "no"}]
    context = {
        "objective": "objective: 리뷰어 프롬프트를 개선한다",
        "acceptance": "acceptance:\n  - build_prompt 출력에 how 포함",
        "ground_truth": "ground_truth:\n  - fact: DEFAULT_MAX_DIFF_CHARS = 20000",
        "allowed_write_files": "allowed_write_files:\n  - scripts/orca_run_reviewer.py",
    }
    prompt = build_prompt(
        checklist=checklist,
        changed_files=[],
        diff_text="diff sample",
        capsule_context=context,
    )
    assert "=== Task 컨텍스트 ===" in prompt
    assert "objective: 리뷰어 프롬프트를 개선한다" in prompt
    assert "acceptance:" in prompt
    assert "ground_truth:" in prompt
    assert "allowed_write_files:" in prompt


def test_extract_capsule_context_extracts_known_fields():
    """(16) _extract_capsule_context 가 objective, acceptance, ground_truth, allowed_write_files 를 추출합니다."""
    capsule_yaml = """schema: ORCA_TASK_CAPSULE_V2
objective: >
  리뷰어 프롬프트 개선

acceptance:
  - build_prompt 출력에 how 포함
  - DEFAULT_MAX_DIFF_CHARS == 20000

ground_truth:
  - fact: "DEFAULT_MAX_DIFF_CHARS = 60000"

allowed_write_files:
  - scripts/orca_run_reviewer.py

review_checklist:
  - id: "C1"
    question: "Q?"
    defect_when: "no"
"""
    ctx = _extract_capsule_context(capsule_yaml)
    assert "objective" in ctx
    assert "acceptance" in ctx
    assert "ground_truth" in ctx
    assert "allowed_write_files" in ctx
    assert "리뷰어 프롬프트 개선" in ctx["objective"]
    assert "scripts/orca_run_reviewer.py" in ctx["allowed_write_files"]


def test_max_diff_chars_large_no_truncation(tmp_path, monkeypatch):
    """(17) max_diff_chars 를 크게 주면 diff 가 절단되지 않고 정상으로 보고됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    diff_content = "+line\n" * 100  # 약 600자
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (
            ["scripts/new_file.py"],
            diff_content,
        ),
    )

    def dummy_runner(prompt, model, timeout):
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        max_diff_chars=5000,
        model_runner=dummy_runner,
    )
    assert code == 0
    assert "Diff 절단 여부:     정상 (전체 포함)" in output


def test_max_diff_chars_small_triggers_truncation(tmp_path, monkeypatch):
    """(18) max_diff_chars 를 작게 주면 diff 가 절단되고 판정 블록에 절단됨이 기록됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    diff_content = "+line\n" * 100  # 약 600자
    captured_prompt = ""

    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (
            ["scripts/new_file.py"],
            diff_content,
        ),
    )

    def dummy_runner(prompt, model, timeout):
        nonlocal captured_prompt
        captured_prompt = prompt
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        max_diff_chars=50,
        model_runner=dummy_runner,
    )
    assert code == 0
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output
    assert "[주의: diff 본문이 최대 허용 크기(50자)를 초과하여" in captured_prompt


def test_max_diff_chars_default_value_is_20000():
    """(19) CLI 인자 파서에서 --max-diff-chars 의 기본값은 20000 (DEFAULT_MAX_DIFF_CHARS) 입니다."""
    args = _parse_args(["--capsule", "cap.yaml", "--out", "out.json"])
    assert args.max_diff_chars == 20000
    assert args.max_diff_chars == DEFAULT_MAX_DIFF_CHARS


def test_paths_filter_narrows_changed_files_and_diff(tmp_path, monkeypatch):
    """(20) --paths 로 경로를 좁히면 changed_files 와 diff 가 해당 경로로 제한되어 프롬프트에 전달됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    captured_paths = None
    captured_prompt = ""

    def mock_get_diff(repo, base, branch, paths=None, timeout=10):
        nonlocal captured_paths
        captured_paths = paths
        # paths 에 전달된 파일만 반환
        return (
            [p for p in ["scripts/target.py", "tests/other.py"] if paths and p in paths],
            "diff --git a/scripts/target.py\n+target_content\n",
        )

    monkeypatch.setattr("scripts.orca_run_reviewer.get_git_diff_and_files", mock_get_diff)

    def dummy_runner(prompt, model, timeout):
        nonlocal captured_prompt
        captured_prompt = prompt
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, _output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        paths=["scripts/target.py"],
        model_runner=dummy_runner,
    )
    assert code == 0
    assert captured_paths == ["scripts/target.py"]
    assert "- scripts/target.py" in captured_prompt
    assert "- tests/other.py" not in captured_prompt


def test_paths_filter_empty_diff_exits_code_2(tmp_path, monkeypatch):
    """(21) --paths 로 좁힌 결과가 빈 diff 이면 조용히 pass 하지 않고 종료 코드 2로 거부합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    # 빈 diff 반환 mock
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: ([], ""),
    )

    model_called = False

    def dummy_runner(prompt, model, timeout):
        nonlocal model_called
        model_called = True
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        paths=["nonexistent_module.py"],
        model_runner=dummy_runner,
    )
    assert code == 2
    assert not model_called
    assert "변경 사항(diff)이 없습니다" in output

    # JSON 모드 확인
    code_json, output_json = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        paths=["nonexistent_module.py"],
        as_json=True,
        model_runner=dummy_runner,
    )
    assert code_json == 2
    data = json.loads(output_json)
    assert data["exit_code"] == 2
    assert "nonexistent_module.py" in data["error"]


def test_get_git_diff_and_files_command_assembly(monkeypatch):
    """(22) get_git_diff_and_files 에 paths 가 주어지면 git diff 에 -- <paths> 가 정확히 전달됩니다."""
    executed_cmds: list[list[str]] = []

    def mock_run_cmd(cmd, cwd, timeout):
        executed_cmds.append(cmd)
        if "--name-only" in cmd:
            return 0, "src/foo.py\nsrc/bar.py\n", "", False
        return 0, "diff content", "", False

    monkeypatch.setattr("scripts.orca_run_reviewer.run_command_safe", mock_run_cmd)

    files, diff = get_git_diff_and_files(
        repo=Path("."),
        base="main",
        branch="HEAD",
        paths=["src/foo.py", "src/bar.py"],
    )
    assert files == ["src/foo.py", "src/bar.py"]
    assert diff == "diff content"
    assert len(executed_cmds) == 2
    assert executed_cmds[0] == [
        "git",
        "diff",
        "--name-only",
        "main...HEAD",
        "--",
        "src/foo.py",
        "src/bar.py",
    ]
    assert executed_cmds[1] == ["git", "diff", "main...HEAD", "--", "src/foo.py", "src/bar.py"]


def test_cli_paths_and_max_diff_chars_dry_run(tmp_path, capsys, monkeypatch):
    """(23) CLI 에서 --paths 와 --max-diff-chars 인자가 전달되고 dry-run 에서 정상 처리되는지 검증."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (
            ["src/foo.py"],
            "+line\n",
        ),
    )

    code = main(
        [
            "--capsule",
            str(capsule_file),
            "--out",
            str(out_file),
            "--paths",
            "src/foo.py",
            "--max-diff-chars",
            "50000",
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["dry_run"] is True
    assert data["char_count"] > 0
