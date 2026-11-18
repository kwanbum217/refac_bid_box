"""행안부 예규 제283호 구판과 학술 GENERAL 폴백 정정 회귀 시험."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.app.services.evaluation_rules import (
    LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES,
    MOIS_ACADEMIC_BAND_RULES_283,
    resolve_evaluation_rule_from_raw_data,
    select_mois_academic_band_rule,
)

METHODS = {
    "under": "적격심사제-추정가격 1억미만",
    "middle": "적격심사제-추정가격 2억미만 1억이상",
    "over": "적격심사제-추정가격 2억이상",
}
OLD_IDS = {
    "under": "SERVC_LOCAL_MOIS_ACADEMIC_20240701_UNDER_1E",
    "middle": "SERVC_LOCAL_MOIS_ACADEMIC_20240701_1E_2E",
    "over": "SERVC_LOCAL_MOIS_ACADEMIC_20240701_OVER_2E",
}
CURRENT_IDS = {
    "under": "SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E",
    "middle": "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E",
    "over": "SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E",
}
GENERAL_FALLBACK_CASES = (
    ("11", "서울특별시", "서울특별시 서대문구", "R25BK00934697", "2025-06-30 09:00:00"),
    ("28", "인천광역시", "인천광역시", "R25BK00825399", "2025-05-01 09:00:00"),
    ("30", "대전광역시", "대전광역시", "R25BK00633539", "2025-02-11 09:00:00"),
    ("30", "대전광역시", "대전광역시", "R25BK00880281", "2025-06-04 09:00:00"),
    ("30", "대전광역시", "대전광역시", "R26BK01402983", "2026-03-18 09:00:00"),
)


def _resolve(
    *,
    announced: str,
    method: str,
    sido: tuple[str | None, str | None] = ("44", "충청남도"),
    classes: tuple[str, str, str] = ("연구조사서비스", "학술연구서비스", "기타연구조사서비스"),
    regime: str | None = "LOCAL",
    app_std: str | None = "학술연구용역 적격심사 세부기준",
    service_type: str | None = None,
):
    price = "130000000"
    raw_data: dict[str, Any] = {
        "bidNtceNo": "R26BKTEST",
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "dminsttNm": sido[1],
        "dminsttCd": "3017000",
        "pubPrcrmntLrgClsfcNm": classes[0],
        "pubPrcrmntMidClsfcNm": classes[1],
        "pubPrcrmntClsfcNm": classes[2],
        "presmptPrce": price,
        "sucsfbidLwltRate": "80.495",
        "cntrctCnclsMthdNm": "지방계약" if regime == "LOCAL" else "국가계약",
    }
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime=regime,
        region_code=sido[0],
        region_name=sido[1],
        local_service_type=service_type,
        estimated_price=Decimal(price),
    )


@pytest.mark.parametrize("band", METHODS)
def test_283_and_current_rules_are_selected_by_announcement_date(band: str) -> None:
    academic = {
        "pubPrcrmntLrgClsfcNm": "연구조사서비스",
        "pubPrcrmntMidClsfcNm": "학술연구서비스",
        "pubPrcrmntClsfcNm": "기타연구조사서비스",
    }
    old = select_mois_academic_band_rule(METHODS[band], academic, date(2025, 6, 30))
    current = select_mois_academic_band_rule(METHODS[band], academic, date(2025, 7, 1))

    assert old is not None
    assert old.rule_id == OLD_IDS[band]
    assert current is not None
    assert current.rule_id == CURRENT_IDS[band]
    assert old.lwlt_rate == current.lwlt_rate == Decimal("80.495")
    assert old.base_rate == current.base_rate == Decimal("0.88")
    assert old.max_price_score == current.max_price_score
    assert old.multiplier == current.multiplier == Decimal("2")
    assert old.pass_threshold == current.pass_threshold == Decimal("85")


def test_before_283_is_still_blocked() -> None:
    result = _resolve(announced="2024-06-30 09:00:00", method=METHODS["under"])

    assert result.is_blocked
    assert result.block_reason_code == "RULE_REGIME_MISMATCH"


@pytest.mark.parametrize("band", METHODS)
def test_old_and_current_announcement_windows_resolve(band: str) -> None:
    old = _resolve(announced="2025-06-30 09:00:00", method=METHODS[band])
    current = _resolve(announced="2025-07-01 09:00:00", method=METHODS[band])

    assert old.rule is not None
    assert old.rule.rule_id == OLD_IDS[band]
    assert current.rule is not None
    assert current.rule.rule_id == CURRENT_IDS[band]


@pytest.mark.parametrize("sido,name,institution,bid_no,announced", GENERAL_FALLBACK_CASES)
def test_excluded_academic_general_fallback_cases_use_mois_band(
    sido: str, name: str, institution: str, bid_no: str, announced: str
) -> None:
    raw = {
        "bidNtceNo": bid_no,
        "bidNtceDt": announced,
        "sucsfbidMthdNm": METHODS["middle"],
        "dminsttNm": institution,
        "dminsttCd": f"{sido}00000",
        "pubPrcrmntLrgClsfcNm": "연구조사서비스",
        "pubPrcrmntMidClsfcNm": "학술연구서비스",
        "pubPrcrmntClsfcNm": "기타연구조사서비스",
        "presmptPrce": "130000000",
        "sucsfbidLwltRate": "80.495",
        "cntrctCnclsMthdNm": "지방계약",
        "sucsfbidMthdAppStd": "학술연구용역 적격심사 세부기준",
    }
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code=sido,
        region_name=name,
        estimated_price=Decimal("130000000"),
    )

    expected = OLD_IDS["middle"] if announced[:10] < "2025-07-01" else CURRENT_IDS["middle"]
    assert result.rule is not None
    assert result.rule.rule_id == expected
    assert not result.is_blocked


def test_fallback_boundaries_remain_unchanged() -> None:
    # USER_SELECTION은 시·도 별표 선택을 존중합니다.
    selected = _resolve(
        announced="2025-05-01 09:00:00",
        method=METHODS["middle"],
        sido=("28", "인천광역시"),
        service_type="GENERAL",
    )
    assert selected.rule is not None
    assert selected.rule.service_type == "GENERAL"

    # 국가계약과 학술 분류가 아닌 공고는 행안부 학술 띠로 바꾸지 않습니다.
    national = _resolve(
        announced="2025-05-01 09:00:00",
        method=METHODS["middle"],
        sido=("28", "인천광역시"),
        regime="NATIONAL",
    )
    non_academic = _resolve(
        announced="2025-05-01 09:00:00",
        method=METHODS["middle"],
        sido=("28", "인천광역시"),
        classes=("일반용역", "기타일반용역", ""),
    )
    assert national.rule is None or national.rule.service_type != "ACADEMIC"
    assert non_academic.rule is None or non_academic.rule.service_type != "ACADEMIC"

    # 기존 대구 격리 코드는 유지됩니다.
    assert frozenset({"27"}) == LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES
    assert len(MOIS_ACADEMIC_BAND_RULES_283) == 3
