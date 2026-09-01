from __future__ import annotations

import json
from pathlib import Path

from scripts.measure_agent_bootstrap_cost import (
    DEFAULT_BUDGETS,
    PROJECT_ROOT,
    build_report,
    format_table,
    measure_all_clis,
    measure_antigravity_cost,
    measure_claude_cost,
    measure_codex_cost,
    measure_cursor_cost,
    measure_opencode_cost,
)


def test_real_repo_bootstrap_cost_measurement():
    """실제 저장소의 5개 CLI 부트스트랩 비용 측정이 정상 수행되고 보고서가 올바르게 생성되는지 검증."""
    raw_entries = measure_all_clis(PROJECT_ROOT)
    assert len(raw_entries) == 5

    report = build_report(PROJECT_ROOT)
    assert report["schema"] == "ORCA_BOOTSTRAP_COST_REPORT_V1"
    assert report["total_clis"] == 5
    assert len(report["entries"]) == 5

    cli_names = [e["cli"] for e in report["entries"]]
    assert cli_names == ["Codex", "opencode", "Antigravity", "Claude Code", "Cursor"]

    for entry in report["entries"]:
        assert entry["char_count"] > 0
        assert entry["budget"] > 0
        assert entry["status"] in ("PASS", "EXCEEDED")
        assert entry["ratio"] >= 0.0
        if entry["within_budget"]:
            assert entry["status"] == "PASS"
            assert entry["char_count"] <= entry["budget"]
        else:
            assert entry["status"] == "EXCEEDED"
            assert entry["char_count"] > entry["budget"]

    # 복합 저장소 예산(12000) 등 커스텀 예산 주입 시 all_within_budget 정상 반영 검증
    custom_report = build_report(
        PROJECT_ROOT,
        budgets={
            "Codex": 12000,
            "opencode": 12000,
            "Antigravity": 12000,
            "Claude Code": 8000,
            "Cursor": 12000,
        },
    )
    assert custom_report["all_within_budget"] is True


def test_measure_individual_clis_in_tmp_path(tmp_path: Path):
    """가상 디렉터리에서 각 CLI 진입점별 측정 로직 검증."""
    # 1. Codex (AGENTS.md)
    agents_content = "# AGENTS\nNon-negotiables and rules."
    (tmp_path / "AGENTS.md").write_text(agents_content, encoding="utf-8")
    codex_res = measure_codex_cost(tmp_path)
    assert codex_res["cli"] == "Codex"
    assert codex_res["char_count"] == len(agents_content)
    assert codex_res["budget"] == DEFAULT_BUDGETS["Codex"]
    assert codex_res["within_budget"] is True

    # 2. opencode (opencode.json -> instructions)
    opencode_json = tmp_path / "opencode.json"
    opencode_json.write_text(json.dumps({"instructions": ["AGENTS.md"]}), encoding="utf-8")
    opencode_res = measure_opencode_cost(tmp_path)
    assert opencode_res["cli"] == "opencode"
    assert opencode_res["char_count"] == len(agents_content)
    assert opencode_res["within_budget"] is True

    # 3. Antigravity (.antigravity/rules.md)
    ag_dir = tmp_path / ".antigravity"
    ag_dir.mkdir(parents=True, exist_ok=True)
    ag_content = "# Antigravity Rules\nSummary of core guidelines."
    (ag_dir / "rules.md").write_text(ag_content, encoding="utf-8")
    ag_res = measure_antigravity_cost(tmp_path)
    assert ag_res["cli"] == "Antigravity"
    assert ag_res["char_count"] == len(ag_content)
    assert ag_res["budget"] == DEFAULT_BUDGETS["Antigravity"]
    assert ag_res["within_budget"] is True

    # 4. Claude Code (CLAUDE.md)
    claude_content = "# Claude Code\n@AGENTS.md"
    (tmp_path / "CLAUDE.md").write_text(claude_content, encoding="utf-8")
    claude_res = measure_claude_cost(tmp_path)
    assert claude_res["cli"] == "Claude Code"
    assert claude_res["char_count"] == len(claude_content)
    assert claude_res["budget"] == DEFAULT_BUDGETS["Claude Code"]
    assert claude_res["within_budget"] is True

    # 5. Cursor (.cursor/rules/*.mdc)
    cursor_dir = tmp_path / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    rule1 = "# Rule 1\nContent 1"
    rule2 = "# Rule 2\nContent 2"
    (cursor_dir / "00-core.mdc").write_text(rule1, encoding="utf-8")
    (cursor_dir / "01-extra.mdc").write_text(rule2, encoding="utf-8")
    cursor_res = measure_cursor_cost(tmp_path)
    assert cursor_res["cli"] == "Cursor"
    assert cursor_res["char_count"] == len(rule1) + len(rule2)
    assert len(cursor_res["paths"]) == 2
    assert cursor_res["within_budget"] is True


