"""`scripts/map_past_criteria_to_rules.py` 의 네트워크·DB 없는 단위 시험.

기준명 표기 변형, 공고일 시행일 대조(미래 규칙 금지), 과거 공고 전용 이력 레지스트리 분기,
추정가격 구간 확정, CSV 왕복, 집계 재현을 합성 기준명으로 검증합니다. 실제 나라장터 요청이나
DB 조회는 하지 않습니다.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts.map_past_criteria_to_rules import (
    HISTORY_REGIME_FROM,
    NoticeRow,
    _agreement,
    _regime_rules,
    _service_types_from_criteria,
    build_rows,
    map_criteria_to_rule,
    summarize,
    write_results_csv,
)

# ----------------------------------------------------------------------------
# 기준명 정규화
# ----------------------------------------------------------------------------


def test_service_types_from_criteria_known_terms() -> None:
    assert _service_types_from_criteria("시설분야용역 적격심사") == ("FACILITY",)
    assert _service_types_from_criteria("일반용역 적격심사") == ("GENERAL",)
    assert "SW_NON_SME" in _service_types_from_criteria("소프트웨어용역 적격심사")


def test_service_types_from_criteria_unknown_and_empty() -> None:
    assert _service_types_from_criteria("적격심사 세부기준") == ()
    assert _service_types_from_criteria("") == ()
    assert _service_types_from_criteria(None) == ()


# ----------------------------------------------------------------------------
# 미래 규칙 금지
# ----------------------------------------------------------------------------


def test_regime_rules_empty_before_earliest_boundary() -> None:
    assert _regime_rules(date(2022, 1, 1)) == ()
    assert _regime_rules(date(2023, 4, 30)) == ()


def test_history_regime_boundary_matches_serving_registry() -> None:
    """이력 분기점은 서빙 레지스트리의 가장 이른 시행 구간 시작일과 같아야 합니다."""
    from src.app.services import evaluation_rules as er

    earliest = min(start for start, _ in er.RULE_REGIME_BOUNDARIES)
    assert earliest == HISTORY_REGIME_FROM


# ----------------------------------------------------------------------------
# 과거 공고 전용 이력 레지스트리 (공고일 < 2023-05-01)
# ----------------------------------------------------------------------------


def test_pre_2023_05_facility_maps_through_history_registry() -> None:
    result = map_criteria_to_rule("시설분야용역 적격심사", "2015-08-01", 400_000_000)
    assert result.scope == "PPS_HISTORY"
    assert result.rule_id == "SERVC_QUAL_HIST_2015_41_ATTACH_02"
    assert result.max_price_score == "70"
    assert result.multiplier == "5"
    assert result.pass_threshold == "85"  # noqa: S105 - 배점표 통과점수(T) 필드
    assert result.lwlt_rate == "87.995"
    assert result.reason == ""


def test_pre_2023_05_uses_the_revision_that_was_in_force() -> None:
    # 2016-48 은 시행 구간이 뒤집혀 조회에서 빠지고, 같은 시행일의 2016-51 이 담당한다.
    result = map_criteria_to_rule("시설분야용역 적격심사", "2016-06-01", 300_000_000)
    assert result.rule_id == "SERVC_QUAL_HIST_2016_51_ATTACH_02"
    # 시행일 경계 당일도 그 판에 든다.
    edge = map_criteria_to_rule("시설분야용역 적격심사", "2016-05-01", 300_000_000)
    assert edge.rule_id == "SERVC_QUAL_HIST_2016_51_ATTACH_02"


def test_pre_2023_05_academic_uses_known_notice_amount() -> None:
    """2023-01~04 학술연구는 2022-42 판이며, 2023 년 고시금액(2.2억)이 근거로 있다."""
    over = map_criteria_to_rule("학술연구용역 적격심사", "2023-02-01", 238_109_427)
    assert over.scope == "PPS_HISTORY"
    assert over.rule_id == "SERVC_QUAL_HIST_2022_42_ATTACH_01"
    assert over.max_price_score == "40"
    assert over.multiplier == "2"
    assert over.lwlt_rate == "80.495"

    under = map_criteria_to_rule("학술연구용역 적격심사", "2023-02-01", 100_000_000)
    assert under.max_price_score == "70"
    assert under.multiplier == "4"
    assert under.lwlt_rate == "84.245"


def test_pre_2023_05_unknown_notice_amount_is_not_guessed() -> None:
    """2019 년 고시금액은 저장소에 근거가 없어 값을 만들지 않고 사유만 남긴다."""
    result = map_criteria_to_rule("학술연구용역 적격심사", "2019-04-12", 90_276_363)
    assert result.rule_id is None
    assert "고시금액" in result.reason


def test_pre_2023_05_uncovered_service_types_are_unmapped() -> None:
    tech = map_criteria_to_rule("기술용역 적격심사", "2018-05-01", 300_000_000)
    assert tech.rule_id is None
    assert "TECH" in tech.reason

    general = map_criteria_to_rule("일반용역 적격심사", "2018-05-01", 300_000_000)
    assert general.rule_id is None
    assert "GENERAL" in general.reason


def test_pre_2023_05_before_history_window_is_unmapped() -> None:
    result = map_criteria_to_rule("시설분야용역 적격심사", "2015-01-15", 400_000_000)
    assert result.rule_id is None
    assert "개정판이 없습니다" in result.reason


def test_pre_2023_05_competition_product_variants_are_ambiguous() -> None:
    """대상/비대상 별표가 둘 다 있으면 기준명만으로 하나를 고르지 않는다."""
    result = map_criteria_to_rule("소프트웨어용역 적격심사", "2018-05-01", 300_000_000)
    assert result.rule_id is None
    assert result.reason == "이력 별표 후보가 둘 이상"


def test_pre_2023_05_institution_and_region_rules_still_win() -> None:
    """공고일이 이력 구간이어도 기관·LOCAL 후보가 있으면 기존 우선순위가 유지된다."""
    institution = map_criteria_to_rule(
        "일반용역 적격심사",
        "2020-01-01",
        200_000_000,
        institution_code="1613000",
        institution_name="국토교통부",
    )
    assert institution.scope == "INSTITUTION"
    assert institution.rule_id == "SERVC_INST_MOLIT_20180104_GENERAL"


def test_mapped_rule_never_effective_after_announcement() -> None:
    cases = [
        ("시설분야용역 적격심사", "2024-06-01", 400_000_000),
        ("학술연구용역 적격심사", "2024-06-01", 300_000_000),
        ("학술연구용역 적격심사", "2024-06-01", 100_000_000),
        ("보험용역 적격심사", "2025-10-01", 600_000_000),
    ]
    for criteria, announced, price in cases:
        result = map_criteria_to_rule(criteria, announced, price)
        assert result.rule_id is not None, (criteria, announced, price)
        rule = next(rule for rule in (*_all_rules(),) if rule.rule_id == result.rule_id)
        assert date.fromisoformat(rule.effective_date) <= date.fromisoformat(announced)


def _all_rules():
    from src.app.services import evaluation_rules as er

    seen: dict[str, object] = {}
    for rule in (
        *er.INSTITUTION_RULES,
        *er.LOCAL_RULES,
        *(rule for _, rules in er.RULE_REGIME_BOUNDARIES for rule in rules),
    ):
        seen[rule.rule_id] = rule
    return tuple(seen.values())


# ----------------------------------------------------------------------------
# 조달청 규칙 대응
# ----------------------------------------------------------------------------


def test_facility_maps_and_applies_conditional_b() -> None:
    under = map_criteria_to_rule("시설분야용역 적격심사", "2024-06-01", 400_000_000)
    assert under.rule_id == "SERVC_QUAL_PRE_20230501_ATTACH_01"
    assert under.max_price_score == "70"
    assert under.multiplier == "5"
    assert under.pass_threshold == "85"  # noqa: S105 - 배점표 통과점수(T)이지 비밀번호가 아님
    assert under.lwlt_rate == "87.995"

    over = map_criteria_to_rule("시설분야용역 적격심사", "2024-06-01", 600_000_000)
    assert over.max_price_score == "60"
    assert over.multiplier == "5"


def test_academic_band_uses_notice_amount() -> None:
    under = map_criteria_to_rule("학술연구용역 적격심사", "2024-06-01", 100_000_000)
    assert under.rule_id == "SERVC_QUAL_PRE_20230501_ATTACH_06"
    assert under.multiplier == "4"

    over = map_criteria_to_rule("학술연구용역 적격심사", "2024-06-01", 300_000_000)
    assert over.rule_id == "SERVC_QUAL_PRE_20230501_ATTACH_07"
    assert over.multiplier == "2"


def test_general_has_no_regime_rule_before_post() -> None:
    result = map_criteria_to_rule("일반용역 적격심사", "2024-06-01", 300_000_000)
    assert result.rule_id is None


# ----------------------------------------------------------------------------
# LOCAL 및 기관 규칙 대응
# ----------------------------------------------------------------------------


def test_local_region_rule_selected_by_institution_name() -> None:
    result = map_criteria_to_rule(
        "일반용역 적격심사",
        "2025-01-01",
        400_000_000,
        institution_name="서울특별시",
    )
    assert result.scope == "LOCAL"
    assert result.rule_id == "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
    assert result.max_price_score == "70"
    assert result.multiplier == "4"
    assert result.lwlt_rate == "86.745"


def test_institution_rule_selected_by_code() -> None:
    result = map_criteria_to_rule(
        "일반용역 적격심사",
        "2020-01-01",
        200_000_000,
        institution_code="1613000",
        institution_name="국토교통부",
    )
    assert result.scope == "INSTITUTION"
    assert result.rule_id == "SERVC_INST_MOLIT_20180104_GENERAL"
    assert result.multiplier == "20"
    assert result.lwlt_rate == "87.745"


def test_local_rule_not_effective_yet_is_not_used() -> None:
    result = map_criteria_to_rule(
        "일반용역 적격심사",
        "2024-01-01",
        400_000_000,
        institution_name="서울특별시",
    )
    # 서울 LOCAL 규칙 시행일은 2024-08-12 이므로 2024-01-01 공고에는 쓰지 않는다.
    assert result.rule_id is None


# ----------------------------------------------------------------------------
# CSV 왕복 및 집계
# ----------------------------------------------------------------------------


def _sample_and_pilot(tmp_path: Path) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    sample = {
        "2024A": {
            "bid_ntce_no": "2024A",
            "bid_ntce_dt": "2024-06-01 10:00:00",
            "raw_data": json.dumps({"dminsttNm": "조달청", "dminsttCd": "1230000"}),
        },
        "2024B": {
            "bid_ntce_no": "2024B",
            "bid_ntce_dt": "2024-06-02 10:00:00",
            "raw_data": json.dumps({"dminsttNm": "조달청", "dminsttCd": "1230000"}),
        },
    }
    pilot = [
        {
            "year": "2024",
            "bid_ntce_no": "2024A",
            "estimated_price": "400000000",
            "criteria_name": "시설분야용역 적격심사",
            "max_price_score": "",
            "multiplier": "",
            "pass_threshold": "",
        },
        {
            "year": "2024",
            "bid_ntce_no": "2024B",
            "estimated_price": "400000000",
            "criteria_name": "시설분야용역 적격심사",
            "max_price_score": "70",
            "multiplier": "5",
            "pass_threshold": "85",
        },
    ]
    return sample, pilot


def test_build_rows_and_csv_round_trip(tmp_path: Path) -> None:
    sample, pilot = _sample_and_pilot(tmp_path)
    rows = build_rows(sample, pilot)
    assert len(rows) == 2

    out = tmp_path / "map.csv"
    write_results_csv(rows, out)
    with out.open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert written[0]["bid_ntce_no"] == "2024A"
    assert written[0]["mapped"] == "1"
    assert written[0]["mapped_lwlt_rate"] == "87.995"
    assert written[1]["extracted_B"] == "70"


def test_summarize_counts_and_agreement(tmp_path: Path) -> None:
    sample, pilot = _sample_and_pilot(tmp_path)
    rows = build_rows(sample, pilot)
    summary = summarize(rows)
    assert summary["rows"] == 2
    assert summary["criteria"] == 2
    # 두 건 모두 B·k 미추출은 아니지만, 2024A 는 미추출이라 대응 모집단에 든다.
    assert summary["missing_bk_with_criteria"] == 1
    assert summary["mapped_missing_bk"] == 1
    # 검증 집합은 별표에서 B·k 를 뽑은 2024B 한 건이며 대응값이 일치한다.
    assert summary["validation_set"] == 1
    assert summary["k_agreement"] == 1


def test_agreement_helper() -> None:
    assert _agreement("2", "1|2|4") is True
    assert _agreement("5", "1|2|4") is False
    assert _agreement("", "1|2") is False
    assert _agreement("2", "") is False


def test_notice_row_as_row_shape() -> None:
    result = map_criteria_to_rule("시설분야용역 적격심사", "2024-06-01", 400_000_000)
    row = NoticeRow(
        year=2024,
        bid_ntce_no="X",
        bid_ntce_dt="2024-06-01",
        institution_name="조달청",
        institution_code="1230000",
        criteria_name="시설분야용역 적격심사",
        estimated_price=400_000_000,
        extracted_b="",
        extracted_k="",
        extracted_t="",
        mapped=result,
    )
    data = row.as_row()
    assert data["mapped"] == "1"
    assert data["rule_id"] == "SERVC_QUAL_PRE_20230501_ATTACH_01"
    assert set(data) == {
        "year",
        "bid_ntce_no",
        "bid_ntce_dt",
        "institution_name",
        "criteria_name",
        "estimated_price",
        "extracted_B",
        "extracted_k",
        "extracted_T",
        "scope",
        "rule_id",
        "service_type",
        "mapped_B",
        "mapped_k",
        "mapped_T",
        "mapped_lwlt_rate",
        "mapped",
        "reason",
    }


def test_unresolved_criteria_reason() -> None:
    result = map_criteria_to_rule("적격심사 세부기준", "2024-06-01", 400_000_000)
    assert result.rule_id is None
    assert "세부유형" in result.reason


def test_decimal_price_string_input() -> None:
    result = map_criteria_to_rule("시설분야용역 적격심사", "2024-06-01", "600000000")
    assert result.max_price_score == "60"
    assert Decimal(result.multiplier) == Decimal("5")
