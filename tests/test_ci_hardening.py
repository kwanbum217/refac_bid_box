"""
tests/test_ci_hardening.py

.github/workflows/ci.yml 의 세 가지 강화 계약을 정적으로 검증합니다.

  1. MySQL 통합 잡의 서비스 이미지가 docker-compose.yml 의 db 서비스와 같은
     다이제스트로 고정되어 있다 (QA-5).
  2. frontend/ 변경이 없으면 동결 React 단계(npm ci, lint, tsc, test, build)가
     건너뛰어지고, tailwind 재현성 검증은 건너뛰지 않는다 (FE-3).
  3. 전량 pytest 의 경고 수가 예산(0건)을 넘으면 실패한다 (QA-2).

워크플로를 실제로 실행하지 않습니다. YAML 을 읽어 배선만 대조합니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

DIGEST_PATTERN = re.compile(r"^(?P<tag>[^@]+)@(?P<digest>sha256:[0-9a-f]{64})$")

EXPECTED_MYSQL_DIGEST = "sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b"

FROZEN_REACT_STEPS = (
    "Install Frontend Dependencies",
    "Run Frontend Lint",
    "Run Frontend Type Check",
    "Run Frontend Tests",
    "Build Frontend",
)

GATE_CONDITION = "steps.frontend-changes.outputs.changed == 'true'"

WARNING_BUDGET_JOB = "pytest-warning-budget"
WARNING_BUDGET_STEP = "Run full pytest and enforce warning budget"

# 새 서드파티 action 을 들이지 않았음을 증명하기 위한 허용 목록입니다.
ALLOWED_WARNING_JOB_ACTIONS = {
    "actions/checkout",
    "actions/setup-python",
    "astral-sh/setup-uv",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    assert isinstance(data, dict), f"{path} 최상위 YAML 은 딕셔너리여야 합니다."
    return data


def _ci_data() -> dict[str, Any]:
    return _load_yaml(CI_WORKFLOW_PATH)


def _steps(job_name: str) -> list[dict[str, Any]]:
    jobs = _ci_data()["jobs"]
    assert job_name in jobs, f"ci.yml 에 {job_name} 잡이 없습니다."
    steps = jobs[job_name].get("steps", [])
    assert steps, f"{job_name} 잡에 스텝이 없습니다."
    return steps


def _find_step(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"ci.yml 에 '{name}' 스텝이 없습니다.")


def _image_digest(image: str, context: str) -> tuple[str, str]:
    matched = DIGEST_PATTERN.match(image.strip())
    assert matched, f"{context} 의 이미지가 다이제스트로 고정되지 않았습니다: {image!r}"
    return matched.group("tag"), matched.group("digest")


def test_mysql_service_image_matches_compose_digest():
    """MySQL 통합 잡의 서비스 이미지가 compose 의 db 이미지와 같아야 합니다."""
    compose_image = _load_yaml(COMPOSE_PATH)["services"]["db"]["image"]
    service_image = _ci_data()["jobs"]["mysql-ngram-integration"]["services"]["mysql"]["image"]

    compose_tag, compose_digest = _image_digest(compose_image, "docker-compose.yml 의 db")
    service_tag, service_digest = _image_digest(service_image, "ci.yml 의 mysql 서비스")

    assert service_tag == compose_tag, (
        f"ci.yml 의 mysql 태그({service_tag})가 compose 의 db 태그({compose_tag})와 다릅니다."
    )
    assert service_digest == compose_digest, (
        f"ci.yml 의 mysql 다이제스트({service_digest})가 compose db({compose_digest})와 다릅니다."
    )
    assert service_digest == EXPECTED_MYSQL_DIGEST, (
        f"고정해야 할 다이제스트는 {EXPECTED_MYSQL_DIGEST} 입니다: {service_digest}"
    )


def test_frontend_change_detection_step_is_wired():
    """frontend/ 변경 감지 스텝이 git diff 로 판정해 GITHUB_OUTPUT 으로 내보내야 합니다."""
    detection = _find_step(_steps("lint-and-validate"), "Detect frontend changes")

    assert detection.get("id") == "frontend-changes", (
        "감지 스텝의 id 는 frontend-changes 여야 후속 스텝이 참조할 수 있습니다."
    )
    assert detection.get("shell") == "bash", (
        "감지 판정은 셸 스크립트이므로 bash 로 고정해야 합니다."
    )

    run = str(detection.get("run", ""))
    assert "git diff --name-only" in run, "변경 판정은 git diff 로 해야 합니다."
    assert "-- frontend/ .github/workflows/ci.yml" in run, (
        "감지 범위는 frontend/ 와 워크플로 자신(.github/workflows/ci.yml)이어야 합니다."
    )
    assert "${{ github.event.pull_request.base.sha }}" in run, (
        "PR 은 base SHA 를 기준으로 삼아야 합니다."
    )
    assert "${{ github.event.pull_request.head.sha }}" in run, (
        "PR 은 head SHA 를 기준으로 삼아야 합니다."
    )
    assert "${{ github.event.before }}" in run, "push 는 before 커밋을 기준으로 삼아야 합니다."
    assert "${{ github.sha }}" in run, "push 는 sha 를 기준으로 삼아야 합니다."
    assert "0000000000000000000000000000000000000000" in run, (
        "첫 push 의 zero SHA 를 명시적으로 처리해야 합니다."
    )
    assert "changed=false" in run, "감지 스텝은 변경 없음(false)을 내보내야 합니다."
    assert "changed=true" in run, "감지 스텝은 변경 있음(true)을 내보내야 합니다."


def test_frontend_change_detection_fails_open():
    """판정 실패와 첫 push 는 건너뛰기가 아니라 실행으로 귀결되어야 합니다."""
    run = str(_find_step(_steps("lint-and-validate"), "Detect frontend changes").get("run", ""))

    # 비교가 실패한 else 갈래에서 changed=true 를 내보내는지 확인합니다.
    fail_open = re.search(r"else\s+echo \"changed=true\"", run)
    assert fail_open, "비교 실패 시 changed=true 로 기울지 않으면 프런트 검증이 누락됩니다."

    # zero SHA 는 HEAD~1 로 대체해 실행 쪽으로 귀결됩니다.
    assert "HEAD~1...HEAD" in run, "첫 push 는 직전 커밋 비교로 대체해 실행해야 합니다."


def test_frozen_react_steps_are_gated_on_frontend_changes():
    """동결 React 5단계는 frontend 변경이 있을 때만 실행되어야 합니다."""
    steps = _steps("lint-and-validate")
    detection_idx = steps.index(_find_step(steps, "Detect frontend changes"))

    for name in FROZEN_REACT_STEPS:
        step = _find_step(steps, name)
        assert str(step.get("if", "")) == GATE_CONDITION, (
            f"'{name}' 스텝이 frontend 변경 조건으로 게이트되지 않았습니다: {step.get('if')!r}"
        )
        assert steps.index(step) > detection_idx, f"'{name}' 스텝은 감지 스텝 뒤에 있어야 합니다."


def test_tailwind_steps_are_not_gated():
    """tailwind 재현성 검증은 동결 React 자산이 아니므로 조건을 붙이지 않습니다."""
    steps = _steps("lint-and-validate")

    for name in ("Install Tailwind Toolchain", "Verify Tailwind CSS Reproducibility"):
        step = _find_step(steps, name)
        assert step.get("if") is None, (
            f"'{name}' 스텝은 frontend 변경과 무관하게 실행되어야 합니다: {step.get('if')!r}"
        )


def test_pytest_warning_budget_job_enforces_summary_line():
    """전용 잡이 pytest 요약 줄의 경고 수를 읽어 0건 초과 시 실패해야 합니다."""
    data = _ci_data()
    jobs = data["jobs"]
    assert WARNING_BUDGET_JOB in jobs, f"ci.yml 에 {WARNING_BUDGET_JOB} 잡이 없습니다."

    job = jobs[WARNING_BUDGET_JOB]
    assert job.get("runs-on") == "ubuntu-latest", (
        "경고 예산 판정은 ubuntu-latest 한 곳에서 수행합니다."
    )

    step = _find_step(job["steps"], WARNING_BUDGET_STEP)
    assert step.get("shell") == "bash", "요약 줄 파싱은 셸에 종속되므로 bash 로 고정해야 합니다."

    env = step.get("env", {})
    assert str(env.get("PYTEST_WARNING_BUDGET")) == "0", (
        f"경고 예산은 0 이어야 합니다: {env.get('PYTEST_WARNING_BUDGET')!r}"
    )

    run = str(step.get("run", ""))
    assert "uv run pytest tests/ -q -m 'not data_assets'" in run, (
        "전량 pytest 를 그대로 실행해야 합니다."
    )
    assert "[0-9]+ warnings?" in run, "pytest 요약 줄에서 경고 수를 추출해야 합니다."
    assert "tail -n 1" in run, "요약 줄은 마지막 경고 표기를 읽어야 합니다."
    assert 'if [ -z "$WARNING_COUNT" ]; then' in run, "경고가 없으면 0 으로 봐야 합니다."
    assert '"$WARNING_COUNT" -gt "$PYTEST_WARNING_BUDGET"' in run, (
        "경고 수를 예산과 비교하는 판정이 있어야 합니다."
    )
    assert "exit 1" in run, "예산 초과 시 CI 를 실패시켜야 합니다."

    # 테스트 실패를 경고 검사가 가리면 안 됩니다. 종료 코드 전파가 판정보다 앞서야 합니다.
    exit_propagation = run.index('exit "$EXIT_CODE"')
    budget_check = run.index('"$WARNING_COUNT" -gt "$PYTEST_WARNING_BUDGET"')
    assert exit_propagation < budget_check, (
        "pytest 종료 코드 전파가 경고 예산 판정보다 앞서야 합니다."
    )
    assert "-m 'not data_assets'" in run, "전량 pytest 의 표식 조건이 유지되어야 합니다."


def test_warning_budget_job_adds_no_new_third_party_action():
    """경고 예산 잡은 기존에 쓰던 핀 고정 action 만 재사용해야 합니다."""
    used: set[str] = set()
    for step in _ci_data()["jobs"][WARNING_BUDGET_JOB]["steps"]:
        uses = step.get("uses")
        if not uses:
            continue
        action_name, sha = uses.split("@", 1)
        used.add(action_name)
        assert re.fullmatch(r"[0-9a-f]{40}", sha), f"{uses} 가 40자 SHA 로 고정되지 않았습니다."

    assert used <= ALLOWED_WARNING_JOB_ACTIONS, (
        f"새 서드파티 action 이 추가됐습니다: {sorted(used - ALLOWED_WARNING_JOB_ACTIONS)}"
    )
