"""건설폐기물 제외 조항이 있는 9개 시·도 규칙의 CDW 공고 제외 시험.

정본: docs/analysis/cdw_local_overlap_20261019.md 5절 원문 인용.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    resolve_evaluation_rule_from_raw_data,
)


def _resolve(region_code, region_name, raw, local_service_type=None, estimated_price=None):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=estimated_price,
        local_service_type=local_service_type,
    )


# (region_code, region_name, service_type, raw dict, estimated_price, local_rule_id)
CDW_CASES = [
    (
        "47",
        "경상북도",
        "WASTE",
        {
            "dminsttNm": "경상북도",
            "bidNtceDt": "2026-01-14 11:19:48",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "283000000",
            "bidNtceNm": "포항~안동(1-2)간 도로건설공사 건설폐기물 처리용역(6차)",
        },
        Decimal("283000000"),
        "SERVC_LOCAL_GB_20260108_ATTACH_03",
    ),
    (
        "47",
        "경상북도",
        "WASTE",
        {
            "dminsttNm": "경상북도 영천시",
            "bidNtceDt": "2025-11-24 08:57:53",
            "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
            "presmptPrce": "117263636",
            "bidNtceNm": "서부동 별빛커뮤니티센터 기존건물 철거공사 건설폐기물 처리용역",
        },
        Decimal("117263636"),
        "SERVC_LOCAL_GB_20241212_ATTACH_05",
    ),
    (
        "41",
        "경기도",
        "WASTE",
        {
            "dminsttNm": "경기도 평택시 상하수도사업소",
            "bidNtceDt": "2025-10-20 13:47:33",
            "sucsfbidMthdNm": "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
            "presmptPrce": "862294550",
            "bidNtceNm": "학현,내기처리분구 하수관로 정비사업(2단계) 건설폐기물처리용역(전체분)(긴급)",
        },
        Decimal("862294550"),
        "SERVC_LOCAL_GG_20250808_ATTACH_1_3",
    ),
    (
        "31",
        "울산광역시",
        "WASTE",
        {
            "dminsttNm": "울산광역시 동구",
            "bidNtceDt": "2025-10-21 14:13:45",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "324940000",
            "bidNtceNm": "대왕암공원 (구)교육연수원 철거공사(2차) 건설폐기물 처리용역 입찰 안내 재공고(긴급)",
        },
        Decimal("324940000"),
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_02",
    ),
    (
        "36",
        "세종특별자치시",
        "WASTE",
        {
            "dminsttNm": "세종특별자치시",
            "bidNtceDt": "2026-03-03 14:59:30",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "269750000",
            "bidNtceNm": "장욱진생가기념관 건립사업 건축공사 건설폐기물 처리 용역",
        },
        Decimal("269750000"),
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_04",
    ),
    (
        "52",
        "전북특별자치도",
        "GENERAL",
        {
            "dminsttNm": "전북특별자치도 군산시",
            "bidNtceDt": "2025-10-21 10:58:47",
            "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
            "presmptPrce": "172200000",
            "bidNtceNm": "새만금북로(공항교차로~GSCO사거리) 재포장공사 건설폐기물 처리용역",
        },
        Decimal("172200000"),
        "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01",
    ),
    (
        "43",
        "충청북도",
        "GENERAL",
        {
            "dminsttNm": "충청북도 단양군",
            "bidNtceDt": "2025-10-23 10:44:04",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "205309091",
            "bidNtceNm": "단양군 지방정원 조성사업 건설폐기물처리용역",
        },
        Decimal("205309091"),
        "SERVC_LOCAL_CB_20231020_ATTACH_01",
    ),
    (
        "51",
        "강원특별자치도",
        "GENERAL",
        {
            "dminsttNm": "강원특별자치도 평창군",
            "bidNtceDt": "2025-11-20 16:26:57",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "226652727",
            "bidNtceNm": "외거문 급경사지 붕괴위험지역 정비사업 건설폐기물처리 용역",
        },
        Decimal("226652727"),
        "SERVC_LOCAL_GANGWON_20230611_ATTACH_01",
    ),
    (
        "28",
        "인천광역시",
        "GENERAL",
        {
            "dminsttNm": "인천광역시 종합건설본부",
            "bidNtceDt": "2026-01-20 20:02:00",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "247500000",
            "bidNtceNm": "인천가족공원 조성사업(3-2단계) 봉안당 증축공사 매립건설폐기물 처리용역",
        },
        Decimal("247500000"),
        "SERVC_LOCAL_INCHEON_20251224_ATTACH_01",
    ),
    (
        "28",
        "인천광역시",
        "GENERAL",
        {
            "dminsttNm": "인천광역시 도시철도건설본부",
            "bidNtceDt": "2025-11-03 16:28:09",
            "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
            "presmptPrce": "362954000",
            "bidNtceNm": "서울도시철도7호선 청라국제도시 연장 4공구 건설공사 건설폐기물 처리용역(불연성)",
        },
        Decimal("362954000"),
        "SERVC_LOCAL_INCHEON_20241204_ATTACH_01",
    ),
    (
        "30",
        "대전광역시",
        "GENERAL",
        {
            "dminsttNm": "대전광역시 건설관리본부",
            "bidNtceDt": "2026-03-26 08:28:55",
            "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
            "presmptPrce": "190796364",
            "bidNtceNm": "융복합 특수영상콘텐츠 클러스터 조성사업 건설폐기물 처리용역",
        },
        Decimal("190796364"),
        "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01",
    ),
    (
        "30",
        "대전광역시",
        "GENERAL",
        {
            "dminsttNm": "대전광역시",
            "bidNtceDt": "2025-10-22 14:27:09",
            "sucsfbidMthdNm": "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
            "presmptPrce": "1063920000",
            "bidNtceNm": "대전도시철도 2호선 12공구 건설공사 건설폐기물 운반·처리용역",
        },
        Decimal("1063920000"),
        "SERVC_LOCAL_DAEJEON_20240120_ATTACH_01",
    ),
]


def test_cdw_cases_go_to_moe():
    for code, name, svc, raw, price, local_id in CDW_CASES:
        result = _resolve(code, name, raw, local_service_type=svc, estimated_price=price)
        assert result.rule is not None, (local_id, result.block_reason_code)
        assert result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_"), (
            local_id,
            result.rule.rule_id,
        )


def test_non_cdw_stays_local():
    for code, name, svc, raw, price, local_id in CDW_CASES:
        raw2 = dict(raw)
        raw2["bidNtceNm"] = "일반 청소용역"
        result = _resolve(code, name, raw2, local_service_type=svc, estimated_price=price)
        assert result.rule is not None, (local_id, result.block_reason_code)
        assert result.rule.rule_id == local_id, (local_id, result.rule.rule_id)


def test_ulsan_haul_stays_local():
    raw = {
        "dminsttNm": "울산광역시 동구",
        "bidNtceDt": "2025-10-21 14:13:45",
        "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "presmptPrce": "324940000",
        "bidNtceNm": "건설폐기물 운반용역",
    }
    result = _resolve(
        "31", "울산광역시", raw, local_service_type="WASTE", estimated_price=Decimal("324940000")
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_ULSAN_20220810_ATTACH_02"


def test_ulsan_processing_goes_moe():
    raw = {
        "dminsttNm": "울산광역시 동구",
        "bidNtceDt": "2025-10-21 14:13:45",
        "sucsfbidMthdNm": "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "presmptPrce": "324940000",
        "bidNtceNm": "건설폐기물 운반 및 처리용역",
    }
    result = _resolve(
        "31", "울산광역시", raw, local_service_type="WASTE", estimated_price=Decimal("324940000")
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")


def test_outside_region_unchanged():
    raw = {
        "dminsttNm": "서울특별시",
        "bidNtceDt": "2025-10-21 10:58:47",
        "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
        "presmptPrce": "172200000",
        "bidNtceNm": "건설폐기물 처리용역",
    }
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="11",
        region_name="서울특별시",
        estimated_price=Decimal("172200000"),
    )
    # 서울은 cdw_exclusion 이 없어 시·도 규칙 경로를 유지한다(차단/규칙 어느 쪽이든 MOE 가 아님).
    if result.rule is not None:
        assert not result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")
