"""첨부 판별기 1.2.0 회귀 시험.

정본: `.orca/capsules/task_130296b8bb9c/capsule.yaml`

문서 `docs/analysis/band_unspecified_subtable_review_20261106.md` 3.1·3.2절과
`docs/analysis/mois_other_band_rule_source_20261106.md` 1절·3.2절의 인용 문구로
짧은 텍스트 픽스처를 만듭니다. 후보 C1(R15) 확정, 대전 부정 lookbehind 유지,
완주 발행기관 없음 유지, 후보 C2(R6·R7 참고 문구 예외), 대구 학술 우선,
광주북구·광명 MOIS_TECH, 순천·원주 MOIS_OTHER 유지를 단언합니다.

해석기 시험은 `resolve_evaluation_rule` 에 `attachment_regime` 을 넘겨
MOIS_TECH 판별 행에만 `SERVC_LOCAL_MOIS_TECH_20250701_1E_2E` 가 적용되고,
판별 행이 없거나 다른 갈래면 종전 결과가 유지되는지 확인합니다. DB·.env 를 쓰지
않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.band_regime_classifier import (
    BAND_REGIME_CLASSIFIER_VERSION,
    MOIS_ACADEMIC,
    MOIS_OTHER,
    MOIS_TECH,
    PPS,
    UNSPECIFIED_SUBTABLE,
    classify_band_regime,
)
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    MOIS_ACADEMIC_ATTACHMENT_WARNING,
    MOIS_TECH_ATTACHMENT_WARNING,
    MOIS_TECH_BAND_RULES,
    RULE_SCOPE_ALL,
    RuleResolutionResult,
    get_mois_academic_attachment_rule,
    get_mois_tech_attachment_rule,
    resolve_evaluation_rule,
    select_mois_academic_band_rule,
)

METHOD_BAND = "적격심사제-추정가격 2억미만 1억이상"
METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"
BID_DATE = "2026-06-01"
SIDO_CHUNGNAM = ("44", "충청남도")
MOIS_TECH_RULE_ID = "SERVC_LOCAL_MOIS_TECH_20250701_1E_2E"
MOIS_ACADEMIC_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"

# 후보 C1: 학술…용역 적격심사 (세부)기준 + 발행기관, 기술용역 표지 없음.
C1_CASES: list[tuple[str, list[str]]] = [
    (
        "광양",
        [
            "행정안전부 예규 제325호 「지방자치단체 입찰시 낙찰자 결정기준」의 "
            "학술연구용역 적격심사 기준 추정가격이 2억 원 미만 1억 원 이상을 적용합니다."
        ],
    ),
    (
        "하동",
        ["「학술연구용역 적격심사 세부기준(행정안전부 예규)」에 따라 적격 심사합니다."],
    ),
    (
        "제주",
        [
            "학술용역 적격심사 세부기준(행정안전부 예규)에 의거 "
            "『추정가격 2억원 미만 1억원 이상 학술연구용역 적격심사 기준』을 적용합니다."
        ],
    ),
    (
        "순천의료원",
        [
            "[행정안전부 예규 제373호, 2026. 6. 29. 일부개정]」에 따른 "
            "학술연구용역 적격심사 세부기준을 적용하여 종합평점이 85점 이상인 자로 결정합니다."
        ],
    ),
]

# 문서 2.2·2.10절 인용. 발행기관이 없거나(완주) 부정 lookbehind(대전)로 학술 확정 불가.
C1_NEGATIVE_CASES: list[tuple[str, list[str], str]] = [
    (
        "완주",
        [
            "『학술연구용역 적격심사 세부기준』 [별표1] 추정가격 2억원 미만 1억원 이상 "
            "평가기준을 적용합니다."
        ],
        UNSPECIFIED_SUBTABLE,
    ),
    (
        "대전",
        [
            "행정안전부 예규「지방자치단체 입찰시 낙찰자 결정기준」의 "
            "‘기술․학술연구 용역 적격심사 세부기준’을 적용합니다."  # noqa: RUF001
        ],
        UNSPECIFIED_SUBTABLE,
    ),
]

# 후보 C2: 참고 문구가 같은 문장에 붙어도 조달청 [별표 1] 표지는 유지합니다.
C2_PPS_TEXT = (
    "조달청 일반용역 적격심사 세부기준 [조달청공고 최신호, [별표1] 학술연구용역 "
    "적격심사 기준을 적용합니다. 참고 : 계약 관련 서류"
)

# 대구: 공고문 [별표4] 학술연구 표지가 첨부 예규 전문의 87.745 보다 우선합니다.
DAEGU_TEXTS = [
    "낙찰자결정은 행정안전부 지방자치단체 입찰시 낙찰자 결정기준 제2장의2 "
    "기술·학술연구 용역 적격심사 세부기준 [별표4] 학술연구용역 평가기준을 적용하며, "
    "예정가격이하로서 낙찰하한율 (80.495%)이상 최저가 입찰자 순으로 적격심사하여 "
    "종합평점이 85점 이상인 자를 최종낙찰자로 선정합니다.",
    # 원문 인용의 곱셈 기호를 그대로 둡니다.
    "가) 입찰가격 평점산식 (87.745%) ① 평점 = 80 - 20 × ( 88/100 - 입찰가격/예정가격 ) × 100",  # noqa: RUF001
]

# 광주북구: 공고문이 [별표 2] 4. P.Q 비대상 기술용역과 낙찰하한율 87.745%를 함께 적습니다.
GWANGJU_BUKGU_TEXTS = [
    "「지방자치단체 입찰 시 낙찰자 결정기준」 제2장의2 기술·학술연구 용역 적격심사 "
    "세부기준 적격심사 기준 적용 규정 사업수행능력평가(P.Q)를 하지 않는 기술용역 "
    "4. 추정가격 2억원 미만 1억원 이상인 평가기준",
    "다. 최종낙찰자는 예정가격 대비 낙찰하한율(87.745%)이상 최저가로 입찰한 사람 "
    "순으로 적격심사를 실시하여 종합평점 95점 이상인 자로 결정합니다.",
]

# 광명: 공고문이 제2장의2 기술용역 적격심사와 낙찰하한율 87.745%를 함께 적습니다.
GWANGMYEONG_TEXTS = [
    "「지방자치단체 입찰시 낙찰자 결정기준(행정안전부 예규 제373호)」 제2장의2 "
    "기술 용역적격심사세부기준에 의거 예정가격 이하로서 낙찰하한율(87.745%) 이상 "
    "최저가 입찰자 순으로 적격심사를 실시하며, 종합평점이 95점 이상인 자를 "
    "낙찰자로 결정합니다."
]

# 순천: 일반용역 평가기준만 지목하고 기술용역 표지가 없습니다.
SUNCHEON_TEXTS = [
    "추정가격 2억원 미만인 일반용역 평가기준”에 따라 예정가격 이하로 "
    "낙찰하한율(87.745%) 이상 최저가 가격으로 입찰한 자의 순으로 적격심사하여 "
    "종합평점이 95점 이상인 자를 낙찰자로 결정합니다."
]

# 원주: 공고문은 85점만 적고, 첨부 예규 전문에 87.745와 기술용역 표지가 함께 있습니다.
WONJU_TEXTS = [
    "행정자치부 예규 제332호(2025.7) 지방자치단체 입찰시 낙찰자선정 세부기준에 "
    "의하며, 예정가격 이하 최저가(부가세포함) 입찰자순으로 적격심사를 실시하여, "
    "종합평점이 85점 이상인 자를 낙찰자로 결정합니다.",
    "제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 2] 4. 추정가격 2억원 미만 "
    "1억원 이상인 평가기준 라. 학술연구용역 : <별표4> 가) 입찰가격 평점산식 "
    "(87.745%) 가. 사업수행능력평가(P.Q)를 하지 않는 기술용역",
]


def test_classifier_version_is_1_2_0() -> None:
    assert BAND_REGIME_CLASSIFIER_VERSION == "1.2.0"


@pytest.mark.parametrize(("case_id", "texts"), C1_CASES, ids=[case[0] for case in C1_CASES])
def test_c1_confirms_mois_academic(case_id: str, texts: list[str]) -> None:
    result = classify_band_regime(texts)

    assert result.regime == MOIS_ACADEMIC, f"{case_id}: {result}"
    assert "R15" in result.matched_rules, case_id


@pytest.mark.parametrize(
    ("case_id", "texts", "expected"),
    C1_NEGATIVE_CASES,
    ids=[case[0] for case in C1_NEGATIVE_CASES],
)
def test_c1_negative_cases_stay_unspecified_subtable(
    case_id: str, texts: list[str], expected: str
) -> None:
    result = classify_band_regime(texts)

    assert result.regime == expected, f"{case_id}: {result}"
    assert "R15" not in result.matched_rules, case_id


def test_c2_keeps_pps_marker_in_reference_sentence() -> None:
    result = classify_band_regime([C2_PPS_TEXT])

    assert result.regime == PPS
    assert set(result.matched_rules) >= {"R6", "R7"}


def test_daegu_academic_notice_marker_beats_regulation_87745() -> None:
    result = classify_band_regime(DAEGU_TEXTS)

    assert result.regime == MOIS_ACADEMIC
    assert "R14" in result.matched_rules


def test_gwangju_bukgu_is_mois_tech() -> None:
    result = classify_band_regime(GWANGJU_BUKGU_TEXTS)

    assert result.regime == MOIS_TECH
    assert result.evidence is not None
    assert len(result.evidence) <= 80


def test_gwangmyeong_is_mois_tech() -> None:
    result = classify_band_regime(GWANGMYEONG_TEXTS)

    assert result.regime == MOIS_TECH


def test_suncheon_general_service_stays_mois_other() -> None:
    result = classify_band_regime(SUNCHEON_TEXTS)

    assert result.regime == MOIS_OTHER


def test_wonju_regulation_attachment_stays_mois_other() -> None:
    result = classify_band_regime(WONJU_TEXTS)

    assert result.regime == MOIS_OTHER


# --------------------------------------------------------------------------- #
# 해석기: MOIS_TECH 규칙 적용 범위
# --------------------------------------------------------------------------- #


def _resolve(
    *,
    attachment_regime: str | None,
    method: str = METHOD_BAND,
    bid_ntce_dt: str | None = BID_DATE,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime="LOCAL",
        region_code=SIDO_CHUNGNAM[0],
        region_name=SIDO_CHUNGNAM[1],
        bid_ntce_dt=bid_ntce_dt,
        attachment_regime=attachment_regime,
    )


def test_mois_tech_rule_values_match_source() -> None:
    rule = get_mois_tech_attachment_rule("1E_2E")

    assert rule is not None
    assert rule.rule_id == MOIS_TECH_RULE_ID
    assert rule.max_price_score == Decimal("80")
    assert rule.multiplier == Decimal("20")
    assert rule.base_rate == Decimal("0.88")
    assert rule.pass_threshold == Decimal("95")
    assert rule.lwlt_rate == Decimal("87.745")
    assert rule.effective_date == "2025-07-01"
    assert "제2장의2" in rule.score_table_source
    assert "별표 2" in rule.score_table_source
    assert get_mois_tech_attachment_rule("UNDER_1E") is None


def test_academic_rule_values_are_unchanged() -> None:
    rule = get_mois_academic_attachment_rule("1E_2E")

    assert rule is not None
    assert rule.rule_id == MOIS_ACADEMIC_RULE_ID
    assert rule.max_price_score == Decimal("60")
    assert rule.multiplier == Decimal("2")
    assert rule.base_rate == Decimal("0.88")
    assert rule.pass_threshold == Decimal("85")
    assert rule.lwlt_rate == Decimal("80.495")


def test_mois_tech_rule_is_not_selected_by_method_name() -> None:
    assert select_mois_academic_band_rule(METHOD_BAND) is None
    assert [rule.rule_id for rule in MOIS_TECH_BAND_RULES] == [MOIS_TECH_RULE_ID]


def test_mois_tech_attachment_unblocks_with_tech_rule() -> None:
    baseline = _resolve(attachment_regime=None)
    result = _resolve(attachment_regime="MOIS_TECH")

    assert baseline.is_blocked is True
    assert baseline.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_RULE_ID
    assert result.effective_lwlt_rate == Decimal("87.745")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_TECH_ATTACHMENT_WARNING in result.warnings
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


@pytest.mark.parametrize("attachment_regime", ["MOIS_OTHER", "PPS", None, ""])
def test_other_attachment_regimes_do_not_use_tech_rule(
    attachment_regime: str | None,
) -> None:
    result = _resolve(attachment_regime=attachment_regime)

    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert MOIS_TECH_ATTACHMENT_WARNING not in result.warnings


def test_mois_academic_attachment_still_uses_academic_rule() -> None:
    result = _resolve(attachment_regime="MOIS_ACADEMIC")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_RULE_ID
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert MOIS_TECH_ATTACHMENT_WARNING not in result.warnings


def test_mois_tech_does_not_apply_to_other_band() -> None:
    baseline = _resolve(attachment_regime=None, method=METHOD_UNDER_1E)
    result = _resolve(attachment_regime="MOIS_TECH", method=METHOD_UNDER_1E)

    assert result == baseline
    assert result.rule is not None
    assert result.rule.rule_id != MOIS_TECH_RULE_ID


def test_mois_tech_does_not_apply_before_effective_date() -> None:
    baseline = _resolve(attachment_regime=None, bid_ntce_dt="2025-06-30")
    result = _resolve(attachment_regime="MOIS_TECH", bid_ntce_dt="2025-06-30")

    assert result == baseline
    assert result.is_blocked is True
    assert MOIS_TECH_ATTACHMENT_WARNING not in result.warnings
