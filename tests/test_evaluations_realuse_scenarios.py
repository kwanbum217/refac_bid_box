"""DB 실측 공고 문자열을 고정하는 일반용역 적격심사 회귀 테스트."""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_MANUAL_EVALUATION,
    BLOCK_CODE_NON_PRED_PRICE,
    BLOCK_CODE_NOT_SERVC,
    BLOCK_CODE_RULE_NOT_FOUND,
    POST_20260526_RULES,
    get_rule_by_id,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

# 각 행은 2026-09-10 DB 조회에서 반환된 공고번호, 전체 원문 문자열, 공고 하한율,
# 기대 별표, 기초금액이다. 레지스트리 patterns를 읽어 테스트 입력을 만들지 않는다.
REAL_ANNOUNCEMENT_CASES = [
    (
        "R26BK01719349",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        "89.995",
        "SERVC_QUAL_POST_20260526_ATTACH_01",
        100_004_080,
    ),
    (
        "R26BK01709274",
        "적격심사제-보험용역 적격심사 추정가격 5억원미만",
        "47.995",
        "SERVC_QUAL_POST_20260526_ATTACH_02",
        221_478_200,
    ),
    (
        "R26BK01721708",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "89.995",
        "SERVC_QUAL_POST_20260526_ATTACH_03",
        216_840_000,
    ),
    (
        "R26BK01719469",
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
        "89.995",
        "SERVC_QUAL_POST_20260526_ATTACH_04",
        162_096_000,
    ),
    (
        "R26BK01707765",
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
        "86.245",
        "SERVC_QUAL_POST_20260526_ATTACH_05",
        48_900_000,
    ),
    (
        "R26BK01719651",
        "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만",
        "86.245",
        "SERVC_QUAL_POST_20260526_ATTACH_06",
        190_080_000,
    ),
    (
        "R26BK01705388",
        "적격심사제-학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상",
        "82.495",
        "SERVC_QUAL_POST_20260526_ATTACH_07",
        358_008_000,
    ),
    (
        "R26BK01721029",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "86.245",
        "SERVC_QUAL_POST_20260526_ATTACH_08",
        56_100_000,
    ),
    (
        "R26BK01708399",
        "적격심사제-폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
        "82.495",
        "SERVC_QUAL_POST_20260526_ATTACH_09",
        516_446_280,
    ),
    (
        "R26BK01695450",
        "적격심사제-화물 육상운송용역 적격심사 추정가격 고시금액미만",
        "86.245",
        "SERVC_QUAL_POST_20260526_ATTACH_10",
        218_628_430,
    ),
    (
        "R26BK01707773",
        "적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
        "82.495",
        "SERVC_QUAL_POST_20260526_ATTACH_11",
        264_557_112,
    ),
    (
        "R26BK01722052",
        "적격심사제-추정가격 2억원 미만인 용역",
        "87.745",
        "SERVC_QUAL_POST_20260526_ATTACH_12",
        38_170_000,
    ),
    (
        "R26BK01722135",
        "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "86.745",
        "SERVC_QUAL_POST_20260526_ATTACH_13",
        242_900_000,
    ),
    (
        "R26BK01719314",
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "82.995",
        "SERVC_QUAL_POST_20260526_ATTACH_14",
        2_644_312_000,
    ),
]


