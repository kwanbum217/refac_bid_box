from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1.evaluations import _score_table
from src.app.schemas.evaluations import QualificationInput
from src.app.services.evaluation_rules import (
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    EvaluationRule,
    resolve_score_params,
)
from src.ml.features import _notice_amount_for
from src.ml.notice_amount import notice_amount_for_year

RULES = PRE_20230501_RULES + PRE_20250901_RULES + POST_20260526_RULES + POST_20260727_RULES


def rule_for(generation: str, attachment: int) -> EvaluationRule:
    suffix = f"_{generation}_ATTACH_{attachment:02d}"
    return next(rule for rule in RULES if rule.rule_id.endswith(suffix))


@pytest.mark.parametrize(
    ("price", "expected"),
    [(Decimal("499999999"), Decimal("70")), (Decimal("500000000"), Decimal("60"))],
)
def test_b_uses_500m_boundary_with_equal_value_on_at_least_side(price, expected):
    result = resolve_score_params(rule_for("POST_20260526", 1), price, date(2026, 1, 1), None)
    assert result.max_price_score == expected
    assert result.max_price_score_basis == "ESTIMATED_PRICE"


@pytest.mark.parametrize(
    ("year", "price", "expected"),
    [
        (2024, Decimal("219999999"), Decimal("4")),
        (2024, Decimal("220000000"), Decimal("2")),
        (2025, Decimal("229999999"), Decimal("4")),
        (2025, Decimal("230000000"), Decimal("2")),
    ],
)
def test_k_uses_announcement_year_notice_boundary(year, price, expected):
    result = resolve_score_params(rule_for("POST_20260526", 5), price, date(year, 6, 1), None)
    assert result.multiplier == expected
    assert result.multiplier_boundary == notice_amount_for_year(year)


def test_missing_price_does_not_select_conditional_values():
    result = resolve_score_params(rule_for("POST_20260526", 1), None, date(2026, 1, 1), None)
    assert result.max_price_score is None
    assert result.max_price_score_basis is None


def test_method_name_wins_and_conflict_warns():
    result = resolve_score_params(
        rule_for("POST_20260526", 1),
        Decimal("500000000"),
        date(2026, 1, 1),
        "추정가격 5억원 미만 2억원 이상인 용역",
    )
    assert result.max_price_score == Decimal("70")
    assert result.max_price_score_basis == "METHOD_NAME"
    assert result.warnings


def test_method_parser_uses_five_hundred_million_marker_in_compound_range():
    result = resolve_score_params(
        rule_for("POST_20260526", 1),
        Decimal("600000000"),
        date(2026, 1, 1),
        "추정가격 5억원 미만 2억원 이상",
    )
    assert result.max_price_score == Decimal("70")
    assert result.max_price_score_basis == "METHOD_NAME"


def test_notice_method_can_select_without_announcement_date():
    result = resolve_score_params(rule_for("POST_20260526", 5), None, None, "고시금액 이상")
    assert result.multiplier == Decimal("2")


def test_missing_announcement_date_does_not_choose_conditional_k_from_price():
    result = resolve_score_params(rule_for("POST_20260526", 5), Decimal("100000000"), None, None)
    assert result.multiplier is None
    assert result.multiplier_basis is None


def test_attach_17_b_stays_manual_and_attach_16_b_stays_fixed():
    attach17 = rule_for("PRE_20250901", 17)
    attach16 = rule_for("PRE_20250901", 16)
    assert attach17.max_price_score_by_500m is None
    assert attach16.max_price_score == Decimal("70")
    assert attach16.max_price_score_by_500m is None


@pytest.mark.parametrize(
    ("generation", "attachment"),
    [
        (generation, attachment)
        for generation, attachments in (
            ("PRE_20230501", (1, 2, 3, 4)),
            ("PRE_20250901", (1, 2, 3, 4)),
            ("POST_20260526", (1, 2, 3, 4)),
            ("POST_20260727", (3, 4)),
        )
        for attachment in attachments
    ],
)
def test_single_formula_attachment_k_remains_fixed(generation, attachment):
    rule = rule_for(generation, attachment)
    assert rule.multiplier_by_notice is None
    assert rule.multiplier is not None


def test_fixed_and_conditional_axis_cannot_be_declared_together():
    with pytest.raises(ValueError):
        replace(rule_for("POST_20260526", 1), max_price_score=Decimal("70"))
    with pytest.raises(ValueError):
        replace(rule_for("POST_20260526", 1), multiplier_by_notice=(Decimal("4"), Decimal("2")))


@pytest.mark.parametrize(
    ("generation", "attachment", "price", "year", "expected_b", "expected_k"),
    [
        ("PRE_20230501", 5, "200000000", 2023, "70", "4"),
        ("PRE_20250901", 5, "250000000", 2025, "70", "2"),
        ("POST_20260526", 5, "230000000", 2025, "70", "2"),
        ("POST_20260727", 3, "600000000", 2026, "60", "4"),
    ],
)
def test_representative_rule_selection_across_generations(
    generation, attachment, price, year, expected_b, expected_k
):
    result = resolve_score_params(rule_for(generation, attachment), price, date(year, 6, 1), None)
    assert result.max_price_score == Decimal(expected_b)
    assert result.multiplier == Decimal(expected_k)


def test_user_input_still_overrides_resolved_declarations():
    rule = rule_for("POST_20260526", 1)
    table, missing, overridden, resolution = _score_table(
        QualificationInput(max_price_score=65, multiplier=3, pass_threshold=95),
        rule,
        SimpleNamespace(
            presmpt_prce=400_000_000, base_amount=900_000_000, bid_ntce_dt=date(2026, 1, 1)
        ),
    )
    assert table is not None
    assert table.max_price_score == Decimal("65")
    assert table.multiplier == Decimal("3")
    assert missing == []
    assert overridden == ["max_price_score", "multiplier", "pass_threshold"]
    assert resolution.max_price_score == Decimal("70")


def test_base_amount_alone_does_not_select_score_parameter():
    table, missing, _, resolution = _score_table(
        QualificationInput(),
        rule_for("POST_20260526", 1),
        SimpleNamespace(presmpt_prce=None, base_amount=100_000_000, bid_ntce_dt=date(2026, 1, 1)),
    )
    assert table is None
    assert "max_price_score" in missing
    assert resolution.max_price_score is None


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2023, 220_000_000),
        (2024, 220_000_000),
        (2025, 230_000_000),
        (2026, 230_000_000),
        (2021, 220_000_000),
    ],
)
def test_features_notice_amount_values_remain_unchanged(year, expected):
    assert _notice_amount_for(SimpleNamespace(year=year)) == expected
