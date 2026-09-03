from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.orca_contract import char_len
from scripts.orca_run_reviewer import (
    DEFAULT_MAX_DIFF_CHARS,
    ReviewerToolError,
    _extract_capsule_context,
    _parse_args,
    build_cli_command,
    build_model_command,
    build_prompt,
    extract_json_from_response,
    get_git_diff_and_files,
    main,
    run_model,
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
    """(7) diff 가 상한을 넘으면 절단이 표시되고, 기본적으로 통과 판정을 막습니다.

    절단된 diff 로 내린 pass 는 리뷰어가 보지 못한 부분에 대한 판정이 아니므로
    병합 근거가 될 수 없습니다. 그대로 받아들이려면 명시적으로 허용해야 합니다.
    """
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

    assert code == 1
    assert "절단되었습니다" in captured_prompt
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output
    assert "리뷰 범위가 불완전" in output

    allowed_code, allowed_output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        max_diff_chars=500,
        allow_truncated_diff=True,
        model_runner=dummy_runner,
    )
    assert allowed_code == 0
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in allowed_output


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
    assert parsed["model"] == "gemini-3.8-flash-high"
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


def test_default_max_diff_chars_is_50000():
    """(12) DEFAULT_MAX_DIFF_CHARS 가 실측 최대 38,401 자를 여유 있게 넘는 50000 이어야 합니다."""
    assert DEFAULT_MAX_DIFF_CHARS == 50000


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
    """(18) max_diff_chars 를 작게 주면 diff 가 절단되고 판정 블록에 절단됨이 기록됩니다.

    절단 자체가 통과를 막으므로 종료 코드는 1 입니다.
    """
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
    assert code == 1
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output
    assert "[주의: diff 본문이 최대 허용 크기(50자)를 초과하여" in captured_prompt


def test_max_diff_chars_default_value_is_50000():
    """(19) CLI 인자 파서에서 --max-diff-chars 의 기본값은 50000 (DEFAULT_MAX_DIFF_CHARS) 입니다."""
    args = _parse_args(["--capsule", "cap.yaml", "--out", "out.json"])
    assert args.max_diff_chars == 50000
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


def test_build_model_command_gemini_generates_agy_command():
    """(24) gemini 모델 ID 가 agy 명령 배열을 생성합니다."""
    prompt = "Review this code"
    cmd = build_model_command("gemini-3.7-flash-high", prompt, timeout=300)
    assert cmd == [
        "agy",
        "--model",
        "gemini-3.7-flash-high",
        "--print",
        prompt,
        "--print-timeout",
        "300s",
    ]


def test_build_model_command_claude_generates_agy_command():
    """(25) claude 모델 ID 가 agy 명령 배열을 생성합니다."""
    prompt = "Review this code"
    cmd = build_model_command("claude-sonnet-4-6", prompt, timeout=120)
    assert cmd == [
        "agy",
        "--model",
        "claude-sonnet-4-6",
        "--print",
        prompt,
        "--print-timeout",
        "120s",
    ]


def test_build_model_command_cerebras_generates_agy_command():
    """(26) cerebras 모델 ID 가 agy 명령 배열을 생성합니다."""
    prompt = "Review this code"
    cmd = build_model_command("cerebras/gpt-oss-120b", prompt, timeout=60)
    assert cmd == [
        "agy",
        "--model",
        "cerebras/gpt-oss-120b",
        "--print",
        prompt,
        "--print-timeout",
        "60s",
    ]


def test_build_model_command_qwen_generates_qwen_dash_p_and_no_dash_i():
    """(27) qwen 계열 모델이 qwen -m <id> -p 명령을 만들고 -i 플래그를 쓰지 않습니다."""
    prompt = "Review this code"
    models_to_test = ["qwen3.7-plus", "qwen-plus", "deepseek-v4-pro", "glm-5.2"]

    for model_id in models_to_test:
        cmd = build_model_command(model_id, prompt, timeout=600)
        assert cmd == ["qwen", "-m", model_id, "-p", prompt]
        assert "-p" in cmd
        assert "-i" not in cmd
        assert cmd[0] == "qwen"


def test_build_model_command_unsupported_provider_raises_exception():
    """(28) 지원하지 않는 provider 는 예외가 발생하고 조용히 agy 로 흘러가지 않습니다."""
    unsupported_models = [
        ("gpt-5.6-terra", "codex"),
        ("cursor-agent/auto", "cursor"),
        ("opencode/deepseek-v4-flash-free", "opencode"),
        ("or-free/nemotron-ultra", "kimi-openrouter"),
    ]

    for model_id, expected_provider in unsupported_models:
        with pytest.raises(ReviewerToolError) as exc_info:
            build_model_command(model_id, "prompt")

        err_msg = str(exc_info.value)
        assert model_id in err_msg
        assert expected_provider in err_msg
        assert "지원하지 않는 제공자" in err_msg or "지원 제공자 목록" in err_msg


