"""적격심사 규칙 레지스트리 공통 계약 시험.

기술용역 두 규칙이 단일값 B·k·T 대신 구간 목록으로 배점표를 선언하면서도,
기존 일반용역 규칙의 배점표 해석 경로가 그대로인지 고정한다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    POST_20260526_RULES,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
    resolve_score_params,
    select_price_band,
    select_threshold_band,
)

TECH_RULES = (
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
)


@pytest.mark.parametrize("rule", TECH_RULES, ids=lambda rule: rule.rule_id)
def test_tech_rule_declares_band_lists_instead_of_single_values(rule) -> None:
    """기술용역 규칙은 네 구간 B·k 와 두 구간 T 를 목록으로 선언한다."""
    assert rule.price_bands is not None
    assert len(rule.price_bands) == 4
    assert rule.threshold_bands is not None
    assert len(rule.threshold_bands) == 2
    assert rule.max_price_score is None
    assert rule.multiplier is None
    assert rule.pass_threshold is None
    assert rule.max_price_score_by_500m is None
    assert rule.multiplier_by_notice is None
    assert rule.lwlt_rate is None
    assert rule.score_table_source


@pytest.mark.parametrize("rule", TECH_RULES, ids=lambda rule: rule.rule_id)
def test_tech_rule_band_order_and_source(rule) -> None:
    """구간은 추정가격 오름차순이고 모든 구간에 출처가 남는다."""
    upper_bounds = [band.upper_bound for band in rule.price_bands]
    assert upper_bounds[0] is not None
    assert upper_bounds[1] == Decimal("500000000")
    assert upper_bounds[2] == Decimal("1000000000")
    assert upper_bounds[3] is None
    for band in rule.price_bands:
        assert band.source
        assert "data/reference/pps_tech_lwlt_pre_20260526.yaml" in band.source
    for band in rule.threshold_bands:
        assert band.source
        assert "제4조" in band.source


@pytest.mark.parametrize("rule", TECH_RULES, ids=lambda rule: rule.rule_id)
def test_tech_rule_helpers_select_declared_bands(rule) -> None:
    """select_price_band·select_threshold_band 가 선언 구간을 그대로 고른다."""
    price_band, index, reason = select_price_band(rule.price_bands, Decimal("400000000"))
    threshold_band, _, threshold_reason = select_threshold_band(
        rule.threshold_bands, Decimal("400000000")
    )

    assert reason is None
    assert threshold_reason is None
    assert index == 1
    assert price_band is not None
    assert price_band.max_price_score == Decimal("70")
    assert threshold_band is not None
    assert threshold_band.pass_threshold == Decimal("95")


def test_general_service_registry_score_table_path_is_unchanged() -> None:
    """일반용역 규칙은 종전처럼 단일·조건부 필드로 배점표를 해석한다."""
    rule = next(
        rule for rule in POST_20260526_RULES if rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"
    )

    resolution = resolve_score_params(
        rule,
        Decimal("400000000"),
        "2026-11-01",
        "시설분야용역 적격심사 추정가격 5억원 미만",
    )

    assert rule.price_bands is None
    assert resolution.max_price_score == Decimal("70")
    assert resolution.multiplier == Decimal("5")
    assert resolution.pass_threshold == Decimal("85")
    assert resolution.base_rate is None
