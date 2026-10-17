"""수요기관 기관 규칙(INSTITUTION_RULES) 시험.

정본:
 - data/reference/institution_rules_20261013.yaml (R1, status=confirmed 기관 12곳)
 - src/app/services/evaluation_rules.py 의 INSTITUTION_RULES·_select_institution_rule
 - docs/analysis/institution_rule_inventory_20261013.md 5~7절, docs/analysis/institution_rules_apply_20261013.md

(가) 12개 기관 구간별 값(B·k·기준비율·통과점수·하한율·경계)이 YAML 과 같은지 대조하고,
(나) 수요기관 이름·코드·name_aliases 로 기관 규칙이 선택되는지, (다) 공고기관이 조달청
계열이면 같은 수요기관이라도 조달청 규칙이 선택되는지, (라) 지방계약(LOCAL)이면 기관 규칙이
배제되는지, (마) partial·unresolved 기관은 조달청 규칙 그대로인지, (사) 원문 적용 범위가
하위 조직을 명시한 3곳만 하위 조직 표기에 기관 규칙이 적용되는지, (바) 평가 API 끝단에서
기관 공고의 최저투찰금액이 기관 규칙 하한율로 계산되는지를 고정합니다.

평가 API 끝단은 mock 없이 TestClient 로 호출하며, 예측 모델만 이 워크트리에 모델 파일이
없어 시험 대역으로 대체합니다. 규칙 판별·구간 하한율·최저 투찰금액 경로는 실제 코드입니다.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services import evaluation_rules as rules_module
from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    INSTITUTION_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule_from_raw_data,
)

YAML_PATH = Path("data/reference/institution_rules_20261013.yaml")
ANALYZE_URL = "/api/v1/evaluations/analyze"

# 2026년 고시금액(용역). 명세의 "고시금액" 표기를 옮긴 값입니다.
NOTICE_AMOUNT = Decimal("230000000")
# DB g2b_demand_institutions 로 확인한 수요기관 코드(한국수력원자력은 본청 코드 부재).
EXPECTED_CODES: dict[str, str | None] = {
    "국토교통부": "1613000",
    "국가유산청": "1833100",
    "환경부": "1482000",
    "한국농어촌공사": "B552149",
    "한국가스공사": "B551210",
    "한국수력원자력": None,
    "한국지역난방공사": "B550373",
    "한국석유공사": "B410005",
    "인천국제공항공사": "B551177",
    "인천공항시설관리": "Z043894",
    "해양환경공단": "B553931",
    "한국공항공사": "B551178",
}
# 원문(한국수력원자력 별표 9·10)이 구간 값이 같아 한 규칙으로 합친 표기입니다.
MERGED_LABEL_PREFIX = "별표 9·10 "

IIAC_OTHER_METHOD = "적격심사제-기타용역 추정가격 고시금액 이상"
IIAC_OTHER_ID = "SERVC_INST_IIAC_20250101_OTHER"
KDHC_FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 이상"
KDHC_FACILITY_ID = "SERVC_INST_KDHC_20260101_FACILITY"
KDHC_FACILITY_LWLT = Decimal("87.995")

# 원문 적용 범위 조항이 적용 주체에 하위 조직을 명시한 3곳과 그 규칙·시험 표기입니다.
SUBUNIT_INSTITUTIONS = ("국토교통부", "환경부", "한국석유공사")
MOLIT_SUPERVISION_ID = "SERVC_INST_MOLIT_20180104_SUPERVISION"
ME_TECH_ID = "SERVC_INST_ME_20251111_TECH"
KNOC_OTHER_ID = "SERVC_INST_KNOC_20190930_OTHER"
MOLIT_SUBUNIT_NAME = "국토교통부 대전지방국토관리청 충주국토관리사무소"
MOLIT_SUPERVISION_METHOD = "적격심사제-감리용역 적격심사 추정가격 5억원 미만"
ME_TECH_METHOD = "적격심사제-기술용역 적격심사 추정가격 5억원 미만"
KNOC_OTHER_METHOD = "적격심사제-기타용역 추정가격 2억원 미만"
# 한국공항공사 별표 3의 2 소프트웨어용역(중소기업자간 경쟁제품 대상) 표기와 규칙 ID 입니다.
KAC_SOFTWARE_SME_METHOD = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만"
)
KAC_SOFTWARE_SME_ID = "SERVC_INST_KAC_20260814_SOFTWARE_SME"


def _yaml_institutions() -> list[dict]:
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return list(data["institutions"])


def _confirmed_institutions() -> list[dict]:
    return [
        institution for institution in _yaml_institutions() if institution["status"] == "confirmed"
    ]


def _expected_bound(band: dict) -> Decimal | None:
    """YAML band 의 상한. 원문이 "고시금액 미만"만 인쇄한 행은 고시금액을 상한으로 봅니다."""
    if band["upper"] == "고시금액":
        return NOTICE_AMOUNT
    if band["upper"] is not None:
        return Decimal(str(band["upper"]))
    if "미만" in band["band"] and band["lower"] == "고시금액":
        return NOTICE_AMOUNT
    return None


def _expected_values(band: dict) -> tuple:
    b = band["B"]
    return (
        _expected_bound(band),
        None if isinstance(b, list) else Decimal(str(b)),
        Decimal(str(band["k"])),
        Decimal(str(band["base_ratio"])) / Decimal("100"),
        Decimal(str(band["pass_score"])),
        Decimal(str(band["lwlt_rate"])),
    )


def _code_values(rule) -> list[tuple]:
    return [
        (
            band.upper_bound,
            band.max_price_score,
            band.multiplier,
            band.base_rate,
            threshold.pass_threshold,
            band.lwlt_rate,
        )
        for band, threshold in zip(rule.price_bands or (), rule.threshold_bands or (), strict=True)
    ]


def _rules_for(institution_name: str) -> list:
    return [rule for rule in INSTITUTION_RULES if rule.institution_name == institution_name]


def _resolve(raw_data: dict, *, estimated_price=None, **kwargs):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        estimated_price=estimated_price,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# (가) R1 YAML 값 대조
# --------------------------------------------------------------------------- #


def test_confirmed_institution_band_values_match_yaml() -> None:
    """확인 기관 12곳의 구간 값과 경계가 R1 YAML 과 같고 빠짐·추가가 없다."""
    confirmed = _confirmed_institutions()
    assert len(confirmed) == 12

    expected_total = 0
    code_total = 0
    for institution in confirmed:
        name = institution["institution_name"]
        rules = _rules_for(name)
        assert rules, name

        expected: list[tuple] = []
        for band in institution["bands"]:
            values = _expected_values(band)
            if name == "한국수력원자력" and "국외운송주선" in band["band"] and values in expected:
                # 별표 9·10 은 값이 같아 한 규칙으로 합쳤습니다(각 값은 한 번만 셉니다).
                continue
            expected.append(values)

        code = [values for rule in rules for values in _code_values(rule)]
        assert Counter(expected) == Counter(code), name
        expected_total += len(expected)
        code_total += len(code)

    assert expected_total == code_total
    assert code_total == 159


def test_institution_band_labels_and_sources_trace_yaml() -> None:
    """코드 구간 라벨이 YAML band 이름과 같고 구간 근거가 YAML source 로 시작한다."""
    for institution in _confirmed_institutions():
        name = institution["institution_name"]
        yaml_bands = {band["band"]: band for band in institution["bands"]}
        for rule in _rules_for(name):
            for band in rule.price_bands or ():
                if band.label.startswith(MERGED_LABEL_PREFIX):
                    assert band.label in (
                        f"{MERGED_LABEL_PREFIX}국외운송주선용역 · 10억원 미만",
                        f"{MERGED_LABEL_PREFIX}국외운송주선용역 · 30억원 미만 10억원 이상",
                        f"{MERGED_LABEL_PREFIX}국외운송주선용역 · 30억원 이상",
                    )
                    source_band = next(
                        yaml_band
                        for label, yaml_band in yaml_bands.items()
                        if "국외운송주선" in label and band.label.split(" · ")[-1] in label
                    )
                    assert band.source.startswith(source_band["source"])
                    continue
                yaml_band = yaml_bands.get(band.label)
                assert yaml_band is not None, (name, band.label)
                assert band.source.startswith(yaml_band["source"]), (name, band.label)


def test_gas_company_band_score_limit_is_not_guessed() -> None:
    """B 를 용역 유형별 여러 값으로 인쇄한 한국가스공사 구간은 B 를 확정하지 않는다."""
    general = _rules_for("한국가스공사")
    general_rules = [rule for rule in general if rule.service_type == "GENERAL"]
    assert len(general_rules) == 1
    rule = general_rules[0]
    yaml_bands = {
        band["band"]: band
        for institution in _confirmed_institutions()
        if institution["institution_name"] == "한국가스공사"
        for band in institution["bands"]
    }
    assert len(rule.price_bands or ()) == 4
    for band in rule.price_bands or ():
        assert band.max_price_score is None
        assert "B 30/50/70" in (band.source or "")
        assert isinstance(yaml_bands[band.label]["B"], list)
    # 시설분야용역은 B 가 단일값이라 확정한다.
    facility = [rule for rule in general if rule.service_type == "FACILITY"]
    assert len(facility) == 1
    assert facility[0].price_bands[0].max_price_score == Decimal("50")


def test_institution_effective_dates_codes_and_aliases_match_yaml() -> None:
    """규칙 시행일·수요기관 코드·name_aliases 가 명세와 결정값에 맞는다."""
    for institution in _confirmed_institutions():
        name = institution["institution_name"]
        rules = _rules_for(name)
        assert rules
        aliases = set(institution.get("name_aliases") or ())
        assert name in aliases
        for rule in rules:
            assert rule.effective_date == institution["effective_date"]
            assert rule.institution_code == EXPECTED_CODES[name]
            assert rule.institution_scope == RULE_SCOPE_INSTITUTION
            assert set(rule.institution_aliases) <= aliases - {name}
            assert rule.source
            assert rule.score_table_source
            for band in rule.price_bands or ():
                assert band.lwlt_rate is not None


def test_partial_and_unresolved_institutions_are_not_registered() -> None:
    """partial·unresolved 기관은 규칙으로 넣지 않아 종전 조달청 경로를 그대로 쓴다."""
    excluded = {
        institution["institution_name"]
        for institution in _yaml_institutions()
        if institution["status"] != "confirmed"
    }
    assert excluded == {
        "방위사업청",
        "한국토지주택공사",
        "한국철도공사",
        "한국도로공사",
        "한국전력기술",
        "한국수자원공사",
        "한전 전력연구원",
        "한전KPS",
    }
    assert {rule.institution_name for rule in INSTITUTION_RULES}.isdisjoint(excluded)


# --------------------------------------------------------------------------- #
# (나) 수요기관 이름·코드·별칭 매칭
# --------------------------------------------------------------------------- #


def test_demand_agency_name_selects_institution_rule() -> None:
    result = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttNm": "인천국제공항공사",
        },
        estimated_price="5533515296",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == IIAC_OTHER_ID
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    # 5,553,515,296원은 고시금액 이상 구간이라 별표 9 인쇄 하한율 80.495% 를 쓴다.
    assert result.effective_lwlt_rate == Decimal("80.495")


def test_demand_agency_code_selects_institution_rule() -> None:
    """이름 없이 코드만 있어도 기관 규칙이 선택된다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttCd": "B551177",
        },
        estimated_price="300000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == IIAC_OTHER_ID
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    # 3억원은 고시금액 이상 구간이다.
    assert result.effective_lwlt_rate == Decimal("80.495")


