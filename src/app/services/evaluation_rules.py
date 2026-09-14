"""
src/app/services/evaluation_rules.py

일반용역 적격심사 규칙 레지스트리 및 공고 판별 모듈.
공고 메타데이터(category, prearngPrceDcsnMthdNm, sucsfbidMthdNm, sucsfbidLwltRate)를
기반으로 적격심사 대상 여부와 적용 별표 규칙을 결정론적으로 판별합니다.
외부 DB, HTTP 요청, 파일 I/O, 시스템 시각에 의존하지 않는 순수 함수로 동작합니다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class EvaluationRule:
    """일반용역 적격심사 별표 평가 규칙 선언형 객체.

    버전이 고정된 선언형 규칙으로, 규칙 ID, 시행일, 출처, 식별 문자열, 낙찰하한율을 관리합니다.
    """

    rule_id: str
    service_type: str
    table_name: str
    description: str
    effective_date: str
    source: str
    patterns: tuple[str, ...]
    lwlt_rate: Decimal
    base_rate: Decimal = Decimal("0.90")
    sample_count: int = 0


# 2026-05-26 개정 후 일반용역 적격심사 실측 정본 별표 14종
POST_20260526_RULES: tuple[EvaluationRule, ...] = (
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_01",
        service_type="FACILITY",
        table_name="시설분야용역 적격심사",
        description="시설분야용역 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "시설분야용역 적격심사 추정가격 5억원 미만",
            "시설분야용역 적격심사 추정가격 5억원 이상",
            "시설분야용역 적격심사 추정가격 5억원미만",
            "시설분야용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("89.995"),
        base_rate=Decimal("0.90"),
        sample_count=213,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_02",
        service_type="INSURANCE",
        table_name="보험용역 적격심사",
        description="보험용역 적격심사 추정가격 5억원미만 / 5억원이상 (실측 정본 47.995)",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "보험용역 적격심사 추정가격 5억원미만",
            "보험용역 적격심사 추정가격 5억원이상",
            "보험용역 적격심사 추정가격 5억원 미만",
            "보험용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("47.995"),
        base_rate=Decimal("0.90"),
        sample_count=195,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_03",
        service_type="PASSENGER_TRANSPORT",
        table_name="여객 육상운송용역 적격심사",
        description="여객 육상운송용역 적격심사 추정가격 5억원미만",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "여객 육상운송용역 적격심사 추정가격 5억원미만",
            "여객 육상운송용역 적격심사 추정가격 5억원 미만",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.90"),
        sample_count=55,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_04",
        service_type="SW_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사",
        description="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 이상",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.90"),
        sample_count=33,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_05",
        service_type="SW_NON_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사",
        description="소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("86.245"),
        base_rate=Decimal("0.90"),
        sample_count=13,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_06",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 미만)",
        description="학술연구용역 적격심사 추정가격 고시금액 미만",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "학술연구용역 적격심사 추정가격 고시금액 미만",
            "학술연구용역 적격심사 추정가격 고시금액미만",
        ),
        lwlt_rate=Decimal("86.245"),
        base_rate=Decimal("0.90"),
        sample_count=77,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_07",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 이상)",
        description="학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상 / 5억원 이상",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "학술연구용역 적격심사 추정가격 5억원미만 고시금액이상",
            "학술연구용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "학술연구용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "학술연구용역 적격심사 추정가격 5억원 이상",
            "학술연구용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("82.495"),
        base_rate=Decimal("0.90"),
        sample_count=17,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_08",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 미만)",
        description="폐기물처리용역 적격심사 추정가격 고시금액미만",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 고시금액미만",
            "폐기물처리용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("86.245"),
        base_rate=Decimal("0.90"),
        sample_count=92,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_09",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 이상)",
        description="폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원미만 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원이상",
            "폐기물처리용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("82.495"),
        base_rate=Decimal("0.90"),
        sample_count=11,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_10",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 미만)",
        description="화물 육상운송용역 적격심사 추정가격 고시금액미만",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 고시금액미만",
            "화물 육상운송용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("86.245"),
        base_rate=Decimal("0.90"),
        sample_count=29,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_11",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 이상)",
        description="화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "화물 육상운송용역 적격심사 추정가격 5억원미만 고시금액이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "화물 육상운송용역 적격심사 추정가격 5억원이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("82.495"),
        base_rate=Decimal("0.90"),
        sample_count=31,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_12",
        service_type="GENERAL",
        table_name="추정가격 2억원 미만인 용역",
        description="추정가격 2억원 미만인 용역",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "추정가격 2억원 미만인 용역",
            "추정가격 2억원미만인 용역",
            "추정가격 2억원 미만인용역",
            "추정가격 2억원미만인용역",
        ),
        lwlt_rate=Decimal("87.745"),
        base_rate=Decimal("0.90"),
        sample_count=480,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_13",
        service_type="GENERAL",
        table_name="추정가격 5억원 미만 2억원 이상인 용역",
        description="추정가격 5억원 미만 2억원 이상인 용역",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "추정가격 5억원 미만 2억원 이상인 용역",
            "추정가격 5억원미만 2억원이상인 용역",
            "추정가격 5억원미만 2억원 이상인 용역",
            "추정가격 5억원 미만 2억원이상인 용역",
        ),
        lwlt_rate=Decimal("86.745"),
        base_rate=Decimal("0.90"),
        sample_count=249,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_14",
        service_type="GENERAL",
        table_name="추정가격 30억원 미만 15억원 이상인 용역",
        description="추정가격 30억원 미만 15억원 이상인 용역",
        effective_date="2026-05-26",
        source="조달청 일반용역 적격심사 세부기준 (2026-05-26 개정)",
        patterns=(
            "추정가격 30억원 미만 15억원 이상인 용역",
            "추정가격 30억원미만 15억원이상인 용역",
            "추정가격 30억원미만 15억원 이상인 용역",
            "추정가격 30억원 미만 15억원이상인 용역",
        ),
        lwlt_rate=Decimal("82.995"),
        base_rate=Decimal("0.90"),
        sample_count=18,
    ),
)

# 기술용역은 식별 문자열별 고정 규칙으로 환원하지 않고 공고 하한율만 사용합니다.
SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT = EvaluationRule(
    rule_id="SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT",
    service_type="TECH",
    table_name="기술용역 적격심사",
    description="기술용역 적격심사 공고 하한율",
    effective_date="2026-05-26",
    source="공고별 sucsfbidLwltRate",
    patterns=(),
    lwlt_rate=Decimal("0"),
    base_rate=Decimal("0.90"),
)

# 2026-05-26 개정 전 규칙 저장소 (과거 분석 재현용 예약)
PRE_20260526_RULES: tuple[EvaluationRule, ...] = ()


# 차단 사유 코드 상수
BLOCK_CODE_NOT_SERVC = "NOT_SERVC"
BLOCK_CODE_NON_PRED_PRICE = "NON_PRED_PRICE"
BLOCK_CODE_MANUAL_EVALUATION = "MANUAL_EVALUATION"
BLOCK_CODE_RULE_NOT_FOUND = "RULE_NOT_FOUND"
BLOCK_CODE_NEGOTIATION_CONTRACT = "NEGOTIATION_CONTRACT"
BLOCK_CODE_TECH_SERVICE_MISSING_LWLT = "TECH_SERVICE_MISSING_LWLT"
BLOCK_CODE_NOT_QUALIFICATION_METHOD = "NOT_QUALIFICATION_METHOD"
BLOCK_CODE_RULE_REGIME_MISMATCH = "RULE_REGIME_MISMATCH"

METHOD_NAME_PLACEHOLDER = "공고서참조"
METHOD_SOURCE_ANNOUNCEMENT = "ANNOUNCEMENT"
METHOD_SOURCE_CODE = "CODE"
METHOD_FAMILY_QUALIFICATION = "적격심사제"

# 2025-01 이후 용역 공고 356,655건에서 코드 하나가 계열 하나에만 대응함을 실측했습니다 (2026-09-14).
METHOD_FAMILY_BY_CODE: dict[str, str] = {
    "낙030001": METHOD_FAMILY_QUALIFICATION,
    "낙030002": "규격가격동시입찰",
    "낙030003": "2단계경쟁입찰",
    "낙030004": "다수공급자계약",
    "낙030005": "협상에의한계약",
    "낙030008": "경쟁적대화방식에의한계약",
    "낙030009": "수의시담",
    "낙030010": "수의시담(2인 이상)",
    "낙030017": "설계공모",
    "낙030018": "규격적합자중 최저가",
    "낙030021": "최저가낙찰제",
    "낙030022": "제한적최저가(낙찰하한율)",
    "낙030026": "종합심사낙찰제(기술용역)",
    "낙030029": "소액수의견적",
    "낙030031": "카탈로그계약",
    "낙030033": "안전점검수행기관지정",
}

NEGOTIATION_VARIANT_STANDARD = "STANDARD"
NEGOTIATION_VARIANT_SW = "SW"
NEGOTIATION_VARIANT_ENGINEERING = "ENGINEERING"
NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING = "CONSTRUCTION_ENGINEERING"

_NEGOTIATION_VARIANTS: tuple[tuple[str, str], ...] = (
    ("건설엔지니어링", NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING),
    ("엔지니어링", NEGOTIATION_VARIANT_ENGINEERING),
    ("SW사업", NEGOTIATION_VARIANT_SW),
    ("협상에 의한 낙찰자 결정", NEGOTIATION_VARIANT_STANDARD),
)


@dataclass(frozen=True)
class RuleResolutionResult:
    """적격심사 규칙 판별 결과 객체."""

    is_blocked: bool
    block_reason_code: str | None = None
    block_reason_message: str | None = None
    rule: EvaluationRule | None = None
    effective_lwlt_rate: Decimal | None = None
    rate_source: str | None = None  # "ANNOUNCEMENT" 또는 "RULE_DEFAULT"
    warnings: list[str] = field(default_factory=list)
    negotiation_tech_eval_rate: Decimal | None = None
    negotiation_price_eval_rate: Decimal | None = None
    negotiation_variant: str | None = None
    method_source: str | None = None  # "ANNOUNCEMENT" 또는 "CODE"


def normalize_pattern_string(text: str) -> str:
    """공백 및 특수문자를 정규화하여 문자열 매칭 안정성을 보장합니다."""
    return re.sub(r"[\s\-_()\[\]]", "", text).lower()


def match_rule_by_mthd_nm(
    sucsfbid_mthd_nm: str,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
) -> EvaluationRule | None:
    """sucsfbidMthdNm 문자열을 기준으로 등록된 별표 규칙과 매칭합니다.

    추정가격 구간으로 별표를 추론하지 않고 공고에 명시된 낙찰방법 문자열을 정본으로 삼습니다.
    구체적인 하위 별표가 일반 용역 별표보다 우선 매칭되도록 정규화 문자열 길이 역순으로 정렬 탐색합니다.
    """
    if not sucsfbid_mthd_nm or not sucsfbid_mthd_nm.strip():
        return None

    normalized_input = normalize_pattern_string(sucsfbid_mthd_nm)

    # 패턴 매칭 후보 목록 작성 (긴 패턴이 먼저 매칭되도록 정렬)
    pattern_rule_pairs: list[tuple[str, str, EvaluationRule]] = []
    for rule in rules:
        for p in rule.patterns:
            pattern_rule_pairs.append((p, normalize_pattern_string(p), rule))

    # 정규화 패턴 길이 내림차순 정렬
    pattern_rule_pairs.sort(key=lambda item: len(item[1]), reverse=True)

    for raw_pat, norm_pat, rule in pattern_rule_pairs:
        if raw_pat in sucsfbid_mthd_nm or norm_pat in normalized_input:
            return rule

    return None


def get_rule_by_id(
    rule_id: str,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
) -> EvaluationRule | None:
    """규칙 ID로 선언형 평가 규칙을 단일 조회합니다."""
    for rule in rules:
        if rule.rule_id == rule_id:
            return rule
    return None


def list_all_rules(
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
) -> list[EvaluationRule]:
    """등록된 모든 선언형 규칙 목록을 반환합니다."""
    return list(rules)


def resolve_method_name(
    sucsfbid_mthd_nm: str | None,
    sucsfbid_mthd_cd: str | None,
) -> tuple[str | None, str | None, list[str]]:
    """판별에 쓸 낙찰방법명과 그 출처를 정합니다.

    원문이 '공고서참조'이거나 비어 있으면 sucsfbidMthdCd 로 계열명을 대신 씁니다.
    2024년 이전 용역 공고는 원문이 전부 '공고서참조'라 코드가 유일한 단서입니다.
    """
    name = sucsfbid_mthd_nm.strip() if sucsfbid_mthd_nm else ""
    if name and name != METHOD_NAME_PLACEHOLDER:
        return sucsfbid_mthd_nm, METHOD_SOURCE_ANNOUNCEMENT, []

    code = sucsfbid_mthd_cd.strip() if sucsfbid_mthd_cd else ""
    family = METHOD_FAMILY_BY_CODE.get(code)
    if family is not None:
        return family, METHOD_SOURCE_CODE, []

    warnings = []
    if code:
        warnings.append(f"낙찰방법 코드({code})가 계열 대응표에 없어 낙찰방법을 추정하지 않습니다.")
    return sucsfbid_mthd_nm, METHOD_SOURCE_ANNOUNCEMENT, warnings


def _parse_announcement_date(value: date | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip() if value is not None else ""
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def resolve_evaluation_rule(
    category: str | None,
    prearng_prce_dcsn_mthd_nm: str | None,
    sucsfbid_mthd_nm: str | None,
    sucsfbid_lwlt_rate: Decimal | str | float | None = None,
    tech_ablt_evl_rt: Decimal | str | float | None = None,
    bid_prce_evl_rt: Decimal | str | float | None = None,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
    srvce_div_nm: str | None = None,
    sucsfbid_mthd_cd: str | None = None,
    bid_ntce_dt: date | str | None = None,
) -> RuleResolutionResult:
    """낙찰방법 출처를 정하고 별표를 판별한 뒤 공고일과 별표 시행일을 대조합니다.

    [추가 판별]
    - 원문 낙찰방법이 '공고서참조'면 sucsfbidMthdCd 계열명으로 판별
    - 별표가 확정돼도 공고일이 별표 시행일보다 앞서면 계산 차단 (RULE_REGIME_MISMATCH).
      공고일이 없으면 대조하지 않고, 있는데 읽을 수 없으면 차단 대신 경고만 남깁니다.
    """
    method_name, method_source, method_warnings = resolve_method_name(
        sucsfbid_mthd_nm, sucsfbid_mthd_cd
    )
    result = _resolve_by_method_name(
        category=category,
        prearng_prce_dcsn_mthd_nm=prearng_prce_dcsn_mthd_nm,
        sucsfbid_mthd_nm=method_name,
        sucsfbid_lwlt_rate=sucsfbid_lwlt_rate,
        tech_ablt_evl_rt=tech_ablt_evl_rt,
        bid_prce_evl_rt=bid_prce_evl_rt,
        rules=rules,
        srvce_div_nm=srvce_div_nm,
    )
    result = replace(
        result,
        method_source=method_source,
        warnings=method_warnings + result.warnings,
    )

    if (
        method_source == METHOD_SOURCE_CODE
        and result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    ):
        result = replace(
            result,
            block_reason_message=(
                f"낙찰방법이 '{METHOD_NAME_PLACEHOLDER}'라 코드({sucsfbid_mthd_cd})로 "
                "적격심사제 공고임은 확인했지만, 적용 별표는 공고서에서만 확인할 수 있습니다."
            ),
        )

    if result.is_blocked or result.rule is None:
        return result

    if bid_ntce_dt is None:
        return result
    effective_date = date.fromisoformat(result.rule.effective_date)
    announced = _parse_announcement_date(bid_ntce_dt)
    if announced is None:
        return replace(
            result,
            warnings=[
                *result.warnings,
                f"공고일({bid_ntce_dt})을 읽을 수 없어 별표 시행일({effective_date}) 대조를 건너뛰었습니다.",
            ],
        )
    if announced < effective_date:
        return replace(
            result,
            is_blocked=True,
            block_reason_code=BLOCK_CODE_RULE_REGIME_MISMATCH,
            block_reason_message=(
                f"공고일({announced})이 별표 시행일({effective_date})보다 앞서 현행 별표로 "
                "계산하지 않습니다. 개정 전 별표는 등록되어 있지 않습니다."
            ),
            effective_lwlt_rate=None,
            rate_source=None,
        )
    return result


def _resolve_by_method_name(
    category: str | None,
    prearng_prce_dcsn_mthd_nm: str | None,
    sucsfbid_mthd_nm: str | None,
    sucsfbid_lwlt_rate: Decimal | str | float | None = None,
    tech_ablt_evl_rt: Decimal | str | float | None = None,
    bid_prce_evl_rt: Decimal | str | float | None = None,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
    srvce_div_nm: str | None = None,
) -> RuleResolutionResult:
    """일반용역 적격심사 대상 판별 순서에 따라 차단 조건 및 별표 규칙을 확정합니다.

    [판별 순서]
    1. category != 'Servc' -> 계산 차단 (NOT_SERVC)
    2. prearngPrceDcsnMthdNm == '비예가' -> 계산 차단 (NON_PRED_PRICE)
    3. sucsfbidMthdNm 이 '적격심사제-관리규정외 수기심사' -> 계산 차단 (MANUAL_EVALUATION)
    4. 협상에의한계약 -> 평가비율만 제공 (NEGOTIATION_CONTRACT)
    5. 적격심사제가 아닌 알려진 낙찰방법 계열 -> 계산 차단 (NOT_QUALIFICATION_METHOD)
    6. 기술용역 적격심사 -> 공고 하한율 적용
    7. sucsfbidMthdNm 을 별표 식별 문자열과 매칭 -> 별표 확정, 실패 시 계산 차단 (RULE_NOT_FOUND)
    8. 하한율 확정 우선순위:
       - 공고의 sucsfbidLwltRate 가 최우선
       - 결측이면 별표 기본값을 쓰되 '기본값 사용' 경고
       - 공고값과 별표 기본값이 다르면 공고값을 쓰고 '불일치' 경고
    """
    warnings: list[str] = []

    # 1. 용역(Servc) 검사
    if category != "Servc":
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_NOT_SERVC,
            block_reason_message="일반용역(Servc) 공고만 적격심사 정량평가 대상입니다.",
            warnings=warnings,
        )

    # 2. 비예가 검사
    if prearng_prce_dcsn_mthd_nm and "비예가" in prearng_prce_dcsn_mthd_nm:
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_NON_PRED_PRICE,
            block_reason_message="비예가 공고는 예정가격이 없어 가격점수 산출 분모가 부재합니다.",
            warnings=warnings,
        )

    # 3. 관리규정외 수기심사 검사
    if sucsfbid_mthd_nm and "관리규정외 수기심사" in sucsfbid_mthd_nm:
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_MANUAL_EVALUATION,
            block_reason_message=(
                "적격심사제-관리규정외 수기심사는 발주기관 자체 기준이 적용되므로 "
                "공고문 확인이 필요하여 계산을 차단합니다."
            ),
            warnings=warnings,
        )

    # 4. 협상에의한계약은 적격심사 별표가 아닌 별도 평가 체계입니다.
    negotiation_variant: str | None = None
    if sucsfbid_mthd_nm and "협상에의한계약" in sucsfbid_mthd_nm:
        for marker, variant in _NEGOTIATION_VARIANTS:
            if marker in sucsfbid_mthd_nm:
                negotiation_variant = variant
                break
        if negotiation_variant is None:
            negotiation_variant = NEGOTIATION_VARIANT_STANDARD

        parsed_rates: list[Decimal | None] = []
        rate_labels = ("기술능력 평가비율(techAbltEvlRt)", "입찰가격 평가비율(bidPrceEvlRt)")
        for label, value in zip(rate_labels, (tech_ablt_evl_rt, bid_prce_evl_rt), strict=True):
            parsed: Decimal | None = None
            try:
                text_value = str(value).strip() if value is not None else ""
                if text_value:
                    parsed = Decimal(str(value))
            except (ArithmeticError, TypeError, ValueError):
                parsed = None
            if parsed is None:
                warnings.append(
                    f"협상 공고의 {label} 값이 없거나 숫자가 아니어서 제공하지 않습니다."
                )
            parsed_rates.append(parsed)

        tech_rate, price_rate = parsed_rates
        if (
            tech_rate is not None
            and price_rate is not None
            and tech_rate + price_rate != Decimal("100")
        ):
            warnings.append(
                f"협상 공고의 기술능력·입찰가격 평가비율 합계({tech_rate + price_rate})가 100이 아닙니다."
            )
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_NEGOTIATION_CONTRACT,
            block_reason_message=(
                "협상에의한계약 공고입니다. 적격심사 점수 산식은 적용하지 않으며 "
                "공고의 기술능력·입찰가격 평가비율만 제공합니다."
            ),
            warnings=warnings,
            negotiation_tech_eval_rate=tech_rate,
            negotiation_price_eval_rate=price_rate,
            negotiation_variant=negotiation_variant,
        )

    method_family = sucsfbid_mthd_nm.split("-", 1)[0].strip() if sucsfbid_mthd_nm else ""
    if (
        method_family in METHOD_FAMILY_BY_CODE.values()
        and method_family != METHOD_FAMILY_QUALIFICATION
    ):
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_NOT_QUALIFICATION_METHOD,
            block_reason_message=(
                f"낙찰방법이 '{method_family}' 계열이라 적격심사 점수 산식을 적용하지 않습니다."
            ),
            warnings=warnings,
        )

    # 기술용역 적격심사는 협상 판별 이후, 일반용역 별표 매칭 이전에 판별합니다.
    if srvce_div_nm == "기술용역" and sucsfbid_mthd_nm and "적격심사" in sucsfbid_mthd_nm:
        tech_parsed_lwlt_rate: Decimal | None = None
        if sucsfbid_lwlt_rate is not None:
            try:
                str_rate = str(sucsfbid_lwlt_rate).strip()
                if str_rate:
                    tech_parsed_lwlt_rate = Decimal(str_rate)
            except (ArithmeticError, TypeError, ValueError):
                tech_parsed_lwlt_rate = None

        if tech_parsed_lwlt_rate is None or tech_parsed_lwlt_rate <= Decimal("0"):
            return RuleResolutionResult(
                is_blocked=True,
                block_reason_code=BLOCK_CODE_TECH_SERVICE_MISSING_LWLT,
                block_reason_message=(
                    "기술용역 공고의 낙찰하한율이 없어 공고별 하한율을 적용할 수 없습니다."
                ),
                rule=SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
                effective_lwlt_rate=Decimal("0"),
                warnings=warnings,
            )

        return RuleResolutionResult(
            is_blocked=False,
            block_reason_code=None,
            block_reason_message=None,
            rule=SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            effective_lwlt_rate=tech_parsed_lwlt_rate,
            rate_source="ANNOUNCEMENT",
            warnings=warnings,
        )

    # 5 & 6. 별표 규칙 매칭
    if not sucsfbid_mthd_nm:
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_RULE_NOT_FOUND,
            block_reason_message="낙찰방법(sucsfbidMthdNm)이 누락되어 적격심사 별표를 매칭할 수 없습니다.",
            warnings=warnings,
        )

    matched_rule = match_rule_by_mthd_nm(sucsfbid_mthd_nm, rules=rules)
    if matched_rule is None:
        return RuleResolutionResult(
            is_blocked=True,
            block_reason_code=BLOCK_CODE_RULE_NOT_FOUND,
            block_reason_message=(
                f"공고의 낙찰방법('{sucsfbid_mthd_nm}')에서 일치하는 일반용역 적격심사 별표를 "
                "찾을 수 없습니다. 수동 규칙 선택이 필요합니다."
            ),
            warnings=warnings,
        )

    # 6 & 7. 하한율 우선순위 처리
    parsed_lwlt_rate: Decimal | None = None
    if sucsfbid_lwlt_rate is not None:
        try:
            str_rate = str(sucsfbid_lwlt_rate).strip()
            if str_rate:
                parsed_lwlt_rate = Decimal(str_rate)
        except Exception:
            parsed_lwlt_rate = None

    if parsed_lwlt_rate is None or parsed_lwlt_rate <= Decimal("0"):
        effective_rate = matched_rule.lwlt_rate
        rate_source = "RULE_DEFAULT"
        warnings.append(
            f"공고에 낙찰하한율이 명시되지 않아 별표 기본값({matched_rule.lwlt_rate}%)을 적용합니다."
        )
    elif parsed_lwlt_rate != matched_rule.lwlt_rate:
        effective_rate = parsed_lwlt_rate
        rate_source = "ANNOUNCEMENT"
        warnings.append(
            f"공고 하한율({parsed_lwlt_rate}%)이 별표 기본값({matched_rule.lwlt_rate}%)과 "
            f"일치하지 않아 공고 하한율을 우선 적용합니다."
        )
    else:
        effective_rate = parsed_lwlt_rate
        rate_source = "ANNOUNCEMENT"

    return RuleResolutionResult(
        is_blocked=False,
        block_reason_code=None,
        block_reason_message=None,
        rule=matched_rule,
        effective_lwlt_rate=effective_rate,
        rate_source=rate_source,
        warnings=warnings,
    )


def resolve_evaluation_rule_from_raw_data(
    category: str | None,
    raw_data: dict[str, Any] | None,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
) -> RuleResolutionResult:
    """raw_data 딕셔너리에서 기관 필드를 추출하여 적격심사 규칙을 판별합니다."""
    if raw_data is None:
        raw_data = {}

    prearng_mthd = raw_data.get("prearngPrceDcsnMthdNm")
    sucsfbid_mthd = raw_data.get("sucsfbidMthdNm")
    lwlt_rate = raw_data.get("sucsfbidLwltRate")
    tech_eval_rate = raw_data.get("techAbltEvlRt")
    price_eval_rate = raw_data.get("bidPrceEvlRt")
    srvce_div_nm = raw_data.get("srvceDivNm")

    return resolve_evaluation_rule(
        category=category,
        prearng_prce_dcsn_mthd_nm=prearng_mthd,
        sucsfbid_mthd_nm=sucsfbid_mthd,
        sucsfbid_lwlt_rate=lwlt_rate,
        tech_ablt_evl_rt=tech_eval_rate,
        bid_prce_evl_rt=price_eval_rate,
        rules=rules,
        srvce_div_nm=srvce_div_nm,
        sucsfbid_mthd_cd=raw_data.get("sucsfbidMthdCd"),
        bid_ntce_dt=raw_data.get("bidNtceDt"),
    )
