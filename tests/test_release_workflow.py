"""tests/test_release_workflow.py

수동 릴리스 워크플로(.github/workflows/release.yml)의 보안 및 무결성 계약을 검증합니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PROD_COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    assert isinstance(data, dict), f"{path} 최상위 YAML 은 딕셔너리여야 합니다."
    return data


def _find_step_index(steps: list[dict[str, Any]], predicate, description: str) -> int:
    for idx, step in enumerate(steps):
        if predicate(step):
            return idx
    raise AssertionError(f"워크플로에서 '{description}' 스텝을 찾을 수 없습니다.")


def test_steps_ordering_build_trivy_sbom_before_tag():
    """(a) 빌드·trivy·allowlist 판정·SBOM 단계가 태그 생성 및 릴리스 단계보다 앞서야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    build_idx = _find_step_index(
        steps,
        lambda s: "docker buildx" in str(s.get("run", "")),
        "docker buildx 운영 이미지 빌드",
    )
    trivy_idx = _find_step_index(
        steps,
        lambda s: "trivy-action" in str(s.get("uses", "")),
        "trivy 컨테이너 취약점 검사",
    )
    filter_idx = _find_step_index(
        steps,
        lambda s: "filter_trivy_results.py" in str(s.get("run", "")),
        "Trivy 결과 allowlist 필터 판정",
    )
    sbom_idx = _find_step_index(
        steps,
        lambda s: "sbom-action" in str(s.get("uses", "")),
        "SBOM 생성",
    )
    digest_idx = _find_step_index(
        steps,
        lambda s: "image-digest.txt" in str(s.get("run", "")),
        "이미지 digest 기록 및 릴리스 노트 갱신",
    )
    tag_idx = _find_step_index(
        steps,
        lambda s: "git tag" in str(s.get("run", "")),
        "릴리스 태그 생성 및 푸시",
    )
    release_idx = _find_step_index(
        steps,
        lambda s: "gh release create" in str(s.get("run", "")),
        "GitHub 릴리스 생성",
    )

    # 차단 결과 발생 시 태그 및 릴리스가 생성되지 않도록 엄격한 순서를 검증합니다.
    assert build_idx < trivy_idx < filter_idx < sbom_idx < digest_idx < tag_idx < release_idx, (
        f"스텝 순서 위반: build({build_idx}) < trivy({trivy_idx}) < filter({filter_idx}) < "
        f"sbom({sbom_idx}) < digest({digest_idx}) < tag({tag_idx}) < release({release_idx})"
    )


def test_no_push_or_registry_login():
    """(b) 이미지를 원격 레지스트리에 push하거나 로그인하는 단계가 없어야 합니다."""
    workflow_text = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = _load_yaml(RELEASE_WORKFLOW_PATH)

    # push, login 관련 액션 및 셸 명령 차단
    assert "docker push" not in workflow_text
    assert "docker login" not in workflow_text
    assert "login-action" not in workflow_text
    assert "--push" not in workflow_text

    # buildx 가 로컬 로드(--load) 방식을 사용하는지 검증
    steps = data["jobs"]["release"]["steps"]
    build_step = next(s for s in steps if "docker buildx" in str(s.get("run", "")))
    build_cmd = str(build_step.get("run", ""))
    assert "--load" in build_cmd

    # permissions 에 packages 권한이 없어야 함
    permissions = data.get("permissions", {})
    assert "packages" not in permissions, "packages 권한은 허용되지 않습니다."


