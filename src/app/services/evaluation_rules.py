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
    # 가격배점한도(B)·평점계수(k)·통과점수(T). 규칙 레지스트리가 원문으로 확정한 규칙만 값을 갖고,
    # 확정 근거가 없는 규칙은 추측하지 않고 None 으로 둡니다. 사용자 직접 입력은 이 선언값을
    # 덮어쓰는 용도로만 남습니다. 출처(또는 미확인 사유)는 score_table_source 에 남깁니다.
    max_price_score: Decimal | None = None
    multiplier: Decimal | None = None
    pass_threshold: Decimal | None = None
    score_table_source: str | None = None


# 배점표(B·k·T) 판정표는 원문 별표 문서에서 확정된 값만 담습니다.
# 근거 문서:
# - docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md (개정 전 제2025-257호·제2026-15호)
# - docs/analysis/servc_post_rules_audit_20260929.md (개정 후 제2026-260호)
# - docs/analysis/20260930_score_params_acquisition.md (별표9 실측·통과점수)
# 고시금액(용역 2.3억) 출처: src/ml/features.py:34-37 NOTICE_AMOUNT_BY_YEAR
_SCORE_DOC_PRE = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:152-179"
_SCORE_DOC_POST = "docs/analysis/servc_post_rules_audit_20260929.md:96-131"
_SCORE_DOC_MEASURED = "docs/analysis/20260930_score_params_acquisition.md:135-148"
_SCORE_SRC_PRE = (
    f"{_SCORE_DOC_PRE} (제2025-257호·제2026-15호 별표별 입찰가격 계산식·배점한도·통과점수)"
)
_SCORE_SRC_POST = f"{_SCORE_DOC_POST} (제2026-260호 별표별 입찰가격 계산식) 및 {_SCORE_DOC_MEASURED} (통과점수·별표9 실측)"
_SCORE_REASON_PRE_20230501 = (
    "미확인: 제2023-53호 판의 별표 배점표(B·k·T)는 조사 범위 밖입니다 "
    "(docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:655-661)"
)
_SCORE_REASON_DOC_CONFLICT = (
    "미확인: 문서 간 기준비율·계수 불일치(시설분야 91 대 93, 여객·SW(대상) 계수 4)로 "
    "확정하지 않습니다 (docs/analysis/servc_post_rules_audit_20260929.md:168-169)"
)
_SCORE_REASON_UNMAPPED_BAND = (
    "미확인: 일반 띠는 별표 1~9 에 같은 이름이 없어 별표 귀속이 미확인입니다 "
    "(docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312)"
)
_SCORE_REASON_UNKNOWN_RULE = "미확인: 배점표 판정표에 없는 규칙이라 값을 만들지 않습니다."
_SCORE_NOTE_B_SPLIT = "B는 추정가격 5억원 미만 70/이상 60 으로 갈려 미확인"
_SCORE_NOTE_K_SPLIT = "k는 고시금액 미만 4/이상 2 로 갈려 미확인"

ScoreTableEntry = tuple[Decimal | None, Decimal | None, Decimal | None, str]

