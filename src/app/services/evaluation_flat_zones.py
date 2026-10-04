"""
src/app/services/evaluation_flat_zones.py

지방계약(시·도) 일반용역 적격심사 별표 원문의 평탄 구간 규정 데이터 모듈.

[평탄 규정 의미]
입찰가격/예정가격 비율 x 가 flat_ratio 이상이면 가격평점은 flat_score 로 고정됩니다.
즉 기준비율(base_rate) 위쪽으로 투찰해 산식값이 flat_score 보다 낮아지더라도 점수는
flat_score 아래로 내려가지 않습니다. flat_ratio 는 항상 기준비율보다 큽니다.

[출처 원칙]
모든 구간은 원문 평탄 문장이 인용된 수집 문서를 source 로 남깁니다. 원문 인용을 찾지 못한
규칙(조달청 PRE/POST 별표 등)은 데이터를 넣지 않습니다. 추정·역산하지 않습니다.

이 모듈은 순수 데이터·조회 함수만 제공하며 산식 계산은 evaluation_scoring 이 담당합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_COLLECTION = "docs/analysis/servc_formula_collection_local_20261004.md"


@dataclass(frozen=True)
class FlatZone:
    """별표 한 구간의 평탄 규정.

    flat_ratio: 이 비율(비율값, 예: 0.8825) 이상이면 평점이 고정됩니다.
    flat_score: 고정되는 평점.
    source: 원문 평탄 문장 근거(문서 경로:행 범위).
    """

    flat_ratio: Decimal
    flat_score: Decimal
    source: str


def _zone(ratio: str, score: str, source: str) -> FlatZone:
    return FlatZone(flat_ratio=Decimal(ratio), flat_score=Decimal(score), source=source)


# 수집 문서 4.2~4.12 의 원문 평탄 문장 절을 규칙별 source 로 씁니다.
_SRC_INCHEON = f"{_COLLECTION}:136-144 (4.2 인천광역시 별표 1 평탄 문장)"
_SRC_JEJU = f"{_COLLECTION}:162-171 (4.3 제주특별자치도 별표 1 평탄 문장)"
_SRC_GANGWON = f"{_COLLECTION}:189-198 (4.4 강원특별자치도 별표 1 평탄 문장)"
_SRC_SEJONG = f"{_COLLECTION}:239-245 (4.6 세종특별자치시 별표 2·4·4의2 평탄 문장)"
_SRC_GB = f"{_COLLECTION}:263-271 (4.7 경상북도 별표 1~4 평탄 문장)"
_SRC_ULSAN = f"{_COLLECTION}:289-304 (4.8 울산광역시 별표 1·1-1·2 평탄 문장)"
_SRC_CB = f"{_COLLECTION}:322-331 (4.9 충청북도 별표 1 평탄 문장)"
_SRC_JNGJ = f"{_COLLECTION}:349-369 (4.10 전남광주통합특별시 별표 1~6 평탄 문장)"
_SRC_GN = f"{_COLLECTION}:387-392 (4.11 경상남도 별표 1 평탄 문장)"
_SRC_DAEGU = f"{_COLLECTION}:218-221 (4.5 대구광역시 별표 1 단순노무 평탄 문장)"
_SRC_GG = f"{_COLLECTION}:427-461 (4.12 경기도 별표 1-2~1-6 평탄 문장)"


def _four_band_general(source: str) -> dict[Decimal | None, FlatZone]:
    """B 30/50/70/90, k 1/2/4/20 구간의 일반 산식 평탄."""
    return {
        Decimal("200000000"): _zone("0.8825", "85", source),
        Decimal("500000000"): _zone("0.8925", "65", source),
        Decimal("1000000000"): _zone("0.905", "45", source),
        None: _zone("0.98", "20", source),
    }


def _four_band_simple_labor(source: str) -> dict[Decimal | None, FlatZone]:
    """단순노무 행(k 전 구간 20)의 평탄. 평탄 비율은 전 구간 88.25%."""
    return {
        Decimal("200000000"): _zone("0.8825", "85", source),
        Decimal("500000000"): _zone("0.8825", "65", source),
        Decimal("1000000000"): _zone("0.8825", "45", source),
        None: _zone("0.8825", "25", source),
    }


# rule_id -> {PriceBand.upper_bound: FlatZone}. upper_bound None 은 상한 없는 마지막 구간입니다.
_FLAT_ZONES: dict[str, dict[Decimal | None, FlatZone]] = {
    # 인천광역시 (예규 제488호)
    "SERVC_LOCAL_INCHEON_20251224_ATTACH_01": _four_band_general(_SRC_INCHEON),
    "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR": _four_band_simple_labor(_SRC_INCHEON),
    # 제주특별자치도 (예규 제82호) — 인천과 동일
    "SERVC_LOCAL_JEJU_20240101_ATTACH_01": _four_band_general(_SRC_JEJU),
    "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR": _four_band_simple_labor(_SRC_JEJU),
    # 강원특별자치도 (예규 제832호) — 인천과 동일
    "SERVC_LOCAL_GANGWON_20230611_ATTACH_01": _four_band_general(_SRC_GANGWON),
    "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR": _four_band_simple_labor(_SRC_GANGWON),
    # 세종특별자치시 (예규 제32호) — 시설·폐기물·생활폐기물. SW·육상운송은 평탄 점수 미인쇄로 제외
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_02": {
        Decimal("500000000"): _zone("0.8825", "55", _SRC_SEJONG),
        None: _zone("0.8825", "45", _SRC_SEJONG),
    },
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_04": {
        Decimal("500000000"): _zone("0.8825", "55", _SRC_SEJONG),
        None: _zone("0.8825", "45", _SRC_SEJONG),
    },
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2": {
        Decimal("500000000"): _zone("0.8825", "55", _SRC_SEJONG),
        None: _zone("0.8825", "45", _SRC_SEJONG),
    },
    # 경상북도 (예규 제1571호)
    "SERVC_LOCAL_GB_20260108_ATTACH_01": {
        Decimal("500000000"): _zone("0.8825", "65", _SRC_GB),
        None: _zone("0.8825", "45", _SRC_GB),
    },
    "SERVC_LOCAL_GB_20260108_ATTACH_02": {
        Decimal("500000000"): _zone("0.91", "68", _SRC_GB),
        None: _zone("0.91", "48", _SRC_GB),
    },
    "SERVC_LOCAL_GB_20260108_ATTACH_03": {
        Decimal("500000000"): _zone("0.8825", "65", _SRC_GB),
        None: _zone("0.8925", "45", _SRC_GB),
    },
    "SERVC_LOCAL_GB_20260108_ATTACH_04": {
        Decimal("500000000"): _zone("0.8825", "65", _SRC_GB),
        None: _zone("0.8925", "45", _SRC_GB),
    },
    # 울산광역시 (공고 제2022-1100호)
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_01": _four_band_general(_SRC_ULSAN),
    "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR": _four_band_simple_labor(_SRC_ULSAN),
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1": {
        Decimal("1000000000"): _zone("0.8825", "65", _SRC_ULSAN),
        Decimal("3000000000"): _zone("0.8825", "45", _SRC_ULSAN),
        None: _zone("0.8825", "20", _SRC_ULSAN),
    },
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_02": _four_band_general(_SRC_ULSAN),
    # 충청북도 (공고 제2023-1428호)
    "SERVC_LOCAL_CB_20231020_ATTACH_01": _four_band_general(_SRC_CB),
    "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR": _four_band_simple_labor(_SRC_CB),
    # 전남광주통합특별시 (예규 제3호)
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_01": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8825", "65", _SRC_JNGJ),
        None: _zone("0.8825", "45", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_02": {
        Decimal("200000000"): _zone("0.8825", "75", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8925", "65", _SRC_JNGJ),
        None: _zone("0.905", "45", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_03": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8825", "75", _SRC_JNGJ),
        None: _zone("0.93", "25", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_04": {
        Decimal("1000000000"): _zone("0.8825", "65", _SRC_JNGJ),
        Decimal("3000000000"): _zone("0.8825", "40", _SRC_JNGJ),
        None: _zone("0.8825", "15", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_05": {
        Decimal("200000000"): _zone("0.905", "75", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.905", "65", _SRC_JNGJ),
        None: _zone("0.905", "55", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_06": _four_band_general(_SRC_JNGJ),
    # 경상남도 (공고 제2023-23호)
    "SERVC_LOCAL_GN_20230105_ATTACH_01": _four_band_general(_SRC_GN),
    # 대구광역시 (예규 제238호) — 단순노무만. 원문 평탄 점수 미인쇄, 산식 대입값을 씁니다.
    "SERVC_LOCAL_DAEGU_20260511_ATTACH_01": {
        Decimal("200000000"): _zone("0.8825", "55", _SRC_DAEGU),
        None: _zone("0.8825", "45", _SRC_DAEGU),
    },
    # 경기도 (예규 제748호) — 별표 1-2~1-6. 별표 1-5(보험)는 평탄 문장 없음
    "SERVC_LOCAL_GG_20250808_ATTACH_1_2": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_GG),
        Decimal("500000000"): _zone("0.8925", "45", _SRC_GG),
        Decimal("1000000000"): _zone("0.905", "45", _SRC_GG),
        None: _zone("0.98", "20", _SRC_GG),
    },
    "SERVC_LOCAL_GG_20250808_ATTACH_1_3": {
        Decimal("200000000"): _zone("0.8825", "65", _SRC_GG),
        Decimal("500000000"): _zone("0.8925", "55", _SRC_GG),
        Decimal("1000000000"): _zone("0.905", "45", _SRC_GG),
        None: _zone("0.98", "20", _SRC_GG),
    },
    "SERVC_LOCAL_GG_20250808_ATTACH_1_4": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_GG),
        Decimal("500000000"): _zone("0.8825", "65", _SRC_GG),
        Decimal("1000000000"): _zone("0.8925", "45", _SRC_GG),
        None: _zone("0.905", "20", _SRC_GG),
    },
    "SERVC_LOCAL_GG_20250808_ATTACH_1_6": _four_band_general(_SRC_GG),
}


def flat_zone_for(rule_id: str, upper_bound: Decimal | int | str | None) -> FlatZone | None:
    """규칙과 선택된 가격 구간(PriceBand.upper_bound)의 평탄 규정을 돌려줍니다.

    평탄 데이터가 없는 규칙·구간이면 None 을 돌려주며, 호출부는 이때 평탄을 적용하지
    않아 기존 동작과 완전히 같게 됩니다.
    """
    zones = _FLAT_ZONES.get(rule_id)
    if not zones:
        return None
    if upper_bound is None:
        return zones.get(None)
    return zones.get(Decimal(str(upper_bound)))


def flat_zone_entries() -> tuple[tuple[str, Decimal | None, FlatZone], ...]:
    """등록된 평탄 구간 전량을 (rule_id, upper_bound, FlatZone) 로 돌려줍니다."""
    return tuple(
        (rule_id, upper_bound, zone)
        for rule_id, zones in _FLAT_ZONES.items()
        for upper_bound, zone in zones.items()
    )
