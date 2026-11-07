"""건설폐기물 고시 경로 라우팅 시험 (2026-11-07).

결정 D01~D06(docs/analysis/decision_backlog_20261107.md)을 고정합니다. 조달분류
`건설폐기물처리서비스` 를 공고명 `건설폐기물` 과 병행(OR)한 신호, A 계열 시·도의
`notice_cited` 선언, 일반 폐기물·미선언 시·도의 기존 동작 불변을 확인합니다.
"""

from __future__ import annotations

import pytest

from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule_from_raw_data,
)

_BAND_UNDER_200M = "적격심사제-추정가격 2억원 미만인 용역"
_BAND_200M_TO_500M = "적격심사제-추정가격 5억원 미만 2억원 이상인 용역"
_MOE_ATTACH_04 = "SERVC_QUAL_MOE_CDW_ATTACH_04"
_MOE_ATTACH_03 = "SERVC_QUAL_MOE_CDW_ATTACH_03"

# 이 Task 전부터 있던 cdw_exclusion 선언. 값이 바뀌거나 사라지면 기존 동작이 변한 것입니다.
_ORIGINAL_CDW_DECLARATIONS = {
    "SERVC_LOCAL_INCHEON_20241204_ATTACH_01": "named",
    "SERVC_LOCAL_INCHEON_20251224_ATTACH_01": "named",
    "SERVC_LOCAL_GANGWON_20230611_ATTACH_01": "named",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_04": "named",
    "SERVC_LOCAL_GB_20241212_ATTACH_05": "named",
    "SERVC_LOCAL_GB_20260108_ATTACH_03": "named",
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_02": "named_except_haul",
    "SERVC_LOCAL_CB_20231020_ATTACH_01": "named",
    "SERVC_LOCAL_DAEGU_20220930_ATTACH_04": "band",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_3": "named",
    "SERVC_LOCAL_DAEJEON_20240120_ATTACH_01": "named",
    "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01": "named",
    "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01": "named",
    "SERVC_LOCAL_DAEGU_20260511_ATTACH_04": "band",
}

_NOTICE_CITED_RULE_IDS = {
    "SERVC_LOCAL_SEOUL_20240812_ATTACH_01",
    "SERVC_LOCAL_BUSAN_20250626_ATTACH_01",
    "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
    "SERVC_LOCAL_GN_20230105_ATTACH_01",
    "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03",
    "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03",
}


def _raw_data(
    *,
    method_name: str,
    notice_name: str = "",
    class_name: str = "",
    lwlt_rate: str = "87.745",
    notice_date: str = "2026-05-01 10:00:00",
) -> dict[str, object]:
    return {
        "sucsfbidMthdCd": "낙030001",
        "sucsfbidMthdNm": method_name,
        "bidNtceNm": notice_name,
        "pubPrcrmntLrgClsfcNm": "폐기물 처리 및 재활용서비스",
        "pubPrcrmntMidClsfcNm": "폐기물 처리",
        "pubPrcrmntClsfcNm": class_name,
        "pubPrcrmntDtlClsfcNm": "",
        "cntrctCnclsMthdNm": "지방계약법에 의한 계약",
        "bidNtceDt": notice_date,
        "sucsfbidLwltRate": lwlt_rate,
        "dminsttNm": "시험 수요기관",
        "dminsttCd": "0000000",
    }


def _resolve(
    sido_code: str,
    sido_name: str,
    *,
    method_name: str = _BAND_UNDER_200M,
    notice_name: str = "",
    class_name: str = "",
    lwlt_rate: str = "87.745",
    estimated_price: int = 150_000_000,
    notice_date: str = "2026-05-01 10:00:00",
):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=_raw_data(
            method_name=method_name,
            notice_name=notice_name,
            class_name=class_name,
            lwlt_rate=lwlt_rate,
            notice_date=notice_date,
        ),
        institution_regime="LOCAL",
        region_code=sido_code,
        region_name=sido_name,
        estimated_price=estimated_price,
    )


