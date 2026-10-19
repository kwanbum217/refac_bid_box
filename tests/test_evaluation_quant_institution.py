"""기관 정량평가 배점표(Q2 명세) 반영 계약 테스트.

정본:
  - 명세: data/reference/institution_quant_tables_20261013.yaml (기관 10곳, 규칙 67개, 구간 136개)
  - 생성본: src/app/services/evaluation_quant_institution.py (scripts/build_institution_quant_tables.py)
  - 규칙·조회: src/app/services/evaluation_rules.py

기관 배점표가 있는 규칙은 quant_basis=INSTITUTION 이고 rule_id 로 표를 찾으며, 명세가
부분이라 표를 확정할 수 없는 한국가스공사·해양환경공단·한국공항공사 규칙은 종전처럼
정량점수 직접 입력을 유지한다. 조달청 별표 표(QUANT_SCORE_TABLES)는 하나도 바뀌면 안 된다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

import scripts.build_institution_quant_tables as builder
from src.app.services.evaluation_quant_institution import INSTITUTION_QUANT_SCORE_TABLES
from src.app.services.evaluation_rules import (
    INSTITUTION_RULES,
    LOCAL_RULES,
    POST_20260727_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    QUANT_BASIS_INSTITUTION,
    QUANT_SCORE_TABLES,
    quant_band_scored_limit_total,
    quant_score_table_for_rule,
    select_quant_band,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "data/reference/institution_quant_tables_20261013.yaml"
# 심사항목 배점표를 확보하지 못해 표 없이 직접 입력을 유지하는 해양환경공단·한국공항공사 규칙입니다.
KOEM_NO_TABLE_ID = "SERVC_INST_KOEM_20250306_MARINE_WASTE"
KAC_NO_TABLE_IDS = (
    "SERVC_INST_KAC_20260814_ACADEMIC",
    "SERVC_INST_KAC_20260814_FACILITY",
    "SERVC_INST_KAC_20260814_WASTE",
    "SERVC_INST_KAC_20260814_INSURANCE",
    "SERVC_INST_KAC_20260814_REPAIR",
    "SERVC_INST_KAC_20260814_SOFTWARE_SME",
    "SERVC_INST_KAC_20260302_ACADEMIC",
    "SERVC_INST_KAC_20260302_INSURANCE",
    "SERVC_INST_KAC_20260302_SOFTWARE_SME",
)
KDHC_NO_TABLE_IDS = ("SERVC_INST_KDHC_20230719_WASTE",)


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _spec_rules() -> list[dict]:
    rules: list[dict] = []
    for institution in _spec()["institutions"]:
        if institution.get("quant_table_status") != "confirmed":
            continue
        rules.extend(institution["rules"])
    return rules


def test_all_confirmed_rules_have_a_table_and_partial_rules_do_not() -> None:
    """표가 있는 규칙만 INSTITUTION 범위이고, 한국가스공사는 직접 입력을 유지한다."""
    table_ids = set(INSTITUTION_QUANT_SCORE_TABLES)
    basis_ids = {
        rule.rule_id for rule in INSTITUTION_RULES if rule.quant_basis == QUANT_BASIS_INSTITUTION
    }
    assert table_ids == basis_ids
    assert len(table_ids) == 65
    other_ids = {rule.rule_id for rule in INSTITUTION_RULES} - table_ids
    assert other_ids == {
        "SERVC_INST_KOGAS_20260709_GENERAL",
        "SERVC_INST_KOGAS_20260709_FACILITY",
        KOEM_NO_TABLE_ID,
        *KAC_NO_TABLE_IDS,
        *KDHC_NO_TABLE_IDS,
    }
    for rule in INSTITUTION_RULES:
        if rule.rule_id in other_ids:
            assert rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED
            assert quant_score_table_for_rule(rule) is None
        else:
            assert rule.quant_basis == QUANT_BASIS_INSTITUTION
            assert quant_score_table_for_rule(rule) is INSTITUTION_QUANT_SCORE_TABLES[rule.rule_id]


def test_every_band_has_unique_item_keys_and_fixed_total() -> None:
    """구간마다 항목 키가 겹치지 않고, 신인도·결격사유를 뺀 합계가 배점표 합계와 같다."""
    for table in INSTITUTION_QUANT_SCORE_TABLES.values():
        assert table.is_institution is True
        for band in table.bands:
            keys = [item.item_key for item in band.items]
            assert len(keys) == len(set(keys)), (table.attachment, band.band_key, keys)
            assert quant_band_scored_limit_total(band) == band.total_limit


def test_table_values_match_yaml_spec() -> None:
    """생성본의 규칙·구간·항목 배점한도가 Q2 명세와 같다(드리프트 차단)."""
    spec_by_rule = {rule["rule_id"]: rule for rule in _spec_rules()}
    assert set(spec_by_rule) == set(INSTITUTION_QUANT_SCORE_TABLES)
    for rule_id, rule in spec_by_rule.items():
        table = INSTITUTION_QUANT_SCORE_TABLES[rule_id]
        spec_bands = {band["band_key"]: band for band in rule["bands"]}
        assert {band.band_key for band in table.bands} == set(spec_bands)
        for band in table.bands:
            spec_band = spec_bands[band.band_key]
            assert band.band_label == spec_band["band_label"]
            assert band.total_limit == Decimal(str(spec_band["total_limit"]))
            assert [item.item_name for item in band.items] == [
                item["name"] for item in spec_band["items"]
            ]
            for item, spec_item in zip(band.items, spec_band["items"], strict=True):
                spec_limit = spec_item.get("limit")
                expected = None if spec_limit is None else Decimal(str(spec_limit))
                assert item.limit == expected, (rule_id, band.band_key, item.item_name)


def test_generator_is_deterministic_and_covers_yaml() -> None:
    """생성 스크립트가 명세의 확정 규칙 수만큼 표를 만들고 다시 돌려도 같다."""
    first = builder.render_module()
    assert first == builder.render_module()
    assert first.count("QuantScoreTable(") == len(_spec_rules())
    assert first.count("QuantScoreBand(") == sum(len(rule["bands"]) for rule in _spec_rules())


def test_krc_band_selection_by_estimated_price() -> None:
    """한국농어촌공사 학술연구용역은 추정가격 5억 기준으로 구간을 고른다."""
    table = INSTITUTION_QUANT_SCORE_TABLES["SERVC_INST_KRC_20260624_ACADEMIC"]
    over, note = select_quant_band(table, 600_000_000)
    assert over is not None
    assert over.band_key == "over_500m"
    assert note is None
    under, _ = select_quant_band(table, 300_000_000)
    assert under is not None
    assert under.band_key == "under_500m"


def test_khs_multi_band_selection_uses_original_boundaries() -> None:
    """국가유산청은 1억·2.5억·5억·10억 원문 경계로 5구간을 고른다."""
    table = INSTITUTION_QUANT_SCORE_TABLES["SERVC_INST_KHS_20240517_BURIAL"]
    expected = {
        50_000_000: "under_100",
        150_000_000: "100_250",
        300_000_000: "250_500",
        700_000_000: "500_1000",
        1_500_000_000: "over_1000",
    }
    for price, band_key in expected.items():
        band, _ = select_quant_band(table, price)
        assert band is not None, price
        assert band.band_key == band_key, price


def test_kdhc_other_uses_notice_amount_boundary() -> None:
    """한국지역난방공사 기타용역은 고시금액(2.3억) 경계로 구간을 고른다."""
    table = INSTITUTION_QUANT_SCORE_TABLES["SERVC_INST_KDHC_20260101_OTHER"]
    under, _ = select_quant_band(table, 200_000_000)
    assert under is not None
    assert under.band_key == "notice_under"
    over, _ = select_quant_band(table, 300_000_000)
    assert over is not None
    assert over.band_key == "notice_over"


def test_institution_band_requires_estimated_price_when_multiple() -> None:
    """구간이 여러 개인데 추정가격이 없으면 임의로 고르지 않고 사유를 남긴다."""
    table = INSTITUTION_QUANT_SCORE_TABLES["SERVC_INST_KRC_20260624_ACADEMIC"]
    band, note = select_quant_band(table, None)
    assert band is None
    assert note is not None
    assert "추정가격" in note


def test_pps_tables_are_untouched_by_institution_lookup() -> None:
    """조달청 별표 표는 그대로이고 기관 표와 섞이지 않는다."""
    assert set(QUANT_SCORE_TABLES) == {
        "ATTACH_01",
        "ATTACH_02",
        "ATTACH_03",
        "ATTACH_04",
        "ATTACH_05",
        "ATTACH_06",
        "ATTACH_07",
        "ATTACH_08",
        "ATTACH_09",
        "ATTACH_10",
        "ATTACH_11",
        "ATTACH_15",
        "ATTACH_16",
        "ATTACH_17",
    }
    pps_rule = next(rule for rule in POST_20260727_RULES if rule.rule_id.endswith("ATTACH_01"))
    found = quant_score_table_for_rule(pps_rule)
    assert found is QUANT_SCORE_TABLES["ATTACH_01"]
    assert found is not None
    assert found.is_institution is False
    # LOCAL 시·도 규칙은 기관 표도 조달청 표도 아니므로 여전히 None 이다.
    assert LOCAL_RULES
    for rule in LOCAL_RULES:
        assert quant_score_table_for_rule(rule) is None


def test_institution_item_keys_cover_pss_input_kinds() -> None:
    """한국농어촌공사 학술연구용역 5억 이상 구간의 항목 키와 종류를 고정한다."""
    band = next(
        band
        for band in INSTITUTION_QUANT_SCORE_TABLES["SERVC_INST_KRC_20260624_ACADEMIC"].bands
        if band.band_key == "over_500m"
    )
    kinds = {item.item_key: item.limit_kind for item in band.items}
    assert kinds == {
        "performance": "score",
        "management": "score",
        "technical_capacity": "score",
        "reputation": "reputation",
        "price": "price",
        "disqualification": "disqualification",
    }


@pytest.mark.parametrize(
    ("attachment", "expected"),
    [
        ("별표 1", True),
        ("별표 9", True),
    ],
)
def test_institution_tables_mark_attachment(attachment: str, expected: bool) -> None:
    """기관 표는 원문 별표 표기를 그대로 갖는다."""
    for table in INSTITUTION_QUANT_SCORE_TABLES.values():
        if table.attachment == attachment:
            assert table.is_institution is expected
