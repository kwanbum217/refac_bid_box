from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.run_level3_reduction_experiment import (
    CLEAN_FIXTURE,
    DEFECTIVE_FIXTURE,
    create_seeded_repo,
    main,
    run_experiment,
)

SAMPLE_REVIEW_PASS = {
    "schema": "ORCA_REVIEW_DONE_V2",
    "version": "2.1.0",
    "verdict": "pass",
    "checklist_results": [
        {"id": "C1", "answer": "no", "evidence": "의존성 추가 없음"},
        {"id": "C2", "answer": "no", "evidence": "이모지 없음"},
        {"id": "C3", "answer": "yes", "evidence": "snake_case 준수"},
        {"id": "C4", "answer": "yes", "evidence": "docstring 준수"},
    ],
    "blocking_issues": [],
}

SAMPLE_REVIEW_FAIL = {
    "schema": "ORCA_REVIEW_DONE_V2",
    "version": "2.1.0",
    "verdict": "fail",
    "checklist_results": [
        {"id": "C1", "answer": "no", "evidence": "의존성 추가 없음"},
        {"id": "C2", "answer": "no", "evidence": "이모지 없음"},
        {"id": "C3", "answer": "yes", "evidence": "snake_case 준수"},
        {"id": "C4", "answer": "yes", "evidence": "docstring 준수"},
        {
            "id": "C5",
            "answer": "yes",
            "evidence": "src/audit_metric_collector.py:13 validate_window_size 경계값 제외 결함",
        },
    ],
    "blocking_issues": ["C5: validate_window_size 에서 경계 조건 오류로 min_w, max_w 가 제외됨"],
}