def test_budget_exceeded_and_status(tmp_path: Path):
    """예산 초과 시 within_budget=False, status='EXCEEDED' 반영 검증."""
    overflow_text = "x" * 10000
    (tmp_path / "AGENTS.md").write_text(overflow_text, encoding="utf-8")

    # budget 8000 인 Codex 에서 10000자 초과
    res = measure_codex_cost(tmp_path, budget=8000)
    assert res["char_count"] == 10000
    assert res["budget"] == 8000
    assert res["ratio"] == 1.25
    assert res["ratio_pct"] == 125.0
    assert res["within_budget"] is False
    assert res["status"] == "EXCEEDED"


def test_opencode_custom_instructions_and_fallback(tmp_path: Path):
    """opencode.json 의 instructions 커스텀 배열 및 폴백 동작 검증."""
    # 1. 다중 instructions 문서
    doc1 = tmp_path / "DOC1.md"
    doc2 = tmp_path / "DOC2.md"
    doc1.write_text("Hello", encoding="utf-8")  # 5 chars
    doc2.write_text("World!", encoding="utf-8")  # 6 chars

    opencode_json = tmp_path / "opencode.json"
    opencode_json.write_text(
        json.dumps({"instructions": ["DOC1.md", "DOC2.md"]}),
        encoding="utf-8",
    )
    res = measure_opencode_cost(tmp_path)
    assert res["char_count"] == 11
    assert res["paths"] == ["DOC1.md", "DOC2.md"]

    # 2. opencode.json 파싱 실패 시 폴백
    opencode_json.write_text("{broken json", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Fallback content", encoding="utf-8")
    fallback_res = measure_opencode_cost(tmp_path)
    assert fallback_res["paths"] == ["AGENTS.md"]
    assert fallback_res["char_count"] == len("Fallback content")


def test_cursor_rules_fallback_when_dir_missing(tmp_path: Path):
    """.cursor/rules 디렉터리가 없을 때 폴백 파일 경로를 처리하는지 검증."""
    res = measure_cursor_cost(tmp_path)
    assert res["exists"] is False
    assert res["char_count"] == 0
    assert res["within_budget"] is True


def test_character_count_is_characters_not_bytes(tmp_path: Path):
    """문자 수가 바이트 수가 아닌 문자 수(len())로 정확히 계측되는지 한글 문자열로 검증."""
    korean_text = "데이터 무손실 원칙과 단일 진실 원천"  # 21자 (UTF-8 바이트 수는 훨씬 큼)
    utf8_bytes_len = len(korean_text.encode("utf-8"))
    char_len = len(korean_text)

    assert utf8_bytes_len > char_len  # 바이트 수가 문자 수보다 큼 (3바이트 * 한글)

    (tmp_path / "AGENTS.md").write_text(korean_text, encoding="utf-8")
    res = measure_codex_cost(tmp_path)

    assert res["char_count"] == char_len
    assert res["char_count"] != utf8_bytes_len


def test_format_table_and_report_generation(tmp_path: Path):
    """build_report 및 format_table 출력 형식 검증."""
    (tmp_path / "AGENTS.md").write_text("Test", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Test", encoding="utf-8")
    (tmp_path / "opencode.json").write_text(
        json.dumps({"instructions": ["AGENTS.md"]}), encoding="utf-8"
    )
    ag_dir = tmp_path / ".antigravity"
    ag_dir.mkdir(parents=True, exist_ok=True)
    (ag_dir / "rules.md").write_text("Test", encoding="utf-8")
    cursor_dir = tmp_path / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / "00-core.mdc").write_text("Test", encoding="utf-8")

    report = build_report(tmp_path)
    assert report["total_clis"] == 5
    assert report["all_within_budget"] is True

    table_str = format_table(report)
    assert "Codex" in table_str
    assert "opencode" in table_str
    assert "Antigravity" in table_str
    assert "Claude Code" in table_str
    assert "Cursor" in table_str
    assert "PASS" in table_str
