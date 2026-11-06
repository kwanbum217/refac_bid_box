"""전라남도 지방계약 용역 공고의 조달청 일반용역 세부기준 준용 시험.

정본: .orca/capsules/task_jeonnam_pps_fallback_20261106/capsule.yaml
- 전남 세부기준(예규 제1075호) 제11조 ① 은 이 세부기준에 정하지 아니한 사항을 조달청
  일반용역 적격심사 세부기준 등에서 정한 바에 따르도록 준용한다.
- 전남 자체 별표가 없는 유형만 조달청 매칭 결과로 계산하고 경고
  (JEONNAM_PPS_FALLBACK_WARNING)를 붙인다.
- 다른 시·도, 다른 차단 코드, 전남 자체 별표가 있는 유형, 건설폐기물 띠 표기 경로는
  바꾸지 않는다.

DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    JEONNAM_LOCAL_RULE_EFFECTIVE_DATE,
    JEONNAM_PPS_FALLBACK_WARNING,
    MOE_CDW_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule,
)

METHOD_REPAIR = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
METHOD_FACILITY = "적격심사제-시설분야용역 적격심사 추정가격 5억원 이상"
METHOD_GENERAL_BAND = "적격심사제-추정가격 2억원 미만인 용역"
BID_DATE = "2026-06-01"
JEONNAM_FACILITY_RULE_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4"
PPS_REPAIR_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_15"


def _resolve(**kwargs: Any):
    params: dict[str, Any] = {
        "category": "Servc",
        "prearng_prce_dcsn_mthd_nm": "복수예가",
        "sucsfbid_mthd_nm": METHOD_REPAIR,
        "contract_regime": "LOCAL",
        "bid_ntce_dt": BID_DATE,
        "region_code": "46",
        "region_name": "전라남도",
    }
    params.update(kwargs)
    return resolve_evaluation_rule(**params)


# --------------------------------------------------------------------------- #
# (a) 전남·LOCAL·수리점검 유형은 조달청 규칙으로 계산한다
# --------------------------------------------------------------------------- #


def test_jeonnam_missing_type_uses_pps_rule() -> None:
    reference = _resolve(contract_regime=None)
    assert reference.rule is not None

    result = _resolve()
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_RULE_ID
    assert result.rule.rule_id.startswith("SERVC_QUAL_")
    assert result.rule.institution_scope == RULE_SCOPE_ALL
    assert result.scope_stage == RULE_SCOPE_ALL
    assert result.rule.rule_id == reference.rule.rule_id
    assert result.effective_lwlt_rate == reference.effective_lwlt_rate
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


# --------------------------------------------------------------------------- #
# (b)(c) 전남 외 시·도는 그대로 둔다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("region_code", "region_name"),
    [
        ("44", "충청남도"),
        ("27", "대구광역시"),
        ("36", "세종특별자치시"),
    ],
)
def test_other_regions_keep_local_rule_not_found(region_code: str, region_name: str) -> None:
    result = _resolve(region_code=region_code, region_name=region_name)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_seoul_keeps_its_own_rule() -> None:
    """서울은 수리점검 유형이 없어 일반 별표로 풀리며, 준용은 끼어들지 않는다."""
    result = _resolve(region_code="11", region_name="서울특별시")
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_LOCAL_SEOUL_")
    assert result.scope_stage == RULE_SCOPE_REGION
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (d) 전남 자체 별표가 있는 유형은 전남 규칙을 유지한다
# --------------------------------------------------------------------------- #


def test_jeonnam_own_rule_is_not_replaced() -> None:
    result = _resolve(sucsfbid_mthd_nm=METHOD_FACILITY)
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == JEONNAM_FACILITY_RULE_ID
    assert result.scope_stage == RULE_SCOPE_REGION
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (e) 예규 시행일 이전 공고는 준용하지 않는다
# --------------------------------------------------------------------------- #


def test_pre_effective_announcement_stays_blocked() -> None:
    assert date(2023, 3, 2) == JEONNAM_LOCAL_RULE_EFFECTIVE_DATE
    result = _resolve(bid_ntce_dt="2023-03-01")
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (f) 세부유형 선택 대기 차단은 준용하지 않는다
# --------------------------------------------------------------------------- #


def test_local_service_type_unresolved_stays_blocked() -> None:
    """준용 분기는 LOCAL_RULE_NOT_FOUND 전용이라 세부유형 선택 대기는 그대로 둔다.

    전남 규칙에는 GENERAL/SIMPLE_LABOR 가 없어 전남 입력으로는 이 차단이 나오지
    않으므로, 같은 낙찰방법명이 세부유형 선택 대기가 되는 인천으로 고정한다.
    """
    result = _resolve(
        sucsfbid_mthd_nm=METHOD_GENERAL_BAND,
        region_code="28",
        region_name="인천광역시",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.rule is None
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (g) 전남 건설폐기물 띠 표기 공고는 환경부고시 경로를 유지한다
# --------------------------------------------------------------------------- #


def test_jeonnam_cdw_band_keeps_moe_path() -> None:
    result = _resolve(sucsfbid_mthd_nm=METHOD_GENERAL_BAND)
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")
    assert MOE_CDW_WARNING in result.warnings
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings
