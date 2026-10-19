"""한국지역난방공사 규칙의 배점 B·계수 k 두 축 분리 시험.

원문(.cache/kdhc_src/9a4a0170f80e_...2026.01.01.hwp)에서 별표 1·3·4·5의2·7·8 의
입찰가격 평점 계산식은 "고시금액 이상 k=2, 고시금액 미만 k=4" 로 계수를 고시금액 축으로
두고, 배점한도 B 는 "5억원 이상 60 / 5억원 미만 70" 으로 추정가격 5억원 축으로 따로 둔다.
기존 규칙이 두 축을 5억원 경계 하나로 묶어 '고시금액 이상 5억원 미만' 공고에 k=4 를
잘못 쓰던 것을 세 구간으로 고쳤다.

고치지 않은 규칙:
 - SERVC_INST_KDHC_*_FACILITY (별표 2): k=5 단일 (원문 k 단일)
 - SERVC_INST_KDHC_*_SW_TARGET (별표 3의2): k=4 단일
 - SERVC_INST_KDHC_*_PASSENGER (별표 5): k=4 단일
 - SERVC_INST_KDHC_*_INSURANCE (별표 6): k=0.375 단일
 - SERVC_INST_KDHC_20260101_OTHER (별표 9): 원문이 고시금액 축으로 B·k 를 함께 둠 (이미 2구간)
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    INSTITUTION_RULES,
    resolve_score_params,
)

AFFECTED_CURRENT = (
    "SERVC_INST_KDHC_20260101_ACADEMIC",
    "SERVC_INST_KDHC_20260101_SW",
    "SERVC_INST_KDHC_20260101_WASTE",
    "SERVC_INST_KDHC_20260101_FREIGHT",
    "SERVC_INST_KDHC_20260101_REPAIR",
    "SERVC_INST_KDHC_20260101_LEASE",
)
AFFECTED_PREDECESSOR = "SERVC_INST_KDHC_20230719_WASTE"

# (rule_id, 6억원 이상일 때 B)
TOP_B = {
    "SERVC_INST_KDHC_20260101_LEASE": Decimal("70"),
}
DEFAULT_TOP_B = Decimal("60")


def _rule(rule_id: str):
    return next(r for r in INSTITUTION_RULES if r.rule_id == rule_id)


def _check(rule_id: str, price: str, b: str, k: str, lwlt: str) -> None:
    rule = _rule(rule_id)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.max_price_score == Decimal(b), (rule_id, price, "B")
    assert result.multiplier == Decimal(k), (rule_id, price, "k")
    assert result.pass_threshold == Decimal("85"), (rule_id, price, "T")
    band = rule.price_bands[result.price_band_index]
    assert band.lwlt_rate == Decimal(lwlt), (rule_id, price, "lwlt")
    assert band.base_rate == Decimal("0.88"), (rule_id, price, "base")


def test_current_rules_three_bands() -> None:
    for rule_id in AFFECTED_CURRENT:
        top_b = TOP_B.get(rule_id, DEFAULT_TOP_B)
        # 고시금액 미만 (2억원)
        _check(rule_id, "200000000", "70", "4", "84.245")
        # 고시금액 이상 5억원 미만 (3억원)
        _check(rule_id, "300000000", "70", "2", "80.495")
        # 5억원 이상 (6억원)
        _check(rule_id, "600000000", str(top_b), "2", "80.495")


def test_predecessor_rule_three_bands() -> None:
    rid = AFFECTED_PREDECESSOR
    _check(rid, "200000000", "70", "4", "84.245")
    _check(rid, "300000000", "70", "2", "80.495")
    _check(rid, "600000000", "60", "2", "80.495")