@pytest.mark.parametrize(
    ("sido_code", "sido_name", "notice_date", "expected_rule_id"),
    [
        ("11", "서울특별시", "2026-05-01 10:00:00", _MOE_ATTACH_04),
        ("26", "부산광역시", "2026-05-01 10:00:00", _MOE_ATTACH_04),
        ("50", "제주특별자치도", "2026-05-01 10:00:00", _MOE_ATTACH_04),
        ("48", "경상남도", "2026-05-01 10:00:00", _MOE_ATTACH_04),
        ("44", "충청남도", "2026-05-01 10:00:00", _MOE_ATTACH_04),
        ("44", "충청남도", "2026-08-01 10:00:00", _MOE_ATTACH_04),
    ],
)
def test_procurement_class_only_routes_to_moe(
    sido_code: str, sido_name: str, notice_date: str, expected_rule_id: str
) -> None:
    """(a)(d)(D06) 조달분류만 건설폐기물처리서비스이고 공고명에 폐기물이 없어도 고시로 갑니다."""
    result = _resolve(
        sido_code,
        sido_name,
        notice_name="노후포장 정비공사",
        class_name="건설폐기물처리서비스",
        notice_date=notice_date,
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.scope_stage == RULE_SCOPE_ALL


@pytest.mark.parametrize(
    ("sido_code", "sido_name", "method_name", "lwlt_rate", "estimated_price"),
    [
        ("11", "서울특별시", _BAND_UNDER_200M, "87.745", 150_000_000),
        ("41", "경기도", _BAND_200M_TO_500M, "86.745", 300_000_000),
        ("51", "강원특별자치도", _BAND_UNDER_200M, "87.745", 150_000_000),
    ],
)
def test_notice_name_only_routes_to_moe(
    sido_code: str,
    sido_name: str,
    method_name: str,
    lwlt_rate: str,
    estimated_price: int,
) -> None:
    """(b)(e) 공고명만 건설폐기물인 기존 신호는 그대로 고시로 갑니다."""
    result = _resolve(
        sido_code,
        sido_name,
        method_name=method_name,
        notice_name="건설폐기물 처리용역",
        lwlt_rate=lwlt_rate,
        estimated_price=estimated_price,
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == (
        _MOE_ATTACH_03 if method_name == _BAND_200M_TO_500M else _MOE_ATTACH_04
    )
    assert result.scope_stage == RULE_SCOPE_ALL


@pytest.mark.parametrize(
    ("sido_code", "sido_name", "method_name", "lwlt_rate", "estimated_price", "expected_rule_id"),
    [
        (
            "11",
            "서울특별시",
            _BAND_UNDER_200M,
            "87.745",
            150_000_000,
            "SERVC_LOCAL_SEOUL_20240812_ATTACH_01",
        ),
        (
            "41",
            "경기도",
            _BAND_200M_TO_500M,
            "86.745",
            300_000_000,
            "SERVC_LOCAL_GG_20250808_ATTACH_1_3",
        ),
    ],
)
def test_non_construction_waste_stays_local(
    sido_code: str,
    sido_name: str,
    method_name: str,
    lwlt_rate: str,
    estimated_price: int,
    expected_rule_id: str,
) -> None:
    """(c) 생활폐기물 등 일반 폐기물 공고는 시·도 규칙 판정을 유지합니다."""
    result = _resolve(
        sido_code,
        sido_name,
        method_name=method_name,
        notice_name="생활폐기물 수집·운반 용역",
        class_name="생활폐기물처리서비스",
        lwlt_rate=lwlt_rate,
        estimated_price=estimated_price,
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.scope_stage == RULE_SCOPE_REGION


@pytest.mark.parametrize(
    ("sido_code", "sido_name", "general_rule_id"),
    [
        ("11", "서울특별시", "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"),
        ("26", "부산광역시", "SERVC_LOCAL_BUSAN_20250626_ATTACH_01"),
        ("50", "제주특별자치도", "SERVC_LOCAL_JEJU_20240101_ATTACH_01"),
        ("48", "경상남도", "SERVC_LOCAL_GN_20230105_ATTACH_01"),
    ],
)
def test_notice_cited_general_fallback_routes_only_construction_waste(
    sido_code: str, sido_name: str, general_rule_id: str
) -> None:
    """(d) notice_cited GENERAL 폴백 시·도는 건설폐기물만 고시로 보내고 일반 용역은 그대로 둡니다."""
    construction = _resolve(
        sido_code, sido_name, notice_name="노후포장 정비공사", class_name="건설폐기물처리서비스"
    )
    general = _resolve(
        sido_code,
        sido_name,
        notice_name="시설물 유지관리 용역",
        class_name="기타사업지원서비스",
    )

    assert construction.rule is not None
    assert construction.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")
    assert general.rule is not None
    assert general.rule.rule_id == general_rule_id
    assert general.scope_stage == RULE_SCOPE_REGION


def test_named_declarations_keep_existing_values_and_behavior() -> None:
    """(e) 원문 근거 named·band 선언은 값과 동작이 그대로입니다."""
    declarations = {rule.rule_id: rule.cdw_exclusion for rule in LOCAL_RULES if rule.cdw_exclusion}
    for rule_id, mode in _ORIGINAL_CDW_DECLARATIONS.items():
        assert declarations.get(rule_id) == mode, rule_id

    gyeonggi_name = _resolve(
        "41",
        "경기도",
        method_name=_BAND_200M_TO_500M,
        notice_name="건설폐기물처리용역",
        lwlt_rate="86.745",
        estimated_price=300_000_000,
    )
    ulsan_haul = _resolve(
        "31",
        "울산광역시",
        notice_name="건설폐기물 수집·운반 용역",
        class_name="건설폐기물처리서비스",
    )

    assert gyeonggi_name.rule is not None
    assert gyeonggi_name.rule.rule_id == _MOE_ATTACH_03
    assert ulsan_haul.rule is not None
    assert ulsan_haul.rule.rule_id == "SERVC_LOCAL_ULSAN_20220810_ATTACH_02"
    assert ulsan_haul.scope_stage == RULE_SCOPE_REGION


def test_notice_cited_is_distinct_from_named() -> None:
    """D03: 원문 제외 문구 근거(named)와 공고 인용 근거(notice_cited)를 섞지 않습니다."""
    notice_cited = {rule.rule_id for rule in LOCAL_RULES if rule.cdw_exclusion == "notice_cited"}
    named = {rule.rule_id for rule in LOCAL_RULES if rule.cdw_exclusion == "named"}

    assert notice_cited == _NOTICE_CITED_RULE_IDS
    assert notice_cited.isdisjoint(named)


def test_undeclared_local_rule_keeps_routing_order() -> None:
    """D05: 선언이 없는 시·도 규칙은 고시 띠 표기여도 지역 규칙을 먼저 씁니다."""
    result = _resolve(
        "12",
        "전남광주통합특별시",
        notice_name="노후포장 정비공사",
        class_name="건설폐기물처리서비스",
        notice_date="2026-09-01 10:00:00",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
    assert result.scope_stage == RULE_SCOPE_REGION