_SCORE_TABLE_DECLARATIONS: dict[str, ScoreTableEntry] = {
    # 2025-09-01 시행 판 (제2025-257호·제2026-15호)
    "SERVC_QUAL_PRE_20250901_ATTACH_01": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_PRE_20250901_ATTACH_02": (
        None,
        Decimal("0.375"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표6 보험: k=0.375 단일·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_03": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_PRE_20250901_ATTACH_04": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_PRE_20250901_ATTACH_05": (
        None,
        None,
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표3 SW 비대상: T=85; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_06": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표1 학술연구 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_07": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표1 학술연구 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_08": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표4 폐기물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_09": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표4 폐기물 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_10": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표5의2 화물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_11": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표5의2 화물 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_15": (
        None,
        None,
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표7 수리·점검: T=85; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_16": (
        Decimal("70"),
        None,
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표8 임대차: B=70 단일·T=85; {_SCORE_NOTE_K_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_17": (
        None,
        None,
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표9 수요기관 지정형: T=85; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
    ),
    # 2023-05-01 시행 판 (제2023-53호). 배점표는 원문 범위 밖이라 전량 미확인입니다.
    **{
        f"SERVC_QUAL_PRE_20230501_ATTACH_{index:02d}": (
            None,
            None,
            None,
            _SCORE_REASON_PRE_20230501,
        )
        for index in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 17)
    },
    # 2026-05-26 시행 판 (제2026-260호)
    "SERVC_QUAL_POST_20260526_ATTACH_01": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_POST_20260526_ATTACH_02": (
        None,
        Decimal("0.375"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표6 보험: k=0.375 단일·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_03": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_POST_20260526_ATTACH_04": (None, None, None, _SCORE_REASON_DOC_CONFLICT),
    "SERVC_QUAL_POST_20260526_ATTACH_05": (
        None,
        None,
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표3 SW 비대상: T=85; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_06": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표1 학술연구 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_07": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표1 학술연구 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_08": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표4 폐기물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_09": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표4 폐기물 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_10": (
        Decimal("70"),
        Decimal("4"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표5의2 화물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억)",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_11": (
        None,
        Decimal("2"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표5의2 화물 고시금액 이상: k=2·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_12": (None, None, None, _SCORE_REASON_UNMAPPED_BAND),
    "SERVC_QUAL_POST_20260526_ATTACH_13": (None, None, None, _SCORE_REASON_UNMAPPED_BAND),
    "SERVC_QUAL_POST_20260526_ATTACH_14": (None, None, None, _SCORE_REASON_UNMAPPED_BAND),
}


def _with_score_table(rules: tuple[EvaluationRule, ...]) -> tuple[EvaluationRule, ...]:
    """선언된 배점표 판정표를 규칙 객체에 반영합니다.

    표에 값이 있으면 그대로 대입하고, 없으면 값을 만들지 않고 미확인 사유만 남깁니다.
    """
    enriched: list[EvaluationRule] = []
    for rule in rules:
        max_price_score, multiplier, pass_threshold, source = _SCORE_TABLE_DECLARATIONS.get(
            rule.rule_id,
            (None, None, None, _SCORE_REASON_UNKNOWN_RULE),
        )
        enriched.append(
            replace(
                rule,
                max_price_score=max_price_score,
                multiplier=multiplier,
                pass_threshold=pass_threshold,
                score_table_source=source,
            )
        )
    return tuple(enriched)


# 2026-05-26 개정 후 일반용역 적격심사 실측 정본 별표 14종
POST_20260526_RULES: tuple[EvaluationRule, ...] = (
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_01",
        service_type="FACILITY",
        table_name="시설분야용역 적격심사",
        description="시설분야용역 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2026-05-26",
        source="조달청 공고 제2026-260호 (2026-05-26 시행)",
        patterns=(
            "시설분야용역 적격심사 추정가격 5억원 미만",
            "시설분야용역 적격심사 추정가격 5억원 이상",
            "시설분야용역 적격심사 추정가격 5억원미만",
            "시설분야용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("89.995"),
        base_rate=Decimal("0.93"),
        sample_count=213,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_02",
        service_type="INSURANCE",
        table_name="보험용역 적격심사",
        description="보험용역 적격심사 추정가격 5억원미만 / 5억원이상 (실측 정본 47.995)",
        effective_date="2026-05-26",
        source="조달청 공고 제2026-260호 (2026-05-26 시행)",
        patterns=(
            "보험용역 적격심사 추정가격 5억원미만",
            "보험용역 적격심사 추정가격 5억원이상",
            "보험용역 적격심사 추정가격 5억원 미만",
            "보험용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("47.995"),
        base_rate=Decimal("0.88"),
        sample_count=195,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_03",
        service_type="PASSENGER_TRANSPORT",
        table_name="여객 육상운송용역 적격심사",
        description="여객 육상운송용역 적격심사 추정가격 5억원미만",
        effective_date="2026-05-26",
        source="조달청 공고 제2026-260호 (2026-05-26 시행)",
        patterns=(
            "여객 육상운송용역 적격심사 추정가격 5억원미만",
            "여객 육상운송용역 적격심사 추정가격 5억원 미만",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=55,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_POST_20260526_ATTACH_04",
        service_type="SW_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사",
        description="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2026-05-26",
        source="조달청 공고 제2026-260호 (2026-05-26 시행)",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 이상",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
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

POST_20260526_RULES = _with_score_table(POST_20260526_RULES)

# 2026-07-27 개정 후 일반용역 적격심사 별표 14종 (조달청 공고 제2026-390호).
# 여객 육상운송용역(ATTACH_03)과 소프트웨어용역 중소기업자간 경쟁제품 대상(ATTACH_04)만
# 기준비율과 낙찰하한율이 오르고, 나머지 12종은 제2026-260호 벌의 같은 객체를 재사용합니다.
POST_20260727_RULES: tuple[EvaluationRule, ...] = (
    POST_20260526_RULES[0],
    POST_20260526_RULES[1],
    replace(
        POST_20260526_RULES[2],
        rule_id="SERVC_QUAL_POST_20260727_ATTACH_03",
        effective_date="2026-07-27",
        source="조달청 공고 제2026-390호 (2026-07-27 시행)",
        lwlt_rate=Decimal("89.995"),
        base_rate=Decimal("0.93"),
    ),
    replace(
        POST_20260526_RULES[3],
        rule_id="SERVC_QUAL_POST_20260727_ATTACH_04",
        effective_date="2026-07-27",
        source="조달청 공고 제2026-390호 (2026-07-27 시행)",
        lwlt_rate=Decimal("89.995"),
        base_rate=Decimal("0.93"),
    ),
    *POST_20260526_RULES[4:],
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

# 2025-09-01 시행 개정 전 규칙 14종 (제2025-257호·제2026-15호).
# 하한율은 2025-09-01 이상 2026-05-26 미만 구간 공고의 실측 최빈값입니다.
PRE_20250901_RULES: tuple[EvaluationRule, ...] = (
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_01",
        service_type="FACILITY",
        table_name="시설분야용역 적격심사 (개정 전)",
        description="시설분야용역 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "시설분야용역 적격심사 추정가격 5억원 미만",
            "시설분야용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=1748,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_02",
        service_type="INSURANCE",
        table_name="보험용역 적격심사 (개정 전)",
        description="보험용역 적격심사 추정가격 5억원미만 / 5억원이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "보험용역 적격심사 추정가격 5억원미만",
            "보험용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("47.995"),
        base_rate=Decimal("0.88"),
        sample_count=845,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_03",
        service_type="PASSENGER_TRANSPORT",
        table_name="여객 육상운송용역 적격심사 (개정 전)",
        description="여객 육상운송용역 적격심사 추정가격 5억원미만 / 5억원이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "여객 육상운송용역 적격심사 추정가격 5억원미만",
            "여객 육상운송용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=1492,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_04",
        service_type="SW_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 (개정 전)",
        description="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=188,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_05",
        service_type="SW_NON_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 (개정 전)",
        description="소프트웨어용역(중소기업자간 경쟁제품 비대상) 고시금액미만 / 5억원 미만 고시금액이상 / 5억원 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만-추정가격 고시금액이상",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=138,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_06",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 미만, 개정 전)",
        description="학술연구용역 적격심사 추정가격 고시금액 미만",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "학술연구용역 적격심사 추정가격 고시금액 미만",
            "학술연구용역 적격심사 추정가격 고시금액미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=407,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_07",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 이상, 개정 전)",
        description="학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상 / 5억원 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "학술연구용역 적격심사 추정가격 5억원미만 고시금액이상",
            "학술연구용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=93,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_08",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 미만, 개정 전)",
        description="폐기물처리용역 적격심사 추정가격 고시금액미만",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 고시금액미만",
            "폐기물처리용역 적격심사 추정가격 고시금액 미만",
            "폐기물처리용역 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=491,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_09",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 이상, 개정 전)",
        description="폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원미만 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원이상",
            "폐기물처리용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=116,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_10",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 미만, 개정 전)",
        description="화물 육상운송용역 적격심사 추정가격 고시금액미만",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 고시금액미만",
            "화물 육상운송용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=111,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_11",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 이상, 개정 전)",
        description="화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "화물 육상운송용역 적격심사 추정가격 5억원이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=50,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_15",
        service_type="REPAIR_INSPECTION",
        table_name="수리ㆍ점검용역 적격심사 (개정 전 전용)",
        description="수리ㆍ점검용역 적격심사 고시금액 미만 / 5억원 미만 고시금액 이상 / 5억원 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "수리ㆍ점검용역 적격심사 고시금액 미만",
            "수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상",
            "수리ㆍ점검용역 적격심사 5억원 이상",
            "수리ㆍ점검용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=431,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_16",
        service_type="LEASE",
        table_name="임대차 적격심사 (개정 전 전용)",
        description="임대차 적격심사 추정가격 고시금액 미만 / 고시금액 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "임대차 적격심사 추정가격 고시금액 미만",
            "임대차 적격심사 추정가격 고시금액 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=299,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20250901_ATTACH_17",
        service_type="DEMAND_AGENCY",
        table_name="수요기관 지정형 적격심사 (개정 전 전용)",
        description="수요기관 지정형 적격심사 추정가격 고시금액 미만 / 고시금액 이상",
        effective_date="2025-09-01",
        source="조달청 일반용역 적격심사 세부기준 제2025-257호(시행 2025-09-01)·제2026-15호(시행 2026-03-01), 하한율 실측 최빈",
        patterns=(
            "수요기관 지정형 적격심사 추정가격 고시금액 미만",
            "수요기관 지정형 적격심사 추정가격 고시금액 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=195,
    ),
)

PRE_20250901_RULES = _with_score_table(PRE_20250901_RULES)

# 2023-05-01 시행 개정 전 규칙 14종 (제2023-53호).
# 별표 1·11 배점표는 제2025-257호와 다르지만, 규칙 레지스트리가 담는 식별 문자열·하한율·기준비율은
# 같아 같은 별표 범위를 한 벌로 표현합니다. 하한율은 2025-01-01 이상 2025-09-01 미만 구간 실측 최빈값입니다.
PRE_20230501_RULES: tuple[EvaluationRule, ...] = (
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_01",
        service_type="FACILITY",
        table_name="시설분야용역 적격심사 (개정 전)",
        description="시설분야용역 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "시설분야용역 적격심사 추정가격 5억원 미만",
            "시설분야용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=986,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_02",
        service_type="INSURANCE",
        table_name="보험용역 적격심사 (개정 전)",
        description="보험용역 적격심사 추정가격 5억원미만 / 5억원이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "보험용역 적격심사 추정가격 5억원미만",
            "보험용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("47.995"),
        base_rate=Decimal("0.88"),
        sample_count=625,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_03",
        service_type="PASSENGER_TRANSPORT",
        table_name="여객 육상운송용역 적격심사 (개정 전)",
        description="여객 육상운송용역 적격심사 추정가격 5억원미만 / 5억원이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "여객 육상운송용역 적격심사 추정가격 5억원미만",
            "여객 육상운송용역 적격심사 추정가격 5억원이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=1258,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_04",
        service_type="SW_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 (개정 전)",
        description="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만 / 5억원 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("87.995"),
        base_rate=Decimal("0.91"),
        sample_count=132,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_05",
        service_type="SW_NON_SME",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 (개정 전)",
        description="소프트웨어용역(중소기업자간 경쟁제품 비대상) 고시금액미만 / 5억원 미만 고시금액이상 / 5억원 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만-추정가격 고시금액이상",
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=69,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_06",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 미만, 개정 전)",
        description="학술연구용역 적격심사 추정가격 고시금액 미만",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "학술연구용역 적격심사 추정가격 고시금액 미만",
            "학술연구용역 적격심사 추정가격 고시금액미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=389,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_07",
        service_type="ACADEMIC",
        table_name="학술연구용역 적격심사 (고시금액 이상, 개정 전)",
        description="학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상 / 5억원 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "학술연구용역 적격심사 추정가격 5억원미만 고시금액이상",
            "학술연구용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=66,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_08",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 미만, 개정 전)",
        description="폐기물처리용역 적격심사 추정가격 고시금액미만",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 고시금액미만",
            "폐기물처리용역 적격심사 추정가격 고시금액 미만",
            "폐기물처리용역 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=429,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_09",
        service_type="WASTE",
        table_name="폐기물처리용역 적격심사 (고시금액 이상, 개정 전)",
        description="폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원미만 고시금액이상",
            "폐기물처리용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "폐기물처리용역 적격심사 추정가격 5억원이상",
            "폐기물처리용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=75,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_10",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 미만, 개정 전)",
        description="화물 육상운송용역 적격심사 추정가격 고시금액미만",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 고시금액미만",
            "화물 육상운송용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=69,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_11",
        service_type="FREIGHT",
        table_name="화물 육상운송용역 적격심사 (고시금액 이상, 개정 전)",
        description="화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 / 5억원이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 미만-추정가격 고시금액 이상",
            "화물 육상운송용역 적격심사 추정가격 5억원이상",
            "화물 육상운송용역 적격심사 추정가격 5억원 이상",
        ),
        lwlt_rate=Decimal("80.495"),
        base_rate=Decimal("0.88"),
        sample_count=57,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_15",
        service_type="REPAIR_INSPECTION",
        table_name="수리ㆍ점검용역 적격심사 (개정 전 전용)",
        description="수리ㆍ점검용역 적격심사 고시금액 미만 / 5억원 미만 고시금액 이상 / 5억원 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "수리ㆍ점검용역 적격심사 고시금액 미만",
            "수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상",
            "수리ㆍ점검용역 적격심사 5억원 이상",
            "수리ㆍ점검용역 적격심사 추정가격 고시금액 미만",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=265,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_16",
        service_type="LEASE",
        table_name="임대차 적격심사 (개정 전 전용)",
        description="임대차 적격심사 추정가격 고시금액 미만 / 고시금액 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "임대차 적격심사 추정가격 고시금액 미만",
            "임대차 적격심사 추정가격 고시금액 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=249,
    ),
    EvaluationRule(
        rule_id="SERVC_QUAL_PRE_20230501_ATTACH_17",
        service_type="DEMAND_AGENCY",
        table_name="수요기관 지정형 적격심사 (개정 전 전용)",
        description="수요기관 지정형 적격심사 추정가격 고시금액 미만 / 고시금액 이상",
        effective_date="2023-05-01",
        source="조달청 일반용역 적격심사 세부기준 제2023-53호(시행 2023-05-01), 하한율 실측 최빈",
        patterns=(
            "수요기관 지정형 적격심사 추정가격 고시금액 미만",
            "수요기관 지정형 적격심사 추정가격 고시금액 이상",
        ),
        lwlt_rate=Decimal("84.245"),
        base_rate=Decimal("0.88"),
        sample_count=159,
    ),
)

