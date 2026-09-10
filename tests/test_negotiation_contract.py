"""협상에의한계약 판별 및 평가비율 제공 계약 테스트."""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_NEGOTIATION_CONTRACT,
    NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING,
    NEGOTIATION_VARIANT_ENGINEERING,
    NEGOTIATION_VARIANT_STANDARD,
    NEGOTIATION_VARIANT_SW,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)


@pytest.mark.parametrize(
    ("method", "variant"),
    [
        ("협상에의한계약-협상에 의한 낙찰자 결정", NEGOTIATION_VARIANT_STANDARD),
        ("협상에의한계약-협상에 의한 낙찰자 결정(SW사업)", NEGOTIATION_VARIANT_SW),
        ("협상에의한계약-협상에 의한 낙찰자 결정(엔지니어링)", NEGOTIATION_VARIANT_ENGINEERING),
        (
            "협상에의한계약-협상에 의한 낙찰자 결정(건설엔지니어링)",
            NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING,
        ),
    ],
)
def test_negotiation_variants_are_recognized(method, variant):
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "sucsfbidMthdNm": method,
            "techAbltEvlRt": "80",
            "bidPrceEvlRt": "20",
        },
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert result.negotiation_variant == variant
    assert result.negotiation_tech_eval_rate == Decimal("80")
    assert result.negotiation_price_eval_rate == Decimal("20")
    assert result.rule is None


def test_multi_supplier_contract_is_not_negotiation_contract():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {"sucsfbidMthdNm": "다수공급자계약-적격성평가 및 가격협상(다수공급자)"},
    )

    assert result.block_reason_code != BLOCK_CODE_NEGOTIATION_CONTRACT
    assert result.negotiation_variant is None


@pytest.mark.parametrize(
    ("tech_rate", "price_rate", "expected_warning"),
    [
        ("", "20", "기술능력 평가비율"),
        ("80", "not-a-number", "입찰가격 평가비율"),
        ("70", "20", "합계"),
    ],
)
def test_negotiation_ratio_missing_or_invalid_values_warn(tech_rate, price_rate, expected_warning):
    result = resolve_evaluation_rule(
        "Servc",
        "복수예가",
        "협상에의한계약-협상에 의한 낙찰자 결정",
        tech_ablt_evl_rt=tech_rate,
        bid_prce_evl_rt=price_rate,
    )

    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert any(expected_warning in warning for warning in result.warnings)


def test_existing_general_service_rule_still_matches():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
            "sucsfbidLwltRate": "89.995",
        },
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"
    assert result.negotiation_variant is None