def test_demand_agency_code_and_name_both_present_use_code_only() -> None:
    """규칙과 공고 양쪽에 코드가 있으면 코드 일치로만 판정한다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttCd": "B999999",
            "dminsttNm": "인천국제공항공사",
        },
    )
    # 코드가 다른 기관이라 기관 규칙을 쓰지 않고 종전 조달청 경로로 간다(별표 9 기타용역 없음).
    assert result.scope_stage is None
    assert result.rule is None
    assert result.block_reason_code == "RULE_NOT_FOUND"


def test_demand_agency_alias_selects_institution_rule() -> None:
    """name_aliases(문화재청)로도 기관 규칙이 선택된다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-매장유산 조사용역",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-01-01",
            "dminsttNm": "문화재청",
        },
        estimated_price="200000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_INST_KHS_20240517_BURIAL"
    assert result.effective_lwlt_rate == Decimal("86.745")


def test_region_and_local_organizations_are_not_matched() -> None:
    """지역본부·지사 등 하위 조직 이름은 접두 일치를 쓰지 않아 기관 규칙 대상이 아니다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사 강남지사",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id != KDHC_FACILITY_ID
    assert result.scope_stage != RULE_SCOPE_INSTITUTION


def test_institution_rule_selection_is_by_longest_service_token() -> None:
    """한국가스공사 공고에서 시설분야용역은 용역보다 긴 표기라 시설분야 규칙이 이긴다."""
    facility = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-08-01",
            "dminsttNm": "한국가스공사",
        },
        estimated_price="600000000",
    )
    assert facility.rule is not None
    assert facility.rule.rule_id == "SERVC_INST_KOGAS_20260709_FACILITY"
    general = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-08-01",
            "dminsttNm": "한국가스공사",
        },
        estimated_price="200000000",
    )
    assert general.rule is not None
    assert general.rule.rule_id == "SERVC_INST_KOGAS_20260709_GENERAL"


def test_lease_rule_splits_k_by_notice_amount() -> None:
    """별표 8 임대차용역은 원문이 고시금액 미만 k=4·이상 k=2 로 인쇄해 고시금액 경계로 나눈다."""
    over = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-임대차 적격심사 추정가격 고시금액 이상",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttNm": "인천국제공항공사",
        },
        estimated_price="300000000",
    )
    assert over.is_blocked is False
    assert over.rule is not None
    assert over.rule.rule_id == "SERVC_INST_IIAC_20250101_LEASE"
    assert over.scope_stage == RULE_SCOPE_INSTITUTION
    # 3억원은 고시금액(2.3억) 이상 구간이라 k=2·인쇄 하한율 80.495% 를 쓴다.
    assert over.effective_lwlt_rate == Decimal("80.495")
    under = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-임대차 적격심사 추정가격 고시금액 미만",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttNm": "인천국제공항공사",
        },
        estimated_price="200000000",
    )
    assert under.is_blocked is False
    assert under.rule is not None
    assert under.rule.rule_id == "SERVC_INST_IIAC_20250101_LEASE"
    # 2억원은 고시금액 미만 구간이라 k=4·인쇄 하한율 84.245% 를 쓴다.
    assert under.effective_lwlt_rate == Decimal("84.245")


def _kac_raw_data(method: str, **extra: str) -> dict:
    return {
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "bidNtceDt": "2026-09-01",
        "dminsttNm": "한국공항공사",
        **extra,
    }


def test_kac_rules_are_selected_by_service_token() -> None:
    """한국공항공사 일반용역 별표는 유형 표기로 갈리고 구간 하한율이 인쇄값과 맞는다."""
    cases = (
        (
            "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만",
            "200000000",
            "ACADEMIC",
            "86.245",
        ),
        (
            "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만",
            "300000000",
            "ACADEMIC",
            "82.495",
        ),
        ("적격심사제-시설분야용역 적격심사 추정가격 5억원 미만", "300000000", "FACILITY", "89.995"),
        (
            "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
            "600000000",
            "WASTE",
            "82.495",
        ),
        ("적격심사제-보험용역 적격심사 추정가격 5억원미만", "600000000", "INSURANCE", "47.995"),
        ("적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만", "300000000", "REPAIR", "82.495"),
    )
    for method, price, suffix, lwlt in cases:
        result = _resolve(_kac_raw_data(method, dminsttCd="B551178"), estimated_price=price)
        assert result.is_blocked is False, method
        assert result.rule is not None, method
        assert result.rule.rule_id == f"SERVC_INST_KAC_20260814_{suffix}", method
        assert result.scope_stage == RULE_SCOPE_INSTITUTION, method
        assert result.effective_lwlt_rate == Decimal(lwlt), method


def test_kac_insurance_token_matches_announcement_name() -> None:
    """낙찰방법명이 공고서참조(코드 낙030001)여도 공고명의 보험 표기로 보험용역 규칙을 고른다."""
    result = _resolve(
        _kac_raw_data(
            "공고서참조",
            sucsfbidMthdCd="낙030001",
            bidNtceNm="2026년도 전국공항 재산종합보험",
            dminsttCd="B551178",
        ),
        estimated_price="300000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_INST_KAC_20260814_INSURANCE"
    assert result.effective_lwlt_rate == Decimal("47.995")


def test_kac_waste_token_does_not_cover_construction_waste() -> None:
    """건설폐기물처리용역은 제5조 제1항 제4-1호의 환경부 고시라 별표 4 기관 규칙을 고르지 않는다."""
    result = _resolve(
        _kac_raw_data(
            "공고서참조",
            sucsfbidMthdCd="낙030001",
            bidNtceNm="김포공항 건설폐기물 처리용역",
            dminsttCd="B551178",
        ),
        estimated_price="300000000",
    )
    assert result.scope_stage != RULE_SCOPE_INSTITUTION


def test_kac_registers_general_service_tables_and_software_sme_rule() -> None:
    """한국공항공사는 통과점수 85점 별표와 대상 표기로 확정된 별표 3의 2 를 등록한다."""
    rules = _rules_for("한국공항공사")
    assert {rule.service_type for rule in rules} == {
        "ACADEMIC",
        "FACILITY",
        "WASTE",
        "INSURANCE",
        "REPAIR_INSPECTION",
        "SOFTWARE",
    }
    assert {rule.effective_date for rule in rules} == {"2026-08-14"}
    assert all(rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED for rule in rules)
    for rule in rules:
        expected = Decimal("88") if rule.service_type == "SOFTWARE" else Decimal("85")
        for threshold in rule.threshold_bands or ():
            assert threshold.pass_threshold == expected, rule.rule_id


def test_kac_software_sme_rule_bands_match_spec() -> None:
    """별표 3의 2 는 B 70·60, k 4, 기준비율 93, 통과 88, 하한율 89.995 두 구간이다."""
    rules = [rule for rule in _rules_for("한국공항공사") if rule.service_type == "SOFTWARE"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_id == KAC_SOFTWARE_SME_ID
    # 대상 표기를 담은 토큰만 쓴다. "소프트웨어용역" 단독은 별표 3(비대상)과 구분되지 않는다.
    assert rule.patterns == ("소프트웨어용역중소기업자간경쟁제품대상",)
    assert [(band.upper_bound, band.max_price_score) for band in rule.price_bands] == [
        (Decimal("500000000"), Decimal("70")),
        (None, Decimal("60")),
    ]
    for band in rule.price_bands:
        assert band.multiplier == Decimal("4")
        assert band.base_rate == Decimal("0.93")
        assert band.lwlt_rate == Decimal("89.995")
    for threshold in rule.threshold_bands:
        assert threshold.pass_threshold == Decimal("88")
    # 하한율: 93 - (100-88)/4 = 90 에서 소수 둘째 자리까지 버린 뒤 0.005 를 뺀 값이다.
    assert Decimal("93") - (Decimal("100") - Decimal("88")) / Decimal("4") - Decimal(
        "0.005"
    ) == Decimal("89.995")


def test_kac_software_sme_announcement_selects_rule_both_bands() -> None:
    """대상 표기 공고는 추정가격 5억원 경계 양쪽 모두 별표 3의 2 하한율 89.995% 로 간다."""
    for price in ("400000000", "600000000"):
        result = _resolve(
            _kac_raw_data(KAC_SOFTWARE_SME_METHOD, dminsttCd="B551178"),
            estimated_price=price,
        )
        assert result.is_blocked is False, price
        assert result.rule is not None, price
        assert result.rule.rule_id == KAC_SOFTWARE_SME_ID, price
        assert result.scope_stage == RULE_SCOPE_INSTITUTION, price
        assert result.effective_lwlt_rate == Decimal("89.995"), price


def test_kac_software_token_without_sme_marker_does_not_select_rule() -> None:
    """대상 표기가 없는 소프트웨어용역 공고는 별표 3의 2 규칙으로 가지 않는다(별표 3 비대상)."""
    result = _resolve(
        _kac_raw_data(
            "적격심사제-소프트웨어용역 적격심사 추정가격 5억원 미만",
            dminsttCd="B551178",
        ),
        estimated_price="400000000",
    )
    assert result.scope_stage != RULE_SCOPE_INSTITUTION
    assert result.rule is None or result.rule.rule_id != KAC_SOFTWARE_SME_ID


def test_kac_subunit_alias_matches_only_without_code() -> None:
    """한국공항공사 하위 조직 표기는 코드가 없을 때만 정확 일치 별칭으로 매칭된다."""
    method = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
    without_code = _resolve(
        _kac_raw_data(method, dminsttNm="한국공항공사 김포공항"),
        estimated_price="300000000",
    )
    assert without_code.rule is not None
    assert without_code.rule.rule_id == "SERVC_INST_KAC_20260814_FACILITY"
    with_code = _resolve(
        _kac_raw_data(method, dminsttCd="Z013741", dminsttNm="한국공항공사 김포공항"),
        estimated_price="300000000",
    )
    assert with_code.scope_stage != RULE_SCOPE_INSTITUTION


def test_khnp_head_office_alias_matches_but_subsidiary_does_not() -> None:
    """한수원 본사 표기(별칭)는 매칭되고 지역본부 등 하위 조직 표기는 매칭되지 않는다."""
    branch = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-청소용역",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-07-01",
            "dminsttNm": "한국수력원자력(주)",
        },
    )
    assert branch.rule is not None
    assert branch.rule.rule_id == "SERVC_INST_KHNP_20260619_CLEANING"
    assert branch.scope_stage == RULE_SCOPE_INSTITUTION
    corp = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-청소용역",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-07-01",
            "dminsttNm": "한국수력원자력주식회사",
        },
    )
    assert corp.rule is not None
    assert corp.rule.rule_id == "SERVC_INST_KHNP_20260619_CLEANING"
    subsidiary = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-청소용역",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-07-01",
            "dminsttNm": "한국수력원자력(주) 한울원자력본부",
        },
    )
    assert subsidiary.scope_stage != RULE_SCOPE_INSTITUTION


def test_institution_rule_effective_date_is_checked() -> None:
    """기관 규칙 시행일보다 앞선 공고는 RULE_REGIME_MISMATCH 로 차단한다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2024-12-31",
            "dminsttNm": "인천국제공항공사",
        },
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_band_boundary_uses_upper_band_and_printed_rate() -> None:
    """고시금액 경계값은 이상 쪽 구간에 속하고 그 구간 인쇄 하한율을 쓴다."""
    under = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttNm": "인천국제공항공사",
        },
        estimated_price=str(NOTICE_AMOUNT - 1),
    )
    assert under.effective_lwlt_rate == Decimal("84.245")
    on_boundary = _resolve(
        {
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-07-01",
            "dminsttNm": "인천국제공항공사",
        },
        estimated_price=str(NOTICE_AMOUNT),
    )
    assert on_boundary.effective_lwlt_rate == Decimal("80.495")


def test_announcement_rate_still_wins_over_institution_band_rate() -> None:
    """공고 하한율이 있으면 기관 규칙 구간 하한율보다 우선한다(종전 규칙 유지)."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "sucsfbidLwltRate": "88.5",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_FACILITY_ID
    assert result.effective_lwlt_rate == Decimal("88.5")
    assert result.rate_source == "ANNOUNCEMENT"


def test_bounded_top_rule_blocks_price_above_printed_range() -> None:
    """원문이 상한(10억원)까지 인쇄한 감리용역 구간은 그보다 큰 추정가격에서 차단된다."""
    rule = next(
        item
        for item in INSTITUTION_RULES
        if item.rule_id == "SERVC_INST_MOLIT_20180104_SUPERVISION"
    )
    assert rule.bounded_price_top is True
    assert rule.price_bands[0].upper_bound == Decimal("1000000000")
    inside = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-감리용역 적격심사 추정가격 5억원 미만",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2020-01-01",
            "dminsttNm": "국토교통부",
        },
        estimated_price="500000000",
    )
    assert inside.rule is not None
    assert inside.rule.rule_id == "SERVC_INST_MOLIT_20180104_SUPERVISION"
    assert inside.effective_lwlt_rate == Decimal("85.495")
    above = _resolve(
        {
            "sucsfbidMthdNm": "적격심사제-감리용역 적격심사 추정가격 5억원 미만",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2020-01-01",
            "dminsttNm": "국토교통부",
        },
        estimated_price="20000000000",
    )
    assert above.rule is not None
    assert above.effective_lwlt_rate is None
    assert any("어느 규모 구간에도 들지 않습니다" in warning for warning in above.warnings)


# --------------------------------------------------------------------------- #
# (다) 조달청 대행 공고 배제
# --------------------------------------------------------------------------- #


def test_pps_proxy_excludes_institution_rules() -> None:
    """공고기관이 조달청 계열이면 같은 수요기관이라도 조달청 규칙을 쓴다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사",
            "ntceInsttNm": "조달청 서울지방조달청",
            "ntceInsttCd": "1230121",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id != KDHC_FACILITY_ID
    assert result.rule.rule_id.startswith("SERVC_QUAL_")
    assert result.scope_stage == "ALL"
    assert any("조달청 대행" in warning for warning in result.warnings)