PRE_20230501_RULES = _with_score_table(PRE_20230501_RULES)

# 2026-05-26 개정 전 규칙 호환 별칭 (제2023-53호 + 제2025-257호·제2026-15호)
PRE_20260526_RULES: tuple[EvaluationRule, ...] = PRE_20230501_RULES + PRE_20250901_RULES

# 공고일 시행일 구간 경계 (내림차순). 공고일이 속한 구간의 벌로 계산합니다.
RULE_REGIME_BOUNDARIES: tuple[tuple[date, tuple[EvaluationRule, ...]], ...] = (
    (date(2026, 7, 27), POST_20260727_RULES),
    (date(2026, 5, 26), POST_20260526_RULES),
    (date(2025, 9, 1), PRE_20250901_RULES),
    (date(2023, 5, 1), PRE_20230501_RULES),
)


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


def _rules_for_announcement_date(announced: date | None) -> tuple[EvaluationRule, ...]:
    """공고일이 속한 시행일 구간의 규칙 벌을 고릅니다.

    공고일이 없으면 현행 벌인 제2026-390호 벌을 쓰고, 가장 이른 구간보다 앞선 공고일은
    가장 이른 개정 전 벌을 돌려주어 시행일 대조에서 차단되게 합니다.
    """
    if announced is None:
        return POST_20260727_RULES
    for start, rules in RULE_REGIME_BOUNDARIES:
        if announced >= start:
            return rules
    return PRE_20230501_RULES


def _allocate_rules_for_announcement(
    announced: date | None,
    method_name: str | None,
) -> tuple[EvaluationRule, ...]:
    """기본 호출의 규칙 벌을 공고일로 고르고, 개정 전 벌 미매칭 시 현행 벌과 대조합니다.

    제2026-260호 벌과 제2026-390호 벌은 그 자체가 개정 후 벌이므로 그대로 돌려줍니다.
    개정 전 구간 공고라도 현행 벌에만 있는 이름(개정 전 별표에 없는 일반 띠)은
    현행 별표로 매칭해 시행일 대조에서 기존과 같이 RULE_REGIME_MISMATCH 로 차단합니다.
    """
    regime_rules = _rules_for_announcement_date(announced)
    if (
        regime_rules is POST_20260526_RULES
        or regime_rules is POST_20260727_RULES
        or not method_name
    ):
        return regime_rules
    if match_rule_by_mthd_nm(method_name, rules=regime_rules) is not None:
        return regime_rules
    if match_rule_by_mthd_nm(method_name, rules=POST_20260727_RULES) is not None:
        return POST_20260727_RULES
    return regime_rules