def test_seeded_repo_creates_two_commits_with_exact_6_defects():
    """(1) 임시 git 저장소 구성이 base 와 branch 두 커밋을 만들고 diff 가 6개 결함만 담는지 검증합니다."""
    tmp_holder, repo_path, base_ref, branch_ref = create_seeded_repo(
        clean_source=CLEAN_FIXTURE.resolve(),
        defective_source=DEFECTIVE_FIXTURE.resolve(),
    )
    try:
        # 커밋 로그 확인
        log_res = subprocess.run(  # noqa: S603
            ["git", "log", "--oneline", f"{base_ref}..{branch_ref}"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert len(log_res.stdout.strip().splitlines()) == 1

        # diff 확인
        diff_res = subprocess.run(  # noqa: S603
            ["git", "diff", f"{base_ref}...{branch_ref}"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        diff_text = diff_res.stdout
        # 6개 결함에 대한 변경 hunk 수 확인
        assert "validate_window_size" in diff_text
        assert "extract_metric_total" in diff_text
        assert "parse_and_accumulate_scores" in diff_text
        assert "match_task_identifier" in diff_text
        assert "truncate_summary_text" in diff_text
        assert "execute_safely_and_collect" in diff_text
        assert diff_text.count("@@") == 6
    finally:
        tmp_holder.cleanup()


def test_dry_run_does_not_invoke_model(tmp_path, monkeypatch):
    """(2) --dry-run 은 모델을 호출하지 않고 정상 완료됩니다."""
    results_dir = tmp_path / "results_dry"

    def mock_reviewer(**kwargs):
        # dry_run=True 시 orca_run_reviewer 도 모델 호출을 하지 않고 프롬프트 문자열만 반환
        assert kwargs.get("dry_run") is True
        return 0, "[Dry-run 완료] 조립된 프롬프트"

    code, summary = run_experiment(
        arm="both",
        runs=1,
        results_dir=results_dir,
        dry_run=True,
        reviewer_runner=mock_reviewer,
    )

    assert code == 0
    assert summary["dry_run"] is True
    assert summary["arms"]["arm_a"]["valid_runs"] == 1
    assert summary["arms"]["arm_b"]["valid_runs"] == 1


def test_reviewer_failure_marked_as_invalid(tmp_path):
    """(3) 리뷰어 호출 실패(종료 코드 2)가 무효(invalid)로 표시되고 검출 0으로 왜곡되지 않습니다."""
    results_dir = tmp_path / "results_fail"

    call_count = 0

    def mock_failing_reviewer(**kwargs):
        nonlocal call_count
        call_count += 1
        return 2, "오류: 모델 호출 실패"

    code, summary = run_experiment(
        arm="a",
        runs=1,
        results_dir=results_dir,
        reviewer_runner=mock_failing_reviewer,
    )

    # invalid_runs 가 존재하므로 exit_code 는 1
    assert code == 1
    arm_a = summary["arms"]["arm_a"]
    assert arm_a["valid_runs"] == 0
    assert arm_a["invalid_runs"] == 1
    # 최대 2회 재시도하여 총 3회 시도
    assert arm_a["retries_used"] == 2
    assert call_count == 3
    assert arm_a["runs"][0]["valid"] is False
    assert arm_a["runs"][0]["exit_code"] == 2


def test_results_dir_preserves_raw_reports_and_outputs(tmp_path):
    """(4) --results-dir 에 각 실행별 원문 JSON 과 stdout 텍스트가 정상 보존됩니다."""
    results_dir = tmp_path / "results_preserve"

    def mock_reviewer(**kwargs):
        out_file = Path(kwargs["out"])
        out_file.write_text(json.dumps(SAMPLE_REVIEW_FAIL), encoding="utf-8")
        return 1, "리뷰어 판정: 반려 (fail)"

    code, _summary = run_experiment(
        arm="b",
        runs=2,
        results_dir=results_dir,
        reviewer_runner=mock_reviewer,
    )

    assert code == 0
    assert (results_dir / "arm_b_run_1.json").exists()
    assert (results_dir / "arm_b_run_1.stdout.txt").exists()
    assert (results_dir / "arm_b_run_2.json").exists()
    assert (results_dir / "arm_b_run_2.stdout.txt").exists()
    assert (results_dir / "experiment_summary.json").exists()

    saved_report = json.loads((results_dir / "arm_b_run_1.json").read_text(encoding="utf-8"))
    assert saved_report["verdict"] == "fail"
    assert "C5" in saved_report["blocking_issues"][0]


def test_runs_and_arm_parameters_reflected(tmp_path):
    """(5) --runs 와 --arm 인자가 실제 실행 횟수와 대상에 정확히 반영됩니다."""
    results_dir = tmp_path / "results_args"

    executed_arms = []

    def mock_reviewer(**kwargs):
        capsule_name = Path(kwargs["capsule"]).name
        executed_arms.append(capsule_name)
        out_file = Path(kwargs["out"])
        out_file.write_text(json.dumps(SAMPLE_REVIEW_PASS), encoding="utf-8")
        return 0, "통과"

    code, summary = run_experiment(
        arm="a",
        runs=3,
        results_dir=results_dir,
        reviewer_runner=mock_reviewer,
    )

    assert code == 0
    assert len(executed_arms) == 3
    assert all("arm_a" in name for name in executed_arms)
    assert "arm_b" not in summary["arms"]
    assert summary["arms"]["arm_a"]["total_runs"] == 3


def test_main_cli_json_output(tmp_path, capsys):
    """(6) --json 옵션 사용 시 유효한 JSON 형식으로 요약이 출력됩니다."""
    results_dir = tmp_path / "results_cli"

    def mock_reviewer(**kwargs):
        out_file = Path(kwargs["out"])
        out_file.write_text(json.dumps(SAMPLE_REVIEW_PASS), encoding="utf-8")
        return 0, "통과"

    import scripts.run_level3_reduction_experiment as module_under_test

    saved_runner = module_under_test.run_reviewer
    try:
        # monkeypatching run_reviewer inside module
        module_under_test.run_reviewer = mock_reviewer
        code = main(
            [
                "--arm",
                "both",
                "--runs",
                "1",
                "--results-dir",
                str(results_dir),
                "--json",
            ]
        )
        assert code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "model" in parsed
        assert "arms" in parsed
        assert parsed["arms"]["arm_a"]["valid_runs"] == 1
        assert parsed["arms"]["arm_b"]["valid_runs"] == 1
    finally:
        module_under_test.run_reviewer = saved_runner