def test_build_model_command_unresolvable_model_raises_exception():
    """(29) 판정 불가 모델 ID 도 예외가 발생하고 예외 메시지에 모델 ID 가 포함됩니다."""
    unresolvable_model = "completely-unknown-custom-model-999"
    with pytest.raises(ReviewerToolError) as exc_info:
        build_model_command(unresolvable_model, "prompt")

    err_msg = str(exc_info.value)
    assert unresolvable_model in err_msg


def test_existing_agy_argument_structure_unchanged():
    """(30) 기존 agy 경로의 인자 형태(순서 및 플래그 이름)가 변경되지 않았습니다."""
    prompt = "Sample prompt"
    cmd = build_model_command("gemini-3.7-flash-high", prompt, timeout=600)
    assert cmd[0] == "agy"
    assert cmd[1] == "--model"
    assert cmd[2] == "gemini-3.7-flash-high"
    assert cmd[3] == "--print"
    assert cmd[4] == prompt
    assert cmd[5] == "--print-timeout"
    assert cmd[6] == "600s"
    assert len(cmd) == 7


def test_build_cli_command_alias():
    """(31) build_cli_command 별칭이 build_model_command 와 동일하게 작동합니다."""
    prompt = "Sample prompt"
    cmd1 = build_model_command("qwen3.7-plus", prompt)
    cmd2 = build_cli_command("qwen3.7-plus", prompt)
    assert cmd1 == cmd2 == ["qwen", "-m", "qwen3.7-plus", "-p", prompt]


def test_run_model_file_not_found_reports_correct_cli_name(monkeypatch):
    """(32) 실행 파일 없음(FileNotFoundError) 발생 시 실제로 호출한 CLI 이름을 정확히 보고합니다."""

    def mock_subprocess_run(cmd, capture_output=True, text=True, timeout=None, check=False):
        raise FileNotFoundError("command not found")

    monkeypatch.setattr("scripts.orca_run_reviewer.subprocess.run", mock_subprocess_run)

    # qwen 모델 호출 시: (qwen) 으로 보고되어야 함
    code_qwen, _stdout_qwen, stderr_qwen = run_model("prompt", model="qwen3.7-plus")
    assert code_qwen == -2
    assert "실행 파일을 찾을 수 없음 (qwen)" in stderr_qwen
    assert "실행 파일을 찾을 수 없음 (agy)" not in stderr_qwen

    # gemini 모델 호출 시: (agy) 로 보고되어야 함
    code_gemini, _stdout_gemini, stderr_gemini = run_model("prompt", model="gemini-3.7-flash-high")
    assert code_gemini == -2
    assert "실행 파일을 찾을 수 없음 (agy)" in stderr_gemini


def test_run_model_unsupported_model_returns_code_minus_2():
    """(33) 지원하지 않는 모델로 run_model 호출 시 종료 코드 -2와 에러 메시지를 반환합니다."""
    code, stdout, stderr = run_model("prompt", model="unsupported-model-xyz")
    assert code == -2
    assert stdout == ""
    assert "unsupported-model-xyz" in stderr
    assert "모델 명령 생성 실패" in stderr


def test_real_world_max_diff_38401_not_truncated_at_default(tmp_path, monkeypatch):
    """(34) 실측 최대치 38,401 자 diff 가 기본값 (50,000 자) 에서 절단되지 않습니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    real_world_diff = "+line\n" * 7680  # 7680 * 5 = 38,400 자 + header line
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (["large.py"], real_world_diff),
    )

    captured_prompt = ""

    def dummy_runner(prompt, model, timeout):
        nonlocal captured_prompt
        captured_prompt = prompt
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert "절단되었습니다" not in captured_prompt
    assert "Diff 절단 여부:     정상 (전체 포함)" in output


def test_diff_exceeding_new_default_is_truncated_and_blocks_pass(tmp_path, monkeypatch):
    """(35) 새 기본값 50,000 자를 초과하는 diff 는 절단되고 exit_code 가 1 입니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    huge_diff = "+x\n" * 30000  # 90,000 자 > 50,000 자
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
        model_runner=dummy_runner,
    )

    assert code == 1
    assert "절단되었습니다" in captured_prompt
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output
    assert "리뷰 범위가 불완전" in output