def resolve_evaluation_rule(
    category: str | None,
    prearng_prce_dcsn_mthd_nm: str | None,
    sucsfbid_mthd_nm: str | None,
    sucsfbid_lwlt_rate: Decimal | str | float | None = None,
    tech_ablt_evl_rt: Decimal | str | float | None = None,
    bid_prce_evl_rt: Decimal | str | float | None = None,
    rules: Sequence[EvaluationRule] | None = None,
    srvce_div_nm: str | None = None,
    sucsfbid_mthd_cd: str | None = None,
    bid_ntce_dt: date | str | None = None,
) -> RuleResolutionResult:
    """낙찰방법 출처를 정하고 별표를 판별한 뒤 공고일과 별표 시행일을 대조합니다.

    [추가 판별]
    - 규칙 벌(rules)을 명시하지 않으면 공고일로 시행일 구간 벌을 고릅니다.
      공고일 2026-07-27 이상은 제2026-390호 벌, 2026-05-26 이상은 제2026-260호 벌,
      2025-09-01 이상은 제2025-257호 벌, 2023-05-01 이상은 제2023-53호 벌이며,
      공고일이 없으면 현행인 제2026-390호 벌을 씁니다.
      고른 벌에 이름이 없으면 현행 벌까지 대조하고, 어느 벌에도 없으면 RULE_NOT_FOUND 입니다.
    - 원문 낙찰방법이 '공고서참조'면 sucsfbidMthdCd 계열명으로 판별
    - 별표가 확정돼도 공고일이 별표 시행일보다 앞서면 계산 차단 (RULE_REGIME_MISMATCH).
      공고일이 없으면 대조하지 않고, 있는데 읽을 수 없으면 차단 대신 경고만 남깁니다.
    """
    method_name, method_source, method_warnings = resolve_method_name(
        sucsfbid_mthd_nm, sucsfbid_mthd_cd
    )
    announced = _parse_announcement_date(bid_ntce_dt)
    allocated_rules = (
        rules if rules is not None else _allocate_rules_for_announcement(announced, method_name)
    )
    result = _resolve_by_method_name(
        category=category,
        prearng_prce_dcsn_mthd_nm=prearng_prce_dcsn_mthd_nm,
        sucsfbid_mthd_nm=method_name,
        sucsfbid_lwlt_rate=sucsfbid_lwlt_rate,
        tech_ablt_evl_rt=tech_ablt_evl_rt,
        bid_prce_evl_rt=bid_prce_evl_rt,
        rules=allocated_rules,
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
                f"공고일({announced})이 별표 시행일({effective_date})보다 앞서 해당 별표로 "
                "계산하지 않습니다."
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
    rules: Sequence[EvaluationRule] | None = None,
) -> RuleResolutionResult:
    """raw_data 딕셔너리에서 기관 필드를 추출하여 적격심사 규칙을 판별합니다.

    rules 를 명시하지 않으면 bidNtceDt 로 고른 시행일 구간 벌로 판별합니다.
    """
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


# =============================================================================
# 정량평가 심사항목 배점한도 (조달청 일반용역 적격심사 별표 1~9 원문 구조)
# =============================================================================
#
# 근거 문서: docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md
#   - 별표 1~9 심사항목 배점한도: 48-136행
#   - 별표 10 경영상태(신용평가등급) 점수표: 187-198행
#   - 별표 11 신인도 가점·감점 항목표: 204-231행
#
# 각 항목은 (심사분야 번호, 항목명, 배점한도)를 함께 가지며, 추정가격 5억원 이상/미만
# 구간이 다르면 구간(band)별로 값을 갖습니다. 결격사유(-20)는 감점 항목이라 합계 100
# 정합성에서 제외하고 limit_kind="disqualification" 으로 구분합니다. 신인도는 가점 상한
# 4.25 와 감점 상한 -5.0 을 함께 갖습니다. 추측 금지 원칙에 따라 원문 표에 없는 값은
# limit=None(limit_kind="absent")으로 두고, 그 사실을 항목명과 사유에 남깁니다.

# 배점표에 없는 항목("-")은 배점한도 None 과 kind="absent" 로 표현합니다.
QUANT_LIMIT_KIND_SCORE = "score"
QUANT_LIMIT_KIND_ABSENT = "absent"
QUANT_LIMIT_KIND_RANGE = "range"
QUANT_LIMIT_KIND_CREDIT_GRADE = "credit_grade"
QUANT_LIMIT_KIND_REPUTATION = "reputation"
QUANT_LIMIT_KIND_PRICE = "price"
QUANT_LIMIT_KIND_DISQUALIFICATION = "disqualification"

# 입력 항목 식별자. 화면 입력란과 서버 검증이 공유하는 안정 키입니다.
QUANT_ITEM_PERFORMANCE = "performance"
QUANT_ITEM_MANAGEMENT = "management"
QUANT_ITEM_TECHNICAL = "technical_capacity"
QUANT_ITEM_TECHNICAL_INPUT = "technical_input"
QUANT_ITEM_TECHNICAL_CREDIT = "technical_credit"
QUANT_ITEM_LABOR_PLAN = "labor_plan"
QUANT_ITEM_REPUTATION = "reputation"
QUANT_ITEM_INSURANCE_ABILITY = "insurance_payment_ability"
QUANT_ITEM_AFTER_SERVICE = "after_service"
QUANT_ITEM_OTHER_PERFORMANCE = "other_performance"
QUANT_ITEM_PRICE = "price"
QUANT_ITEM_DISQUALIFICATION = "disqualification"

QUANT_BAND_OVER_500M = "over_500m"
QUANT_BAND_UNDER_500M = "under_500m"
QUANT_BAND_SINGLE = "single"

QUANT_BAND_LABELS: dict[str, str] = {
    QUANT_BAND_OVER_500M: "추정가격 5억원 이상",
    QUANT_BAND_UNDER_500M: "추정가격 5억원 미만",
    QUANT_BAND_SINGLE: "단일 구간",
}

QUANT_ESTIMATED_PRICE_THRESHOLD = Decimal("500000000")

_QUANT_SRC_ATTACH = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:48-136"
_QUANT_SRC_CREDIT = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:187-198"
_QUANT_SRC_REPUTATION = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:204-231"
_QUANT_SRC_BKT = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:152-179"

_QUANT_NOTE_ABSENT = "원문 배점표에 '-' 로 표기되어 입력할 수 없는 항목입니다."
_QUANT_NOTE_RANGE = "원문이 범위(예: 10점 이상 30점 이하)로 표기한 항목입니다."

# 심사분야 번호는 원문 표기를 그대로 씁니다(로마 숫자 I, II, III, IV). 표기 문자를
# 유니코드 이스케이프로 선언해 소스에는 ASCII 로 남깁니다.
QUANT_SECTION_1 = "\u2160"
QUANT_SECTION_2 = "\u2161"
QUANT_SECTION_3 = "\u2162"
QUANT_SECTION_4 = "\u2163"


