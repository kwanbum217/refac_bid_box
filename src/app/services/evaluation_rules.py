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

from src.ml.notice_amount import notice_amount_for_year

RULE_SCOPE_ALL = "ALL"
RULE_SCOPE_INSTITUTION = "INSTITUTION"
RULE_SCOPE_REGION = "REGION"
RULE_SCOPE_VALUES = frozenset({RULE_SCOPE_ALL, RULE_SCOPE_INSTITUTION, RULE_SCOPE_REGION})

QUANT_BASIS_REGISTRY = "REGISTRY"
QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED = "AGENCY_DOCUMENT_NOT_LOADED"


@dataclass(frozen=True)
class PriceBand:
    """입찰가격 평점(B·k) 구간 하나.

    upper_bound 는 이 구간의 추정가격 상한(원)이며 이 값 **미만**이 이 구간에 들어갑니다.
    원문 표기가 "10억원 미만 5억원 이상"이면 upper_bound=10억, "5억원 미만 2억원 이상"이면
    5억이므로, 경계값은 상위 구간(이상 쪽)에 속합니다. None 은 상한 없음(마지막 구간)입니다.
    """

    upper_bound: Decimal | None
    max_price_score: Decimal
    multiplier: Decimal
    base_rate: Decimal | None = None
    flat_score: Decimal | None = None
    label: str = ""
    source: str | None = None
    # 이 구간에 인쇄된 낙찰하한율(%). 원문이 구간마다 다른 하한율을 인쇄한 별표만 값을
    # 가지며, None 이면 규칙 대표값(EvaluationRule.lwlt_rate)을 씁니다. 공고 하한율이
    # 있으면 언제나 공고값이 우선입니다.
    lwlt_rate: Decimal | None = None


@dataclass(frozen=True)
class ThresholdBand:
    """통과점수(T) 구간 하나. 경계가 PriceBand 와 다를 수 있습니다."""

    upper_bound: Decimal | None
    pass_threshold: Decimal
    label: str = ""
    source: str | None = None


def _validate_bands(bands: Sequence[Any], *, axis: str) -> None:
    open_upper = 0
    previous: Decimal | None = None
    for band in bands:
        if band.upper_bound is None:
            open_upper += 1
            continue
        if previous is not None and band.upper_bound <= previous:
            raise ValueError(f"{axis} 구간이 추정가격 오름차순이 아닙니다.")
        previous = band.upper_bound
    if open_upper > 1:
        raise ValueError(f"{axis} 구간에서 상한 없는 구간은 마지막 하나만 허용합니다.")
    if bands and bands[-1].upper_bound is not None:
        raise ValueError(f"{axis} 구간의 마지막은 상한 없는 구간이어야 합니다.")


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
    max_price_score_by_500m: tuple[Decimal, Decimal] | None = None
    multiplier_by_notice: tuple[Decimal, Decimal] | None = None
    pass_threshold: Decimal | None = None
    # 시·도 자체 별표처럼 추정가격 3~4구간으로 B·k·T 가 갈리는 규칙은 위 단일·2구간 필드 대신
    # 아래 두 구간 목록으로 표현합니다. 기존 규칙은 모두 None 이라 기존 경로가 그대로 유지됩니다.
    price_bands: tuple[PriceBand, ...] | None = None
    threshold_bands: tuple[ThresholdBand, ...] | None = None
    quant_basis: str = QUANT_BASIS_REGISTRY
    score_table_source: str | None = None
    contract_regime: str | None = None
    institution_scope: str = RULE_SCOPE_ALL
    institution_code: str | None = None
    institution_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None

    def __post_init__(self) -> None:
        if self.max_price_score is not None and self.max_price_score_by_500m is not None:
            raise ValueError("B 단일값과 추정가격 조건부 값은 동시에 선언할 수 없습니다.")
        if self.multiplier is not None and self.multiplier_by_notice is not None:
            raise ValueError("k 단일값과 고시금액 조건부 값은 동시에 선언할 수 없습니다.")
        if self.price_bands is not None:
            if any(
                value is not None
                for value in (
                    self.max_price_score,
                    self.max_price_score_by_500m,
                    self.multiplier,
                    self.multiplier_by_notice,
                )
            ):
                raise ValueError("price_bands 와 기존 B·k 필드는 동시에 선언할 수 없습니다.")
            if not self.price_bands:
                raise ValueError("price_bands 는 최소 한 구간이 필요합니다.")
            if not self.threshold_bands:
                raise ValueError("price_bands 규칙은 threshold_bands 를 함께 선언해야 합니다.")
            if any(band.multiplier <= 0 for band in self.price_bands):
                raise ValueError("PriceBand 의 평점계수(k)는 0보다 커야 합니다.")
            _validate_bands(self.price_bands, axis="PriceBand")
        if self.threshold_bands is not None:
            if self.pass_threshold is not None:
                raise ValueError("threshold_bands 와 pass_threshold 는 동시에 선언할 수 없습니다.")
            if not self.threshold_bands:
                raise ValueError("threshold_bands 는 최소 한 구간이 필요합니다.")
            _validate_bands(self.threshold_bands, axis="ThresholdBand")
        if self.institution_scope not in RULE_SCOPE_VALUES:
            raise ValueError(f"지원하지 않는 기관 범위입니다: {self.institution_scope}")
        if self.institution_scope == RULE_SCOPE_INSTITUTION and not (
            self.institution_code or self.institution_name
        ):
            raise ValueError("INSTITUTION 규칙은 기관 코드 또는 기관명이 필요합니다.")
        if self.institution_scope == RULE_SCOPE_REGION and not (
            self.region_code or self.region_name
        ):
            raise ValueError("REGION 규칙은 지역 코드 또는 지역명이 필요합니다.")


# 배점표(B·k·T) 판정표는 원문 별표 문서에서 확정된 값만 담습니다.
# 근거 문서:
# - docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md (개정 전 제2025-257호·제2026-15호)
# - docs/analysis/servc_post_rules_audit_20260929.md (개정 후 제2026-260호)
# - docs/analysis/20260930_score_params_acquisition.md (별표9 실측·통과점수)
# 고시금액(용역 2.3억) 출처: src/ml/notice_amount.py NOTICE_AMOUNT_BY_YEAR
_SCORE_DOC_PRE = "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:152-179"
_SCORE_DOC_POST = "docs/analysis/servc_post_rules_audit_20260929.md:96-131"
_SCORE_DOC_MEASURED = "docs/analysis/20260930_score_params_acquisition.md:135-148"
_SCORE_SRC_PRE = (
    f"{_SCORE_DOC_PRE} (제2025-257호·제2026-15호 별표별 입찰가격 계산식·배점한도·통과점수)"
)
_SCORE_SRC_POST = f"{_SCORE_DOC_POST} (제2026-260호 별표별 입찰가격 계산식) 및 {_SCORE_DOC_MEASURED} (통과점수·별표9 실측)"
_SCORE_DOC_PRE_20230501 = "docs/analysis/servc_2023_53_original_attachments_20261003.md"
_SCORE_REASON_UNMAPPED_BAND = (
    "미확인: 일반 띠는 별표 1~9 에 같은 이름이 없어 별표 귀속이 미확인입니다 "
    "(docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312)"
)
_SCORE_REASON_UNKNOWN_RULE = "미확인: 배점표 판정표에 없는 규칙이라 값을 만들지 않습니다."
_SCORE_NOTE_B_SPLIT = "조건부: B는 추정가격 5억원 미만 70/이상 60으로 선택"
_SCORE_NOTE_B_MANUAL = "수요기관 지정: B는 60~70 범위에서 공고문 값 입력"
_SCORE_NOTE_K_SPLIT = "조건부: k는 고시금액 미만 4/이상 2로 선택"
_SCORE_THRESHOLD_88_ATTACHMENTS = {"ATTACH_03", "ATTACH_04"}


def _score_source(regime: str, table_row: int, *, pre_rows: str = "") -> str:
    if regime == "PRE":
        return (
            f"docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:"
            f"{table_row},174,176 {pre_rows}"
        ).strip()
    return (
        f"docs/analysis/servc_post_rules_audit_20260929.md:{table_row},131 "
        "및 docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174"
    )


ScoreTableEntry = tuple[Decimal | None, Decimal | None, Decimal | None, str]

