from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.orca_contract import char_len
from scripts.orca_run_reviewer import (
    extract_json_from_response,
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
        lambda repo, base, branch, timeout: (
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
        lambda repo, base, branch, timeout: (["huge.py"], huge_diff),
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
        lambda repo, base, branch, timeout: (["file.py"], "diff"),
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