@dataclass(frozen=True)
class QuantScoreItem:
    """별표 심사항목 한 줄. (심사분야 번호, 항목명, 배점한도)를 함께 갖습니다.

    limit_kind 는 입력 방식과 합계 포함 여부를 정합니다. limit 이 None 이면(absent)
    원문 배점표에 없는 항목이라 입력을 막습니다. limit_min 은 범위 하한(신인도 감점
    상한, 별표 9 범위 하한)입니다.
    """

    section_no: str
    section_name: str
    item_key: str
    item_name: str
    limit: Decimal | None
    limit_kind: str
    source: str
    limit_min: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class QuantScoreBand:
    """추정가격 구간 하나의 심사항목 배점한도 묶음."""

    band_key: str
    band_label: str
    items: tuple[QuantScoreItem, ...]
    total_limit: Decimal


@dataclass(frozen=True)
class QuantScoreTable:
    """한 별표의 심사항목 배점한도. 구간(5억원 이상/미만)별 값을 함께 갖습니다."""

    attachment: str
    table_name: str
    source: str
    bands: tuple[QuantScoreBand, ...]
    note: str | None = None


def _qi(
    section_no: str,
    section_name: str,
    item_key: str,
    item_name: str,
    limit: Decimal | None,
    *,
    kind: str = QUANT_LIMIT_KIND_SCORE,
    section_name_override: str | None = None,
    limit_min: Decimal | None = None,
    note: str | None = None,
    source: str = _QUANT_SRC_ATTACH,
) -> QuantScoreItem:
    """심사항목 한 줄을 만듭니다. 항목명과 배점한도, 근거 경로를 함께 남깁니다."""
    return QuantScoreItem(
        section_no=section_no,
        section_name=section_name_override or section_name,
        item_key=item_key,
        item_name=item_name,
        limit=limit,
        limit_kind=kind,
        source=source,
        limit_min=limit_min,
        note=note,
    )


def _reputation_item(section_no: str, section_name: str) -> QuantScoreItem:
    """신인도 항목. 가점 상한 4.25 와 감점 상한 -5.0 을 함께 갖습니다."""
    return _qi(
        section_no,
        section_name,
        QUANT_ITEM_REPUTATION,
        "신인도",
        Decimal("4.25"),
        kind=QUANT_LIMIT_KIND_REPUTATION,
        limit_min=Decimal("-5"),
        source=_QUANT_SRC_REPUTATION,
    )


def _price_item(
    section_no: str, limit: Decimal, *, kind: str = QUANT_LIMIT_KIND_PRICE
) -> QuantScoreItem:
    return _qi(
        section_no,
        "입찰가격",
        QUANT_ITEM_PRICE,
        "입찰가격",
        limit,
        kind=kind,
        source=_QUANT_SRC_BKT,
    )


def _disqualification_item(section_no: str) -> QuantScoreItem:
    """결격사유 -20. 감점 항목이라 합계 100 정합성에서 제외합니다."""
    return _qi(
        section_no,
        "결격사유",
        QUANT_ITEM_DISQUALIFICATION,
        "결격사유",
        Decimal("-20"),
        kind=QUANT_LIMIT_KIND_DISQUALIFICATION,
    )


def _performance_section(
    section_no: str,
    *,
    performance: Decimal | None,
    management: Decimal,
    technical: tuple[tuple[str, str, Decimal | None], ...] = (),
    management_kind: str = QUANT_LIMIT_KIND_CREDIT_GRADE,
) -> tuple[QuantScoreItem, ...]:
    """별표 1~5의2, 7 의 심사분야 I. 해당용역 수행능력 항목 묶음을 만듭니다."""
    items: list[QuantScoreItem] = [
        _qi(
            section_no,
            "해당용역 수행능력",
            QUANT_ITEM_PERFORMANCE,
            "이행실적",
            performance,
            kind=QUANT_LIMIT_KIND_SCORE if performance is not None else QUANT_LIMIT_KIND_ABSENT,
            note=None if performance is not None else _QUANT_NOTE_ABSENT,
        ),
        _qi(
            section_no,
            "해당용역 수행능력",
            QUANT_ITEM_MANAGEMENT,
            "경영상태(신용평가등급)",
            management,
            kind=management_kind,
        ),
    ]
    for key, name, limit in technical:
        items.append(
            _qi(
                section_no,
                "해당용역 수행능력",
                key,
                name,
                limit,
                kind=QUANT_LIMIT_KIND_SCORE if limit is not None else QUANT_LIMIT_KIND_ABSENT,
                note=None if limit is not None else _QUANT_NOTE_ABSENT,
            )
        )
    items.append(_reputation_item(section_no, "해당용역 수행능력"))
    return tuple(items)


def _band(
    band_key: str,
    *groups: tuple[QuantScoreItem, ...],
    total_limit: Decimal = Decimal("100"),
) -> QuantScoreBand:
    """구간 하나를 만듭니다. 심사분야별 항목 묶음을 순서대로 이어 붙입니다."""
    items = tuple(item for group in groups for item in group)
    return QuantScoreBand(
        band_key=band_key,
        band_label=QUANT_BAND_LABELS[band_key],
        items=items,
        total_limit=total_limit,
    )


def _labor_item(section_no: str) -> QuantScoreItem:
    return _qi(
        section_no,
        "근로조건 이행계획의 적정성",
        QUANT_ITEM_LABOR_PLAN,
        "근로조건 이행계획의 적정성",
        Decimal("10"),
    )


