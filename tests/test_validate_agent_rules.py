from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import validate_agent_rules
from scripts.validate_agent_rules import (
    AGENTS_CHAR_BUDGET,
    ANTIGRAVITY_CHAR_CAP,
    CONTRACT_VERSION,
    CURRENT_STATE_CHAR_BUDGET,
    CURRENT_STATE_LAG_TOLERANCE,
    GIT_PROBE_TIMEOUT_SECONDS,
    PROJECT_ROOT,
    check_agents_model_table_absence,
    check_agents_single_root,
    check_antigravity_rules,
    check_claude_is_pointer,
    check_context_budgets,
    check_current_state_exists,
    check_current_state_sections,
    check_current_state_unknowns_contradictions,
    check_cursor_references_agents,
    check_opencode_json,
    check_orca_coordination_skill,
    check_skills_mirror,
    check_task_capsule_v2_docs,
    check_v2_templates,
    check_worker_model_pool_drift,
    get_all_checks,
    parse_yaml_keys_fallback,
    run_all_checks,
)


def test_real_repo_validation_passes():
    """실제 저장소의 v2 정합성 검증이 100% 통과하는지 확인."""
    checks = get_all_checks(PROJECT_ROOT)
    assert len(checks) == 16
    for chk in checks:
        assert chk.ok, f"Check failed: {chk.name} -> {chk.detail}"
    assert run_all_checks(PROJECT_ROOT, quiet=True) == 0
    assert check_worker_model_pool_drift(PROJECT_ROOT).ok
    assert check_agents_model_table_absence(PROJECT_ROOT).ok
    assert check_current_state_unknowns_contradictions(PROJECT_ROOT).ok


def test_check_claude_is_pointer(tmp_path: Path):
    # 1. Valid pointer
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Claude Code\n\n@AGENTS.md\n", encoding="utf-8")
    res = check_claude_is_pointer(tmp_path)
    assert res.ok

    # 2. Missing file
    claude_md.unlink()
    res = check_claude_is_pointer(tmp_path)
    assert not res.ok
    assert "파일 없음" in res.detail

    # 3. Missing @AGENTS.md
    claude_md.write_text("# Claude Code\nNo import here\n", encoding="utf-8")
    res = check_claude_is_pointer(tmp_path)
    assert not res.ok

    # 4. Copied canonical markers
    claude_md.write_text("# Claude Code\n@AGENTS.md\n## 2. 기술 스택\nFastAPI\n", encoding="utf-8")
    res = check_claude_is_pointer(tmp_path)
    assert not res.ok
    assert "복사됨" in res.detail


def test_check_antigravity_rules(tmp_path: Path):
    antigravity_dir = tmp_path / ".antigravity"
    antigravity_dir.mkdir(parents=True)
    rules_md = antigravity_dir / "rules.md"

    valid_content = """# Rules
- 데이터 무손실
- Train/Serve
- 금지 행위
- 이모지 금지
- main 브랜치 직접 커밋 금지
- 재학습 게이트
- 스킬 인덱스
"""
    # 1. Valid
    rules_md.write_text(valid_content, encoding="utf-8")
    res = check_antigravity_rules(tmp_path)
    assert res.ok

    # 2. Missing file
    rules_md.unlink()
    res = check_antigravity_rules(tmp_path)
    assert not res.ok

    # 3. Char cap exceeded
    overflow_content = valid_content + ("a" * (ANTIGRAVITY_CHAR_CAP + 10))
    rules_md.write_text(overflow_content, encoding="utf-8")
    res = check_antigravity_rules(tmp_path)
    assert not res.ok
    assert "캡 초과" in res.detail

    # 4. Missing required section
    incomplete_content = "# Rules\n- 데이터 무손실\n"
    rules_md.write_text(incomplete_content, encoding="utf-8")
    res = check_antigravity_rules(tmp_path)
    assert not res.ok
    assert "누락" in res.detail


def test_check_cursor_references_agents(tmp_path: Path):
    cursor_dir = tmp_path / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True)
    rule_file = cursor_dir / "00-core-guidelines.mdc"

    # 1. Valid
    rule_file.write_text("# Core\nRefer to AGENTS.md for details.\n", encoding="utf-8")
    res = check_cursor_references_agents(tmp_path)
    assert res.ok

    # 2. Missing file
    rule_file.unlink()
    res = check_cursor_references_agents(tmp_path)
    assert not res.ok

    # 3. Missing reference
    rule_file.write_text("# Core\nNo reference\n", encoding="utf-8")
    res = check_cursor_references_agents(tmp_path)
    assert not res.ok


