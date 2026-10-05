"""
src/app/services/evaluation_flat_zones.py

지방계약(시·도) 일반용역 적격심사 별표 원문의 평탄 구간 규정 데이터 모듈.

[평탄 규정 의미]
입찰가격/예정가격 비율 x 가 flat_ratio 이상이면 가격평점은 flat_score 로 고정됩니다.
즉 기준비율(base_rate) 위쪽으로 투찰해 산식값이 flat_score 보다 낮아지더라도 점수는
flat_score 아래로 내려가지 않습니다. flat_ratio 는 항상 기준비율보다 큽니다.

[출처 원칙]
모든 구간은 원문 평탄 문장이 인용된 수집 문서를 source 로 남깁니다. 원문 인용이 없는
규칙(조달청 별표 6 보험, 일반 띠 3개, 기술용역)은 데이터를 넣지 않습니다. 추정·역산하지
않습니다. 조달청 PRE/POST 별표는 수집 문서의 평탄 비율과 산식 대입 점수를 등록합니다.

이 모듈은 순수 데이터·조회 함수만 제공하며 산식 계산은 evaluation_scoring 이 담당합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_COLLECTION = "docs/analysis/servc_formula_collection_local_20261004.md"
_RECOVER = "docs/analysis/servc_formula_recover_c_20261005.md"


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

# 2단계 추가 5곳은 재수집 문서 절과 EXT 원문 행을 함께 인용합니다. 충남은 원문이 비율만
# 인쇄하고 점수는 미인쇄라 flat_score 가 산식 대입값입니다.
_SRC_SEOUL = (
    f"{_RECOVER}:90-99 (4.1 서울특별시 별표 1~4 평탄 문장); "
    "EXT/seoul/seoul_general_2024_08_12.tbl.txt:379-384,722-727,1065-1070,1318-1323"
)
_SRC_BUSAN = (
    f"{_RECOVER}:121-128 (4.2 부산광역시 별표 1 평탄 문장); "
    "EXT/busan/busan_general_2025_1981.txt:149-150"
)
_SRC_DAEJEON = (
    f"{_RECOVER}:161-164 (4.3 대전광역시 별표 6 소프트웨어류 10억원 이상 평탄 문장); "
    "EXT/daejeon/daejeon_2025_9528.txt:262"
)
_SRC_CHUNGNAM_01 = (
    f"{_RECOVER}:188 (4.4 충청남도 별표 1 시설분야 평탄 문장, 점수 미인쇄 대입값); "
    "EXT/chungnam/chungnam_2026_1235.txt:551-560; EXT/chungnam/chungnam_tables.txt:2-18"
)
_SRC_CHUNGNAM_2_1 = (
    f"{_RECOVER}:191 (4.4 충청남도 별표 2의1 정보통신 대상 평탄 문장, 점수 미인쇄 대입값); "
    "EXT/chungnam/chungnam_2026_1235.txt:1172-1180; EXT/chungnam/chungnam_tables.txt:47-63"
)
_SRC_CHUNGNAM_05 = (
    f"{_RECOVER}:197-198 (4.4 충청남도 별표 5 해양환경·어장관리 평탄 문장, 점수 미인쇄 대입값); "
    "EXT/chungnam/chungnam_2026_1235.txt:2334-2366; EXT/chungnam/chungnam_tables.txt:137-158"
)
_SRC_JEONBUK = (
    f"{_RECOVER}:220-226 (4.5 전북특별자치도 별표 1 평탄 문장); "
    "EXT/jeonbuk/jb_general_2024_10.tbl.txt:127-145,357-366,583-592,792-799"
)
_SRC_SEJONG_SW = (
    f"{_COLLECTION}:225-247 (4.6 세종특별자치시 별표 2~5); "
    "EXT/sejong/byp3_sw_2025.txt:16-34 (비대상 95.5%, 대상 91%; 점수 미인쇄 대입값)"
)
_SRC_SEJONG_LT = (
    f"{_COLLECTION}:225-247 (4.6 세종특별자치시 별표 2~5); "
    "EXT/sejong/byp5_2025.txt:19-34 (비대상 95.5%, 대상 91%; 점수 미인쇄 대입값)"
)


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


def _five_band_general(source: str) -> dict[Decimal | None, FlatZone]:
    """10억원 이상을 30억원 경계로 나눈 5구간의 일반 산식 평탄.

    30억원 미만·이상 두 구간 모두 원래 10억원 이상 구간의 평탄(98% -> 20점)을 씁니다.
    """
    return {
        Decimal("200000000"): _zone("0.8825", "85", source),
        Decimal("500000000"): _zone("0.8925", "65", source),
        Decimal("1000000000"): _zone("0.905", "45", source),
        Decimal("3000000000"): _zone("0.98", "20", source),
        None: _zone("0.98", "20", source),
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
    # 세종특별자치시 (예규 제32호) — 시설·폐기물·생활폐기물. SW·육상운송은 점수 미인쇄라
    # 산식 대입값(비대상 95.5%, 대상 91%)을 씁니다.
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
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03": {
        Decimal("500000000"): _zone("0.955", "55", _SRC_SEJONG_SW),
        None: _zone("0.955", "45", _SRC_SEJONG_SW),
    },
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME": {
        Decimal("500000000"): _zone("0.91", "58", _SRC_SEJONG_SW),
        None: _zone("0.91", "48", _SRC_SEJONG_SW),
    },
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05": {
        Decimal("500000000"): _zone("0.955", "55", _SRC_SEJONG_LT),
        None: _zone("0.955", "45", _SRC_SEJONG_LT),
    },
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME": {
        Decimal("500000000"): _zone("0.91", "58", _SRC_SEJONG_LT),
        None: _zone("0.91", "48", _SRC_SEJONG_LT),
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
    # 별표 4 는 공고 실측 구간 하한율을 붙이려고 5억원 미만/이상 두 행을 2억·10억에서
    # 나눴습니다. 나눈 구간은 원래 행의 평탄을 그대로 쓰므로 같은 값을 키만 늘려 둡니다.
    "SERVC_LOCAL_GB_20260108_ATTACH_04": {
        Decimal("200000000"): _zone("0.8825", "65", _SRC_GB),
        Decimal("500000000"): _zone("0.8825", "65", _SRC_GB),
        Decimal("1000000000"): _zone("0.8925", "45", _SRC_GB),
        None: _zone("0.8925", "45", _SRC_GB),
    },
    # 울산광역시 (공고 제2022-1100호)
    # 30억원 분할 키는 분할 전 10억원 이상 구간(None)과 같은 평탄 값을 씁니다.
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_01": {
        **_four_band_general(_SRC_ULSAN),
        Decimal("3000000000"): _zone("0.98", "20", _SRC_ULSAN),
    },
    "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR": _four_band_simple_labor(_SRC_ULSAN),
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1": {
        Decimal("1000000000"): _zone("0.8825", "65", _SRC_ULSAN),
        Decimal("3000000000"): _zone("0.8825", "45", _SRC_ULSAN),
        None: _zone("0.8825", "20", _SRC_ULSAN),
    },
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_02": {
        **_four_band_general(_SRC_ULSAN),
        Decimal("3000000000"): _zone("0.98", "20", _SRC_ULSAN),
    },
    # 충청북도 (공고 제2023-1428호)
    "SERVC_LOCAL_CB_20231020_ATTACH_01": {
        **_four_band_general(_SRC_CB),
        Decimal("3000000000"): _zone("0.98", "20", _SRC_CB),
    },
    "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR": _four_band_simple_labor(_SRC_CB),
    # 전남광주통합특별시 (예규 제3호)
    # 별표 2·3·5·6 의 10억·30억 분할 키는 분할 전 5억원 이상 구간(None)과 같은 평탄 값을 씁니다.
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_01": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8825", "65", _SRC_JNGJ),
        None: _zone("0.8825", "45", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_02": {
        Decimal("200000000"): _zone("0.8825", "75", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8925", "65", _SRC_JNGJ),
        Decimal("1000000000"): _zone("0.905", "45", _SRC_JNGJ),
        Decimal("3000000000"): _zone("0.905", "45", _SRC_JNGJ),
        None: _zone("0.905", "45", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_03": {
        Decimal("200000000"): _zone("0.8825", "85", _SRC_JNGJ),
        Decimal("500000000"): _zone("0.8825", "75", _SRC_JNGJ),
        Decimal("1000000000"): _zone("0.93", "25", _SRC_JNGJ),
        Decimal("3000000000"): _zone("0.93", "25", _SRC_JNGJ),
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
        Decimal("1000000000"): _zone("0.905", "55", _SRC_JNGJ),
        Decimal("3000000000"): _zone("0.905", "55", _SRC_JNGJ),
        None: _zone("0.905", "55", _SRC_JNGJ),
    },
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_06": {
        **_four_band_general(_SRC_JNGJ),
        Decimal("3000000000"): _zone("0.98", "20", _SRC_JNGJ),
    },
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
    # 서울특별시 (시행 2024-08-12) — 10억원 이상을 30억원 경계로 나눈 서울 전용 매핑.
    # 새 상한 키 3000000000 은 분할 전 10억원 이상 구간(None)과 같은 평탄(98% -> 20점)을 씁니다.
    "SERVC_LOCAL_SEOUL_20240812_ATTACH_01": {
        **_four_band_general(_SRC_SEOUL),
        Decimal("3000000000"): _zone("0.98", "20", _SRC_SEOUL),
    },
    "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR": _four_band_simple_labor(_SRC_SEOUL),
    # 부산광역시 (공고 제2025-1981호) — 10억원 이상을 30억원 경계로 나눠 두 구간 모두 같은 평탄
    "SERVC_LOCAL_BUSAN_20250626_ATTACH_01": _five_band_general(_SRC_BUSAN),
    "SERVC_LOCAL_BUSAN_20250626_SIMPLE_LABOR": _four_band_simple_labor(_SRC_BUSAN),
    # 대전광역시 (공고 제2025-9528호) — 10억원 이상 소프트웨어류에만 평탄 문장이 인쇄됨.
    # 30억원 이상 구간은 원문 문장이 30억원 미만을 가리키지만, 분할 전 동작을 유지하도록
    # 두 구간에 같은 평탄을 둡니다.
    "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01": {
        Decimal("3000000000"): _zone("0.98", "20", _SRC_DAEJEON),
        None: _zone("0.98", "20", _SRC_DAEJEON),
    },
    # 충청남도 (공고 2026-1235호) — 점수 미인쇄, 산식 대입값
    "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01": {
        Decimal("500000000"): _zone("0.94", "55", _SRC_CHUNGNAM_01),
        None: _zone("0.94", "45", _SRC_CHUNGNAM_01),
    },
    "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_2_1": {
        Decimal("500000000"): _zone("0.94", "58", _SRC_CHUNGNAM_2_1),
        None: _zone("0.94", "48", _SRC_CHUNGNAM_2_1),
    },
    "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05": {
        Decimal("500000000"): _zone("0.94", "55", _SRC_CHUNGNAM_05),
        None: _zone("0.955", "45", _SRC_CHUNGNAM_05),
    },
    # 전북특별자치도 (부칙 제2024-10호) — 10억원 이상을 30억원 경계로 나눠 두 구간 모두 같은 평탄
    "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01": _five_band_general(_SRC_JEONBUK),
    "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR": _four_band_simple_labor(_SRC_JEONBUK),
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
    """등록된 지방 규칙 평탄 구간 전량을 (rule_id, upper_bound, FlatZone) 로 돌려줍니다."""
    return tuple(
        (rule_id, upper_bound, zone)
        for rule_id, zones in _FLAT_ZONES.items()
        for upper_bound, zone in zones.items()
    )


# =============================================================================
# 조달청 PRE/POST 별표 평탄 구간
# =============================================================================

# 조달청 규칙은 price_bands 대신 두 축으로 배점표를 가릅니다. B 는 추정가격 5억원 축
# (max_price_score_by_500m), k 는 고시금액 축(multiplier_by_notice)입니다. 평탄 비율은
# k 축으로, 평탄 점수는 B·k·기준비율 산식 대입값으로 갈리므로 두 축 해당 여부를 키로 둡니다.
# 값 근거: docs/analysis/pps_flat_zone_source_20261005.md 8장,
# docs/analysis/pps_lwlt_basis_20261005.md 7.1장.
_PPS_RATIO_DOC = "docs/analysis/pps_flat_zone_source_20261005.md"
_PPS_BASIS_DOC = "docs/analysis/pps_lwlt_basis_20261005.md"


@dataclass(frozen=True)
class PpsFlatZone:
    """조달청 평탄 원문 한 줄.

    flat_score None 은 배점한도(B)가 공고 입력값이라 고정할 수 없어 조회 시 산식 대입값으로
    산출하는 구간입니다(별표9 수요기관지정형).
    """

    flat_ratio: Decimal
    flat_score: Decimal | None
    source: str


def _pps_zone(ratio: str, score: str | None, source: str) -> PpsFlatZone:
    return PpsFlatZone(
        flat_ratio=Decimal(ratio),
        flat_score=Decimal(score) if score is not None else None,
        source=source,
    )


def _pps_b_band(
    ratio: str, score_below: str, score_above: str, source: str
) -> dict[tuple[bool | None, bool | None], PpsFlatZone]:
    """B(5억) 축만 값이 갈리는 규칙. False=5억원 미만(B 70), True=5억원 이상(B 60)."""
    return {
        (False, None): _pps_zone(ratio, score_below, source),
        (True, None): _pps_zone(ratio, score_above, source),
    }


def _pps_notice_band(
    ratio_below: str, ratio_above: str, score: str | None, source: str
) -> dict[tuple[bool | None, bool | None], PpsFlatZone]:
    """고시금액 축만 값이 갈리는 규칙. False=고시금액 미만(k 4), True=고시금액 이상(k 2)."""
    return {
        (None, False): _pps_zone(ratio_below, score, source),
        (None, True): _pps_zone(ratio_above, score, source),
    }


def _pps_both_bands(
    ratio_below: str, ratio_above: str, score_below: str, score_above: str, source: str
) -> dict[tuple[bool | None, bool | None], PpsFlatZone]:
    """두 축이 함께 갈리는 규칙. 평탄 점수는 B 로, 평탄 비율은 k 축으로 갈립니다."""
    return {
        (False, False): _pps_zone(ratio_below, score_below, source),
        (False, True): _pps_zone(ratio_above, score_below, source),
        (True, False): _pps_zone(ratio_below, score_above, source),
        (True, True): _pps_zone(ratio_above, score_above, source),
    }


def _pps_fixed(
    ratio: str, score: str, source: str
) -> dict[tuple[bool | None, bool | None], PpsFlatZone]:
    """두 축 모두 조건이 아닌 규칙."""
    return {(None, None): _pps_zone(ratio, score, source)}


def _pps_pre_source(label: str, row: int, basis_row: int) -> str:
    return (
        f"{_PPS_RATIO_DOC}:{row} (8.1 {label} 등록 값, 개정 전 제2023-53호·제2025-257호 두 판 동일); "
        f"{_PPS_BASIS_DOC}:{basis_row} (7.1 등록 후보); 점수는 원문 미인쇄 산식 대입값"
    )


def _pps_post_source(label: str, row: int) -> str:
    return (
        f"{_PPS_RATIO_DOC}:{row} (8.2 {label} 등록 값, 제2026-260호); "
        "원문 대조 4.3·5.2; 점수는 원문 미인쇄 산식 대입값"
    )


def _pps_post_390_source(label: str, row: int) -> str:
    return (
        f"{_PPS_RATIO_DOC}:{row} (8.3 {label} 등록 값, 제2026-390호); "
        "원문 대조 4.4·5.3; 점수는 원문 미인쇄 산식 대입값"
    )


# 개정 전 제2023-53호·제2025-257호·제2026-15호 값. 두 판이 같아 규칙 ID 접두만 달리 붙입니다.
_PPS_PRE_ZONES: dict[str, dict[tuple[bool | None, bool | None], PpsFlatZone]] = {
    "01": _pps_b_band("0.94", "55", "45", _pps_pre_source("별표2 시설분야", 266, 278)),
    "03": _pps_b_band("0.94", "58", "48", _pps_pre_source("별표5 여객", 267, 279)),
    "04": _pps_b_band("0.94", "58", "48", _pps_pre_source("별표3의2 SW대상", 268, 280)),
    "05": _pps_both_bands(
        "0.9175", "0.955", "55", "45", _pps_pre_source("별표3 SW비대상", 269, 281)
    ),
    "06": _pps_fixed("0.9175", "55", _pps_pre_source("별표1 학술연구 고시 미만", 270, 282)),
    "07": _pps_b_band("0.955", "55", "45", _pps_pre_source("별표1 학술연구 고시 이상", 271, 283)),
    "08": _pps_fixed("0.9175", "55", _pps_pre_source("별표4 폐기물 고시 미만", 272, 284)),
    "09": _pps_b_band("0.955", "55", "45", _pps_pre_source("별표4 폐기물 고시 이상", 273, 285)),
    "10": _pps_fixed("0.9175", "55", _pps_pre_source("별표5의2 화물 고시 미만", 274, 286)),
    "11": _pps_b_band("0.955", "55", "45", _pps_pre_source("별표5의2 화물 고시 이상", 275, 287)),
    "15": _pps_both_bands(
        "0.9175", "0.955", "55", "45", _pps_pre_source("별표7 수리·점검", 276, 288)
    ),
    "16": _pps_notice_band("0.9175", "0.955", "55", _pps_pre_source("별표8 임대차", 277, 289)),
    "17": _pps_notice_band(
        "0.9175",
        "0.955",
        None,
        _pps_pre_source("별표9 수요기관지정형(B 공고 입력값, 점수 B-15)", 278, 290),
    ),
}


_PPS_FLAT_ZONES: dict[str, dict[tuple[bool | None, bool | None], PpsFlatZone]] = {
    # 개정 전 제2023-53호 (시행 2023-05-01)
    "SERVC_QUAL_PRE_20230501_ATTACH_01": _PPS_PRE_ZONES["01"],
    "SERVC_QUAL_PRE_20230501_ATTACH_03": _PPS_PRE_ZONES["03"],
    "SERVC_QUAL_PRE_20230501_ATTACH_04": _PPS_PRE_ZONES["04"],
    "SERVC_QUAL_PRE_20230501_ATTACH_05": _PPS_PRE_ZONES["05"],
    "SERVC_QUAL_PRE_20230501_ATTACH_06": _PPS_PRE_ZONES["06"],
    "SERVC_QUAL_PRE_20230501_ATTACH_07": _PPS_PRE_ZONES["07"],
    "SERVC_QUAL_PRE_20230501_ATTACH_08": _PPS_PRE_ZONES["08"],
    "SERVC_QUAL_PRE_20230501_ATTACH_09": _PPS_PRE_ZONES["09"],
    "SERVC_QUAL_PRE_20230501_ATTACH_10": _PPS_PRE_ZONES["10"],
    "SERVC_QUAL_PRE_20230501_ATTACH_11": _PPS_PRE_ZONES["11"],
    "SERVC_QUAL_PRE_20230501_ATTACH_15": _PPS_PRE_ZONES["15"],
    "SERVC_QUAL_PRE_20230501_ATTACH_16": _PPS_PRE_ZONES["16"],
    "SERVC_QUAL_PRE_20230501_ATTACH_17": _PPS_PRE_ZONES["17"],
    # 개정 전 제2025-257호·제2026-15호 (시행 2025-09-01) — 위와 값 동일
    "SERVC_QUAL_PRE_20250901_ATTACH_01": _PPS_PRE_ZONES["01"],
    "SERVC_QUAL_PRE_20250901_ATTACH_03": _PPS_PRE_ZONES["03"],
    "SERVC_QUAL_PRE_20250901_ATTACH_04": _PPS_PRE_ZONES["04"],
    "SERVC_QUAL_PRE_20250901_ATTACH_05": _PPS_PRE_ZONES["05"],
    "SERVC_QUAL_PRE_20250901_ATTACH_06": _PPS_PRE_ZONES["06"],
    "SERVC_QUAL_PRE_20250901_ATTACH_07": _PPS_PRE_ZONES["07"],
    "SERVC_QUAL_PRE_20250901_ATTACH_08": _PPS_PRE_ZONES["08"],
    "SERVC_QUAL_PRE_20250901_ATTACH_09": _PPS_PRE_ZONES["09"],
    "SERVC_QUAL_PRE_20250901_ATTACH_10": _PPS_PRE_ZONES["10"],
    "SERVC_QUAL_PRE_20250901_ATTACH_11": _PPS_PRE_ZONES["11"],
    "SERVC_QUAL_PRE_20250901_ATTACH_15": _PPS_PRE_ZONES["15"],
    "SERVC_QUAL_PRE_20250901_ATTACH_16": _PPS_PRE_ZONES["16"],
    "SERVC_QUAL_PRE_20250901_ATTACH_17": _PPS_PRE_ZONES["17"],
    # 개정 후 제2026-260호 (시행 2026-05-26). 별표 6 보험(ATTACH_02)은 평탄 문장이 없어 제외합니다.
    "SERVC_QUAL_POST_20260526_ATTACH_01": _pps_b_band(
        "0.96", "55", "45", _pps_post_source("별표2 시설분야", 284)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_03": _pps_b_band(
        "0.94", "58", "48", _pps_post_source("별표5 여객", 285)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_04": _pps_b_band(
        "0.94", "58", "48", _pps_post_source("별표3의2 SW대상", 286)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_05": _pps_both_bands(
        "0.9375", "0.975", "55", "45", _pps_post_source("별표3 SW비대상", 287)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_06": _pps_fixed(
        "0.9375", "55", _pps_post_source("별표1 학술연구 고시 미만", 288)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_07": _pps_b_band(
        "0.975", "55", "45", _pps_post_source("별표1 학술연구 고시 이상", 289)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_08": _pps_fixed(
        "0.9375", "55", _pps_post_source("별표4 폐기물 고시 미만", 290)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_09": _pps_b_band(
        "0.975", "55", "45", _pps_post_source("별표4 폐기물 고시 이상", 291)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_10": _pps_fixed(
        "0.9375", "55", _pps_post_source("별표5의2 화물 고시 미만", 292)
    ),
    "SERVC_QUAL_POST_20260526_ATTACH_11": _pps_b_band(
        "0.975", "55", "45", _pps_post_source("별표5의2 화물 고시 이상", 293)
    ),
    # 개정 후 제2026-390호 (시행 2026-07-27, 신규 2개). 나머지 12칸은 제2026-260호 객체 재사용입니다.
    "SERVC_QUAL_POST_20260727_ATTACH_03": _pps_b_band(
        "0.96", "58", "48", _pps_post_390_source("별표5 여객", 299)
    ),
    "SERVC_QUAL_POST_20260727_ATTACH_04": _pps_b_band(
        "0.96", "58", "48", _pps_post_390_source("별표3의2 SW대상", 300)
    ),
}


def pps_axis_side(
    conditional: tuple[Decimal, Decimal] | None, value: Decimal | None
) -> bool | None:
    """조건부 축(B·k)에서 실제 적용한 값이 어느 쪽인지(이상=True)를 돌려줍니다.

    evaluation_rules 의 조건부 선언 튜플은 (미만, 이상) 순서입니다. 값이 어느 쪽과도 다르면
    None 을 돌려주어 호출부가 평탄을 적용하지 않게 합니다.
    """
    if conditional is None or value is None:
        return None
    below, above = conditional
    if value == above:
        return True
    if value == below:
        return False
    return None


def pps_flat_zone_for(
    rule_id: str,
    *,
    above_500m: bool | None,
    above_notice: bool | None,
    max_price_score: Decimal | None = None,
    multiplier: Decimal | None = None,
    base_rate: Decimal | None = None,
) -> FlatZone | None:
    """조달청 규칙의 평탄 규정을 두 축 해당 여부로 조회합니다.

    above_500m: 추정가격이 5억원 이상이면 True. 규칙의 B 가 5억 축 조건이 아니면 None.
    above_notice: 추정가격이 고시금액 이상이면 True. 규칙의 k 가 고시금액 축 조건이 아니면 None.
    max_price_score·multiplier·base_rate 는 별표9(수요기관 지정형)처럼 B 가 공고 입력값이라
    점수를 저장할 수 없는 구간의 산식 대입값을 계산할 때만 씁니다. 데이터가 없거나 축 값이
    등록 키와 맞지 않으면 None 을 돌려주며, 호출부는 그대로 평탄을 적용하지 않습니다.
    """
    zones = _PPS_FLAT_ZONES.get(rule_id)
    if not zones:
        return None
    zone = zones.get((above_500m, above_notice))
    if zone is None:
        return None
    score = zone.flat_score
    if score is None:
        if max_price_score is None or multiplier is None or base_rate is None:
            return None
        normalized_base = base_rate / Decimal("100") if base_rate > Decimal("1") else base_rate
        diff = abs(zone.flat_ratio - normalized_base) * Decimal("100")
        score = max_price_score - multiplier * diff
    return FlatZone(flat_ratio=zone.flat_ratio, flat_score=score, source=zone.source)


def pps_flat_zone_entries() -> tuple[tuple[str, tuple[bool | None, bool | None], PpsFlatZone], ...]:
    """등록된 조달청 평탄 구간 전량을 (rule_id, 두 축 키, 원문 데이터) 로 돌려줍니다."""
    return tuple(
        (rule_id, key, zone)
        for rule_id, zones in _PPS_FLAT_ZONES.items()
        for key, zone in zones.items()
    )
