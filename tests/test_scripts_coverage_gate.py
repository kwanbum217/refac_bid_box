"""tests/test_scripts_coverage_gate.py

G1 데이터 무손실 운영 도구 3종(scripts/verify_migration.py, scripts/backup_recovery.py,
scripts/promote_model.py)과 Orca 조율 도구 6종(orca_taskctl, orca_model_router,
orca_level1_gate, orca_auto_approve, validate_agent_rules, benchmark_provenance),
무테스트 2종(orca_forbidden_artifacts, orca_codex_launch)의 개별 커버리지 게이트
설정 정합성을 검증하는 테스트.

검증 항목:
1. pyproject.toml 의 src 전체 커버리지 게이트(80%) 보존 및 scripts_coverage_gate 임계값 정합성
2. .github/workflows/ci.yml 의 개별 커버리지 게이트 실행 스텝 배선 및 임계값 반영 여부
3. 임계값 미달 시 커버리지 게이트 실패(exit code != 0) 감지 동작 검증
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_scripts_coverage_gate_config():
    """pyproject.toml 에 세 스크립트에 대한 개별 커버리지 게이트 설정이 존재하고 src 전체 게이트가 보존되는지 검증합니다."""
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml 파일이 존재해야 합니다."

    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    # 1. src 전체 게이트 80% 보존 확인 (희석 금지)
    coverage_report = config.get("tool", {}).get("coverage", {}).get("report", {})
    assert coverage_report.get("fail_under") == 80, (
        "src 전체 커버리지 게이트 fail_under 는 80이어야 합니다."
    )

    coverage_run = config.get("tool", {}).get("coverage", {}).get("run", {})
    assert coverage_run.get("source") == ["src"], (
        "src 전체 coverage source 는 [src] 로 유지되어야 하며 scripts 로 넓혀 희석되지 않아야 합니다."
    )

    # 2. scripts 개별 게이트 임계값 설정 존재 및 수치 검증
    scripts_gate = config.get("tool", {}).get("scripts_coverage_gate", {}).get("thresholds", {})
    assert scripts_gate, "tool.scripts_coverage_gate.thresholds 설정이 존재해야 합니다."

    expected_thresholds = {
        "scripts/verify_migration.py": 70.0,
        "scripts/backup_recovery.py": 80.0,
        "scripts/promote_model.py": 85.0,
        "scripts/orca_taskctl.py": 78.0,
        "scripts/orca_model_router.py": 84.0,
        "scripts/orca_level1_gate.py": 74.0,
        "scripts/orca_auto_approve.py": 83.0,
        "scripts/validate_agent_rules.py": 83.0,
        "scripts/benchmark_provenance.py": 80.0,
        "scripts/orca_forbidden_artifacts.py": 98.0,
        "scripts/orca_codex_launch.py": 96.0,
    }

    for script_key, expected_val in expected_thresholds.items():
        assert script_key in scripts_gate, f"{script_key} 임계값 설정이 존재해야 합니다."
        actual_val = float(scripts_gate[script_key])
        assert actual_val == expected_val, (
            f"{script_key} 임계값은 {expected_val}이어야 합니다 (현재: {actual_val})."
        )


def test_ci_workflow_scripts_coverage_gate_step():
    """.github/workflows/ci.yml 에 개별 커버리지 게이트를 실제로 실행하는 스텝이 배선되어 있는지 검증합니다."""
    ci_yaml_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_yaml_path.exists(), ".github/workflows/ci.yml 파일이 존재해야 합니다."

    with open(ci_yaml_path, encoding="utf-8") as f:
        ci_config = yaml.safe_load(f)

    jobs = ci_config.get("jobs", {})
    assert "cross-platform-test" in jobs, "cross-platform-test job이 존재해야 합니다."

    steps = jobs["cross-platform-test"].get("steps", [])
    gate_step = None
    src_step = None

    for step in steps:
        name = step.get("name", "")
        if "Run G1 scripts individual coverage gate" in name:
            gate_step = step
        elif "Run pytest (SQLite in-memory with coverage)" in name:
            src_step = step

    assert src_step is not None, "기존 src 커버리지 테스트 스텝이 유지되어야 합니다."
    src_run = src_step.get("run", "")
    assert "--cov=src" in src_run, "src 커버리지 측정 플래그가 유지되어야 합니다."
    assert "--cov-fail-under=80" in src_run, "src 커버리지 80% 하한 게이트가 유지되어야 합니다."
    assert "--cov=scripts." not in src_run, (
        "src 전역 80% 판정에 scripts 가 섞여 희석되어서는 안 됩니다."
    )

    assert gate_step is not None, (
        "Run G1 scripts individual coverage gate 스텝이 CI workflow 에 존재해야 합니다."
    )
    gate_run = gate_step.get("run", "")

    # 세 스크립트 대상 측정 플래그 확인
    assert "--cov=scripts.verify_migration" in gate_run
    assert "--cov=scripts.backup_recovery" in gate_run
    assert "--cov=scripts.promote_model" in gate_run

    # 세 스크립트 개별 fail_under 검증 호출 확인
    assert 'coverage report --include="*verify_migration.py" --fail-under=70' in gate_run
    assert 'coverage report --include="*backup_recovery.py" --fail-under=80' in gate_run
    assert 'coverage report --include="*promote_model.py" --fail-under=85' in gate_run

    # Orca 조율 도구 6종과 무테스트 2종 개별 게이트 스텝 확인
    orca_gate_step = None
    for step in steps:
        if step.get("name", "") == "Run orca scripts individual coverage gate":
            orca_gate_step = step

    assert orca_gate_step is not None, (
        "Run orca scripts individual coverage gate 스텝이 CI workflow 에 존재해야 합니다."
    )
    orca_gate_run = orca_gate_step.get("run", "")

    orca_cov_modules = [
        "scripts.orca_taskctl",
        "scripts.orca_model_router",
        "scripts.orca_level1_gate",
        "scripts.orca_auto_approve",
        "scripts.validate_agent_rules",
        "scripts.benchmark_provenance",
        "scripts.orca_forbidden_artifacts",
        "scripts.orca_codex_launch",
    ]
    for module in orca_cov_modules:
        assert f"--cov={module}" in orca_gate_run, (
            f"{module} 측정 플래그가 orca scripts 게이트 스텝에 있어야 합니다."
        )

    orca_expected_reports = [
        ('coverage report --include="*orca_taskctl.py" --fail-under=78'),
        ('coverage report --include="*orca_model_router.py" --fail-under=84'),
        ('coverage report --include="*orca_level1_gate.py" --fail-under=74'),
        ('coverage report --include="*orca_auto_approve.py" --fail-under=83'),
        ('coverage report --include="*validate_agent_rules.py" --fail-under=83'),
        ('coverage report --include="*benchmark_provenance.py" --fail-under=80'),
        ('coverage report --include="*orca_forbidden_artifacts.py" --fail-under=98'),
        ('coverage report --include="*orca_codex_launch.py" --fail-under=96'),
    ]
    for report_line in orca_expected_reports:
        assert report_line in orca_gate_run, (
            f"{report_line} 판정이 orca scripts 게이트 스텝에 있어야 합니다."
        )

    # 측정만 하고 판정하지 않는 형태를 막기 위해 -m 필터와 fail_under=0 측정 플래그를 확인합니다.
    assert '-m "not data_assets and not e2e"' in orca_gate_run
    assert "--cov-fail-under=0" in orca_gate_run


def test_coverage_gate_failure_reproduction(tmp_path: Path):
    """임계값 미달 시 coverage report 가 실제로 0이 아닌 종료 코드로 실패하는지 확인합니다.

    측정 데이터를 이 테스트가 직접 만듭니다. 저장소에 남아 있는 .coverage 파일에
    의존하면 그 파일이 없는 환경에서 coverage 가 'No data to report.' 를 내고
    실패합니다. 격리 워크트리와 CI 신규 체크아웃이 그런 환경입니다.
    """
    target = tmp_path / "partially_covered.py"
    target.write_text(
        "def covered():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def uncovered():\n"
        "    value = 2\n"
        "    return value\n"
        "\n"
        "\n"
        "covered()\n",
        encoding="utf-8",
    )
    env = {**os.environ, "COVERAGE_FILE": str(tmp_path / ".coverage")}
    measured = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "coverage", "run", str(target)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert measured.returncode == 0, (
        f"커버리지 측정 실행이 성공해야 합니다: {measured.stdout} {measured.stderr}"
    )

    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            "--include=*partially_covered.py",
            "--fail-under=99.99",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert res.returncode != 0, (
        f"임계값 미달 시 coverage report 는 0이 아닌 종료 코드를 반환해야 합니다: {res.stdout}"
    )
    assert "Coverage failure" in res.stdout or "Coverage failure" in res.stderr