def test_check_opencode_json_v2_and_legacy_dual_injection(tmp_path: Path):
    opencode_json = tmp_path / "opencode.json"

    # 1. Valid v2 single injection
    opencode_json.write_text(json.dumps({"instructions": ["AGENTS.md"]}), encoding="utf-8")
    res = check_opencode_json(tmp_path)
    assert res.ok
    assert "단일 자동 로드 확인" in res.detail

    # 2. Missing file
    opencode_json.unlink()
    res = check_opencode_json(tmp_path)
    assert not res.ok

    # 3. Invalid JSON
    opencode_json.write_text("{not valid json", encoding="utf-8")
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "파싱 실패" in res.detail

    # 4. Missing AGENTS.md
    opencode_json.write_text(json.dumps({"instructions": ["OTHER.md"]}), encoding="utf-8")
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "AGENTS.md 누락" in res.detail

    # 5. Legacy dual injection with SKILLS.md must FAIL
    opencode_json.write_text(
        json.dumps({"instructions": ["AGENTS.md", "SKILLS.md"]}), encoding="utf-8"
    )
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "SKILLS.md 이중 주입 감지" in res.detail

    # 6. 문자열값은 반드시 실패 (배열이 아니라 문자열이므로 단일 주입 계약 위반)
    opencode_json.write_text(json.dumps({"instructions": "AGENTS.md"}), encoding="utf-8")
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "타입 위반" in res.detail

    # 7. 빈 배열은 반드시 실패 (AGENTS.md 미포함, v2 단일 주입 계약 위반)
    opencode_json.write_text(json.dumps({"instructions": []}), encoding="utf-8")
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "빈 배열" in res.detail

    # 8. 추가 항목 배열은 반드시 실패 (정확히 ["AGENTS.md"]만 허용)
    opencode_json.write_text(
        json.dumps({"instructions": ["AGENTS.md", "OTHER.md"]}), encoding="utf-8"
    )
    res = check_opencode_json(tmp_path)
    assert not res.ok
    assert "추가 항목" in res.detail


def test_check_skills_mirror(tmp_path: Path):
    agents_dir = tmp_path / ".agents" / "skills" / "skill-a"
    claude_dir = tmp_path / ".claude" / "skills" / "skill-a"
    opencode_dir = tmp_path / ".opencode" / "skills" / "skill-a"

    agents_dir.mkdir(parents=True)
    claude_dir.mkdir(parents=True)
    opencode_dir.mkdir(parents=True)

    (agents_dir / "SKILL.md").write_text("content", encoding="utf-8")
    (claude_dir / "SKILL.md").write_text("content", encoding="utf-8")
    (opencode_dir / "SKILL.md").write_text("content", encoding="utf-8")

    # 1. Valid mirror
    res = check_skills_mirror(tmp_path)
    assert res.ok

    # 2. Discrepancy in claude mirror
    (claude_dir / "SKILL.md").write_text("different content", encoding="utf-8")
    res = check_skills_mirror(tmp_path)
    assert not res.ok
    assert "차이" in res.detail