def test_all_action_uses_pinned_to_40char_sha():
    """(c) 모든 uses 가 40자 커밋 SHA 로 고정되어야 하며, ci.yml 과 동일 액션은 SHA 를 재사용해야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    ci_data = _load_yaml(CI_WORKFLOW_PATH)

    # ci.yml 의 모든 액션 SHA 수집
    ci_action_shas: dict[str, str] = {}
    for job in ci_data.get("jobs", {}).values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses and "@" in uses:
                action_name, sha = uses.split("@", 1)
                ci_action_shas[action_name] = sha

    steps = data["jobs"]["release"]["steps"]
    checked_uses_count = 0

    for step in steps:
        uses = step.get("uses")
        if not uses:
            continue
        checked_uses_count += 1
        assert "@" in uses, f"uses 에 버전/SHA 구분자 '@' 가 없습니다: {uses}"
        action_name, sha = uses.split("@", 1)
        # 40자 sha 검증
        assert SHA_PATTERN.match(sha), (
            f"액션 '{action_name}' 의 SHA 가 40자 16진수가 아닙니다: {sha}"
        )

        # ci.yml 에 이미 사용 중인 액션인 경우 동일한 SHA 를 사용하는지 검증
        if action_name in ci_action_shas:
            assert sha == ci_action_shas[action_name], (
                f"액션 '{action_name}' 의 SHA({sha})가 ci.yml 의 SHA({ci_action_shas[action_name]})와 다릅니다."
            )

    assert checked_uses_count >= 4, (
        f"최소 4개 이상의 핀된 액션이 검사되어야 합니다 (검사됨: {checked_uses_count})"
    )


def test_release_assets_and_digest_appended():
    """(d) GitHub 릴리스 생성 시 SBOM 및 digest 파일이 첨부되고, 릴리스 노트 끝에 digest 가 추가되어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    # 1. 릴리스 노트에 digest 추가 스텝 검증
    digest_step = next(s for s in steps if "image-digest.txt" in str(s.get("run", "")))
    digest_cmd = str(digest_step.get("run", ""))
    assert "docker inspect --format='{{.Id}}'" in digest_cmd
    assert "image-digest.txt" in digest_cmd
    assert "release-notes.md" in digest_cmd
    assert "Image Digest:" in digest_cmd

    # 2. gh release create 명령어에 자산 첨부 검증
    release_step = next(s for s in steps if "gh release create" in str(s.get("run", "")))
    release_cmd = str(release_step.get("run", ""))
    assert "refac-bid-box-sbom.spdx.json" in release_cmd
    assert "image-digest.txt" in release_cmd


def test_build_target_matches_production_compose_app():
    """Dockerfile 의 target 은 운영 compose 의 app 이 쓰는 target 과 일치해야 합니다."""
    compose_data = _load_yaml(PROD_COMPOSE_PATH)
    app_build = compose_data.get("services", {}).get("app", {}).get("build", {})
    compose_app_target = app_build.get("target")

    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]
    build_step = next(s for s in steps if "docker buildx" in str(s.get("run", "")))
    build_cmd = str(build_step.get("run", ""))

    if compose_app_target is None:
        # 운영 compose 의 app 에 target 이 명시되지 않았으므로 buildx 명령에도 --target 이 없어야 함
        assert "--target" not in build_cmd, (
            "운영 compose app 에 target 이 없으므로 --target 옵션을 지정하지 않아야 합니다."
        )
    else:
        assert (
            f"--target {compose_app_target}" in build_cmd
            or f"--target={compose_app_target}" in build_cmd
        )


def test_trivy_and_filter_criteria():
    """Trivy 검사 및 scripts/filter_trivy_results.py 판정 기준이 엄격하게 설정되어 있는지 검증합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    trivy_step = next(s for s in steps if "trivy-action" in str(s.get("uses", "")))
    with_clause = trivy_step.get("with", {})
    assert with_clause.get("format") == "json"
    assert with_clause.get("severity") == "CRITICAL,HIGH"
    assert with_clause.get("exit-code") == "0"
    assert with_clause.get("ignore-unfixed") is True or with_clause.get("ignore-unfixed") == "true"
    assert with_clause.get("output") == "trivy-results.json"

    filter_step = next(s for s in steps if "filter_trivy_results.py" in str(s.get("run", "")))
    filter_cmd = str(filter_step.get("run", ""))
    assert "scripts/filter_trivy_results.py" in filter_cmd
    assert ".github/vulnerability-allowlist.yml" in filter_cmd


def test_workflow_dispatch_draft_input_contract():
    """workflow_dispatch 에 draft(type boolean, default true) 입력이 명시되어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    on_dispatch = (data.get("on") or data.get(True, {})).get("workflow_dispatch", {})
    assert isinstance(on_dispatch, dict), "workflow_dispatch 는 딕셔너리여야 합니다."
    inputs = on_dispatch.get("inputs", {})
    assert "draft" in inputs, "workflow_dispatch 에 'draft' 입력이 정의되어야 합니다."
    draft_spec = inputs["draft"]
    assert draft_spec.get("type") == "boolean", "draft 입력의 type 은 boolean 이어야 합니다."
    assert draft_spec.get("default") is True, "draft 입력의 default 는 true 여야 합니다."