_SCORE_TABLE_DECLARATIONS: dict[str, ScoreTableEntry] = {
    # 2025-09-01 시행 판 (제2025-257호·제2026-15호)
    "SERVC_QUAL_PRE_20250901_ATTACH_01": (
        None,
        Decimal("5"),
        Decimal("85"),
        f"{_score_source('PRE', 163)} (별표2 시설: k=5·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_02": (
        None,
        Decimal("0.375"),
        Decimal("85"),
        f"{_SCORE_SRC_PRE} (별표6 보험: k=0.375 단일·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_03": (
        None,
        Decimal("4"),
        Decimal("88"),
        f"{_score_source('PRE', 167)} (별표5 여객: k=4·T=88; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_04": (
        None,
        Decimal("4"),
        Decimal("88"),
        f"{_score_source('PRE', 165)} (별표3의2 SW 대상: k=4·T=88; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_PRE_20250901_ATTACH_05": (
        None,
        None,
        Decimal("85"),
        f"{_score_source('PRE', 164)} (별표3 SW 비대상: T=85; "
        f"{_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
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
        f"{_SCORE_SRC_PRE} (별표9 수요기관 지정형: T=85; {_SCORE_NOTE_B_MANUAL}, {_SCORE_NOTE_K_SPLIT})",
    ),
    # 2023-05-01 시행 판 (제2023-53호). 국가법령정보센터 원문 별표에서 직접 확인한 값입니다.
    **{
        f"SERVC_QUAL_PRE_20230501_ATTACH_{index:02d}": (
            max_price_score,
            multiplier,
            pass_threshold,
            f"{_SCORE_DOC_PRE_20230501}:17,{attachment_row},{rule_row} "
            f"(제2023-53호 원문 {label}){note}",
        )
        for (
            index,
            max_price_score,
            multiplier,
            pass_threshold,
            attachment_row,
            rule_row,
            label,
            note,
        ) in (
            (
                1,
                None,
                Decimal("5"),
                Decimal("85"),
                26,
                46,
                "별표2 시설: k=5·T=85",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                2,
                None,
                Decimal("0.375"),
                Decimal("85"),
                32,
                47,
                "별표6 보험: k=0.375·T=85",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                3,
                None,
                Decimal("4"),
                Decimal("88"),
                30,
                48,
                "별표5 여객: k=4·T=88",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                4,
                None,
                Decimal("4"),
                Decimal("88"),
                28,
                49,
                "별표3의2 SW 대상: k=4·T=88",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                5,
                None,
                None,
                Decimal("85"),
                27,
                50,
                "별표3 SW 비대상: T=85",
                f"; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT}",
            ),
            (
                6,
                Decimal("70"),
                Decimal("4"),
                Decimal("85"),
                25,
                51,
                "별표1 학술연구 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억",
                "",
            ),
            (
                7,
                None,
                Decimal("2"),
                Decimal("85"),
                25,
                52,
                "별표1 학술연구 고시금액 이상: k=2·T=85",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                8,
                Decimal("70"),
                Decimal("4"),
                Decimal("85"),
                29,
                53,
                "별표4 폐기물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억",
                "",
            ),
            (
                9,
                None,
                Decimal("2"),
                Decimal("85"),
                29,
                54,
                "별표4 폐기물 고시금액 이상: k=2·T=85",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                10,
                Decimal("70"),
                Decimal("4"),
                Decimal("85"),
                31,
                55,
                "별표5의2 화물 고시금액 미만: B=70·k=4·T=85; 고시금액 2.3억<5억",
                "",
            ),
            (
                11,
                None,
                Decimal("2"),
                Decimal("85"),
                31,
                56,
                "별표5의2 화물 고시금액 이상: k=2·T=85",
                f"; {_SCORE_NOTE_B_SPLIT}",
            ),
            (
                15,
                None,
                None,
                Decimal("85"),
                33,
                57,
                "별표7 수리·점검: T=85",
                f"; {_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT}",
            ),
            (
                16,
                Decimal("70"),
                None,
                Decimal("85"),
                34,
                58,
                "별표8 임대차: B=70·T=85",
                f"; {_SCORE_NOTE_K_SPLIT}",
            ),
            (
                17,
                None,
                None,
                Decimal("85"),
                35,
                59,
                "별표9 수요기관 지정형: T=85",
                f"; {_SCORE_NOTE_B_MANUAL}, {_SCORE_NOTE_K_SPLIT}",
            ),
        )
    },
    # 2026-05-26 시행 판 (제2026-260호)
    "SERVC_QUAL_POST_20260526_ATTACH_01": (
        None,
        Decimal("5"),
        Decimal("85"),
        f"{_score_source('POST', 103)} (별표2 시설: k=5·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_02": (
        None,
        Decimal("0.375"),
        Decimal("85"),
        f"{_SCORE_SRC_POST} (별표6 보험: k=0.375 단일·T=85; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_03": (
        None,
        Decimal("4"),
        Decimal("88"),
        f"{_score_source('POST', 107)} (별표5 여객: k=4·T=88; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_04": (
        None,
        Decimal("4"),
        Decimal("88"),
        f"{_score_source('POST', 105)} (별표3의2 SW 대상: k=4·T=88; {_SCORE_NOTE_B_SPLIT})",
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_05": (
        None,
        None,
        Decimal("85"),
        f"{_score_source('POST', 104)} (별표3 SW 비대상: T=85; "
        f"{_SCORE_NOTE_B_SPLIT}, {_SCORE_NOTE_K_SPLIT})",
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
        if pass_threshold is not None:
            attachment = "_".join(rule.rule_id.rsplit("_", 2)[-2:])
            expected_threshold = (
                Decimal("88") if attachment in _SCORE_THRESHOLD_88_ATTACHMENTS else Decimal("85")
            )
            if pass_threshold != expected_threshold:
                raise ValueError(f"배점표 통과점수가 별표 예외 규칙과 다릅니다: {rule.rule_id}")
        enriched.append(
            replace(
                rule,
                max_price_score=max_price_score,
                multiplier=multiplier,
                pass_threshold=pass_threshold,
                max_price_score_by_500m=(
                    (Decimal("70"), Decimal("60"))
                    if max_price_score is None and _has_conditional_axis(rule.rule_id, "B")
                    else None
                ),
                multiplier_by_notice=(
                    (Decimal("4"), Decimal("2"))
                    if multiplier is None and _has_conditional_axis(rule.rule_id, "k")
                    else None
                ),
                score_table_source=source,
            )
        )
    return tuple(enriched)


def _has_conditional_axis(rule_id: str, axis: str) -> bool:
    match = re.search(r"(PRE|POST)_\d{8}_ATTACH_(\d{2})$", rule_id)
    if not match:
        return False
    generation, attachment = match.groups()
    attachment_number = int(attachment)
    if generation == "PRE":
        conditional = {
            "B": {1, 2, 3, 4, 5, 7, 9, 11, 15},
            "k": {5, 15, 16, 17},
        }
    else:
        conditional = {"B": {1, 2, 3, 4, 5, 7, 9, 11}, "k": {5}}
    return attachment_number in conditional[axis]


@dataclass(frozen=True)
class ScoreParamResolution:
    max_price_score: Decimal | None
    multiplier: Decimal | None
    pass_threshold: Decimal | None
    max_price_score_basis: str | None
    multiplier_basis: str | None
    pass_threshold_basis: str | None
    estimated_price: Decimal | None
    max_price_score_boundary: Decimal | None
    multiplier_boundary: Decimal | None
    warnings: tuple[str, ...] = ()
    base_rate: Decimal | None = None
    price_band_index: int | None = None
    price_band_label: str | None = None
    threshold_band_label: str | None = None


def method_name_500m_side(method_name: str | None) -> bool | None:
    """낙찰방법명에 적힌 추정가격 5억원 이상 여부를 반환합니다."""
    match = re.search(r"5\s*억\s*원?\s*(미만|이상)", method_name or "")
    return None if match is None else match.group(1) == "이상"


def _select_upper_bound_band(
    bands: Sequence[Any],
    price: Decimal | None,
) -> tuple[Any | None, int | None, str | None]:
    """추정가격으로 구간 목록에서 하나를 고릅니다.

    상한(upper_bound) 없는 마지막 구간은 나머지 전부를 담당하고, 경계값은 상위 구간
    (이상 쪽)에 속합니다(예: 정확히 5억원이면 "10억원 미만 5억원 이상" 구간).
    """
    if not bands:
        return None, None, "규모 구간이 없습니다."
    if price is None:
        return None, None, "추정가격이 없어 규모 구간을 정할 수 없습니다."
    open_upper_index: int | None = None
    for index, band in enumerate(bands):
        if band.upper_bound is None:
            open_upper_index = index
            continue
        if price < band.upper_bound:
            return band, index, None
    if open_upper_index is not None:
        return bands[open_upper_index], open_upper_index, None
    return None, None, "추정가격이 어느 규모 구간에도 들지 않습니다."


def select_price_band(
    bands: Sequence[PriceBand], estimated_price: Decimal | None
) -> tuple[PriceBand | None, int | None, str | None]:
    """추정가격으로 B·k 구간을 고릅니다. 추정가격이 없으면 임의 선택하지 않습니다."""
    return _select_upper_bound_band(bands, estimated_price)


def select_threshold_band(
    bands: Sequence[ThresholdBand], estimated_price: Decimal | None
) -> tuple[ThresholdBand | None, int | None, str | None]:
    """추정가격으로 T 구간을 고릅니다. B·k 경계와 다른 경계를 씁니다."""
    return _select_upper_bound_band(bands, estimated_price)


def resolve_score_params(
    rule: EvaluationRule,
    estimated_price: Decimal | int | float | str | None,
    announced_date: date | datetime | str | None,
    method_name: str | None,
) -> ScoreParamResolution:
    """규칙의 고정값과 공고 구간 표기·추정가격으로 B·k·T를 결정합니다."""
    try:
        price = Decimal(str(estimated_price)) if estimated_price not in (None, "") else None
        if price is not None and price <= 0:
            price = None
    except Exception:
        price = None
    if rule.price_bands is not None:
        price_band, price_index, price_reason = select_price_band(rule.price_bands, price)
        threshold_band, _, threshold_reason = select_threshold_band(
            rule.threshold_bands or (), price
        )
        if price_band is None or threshold_band is None:
            return ScoreParamResolution(
                max_price_score=None,
                multiplier=None,
                pass_threshold=None,
                max_price_score_basis=None,
                multiplier_basis=None,
                pass_threshold_basis=None,
                estimated_price=price,
                max_price_score_boundary=None,
                multiplier_boundary=None,
                warnings=tuple(reason for reason in (price_reason or threshold_reason,) if reason),
            )
        return ScoreParamResolution(
            max_price_score=price_band.max_price_score,
            multiplier=price_band.multiplier,
            pass_threshold=threshold_band.pass_threshold,
            max_price_score_basis=f"규모 구간: {price_band.label}",
            multiplier_basis=f"규모 구간: {price_band.label}",
            pass_threshold_basis=f"규모 구간: {threshold_band.label}",
            estimated_price=price,
            max_price_score_boundary=None,
            multiplier_boundary=None,
            base_rate=price_band.base_rate,
            price_band_index=price_index,
            price_band_label=price_band.label,
            threshold_band_label=threshold_band.label,
            warnings=(),
        )
    year = None
    try:
        if isinstance(announced_date, (date, datetime)):
            year = announced_date.year
        elif announced_date:
            year = date.fromisoformat(str(announced_date)[:10]).year
    except ValueError:
        pass
    name = method_name or ""
    method_notice = re.search(r"고시금액\s*(미만|이상)", name)
    method_b = method_name_500m_side(name)
    method_k = (method_notice.group(1) == "이상") if method_notice else None
    boundary_b = Decimal("500000000")
    boundary_k = Decimal(notice_amount_for_year(year)) if year is not None else None
    warnings: list[str] = []

    def choose(fixed, conditional, method_side, boundary, axis):
        if conditional is None:
            return fixed, ("FIXED" if fixed is not None else None)
        price_side = None if price is None or boundary is None else price >= boundary
        if method_side is not None:
            if price_side is not None and method_side != price_side:
                warnings.append(
                    f"낙찰방법명 구간과 추정가격의 {axis} 판정이 달라 낙찰방법명을 적용했습니다."
                )
            return conditional[1 if method_side else 0], "METHOD_NAME"
        if price_side is not None:
            return conditional[1 if price_side else 0], "ESTIMATED_PRICE"
        return None, None

    b_value, b_basis = choose(
        rule.max_price_score, rule.max_price_score_by_500m, method_b, boundary_b, "B"
    )
    k_value, k_basis = choose(rule.multiplier, rule.multiplier_by_notice, method_k, boundary_k, "k")
    return ScoreParamResolution(
        max_price_score=b_value,
        multiplier=k_value,
        pass_threshold=rule.pass_threshold,
        max_price_score_basis=b_basis,
        multiplier_basis=k_basis,
        pass_threshold_basis="FIXED" if rule.pass_threshold is not None else None,
        estimated_price=price,
        max_price_score_boundary=boundary_b if rule.max_price_score_by_500m else None,
        multiplier_boundary=boundary_k if rule.multiplier_by_notice else None,
        warnings=tuple(warnings),
    )


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

# =============================================================================
# 지방계약(LOCAL) 시·도 자체 별표 규칙
# =============================================================================
#
# 정본: docs/design/local_regime_rules_design_20261005.md 0절(D8)·6.4절, 4절.
# 수집 원문: docs/analysis/servc_formula_collection_local_20261004.md 4.2~4.12절,
#           docs/analysis/servc_formula_userfiles_local_20261004.md,
#           docs/analysis/servc_formula_resolve_daegu_dapa_gg_20261005.md.
# 시·도 규칙은 낙찰방법명이 아니라 수요기관 시·도로 매칭하며, 조달청 별표를 후보에서 배제합니다.
# 행정안전부 예규 기본 규칙은 만들지 않습니다(0.1 D8). 시·도 규칙이 없으면 LOCAL_RULE_NOT_FOUND 입니다.
#
# B·k 는 price_bands(추정가격 3~4구간), T 는 threshold_bands(경계가 다를 수 있음)로 표현합니다.
# 모든 밴드의 기준비율은 88%(경기 별표 1-1 의 89 는 미확정이라 규칙을 만들지 않음)입니다.
_LOCAL_COLLECTION = "docs/analysis/servc_formula_collection_local_20261004.md"

_SRC_INCHEON = (
    f"{_LOCAL_COLLECTION}:122-146 (인천광역시 일반용역 적격심사 세부기준, "
    "인천광역시 예규 제488호, 시행 2025-12-24, 별표 1)"
)
_SRC_JEJU = (
    f"{_LOCAL_COLLECTION}:148-173 (제주특별자치도 일반용역 적격심사 세부기준, "
    "제주특별자치도 예규 제82호, 시행 2024-01-01, 별표 1)"
)
_SRC_GANGWON = (
    f"{_LOCAL_COLLECTION}:175-200 (강원특별자치도 일반용역 적격심사 세부기준, "
    "강원특별자치도 예규 제832호, 시행 2023-06-11, 별표 1)"
)
_SRC_SEJONG = (
    f"{_LOCAL_COLLECTION}:225-247 (세종특별자치시 일반용역 적격심사 세부기준, "
    "세종특별자치시 예규 제32호, 시행 2025-12-01, 별표 2~5)"
)
_SRC_GB = (
    f"{_LOCAL_COLLECTION}:249-273 (경상북도 일반용역 등 적격심사 세부기준, "
    "경상북도 예규 제1571호, 시행 2026-01-08, 별표 1~4)"
)
_SRC_ULSAN = (
    f"{_LOCAL_COLLECTION}:275-306 (울산광역시 일반용역 적격심사 세부기준, "
    "울산광역시 공고 제2022-1100호, 시행 2022-08-10, 별표 1·1-1·2); "
    "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713 "
    "(참고 입찰가격 평점 산식의 낙찰하한율)"
)
_SRC_CB = (
    f"{_LOCAL_COLLECTION}:308-333 (충청북도 일반용역 적격심사 세부기준, "
    "충청북도 공고 제2023-1428호, 시행 2023-10-20, 별표 1); "
    "EXT/cb/cb_cjuc.txt:1454-1659 (별표 1 3. 입찰가격 평가의 낙찰하한율)"
)
_SRC_JNGJ = (
    f"{_LOCAL_COLLECTION}:335-371 (전남광주통합특별시 일반용역 적격심사 세부지침, "
    "전남광주통합특별시 예규 제3호, 시행 2026-07-16, 별표 1~6); "
    "EXT/jn_gj/jngj_att001.hwp.tbl.txt:47-69, EXT/jn_gj/jngj_att002.hwp.tbl.txt:52-74, "
    "EXT/jn_gj/jngj_att003.hwp.tbl.txt:53-75, EXT/jn_gj/jngj_att004.hwp.tbl.txt:46-60, "
    "EXT/jn_gj/jngj_att005.hwp.tbl.txt:48-70, EXT/jn_gj/jngj_att006.hwp.tbl.txt:9-93 "
    "(별표 1~6 입찰가격 평가의 낙찰하한율)"
)
_SRC_GN = (
    f"{_LOCAL_COLLECTION}:373-394 (경상남도 일반용역 등 적격심사 세부기준, "
    "경상남도 공고 제2023-23호, 시행 2023-01-05, 별표 1)"
)
_SRC_DAEGU = (
    f"{_LOCAL_COLLECTION}:202-223 (대구광역시 일반용역 적격심사 세부기준, "
    "대구광역시 예규 제238호, 시행 2026-05-11, 별표 1 단순노무); "
    "EXT/daegu/tbl1_daegu.txt:150 (최저 낙찰하한율 87.745%), "
    "EXT/supplement/daegu/R25BK01157938_f1.txt:47 (공고문 낙찰하한율 87.745%)"
)
_SRC_GG = (
    f"{_LOCAL_COLLECTION}:396-463 (경기도 일반용역 적격심사 세부기준 지침, "
    "경기도 예규 제748호, 시행 2025-08-08, 별표 1-2~1-6); "
    "EXT/gg/gg_g2b_20251210_coord.txt:337-455 (별표 1-2), "
    "EXT/gg/gg_g2b_20251210_coord.txt:456-572 (별표 1-3), "
    "EXT/gg/gg_g2b_20251210_coord.txt:573-672 (별표 1-4), "
    "EXT/gg/gg_g2b_20251210_coord.txt:733-843 (별표 1-6) "
    "(입찰가격 평점 산식의 낙찰하한율)"
)

# 2단계 추가 5곳(서울·부산·대전·충남·전북)의 원문 근거는 별도 재수집 문서와 이 워크트리의
# EXT/ 추출물입니다. 값이 의심스러우면 EXT 원문 행을 직접 대조합니다.
_SRC_RECOVER = "docs/analysis/servc_formula_recover_c_20261005.md"
_SRC_SEOUL = (
    f"{_SRC_RECOVER}:76-103 (서울특별시 일반용역 적격심사 세부기준, 시행 2024-08-12, "
    "별표 1~4); EXT/seoul/seoul_general_2024_08_12.tbl.txt:"
    "32,35-37,369-384,712-727,1055-1070,1308-1323"
)
_SRC_BUSAN = (
    f"{_SRC_RECOVER}:105-132 (부산광역시 일반용역 적격심사 세부기준, 공고 제2025-1981호, "
    "시행 2025-06-26, 별표 1); EXT/busan/busan_general_2025_1981.txt:57,82-84,149-150 "
    "(149 입찰가격 평가: 단순노무 외 10억원 이상 30억원 미만 77.995%, 30억원 이상 72.995%; "
    "단순노무 87.745%)"
)
_SRC_DAEJEON = (
    f"{_SRC_RECOVER}:134-168 (대전광역시 일반용역 적격심사 세부기준, 공고 제2025-9528호, "
    "시행 2026-01-01, 별표 6); EXT/daejeon/daejeon_2025_9528.txt:39,68-71,260-265 "
    "(262 입찰가격 평가: 소프트웨어·폐기물·기타 일반용역 10억원 이상 30억원 미만 77.995%, "
    "30억원 이상 72.995%; 청소·시설물경비·시설물관리 87.745%)"
)
_SRC_CHUNGNAM_ATTACH_01 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 공고 2026-1235호, "
    "시행 2026-07-13, 별표 1 시설분야용역); EXT/chungnam/chungnam_2026_1235.txt:"
    "457-459,481-483,487,551-560; EXT/chungnam/chungnam_tables.txt:2-18"
)
_SRC_CHUNGNAM_ATTACH_2_1 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 별표 2의1 정보통신 "
    "중소기업자간 경쟁제품 대상); EXT/chungnam/chungnam_2026_1235.txt:"
    "457-459,481-483,1121,1172-1180; EXT/chungnam/chungnam_tables.txt:47-63"
)
_SRC_CHUNGNAM_ATTACH_05 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 별표 5 해양환경관리 "
    "및 어장관리용역); EXT/chungnam/chungnam_2026_1235.txt:"
    "193,457-459,481-483,2248,2334-2366; EXT/chungnam/chungnam_tables.txt:137-158"
)
_SRC_JEONBUK = (
    f"{_SRC_RECOVER}:204-230 (전북특별자치도 일반용역 적격심사 세부기준, 부칙 제2024-10호, "
    "시행 2024-01-18, 별표 1); EXT/jeonbuk/jb_general_2024_10.tbl.txt:"
    "35-37,44-49,127-145,357-366,583-592,792-799 "
    "(138-145 입찰가격 평가: 단순노무 외 10억원 이상 30억원 미만 77.995%, 30억원 이상 "
    "72.995%; 단순노무 87.745%; 구간 하한율 숫자 행 141, 143, 145, 369, 595, 802)"
)

# 세종 별표 3(소프트웨어)·별표 5(육상운송)는 같은 별표 안에서 중소기업자간 경쟁제품
# 대상/비대상 여부로 k·낙찰하한율·통과점수가 갈립니다(별표 분리가 아니라 조건 분기).
# 출처는 코디네이터가 확인한 원문 추출 파일의 행 번호입니다.
_SRC_SEJONG_EXT = ".orca/capsules/task_58ea8ddab6fb/external/sejong"
_SRC_SEJONG_SW_NON_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp3_sw_2025.txt:16-23 "
    "(가. 중소기업간 경쟁제품 비대상 입찰가격 평점산식 80.495%), "
    f"{_SRC_SEJONG_EXT}/byp3_sw_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":14 (k 2), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (비대상 T 85)"
)
_SRC_SEJONG_SW_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp3_sw_2025.txt:24-31 "
    "(나. 중소기업간 경쟁제품 대상 입찰가격 평점산식 84.995%), "
    f"{_SRC_SEJONG_EXT}/byp3_sw_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":17 (k 4), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (대상 T 88)"
)
_SRC_SEJONG_LT_NON_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp5_2025.txt:19-26 "
    "(가. 중소기업간 경쟁제품 비대상 입찰가격 평점산식 80.495%), "
    f"{_SRC_SEJONG_EXT}/byp5_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":20 (k 2), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (비대상 T 85)"
)
_SRC_SEJONG_LT_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp5_2025.txt:27-34 "
    "(나. 중소기업간 경쟁제품 대상 입찰가격 평점산식 84.995%), "
    f"{_SRC_SEJONG_EXT}/byp5_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":23 (k 4), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (대상 T 88)"
)
# 시설·폐기물·생활폐기물 별표는 전 구간 단일 낙찰하한율을 인쇄합니다.
_SRC_SEJONG_FACILITY = f"{_SRC_SEJONG}; EXT/sejong/byp2_2025.txt:31 (별표 2 시설 전 구간 87.745%)"
_SRC_SEJONG_WASTE = f"{_SRC_SEJONG}; EXT/sejong/byp4_2025.txt:18 (별표 4 폐기물 전 구간 87.745%)"
_SRC_SEJONG_WASTE_HOUSEHOLD = (
    f"{_SRC_SEJONG}; EXT/sejong/byp4_2_2025.txt:11 (별표 4의2 생활폐기물 전 구간 87.745%)"
)

# 2026-10-05 공고 실측: 별표 원문에 하한율이 인쇄되지 않은 GENERAL 규칙 6개의 10억원 미만
# 구간 최빈값입니다. 자치법규 원문이 인쇄한 값이 아니므로 원문 확인값으로 표기하지 않습니다.
_SRC_LWLT_MEASURED = (
    "docs/analysis/local_lwlt_announcement_measure_20261005.md:225-235 "
    "6.1 공고 실측 최빈값, 자치법규 원문 미확인"
)
_SRC_GB_MEASURED = f"{_SRC_GB}; {_SRC_LWLT_MEASURED}"
# 구간 순서는 (2억원 미만, 5억원 미만, 10억원 미만, 10억원 이상)입니다. 10억원 이상은
# 값을 비워 두어 규칙 대표값(EvaluationRule.lwlt_rate)을 쓰게 합니다.
_MEASURED_LWLT_UNDER_1B: tuple[str | None, str | None, str | None, str | None] = (
    "87.745",
    "86.745",
    "85.495",
    None,
)

_LOCAL_NOT_FOUND_MESSAGE = (
    "해당 지자체의 일반용역 적격심사 기준이 아직 확보되지 않았습니다. "
    "가격배점한도(B)·평점계수(k)·기준비율·통과점수를 직접 입력하면 가격점수를 계산합니다."
)

# 시·도별 기본 낙찰하한율은 그 별표에 대응하는 조달청 관행 하한율을 기본값으로 둡니다.
# 공고에 sucsfbidLwltRate 가 있으면 공고값이 우선합니다(현행과 동일).
_LOCAL_LWLT_BY_SERVICE: dict[str, str] = {
    "FACILITY": "87.995",
    "INSURANCE": "47.995",
    "LAND_TRANSPORT": "87.995",
    "LAND_TRANSPORT_SME": "84.995",
    "SW": "87.995",
    "SW_SME": "84.995",
    "WASTE": "84.245",
    "WASTE_HOUSEHOLD": "84.245",
    "REPAIR_INSPECTION": "84.245",
    "LEASE": "84.245",
    "GENERAL": "87.995",
    "SIMPLE_LABOR": "87.995",
    "FISHERY_CLEANUP": "87.995",
}


def _local_price_band(
    upper: str | None,
    b: str,
    k: str,
    label: str,
    source: str,
    base_rate: str = "0.88",
    lwlt_rate: str | None = None,
) -> PriceBand:
    return PriceBand(
        upper_bound=Decimal(upper) if upper is not None else None,
        max_price_score=Decimal(b),
        multiplier=Decimal(k),
        base_rate=Decimal(base_rate),
        label=label,
        source=source,
        lwlt_rate=Decimal(lwlt_rate) if lwlt_rate is not None else None,
    )


def _local_threshold_band(upper: str | None, t: str, label: str, source: str) -> ThresholdBand:
    return ThresholdBand(
        upper_bound=Decimal(upper) if upper is not None else None,
        pass_threshold=Decimal(t),
        label=label,
        source=source,
    )


def _four_band_price(
    source: str,
    *,
    simple_labor: bool = False,
    lwlt_rates: tuple[str | None, str | None, str | None, str | None] | None = None,
) -> tuple[PriceBand, ...]:
    """10억/5억/2억 4구간 B·k. 단순노무 행은 k 가 전 구간 20 입니다.

    lwlt_rates 를 주면 구간 순서(2억 미만, 5억 미만, 10억 미만, 10억 이상)대로 인쇄된
    낙찰하한율을 덧붙입니다. 원문이 구간 하나에 값을 확정하지 못하는 자리는 None 으로
    두어 규칙 대표값을 쓰게 합니다.
    """
    k_top = "20" if simple_labor else "1"
    k_10 = "20" if simple_labor else "2"
    k_5 = "20" if simple_labor else "4"
    bands = (
        _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", source),
        _local_price_band("500000000", "70", k_5, "5억원 미만 2억원 이상", source),
        _local_price_band("1000000000", "50", k_10, "10억원 미만 5억원 이상", source),
        _local_price_band(None, "30", k_top, "추정가격 10억원 이상", source),
    )
    if lwlt_rates is None:
        return bands
    return tuple(
        replace(band, lwlt_rate=Decimal(rate) if rate is not None else None)
        for band, rate in zip(bands, lwlt_rates, strict=True)
    )


def _measured_lwlt_four_band_price(source: str) -> tuple[PriceBand, ...]:
    """10억원 미만 3개 구간에 공고 실측 하한율을 붙인 10억/5억/2억 4구간.

    2026-10-05 공고 실측 대상 6개 GENERAL 규칙 전용입니다. 구간 하한율을 붙인 구간의
    source 는 자치법규 원문이 아니라 공고 실측임을 함께 밝히고, 10억원 이상 구간은 값을
    비워 규칙 대표값(EvaluationRule.lwlt_rate)을 그대로 쓰게 합니다. 이 헬퍼를 쓰지 않는
    다른 규칙의 구간은 종전과 같습니다.
    """
    bands = _four_band_price(source, lwlt_rates=_MEASURED_LWLT_UNDER_1B)
    return tuple(
        replace(band, source=f"{source}; {_SRC_LWLT_MEASURED}")
        if band.lwlt_rate is not None
        else band
        for band in bands
    )


# 서울 GENERAL 전용 30억원 분할. 10억원 이상 공고 실측 하한율이 30억원 경계로
# 77.995/72.995 로 갈려 서울 규칙만 5구간으로 만듭니다. 구간 라벨은 원문 구간 표기를
# 따르고, B·k·기준비율은 분할 전 10억원 이상 구간 값(B 30·k 1·0.88) 그대로입니다.
_SEOUL_TOP_LWLT_RATES: tuple[str, str] = ("77.995", "72.995")


def _measured_lwlt_seoul_five_band_price(source: str) -> tuple[PriceBand, ...]:
    """서울 GENERAL 전용 5구간. 10억원 이상을 30억원 경계로 나눠 실측 하한율을 붙입니다.

    공유 헬퍼(_four_band_price·_measured_lwlt_four_band_price)는 다른 5개 GENERAL 규칙이
    함께 쓰므로 건드리지 않고, 이 함수에서 10억원 이상 밴드만 두 밴드로 바꿔 끼웁니다.
    두 밴드의 source 는 분할 전 10억원 미만 구간과 같이 공고 실측임을 함께 밝힙니다.
    """
    bands = _measured_lwlt_four_band_price(source)
    under_30 = replace(
        bands[-1],
        upper_bound=Decimal("3000000000"),
        label="30억원 미만 10억원 이상",
        lwlt_rate=Decimal(_SEOUL_TOP_LWLT_RATES[0]),
        source=f"{source}; {_SRC_LWLT_MEASURED}",
    )
    over_30 = _local_price_band(
        None,
        "30",
        "1",
        "추정가격 30억원 이상",
        f"{source}; {_SRC_LWLT_MEASURED}",
        lwlt_rate=_SEOUL_TOP_LWLT_RATES[1],
    )
    return (*bands[:-1], under_30, over_30)


def _five_band_price(
    source: str,
    *,
    lwlt_rates: tuple[str | None, str | None, str | None, str | None, str | None] | None = None,
) -> tuple[PriceBand, ...]:
    """10억원 이상을 30억원 경계로 나눈 5구간 B·k.

    부산·대전·전북·울산·충북 일반 띠와 전남광주 어장정화 띠가 씁니다.
    원문은 10억원 이상 행을 30억원 미만 77.995%, 30억원 이상 72.995% 로 나눠 인쇄합니다.
    B·k·기준비율은 나눈 두 구간 모두 10억원 이상 값(B 30·k 1·0.88)입니다. 서울 등 나머지
    시·도는 이 분할이 없어 기존 _four_band_price 를 그대로 씁니다.
    lwlt_rates 순서는 (2억원 미만, 5억원 미만, 10억원 미만, 30억원 미만, 30억원 이상)입니다.
    """
    bands = (
        _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", source),
        _local_price_band("500000000", "70", "4", "5억원 미만 2억원 이상", source),
        _local_price_band("1000000000", "50", "2", "10억원 미만 5억원 이상", source),
        _local_price_band("3000000000", "30", "1", "30억원 미만 10억원 이상", source),
        _local_price_band(None, "30", "1", "추정가격 30억원 이상", source),
    )
    if lwlt_rates is None:
        return bands
    return tuple(
        replace(band, lwlt_rate=Decimal(rate) if rate is not None else None)
        for band, rate in zip(bands, lwlt_rates, strict=True)
    )


def _threshold_30_10(source: str) -> tuple[ThresholdBand, ...]:
    """30억/10억 경계 T: 30억↑85, 10억~30억90, ~10억95."""
    return (
        _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", source),
        _local_threshold_band("3000000000", "90", "30억원 미만 10억원 이상", source),
        _local_threshold_band(None, "85", "추정가격 30억원 이상", source),
    )


def _single_threshold(value: str, label: str, source: str) -> tuple[ThresholdBand, ...]:
    return (_local_threshold_band(None, value, label, source),)


def _local_rule(
    rule_id: str,
    *,
    sido_code: str,
    sido_name: str,
    service_type: str,
    effective_date: str,
    source: str,
    price_bands: tuple[PriceBand, ...],
    threshold_bands: tuple[ThresholdBand, ...],
    description: str,
    lwlt_rate: str | None = None,
    base_rate: str = "0.88",
) -> EvaluationRule:
    return EvaluationRule(
        rule_id=rule_id,
        service_type=service_type,
        table_name=f"{sido_name} 일반용역 적격심사 ({service_type})",
        description=description,
        effective_date=effective_date,
        source=source,
        patterns=(),
        lwlt_rate=Decimal(lwlt_rate or _LOCAL_LWLT_BY_SERVICE[service_type]),
        base_rate=Decimal(base_rate),
        price_bands=price_bands,
        threshold_bands=threshold_bands,
        quant_basis=QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
        score_table_source=source,
        contract_regime="LOCAL",
        institution_scope=RULE_SCOPE_REGION,
        region_code=sido_code,
        region_name=sido_name,
    )


LOCAL_RULES: tuple[EvaluationRule, ...] = (
    # 인천광역시 (예규 제488호, 시행 2025-12-24)
    _local_rule(
        "SERVC_LOCAL_INCHEON_20251224_ATTACH_01",
        sido_code="28",
        sido_name="인천광역시",
        service_type="GENERAL",
        effective_date="2025-12-24",
        source=_SRC_INCHEON,
        description="인천광역시 일반용역 적격심사 (단순노무 외)",
        price_bands=_measured_lwlt_four_band_price(_SRC_INCHEON),
        threshold_bands=_threshold_30_10(_SRC_INCHEON),
    ),
    _local_rule(
        "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR",
        sido_code="28",
        sido_name="인천광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2025-12-24",
        source=_SRC_INCHEON,
        description="인천광역시 일반용역 적격심사 (단순노무)",
        price_bands=_four_band_price(_SRC_INCHEON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_INCHEON),
    ),
    # 제주특별자치도 (예규 제82호, 시행 2024-01-01) — 인천과 동일 구조
    _local_rule(
        "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
        sido_code="50",
        sido_name="제주특별자치도",
        service_type="GENERAL",
        effective_date="2024-01-01",
        source=_SRC_JEJU,
        description="제주특별자치도 일반용역 적격심사 (단순노무 외)",
        price_bands=_measured_lwlt_four_band_price(_SRC_JEJU),
        threshold_bands=_threshold_30_10(_SRC_JEJU),
    ),
    _local_rule(
        "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR",
        sido_code="50",
        sido_name="제주특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2024-01-01",
        source=_SRC_JEJU,
        description="제주특별자치도 일반용역 적격심사 (단순노무)",
        price_bands=_four_band_price(_SRC_JEJU, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_JEJU),
    ),
    # 강원특별자치도 (예규 제832호, 시행 2023-06-11) — 인천과 동일 구조
    _local_rule(
        "SERVC_LOCAL_GANGWON_20230611_ATTACH_01",
        sido_code="51",
        sido_name="강원특별자치도",
        service_type="GENERAL",
        effective_date="2023-06-11",
        source=_SRC_GANGWON,
        description="강원특별자치도 일반용역 적격심사 (단순노무 외)",
        price_bands=_measured_lwlt_four_band_price(_SRC_GANGWON),
        threshold_bands=_threshold_30_10(_SRC_GANGWON),
    ),
    _local_rule(
        "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR",
        sido_code="51",
        sido_name="강원특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2023-06-11",
        source=_SRC_GANGWON,
        description="강원특별자치도 일반용역 적격심사 (단순노무)",
        price_bands=_four_band_price(_SRC_GANGWON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GANGWON),
    ),
    # 세종특별자치시 (예규 제32호, 시행 2025-12-01)
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_02",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="FACILITY",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_FACILITY,
        description="세종특별자치시 시설분야용역 적격심사 (별표 2)",
        price_bands=(
            _local_price_band("500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_FACILITY),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_FACILITY),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_FACILITY),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_03",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="SW",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_SW_NON_TARGET,
        description="세종특별자치시 소프트웨어용역(중소기업간 경쟁제품 비대상) 적격심사 (별표 3)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "2", "추정가격 5억원 미만", _SRC_SEJONG_SW_NON_TARGET
            ),
            _local_price_band(None, "60", "2", "추정가격 5억원 이상", _SRC_SEJONG_SW_NON_TARGET),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_SW_NON_TARGET),
        lwlt_rate="80.495",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="SW_SME",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_SW_TARGET,
        description="세종특별자치시 소프트웨어용역(중소기업간 경쟁제품 대상) 적격심사 (별표 3)",
        price_bands=(
            _local_price_band("500000000", "70", "4", "추정가격 5억원 미만", _SRC_SEJONG_SW_TARGET),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_SEJONG_SW_TARGET),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_SEJONG_SW_TARGET),
        lwlt_rate="84.995",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_04",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="WASTE",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_WASTE,
        description="세종특별자치시 폐기물처리용역 적격심사 (별표 4)",
        price_bands=(
            _local_price_band("500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_WASTE),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_WASTE),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_WASTE),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_WASTE_HOUSEHOLD,
        description="세종특별자치시 생활폐기물처리용역 적격심사 (별표 4의2)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_WASTE_HOUSEHOLD
            ),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_WASTE_HOUSEHOLD),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_WASTE_HOUSEHOLD),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="LAND_TRANSPORT",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_LT_NON_TARGET,
        description="세종특별자치시 육상운송용역(중소기업간 경쟁제품 비대상) 적격심사 (별표 5)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "2", "추정가격 5억원 미만", _SRC_SEJONG_LT_NON_TARGET
            ),
            _local_price_band(None, "60", "2", "추정가격 5억원 이상", _SRC_SEJONG_LT_NON_TARGET),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_LT_NON_TARGET),
        lwlt_rate="80.495",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="LAND_TRANSPORT_SME",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_LT_TARGET,
        description="세종특별자치시 육상운송용역(중소기업간 경쟁제품 대상) 적격심사 (별표 5)",
        price_bands=(
            _local_price_band("500000000", "70", "4", "추정가격 5억원 미만", _SRC_SEJONG_LT_TARGET),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_SEJONG_LT_TARGET),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_SEJONG_LT_TARGET),
        lwlt_rate="84.995",
    ),
    # 경상북도 (예규 제1571호, 시행 2026-01-08)
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_01",
        sido_code="47",
        sido_name="경상북도",
        service_type="SIMPLE_LABOR",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 단순노무용역 적격심사 (별표 1)",
        price_bands=(
            _local_price_band("500000000", "70", "20", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "50", "20", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_02",
        sido_code="47",
        sido_name="경상북도",
        service_type="SW",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 소프트웨어용역 적격심사 (별표 2)",
        price_bands=(
            _local_price_band("500000000", "80", "4", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_03",
        sido_code="47",
        sido_name="경상북도",
        service_type="WASTE",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 폐기물처리용역 적격심사 (별표 3)",
        price_bands=(
            _local_price_band("500000000", "70", "20", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "50", "4", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_04",
        sido_code="47",
        sido_name="경상북도",
        service_type="GENERAL",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 기타 일반용역 적격심사 (별표 4)",
        # 별표 4 원문은 5억원 미만 / 5억원 이상 두 행(B70·k20 / B50·k4)만 인쇄하고 하한율은
        # 인쇄하지 않습니다. 10억원 미만 3개 구간에 공고 실측 최빈값을 붙이려고 각 행을 같은
        # B·k 로 2억·10억에서 나눴습니다.
        price_bands=(
            _local_price_band(
                "200000000", "70", "20", "추정가격 2억원 미만", _SRC_GB_MEASURED, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000",
                "70",
                "20",
                "5억원 미만 2억원 이상",
                _SRC_GB_MEASURED,
                lwlt_rate="86.745",
            ),
            _local_price_band(
                "1000000000",
                "50",
                "4",
                "10억원 미만 5억원 이상",
                _SRC_GB_MEASURED,
                lwlt_rate="85.495",
            ),
            _local_price_band(None, "50", "4", "추정가격 10억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB),
    ),
    # 울산광역시 (공고 제2022-1100호, 시행 2022-08-10)
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_01",
        sido_code="31",
        sido_name="울산광역시",
        service_type="GENERAL",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 참고 입찰가격 평점 산식은 구간마다 낙찰하한율을 인쇄합니다(원문 :671-713).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_ULSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR",
        sido_code="31",
        sido_name="울산광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :677,689,701,713).
        price_bands=_four_band_price(_SRC_ULSAN, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_ULSAN),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1",
        sido_code="31",
        sido_name="울산광역시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 생활폐기물 수집·운반 대행용역 적격심사 (별표 1-1)",
        price_bands=(
            _local_price_band("1000000000", "70", "20", "추정가격 10억원 미만", _SRC_ULSAN),
            _local_price_band("3000000000", "50", "20", "30억원 미만 10억원 이상", _SRC_ULSAN),
            _local_price_band(None, "30", "40", "추정가격 30억원 이상", _SRC_ULSAN),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
        # 생활폐기물수집·운반대행용역 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다
        # (원문 :680,692,704).
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_02",
        sido_code="31",
        sido_name="울산광역시",
        service_type="WASTE",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 폐기물처리용역 적격심사 (별표 2)",
        # 폐기물용역 행도 별표 1 참고 산식과 같은 구간별 낙찰하한율을 인쇄합니다.
        price_bands=_five_band_price(
            _SRC_ULSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
    ),
    # 충청북도 (공고 제2023-1428호, 시행 2023-10-20)
    _local_rule(
        "SERVC_LOCAL_CB_20231020_ATTACH_01",
        sido_code="43",
        sido_name="충청북도",
        service_type="GENERAL",
        effective_date="2023-10-20",
        source=_SRC_CB,
        description="충청북도 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 3. 입찰가격 평가는 구간마다 낙찰하한율을 인쇄합니다(원문 :1513-1659).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_CB,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_CB),
    ),
    _local_rule(
        "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR",
        sido_code="43",
        sido_name="충청북도",
        service_type="SIMPLE_LABOR",
        effective_date="2023-10-20",
        source=_SRC_CB,
        description="충청북도 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :1535-1537 등).
        price_bands=_four_band_price(_SRC_CB, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_CB),
        lwlt_rate="87.745",
    ),
    # 전남광주통합특별시 (예규 제3호, 시행 2026-07-16)
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_01",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="FACILITY",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 시설분야용역 적격심사 (별표 1)",
        # 별표 1 입찰가격 평가의 낙찰하한율은 3구간 모두 87.745% 입니다(원문 att001:53,61,69).
        price_bands=(
            _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", _SRC_JNGJ),
            _local_price_band("500000000", "70", "20", "5억원 미만 2억원 이상", _SRC_JNGJ),
            _local_price_band(None, "50", "20", "추정가격 5억원 이상", _SRC_JNGJ),
        ),
        threshold_bands=_single_threshold("95", "시설분야 추정가격 무관 95", _SRC_JNGJ),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_02",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="SW",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 소프트웨어용역 적격심사 (별표 2)",
        # 별표 2 는 5억원 이상 행을 10억·30억 경계로 나눠 인쇄합니다(원문 att002:58).
        # B·k(50·2)는 나눈 세 구간 모두 같습니다.
        price_bands=(
            _local_price_band(
                "200000000", "80", "20", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "70", "4", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "3000000000", "50", "2", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                None, "50", "2", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_03",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="WASTE",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 폐기물처리용역 적격심사 (별표 3)",
        # 별표 3 의 5억원 이상 행도 10억·30억 경계로 나뉩니다(원문 att003:59).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "80", "20", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "1000000000", "30", "1", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                "3000000000", "30", "1", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="77.995"
            ),
            _local_price_band(
                None, "30", "1", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="72.995"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_04",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 생활폐기물처리용역 적격심사 (별표 4)",
        # 별표 4 입찰가격 평가의 낙찰하한율은 3구간 모두 87.745% 입니다(원문 att004:46-60).
        price_bands=(
            _local_price_band("1000000000", "70", "20", "추정가격 10억원 미만", _SRC_JNGJ),
            _local_price_band("3000000000", "50", "40", "30억원 미만 10억원 이상", _SRC_JNGJ),
            _local_price_band(None, "30", "60", "추정가격 30억원 이상", _SRC_JNGJ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_05",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="LAND_TRANSPORT",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 육상운송용역 적격심사 (별표 5)",
        lwlt_rate="84.245",
        # 별표 5 의 5억원 이상 행도 10억·30억 경계로 나뉩니다(원문 att005:54).
        price_bands=(
            _local_price_band(
                "200000000", "80", "2", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "500000000", "70", "2", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "1000000000", "60", "2", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "3000000000", "60", "2", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                None, "60", "2", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_06",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="FISHERY_CLEANUP",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 어장정화·정비용역 적격심사 (별표 6)",
        # 별표 6 은 구간마다 낙찰하한율을 인쇄합니다(원문 att006:9,37,65,93).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_JNGJ,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    # 경상남도 (공고 제2023-23호, 시행 2023-01-05)
    _local_rule(
        "SERVC_LOCAL_GN_20230105_ATTACH_01",
        sido_code="48",
        sido_name="경상남도",
        service_type="GENERAL",
        effective_date="2023-01-05",
        source=_SRC_GN,
        description="경상남도 일반용역 적격심사 (별표 1)",
        price_bands=_measured_lwlt_four_band_price(_SRC_GN),
        threshold_bands=_threshold_30_10(_SRC_GN),
    ),
    # 대구광역시 (예규 제238호, 시행 2026-05-11) — 단순노무만 확정, 일반 별표는 삭제됨
    _local_rule(
        "SERVC_LOCAL_DAEGU_20260511_ATTACH_01",
        sido_code="27",
        sido_name="대구광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2026-05-11",
        source=_SRC_DAEGU,
        description="대구광역시 단순노무 일반용역 적격심사 (별표 1)",
        price_bands=(
            _local_price_band("200000000", "70", "60", "추정가격 2억원 미만", _SRC_DAEGU),
            _local_price_band(None, "60", "60", "추정가격 2억원 이상", _SRC_DAEGU),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_DAEGU),
        # 별표 1 은 최저 낙찰하한율을 87.745% 이상으로 인쇄합니다(원문 tbl1_daegu.txt:150).
        lwlt_rate="87.745",
    ),
    # 경기도 (예규 제748호, 시행 2025-08-08) — 별표 1-1(단순노무)은 0.25 불일치로 제외
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_2",
        sido_code="41",
        sido_name="경기도",
        service_type="SW",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 소프트웨어용역 적격심사 (별표 1-2)",
        # 별표 1-2 입찰가격 평점 산식은 구간마다 낙찰하한율을 인쇄합니다(원문 coord:419-452).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "50", "4", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="85.495"
            ),
            _local_price_band(None, "30", "1", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="77.995"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_3",
        sido_code="41",
        sido_name="경기도",
        service_type="WASTE",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 폐기물처리용역 적격심사 (별표 1-3)",
        # 별표 1-3 도 구간마다 낙찰하한율을 인쇄합니다(원문 coord:537-569).
        price_bands=(
            _local_price_band(
                "200000000", "70", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "60", "4", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="85.495"
            ),
            _local_price_band(None, "30", "1", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="77.995"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_4",
        sido_code="41",
        sido_name="경기도",
        service_type="LAND_TRANSPORT",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 육상운송용역 적격심사 (별표 1-4)",
        lwlt_rate="87.995",
        # 별표 1-4 의 구간별 낙찰하한율은 85.495/86.745/87.745/87.745% 입니다(원문 coord:641-669).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "70", "20", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "1000000000", "50", "4", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(None, "30", "4", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="85.495"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_5",
        sido_code="41",
        sido_name="경기도",
        service_type="INSURANCE",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 보험용역 적격심사 (별표 1-5)",
        price_bands=(
            _local_price_band("500000000", "70", "0.375", "추정가격 5억원 미만", _SRC_GG),
            _local_price_band(None, "60", "0.375", "추정가격 5억원 이상", _SRC_GG),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_GG),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_6",
        sido_code="41",
        sido_name="경기도",
        service_type="GENERAL",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 기타 일반용역 적격심사 (별표 1-6)",
        # 별표 1-6 도 구간마다 낙찰하한율을 인쇄합니다(원문 coord:805-835).
        price_bands=_four_band_price(_SRC_GG, lwlt_rates=("87.745", "86.745", "85.495", "77.995")),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    # 서울특별시 (시행 2024-08-12) — 일반 띠 단순노무 외/단순노무가 갈려 두 규칙으로 둡니다.
    # 추출 원문에는 낙찰하한율 표기가 없어 공고 실측 최빈값을 넣고, 10억원 이상은 부산·대전·
    # 전북과 같은 30억원 경계(30억원 미만 77.995%, 30억원 이상 72.995%)로 나눕니다.
    _local_rule(
        "SERVC_LOCAL_SEOUL_20240812_ATTACH_01",
        sido_code="11",
        sido_name="서울특별시",
        service_type="GENERAL",
        effective_date="2024-08-12",
        source=_SRC_SEOUL,
        description="서울특별시 일반용역 적격심사 (별표 1~4, 단순노무 외)",
        price_bands=_measured_lwlt_seoul_five_band_price(_SRC_SEOUL),
        threshold_bands=_threshold_30_10(_SRC_SEOUL),
    ),
    _local_rule(
        "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR",
        sido_code="11",
        sido_name="서울특별시",
        service_type="SIMPLE_LABOR",
        effective_date="2024-08-12",
        source=_SRC_SEOUL,
        description="서울특별시 일반용역 적격심사 (별표 1~4, 단순노무)",
        price_bands=_four_band_price(_SRC_SEOUL, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_SEOUL),
    ),
    # 부산광역시 (공고 제2025-1981호, 시행 2025-06-26) — 서울과 동일 구조
    _local_rule(
        "SERVC_LOCAL_BUSAN_20250626_ATTACH_01",
        sido_code="26",
        sido_name="부산광역시",
        service_type="GENERAL",
        effective_date="2025-06-26",
        source=_SRC_BUSAN,
        description="부산광역시 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 입찰가격 평가는 구간마다 낙찰하한율을 인쇄합니다(원문 :149). 10억원 이상은
        # 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_BUSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_BUSAN),
    ),
    _local_rule(
        "SERVC_LOCAL_BUSAN_20250626_SIMPLE_LABOR",
        sido_code="26",
        sido_name="부산광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2025-06-26",
        source=_SRC_BUSAN,
        description="부산광역시 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :149).
        price_bands=_four_band_price(_SRC_BUSAN, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_BUSAN),
        lwlt_rate="87.745",
    ),
    # 대전광역시 (공고 제2025-9528호, 시행 2026-01-01) — 별표 6 이 두 행 묶음으로 인쇄됩니다.
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01",
        sido_code="30",
        sido_name="대전광역시",
        service_type="GENERAL",
        effective_date="2026-01-01",
        source=_SRC_DAEJEON,
        description="대전광역시 일반용역 적격심사 (소프트웨어·폐기물처리·기타 일반용역)",
        # 별표 6 소프트웨어·폐기물처리·기타 일반용역 행은 구간마다 낙찰하한율을
        # 인쇄합니다(원문 :262). 10억원 이상은 30억원 경계로 30억원 미만 77.995%,
        # 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_DAEJEON,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_DAEJEON),
    ),
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20260101_SIMPLE_LABOR",
        sido_code="30",
        sido_name="대전광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2026-01-01",
        source=_SRC_DAEJEON,
        description="대전광역시 일반용역 적격심사 (청소·시설물경비·시설물관리용역)",
        # 청소·시설물경비·시설물관리 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :262).
        price_bands=_four_band_price(_SRC_DAEJEON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_DAEJEON),
        lwlt_rate="87.745",
    ),
    # 충청남도 (공고 2026-1235호, 시행 2026-07-13) — 별표 1·2의1·5 만 등록합니다.
    # 별표 2·3·4 는 B(5억 축)와 k(고시금액 축)가 결합 인쇄되지 않아 짝짓기를 추론하지 않고
    # 등록하지 않습니다(수집 판정 규칙 8). 해당 용역은 LOCAL_RULE_NOT_FOUND 사용자 입력 경로입니다.
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01",
        sido_code="44",
        sido_name="충청남도",
        service_type="FACILITY",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_01,
        description="충청남도 시설분야용역 적격심사 (별표 1)",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "5",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_01,
                base_rate="0.91",
            ),
            _local_price_band(
                None,
                "60",
                "5",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_01,
                base_rate="0.91",
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_01),
        base_rate="0.91",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_2_1",
        sido_code="44",
        sido_name="충청남도",
        service_type="SW_SME",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_2_1,
        description="충청남도 정보통신용역(중소기업자간 경쟁제품 대상) 적격심사 (별표 2의1)",
        lwlt_rate="87.995",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "4",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_2_1,
                base_rate="0.91",
            ),
            _local_price_band(
                None,
                "60",
                "4",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_2_1,
                base_rate="0.91",
            ),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_CHUNGNAM_ATTACH_2_1),
        base_rate="0.91",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05",
        sido_code="44",
        sido_name="충청남도",
        service_type="FISHERY_CLEANUP",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_05,
        description="충청남도 해양환경관리 및 어장관리용역 적격심사 (별표 5)",
        # 별표 5 입찰가격 평점산식은 추정가격 5억원 미만 87.995%, 5억원 이상 80.495%
        # 낙찰하한율을 인쇄합니다(원문 :2334-2366). 공고 하한율이 없으면 이 구간값을 씁니다.
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "5",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_05,
                base_rate="0.91",
                lwlt_rate="87.995",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_05,
                base_rate="0.88",
                lwlt_rate="80.495",
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_05),
        base_rate="0.91",
    ),
    # 전북특별자치도 (부칙 제2024-10호, 시행 2024-01-18) — 서울과 동일 구조
    _local_rule(
        "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01",
        sido_code="52",
        sido_name="전북특별자치도",
        service_type="GENERAL",
        effective_date="2024-01-18",
        source=_SRC_JEONBUK,
        description="전북특별자치도 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 단순노무 외 행은 구간마다 낙찰하한율을 인쇄합니다(원문 :127-145,
        # :357-366, :583-592, :792-799). 10억원 이상은 30억원 경계로 30억원 미만
        # 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_JEONBUK,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEONBUK),
    ),
    _local_rule(
        "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR",
        sido_code="52",
        sido_name="전북특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2024-01-18",
        source=_SRC_JEONBUK,
        description="전북특별자치도 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :140-143).
        price_bands=_four_band_price(_SRC_JEONBUK, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_JEONBUK),
        lwlt_rate="87.745",
    ),
)

# 낙찰방법명·조달분류에서 시·도 별표의 용역 세부유형을 정하는 신호. 자동 확정이 아니라
# 후보를 좁히는 데만 쓰고, 단순노무는 낙찰방법명 표기 또는 사용자 선택으로만 확정합니다(D5).
_METHOD_SERVICE_MARKERS: tuple[tuple[str, str], ...] = (
    ("생활폐기물", "WASTE_HOUSEHOLD"),
    ("폐기물", "WASTE"),
    ("시설분야", "FACILITY"),
    ("보험", "INSURANCE"),
    ("육상운송", "LAND_TRANSPORT"),
    ("여객", "LAND_TRANSPORT"),
    ("화물", "LAND_TRANSPORT"),
    ("소프트웨어", "SW"),
    ("수리ㆍ점검", "REPAIR_INSPECTION"),
    ("수리", "REPAIR_INSPECTION"),
    ("임대차", "LEASE"),
    ("수요기관 지정형", "DEMAND_AGENCY"),
    ("학술연구", "ACADEMIC"),
    ("어장", "FISHERY_CLEANUP"),
)
_PROCUREMENT_SERVICE_MARKERS: tuple[tuple[str, str], ...] = (
    ("폐기물", "WASTE"),
    ("소프트웨어", "SW"),
)
_PROCUREMENT_CLASS_KEYS = (
    "pubPrcrmntLrgClsfcNm",
    "pubPrcrmntMidClsfcNm",
    "pubPrcrmntClsfcNm",
    "pubPrcrmntDtlClsfcNm",
)
_SIMPLE_LABOR_RECOMMEND_KEYWORDS = ("청소", "경비", "시설관리", "주차", "미화")
_FISHERY_CLEANUP_RECOMMEND_KEYWORDS = ("어장정화", "어장정비", "해양쓰레기", "어장")


def resolve_local_service_type(
    raw_data: dict[str, Any] | None, method_name: str | None
) -> tuple[str, str, str | None]:
    """시·도 별표의 용역 세부유형을 (service_type, 근거, 미판정 사유)로 돌려줍니다.

    판정 순서: 낙찰방법명의 단순노무·별표 식별 문자열 -> 조달분류 -> 미판정(GENERAL).
    단순노무 여부는 낙찰방법명에 '단순노무' 가 있을 때만 확정합니다(D5).
    """
    name = method_name or ""
    if "단순노무" in name:
        return "SIMPLE_LABOR", "METHOD_NAME", None
    for marker, service_type in _METHOD_SERVICE_MARKERS:
        if marker in name:
            return service_type, "METHOD_NAME", None
    data = raw_data if isinstance(raw_data, dict) else {}
    class_text = " ".join(str(data.get(key) or "") for key in _PROCUREMENT_CLASS_KEYS)
    for marker, service_type in _PROCUREMENT_SERVICE_MARKERS:
        if marker in class_text:
            return service_type, "PROCUREMENT_CLASS", None
    return "GENERAL", "UNRESOLVED", "낙찰방법명과 조달분류에서 용역 세부유형을 확정하지 못했습니다."


def _recommend_local_service_type(
    raw_data: dict[str, Any] | None, method_name: str | None
) -> str | None:
    """공고명·조달분류 키워드로 어장정화·단순노무 별표를 추천합니다. 확정하지 않습니다."""
    data = raw_data if isinstance(raw_data, dict) else {}
    text = " ".join(
        [
            method_name or "",
            str(data.get("bidNtceNm") or ""),
            *(str(data.get(key) or "") for key in _PROCUREMENT_CLASS_KEYS),
        ]
    )
    for keyword in _FISHERY_CLEANUP_RECOMMEND_KEYWORDS:
        if keyword in text:
            return f"FISHERY_CLEANUP 추천 (공고명·조달분류 키워드 '{keyword}')"
    for keyword in _SIMPLE_LABOR_RECOMMEND_KEYWORDS:
        if keyword in text:
            return f"SIMPLE_LABOR 추천 (공고명·조달분류 키워드 '{keyword}')"
    return None


# 중소기업자간(또는 중소기업간) 경쟁제품 대상/비대상 표기. 세종 SW·육상운송은 같은 별표
# 안에서 대상 여부로 k·낙찰하한율·통과점수가 갈리므로 비대상 규칙과 대상(_SME) 규칙을
# 나눠 두고 이 표기로 하나를 고릅니다. 근거 표기가 없으면 자동 확정하지 않습니다.
_SME_NON_TARGET_MARKER = "비대상"
_SME_TARGET_MARKERS = ("중소기업자간", "중소기업간")
_SME_SERVICE_TYPE_BY_BASE: dict[str, str] = {
    "SW": "SW_SME",
    "LAND_TRANSPORT": "LAND_TRANSPORT_SME",
}


def _classify_sme_competition(text: str) -> str | None:
    """중소기업자간 경쟁제품 대상 여부를 'TARGET'/'NON_TARGET'/None 으로 돌려줍니다.

    '비대상' 이 있으면 대상 표기가 함께 있어도 비대상으로 봅니다. '중소기업자간 경쟁제품
    비대상' 을 대상으로 오인하면 통과점수가 3점 높아져 낙찰 판정이 뒤집힙니다.
    """
    if _SME_NON_TARGET_MARKER in text:
        return "NON_TARGET"
    if any(marker in text for marker in _SME_TARGET_MARKERS):
        return "TARGET"
    return None


def _select_local_rule(
    method_name: str | None,
    raw_data: dict[str, Any] | None,
    *,
    sido_code: str | None,
    sido_name: str | None,
    configured_service_type: str | None = None,
) -> tuple[EvaluationRule | None, str | None, str, list[str]]:
    """LOCAL 규칙 후보를 수요기관 시·도와 용역 세부유형으로 골라 돌려줍니다.

    반환: (규칙, 차단 코드, 사유, 경고). 규칙을 못 고르면 차단 코드와 사유를 채웁니다.
    """
    warnings: list[str] = []

    def _applied(rule: EvaluationRule) -> tuple[EvaluationRule, str | None, str, list[str]]:
        return rule, None, "", list(warnings)

    region_rules = [
        rule
        for rule in LOCAL_RULES
        if _axis_matches(
            rule,
            institution_code=None,
            institution_name=None,
            region_code=sido_code,
            region_name=sido_name,
            contract_regime="LOCAL",
        )
    ]
    if not region_rules:
        return None, BLOCK_CODE_LOCAL_RULE_NOT_FOUND, _LOCAL_NOT_FOUND_MESSAGE, warnings

    if configured_service_type and configured_service_type.strip():
        service_type = configured_service_type.strip().upper()
        basis = "USER_SELECTION"
    else:
        service_type, basis, _ = resolve_local_service_type(raw_data, method_name)

    if basis == "UNRESOLVED":
        general = [rule for rule in region_rules if rule.service_type == "GENERAL"]
        simple = [rule for rule in region_rules if rule.service_type == "SIMPLE_LABOR"]
        if general and simple:
            candidates = general + simple
            warnings.append(
                "후보 별표: "
                + ", ".join(f"{rule.rule_id} ({rule.table_name})" for rule in candidates)
            )
            recommendation = _recommend_local_service_type(raw_data, method_name)
            if recommendation:
                warnings.append(f"추천: {recommendation}")
            return (
                None,
                BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
                "단순노무 여부에 따라 적용 별표가 갈리는데 낙찰방법명에 '단순노무' 표기가 없습니다. "
                "용역 세부유형(local_service_type, 예: GENERAL 또는 SIMPLE_LABOR)을 선택해 주십시오.",
                warnings,
            )
        if general:
            return _applied(general[0])
        if simple:
            return _applied(simple[0])
        recommendation = _recommend_local_service_type(raw_data, method_name)
        if recommendation:
            warnings.append(f"추천: {recommendation}")
        return None, BLOCK_CODE_LOCAL_RULE_NOT_FOUND, _LOCAL_NOT_FOUND_MESSAGE, warnings

    candidates = [rule for rule in region_rules if rule.service_type == service_type]
    sme_type = _SME_SERVICE_TYPE_BY_BASE.get(service_type)
    if basis != "USER_SELECTION" and sme_type:
        sme_candidates = [rule for rule in region_rules if rule.service_type == sme_type]
        if sme_candidates:
            data = raw_data if isinstance(raw_data, dict) else {}
            status = _classify_sme_competition(f"{method_name or ''} {data.get('bidNtceNm') or ''}")
            if status == "TARGET":
                candidates = sme_candidates
            elif status != "NON_TARGET":
                pool = [*candidates, *sme_candidates]
                warnings.append(
                    "후보 별표: "
                    + ", ".join(f"{rule.rule_id} ({rule.table_name})" for rule in pool)
                )
                options = "/".join(sorted({rule.service_type for rule in pool}))
                return (
                    None,
                    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
                    "중소기업자간 경쟁제품 대상/비대상 표기가 없어 적용 별표를 자동 확정하지 "
                    f"못했습니다. 용역 세부유형(local_service_type, 예: {options})을 선택해 주십시오.",
                    warnings,
                )
    if not candidates and service_type != "GENERAL":
        fallback = [rule for rule in region_rules if rule.service_type == "GENERAL"]
        if fallback:
            warnings.append(f"별표 유형 {service_type} 이(가) 없어 일반 별표를 적용했습니다.")
            candidates = fallback
    if not candidates:
        return None, BLOCK_CODE_LOCAL_RULE_NOT_FOUND, _LOCAL_NOT_FOUND_MESSAGE, warnings
    if len(candidates) > 1:
        warnings.append(
            "후보 별표: " + ", ".join(f"{rule.rule_id} ({rule.table_name})" for rule in candidates)
        )
        return (
            None,
            BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
            "같은 조건에 맞는 시·도 별표가 여러 개라 하나를 확정하지 못했습니다.",
            warnings,
        )
    return _applied(candidates[0])


def _normalized_price(value: Decimal | str | float | int | None) -> Decimal | None:
    """추정가격 입력을 구간 판정용 Decimal 로 정규화합니다. 0 이하는 미상으로 봅니다."""
    try:
        price = Decimal(str(value)) if value not in (None, "") else None
    except (ArithmeticError, TypeError, ValueError):
        return None
    return price if price is not None and price > 0 else None


def _band_lwlt_rate(
    rule: EvaluationRule, estimated_price: Decimal | None
) -> tuple[Decimal | None, str | None, str | None]:
    """공고 하한율이 없을 때 쓸 구간 하한율을 고릅니다.

    반환: (하한율, 구간 라벨, 미확정 사유). 셋째 값이 있으면 구간별 하한율이 서로 다른데
    추정가격을 몰라 구간을 고르지 못한 경우이며, 호출부는 규칙 대표값으로 추측하지 않고
    하한율을 미확정으로 남깁니다. 구간 하한율이 없는 규칙은 사유 없이 (None, None, None)
    이라 기존 규칙 대표값 경로가 그대로 유지됩니다.
    """
    bands = rule.price_bands or ()
    band_rates = {band.lwlt_rate for band in bands if band.lwlt_rate is not None}
    if not band_rates:
        return None, None, None
    if estimated_price is None:
        if len(band_rates) == 1:
            return next(iter(band_rates)), None, None
        return (
            None,
            None,
            "추정가격이 없어 구간별로 다른 낙찰하한율을 확정하지 못했습니다. "
            "추정가격을 입력해야 계산할 수 있습니다.",
        )
    band, _, reason = select_price_band(bands, estimated_price)
    if band is None:
        return None, None, reason
    if band.lwlt_rate is None:
        return None, None, None
    return band.lwlt_rate, band.label, None


def _apply_rule_lwlt(
    result: RuleResolutionResult,
    rule: EvaluationRule,
    sucsfbid_lwlt_rate: Decimal | str | float | None,
    estimated_price: Decimal | str | float | int | None = None,
) -> RuleResolutionResult:
    """선택한 규칙으로 하한율을 다시 적용합니다. 공고 하한율이 별표 기본값보다 우선합니다.

    공고 하한율이 없으면 추정가격으로 고른 구간의 하한율을 쓰고, 그 구간에 하한율이 없으면
    규칙 대표값을 씁니다. 다만 구간별 하한율이 서로 다른데 추정가격을 몰라 구간을 고르지
    못하면 대표값으로 추측하지 않고 하한율을 미확정으로 남깁니다.
    """
    parsed: Decimal | None = None
    if sucsfbid_lwlt_rate is not None:
        try:
            text = str(sucsfbid_lwlt_rate).strip()
            if text:
                parsed = Decimal(text)
        except (ArithmeticError, TypeError, ValueError):
            parsed = None
    if parsed is None or parsed <= 0:
        band_rate, band_label, band_reason = _band_lwlt_rate(
            rule, _normalized_price(estimated_price)
        )
        if band_reason is not None:
            return replace(
                result,
                rule=rule,
                effective_lwlt_rate=None,
                rate_source=None,
                warnings=[*result.warnings, band_reason],
            )
        if band_rate is not None:
            label = f", {band_label}" if band_label else ""
            return replace(
                result,
                rule=rule,
                effective_lwlt_rate=band_rate,
                rate_source="RULE_DEFAULT",
                warnings=[
                    *result.warnings,
                    "공고에 낙찰하한율이 명시되지 않아 "
                    f"별표 구간 하한율({band_rate}%{label})을 적용합니다.",
                ],
            )
        return replace(
            result,
            rule=rule,
            effective_lwlt_rate=rule.lwlt_rate,
            rate_source="RULE_DEFAULT",
            warnings=[
                *result.warnings,
                f"공고에 낙찰하한율이 명시되지 않아 별표 기본값({rule.lwlt_rate}%)을 적용합니다.",
            ],
        )
    warnings = list(result.warnings)
    if parsed != rule.lwlt_rate:
        warnings.append(
            f"공고 하한율({parsed}%)이 별표 기본값({rule.lwlt_rate}%)과 일치하지 않아 "
            "공고 하한율을 우선 적용합니다."
        )
    return replace(
        result,
        rule=rule,
        effective_lwlt_rate=parsed,
        rate_source="ANNOUNCEMENT",
        warnings=warnings,
    )


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
BLOCK_CODE_RULE_SCOPE_AMBIGUOUS = "RULE_SCOPE_AMBIGUOUS"
# 지방계약(LOCAL) 전용 차단 코드
BLOCK_CODE_LOCAL_RULE_NOT_FOUND = "LOCAL_RULE_NOT_FOUND"
BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED = "LOCAL_SERVICE_TYPE_UNRESOLVED"

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
    contract_regime: str | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    scope_stage: str | None = None


def extract_contract_regime(
    raw_data: dict[str, Any] | None,
    cntrct_mthd_nm: str | None = None,
    institution_regime: str | None = None,
) -> str | None:
    """계약방법의 명시적 지방 표기를 우선하고 기관 기준정보 판정을 보조값으로 씁니다."""
    data = raw_data if isinstance(raw_data, dict) else {}
    methods = f"{data.get('cntrctCnclsMthdNm') or ''} {cntrct_mthd_nm or ''}"
    return "LOCAL" if "지방" in methods else institution_regime


def _clean_axis_value(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _axis_matches(
    rule: EvaluationRule,
    *,
    institution_code: str | None,
    institution_name: str | None,
    region_code: str | None,
    region_name: str | None,
    contract_regime: str | None,
) -> bool:
    if rule.contract_regime is not None and rule.contract_regime != contract_regime:
        return False
    if rule.institution_scope == RULE_SCOPE_INSTITUTION:
        if rule.institution_code:
            return bool(institution_code and rule.institution_code == institution_code)
        return bool(
            institution_name
            and rule.institution_name
            and re.sub(r"\s+", "", institution_name) == re.sub(r"\s+", "", rule.institution_name)
        )
    if rule.institution_scope == RULE_SCOPE_REGION:
        if rule.region_code:
            return bool(region_code and rule.region_code == region_code)
        return bool(
            region_name
            and rule.region_name
            and re.sub(r"\s+", "", region_name) == re.sub(r"\s+", "", rule.region_name)
        )
    return True


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
    contract_regime: str | None = None,
    institution_code: str | None = None,
    institution_name: str | None = None,
    region_code: str | None = None,
    region_name: str | None = None,
    raw_data: dict[str, Any] | None = None,
    local_service_type: str | None = None,
    estimated_price: Decimal | str | float | int | None = None,
) -> RuleResolutionResult:
    """낙찰방법 출처를 정하고 별표를 판별한 뒤 공고일과 별표 시행일을 대조합니다.

    [추가 판별]
    - 규칙 벌(rules)을 명시하지 않으면 공고일로 시행일 구간 벌을 고릅니다.
      공고일 2026-07-27 이상은 제2026-390호 벌, 2026-05-26 이상은 제2026-260호 벌,
      2025-09-01 이상은 제2025-257호 벌, 2023-05-01 이상은 제2023-53호 벌이며,
      공고일이 없으면 현행인 제2026-390호 벌을 씁니다.
      고른 벌에 이름이 없으면 현행 벌까지 대조하고, 어느 벌에도 없으면 RULE_NOT_FOUND 입니다.
    - 원문 낙찰방법이 '공고서참조'면 sucsfbidMthdCd 계열명으로 판별
    - contract_regime == "LOCAL" 이면 조달청 규칙을 후보에서 배제하고 시·도 자체 별표
      (LOCAL_RULES)만 봅니다. region_code/region_name 은 수요기관 시·도 값입니다(5.4절).
      시·도 규칙이 없으면 LOCAL_RULE_NOT_FOUND 로 차단합니다(D8, 행안부 기본 규칙 없음).
    - 별표가 확정돼도 공고일이 별표 시행일보다 앞서면 계산 차단 (RULE_REGIME_MISMATCH).
      공고일이 없으면 대조하지 않고, 있는데 읽을 수 없으면 차단 대신 경고만 남깁니다.
    - 공고 하한율이 없으면 estimated_price 로 고른 구간의 하한율을 씁니다. 구간별
      하한율이 서로 다른데 추정가격이 없으면 하한율을 확정하지 않고(effective_lwlt_rate
      None) 호출부가 추정가격 입력을 요구합니다.
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
    scope_stage: str | None = None
    if (
        contract_regime == "LOCAL"
        and result.block_reason_code in (None, BLOCK_CODE_RULE_NOT_FOUND)
        and not (
            result.rule is not None and result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
        )
    ):
        selected, local_code, local_reason, local_warnings = _select_local_rule(
            method_name,
            raw_data,
            sido_code=region_code,
            sido_name=region_name,
            configured_service_type=local_service_type,
        )
        if selected is None:
            result = replace(
                result,
                is_blocked=True,
                block_reason_code=local_code,
                block_reason_message=local_reason,
                rule=None,
                effective_lwlt_rate=None,
                rate_source=None,
                warnings=[*result.warnings, *local_warnings],
            )
        else:
            # 시·도 규칙을 확정했으므로 조달청 매칭 단계에서 세워진 RULE_NOT_FOUND 차단을
            # 해제합니다. 이 플래그를 남기면 아래 조기 반환이 유효한 규칙을 차단합니다.
            result = replace(
                _apply_rule_lwlt(result, selected, sucsfbid_lwlt_rate, estimated_price),
                is_blocked=False,
                block_reason_code=None,
                block_reason_message=None,
            )
            if local_warnings:
                result = replace(result, warnings=[*result.warnings, *local_warnings])
            scope_stage = RULE_SCOPE_REGION
    elif result.rule is not None and result.rule.rule_id != "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT":
        matching_rules = [
            candidate
            for candidate in allocated_rules
            if candidate.service_type == result.rule.service_type
            and match_rule_by_mthd_nm(method_name or "", rules=(candidate,)) is not None
        ]
        base_specificity = max(
            (
                len(normalize_pattern_string(pattern))
                for pattern in result.rule.patterns
                if pattern in (method_name or "")
                or normalize_pattern_string(pattern) in normalize_pattern_string(method_name or "")
            ),
            default=0,
        )
        matching_rules = [
            candidate
            for candidate in matching_rules
            if any(
                len(normalize_pattern_string(pattern)) == base_specificity
                and (
                    pattern in (method_name or "")
                    or normalize_pattern_string(pattern)
                    in normalize_pattern_string(method_name or "")
                )
                for pattern in candidate.patterns
            )
            and _axis_matches(
                candidate,
                institution_code=institution_code,
                institution_name=institution_name,
                region_code=region_code,
                region_name=region_name,
                contract_regime=contract_regime,
            )
        ]
        for stage in (RULE_SCOPE_INSTITUTION, RULE_SCOPE_REGION, RULE_SCOPE_ALL):
            stage_rules = [rule for rule in matching_rules if rule.institution_scope == stage]
            if len(stage_rules) > 1:
                result = replace(
                    result,
                    is_blocked=True,
                    block_reason_code=BLOCK_CODE_RULE_SCOPE_AMBIGUOUS,
                    block_reason_message=f"{stage} 범위에 일치하는 적격심사 규칙이 여러 개입니다.",
                    rule=None,
                    effective_lwlt_rate=None,
                    rate_source=None,
                )
                scope_stage = stage
                break
            if stage_rules:
                selected = stage_rules[0]
                if result.rate_source == "RULE_DEFAULT":
                    warnings = [
                        warning
                        for warning in result.warnings
                        if not warning.startswith("공고에 낙찰하한율이 명시되지 않아 별표 기본값(")
                    ]
                    warnings.append(
                        f"공고에 낙찰하한율이 명시되지 않아 별표 기본값({selected.lwlt_rate}%)을 적용합니다."
                    )
                    result = replace(
                        result,
                        rule=selected,
                        effective_lwlt_rate=selected.lwlt_rate,
                        warnings=warnings,
                    )
                else:
                    result = replace(result, rule=selected)
                scope_stage = stage
                break
        if scope_stage is None:
            result = replace(
                result,
                is_blocked=True,
                block_reason_code=BLOCK_CODE_RULE_NOT_FOUND,
                block_reason_message="공고의 판정 문맥에 일치하는 적격심사 규칙이 없습니다.",
                rule=None,
                effective_lwlt_rate=None,
                rate_source=None,
            )
    elif result.rule is not None:
        scope_stage = RULE_SCOPE_ALL
    result = replace(
        result,
        method_source=method_source,
        warnings=method_warnings + result.warnings,
        contract_regime=contract_regime,
        institution_code=institution_code,
        institution_name=institution_name,
        region_code=region_code,
        region_name=region_name,
        scope_stage=scope_stage,
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
    institution_name_fallback: str | None = None,
    cntrct_mthd_nm: str | None = None,
    institution_regime: str | None = None,
    region_code: str | None = None,
    region_name: str | None = None,
    local_service_type: str | None = None,
    estimated_price: Decimal | str | float | int | None = None,
) -> RuleResolutionResult:
    """raw_data 딕셔너리에서 기관 필드를 추출하여 적격심사 규칙을 판별합니다.

    rules 를 명시하지 않으면 bidNtceDt 로 고른 시행일 구간 벌로 판별합니다.
    region_code/region_name 은 LOCAL 판정에서 수요기관 시·도 값을 담습니다(5.4절).
    local_service_type 은 사용자가 고른 시·도 별표 세부유형(D5)입니다.
    estimated_price 는 구간별 낙찰하한율을 고르는 추정가격입니다.
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
        contract_regime=extract_contract_regime(raw_data, cntrct_mthd_nm, institution_regime),
        institution_code=_clean_axis_value(raw_data.get("dminsttCd")),
        institution_name=(
            _clean_axis_value(raw_data.get("dminsttNm"))
            or _clean_axis_value(institution_name_fallback)
        ),
        region_code=_clean_axis_value(region_code),
        region_name=_clean_axis_value(region_name),
        raw_data=raw_data,
        local_service_type=local_service_type,
        estimated_price=estimated_price,
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

# 배점한도 합계(합계 100 정합성)에서 제외하는 항목 종류입니다. 원문 배점표는 신인도를
# 가점/감점 범위로만 적고 계·합계에는 0으로 산입하며(docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:44),
# 결격사유(-20)는 감점 항목이라 별도 심사번호로 분리합니다. 두 항목을 빼고 더한 값이
# 배점표의 합계 100 과 같아야 합니다.
QUANT_LIMIT_KIND_TOTAL_EXCLUDED: frozenset[str] = frozenset(
    {QUANT_LIMIT_KIND_REPUTATION, QUANT_LIMIT_KIND_DISQUALIFICATION}
)
QUANT_FIXED_TOTAL_LIMIT = Decimal("100")

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
_QUANT_NOTE_REPUTATION = (
    "신인도는 가점 상한 4.25·감점 상한 -5.0 범위이며 원문 계·합계에는 0으로 산입됩니다."
)
_QUANT_NOTE_RANGE_TOTAL = (
    "별표 9 는 수요기관이 심사분야별 배점한도를 20% 범위에서 조정하고 입찰가격을 60~70 사이에서 "
    "정하므로 항목 상한 합계가 100 과 다릅니다. 합계 100 은 수요기관 선택값으로 정해집니다."
)

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
    """추정가격 구간 하나의 심사항목 배점한도 묶음.

    total_is_fixed 가 True 면 신인도·결격사유를 뺀 항목 배점한도 합이 total_limit 과
    같아야 합니다. 별표 9 처럼 수요기관이 배점을 정하는 범위 구조는 False 이며,
    합계 100 을 항목 상한 합으로 검증하지 않습니다.
    """

    band_key: str
    band_label: str
    items: tuple[QuantScoreItem, ...]
    total_limit: Decimal
    total_is_fixed: bool = True


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
    """신인도 항목. 가점 상한 4.25·감점 상한 -5.0 범위이며 계·합계에는 0으로 산입합니다.

    원문 배점표가 신인도를 가감분으로만 적고 계·합계에는 0을 넣으므로, 배점한도 합계에
    산입되는 limit 은 두지 않습니다. 가점 상한은 REPUTATION_MAX_BONUS 로만 노출합니다.
    """
    return _qi(
        section_no,
        section_name,
        QUANT_ITEM_REPUTATION,
        "신인도",
        None,
        kind=QUANT_LIMIT_KIND_REPUTATION,
        limit_min=Decimal("-5"),
        note=_QUANT_NOTE_REPUTATION,
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
    total_limit: Decimal = QUANT_FIXED_TOTAL_LIMIT,
    total_is_fixed: bool = True,
) -> QuantScoreBand:
    """구간 하나를 만듭니다. 심사분야별 항목 묶음을 순서대로 이어 붙입니다."""
    items = tuple(item for group in groups for item in group)
    return QuantScoreBand(
        band_key=band_key,
        band_label=QUANT_BAND_LABELS[band_key],
        items=items,
        total_limit=total_limit,
        total_is_fixed=total_is_fixed,
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

    원문이 범위로 표기하므로 limit 은 상한, limit_min 은 하한입니다. 항목 상한을 모두
    더하면 165 이지만 합계 100 은 수요기관이 범위 안에서 정하므로, 별표 1~5의2 처럼
    항목 합으로 검증하지 않습니다(total_is_fixed=False).
    """
    return QuantScoreTable(
        attachment="별표 9",
        table_name="수요기관 지정형 적격심사",
        source=_QUANT_SRC_ATTACH,
        note=_QUANT_NOTE_RANGE_TOTAL,
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
                total_is_fixed=False,
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
    LOCAL 시·도 규칙처럼 기관 정량 배점표를 아직 반영하지 않은 규칙(quant_basis != REGISTRY)은
    조달청 배점표를 잘못 적용하지 않도록 무조건 None 을 돌려줍니다.
    """
    if rule.quant_basis != QUANT_BASIS_REGISTRY:
        return None
    suffix = "_".join(rule.rule_id.rsplit("_", 2)[-2:])
    return QUANT_SCORE_TABLES.get(suffix)


def quant_band_scored_limit_total(band: QuantScoreBand) -> Decimal:
    """구간의 배점한도 합계. 신인도(가감분)와 결격사유(감점)는 산입하지 않습니다.

    원문 배점표는 신인도를 계·합계에 0으로 넣고 결격사유는 별도 심사번호로 분리합니다
    (docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:44,57). 두 항목을 빼고
    남은 배점한도를 더한 값이 별표 합계 100 과 같아야 합니다.
    """
    return sum(
        (
            item.limit
            for item in band.items
            if item.limit is not None and item.limit_kind not in QUANT_LIMIT_KIND_TOTAL_EXCLUDED
        ),
        Decimal("0"),
    )


@dataclass(frozen=True)
class QuantTotalAuditRow:
    """구간별 배점한도 합계 점검 한 줄.

    같은 별표를 고시금액 미만 전용 규칙과 공용 규칙이 함께 쓰므로(예: ATTACH_06·ATTACH_07)
    별표명만으로는 구간을 특정할 수 없습니다. table_key(규칙 ID 접미사)를 함께 갖습니다.
    """

    table_key: str
    attachment: str
    band_key: str
    scored_limit_total: Decimal
    total_limit: Decimal
    total_is_fixed: bool


def quant_score_tables_total_audit() -> tuple[QuantTotalAuditRow, ...]:
    """QUANT_SCORE_TABLES 의 모든 구간 합계를 신인도·결격사유 제외로 계산해 돌려줍니다."""
    return tuple(
        QuantTotalAuditRow(
            table_key=table_key,
            attachment=table.attachment,
            band_key=band.band_key,
            scored_limit_total=quant_band_scored_limit_total(band),
            total_limit=band.total_limit,
            total_is_fixed=band.total_is_fixed,
        )
        for table_key, table in QUANT_SCORE_TABLES.items()
        for band in table.bands
    )


def select_quant_band(
    table: QuantScoreTable,
    estimated_price: Decimal | int | float | str | None,
    method_name: str | None = None,
) -> tuple[QuantScoreBand | None, str | None]:
    """공식 기준인 추정가격 또는 낙찰방법명 표기로 5억원 구간을 고릅니다.

    구간이 하나면 추정가격과 무관하게 그 구간을 쓰고, 구간이 둘인데 추정가격을 읽을
    수 없으면 임의로 고르지 않고 사유와 함께 None 을 돌려줍니다.
    """
    if len(table.bands) == 1:
        return table.bands[0], None
    method_side = method_name_500m_side(method_name)
    price = None
    try:
        price = Decimal(str(estimated_price)) if estimated_price not in (None, "") else None
        if price is not None and price <= 0:
            price = None
    except (ArithmeticError, TypeError, ValueError):
        price = None
    price_side = None if price is None else price >= QUANT_ESTIMATED_PRICE_THRESHOLD
    if method_side is not None:
        note = None
        if price_side is not None and method_side != price_side:
            note = "낙찰방법명 구간과 추정가격의 정량평가 판정이 달라 낙찰방법명을 적용했습니다."
        band_key = QUANT_BAND_OVER_500M if method_side else QUANT_BAND_UNDER_500M
        return (
            next((band, note) for band in table.bands if band.band_key == band_key)
            if any(band.band_key == band_key for band in table.bands)
            else (None, "낙찰방법명 구간에 대응하는 배점표 구간이 없습니다.")
        )
    if price_side is None:
        return (
            None,
            "공고 추정가격이 없어 배점표 구간(추정가격 5억원 이상/미만)을 정할 수 없습니다. 공고서의 추정가격을 확인하십시오.",
        )
    band_key = QUANT_BAND_OVER_500M if price_side else QUANT_BAND_UNDER_500M
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
