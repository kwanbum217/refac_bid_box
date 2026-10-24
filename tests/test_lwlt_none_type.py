"""대표 낙찰하한율 None 허용과 규칙 메타 직렬화 계약 시험.

대표 하한율이 None 인 기관 규칙을 _serialize_rule_meta 로 직렬화해도 예외 없이
lwlt_rate 가 null 이어야 합니다. 숫자 하한율 규칙의 문자열 표기는 종전과 같아야 하며,
기술용역 하한율 부재 차단과 사용자 입력 임시 규칙의 대표값도 None 입니다.

DB 와 HTTP 클라이언트는 쓰지 않습니다.
"""

from __future__ import annotations

from src.app.api.v1.evaluations import (
    _local_user_input_rule,
    _manual_user_input_rule,
    _serialize_rule_meta,
)
from src.app.schemas.evaluations import QualificationInput
from src.app.services.evaluation_rules import (
    BLOCK_CODE_TECH_SERVICE_MISSING_LWLT,
    INSTITUTION_RULES,
    POST_20260727_RULES,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.evaluation_scoring import format_decimal_plain

KRC_INSURANCE = "SERVC_INST_KRC_20251001_INSURANCE"

PRICE_INPUTS = {
    "max_price_score": 60.0,
    "multiplier": 2.0,
    "pass_threshold": 95.0,
    "base_rate": 0.88,
}


def _institution_rule(rule_id: str):
    return next(rule for rule in INSTITUTION_RULES if rule.rule_id == rule_id)


def test_serialize_rule_meta_with_none_lwlt_rate() -> None:
    """대표 하한율이 None 인 기관 규칙은 예외 없이 lwlt_rate null 로 직렬화합니다."""
    rule = _institution_rule(KRC_INSURANCE)
    assert rule.lwlt_rate is None

    meta = _serialize_rule_meta(rule)

    assert meta["rule_id"] == KRC_INSURANCE
    assert meta["lwlt_rate"] is None


def test_serialize_rule_meta_keeps_numeric_lwlt_rate_text() -> None:
    """숫자 하한율 규칙은 종전과 같은 평문 문자열을 냅니다."""
    rule = POST_20260727_RULES[0]
    assert rule.lwlt_rate is not None

    meta = _serialize_rule_meta(rule)

    assert meta["lwlt_rate"] == format_decimal_plain(rule.lwlt_rate)
    assert meta["lwlt_rate"] == "89.995"


def test_tech_service_missing_lwlt_keeps_rule_none_and_block() -> None:
    """기술용역 공고 하한율 부재는 대표·유효 하한율 None 으로 차단합니다."""
    assert SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.lwlt_rate is None

    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "기술용역",
            "sucsfbidMthdNm": "적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준",
        },
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_TECH_SERVICE_MISSING_LWLT
    assert result.rule is not None
    assert result.rule.lwlt_rate is None
    assert result.effective_lwlt_rate is None


def test_user_input_rules_have_none_lwlt_rate() -> None:
    """사용자 입력 임시 규칙 두 경로 모두 대표 하한율을 None 으로 둡니다."""
    qualification = QualificationInput(**PRICE_INPUTS)

    for builder in (_local_user_input_rule, _manual_user_input_rule):
        rule = builder(qualification)
        assert rule is not None
        assert rule.lwlt_rate is None