def _attachment_1_table() -> QuantScoreTable:
    """별표 1 학술연구. 5억원 이상 40 + 입찰가격 60, 미만 30 + 70."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("20"),
            management=Decimal("10"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(기술인력 보유)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("10"),
            management=Decimal("20"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(기술인력 보유)", None),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 1",
        table_name="학술연구용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_2_table() -> QuantScoreTable:
    """별표 2 시설분야. 근로조건 이행계획이 별도 심사번호인 유일한 별표."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(QUANT_SECTION_1, performance=Decimal("20"), management=Decimal("10")),
        (
            _labor_item(QUANT_SECTION_2),
            _price_item(QUANT_SECTION_3, Decimal("60")),
            _disqualification_item(QUANT_SECTION_4),
        ),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(QUANT_SECTION_1, performance=None, management=Decimal("20")),
        (
            _labor_item(QUANT_SECTION_2),
            _price_item(QUANT_SECTION_3, Decimal("70")),
            _disqualification_item(QUANT_SECTION_4),
        ),
    )
    return QuantScoreTable(
        attachment="별표 2",
        table_name="시설분야용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_3_table() -> QuantScoreTable:
    """별표 3 SW(비대상). 5억원 미만은 이행실적이 '-' 이고 기술능력 10 은 유지됩니다."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("20"),
            management=Decimal("10"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(기술인력 보유 상황)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=None,
            management=Decimal("20"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(기술인력 보유 상황)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 3",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_3_2_table() -> QuantScoreTable:
    """별표 3의2 SW(대상). 배점 구성은 별표 3 과 같습니다."""
    table = _attachment_3_table()
    return QuantScoreTable(
        attachment="별표 3의2",
        table_name="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사",
        source=table.source,
        bands=table.bands,
    )


def _attachment_4_table() -> QuantScoreTable:
    """별표 4 폐기물처리. 기술능력이 가. 기술인력 보유상황 9 + 나. 기술 보유상황 1 입니다."""
    technical = (
        (QUANT_ITEM_TECHNICAL, "기술능력 가. 기술인력 보유상황", Decimal("9")),
        (QUANT_ITEM_TECHNICAL_INPUT, "기술능력 나. 기술 보유상황", Decimal("1")),
    )
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("20"),
            management=Decimal("10"),
            technical=technical,
        ),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("10"),
            management=Decimal("10"),
            technical=technical,
        ),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 4",
        table_name="폐기물처리용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_5_table() -> QuantScoreTable:
    """별표 5 여객 육상운송. 기술능력은 안전성 정도 10."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("20"),
            management=Decimal("10"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(안전성 정도)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("10"),
            management=Decimal("10"),
            technical=((QUANT_ITEM_TECHNICAL, "기술능력(안전성 정도)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 5",
        table_name="여객 육상운송용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_5_2_table() -> QuantScoreTable:
    """별표 5의2 화물 육상운송. 경영상태가 20점이고 기술능력 항목이 없습니다."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(QUANT_SECTION_1, performance=Decimal("20"), management=Decimal("20")),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(QUANT_SECTION_1, performance=Decimal("10"), management=Decimal("20")),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 5의2",
        table_name="화물 육상운송용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_6_table() -> QuantScoreTable:
    """별표 6 보험. 보험금 지급능력이 심사분야 I 항목 전체입니다."""
    over = _band(
        QUANT_BAND_OVER_500M,
        (
            _qi(
                QUANT_SECTION_1,
                "해당용역 수행능력",
                QUANT_ITEM_INSURANCE_ABILITY,
                "보험금 지급능력(지급여력비율)",
                Decimal("40"),
            ),
            _reputation_item(QUANT_SECTION_1, "해당용역 수행능력"),
            _price_item(QUANT_SECTION_2, Decimal("60")),
            _disqualification_item(QUANT_SECTION_3),
        ),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        (
            _qi(
                QUANT_SECTION_1,
                "해당용역 수행능력",
                QUANT_ITEM_INSURANCE_ABILITY,
                "보험금 지급능력(지급여력비율)",
                Decimal("30"),
            ),
            _reputation_item(QUANT_SECTION_1, "해당용역 수행능력"),
            _price_item(QUANT_SECTION_2, Decimal("70")),
            _disqualification_item(QUANT_SECTION_3),
        ),
    )
    return QuantScoreTable(
        attachment="별표 6",
        table_name="보험용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_7_table() -> QuantScoreTable:
    """별표 7 수리·점검. 기술능력은 기술신용평가등급이며 미만 구간은 0점입니다."""
    over = _band(
        QUANT_BAND_OVER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("20"),
            management=Decimal("10"),
            technical=((QUANT_ITEM_TECHNICAL_CREDIT, "기술능력(기술신용평가등급)", Decimal("10")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("60")), _disqualification_item(QUANT_SECTION_3)),
    )
    under = _band(
        QUANT_BAND_UNDER_500M,
        _performance_section(
            QUANT_SECTION_1,
            performance=Decimal("10"),
            management=Decimal("20"),
            technical=((QUANT_ITEM_TECHNICAL_CREDIT, "기술능력(기술신용평가등급)", Decimal("0")),),
        ),
        (_price_item(QUANT_SECTION_2, Decimal("70")), _disqualification_item(QUANT_SECTION_3)),
    )
    return QuantScoreTable(
        attachment="별표 7",
        table_name="수리ㆍ점검용역 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(over, under),
    )


def _attachment_8_table() -> QuantScoreTable:
    """별표 8 임대차. 이행실적·기술능력 없이 경영상태와 사후관리만 봅니다."""
    return QuantScoreTable(
        attachment="별표 8",
        table_name="임대차 적격심사",
        source=_QUANT_SRC_ATTACH,
        bands=(
            _band(
                QUANT_BAND_SINGLE,
                (
                    _qi(
                        QUANT_SECTION_1,
                        "해당용역 수행능력",
                        QUANT_ITEM_MANAGEMENT,
                        "경영상태(신용평가등급)",
                        Decimal("20"),
                        kind=QUANT_LIMIT_KIND_CREDIT_GRADE,
                    ),
                    _qi(
                        QUANT_SECTION_1,
                        "해당용역 수행능력",
                        QUANT_ITEM_AFTER_SERVICE,
                        "사후관리(A/S)",
                        Decimal("10"),
                    ),
                    _reputation_item(QUANT_SECTION_1, "해당용역 수행능력"),
                    _price_item(QUANT_SECTION_2, Decimal("70")),
                    _disqualification_item(QUANT_SECTION_3),
                ),
            ),
        ),
    )


def _attachment_9_table() -> QuantScoreTable:
    """별표 9 수요기관 지정형. 기본평가·선택평가와 입찰가격 60~70 범위 구조입니다.

    원문이 범위로 표기하므로 limit 은 상한, limit_min 은 하한입니다. 합계 100 은
    범위 안에서 수요기관이 정하므로 별표 1~5의2 처럼 고정 합계로 검증하지 않습니다.
    """
    return QuantScoreTable(
        attachment="별표 9",
        table_name="수요기관 지정형 적격심사",
        source=_QUANT_SRC_ATTACH,
        note=_QUANT_NOTE_RANGE,
        bands=(
            _band(
                QUANT_BAND_SINGLE,
                (
                    _qi(
                        QUANT_SECTION_1,
                        "해당용역 수행능력 기본평가항목",
                        QUANT_ITEM_MANAGEMENT,
                        "경영상태(신용평가등급)",
                        Decimal("30"),
                        kind=QUANT_LIMIT_KIND_CREDIT_GRADE,
                        limit_min=Decimal("10"),
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _reputation_item(QUANT_SECTION_1, "해당용역 수행능력 기본평가항목"),
                    _qi(
                        "선택평가항목",
                        "선택평가항목",
                        QUANT_ITEM_PERFORMANCE,
                        "이행실적",
                        Decimal("30"),
                        kind=QUANT_LIMIT_KIND_RANGE,
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _qi(
                        "선택평가항목",
                        "선택평가항목",
                        QUANT_ITEM_TECHNICAL,
                        "기술능력 가. 기술인력 보유상황",
                        Decimal("10"),
                        kind=QUANT_LIMIT_KIND_RANGE,
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _qi(
                        "선택평가항목",
                        "선택평가항목",
                        QUANT_ITEM_TECHNICAL_CREDIT,
                        "기술능력 나. 기술신용평가등급",
                        Decimal("10"),
                        kind=QUANT_LIMIT_KIND_RANGE,
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _qi(
                        "선택평가항목",
                        "선택평가항목",
                        QUANT_ITEM_AFTER_SERVICE,
                        "사후관리(A/S)",
                        Decimal("10"),
                        kind=QUANT_LIMIT_KIND_RANGE,
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _qi(
                        "선택평가항목",
                        "선택평가항목",
                        QUANT_ITEM_OTHER_PERFORMANCE,
                        "기타 수행능력",
                        Decimal("5"),
                        kind=QUANT_LIMIT_KIND_RANGE,
                        note=_QUANT_NOTE_RANGE,
                    ),
                    _price_item(QUANT_SECTION_2, Decimal("70"), kind=QUANT_LIMIT_KIND_RANGE),
                    _disqualification_item(QUANT_SECTION_3),
                ),
            ),
        ),
    )


def _under_only(
    table: QuantScoreTable, *, attachment: str, table_name: str, note: str
) -> QuantScoreTable:
    """고시금액 미만 구간에만 존재하는 규칙의 배점표. 5억원 미만 구간 하나만 남깁니다.

    고시금액(용역 2.3억원)이 5억원 미만이므로 고시금액 미만 규칙은 항상 미만 구간입니다.
    """
    bands = tuple(band for band in table.bands if band.band_key == QUANT_BAND_UNDER_500M)
    return QuantScoreTable(
        attachment=attachment,
        table_name=table_name,
        source=table.source,
        bands=bands,
        note=note,
    )


_QUANT_NOTE_UNDER_ONLY = "고시금액(용역 2.3억원) 미만 구간 전용이라 5억원 미만 배점만 적용합니다."

# 규칙 ID 접미사(ATTACH_NN)로 별표 배점표를 찾습니다. 일반 띠(ATTACH_12~14)는 원문
# 별표 1~9 에 같은 이름이 없어 별표 귀속이 미확인이라 표를 선언하지 않습니다.
QUANT_SCORE_TABLES: dict[str, QuantScoreTable] = {
    "ATTACH_01": _attachment_2_table(),
    "ATTACH_02": _attachment_6_table(),
    "ATTACH_03": _attachment_5_table(),
    "ATTACH_04": _attachment_3_2_table(),
    "ATTACH_05": _attachment_3_table(),
    "ATTACH_06": _under_only(
        _attachment_1_table(),
        attachment="별표 1",
        table_name="학술연구용역 적격심사 (고시금액 미만)",
        note=_QUANT_NOTE_UNDER_ONLY,
    ),
    "ATTACH_07": _attachment_1_table(),
    "ATTACH_08": _under_only(
        _attachment_4_table(),
        attachment="별표 4",
        table_name="폐기물처리용역 적격심사 (고시금액 미만)",
        note=_QUANT_NOTE_UNDER_ONLY,
    ),
    "ATTACH_09": _attachment_4_table(),
    "ATTACH_10": _under_only(
        _attachment_5_2_table(),
        attachment="별표 5의2",
        table_name="화물 육상운송용역 적격심사 (고시금액 미만)",
        note=_QUANT_NOTE_UNDER_ONLY,
    ),
    "ATTACH_11": _attachment_5_2_table(),
    "ATTACH_15": _attachment_7_table(),
    "ATTACH_16": _attachment_8_table(),
    "ATTACH_17": _attachment_9_table(),
}


def quant_score_table_for_rule(rule: EvaluationRule) -> QuantScoreTable | None:
    """규칙이 어느 별표인지에 따라 정량평가 배점표를 돌려줍니다.

    별표 귀속이 미확인인 규칙(일반 띠)은 표를 만들지 않고 None 을 돌려줍니다.
    """
    suffix = "_".join(rule.rule_id.rsplit("_", 2)[-2:])
    return QUANT_SCORE_TABLES.get(suffix)


def select_quant_band(
    table: QuantScoreTable,
    estimated_price: Decimal | int | float | str | None,
) -> tuple[QuantScoreBand | None, str | None]:
    """추정가격으로 5억원 이상/미만 구간을 고릅니다.

    구간이 하나면 추정가격과 무관하게 그 구간을 쓰고, 구간이 둘인데 추정가격을 읽을
    수 없으면 임의로 고르지 않고 사유와 함께 None 을 돌려줍니다.
    """
    if len(table.bands) == 1:
        return table.bands[0], None
    if estimated_price is None:
        return None, "추정가격이 없어 5억원 이상/미만 구간을 확정할 수 없습니다."
    try:
        price = Decimal(str(estimated_price))
    except (ArithmeticError, TypeError, ValueError):
        return None, "추정가격을 숫자로 읽을 수 없어 5억원 이상/미만 구간을 확정할 수 없습니다."
    band_key = (
        QUANT_BAND_OVER_500M if price >= QUANT_ESTIMATED_PRICE_THRESHOLD else QUANT_BAND_UNDER_500M
    )
    for band in table.bands:
        if band.band_key == band_key:
            return band, None
    return None, "추정가격 구간에 대응하는 배점표 구간이 없습니다."


# -----------------------------------------------------------------------------
# 별표 10 경영상태(신용평가등급) 점수표
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CreditGradeScore:
    """별표 10 신용평가등급 한 줄. 배점한도 20점 기준과 10점 기준을 함께 갖습니다."""

    grade_group: str
    grade_codes: tuple[str, ...]
    score_at_20: Decimal
    score_at_10: Decimal
    source: str = _QUANT_SRC_CREDIT


CREDIT_GRADE_SCORES: tuple[CreditGradeScore, ...] = (
    CreditGradeScore(
        "AAA ~ A-",
        ("AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-"),
        Decimal("20"),
        Decimal("10"),
    ),
    CreditGradeScore("BBB+", ("BBB+",), Decimal("19.8"), Decimal("9.8")),
    CreditGradeScore("BBB0", ("BBB0", "BBB"), Decimal("19.6"), Decimal("9.6")),
    CreditGradeScore("BBB-", ("BBB-",), Decimal("19.4"), Decimal("9.4")),
    CreditGradeScore("BB+ ~ BB0", ("BB+", "BB0", "BB"), Decimal("19.2"), Decimal("9.2")),
    CreditGradeScore("BB-", ("BB-",), Decimal("19.0"), Decimal("9.0")),
    CreditGradeScore("B+ ~ B-", ("B+", "B0", "B-"), Decimal("18.8"), Decimal("8.8")),
    CreditGradeScore("CCC+ 이하", ("CCC+", "CCC", "CC", "C", "D"), Decimal("16.0"), Decimal("7.0")),
)


def _normalize_grade(text: str) -> str:
    """신용평가등급 비교용 정규화. 공백·물결·하이픈을 제거하고 대문자로 맞춥니다."""
    return re.sub(r"[\s~\-]", "", text).upper()


def find_credit_grade(text: str | None) -> CreditGradeScore | None:
    """입력한 신용평가등급 표기를 별표 10 등급군으로 정규화합니다. 없으면 None."""
    if not text:
        return None
    target = _normalize_grade(text)
    for grade in CREDIT_GRADE_SCORES:
        if target == _normalize_grade(grade.grade_group):
            return grade
        if any(target == _normalize_grade(code) for code in grade.grade_codes):
            return grade
    return None


def credit_score_for_grade(text: str | None, limit: Decimal) -> Decimal | None:
    """신용평가등급과 배점한도 기준으로 별표 10 점수를 돌려줍니다.

    배점한도 20점 기준과 10점 기준을 구분합니다. 등급을 해석하지 못하면 None 입니다.
    """
    grade = find_credit_grade(text)
    if grade is None:
        return None
    return grade.score_at_20 if limit >= Decimal("20") else grade.score_at_10


# -----------------------------------------------------------------------------
# 별표 9 수요기관 지정형 경영상태 상대 감점
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DemandAgencyCreditDeduction:
    """별표 9 전용 경영상태. 배점한도(만점) 기준 상대 감점입니다."""

    grade_group: str
    deduction: Decimal
    source: str = _QUANT_SRC_CREDIT


DEMAND_AGENCY_CREDIT_DEDUCTIONS: tuple[DemandAgencyCreditDeduction, ...] = (
    DemandAgencyCreditDeduction("AAA ~ A-", Decimal("0")),
    DemandAgencyCreditDeduction("BBB+", Decimal("0.2")),
    DemandAgencyCreditDeduction("BBB0", Decimal("0.4")),
    DemandAgencyCreditDeduction("BBB-", Decimal("0.6")),
    DemandAgencyCreditDeduction("BB+ ~ BB0", Decimal("0.8")),
    DemandAgencyCreditDeduction("BB-", Decimal("1.0")),
    DemandAgencyCreditDeduction("B+ ~ B-", Decimal("1.2")),
    DemandAgencyCreditDeduction("CCC+ 이하", Decimal("5.0")),
)


def demand_agency_credit_deduction(text: str | None) -> Decimal | None:
    """별표 9 경영상태 상대 감점. 등급을 해석하지 못하면 None."""
    grade = find_credit_grade(text)
    if grade is None:
        return None
    for row in DEMAND_AGENCY_CREDIT_DEDUCTIONS:
        if row.grade_group == grade.grade_group:
            return row.deduction
    return None


# -----------------------------------------------------------------------------
# 별표 11 신인도 가점·감점 항목
# -----------------------------------------------------------------------------

REPUTATION_OPTION_CHOICE = "choice"
REPUTATION_OPTION_RANGE = "range"

REPUTATION_MAX_BONUS = Decimal("4.25")
REPUTATION_MAX_PENALTY = Decimal("-5.0")
REPUTATION_INDUSTRIAL_ACCIDENT_MAX_BONUS = Decimal("3.0")
REPUTATION_ITEM_INDUSTRIAL_ACCIDENT = "industrial_accident"


@dataclass(frozen=True)
class ReputationItem:
    """별표 11 신인도 항목 한 줄.

    option_kind="choice" 면 options 가 선택 가능한 평점 목록이고, "range" 면
    options 가 (하한, 상한) 입니다. 감점 항목은 음수입니다.
    """

    item_code: str
    item_name: str
    option_kind: str
    options: tuple[Decimal, ...]
    source: str = _QUANT_SRC_REPUTATION
    note: str | None = None


REPUTATION_ITEMS: tuple[ReputationItem, ...] = (
    ReputationItem(
        "sme_support",
        "가. 중소기업 ① 중소기업 지원",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.5"), Decimal("1.0")),
    ),
    ReputationItem(
        "sme_consortium",
        "가. 중소기업 ② 공동수급체 구성 지원",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.0"), Decimal("0.5"), Decimal("1.5"), Decimal("0.75")),
    ),
    ReputationItem(
        "woman_company",
        "나. 약자기업 ① 여성기업 지원",
        REPUTATION_OPTION_CHOICE,
        (Decimal("0.75"), Decimal("0.5"), Decimal("0.25")),
    ),
    ReputationItem(
        "disabled_company",
        "나. 약자기업 ② 장애인기업 지원",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.5"),),
    ),
    ReputationItem(
        "job_creation",
        "다. 고용창출 ① 일자리창출 우수기업",
        REPUTATION_OPTION_RANGE,
        (Decimal("1.0"), Decimal("3.0")),
    ),
    ReputationItem(
        "youth_employment",
        "다. 고용창출 ② 청년고용 우수기업",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.75"), Decimal("1.5"), Decimal("1.0")),
    ),
    ReputationItem(
        "woman_employment",
        "다. 고용창출 ③ 여성고용 우수기업",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.75"), Decimal("1.5"), Decimal("1.0"), Decimal("2.0")),
    ),
    ReputationItem(
        "disabled_employment",
        "다. 고용창출 ④ 장애인고용 우수기업",
        REPUTATION_OPTION_CHOICE,
        (Decimal("2.0"), Decimal("1.5")),
    ),
    ReputationItem(
        "employment_type_a",
        "다. 고용창출 ⑤ 고용형태 등에 따른 지원 A",
        REPUTATION_OPTION_CHOICE,
        (Decimal("2.0"), Decimal("1.5"), Decimal("1.0"), Decimal("0.5"), Decimal("0")),
    ),
    ReputationItem(
        "employment_type_b",
        "다. 고용창출 ⑤ 고용형태 등에 따른 지원 B(정규직 전환)",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.5"),),
    ),
    ReputationItem(
        "employment_stability",
        "다. 고용창출 ⑥ 고용안정 우수기업",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.5"), Decimal("1.25"), Decimal("1.0")),
    ),
    ReputationItem("low_birth", "라. 저출생 대응", REPUTATION_OPTION_CHOICE, (Decimal("2.0"),)),
    ReputationItem(
        "policy_support", "마. 정책지원", REPUTATION_OPTION_RANGE, (Decimal("0"), Decimal("2.0"))
    ),
    ReputationItem(
        "delayed_delivery",
        "바. 불공정 계약행위 ① 납품지연",
        REPUTATION_OPTION_RANGE,
        (Decimal("-2.0"), Decimal("-0.25")),
    ),
    ReputationItem(
        "unfair_subcontract",
        "바. 불공정 계약행위 ② 불공정 하도급거래",
        REPUTATION_OPTION_CHOICE,
        (Decimal("-1.0"), Decimal("-2.0")),
    ),
    ReputationItem(
        "waste_mishandling",
        "바. 불공정 계약행위 ③ 폐기물부적정 처리",
        REPUTATION_OPTION_CHOICE,
        (Decimal("-1.0"), Decimal("-2.0"), Decimal("-3.0")),
    ),
    ReputationItem(
        "wage_arrears",
        "고용 관련 법령 위반 ① 체불사업주",
        REPUTATION_OPTION_CHOICE,
        (Decimal("-2.0"),),
    ),
    ReputationItem(
        "employment_improvement",
        "고용 관련 법령 위반 ② 고용개선조치 미이행",
        REPUTATION_OPTION_CHOICE,
        (Decimal("-2.0"),),
    ),
    ReputationItem(
        REPUTATION_ITEM_INDUSTRIAL_ACCIDENT,
        "산업안전 ① 산업재해발생",
        REPUTATION_OPTION_CHOICE,
        (Decimal("-3.0"),),
    ),
    ReputationItem(
        "safety_health",
        "산업안전 ② 안전보건(KOSHA-MS 인증)",
        REPUTATION_OPTION_CHOICE,
        (Decimal("1.0"),),
    ),
)

REPUTATION_ITEMS_BY_CODE: dict[str, ReputationItem] = {
    item.item_code: item for item in REPUTATION_ITEMS
}


def find_reputation_item(item_code: str) -> ReputationItem | None:
    return REPUTATION_ITEMS_BY_CODE.get(item_code)