def test_pps_proxy_flag_off_selects_institution_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """배제 플래그를 끄면 대행 공고라도 기관 규칙을 쓴다."""
    monkeypatch.setattr(rules_module, "EXCLUDE_INSTITUTION_RULES_FOR_PPS_PROXY", False)
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사",
            "ntceInsttNm": "조달청 서울지방조달청",
            "ntceInsttCd": "1230121",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_FACILITY_ID
    assert result.effective_lwlt_rate == KDHC_FACILITY_LWLT


def test_self_hosted_announcement_keeps_institution_rule() -> None:
    """공고기관이 수요기관 자신이면 기관 규칙을 그대로 쓴다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사",
            "ntceInsttNm": "한국지역난방공사",
            "ntceInsttCd": "B550373",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_FACILITY_ID


# --------------------------------------------------------------------------- #
# (라) 지방계약(LOCAL) 배제
# --------------------------------------------------------------------------- #


def test_local_contract_excludes_institution_rules() -> None:
    """계약방법에 지방 표기가 있으면 기관 규칙 대신 시·도 규칙을 쓴다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국지역난방공사",
        },
        region_code="11",
        region_name="서울특별시",
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_LOCAL_SEOUL")
    assert result.scope_stage == RULE_SCOPE_REGION
    assert result.contract_regime == "LOCAL"


