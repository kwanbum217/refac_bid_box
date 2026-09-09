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
from dataclasses import dataclass, field
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

# 2026-05-26 개정 전 규칙 저장소 (과거 분석 재현용 예약)
PRE_20260526_RULES: tuple[EvaluationRule, ...] = ()


# 차단 사유 코드 상수
BLOCK_CODE_NOT_SERVC = "NOT_SERVC"
BLOCK_CODE_NON_PRED_PRICE = "NON_PRED_PRICE"
BLOCK_CODE_MANUAL_EVALUATION = "MANUAL_EVALUATION"
BLOCK_CODE_RULE_NOT_FOUND = "RULE_NOT_FOUND"


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


def resolve_evaluation_rule(
    category: str | None,
    prearng_prce_dcsn_mthd_nm: str | None,
    sucsfbid_mthd_nm: str | None,
    sucsfbid_lwlt_rate: Decimal | str | float | None = None,
    rules: Sequence[EvaluationRule] = POST_20260526_RULES,
) -> RuleResolutionResult:
    """일반용역 적격심사 대상 판별 순서에 따라 차단 조건 및 별표 규칙을 확정합니다.

    [판별 순서]
    1. category != 'Servc' -> 계산 차단 (NOT_SERVC)
    2. prearngPrceDcsnMthdNm == '비예가' -> 계산 차단 (NON_PRED_PRICE)
    3. sucsfbidMthdNm 이 '적격심사제-관리규정외 수기심사' -> 계산 차단 (MANUAL_EVALUATION)
    4. sucsfbidMthdNm 을 별표 식별 문자열과 매칭 -> 별표 확정
    5. 매칭 실패 -> 계산 차단 (RULE_NOT_FOUND)
    6. 하한율 확정 우선순위:
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

    # 4 & 5. 별표 규칙 매칭
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

    return resolve_evaluation_rule(
        category=category,
        prearng_prce_dcsn_mthd_nm=prearng_mthd,
        sucsfbid_mthd_nm=sucsfbid_mthd,
        sucsfbid_lwlt_rate=lwlt_rate,
        rules=rules,
    )