@pytest.mark.parametrize(
    ("bid_ntce_no", "announcement_method", "announcement_rate", "expected_rule_id", "base_amount"),
    REAL_ANNOUNCEMENT_CASES,
    ids=[case[0] for case in REAL_ANNOUNCEMENT_CASES],
)
def test_real_announcement_string_resolves_to_expected_star(
    bid_ntce_no: str,
    announcement_method: str,
    announcement_rate: str,
    expected_rule_id: str,
    base_amount: int,
) -> None:
    """실제 공고 원문 전체 문자열이 해당 별표로 매칭된다."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=announcement_method,
        sucsfbid_lwlt_rate=announcement_rate,
    )

    assert bid_ntce_no.startswith("R26BK")
    assert base_amount > 0
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.effective_lwlt_rate == Decimal(announcement_rate)
    assert result.rate_source == "ANNOUNCEMENT"


# 레지스트리 기본값과 실제 공고값이 달랐던 DB 행이다. 이 테스트는 기본값을 복사해
# 넣어 매칭하는 동어반복이 아니라 공고값 우선 경고를 보호한다.
REAL_MISMATCH_CASES = [
    (
        "R26BK01656148",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        "87.995",
        "89.995",
    ),
    (
        "R26BK01721708",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "89.995",
        "87.995",
    ),
    (
        "R26BK01719469",
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
        "89.995",
        "87.995",
    ),
    (
        "R26BK01547916",
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
        "84.245",
        "86.245",
    ),
    (
        "R26BK01676174",
        "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만",
        "84.245",
        "86.245",
    ),
    (
        "R26BK01678121",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "87.745",
        "86.245",
    ),
    (
        "R26BK01595105",
        "적격심사제-폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
        "87.745",
        "82.495",
    ),
    (
        "R26BK01686463",
        "적격심사제-추정가격 2억원 미만인 용역",
        "86.245",
        "87.745",
    ),
    (
        "R26BK01674713",
        "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "86.245",
        "86.745",
    ),
]


@pytest.mark.parametrize(
    ("bid_ntce_no", "announcement_method", "announcement_rate", "registry_rate"),
    REAL_MISMATCH_CASES,
    ids=[case[0] for case in REAL_MISMATCH_CASES],
)
def test_real_announcement_rate_wins_over_registry_default(
    bid_ntce_no: str,
    announcement_method: str,
    announcement_rate: str,
    registry_rate: str,
) -> None:
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=announcement_method,
        sucsfbid_lwlt_rate=announcement_rate,
    )

    assert bid_ntce_no.startswith("R26BK")
    assert result.rule is not None
    assert result.rule.lwlt_rate == Decimal(registry_rate)
    assert result.effective_lwlt_rate == Decimal(announcement_rate)
    assert result.rate_source == "ANNOUNCEMENT"
    assert any("일치하지 않아" in warning for warning in result.warnings)


def test_real_star_cases_cover_all_registry_rule_ids() -> None:
    expected_ids = {case[3] for case in REAL_ANNOUNCEMENT_CASES}
    assert expected_ids == {rule.rule_id for rule in POST_20260526_RULES}


@pytest.mark.parametrize(
    ("category", "prearng_method", "announcement_method", "rate", "expected_code"),
    [
        (
            "Cnstwk",
            "복수예가",
            "소액수의견적-소액수의견적(2인 이상 견적 제출)-국민연금보험료 등 합산액 감액 적용",
            "89.745",
            BLOCK_CODE_NOT_SERVC,
        ),
        (
            "Servc",
            "비예가",
            "협상에의한계약-협상에 의한 낙찰자 결정(SW사업)",
            None,
            BLOCK_CODE_NON_PRED_PRICE,
        ),
        (
            "Servc",
            "복수예가",
            "적격심사제-관리규정외 수기심사(총점입력)",
            "87.745",
            BLOCK_CODE_MANUAL_EVALUATION,
        ),
        (
            "Servc",
            "복수예가",
            "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
            "85.495",
            BLOCK_CODE_RULE_NOT_FOUND,
        ),
    ],
)
def test_real_blocking_announcement_resolves_to_expected_code(
    category: str,
    prearng_method: str,
    announcement_method: str,
    rate: str | None,
    expected_code: str,
) -> None:
    result = resolve_evaluation_rule(
        category=category,
        prearng_prce_dcsn_mthd_nm=prearng_method,
        sucsfbid_mthd_nm=announcement_method,
        sucsfbid_lwlt_rate=rate,
    )

    assert result.is_blocked is True
    assert result.block_reason_code == expected_code
    assert result.rule is None


class TestMovedRuleResolutionEdgeCases:
    """기존 별표 회귀 테스트에서 이동한 결측·경계 입력."""

    def test_category_none_is_blocked(self) -> None:
        result = resolve_evaluation_rule(
            category=None,
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        )
        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_NOT_SERVC

    def test_prearng_method_none_with_real_announcement_passes(self) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm=None,
            sucsfbid_mthd_nm="적격심사제-추정가격 2억원 미만인 용역",
            sucsfbid_lwlt_rate="87.745",
        )
        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_12"

    def test_sucsfbid_method_none_blocks_rule_not_found(self) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm=None,
        )
        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND

    def test_sucsfbid_method_empty_string_blocks_rule_not_found(self) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="",
        )
        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND

    def test_resolve_from_raw_data_none(self) -> None:
        result = resolve_evaluation_rule_from_raw_data(category="Servc", raw_data=None)
        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


class TestMovedNormalizedPatternMatching:
    """공백·구분기호가 변형된 입력의 기존 회귀 테스트."""

    @pytest.mark.parametrize(
        ("announcement_method", "expected_rule_id", "rate"),
        [
            (
                "적격심사제-시설 분야 용역 적격 심사 추정 가격 5억원 미만",
                "SERVC_QUAL_POST_20260526_ATTACH_01",
                "89.995",
            ),
            (
                "적격심사제-폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
                "SERVC_QUAL_POST_20260526_ATTACH_09",
                "82.495",
            ),
            (
                "적격심사제-학술연구용역 적격심사 추정가격 고시금액미만",
                "SERVC_QUAL_POST_20260526_ATTACH_06",
                "86.245",
            ),
            (
                "적격심사제-소프트웨어용역(중소기업자간 경쟁제품_비대상) 추정가격 고시금액미만",
                "SERVC_QUAL_POST_20260526_ATTACH_05",
                "86.245",
            ),
            (
                "적격심사제-  추정가격  2억원  미만인  용역  ",
                "SERVC_QUAL_POST_20260526_ATTACH_12",
                "87.745",
            ),
            (
                "적격심사제-소프트웨어용역-중소기업자간 경쟁제품 대상-적격심사 추정가격 5억원 미만",
                "SERVC_QUAL_POST_20260526_ATTACH_04",
                "87.995",
            ),
        ],
    )
    def test_normalized_announcement_variant_matches(
        self,
        announcement_method: str,
        expected_rule_id: str,
        rate: str,
    ) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm=announcement_method,
            sucsfbid_lwlt_rate=rate,
        )
        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == expected_rule_id
        assert result.effective_lwlt_rate == Decimal(rate)


def test_real_registry_rate_is_used_when_announcement_rate_is_missing() -> None:
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm="적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        sucsfbid_lwlt_rate=None,
    )
    assert result.is_blocked is False
    assert result.effective_lwlt_rate == Decimal("89.995")
    assert result.rate_source == "RULE_DEFAULT"
    assert any("기본값" in warning for warning in result.warnings)


def test_real_raw_data_adapter_uses_full_announcement_method() -> None:
    result = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": "적격심사제-보험용역 적격심사 추정가격 5억원미만",
            "sucsfbidLwltRate": "47.995",
        },
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_02"
    assert result.effective_lwlt_rate == Decimal("47.995")


def test_real_registry_contains_fourteen_rules() -> None:
    assert len(POST_20260526_RULES) == 14
    assert get_rule_by_id("SERVC_QUAL_POST_20260526_ATTACH_14") is not None