# --------------------------------------------------------------------------- #
# (마) partial·unresolved 기관은 조달청 규칙 그대로
# --------------------------------------------------------------------------- #


def test_unresolved_institution_keeps_common_rule() -> None:
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-10-01",
            "dminsttNm": "한국토지주택공사 경기남부지역본부",
        },
        estimated_price="3250144942",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_")
    assert result.scope_stage == "ALL"
    assert result.effective_lwlt_rate == KDHC_FACILITY_LWLT


def test_partial_institution_keeps_common_rule() -> None:
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-05-01",
            "dminsttNm": "한국도로공사",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_")
    assert result.scope_stage == "ALL"


def test_non_institution_announcement_resolution_is_unchanged() -> None:
    """기관 규칙 대상이 아닌 공고는 종전 조달청 판정 그대로다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2025-10-01",
            "dminsttNm": "테스트 수요기관",
        },
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_PRE_20250901_ATTACH_01"
    assert result.scope_stage == "ALL"
    assert any("별표 기본값(" in warning for warning in result.warnings)
    assert not any("기관" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# (사) 하위 조직(지역본부·지사·사업소·소속기관) 확장
# --------------------------------------------------------------------------- #


def test_subunit_expansion_is_declared_only_for_three_institutions() -> None:
    """하위 조직 확장은 원문으로 확인된 3곳만 선언하고 나머지는 종전 정확 일치를 유지한다."""
    declared = {
        rule.institution_name
        for rule in INSTITUTION_RULES
        if rule.subunit_name_prefixes or rule.subunit_code_prefixes
    }
    assert declared == set(SUBUNIT_INSTITUTIONS)
    for rule in INSTITUTION_RULES:
        if rule.institution_name == "국토교통부":
            assert rule.subunit_name_prefixes == ("국토교통부 ",)
            assert rule.subunit_code_prefixes == ("1613",)
        elif rule.institution_name == "환경부":
            assert rule.subunit_name_prefixes == ("기후에너지환경부 ", "환경부 ")
            # 현행 1482 대역과 옛 환경부 소속기관 1481 대역을 함께 쓴다.
            assert rule.subunit_code_prefixes == ("1482", "1481")
        elif rule.institution_name == "한국석유공사":
            assert rule.subunit_name_prefixes == ("한국석유공사 ",)
            assert rule.subunit_code_prefixes == ()
        else:
            assert rule.subunit_name_prefixes == ()
            assert rule.subunit_code_prefixes == ()


def test_molit_subunit_name_prefix_matches_without_code() -> None:
    """국토교통부 소속기관 표기는 코드가 없어도 공백 접두와 하위 조직 토막으로 매칭된다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttNm": MOLIT_SUBUNIT_NAME,
        },
        estimated_price="500000000",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOLIT_SUPERVISION_ID
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    assert result.effective_lwlt_rate == Decimal("85.495")


