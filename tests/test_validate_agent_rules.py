from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_agent_rules import (
    AGENTS_CHAR_BUDGET,
    ANTIGRAVITY_CHAR_CAP,
    CONTRACT_VERSION,
    CURRENT_STATE_CHAR_BUDGET,
    CURRENT_STATE_LAG_TOLERANCE,
    GIT_PROBE_TIMEOUT_SECONDS,
    PROJECT_ROOT,
    check_agents_single_root,
    check_antigravity_rules,
    check_claude_is_pointer,
    check_context_budgets,
    check_current_state_exists,
    check_current_state_sections,
    check_cursor_references_agents,
    check_opencode_json,
    check_orca_coordination_skill,
    check_skills_mirror,
    check_task_capsule_v2_docs,
    check_v2_templates,
    get_all_checks,
    parse_yaml_keys_fallback,
    run_all_checks,
)


def test_real_repo_validation_passes():
    """실제 저장소의 v2 정합성 검증이 100% 통과하는지 확인."""
    checks = get_all_checks(PROJECT_ROOT)
    assert len(checks) == 12
    for chk in checks:
        assert chk.ok, f"Check failed: {chk.name} -> {chk.detail}"
    assert run_all_checks(PROJECT_ROOT, quiet=True) == 0


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
    """git 으로 확인할 수 없는 커밋은 WARN 이며 통과로 셉니다."""
    body = (
        "# state\n> updated_at: 2026-08-15\n> source_commit: `deadbee`\nG1 G2 G3\ndocs/ops/x.md\n"
    )
    _write_current_state(tmp_path, body)
    res = check_current_state_sections(tmp_path)
    assert res.ok
    assert res.warn


def test_check_current_state_sections_real_repo_within_tolerance():
    """실제 저장소의 source_commit 은 허용 지연 안에 있어야 합니다."""
    res = check_current_state_sections(PROJECT_ROOT)
    assert res.ok
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
