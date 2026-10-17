"""광주 구판 규칙 지역제한 금액 경계(광역 본청 vs 자치구) 시험.

정본: Capsule task_gwangju_region_limit_boundary_20261018.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    resolve_evaluation_rule,
    resolve_score_params,
)

WASTE_METHOD = "폐기물처리용역 적격심사 추정가격 고시금액미만"
LAND_TRANSPORT_METHOD = "여객 육상운송용역 적격심사 추정가격 5억원미만"

METRO_WASTE_330 = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_330"
METRO_WASTE_350 = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_350"
METRO_LT_330 = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5_METRO_330"
METRO_LT_350 = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5_METRO_350"
LEGACY_WASTE = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3"
LEGACY_LT = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5"


def _resolve(inst: str, method: str, announced: str, price: str, **kw):
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime="LOCAL",
        bid_ntce_dt=announced,
        region_code="29",
        region_name="광주광역시",
        institution_name=inst,
        estimated_price=Decimal(price),
        **kw,
    )


@pytest.mark.parametrize(
    ("inst", "announced", "price", "expected_rule", "expected_b"),
    [
        ("광주광역시", "2024-06-01", "340000000", METRO_WASTE_330, "30"),
        ("광주광역시 북구", "2024-06-01", "340000000", LEGACY_WASTE, "80"),
        ("광주광역시", "2025-03-01", "340000000", METRO_WASTE_350, "80"),
        ("광주광역시", "2025-03-01", "360000000", METRO_WASTE_350, "30"),
        ("광주광역시교육청", "2025-03-01", "360000000", LEGACY_WASTE, "80"),
    ],
)
def test_waste_boundary(inst, announced, price, expected_rule, expected_b):
    r = _resolve(inst, WASTE_METHOD, announced, price)
    assert r.rule is not None
    assert r.rule.rule_id == expected_rule
    assert r.is_blocked is False
    res = resolve_score_params(r.rule, Decimal(price), None, None)
    assert res.max_price_score == Decimal(expected_b)


@pytest.mark.parametrize(
    ("inst", "announced", "price", "expected_rule", "expected_b"),
    [
        ("광주광역시", "2024-06-01", "340000000", METRO_LT_330, "60"),
        ("광주광역시 북구", "2024-06-01", "340000000", LEGACY_LT, "70"),
        ("광주광역시", "2025-03-01", "340000000", METRO_LT_350, "70"),
        ("광주광역시", "2025-03-01", "360000000", METRO_LT_350, "60"),
    ],
)
def test_land_transport_boundary(inst, announced, price, expected_rule, expected_b):
    r = _resolve(inst, LAND_TRANSPORT_METHOD, announced, price)
    assert r.rule is not None
    assert r.rule.rule_id == expected_rule
    assert r.is_blocked is False
    res = resolve_score_params(r.rule, Decimal(price), None, None)
    assert res.max_price_score == Decimal(expected_b)


def test_after_regime_uses_current_rule():
    r = _resolve("광주광역시", WASTE_METHOD, "2026-08-01", "340000000")
    assert r.rule is not None
    assert r.rule.rule_id == "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"


def test_no_date_keeps_legacy_for_autonomy():
    r = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=WASTE_METHOD,
        contract_regime="LOCAL",
        bid_ntce_dt=None,
        region_code="29",
        region_name="광주광역시",
        institution_name="광주광역시",
        estimated_price=Decimal("340000000"),
    )
    # 공고일이 없으면 폐지되지 않은 규칙(5억 경계)을 유지한다.
    assert r.rule is not None