def test_draft_true_branch_contracts():
    """draft=true 경로에서 태그 push 가 차단되고, gh release create 에 --draft 및 --target 이 전달되며 --verify-tag 는 배제되어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    # 1. 태그 푸시 스텝 조건 검증
    tag_step = next(s for s in steps if "git tag" in str(s.get("run", "")))
    tag_condition = str(tag_step.get("if", ""))
    assert "!inputs.draft" in tag_condition, (
        "태그 푸시 스텝은 draft 가 false 일 때만 실행되어야 합니다."
    )

    # 2. 초안 릴리스 생성 스텝 검증
    draft_release_step = next(
        s
        for s in steps
        if "gh release create" in str(s.get("run", "")) and "--draft" in str(s.get("run", ""))
    )
    draft_cmd = str(draft_release_step.get("run", ""))
    draft_condition = str(draft_release_step.get("if", ""))

    assert "inputs.draft" in draft_condition
    assert "!inputs.draft" not in draft_condition
    assert "--draft" in draft_cmd
    assert "--target" in draft_cmd
    assert "--verify-tag" not in draft_cmd
    assert "refac-bid-box-sbom.spdx.json" in draft_cmd
    assert "image-digest.txt" in draft_cmd


def test_draft_false_public_branch_contracts():
    """draft=false 경로에서 태그가 푸시되고, gh release create 에 --verify-tag 가 포함되며 --draft 는 배제되어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    # 1. 태그 푸시 스텝 검증
    tag_step = next(s for s in steps if "git tag" in str(s.get("run", "")))
    tag_cmd = str(tag_step.get("run", ""))
    tag_condition = str(tag_step.get("if", ""))
    assert "!inputs.draft" in tag_condition
    assert "git tag" in tag_cmd
    assert "git push origin" in tag_cmd

    # 2. 공개 릴리스 생성 스텝 검증
    public_release_step = next(
        s
        for s in steps
        if "gh release create" in str(s.get("run", "")) and "--verify-tag" in str(s.get("run", ""))
    )
    public_cmd = str(public_release_step.get("run", ""))
    public_condition = str(public_release_step.get("if", ""))

    assert "!inputs.draft" in public_condition
    assert "--verify-tag" in public_cmd
    assert "--draft" not in public_cmd
    assert "refac-bid-box-sbom.spdx.json" in public_cmd
    assert "image-digest.txt" in public_cmd


def test_security_gates_run_unconditionally_for_both_branches():
    """readiness, build, trivy, allowlist, sbom, image-digest 스텝은 draft 분기 조건 없이 항상 실행되어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    essential_step_predicates = [
        ("readiness", lambda s: "check_release_readiness.py" in str(s.get("run", ""))),
        ("build", lambda s: "docker buildx" in str(s.get("run", ""))),
        ("trivy", lambda s: "trivy-action" in str(s.get("uses", ""))),
        ("filter", lambda s: "filter_trivy_results.py" in str(s.get("run", ""))),
        ("sbom", lambda s: "sbom-action" in str(s.get("uses", ""))),
        ("digest", lambda s: "image-digest.txt" in str(s.get("run", ""))),
    ]

    for name, pred in essential_step_predicates:
        matching_step = next(s for s in steps if pred(s))
        step_if = matching_step.get("if")
        assert step_if is None or "draft" not in str(step_if), (
            f"필수 보안/무결성 게이트 '{name}' 는 draft 분기와 무관하게 무조건 실행되어야 합니다."
        )


def test_prerelease_conditional_in_draft_and_public_steps():
    """(5) 사전 릴리스일 때만 --prerelease 가 붙는 조건식이 draft 경로와 공개 경로 모두에 있어야 합니다."""
    data = _load_yaml(RELEASE_WORKFLOW_PATH)
    steps = data["jobs"]["release"]["steps"]

    # 1. draft 릴리스 생성 스텝
    draft_step = next(
        s
        for s in steps
        if "gh release create" in str(s.get("run", "")) and "--draft" in str(s.get("run", ""))
    )
    draft_env = draft_step.get("env", {})
    draft_cmd = str(draft_step.get("run", ""))
    assert "IS_PRERELEASE" in draft_env
    assert "steps.readiness.outputs.prerelease" in draft_env["IS_PRERELEASE"]
    assert 'if [ "$IS_PRERELEASE" = "true" ]' in draft_cmd
    assert "--prerelease" in draft_cmd
    # gh release create 인자에 정적으로 --prerelease가 하드코딩되지 않음
    assert not re.search(r"gh release create[^\n]*--prerelease", draft_cmd)

    # 2. 공개 릴리스 생성 스텝
    public_step = next(
        s
        for s in steps
        if "gh release create" in str(s.get("run", "")) and "--verify-tag" in str(s.get("run", ""))
    )
    public_env = public_step.get("env", {})
    public_cmd = str(public_step.get("run", ""))
    assert "IS_PRERELEASE" in public_env
    assert "steps.readiness.outputs.prerelease" in public_env["IS_PRERELEASE"]
    assert 'if [ "$IS_PRERELEASE" = "true" ]' in public_cmd
    assert "--prerelease" in public_cmd
    # gh release create 인자에 정적으로 --prerelease가 하드코딩되지 않음
    assert not re.search(r"gh release create[^\n]*--prerelease", public_cmd)
