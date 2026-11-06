"""지방 규칙 모듈의 서비스 유형 기본 하한율 계약 시험.

`_local_rule` 은 규칙이 대표값을 넘기지 않으면 `_LOCAL_LWLT_BY_SERVICE[service_type]` 을
씁니다. 이 기본값은 여러 규칙이 공유하므로 개별 규칙 정정은 규칙 자신의 대표값·구간
하한율로만 해야 합니다. 경북 폐기물(2026) 정정도 같은 원칙을 따랐는지 고정합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import LOCAL_RULES, EvaluationRule
from src.app.services.evaluation_rules_local import _LOCAL_LWLT_BY_SERVICE

GB_WASTE_ID = "SERVC_LOCAL_GB_20260108_ATTACH_03"
JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def test_service_default_lower_rates_unchanged() -> None:
    """서비스 유형 기본 하한율은 정정 대상이 아니다."""
    assert _LOCAL_LWLT_BY_SERVICE["WASTE"] == "84.245"
    assert _LOCAL_LWLT_BY_SERVICE["WASTE_HOUSEHOLD"] == "84.245"
    assert _LOCAL_LWLT_BY_SERVICE["GENERAL"] == "87.995"


def test_rules_without_own_rate_still_use_service_default() -> None:
    """대표값을 넘기지 않은 폐기물 규칙은 종전 기본값을 그대로 쓴다."""
    rule = _rule(JNGJ_WASTE_ID)
    assert rule.lwlt_rate == Decimal(_LOCAL_LWLT_BY_SERVICE["WASTE"])


def test_gb_waste_rule_owns_its_lower_rate() -> None:
    """경북 폐기물(2026)은 기본값이 아니라 원문 산식값을 직접 선언한다."""
    rule = _rule(GB_WASTE_ID)
    assert rule.lwlt_rate == Decimal("87.745")
    assert rule.lwlt_rate != Decimal(_LOCAL_LWLT_BY_SERVICE["WASTE"])
    assert [band.lwlt_rate for band in rule.price_bands] == [
        Decimal("87.745"),
        Decimal("86.745"),
    ]