def test_molit_subunit_code_band_matches() -> None:
    """공고 코드가 국토교통부 하위 조직 코드 대역(1613)에 속하면 이름 없이도 매칭된다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "1613181",
        },
        estimated_price="500000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == MOLIT_SUPERVISION_ID
    assert result.scope_stage == RULE_SCOPE_INSTITUTION


def test_molit_code_out_of_band_is_excluded_even_with_prefix_name() -> None:
    """코드가 대역 밖이면 이름이 접두와 같아도 하위 조직으로 보지 않는다(오탐 차단)."""
    result = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "1614000",
            "dminsttNm": MOLIT_SUBUNIT_NAME,
        },
        estimated_price="500000000",
    )
    assert result.scope_stage != RULE_SCOPE_INSTITUTION
    assert result.rule is None or result.rule.rule_id != MOLIT_SUPERVISION_ID


def test_me_subunit_code_band_and_legacy_name_prefix_match() -> None:
    """환경부 소속기관은 코드 대역(1482·1481)과 구 표기 접두(환경부 ) 모두로 매칭된다."""
    by_code = _resolve(
        {
            "sucsfbidMthdNm": ME_TECH_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "1482021",
            "dminsttNm": "기후에너지환경부 원주지방환경청",
        },
        estimated_price="500000000",
    )
    assert by_code.rule is not None
    assert by_code.rule.rule_id == ME_TECH_ID
    assert by_code.scope_stage == RULE_SCOPE_INSTITUTION
    # 옛 환경부 소속기관 코드(1481xxx)도 같은 기관이라 코드 대역으로 매칭된다.
    by_legacy_code = _resolve(
        {
            "sucsfbidMthdNm": ME_TECH_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "1481019",
            "dminsttNm": "환경부 국가미세먼지정보센터",
        },
        estimated_price="500000000",
    )
    assert by_legacy_code.rule is not None
    assert by_legacy_code.rule.rule_id == ME_TECH_ID
    assert by_legacy_code.scope_stage == RULE_SCOPE_INSTITUTION
    by_legacy_name = _resolve(
        {
            "sucsfbidMthdNm": ME_TECH_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttNm": "환경부 한강유역환경청",
        },
        estimated_price="500000000",
    )
    assert by_legacy_name.rule is not None
    assert by_legacy_name.rule.rule_id == ME_TECH_ID
    assert by_legacy_name.scope_stage == RULE_SCOPE_INSTITUTION


def test_me_code_out_of_band_is_excluded_even_with_prefix_name() -> None:
    """환경부 코드 대역(1482·1481) 밖 코드는 이름이 접두와 같아도 하위 조직으로 보지 않는다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": ME_TECH_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "1483000",
            "dminsttNm": "환경부 한강유역환경청",
        },
        estimated_price="500000000",
    )
    assert result.scope_stage != RULE_SCOPE_INSTITUTION
    assert result.rule is None or result.rule.rule_id != ME_TECH_ID


