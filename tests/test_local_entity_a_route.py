"""공고문이 조달청 세부기준을 인용한 지방공기업(라벨 A)의 기관 단위 경로 시험.

정본: `.orca/capsules/task_b49ef852a1ac/capsule.yaml` (사용자 결정 3, 2026-11-06)
- 대상 기관은 `docs/analysis/local_entity_69_citation_check_20261106.md` 2·3절에서
  해당 기관의 모든 공고 라벨이 (A) 조달청 세부기준 인용 또는 (E) 판독 불가이고
  (A)가 1건 이상인 기관입니다.
- 해석기는 실행 시 공고문을 읽지 않으므로 수요기관 코드(dminstt_cd) 명시 목록으로
  기관 단위로 옮깁니다. 이름 패턴은 쓰지 않습니다.
- 목록 기관은 시·도 매핑이 있어도 시·도 규칙 후보를 만들지 않고 조달청 기본 규칙으로
  해석합니다. 목록 밖 지방공기업과 라벨이 섞인 기관의 판정은 그대로 둡니다.

DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.app.services.demand_institutions import (
    PPS_CITED_LOCAL_INSTITUTION_CODES,
    is_pps_cited_local_institution,
)
from src.app.services.evaluation_rules import (
    PPS_CITED_LOCAL_INSTITUTION_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule_from_raw_data,
)

METHOD_FACILITY = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
BID_DATE = "2025-12-04"

# (수요기관 코드, 기관명, 시·도 코드, 시·도 명). 2절 라벨 A 공고가 있는 기관 전부입니다.
# 한 기관이 여러 코드로 등록된 경우(부산환경공단·제주관광공사)는 코드를 모두 담습니다.
TARGET_INSTITUTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("Z003836", "구리농수산물공사", "41", "경기도"),
    ("Z004979", "대전광역시 시설관리공단", "30", "대전광역시"),
    ("B552519", "대전도시공사", "30", "대전광역시"),
    ("Z003824", "부산환경공단", "26", "부산광역시"),
    ("B552625", "부산환경공단", "26", "부산광역시"),
    ("Z005642", "서울시 강남구도시관리공단", "11", "서울특별시"),
    ("B553733", "세종도시교통공사", "36", "세종특별자치시"),
    ("Z028316", "아산시시설관리공단", "44", "충청남도"),
    ("B552542", "양산시시설관리공단", "48", "경상남도"),
    ("B552147", "울주군시설관리공단", "31", "울산광역시"),
    ("Z033569", "인천광역시 연수구 시설안전관리공단", "28", "인천광역시"),
    ("Z003991", "인천교통공사", "28", "인천광역시"),
    ("B555480", "전남광주통합특별시북구시설관리공단", "12", "전남광주통합특별시"),
    ("B552701", "제주관광공사", "50", "제주특별자치도"),
    ("Z017752", "제주관광공사", "50", "제주특별자치도"),
    ("Z020113", "제주관광공사", "50", "제주특별자치도"),
    ("B552915", "제주에너지공사", "50", "제주특별자치도"),
)

# 라벨이 (B)·(C)·(D)와 섞여 기관 단위 전환에서 제외한 기관입니다.
MIXED_LABEL_INSTITUTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("B551939", "제주특별자치도개발공사", "50", "제주특별자치도"),
    ("B552833", "거제해양관광개발공사", "48", "경상남도"),
    ("B554808", "대구공공시설관리공단", "27", "대구광역시"),
)

NON_TARGET_LOCAL_ENTERPRISE_CODE = "Z000000"
NON_TARGET_LOCAL_ENTERPRISE_NAME = "서울특별시 강북구도시관리공단"


def _raw(code: str | None, name: str) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "dminsttNm": name,
        "sucsfbidMthdNm": METHOD_FACILITY,
        "bidNtceDt": BID_DATE,
    }
    if code is not None:
        raw["dminsttCd"] = code
    return raw


def _resolve(
    raw: dict[str, Any],
    *,
    regime: str | None = "LOCAL",
    region_code: str | None,
    region_name: str | None,
):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw,
        institution_regime=regime,
        region_code=region_code,
        region_name=region_name,
        estimated_price="100000000",
    )


def test_target_code_list_matches_document_institutions() -> None:
    assert (
        frozenset(code for code, _name, _region_code, _region_name in TARGET_INSTITUTIONS)
        == PPS_CITED_LOCAL_INSTITUTION_CODES
    )


@pytest.mark.parametrize(
    ("code", "name", "region_code", "region_name"),
    TARGET_INSTITUTIONS,
    ids=[code for code, _name, _region_code, _region_name in TARGET_INSTITUTIONS],
)
def test_listed_institution_uses_pps_default_rule(
    code: str,
    name: str,
    region_code: str,
    region_name: str,
) -> None:
    reference = _resolve(
        _raw(code, name),
        regime=None,
        region_code=None,
        region_name=None,
    )
    assert reference.is_blocked is False
    assert reference.rule is not None

    result = _resolve(_raw(code, name), region_code=region_code, region_name=region_name)

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == reference.rule.rule_id
    assert result.rule.rule_id.startswith("SERVC_QUAL_")
    assert result.rule.institution_scope == RULE_SCOPE_ALL
    assert result.scope_stage == RULE_SCOPE_ALL
    assert PPS_CITED_LOCAL_INSTITUTION_WARNING in result.warnings


def test_unlisted_local_enterprise_keeps_sido_rule() -> None:
    result = _resolve(
        _raw(NON_TARGET_LOCAL_ENTERPRISE_CODE, NON_TARGET_LOCAL_ENTERPRISE_NAME),
        region_code="11",
        region_name="서울특별시",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert PPS_CITED_LOCAL_INSTITUTION_WARNING not in result.warnings


@pytest.mark.parametrize(
    ("code", "name", "region_code", "region_name", "expected_rule_id"),
    [
        (
            "B551939",
            "제주특별자치도개발공사",
            "50",
            "제주특별자치도",
            "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
        ),
        (
            "B552833",
            "거제해양관광개발공사",
            "48",
            "경상남도",
            "SERVC_LOCAL_GN_20230105_ATTACH_01",
        ),
    ],
)
def test_mixed_label_institution_keeps_existing_judgment(
    code: str,
    name: str,
    region_code: str,
    region_name: str,
    expected_rule_id: str,
) -> None:
    result = _resolve(_raw(code, name), region_code=region_code, region_name=region_name)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.scope_stage == RULE_SCOPE_REGION
    assert PPS_CITED_LOCAL_INSTITUTION_WARNING not in result.warnings


@pytest.mark.parametrize(
    ("code", "name", "_region_code", "_region_name"),
    MIXED_LABEL_INSTITUTIONS,
    ids=[code for code, _name, _region_code, _region_name in MIXED_LABEL_INSTITUTIONS],
)
def test_mixed_label_institution_codes_are_not_listed(
    code: str,
    name: str,
    _region_code: str,
    _region_name: str,
) -> None:
    assert is_pps_cited_local_institution(code) is False
    assert is_pps_cited_local_institution(name) is False


def test_institution_name_is_not_used_as_code() -> None:
    assert is_pps_cited_local_institution("구리농수산물공사") is False
    assert is_pps_cited_local_institution(" Z003836 ") is True
    assert is_pps_cited_local_institution(None) is False
