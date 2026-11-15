"""한국지역난방공사 지사·사업소 코드 추가 회귀 시험.

정본:
 - docs/analysis/appstd_vs_pps_default_20261115.md 3.6절, 4절 3행
 - docs/analysis/kdhc_branch_codes_20261115.md

2026-11-15 읽기 전용 DB 조회로 확인한 용인지사 D325100·파주지사 D325101·고양사업소
D325111 을 정확 코드 목록에 더한 뒤, 세 지사의 일반용역 공고가 공사 규칙
(SERVC_INST_KDHC_*) 을 고르고 기술용역 공고는 종전 기술용역 규칙을 유지하는지
대표 raw_data 로 검사합니다. 실제 DB·Redis 에 연결하지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    RULE_SCOPE_ALL,
    RULE_SCOPE_INSTITUTION,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
    resolve_evaluation_rule_from_raw_data,
)

KDHC_FACILITY_20260101 = "SERVC_INST_KDHC_20260101_FACILITY"
KDHC_REPAIR_20260101 = "SERVC_INST_KDHC_20260101_REPAIR"
KDHC_REPAIR_20260818 = "SERVC_INST_KDHC_20260818_REPAIR"
KDHC_WASTE_20260101 = "SERVC_INST_KDHC_20260101_WASTE"

KDHC_GENERAL_STANDARD = "한국지역난방공사 일반용역 적격심사 세부기준"
KDHC_TECH_STANDARD = "한국지역난방공사 기술용역 적격심사 세부기준"
PPS_GENERAL_STANDARD = "조달청 일반용역 적격심사 세부기준"

FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
REPAIR_METHOD = "적격심사제-수리ㆍ점검용역 적격심사 추정가격 고시금액 미만"
WASTE_METHOD = "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액 미만"
TECH_METHOD = (
    "적격심사제-추정가격이 고시금액미만(건축사법에 따른 설계는 1억원미만, "
    "소방시설공사업법에 따른 설계·감리는 2천만원미만)인 용역"
)


def _raw(
    *,
    code: str,
    name: str,
    announced: str,
    method_name: str,
    price: str,
    standard: str,
    service_division: str = "일반용역",
    notice_name: str = "유지보수용역",
    lwlt_rate: str | None = None,
) -> dict[str, str]:
    data = {
        "dminsttCd": code,
        "dminsttNm": name,
        "ntceInsttCd": code,
        "ntceInsttNm": name,
        "bidNtceDt": announced,
        "bidNtceNm": notice_name,
        "sucsfbidMthdNm": method_name,
        "sucsfbidMthdAppStd": standard,
        "srvceDivNm": service_division,
        "presmptPrce": price,
    }
    if lwlt_rate is not None:
        data["sucsfbidLwltRate"] = lwlt_rate
    return data


def _resolve(raw: dict[str, str], price: str):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        estimated_price=Decimal(price),
    )


@pytest.mark.parametrize(
    ("code", "name", "announced", "price"),
    [
        ("D325100", "한국지역난방공사 용인지사", "2026-03-16 14:26:32", "25217000"),
        ("D325101", "한국지역난방공사 파주지사", "2026-01-29 14:24:46", "39646000"),
    ],
)
def test_new_branch_codes_select_facility_rule(
    code: str,
    name: str,
    announced: str,
    price: str,
) -> None:
    raw = _raw(
        code=code,
        name=name,
        announced=announced,
        method_name=FACILITY_METHOD,
        price=price,
        standard=KDHC_GENERAL_STANDARD,
    )

    result = _resolve(raw, price)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_FACILITY_20260101
    assert result.scope_stage == RULE_SCOPE_INSTITUTION


@pytest.mark.parametrize(
    ("code", "name", "announced", "price", "expected_rule_id"),
    [
        (
            "D325111",
            "한국지역난방공사 고양사업소",
            "2026-01-14 09:27:13",
            "13890000",
            KDHC_REPAIR_20260101,
        ),
        (
            "D325101",
            "한국지역난방공사 파주지사",
            "2026-09-17 13:33:11",
            "26630000",
            KDHC_REPAIR_20260818,
        ),
    ],
)
def test_new_branch_codes_select_repair_rule(
    code: str,
    name: str,
    announced: str,
    price: str,
    expected_rule_id: str,
) -> None:
    raw = _raw(
        code=code,
        name=name,
        announced=announced,
        method_name=REPAIR_METHOD,
        price=price,
        standard=KDHC_GENERAL_STANDARD,
    )

    result = _resolve(raw, price)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.scope_stage == RULE_SCOPE_INSTITUTION


def test_new_branch_code_selects_waste_rule() -> None:
    price = "182700000"
    raw = _raw(
        code="D325101",
        name="한국지역난방공사 파주지사",
        announced="2026-04-13 17:24:03",
        method_name=WASTE_METHOD,
        price=price,
        standard=KDHC_GENERAL_STANDARD,
        notice_name="생활폐기물 처리용역",
    )

    result = _resolve(raw, price)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_WASTE_20260101
    assert result.scope_stage == RULE_SCOPE_INSTITUTION


@pytest.mark.parametrize(
    ("code", "name", "announced", "price", "expected_rule_id"),
    [
        (
            "D325111",
            "한국지역난방공사 고양사업소",
            "2026-04-17 09:54:50",
            "189217000",
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526.rule_id,
        ),
        (
            "D325100",
            "한국지역난방공사 용인지사",
            "2026-06-29 16:18:42",
            "188515000",
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id,
        ),
    ],
)
def test_tech_service_notice_keeps_tech_rule(
    code: str,
    name: str,
    announced: str,
    price: str,
    expected_rule_id: str,
) -> None:
    raw = _raw(
        code=code,
        name=name,
        announced=announced,
        method_name=TECH_METHOD,
        price=price,
        standard=KDHC_TECH_STANDARD,
        service_division="기술용역",
        lwlt_rate="87.745",
    )

    result = _resolve(raw, price)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.scope_stage == RULE_SCOPE_ALL


def test_pps_stated_notice_selects_kdhc_repair_rule() -> None:
    """공고 명시와 기관 규칙 충돌 사례.

    R26BK01809261 은 적용 기준을 조달청 일반용역 적격심사 세부기준으로 명시했지만,
    2026-11-15 코디네이터 결정(C)으로 기관 코드 우선 설계를 그대로 두어 공사
    수리·점검 규칙으로 계산합니다. 충돌 해소는 별도 사용자 결정 대기 항목입니다.
    """
    price = "14400000"
    raw = _raw(
        code="D325100",
        name="한국지역난방공사 용인지사",
        announced="2026-11-04 13:27:41",
        method_name="적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만",
        price=price,
        standard=PPS_GENERAL_STANDARD,
        notice_name="2026년 용인지사 열 생산 및 공급 계량설비 교정검사 용역",
    )

    result = _resolve(raw, price)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == KDHC_REPAIR_20260818
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