def test_allow_truncated_diff_permits_exit_code_zero_on_oversized_diff(tmp_path, monkeypatch):
    """(36) --allow-truncated-diff 를 주면 50,000 자 초과 diff 도 절단 후 exit_code 0 이 됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    huge_diff = "+x\n" * 30000  # 90,000 자 > 50,000 자
    monkeypatch.setattr(
        "scripts.orca_run_reviewer.get_git_diff_and_files",
        lambda repo, base, branch, paths=None, timeout=10: (["huge.py"], huge_diff),
    )

    def dummy_runner(prompt, model, timeout):
        return 0, json.dumps(SAMPLE_VALID_REPORT), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        allow_truncated_diff=True,
        model_runner=dummy_runner,
    )

    assert code == 0
    assert "Diff 절단 여부:     절단됨 (상한 초과)" in output


def test_extract_json_parses_first_complete_json_object_with_trailing_data():
    """(37) 다중 JSON 객체 및 후속 데이터가 있어도 첫 번째 완전한 JSON 객체만 정상 추출합니다."""
    # 1. 다중 JSON 객체 연결
    multi_json = '{"a": 1, "b": "first"} {"c": 2, "d": "second"}'
    data, err = extract_json_from_response(multi_json)
    assert err == ""
    assert data == {"a": 1, "b": "first"}

    # 2. 설명 텍스트 + 다중 JSON 객체
    surrounded_multi = (
        "리뷰 결과입니다.\n"
        '{"schema": "ORCA_REVIEW_DONE_V2", "verdict": "pass"}\n'
        '{"extra_info": "ignored"}\n'
        "이상입니다."
    )
    data, err = extract_json_from_response(surrounded_multi)
    assert err == ""
    assert data == {"schema": "ORCA_REVIEW_DONE_V2", "verdict": "pass"}

    # 3. 앞쪽에 유효하지 않은 중괄호 텍스트가 있고 뒤에 유효한 JSON 이 오는 경우
    invalid_then_valid = '다음은 {잘못된 텍스트} 이며 진짜는: {"valid": true} 입니다.'
    data, err = extract_json_from_response(invalid_then_valid)
    assert err == ""
    assert data == {"valid": True}


def test_retry_on_parse_failure_succeeds_on_second_attempt(tmp_path, mock_git):
    """(38) 첫 번째 응답이 깨진 JSON 이어도 1회 재시도에서 유효한 JSON 을 받으면 성공(0) 처리됩니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    call_count = 0

    def mock_runner(prompt, model, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 0, "깨진 응답: {invalid json", ""
        return 0, json.dumps(SAMPLE_VALID_REPORT, ensure_ascii=False), ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=mock_runner,
    )

    assert code == 0
    assert call_count == 2
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["schema"] == "ORCA_REVIEW_DONE_V2"
    assert "최종 판정: 통과 (pass)" in output


def test_retry_on_parse_failure_fails_after_exactly_one_retry(tmp_path, mock_git):
    """(39) 재시도에서도 JSON 파싱이 실패하면 정확히 2회 호출 후 종료 코드 2 로 실패합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"
    raw_file = Path(str(out_file) + ".raw")

    call_count = 0

    def mock_runner(prompt, model, timeout):
        nonlocal call_count
        call_count += 1
        return 0, f"깨진 응답 회차 {call_count}: {{bad: json}}", ""

    code, output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        repo=tmp_path,
        model_runner=mock_runner,
    )

    assert code == 2
    assert call_count == 2
    assert raw_file.exists()
    assert "깨진 응답 회차 2" in raw_file.read_text(encoding="utf-8")
    assert "JSON 파싱 실패" in output

    # .orca/reports/ 아래에도 타임스탬프 .raw 파일이 생성되었는지 검증
    reports_dir = tmp_path / ".orca" / "reports"
    assert reports_dir.exists()
    report_raw_files = list(reports_dir.glob("*.raw"))
    assert len(report_raw_files) == 1
    assert "깨진 응답 회차 2" in report_raw_files[0].read_text(encoding="utf-8")


def test_no_retry_when_first_attempt_succeeds(tmp_path, mock_git):
    """(40) 첫 번째 시도에서 정상 파싱되면 추가 재시도 없이 1회만 호출합니다."""
    capsule_file = tmp_path / "capsule.yaml"
    capsule_file.write_text(SAMPLE_CAPSULE_VALID, encoding="utf-8")
    out_file = tmp_path / "out.json"

    call_count = 0

    def mock_runner(prompt, model, timeout):
        nonlocal call_count
        call_count += 1
        return 0, json.dumps(SAMPLE_VALID_REPORT, ensure_ascii=False), ""

    code, _output = run_reviewer(
        capsule=capsule_file,
        out=out_file,
        model_runner=mock_runner,
    )

    assert code == 0
    assert call_count == 1


def test_build_model_command_supported_independent_reviewer_models():
    """(41) 지원되는 독립 리뷰어 모델들이 올바른 CLI 명령어로 빌드됩니다."""
    cmd_qwen = build_model_command("qwen3.7-plus", "test prompt")
    assert cmd_qwen[0] == "qwen"
    assert "test prompt" in cmd_qwen

    cmd_gemini = build_model_command("gemini-3.7-flash-high", "test prompt")
    assert cmd_gemini[0] == "agy"
    assert "test prompt" in cmd_gemini