def test_knoc_subunit_name_prefix_matches_with_and_without_code() -> None:
    """한국석유공사는 공유 코드 대역이 없어 지사·사무소 표기를 이름 접두로 판정한다."""
    without_code = _resolve(
        {
            "sucsfbidMthdNm": KNOC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttNm": "한국석유공사 서산지사",
        },
        estimated_price="200000000",
    )
    assert without_code.rule is not None
    assert without_code.rule.rule_id == KNOC_OTHER_ID
    assert without_code.scope_stage == RULE_SCOPE_INSTITUTION
    with_code = _resolve(
        {
            "sucsfbidMthdNm": KNOC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttCd": "Z000650",
            "dminsttNm": "한국석유공사 서산지사",
        },
        estimated_price="200000000",
    )
    assert with_code.rule is not None
    assert with_code.rule.rule_id == KNOC_OTHER_ID
    assert with_code.scope_stage == RULE_SCOPE_INSTITUTION


def test_subunit_prefix_requires_space_boundary_and_subunit_token() -> None:
    """공백 경계가 없거나 접두 뒤 토막이 하위 조직 표기가 아니면 확장하지 않는다."""
    cases = (
        (MOLIT_SUPERVISION_METHOD, "국토교통부대전지방국토관리청", "500000000"),
        (MOLIT_SUPERVISION_METHOD, "국토교통부 관련기관", "500000000"),
        (KNOC_OTHER_METHOD, "한국석유공사미포함기관", "200000000"),
        (KNOC_OTHER_METHOD, "한국석유공사 신규사업", "200000000"),
    )
    for method, name, price in cases:
        result = _resolve(
            {
                "sucsfbidMthdNm": method,
                "srvceDivNm": "일반용역",
                "bidNtceDt": "2026-01-02",
                "dminsttNm": name,
            },
            estimated_price=price,
        )
        assert result.scope_stage != RULE_SCOPE_INSTITUTION, name


