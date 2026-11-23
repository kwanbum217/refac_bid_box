"""Capsule 기본 사실에 토큰 절약 규칙이 들어가는지 검증합니다."""

from __future__ import annotations

from scripts.orca_taskctl import BASE_GROUND_TRUTH, _format_ground_truth


def test_base_ground_truth_includes_token_saving_rule():
    facts = [fact for fact, _ in BASE_GROUND_TRUTH]
    assert any(fact.startswith("토큰 절약:") for fact in facts)
    assert "전량 시험은 배경이 아니라 앞에서 한 번만" in _format_ground_truth([])


def test_token_saving_rule_covers_step_waste_patterns():
    fact = next(fact for fact, _ in BASE_GROUND_TRUTH if fact.startswith("토큰 절약:"))
    for phrase in ("processlist", "grep -n", "편집이 실패하면", "2~3건씩", "한 번만 보낸다"):
        assert phrase in fact
