"""
src/app/services/evaluation_rules_core.py

적격심사 규칙 레지스트리의 공통 자료형과 상수.
시·도 규칙 모듈과 기관 규칙 모듈이 함께 쓰는 EvaluationRule 자료형과 구간 검증
도우미를 담습니다. 순환 import 를 피하기 위해 조달청 규칙과 선택 로직은 이
모듈에 두지 않습니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

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
    # 원문이 배점한도를 용역 유형(계량화 정도 등)별로 여러 값으로 인쇄한 구간은 하나를
    # 고르지 않고 None 으로 두며, 그 사실을 label·source 에 남깁니다(예: 한국가스공사).
    max_price_score: Decimal | None
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


def _validate_bands(bands: Sequence[Any], *, axis: str, allow_bounded_top: bool = False) -> None:
    """구간 목록의 순서와 상한 규칙을 검사합니다.

    원칙적으로 마지막 구간은 상한이 없어야 합니다. 원문이 마지막 구간의 상한까지 인쇄한
    규칙만 allow_bounded_top 으로 그 사실을 선언하며, 그보다 큰 추정가격은 구간을 고르지
    못해 계산이 차단됩니다.
    """
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
    if not allow_bounded_top and bands and bands[-1].upper_bound is not None:
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
    # 원문이 마지막 구간의 상한까지 인쇄한 규칙은 True 로 두어, 그보다 큰 추정가격이 어느
    # 구간에도 들지 않아 계산이 차단됨을 선언합니다(예: 국토교통부 감리용역 10억원 미만).
    bounded_price_top: bool = False
    quant_basis: str = QUANT_BASIS_REGISTRY
    score_table_source: str | None = None
    contract_regime: str | None = None
    institution_scope: str = RULE_SCOPE_ALL
    institution_code: str | None = None
    institution_name: str | None = None
    # 원문이 함께 쓰는 기관 이름(예: 국가유산청-문화재청). 공고에 코드가 없을 때만 씁니다.
    institution_aliases: tuple[str, ...] = ()
    # 이 규칙의 효력이 끝나는 시행일. 시·도 구판 별표처럼 후속 규칙이 시행돼 폐지된 규칙에만
    # 적고, 공고일이 그 날짜 이상이면 같은 세부유형 후보에서 밀립니다(현행 규칙은 None).
    superseded_date: str | None = None
    # 원문 적용 범위 조항이 적용 주체에 하위 조직(지역본부·지사·사업소·소속기관)을 명시한
    # 기관만 선언합니다. 정확 일치가 실패한 뒤의 2차 판정에만 쓰며, 코드 대역을 선언한
    # 규칙은 코드가 이름보다 우선합니다.
    subunit_name_prefixes: tuple[str, ...] = ()
    subunit_code_prefixes: tuple[str, ...] = ()
    region_code: str | None = None
    region_name: str | None = None
    # 대구 세부기준 원문은 '폐기물처리용역 … 이 경우 건설폐기물 처리용역은 제외한다' 고 정의한다.
    # 낙찰방법명이 환경부고시 건설폐기물 띠 표기에 맞는 공고에는 대구 폐기물 규칙을 적용하지
    # 않도록 _select_local_rule 에서 select_moe_cdw_rule(method_name) 이 None 이 아닐 때 후보에서
    # 뺀다. 기본값 False 이며 대구 폐기물 두 규칙만 True 로 둔다.
    cdw_exclusion: str | None = None

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
            _validate_bands(
                self.price_bands, axis="PriceBand", allow_bounded_top=self.bounded_price_top
            )
        if self.threshold_bands is not None:
            if self.pass_threshold is not None:
                raise ValueError("threshold_bands 와 pass_threshold 는 동시에 선언할 수 없습니다.")
            if not self.threshold_bands:
                raise ValueError("threshold_bands 는 최소 한 구간이 필요합니다.")
            _validate_bands(
                self.threshold_bands, axis="ThresholdBand", allow_bounded_top=self.bounded_price_top
            )
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
        if (self.subunit_name_prefixes or self.subunit_code_prefixes) and (
            self.institution_scope != RULE_SCOPE_INSTITUTION
        ):
            raise ValueError("하위 조직 확장은 INSTITUTION 규칙에만 선언할 수 있습니다.")