def test_check_agents_single_root_and_legacy_import(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.md"

    valid_content = """# refac_bid_box
## 0. 에이전트 부트스트랩 모드
ORCA_TASK_CAPSULE_V2 기반 실행.
## 1. 비협상 원칙
- 데이터 무손실
- 금지 행위
- 이모지 금지
- main 브랜치 보호
"""
    # 1. Valid v2 single bootstrap root
    agents_md.write_text(valid_content, encoding="utf-8")
    res = check_agents_single_root(tmp_path)
    assert res.ok

    # 2. Missing file
    agents_md.unlink()
    res = check_agents_single_root(tmp_path)
    assert not res.ok

    # 3. Legacy @SKILLS.md import must FAIL
    legacy_content = "@SKILLS.md\n" + valid_content
    agents_md.write_text(legacy_content, encoding="utf-8")
    res = check_agents_single_root(tmp_path)
    assert not res.ok
    assert "@SKILLS.md import 구문 존재" in res.detail

    # 4. Missing required non-negotiables
    incomplete_content = "# refac_bid_box\nNo core sections.\n"
    agents_md.write_text(incomplete_content, encoding="utf-8")
    res = check_agents_single_root(tmp_path)
    assert not res.ok
    assert "키워드 누락" in res.detail


def test_check_task_capsule_v2_docs(tmp_path: Path):
    docs_dir = tmp_path / "docs" / "ops"
    docs_dir.mkdir(parents=True)
    doc_path = docs_dir / "orca_task_capsule_v2.md"

    valid_content = """# Task Capsule v2
- ORCA_TASK_CAPSULE_V2
- ORCA_WORKER_DONE_V2
- ORCA_REVIEW_DONE_V2
- 3단계 검증
- 자족적 실행 계약
"""
    # 1. Valid
    doc_path.write_text(valid_content, encoding="utf-8")
    res = check_task_capsule_v2_docs(tmp_path)
    assert res.ok

    # 2. Missing file
    doc_path.unlink()
    res = check_task_capsule_v2_docs(tmp_path)
    assert not res.ok

    # 3. Missing keyword
    doc_path.write_text("# Short doc\n", encoding="utf-8")
    res = check_task_capsule_v2_docs(tmp_path)
    assert not res.ok
    assert "키워드 누락" in res.detail


def test_check_v2_templates(tmp_path: Path):
    tpl_dir = tmp_path / ".agents" / "templates"
    tpl_dir.mkdir(parents=True)

    capsule_yaml = tpl_dir / "task_capsule_v2.yaml"
    worker_json = tpl_dir / "worker_done_v2.json"
    review_json = tpl_dir / "review_done_v2.json"

    valid_capsule = f"""
schema: ORCA_TASK_CAPSULE_V2
version: "{CONTRACT_VERSION}"
mode: worker
run_id: run-123
task_id: task-456
role: builder
objective: objective text
why_now: why text
ground_truth: []
allowed_read_files: []
allowed_write_files: []
search_scope:
  mode: deny_by_default
forbidden: []
shared_resources: []
required_change: []
acceptance: []
verification_commands: []
artifact_paths: []
escalate_when: []
return_contract: ORCA_WORKER_DONE_V2
"""
    valid_worker = {
        "schema": "ORCA_WORKER_DONE_V2",
        "version": CONTRACT_VERSION,
        "task_id": "task-456",
        "dispatch_id": "ctx-1",
        "status": "succeeded",
        "branch": "feat/test",
        "commit": "sha123",
        "commit_count": 1,
        "changed_files": [],
        "verification": [],
        "metrics": {},
        "verdict": "candidate",
        "blocking_issues": [],
        "remaining_risks": [],
        "artifacts": [],
        "reproduce": [],
    }
    valid_review = {
        "schema": "ORCA_REVIEW_DONE_V2",
        "version": CONTRACT_VERSION,
        "task_id": "task-456",
        "dispatch_id": "ctx-1",
        "verdict": "pass",
        "blocking_issues": [],
        "unverified_claims": [],
        "missing_tests": [],
        "requested_context": [],
        "commands_to_verify": [],
    }

    # 1. Valid templates
    capsule_yaml.write_text(valid_capsule, encoding="utf-8")
    worker_json.write_text(json.dumps(valid_worker), encoding="utf-8")
    review_json.write_text(json.dumps(valid_review), encoding="utf-8")

    res = check_v2_templates(tmp_path)
    assert res.ok

    # 2. Missing capsule file
    capsule_yaml.unlink()
    res = check_v2_templates(tmp_path)
    assert not res.ok

    # 3. Missing key in capsule
    capsule_yaml.write_text(
        f"schema: ORCA_TASK_CAPSULE_V2\nversion: '{CONTRACT_VERSION}'\n", encoding="utf-8"
    )
    res = check_v2_templates(tmp_path)
    assert not res.ok
    assert "필수 키 누락" in res.detail

    # Restore valid capsule
    capsule_yaml.write_text(valid_capsule, encoding="utf-8")

    # 4. Worker done invalid schema
    invalid_worker = dict(valid_worker)
    invalid_worker["schema"] = "WRONG_SCHEMA"
    worker_json.write_text(json.dumps(invalid_worker), encoding="utf-8")
    res = check_v2_templates(tmp_path)
    assert not res.ok
    assert "schema 불일치" in res.detail

    # Restore valid worker
    worker_json.write_text(json.dumps(valid_worker), encoding="utf-8")

    # 5. Review done missing key
    invalid_review = dict(valid_review)
    del invalid_review["verdict"]
    review_json.write_text(json.dumps(invalid_review), encoding="utf-8")
    res = check_v2_templates(tmp_path)
    assert not res.ok
    assert "필수 키 누락" in res.detail


def test_check_orca_coordination_skill(tmp_path: Path):
    skill_dir = tmp_path / ".agents" / "skills" / "orca-section-coordination"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"

    valid_content = """# Orca Section Coordination
- ORCA_TASK_CAPSULE_V2
- ORCA_WORKER_DONE_V2
- ORCA_REVIEW_DONE_V2
"""
    # 1. Valid
    skill_file.write_text(valid_content, encoding="utf-8")
    res = check_orca_coordination_skill(tmp_path)
    assert res.ok

    # 2. Missing file
    skill_file.unlink()
    res = check_orca_coordination_skill(tmp_path)
    assert not res.ok

    # 3. Missing keywords
    skill_file.write_text("# Skill\n", encoding="utf-8")
    res = check_orca_coordination_skill(tmp_path)
    assert not res.ok


def test_fallback_yaml_parser():
    content = """schema: ORCA_TASK_CAPSULE_V2
version: "2.0.0"
mode: worker
"""
    parsed = parse_yaml_keys_fallback(content)
    assert parsed.get("schema") == "ORCA_TASK_CAPSULE_V2"
    assert parsed.get("version") == "2.0.0"
    assert parsed.get("mode") == "worker"


def _write_current_state(root: Path, body: str) -> Path:
    target = root / "docs" / "context" / "CURRENT_STATE.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_check_current_state_exists(tmp_path: Path):
    """정본이 없으면 FAIL, 있으면 PASS 입니다."""
    res = check_current_state_exists(tmp_path)
    assert not res.ok

    _write_current_state(tmp_path, "# state\n")
    res = check_current_state_exists(tmp_path)
    assert res.ok


def test_check_current_state_sections_missing_field(tmp_path: Path):
    """필수 필드가 빠지면 FAIL 입니다."""
    _write_current_state(tmp_path, "# state\n> updated_at: 2026-08-15\nG1 G2 G3\ndocs/ops/x.md\n")
    res = check_current_state_sections(tmp_path)
    assert not res.ok
    assert "source_commit" in res.detail


def test_check_current_state_sections_missing_evidence(tmp_path: Path):
    """증거 경로가 없으면 FAIL 입니다. 수치는 evidence path 를 가져야 합니다."""
    body = "# state\n> updated_at: 2026-08-15\n> source_commit: `abc1234`\nG1 G2 G3\n"
    _write_current_state(tmp_path, body)
    res = check_current_state_sections(tmp_path)
    assert not res.ok
    assert "증거" in res.detail


def test_check_current_state_sections_unverifiable_commit_warns(tmp_path: Path):
    """부재를 증명할 수 없는 곳에서는 WARN 이며 통과로 셉니다.

    git 이력이 없는 압축본 검토와 얕은 클론이 여기 해당합니다.
    """
    body = (
        "# state\n> updated_at: 2026-08-15\n> source_commit: `deadbee`\nG1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    res = check_current_state_sections(tmp_path)
    assert res.ok
    assert res.warn


def test_check_current_state_sections_unknown_commit_in_git_repo_fails(tmp_path: Path, monkeypatch):
    """전체 이력이 있는데 커밋을 찾지 못하면 값이 틀린 것이므로 FAIL 입니다.

    반대로 얕은 클론에서는 커밋이 없는 것과 못 받은 것을 구분할 수 없어
    WARN 이어야 합니다. 이력 유무만 보고 FAIL 로 단정했더니 fetch-depth 1 인
    CI 테스트 잡 셋이 정상 값을 오타로 판정해 main 이 빨개졌습니다.
    """
    body = (
        "# state\n> updated_at: 2026-08-15\n> source_commit: `deadbee`\nG1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    monkeypatch.setattr(
        "scripts.validate_agent_rules._can_verify_commit_history", lambda root: True
    )
    res = check_current_state_sections(tmp_path)
    assert not res.ok
    assert "찾을 수 없습니다" in res.detail


def test_check_current_state_sections_stale_commit_fails(tmp_path: Path, monkeypatch):
    """허용 지연을 넘긴 source_commit 은 WARN 이 아니라 FAIL 입니다.

    경고로 두면 아무도 고치지 않습니다. 2026-08-19 측정에서 6 커밋 뒤처진 채
    WARN 만 내고 exit 0 이었습니다.
    """
    body = (
        "# state\n> updated_at: 2026-08-15\n> source_commit: `abc1234`\nG1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    monkeypatch.setattr(
        "scripts.validate_agent_rules._commits_behind_head",
        lambda root, commit: CURRENT_STATE_LAG_TOLERANCE + 1,
    )
    res = check_current_state_sections(tmp_path)
    assert not res.ok
    assert "뒤처짐" in res.detail


def test_check_current_state_sections_real_repo_within_tolerance():
    """실제 저장소의 source_commit 은 허용 지연 안에 있어야 합니다.

    CI 는 fetch-depth 0 으로 전체 이력을 받으므로 조회에 성공해야 정상입니다.
    다만 이 테스트가 실행되는 환경이 항상 git 저장소라는 보장은 없으므로,
    이력이 없어 미검증으로 내려앉은 경우만 예외로 둡니다.
    """
    res = check_current_state_sections(PROJECT_ROOT)
    assert res.ok
    if "신선도 미검증" in res.detail:
        assert res.warn
        return
    assert str(CURRENT_STATE_LAG_TOLERANCE) in res.detail


def test_check_context_budgets_warns_when_over(tmp_path: Path):
    """대상이 모두 있고 하나가 예산을 넘으면 FAIL 이 아니라 WARN 입니다.

    대상 부재는 별도로 FAIL 이므로 두 파일을 모두 만들어야 WARN 경로에 닿습니다.
    """
    (tmp_path / "AGENTS.md").write_text("가" * (AGENTS_CHAR_BUDGET + 1), encoding="utf-8")
    _write_current_state(tmp_path, "가" * (CURRENT_STATE_CHAR_BUDGET - 1))
    res = check_context_budgets(tmp_path)
    assert res.ok
    assert res.warn
    assert "AGENTS.md" in res.detail


def test_check_context_budgets_passes_within_budget(tmp_path: Path):
    """예산 이내면 WARN 없이 통과합니다."""
    (tmp_path / "AGENTS.md").write_text("가" * (AGENTS_CHAR_BUDGET - 1), encoding="utf-8")
    _write_current_state(tmp_path, "가" * (CURRENT_STATE_CHAR_BUDGET - 1))
    res = check_context_budgets(tmp_path)
    assert res.ok
    assert not res.warn


def test_warn_counts_as_pass_and_shows_warn_tag():
    """WARN 은 실패로 세지 않지만 화면에 드러나야 합니다."""
    from scripts.validate_agent_rules import CheckResult

    warned = CheckResult("x", True, "detail", warn=True)
    assert warned.ok
    assert warned.warn
    assert "[WARN]" in warned.format()

    failed = CheckResult("y", False, "detail", warn=True)
    assert not failed.warn, "실패한 검사는 WARN 으로 격하되지 않아야 합니다"
    assert "[FAIL]" in failed.format()


def test_source_commit_regex_does_not_cross_lines(tmp_path: Path):
    r"""값이 비었을 때 다른 줄의 해시 유사 문자열을 오인하지 않아야 합니다.

    이전 정규식은 `\D*` 를 써서 줄바꿈을 넘어 매칭했고, source_commit 값이
    비어 있어도 아래 줄의 deadbeef 를 커밋으로 읽었습니다.
    """
    body = (
        "# state\n> updated_at: 2026-08-15\n> **source_commit**: (미기록)\n\n"
        "어떤 문서 deadbeef 참조\nG1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    res = check_current_state_sections(tmp_path)
    assert not res.ok
    assert "커밋 해시를 읽을 수 없음" in res.detail


def test_source_commit_regex_accepts_markdown_emphasis(tmp_path: Path):
    """실제 문서 형식인 > **source_commit**: `hash` 를 읽어야 합니다."""
    body = (
        "# state\n> updated_at: 2026-08-15\n> **source_commit**: `deadbee`\n"
        "G1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    res = check_current_state_sections(tmp_path)
    assert res.ok
    assert "deadbee" in res.detail


def test_context_budgets_fails_when_target_missing(tmp_path: Path):
    """측정 대상이 없으면 통과가 아니라 실패입니다.

    대상 부재를 통과로 처리하면 파일이 사라진 상태를 조용히 넘깁니다.
    """
    res = check_context_budgets(tmp_path)
    assert not res.ok
    assert "측정 대상 없음" in res.detail


def test_git_probe_has_timeout_constant():
    """git 조회에 상한이 있어야 합니다.

    검증기는 pre-commit 에서 돌기 때문에 git 이 잠기면 커밋 자체가 막힙니다.
    """
    assert GIT_PROBE_TIMEOUT_SECONDS > 0

    source = (PROJECT_ROOT / "scripts" / "validate_agent_rules.py").read_text(encoding="utf-8")
    run_calls = source.count("subprocess.run(")
    timeout_args = source.count("timeout=GIT_PROBE_TIMEOUT_SECONDS")
    assert run_calls > 0
    assert timeout_args == run_calls, (
        f"subprocess.run {run_calls}회 중 timeout 지정 {timeout_args}회. 전부 지정해야 합니다"
    )


# ===========================================================================
# CURRENT_STATE 신선도는 정본 브랜치 기준으로 잽니다
# ===========================================================================


def test_freshness_ref_uses_merge_base_with_main(monkeypatch, tmp_path):
    """HEAD 로 재면 작업 브랜치 커밋까지 세어 문서가 낡은 것으로 오판됩니다.

    2026-08-30 세션에서 워커 브랜치가 커밋을 낼 때마다 허용치를 넘겨 갱신을 네 번
    반복했고, 그중 두 번은 어떤 값으로도 수렴하지 않았습니다. 갱신 커밋이 정본
    브랜치를 두 커밋 앞세우고 작업 브랜치가 그것을 병합하면 거리가 다시 늘기
    때문입니다.
    """
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "merge-base" in argv and "--is-ancestor" not in argv:
            return _Result("abc1234\n")
        if "rev-list" in argv:
            return _Result("2\n")
        return _Result("")

    monkeypatch.setattr("scripts.validate_agent_rules.subprocess.run", fake_run)
    behind = validate_agent_rules._commits_behind_head(tmp_path, "deadbee")

    assert behind == 2
    revlist = [c for c in calls if "rev-list" in c]
    assert revlist, "rev-list 를 호출해야 합니다"
    # 기준이 HEAD 가 아니라 merge-base 결과여야 합니다.
    assert any("deadbee..abc1234" in arg for arg in revlist[0])


def test_freshness_ref_falls_back_to_head_without_main(monkeypatch, tmp_path):
    """main 을 찾을 수 없으면 종전대로 HEAD 를 기준으로 씁니다."""

    def fake_run(argv, **kwargs):
        if "merge-base" in argv:
            raise subprocess.CalledProcessError(1, argv)
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr("scripts.validate_agent_rules.subprocess.run", fake_run)
    assert validate_agent_rules._freshness_ref(tmp_path) == "HEAD"


# ===========================================================================
# 워커 모델 배정표 (TIER_POLICY) 정합성 검증 테스트
# ===========================================================================


def _write_model_pool_doc(root: Path, table_rows: list[tuple[str, str, str, str]]) -> Path:
    target = root / "docs" / "ops" / "orca_worker_model_pool.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Orca 워커 모델 풀 정본",
        "",
        "## 1. 역할별 모델 배정 정책 (TIER_POLICY)",
        "",
        "| 역할 (`role`) | 위험도 (`risk`) | 1순위 (Primary) | 2순위 (Fallback) |",
        "| --- | :---: | --- | --- |",
    ]
    for role, risk, prim, fb in table_rows:
        lines.append(f"| `{role}` | `{risk}` | `{prim}` | `{fb}` |")
    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def test_check_worker_model_pool_drift_match_passes(tmp_path: Path):
    """문서 표가 TIER_POLICY 와 일치하면 통과합니다."""
    from scripts.orca_model_router import TIER_POLICY

    rows = [(k[0], k[1], v[0], v[1]) for k, v in TIER_POLICY.items()]
    _write_model_pool_doc(tmp_path, rows)

    res = check_worker_model_pool_drift(tmp_path)
    assert res.ok
    assert "완전 일치" in res.detail


def test_check_worker_model_pool_drift_primary_mismatch_fails(tmp_path: Path):
    """한 행의 primary 가 다르면 실패하고 그 조합이 detail 에 나와야 합니다."""
    from scripts.orca_model_router import TIER_POLICY

    rows = []
    for k, v in TIER_POLICY.items():
        if k == ("reviewer", "high"):
            rows.append((k[0], k[1], "gemini-flash-high", v[1]))
        else:
            rows.append((k[0], k[1], v[0], v[1]))
    _write_model_pool_doc(tmp_path, rows)

    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "값 불일치" in res.detail
    assert "reviewer" in res.detail
    assert "high" in res.detail


def test_check_worker_model_pool_drift_fallback_mismatch_fails(tmp_path: Path):
    """한 행의 fallback 이 다르면 실패하고 그 조합이 detail 에 나와야 합니다."""
    from scripts.orca_model_router import TIER_POLICY

    rows = []
    for k, v in TIER_POLICY.items():
        if k == ("builder", "low"):
            rows.append((k[0], k[1], v[0], "gemini-flash-high"))
        else:
            rows.append((k[0], k[1], v[0], v[1]))
    _write_model_pool_doc(tmp_path, rows)

    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "값 불일치" in res.detail
    assert "builder" in res.detail
    assert "low" in res.detail


def test_check_worker_model_pool_drift_code_only_combination_fails(tmp_path: Path):
    """코드에만 있는 조합이 있으면 실패해야 합니다."""
    from scripts.orca_model_router import TIER_POLICY

    # Omit __default__, low
    rows = [(k[0], k[1], v[0], v[1]) for k, v in TIER_POLICY.items() if k != ("__default__", "low")]
    _write_model_pool_doc(tmp_path, rows)

    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "코드에만 있는 조합" in res.detail
    assert "__default__" in res.detail


def test_check_worker_model_pool_drift_doc_only_combination_fails(tmp_path: Path):
    """문서에만 있는 조합이 있으면 실패해야 합니다."""
    from scripts.orca_model_router import TIER_POLICY

    rows = [(k[0], k[1], v[0], v[1]) for k, v in TIER_POLICY.items()]
    rows.append(("extra_role", "low", "qwen-plus", "gemini-flash-medium"))
    _write_model_pool_doc(tmp_path, rows)

    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "문서에만 있는 조합" in res.detail
    assert "extra_role" in res.detail


def test_check_worker_model_pool_drift_missing_file_or_unparseable_fails(tmp_path: Path):
    """표 파일이 없거나 표를 찾을 수 없으면 통과가 아니라 실패여야 합니다."""
    # 1. File missing
    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "문서 파일 없음" in res.detail

    # 2. File exists but without table
    target = tmp_path / "docs" / "ops" / "orca_worker_model_pool.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Title\nNo table here\n", encoding="utf-8")
    res = check_worker_model_pool_drift(tmp_path)
    assert not res.ok
    assert "배정표를 찾을 수 없거나 파싱 실패" in res.detail


# ===========================================================================
# AGENTS.md 워커 모델 배정표 부재 검증 테스트
# ===========================================================================


def test_check_agents_model_table_absence(tmp_path: Path):
    """AGENTS.md 에 구체 워커 모델 ID나 풀 키가 나타나면 실패해야 합니다."""
    agents_md = tmp_path / "AGENTS.md"

    # 1. Valid (only pointer, no worker model pool keys / IDs)
    valid_content = """# AGENTS.md
- 코디네이터의 기본값은 Codex `gpt-5.6-terra` + effort `medium`입니다.
- 워커 모델 배정의 실행 정본은 scripts/orca_model_router.py의 TIER_POLICY 입니다.
"""
    agents_md.write_text(valid_content, encoding="utf-8")
    res = check_agents_model_table_absence(tmp_path)
    assert res.ok

    # 2. Worker model ID present (e.g. gemini-3.7-flash-high)
    bad_content_id = valid_content + "\n| builder | high | `gemini-3.7-flash-high` |\n"
    agents_md.write_text(bad_content_id, encoding="utf-8")
    res = check_agents_model_table_absence(tmp_path)
    assert not res.ok
    assert "gemini-3.7-flash-high" in res.detail

    # 3. Worker pool key present (e.g. qwen-plus)
    bad_content_key = valid_content + "\n- reviewer 모델: `qwen-plus`\n"
    agents_md.write_text(bad_content_key, encoding="utf-8")
    res = check_agents_model_table_absence(tmp_path)
    assert not res.ok
    assert "qwen-plus" in res.detail

    # 4. Missing file
    agents_md.unlink()
    res = check_agents_model_table_absence(tmp_path)
    assert not res.ok
    assert "파일 없음" in res.detail


# ===========================================================================
# CURRENT_STATE 6.1 Unknowns 상태 모순 검사 테스트
# ===========================================================================


def test_check_current_state_unknowns_contradictions(tmp_path: Path):
    """CURRENT_STATE 6.1 절의 동일 사안 상태 모순을 기계로 탐지합니다."""
    # 1. Valid content with distinct topics
    valid_body = """# CURRENT_STATE
> updated_at: 2026-08-31
> source_commit: `9d38a2a`

### 6.1 알려진 미해결 사항 (Unknowns)

- **Wave G 조율 평면 정합성 (2026-08-31, 병합 완료)**: 외부 감사 완료.
- **리뷰어 실행 경로 (2026-08-31, 해소)**: 실행 경로 정상화.
- **공고 상세 페이지 쿼리 (코드 수정 완료, 실측 미수행)**: 실측 대기.
- Windows Docker Desktop 실기 미검증.

### 6.2 정본 갱신 규약 (Update Protocol)
"""
    _write_current_state(tmp_path, valid_body)
    res = check_current_state_unknowns_contradictions(tmp_path)
    assert res.ok
    assert "모순 없음 확인" in res.detail

    # 2. Cross-item contradiction for same topic (e.g., q21)
    cross_conflict_body = """# CURRENT_STATE
### 6.1 알려진 미해결 사항 (Unknowns)

- **q21 결함 (2026-08-31, 해소)**: q21 재순위 결함 닫힘.
- **q21 결함 (2026-08-30, 수정 미적용)**: q21 아직 미적용 상태.

### 6.2 정본 갱신 규약
"""
    _write_current_state(tmp_path, cross_conflict_body)
    res = check_current_state_unknowns_contradictions(tmp_path)
    assert not res.ok
    assert "복수 항목 간 상태 모순" in res.detail
    assert "q21 결함" in res.detail

    # 3. Single-item contradiction (해소 and 수정 미적용 in same header)
    single_conflict_body = """# CURRENT_STATE
### 6.1 알려진 미해결 사항 (Unknowns)

- **q21 결함 (2026-08-31, 해소, 수정 미적용)**: 모순된 상태 표기.

### 6.2 정본 갱신 규약
"""
    _write_current_state(tmp_path, single_conflict_body)
    res = check_current_state_unknowns_contradictions(tmp_path)
    assert not res.ok
    assert "단일 항목 내부 상태 모순" in res.detail

    # 4. Missing file
    (tmp_path / "docs" / "context" / "CURRENT_STATE.md").unlink()
    res = check_current_state_unknowns_contradictions(tmp_path)
    assert not res.ok
    assert "파일 없음" in res.detail

    # 5. Missing 6.1 section
    _write_current_state(tmp_path, "# CURRENT_STATE\n## 1. 개요\n")
    res = check_current_state_unknowns_contradictions(tmp_path)
    assert not res.ok
    assert "6.1절" in res.detail


def test_unresolved_only_item_is_not_flagged_as_contradiction(tmp_path):
    """미해결 표기만 있는 항목을 모순으로 잡으면 안 됩니다.

    부분 문자열로 찾으면 "미해결" 안의 "해결" 과 "미완료" 안의 "완료" 가 해소
    표지로 잡혀 정상 항목이 전부 오탐됩니다. 2026-08-31 에 실제로 발생했습니다.
    """
    from scripts.validate_agent_rules import check_current_state_unknowns_contradictions

    doc = tmp_path / "docs" / "context" / "CURRENT_STATE.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# 정본\n\n"
        "### 6.1 알려진 미해결 사항 (Unknowns)\n\n"
        "- **ngram 경계값 7 클래스 미실측 (2026-08-31, 미해결)**: 실측이 필요합니다.\n"
        "- **다른 항목 (2026-08-31, 미완료)**: 아직 남았습니다.\n\n"
        "### 6.2 정본 갱신 규약 (Update Protocol)\n",
        encoding="utf-8",
    )

    result = check_current_state_unknowns_contradictions(tmp_path)

    assert result.ok, f"미해결 표기만 있는 항목을 모순으로 잡았습니다: {result.detail}"


def test_genuine_contradiction_is_still_flagged(tmp_path):
    """오탐을 없애면서 진짜 모순까지 놓치면 검사가 무의미해집니다."""
    from scripts.validate_agent_rules import check_current_state_unknowns_contradictions

    doc = tmp_path / "docs" / "context" / "CURRENT_STATE.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# 정본\n\n"
        "### 6.1 알려진 미해결 사항 (Unknowns)\n\n"
        "- **q21 검색 실패 (2026-08-30, 해소, 수정 미적용)**: 서로 다른 상태입니다.\n\n"
        "### 6.2 정본 갱신 규약 (Update Protocol)\n",
        encoding="utf-8",
    )

    result = check_current_state_unknowns_contradictions(tmp_path)

    assert not result.ok, "해소와 미적용이 함께 있는 항목을 잡지 못했습니다"
