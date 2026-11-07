"""2026-11-07 기관 규칙 판본·구간 축·매칭 결정 회귀 시험.

정본:
 - docs/analysis/decision_backlog_20261107.md D07·D08·D09·D22·D29
 - docs/analysis/kdhc_krc_sources_20261107.md 3.1~3.3
 - docs/analysis/not_computable_9_trace_20261107.md 3.2
 - docs/analysis/regime_lag_65_check_20261107.md 3.1, 3.2, 4.3

(a) 한국지역난방공사 2026-08-18 이후 공고는 2026-08-18판 규칙, 그 이전 공고는 2026-01-01판
규칙을 쓰고 2026-04-13판은 2026-01-01판과 같은 규칙으로 계산되는지, (b) 한국농어촌공사
5억원 미만 밴드가 고시금액 경계로 갈려 k=4/2 로 계산되는지, (c) 한국지역난방공사
2023-07-19판 여객 규칙이 2026-01-01판 시행 전 공고에 적용되는지, (d) 지사·사업소 코드가
명시 목록으로 매칭되는지, (e) 목록 밖 코드는 매칭되지 않는지, (f) 공고문이 환경부고시를
인용한 건설폐기물처리용역이 고시 규칙으로 계산되는지, (g) 공고명에 건설폐기물이 없으면
공사 별표 4 를 그대로 쓰는지 단언합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_NOT_FOUND,
    INSTITUTION_RULES,
    PREDECESSOR_INSTITUTION_RULES,
    QUANT_BASIS_INSTITUTION,
    RULE_SCOPE_INSTITUTION,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

KDHC_CODE = "B550373"
KRC_CODE = "B552149"
KDHC_NEW = "SERVC_INST_KDHC_20260818_"
KDHC_OLD = "SERVC_INST_KDHC_20260101_"
KDHC_PREDECESSOR_PASSENGER = "SERVC_INST_KDHC_20230719_PASSENGER"

KDHC_WASTE_METHOD = "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액 이상 5억원 미만"
KDHC_FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
KDHC_PASSENGER_METHOD = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원 미만"
KRC_ACADEMIC_METHOD = "적격심사제-학술연구용역 적격심사 추정가격 5억원 미만"


def _raw(
    *,
    code: str,
    name: str,
    announced: str,
    method: str,
    price: int,
    announcement_lwlt: str | None = None,
    bid_name: str | None = None,
) -> dict[str, str]:
    raw = {
        "dminsttCd": code,
        "dminsttNm": name,
        "ntceInsttCd": code,
        "ntceInsttNm": name,
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "presmptPrce": str(price),
        "bidNtceNm": bid_name if bid_name is not None else name,
    }
    if announcement_lwlt is not None:
        raw["sucsfbidLwltRate"] = announcement_lwlt
    return raw


def _resolve(raw: dict[str, str], price: int):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        estimated_price=Decimal(str(price)),
    )


def _band(rule, price: int):
    params = resolve_score_params(rule, Decimal(str(price)), None, None)
    band = rule.price_bands[params.price_band_index]
    return params, band


def test_kdhc_20260818_version_boundary() -> None:
    """(a) 2026-08-18 이후는 새 판 규칙, 이전은 2026-01-01판 규칙을 쓴다."""
    after = _resolve(
        _raw(
            code=KDHC_CODE,
            name="한국지역난방공사",
            announced="2026-08-18",
            method=KDHC_WASTE_METHOD,
            price=300_000_000,
        ),
        300_000_000,
    )
    assert after.is_blocked is False
    assert after.rule is not None
    assert after.rule.rule_id == f"{KDHC_NEW}WASTE"
    assert after.effective_lwlt_rate == Decimal("82.495")

    before = _resolve(
        _raw(
            code=KDHC_CODE,
            name="한국지역난방공사",
            announced="2026-08-17",
            method=KDHC_WASTE_METHOD,
            price=300_000_000,
        ),
        300_000_000,
    )
    assert before.is_blocked is False
    assert before.rule is not None
    assert before.rule.rule_id == f"{KDHC_OLD}WASTE"
    assert before.effective_lwlt_rate == Decimal("80.495")

    # 2026-04-13판은 2026-01-01판과 값이 같아 별도 규칙 없이 2026-01-01판을 쓴다.
    april = _resolve(
        _raw(
            code=KDHC_CODE,
            name="한국지역난방공사",
            announced="2026-04-13",
            method=KDHC_WASTE_METHOD,
            price=300_000_000,
        ),
        300_000_000,
    )
    assert april.is_blocked is False
    assert april.rule is not None
    assert april.rule.rule_id == f"{KDHC_OLD}WASTE"

    for service_type in (
        "ACADEMIC",
        "FACILITY",
        "SW",
        "SW_TARGET",
        "WASTE",
        "PASSENGER",
        "FREIGHT",
        "INSURANCE",
        "REPAIR",
        "LEASE",
        "OTHER",
    ):
        rule = next(
            rule for rule in INSTITUTION_RULES if rule.rule_id == f"{KDHC_NEW}{service_type}"
        )
        assert rule.effective_date == "2026-08-18"
        assert rule.superseded_date is None
        # 2026-08-18판 별표 1~9 의 심사항목 배점한도는 원문상 2026-01-01판과 같아
        # 기관 정량 배점표를 그대로 연결했습니다(docs/analysis/kdhc_quant_20260818_20261107.md).
        assert rule.quant_basis == QUANT_BASIS_INSTITUTION

    old_waste = next(rule for rule in INSTITUTION_RULES if rule.rule_id == f"{KDHC_OLD}WASTE")
    assert old_waste.superseded_date == "2026-08-18"


def test_krc_notice_amount_axis_splits_under_500m() -> None:
    """(b) 5억원 미만이 고시금액 미만 k=4, 고시금액 이상 k=2 로 계산된다."""
    under_notice = _resolve(
        _raw(
            code=KRC_CODE,
            name="한국농어촌공사",
            announced="2026-10-01",
            method=KRC_ACADEMIC_METHOD,
            price=200_000_000,
        ),
        200_000_000,
    )
    assert under_notice.rule is not None
    params, band = _band(under_notice.rule, 200_000_000)
    assert params.max_price_score == Decimal("70")
    assert params.multiplier == Decimal("4")
    assert band.lwlt_rate == Decimal("86.245")

    above_notice = _resolve(
        _raw(
            code=KRC_CODE,
            name="한국농어촌공사",
            announced="2026-10-01",
            method=KRC_ACADEMIC_METHOD,
            price=300_000_000,
        ),
        300_000_000,
    )
    assert above_notice.rule is not None
    params, band = _band(above_notice.rule, 300_000_000)
    assert params.max_price_score == Decimal("70")
    assert params.multiplier == Decimal("2")
    assert band.lwlt_rate == Decimal("82.495")

    # 5억원 이상은 B 60·k 2 이다.
    above_500m = _resolve(
        _raw(
            code=KRC_CODE,
            name="한국농어촌공사",
            announced="2026-10-01",
            method=KRC_ACADEMIC_METHOD,
            price=600_000_000,
        ),
        600_000_000,
    )
    assert above_500m.rule is not None
    params, band = _band(above_500m.rule, 600_000_000)
    assert params.max_price_score == Decimal("60")
    assert params.multiplier == Decimal("2")
    assert band.lwlt_rate == Decimal("82.495")


def test_kdhc_20230719_passenger_rule_matches_pre_2026_announcement() -> None:
    """(c) 2023-07-19판 별표 5 여객 규칙이 2025-11-19 공고에 적용된다."""
    result = _resolve(
        _raw(
            code=KDHC_CODE,
            name="한국지역난방공사",
            announced="2025-11-19",
            method=KDHC_PASSENGER_METHOD,
            price=67_283_460,
            announcement_lwlt="87.995",
        ),
        67_283_460,
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_PREDECESSOR_PASSENGER
    assert result.rule.effective_date == "2023-07-19"
    assert result.rule.superseded_date == "2026-01-01"
    assert result.effective_lwlt_rate == Decimal("87.995")

    params, band = _band(result.rule, 67_283_460)
    assert params.max_price_score is None
    assert params.multiplier == Decimal("4")
    assert params.pass_threshold == Decimal("88")
    assert band.base_rate == Decimal("0.91")
    assert band.lwlt_rate == Decimal("87.995")

    rule = next(
        rule for rule in PREDECESSOR_INSTITUTION_RULES if rule.rule_id == KDHC_PREDECESSOR_PASSENGER
    )
    assert rule.patterns == ("여객육상운송용역", "여객육상운송")


def test_kdhc_branch_office_code_matches_institution_rule() -> None:
    """(d) 지사·사업소 수요기관 코드는 명시 목록으로 기관 규칙에 매칭된다."""
    facility = _resolve(
        _raw(
            code="D325105",
            name="한국지역난방공사 광주전남지사",
            announced="2026-07-29",
            method=KDHC_FACILITY_METHOD,
            price=90_630_000,
        ),
        90_630_000,
    )
    assert facility.is_blocked is False
    assert facility.rule is not None
    assert facility.rule.rule_id == f"{KDHC_OLD}FACILITY"
    assert facility.scope_stage == RULE_SCOPE_INSTITUTION
    assert facility.effective_lwlt_rate == Decimal("87.995")

    passenger = _resolve(
        _raw(
            code="D325102",
            name="한국지역난방공사 대구지사",
            announced="2026-08-13",
            method=KDHC_PASSENGER_METHOD,
            price=33_681_908,
        ),
        33_681_908,
    )
    assert passenger.is_blocked is False
    assert passenger.rule is not None
    assert passenger.rule.rule_id == f"{KDHC_OLD}PASSENGER"
    assert passenger.scope_stage == RULE_SCOPE_INSTITUTION

    after_version = _resolve(
        _raw(
            code="D325105",
            name="한국지역난방공사 광주전남지사",
            announced="2026-11-05",
            method=KDHC_PASSENGER_METHOD,
            price=108_727_320,
        ),
        108_727_320,
    )
    assert after_version.is_blocked is False
    assert after_version.rule is not None
    assert after_version.rule.rule_id == f"{KDHC_NEW}PASSENGER"


def test_kdhc_unlisted_institution_code_does_not_match() -> None:
    """(e) 목록 밖 코드는 이름이 지사 표기여도 기관 규칙으로 매칭되지 않는다."""
    result = _resolve(
        _raw(
            code="D325199",
            name="한국지역난방공사 가상지사",
            announced="2026-06-19",
            method=KDHC_WASTE_METHOD,
            price=300_000_000,
        ),
        300_000_000,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert result.rule is None
    assert result.scope_stage != RULE_SCOPE_INSTITUTION


def test_kdhc_construction_waste_uses_moe_notice_rule() -> None:
    """(f) 공고문이 환경부고시를 인용한 건설폐기물처리용역은 공사 별표 4 를 쓰지 않는다.

    R26BK01621293 첨부 '1. 입찰공고문(불연성).pdf' 는 "기후에너지환경부
    '건설폐기물처리용역 적격업체 평가기준'에 의하여 낙찰자를 결정"한다고 적고,
    하한율도 환경부고시 제4호 값 87.745% 를 인쇄합니다.
    """
    result = _resolve(
        _raw(
            code="D325152",
            name="한국지역난방공사 동탄지사",
            announced="2026-07-07",
            method="적격심사제-추정가격 2억원 미만인 용역",
            price=82_000_000,
            announcement_lwlt="87.745",
            bid_name="2026년 동탄지사 열수송관공사 불연성 건설폐기물처리용역 단가계약",
        ),
        82_000_000,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_MOE_CDW_ATTACH_04"
    assert result.scope_stage != RULE_SCOPE_INSTITUTION
    assert result.effective_lwlt_rate == Decimal("87.745")


def test_kdhc_waste_without_construction_word_keeps_institution_rule() -> None:
    """(g) 공고명에 건설폐기물이 없으면 같은 띠 표기라도 공사 별표 4 를 그대로 쓴다."""
    result = _resolve(
        _raw(
            code="D325152",
            name="한국지역난방공사 동탄지사",
            announced="2026-07-07",
            method="적격심사제-추정가격 2억원 미만인 용역",
            price=82_000_000,
            bid_name="2026년 동탄지사 생활폐기물처리용역 단가계약",
        ),
        82_000_000,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == f"{KDHC_OLD}WASTE"
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    assert result.effective_lwlt_rate == Decimal("84.245")