def test_other_institutions_subunits_stay_out_of_institution_scope() -> None:
    """원문 근거가 부족한 기관의 하위 조직 표기는 종전 정확 일치 동작을 유지한다."""
    cases = (
        {"dminsttNm": "한국농어촌공사 경기지역본부", "dminsttCd": "D150001"},
        {"dminsttNm": "국가유산청 국립문화유산연구원"},
        {"dminsttNm": "한국수력원자력(주) 한울원자력본부"},
    )
    for extra in cases:
        result = _resolve(
            {
                "sucsfbidMthdNm": KDHC_FACILITY_METHOD,
                "srvceDivNm": "일반용역",
                "bidNtceDt": "2026-05-01",
                **extra,
            },
            estimated_price="600000000",
        )
        assert result.scope_stage != RULE_SCOPE_INSTITUTION, extra["dminsttNm"]


def test_subunit_announcement_still_excludes_pps_proxy_and_local() -> None:
    """하위 조직 표기라도 조달청 대행 배제와 LOCAL 우선은 그대로 적용된다."""
    proxy = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-01-02",
            "dminsttNm": MOLIT_SUBUNIT_NAME,
            "ntceInsttNm": "조달청 서울지방조달청",
            "ntceInsttCd": "1230121",
        },
        estimated_price="500000000",
    )
    assert proxy.scope_stage != RULE_SCOPE_INSTITUTION
    assert any("조달청 대행" in warning for warning in proxy.warnings)
    local = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
            "bidNtceDt": "2026-01-02",
            "dminsttNm": MOLIT_SUBUNIT_NAME,
        },
        region_code="11",
        region_name="서울특별시",
        local_service_type="GENERAL",
        estimated_price="500000000",
    )
    assert local.scope_stage == RULE_SCOPE_REGION


def test_subunit_announcement_still_checks_effective_date() -> None:
    """하위 조직 표기로 기관 규칙이 잡혀도 시행일 대조는 그대로 적용된다."""
    result = _resolve(
        {
            "sucsfbidMthdNm": MOLIT_SUPERVISION_METHOD,
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2017-12-31",
            "dminsttNm": MOLIT_SUBUNIT_NAME,
        },
        estimated_price="500000000",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


# --------------------------------------------------------------------------- #
# (바) 평가 API 끝단: 최저투찰금액이 기관 규칙 하한율로 계산
# --------------------------------------------------------------------------- #


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=4_400_000_000,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_institution_bid(db, *, presmpt_prce: int) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="기관 규칙 끝단 시험 공고",
        bid_ntce_no="EVAL-INST-001",
        bid_ntce_ord="000",
        ntce_instt_nm="인천국제공항공사",
        dminstt_nm="인천국제공항공사",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": IIAC_OTHER_METHOD,
            "srvceDivNm": "일반용역",
            "dminsttCd": "B551177",
            "dminsttNm": "인천국제공항공사",
            "ntceInsttNm": "인천국제공항공사",
            "ntceInsttCd": "B551177",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def test_institution_rule_min_bid_through_analyze_api(client, isolated_db, as_user) -> None:
    """공고 하한율이 없어도 기관 규칙 구간 하한율로 최저투찰금액이 계산된다."""
    as_user(10)
    bid = _create_institution_bid(isolated_db, presmpt_prce=5_000_000_000)

    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": 4_100_000_000,
            "qualification_input": {
                "disqualification": False,
                # 기관 정량평가 배점표는 아직 미반영이라 정량점수를 직접 입력한다.
                "manual_non_price_score": 40.0,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["rule_id"] == IIAC_OTHER_ID
    assert payload["lower_bound_rate"] == pytest.approx(80.495)
    assert any(
        "낙찰하한율 80.495% 적용 최저 투찰금액: 4,024,750,000원" in warning
        for warning in payload["warnings"]
    )
