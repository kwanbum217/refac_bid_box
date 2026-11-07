"""한국지역난방공사 2026-08-18판 일반용역 적격심사 정량 배점표 회귀 시험.

정본:
 - docs/analysis/kdhc_quant_20260818_20261107.md (규칙 ID 별 정량 항목·배점·원문 근거)
 - data/reference/institution_quant_tables_20261013.yaml (한국지역난방공사 항목)
 - 원문: data/sources/qualification/files/kdhc/60ea20722555_kdhc_20260818.txt
   (나라장터 R26BK01730527 첨부 '5. 일반용역적격심사세부기준(260818).pdf')

2026-08-18판 별표 1~9 의 심사항목 배점한도는 원문상 2026-01-01판과 같습니다. 그래서
SERVC_INST_KDHC_20260818_* 11개 규칙은 2026-01-01판과 같은 기관 배점표를 조회합니다.
달라진 것은 입찰가격 기준비율(88/93/91/88 -> 90/93/91/88)과 별표 6 지급여력비율 A
기준선(150% -> 130%)이며, 뒤엣것은 표의 배점한도가 아니라 등급 경계라 details 에 남깁니다.

원문에서 배점표를 읽지 못해 표를 등록하지 않은 규칙은 없습니다. 구판(2023-07-19판)
폐기물처리용역은 이 과업 범위가 아니므로 종전처럼 정량점수 직접 입력을 유지합니다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.app.services.evaluation_quant_institution import INSTITUTION_QUANT_SCORE_TABLES
from src.app.services.evaluation_rules import (
    INSTITUTION_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    QUANT_BASIS_INSTITUTION,
    QUANT_LIMIT_KIND_ABSENT,
    QUANT_LIMIT_KIND_DISQUALIFICATION,
    QUANT_LIMIT_KIND_PRICE,
    QUANT_LIMIT_KIND_REPUTATION,
    QUANT_LIMIT_KIND_SCORE,
    quant_band_scored_limit_total,
    quant_score_table_for_rule,
    select_quant_band,
)

KDHC_NEW = "SERVC_INST_KDHC_20260818_"
KDHC_OLD = "SERVC_INST_KDHC_20260101_"

SERVICE_TYPES = (
    "ACADEMIC",
    "FACILITY",
    "SW",
    "SW_TARGET",
    "WASTE",
    "PASSENGER",
    "FREIGHT",
    "INSURANCE",
    "REPAIR",
    "LEASE",
    "OTHER",
)

# 원문 별표 1~9 의 심사항목별 배점한도(추정가격 5억원 이상 / 5억원 미만).
# 2026-08-18판 PDF 원문 줄 번호를 함께 적습니다.
# (item_name, over_500m, under_500m, source_row)
ACADEMIC_ITEMS = (
    ("1. 이행실적", 20, 10, 459),
    ("2. 경영상태(신용평가등급)", 10, 20, 461),
    ("3. 기술능력(기술인력 보유)", 10, None, 462),
    ("4. 신인도", None, None, 463),
    ("입찰가격", 60, 70, 467),
    ("결격사유", -20, -20, 474),
)
FACILITY_ITEMS = (
    ("1. 이행실적", 20, None, 593),
    ("2. 경영상태(신용평가등급)", 10, 20, 596),
    ("3. 신인도", None, None, 597),
    ("근로조건 이행계획의 적정성", 10, 10, 603),
    ("입찰가격", 60, 70, 608),
    ("결격사유", -20, -20, 613),
)
SW_ITEMS = (
    ("1. 이행실적", 20, None, 736),
    ("2. 경영상태(신용평가등급)", 10, 20, 739),
    ("3. 기술능력(기술인력 보유 상황)", 10, 10, 740),
    ("4. 신인도", None, None, 742),
    ("입찰가격", 60, 70, 746),
    ("결격사유", -20, -20, 751),
)
SW_TARGET_ITEMS = (
    ("1. 이행실적", 20, None, 890),
    ("2. 경영상태(신용평가등급)", 10, 20, 893),
    ("3. 기술능력(기술인력 보유 상황)", 10, 10, 894),
    ("4. 신인도", None, None, 896),
    ("입찰가격", 60, 70, 900),
    ("결격사유", -20, -20, 905),
)
WASTE_ITEMS = (
    ("1. 이행실적", 20, 10, 1022),
    ("2. 경영상태(신용평가등급)", 10, 10, 1024),
    ("3. 기술능력 가. 기술인력 보유상황", 9, 9, 1027),
    ("3. 기술능력 나. 기술 보유상황", 1, 1, 1029),
    ("4. 신인도", None, None, 1031),
    ("입찰가격", 60, 70, 1035),
    ("결격사유", -20, -20, 1043),
)
PASSENGER_ITEMS = (
    ("1. 이행실적", 20, 10, 1161),
    ("2. 경영상태(신용평가등급)", 10, 10, 1163),
    ("3. 기술능력(안전성 정도)", 10, 10, 1164),
    ("4. 신인도", None, None, 1165),
    ("입찰가격", 60, 70, 1169),
    ("결격사유", -20, -20, 1175),
)
FREIGHT_ITEMS = (
    ("1. 이행실적", 20, 10, 1295),
    ("2. 경영상태(신용평가등급)", 20, 20, 1299),
    ("3. 신인도", None, None, 1300),
    ("입찰가격", 60, 70, 1303),
    ("결격사유", -20, -20, 1311),
)
INSURANCE_ITEMS = (
    ("1. 보험금 지급능력(지급여력비율)", 40, 30, 1448),
    ("2. 신인도", None, None, 1451),
    ("입찰가격", 60, 70, 1458),
    ("결격사유", -20, -20, 1468),
)
REPAIR_ITEMS = (
    ("1. 이행실적", 20, 10, 1515),
    ("2. 경영상태(신용평가등급)", 10, 20, 1517),
    ("3. 기술능력(기술신용평가등급)", 10, 0, 1518),
    ("4. 신인도", None, None, 1519),
    ("입찰가격", 60, 70, 1523),
    ("결격사유", -20, -20, 1528),
)
LEASE_ITEMS = (
    ("1. 경영상태(신용평가등급)", 20, 20, 1636),
    ("2. 사후관리(A/S)", 10, 10, 1639),
    ("3. 신인도", None, None, 1640),
    ("입찰가격", 70, 70, 1643),
    ("결격사유", -20, -20, 1654),
)
OTHER_ITEMS = (
    ("1. 이행실적", 20, 10, 1756),
    ("2. 경영상태(신용평가등급)", 30, 10, 1758),
    ("3. 신인도", None, None, 1759),
    ("입찰가격", 50, 80, 1762),
    ("결격사유", -20, -20, 1767),
)

TWO_BAND_ITEMS = {
    "ACADEMIC": ACADEMIC_ITEMS,
    "FACILITY": FACILITY_ITEMS,
    "SW": SW_ITEMS,
    "SW_TARGET": SW_TARGET_ITEMS,
    "WASTE": WASTE_ITEMS,
    "PASSENGER": PASSENGER_ITEMS,
    "FREIGHT": FREIGHT_ITEMS,
    "INSURANCE": INSURANCE_ITEMS,
    "REPAIR": REPAIR_ITEMS,
}


def _rule(rule_id: str):
    return next(rule for rule in INSTITUTION_RULES if rule.rule_id == rule_id)


def _band(table, band_key: str):
    return next(band for band in table.bands if band.band_key == band_key)


def test_every_20260818_rule_resolves_its_quant_table() -> None:
    """2026-08-18판 11개 규칙이 모두 기관 정량 배점표를 조회한다(정량표 없음 해소)."""
    for service_type in SERVICE_TYPES:
        rule_id = f"{KDHC_NEW}{service_type}"
        rule = _rule(rule_id)
        assert rule.quant_basis == QUANT_BASIS_INSTITUTION, rule_id
        table = quant_score_table_for_rule(rule)
        assert table is not None, rule_id
        assert table is INSTITUTION_QUANT_SCORE_TABLES[rule_id]
        assert table.is_institution is True


def test_quant_table_absent_rules_are_only_the_predecessor() -> None:
    """원문에서 읽지 못해 표를 남기지 않은 2026-08-18판 규칙은 없고 구판만 남는다."""
    no_table = {
        rule.rule_id
        for rule in INSTITUTION_RULES
        if rule.rule_id.startswith(("SERVC_INST_KDHC_20260818_", "SERVC_INST_KDHC_20230719_"))
        and rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED
    }
    assert no_table == {"SERVC_INST_KDHC_20230719_WASTE"}
    assert quant_score_table_for_rule(_rule("SERVC_INST_KDHC_20230719_WASTE")) is None


def test_20260818_band_totals_and_item_limits_match_the_original() -> None:
    """별표 1~9 의 구간별 항목 배점한도가 2026-08-18판 원문 표와 같다."""
    for service_type, items in TWO_BAND_ITEMS.items():
        table = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_NEW}{service_type}"]
        over = _band(table, "over_500m")
        under = _band(table, "under_500m")
        assert [item.item_name for item in over.items] == [row[0] for row in items]
        assert [item.item_name for item in under.items] == [row[0] for row in items]
        for index, (name, over_limit, under_limit, source_row) in enumerate(items):
            expected_over = None if over_limit is None else Decimal(str(over_limit))
            expected_under = None if under_limit is None else Decimal(str(under_limit))
            assert over.items[index].limit == expected_over, (service_type, "over", name)
            assert under.items[index].limit == expected_under, (service_type, "under", name)
            assert str(source_row) in over.items[index].source, (service_type, name)
        assert quant_band_scored_limit_total(over) == over.total_limit == Decimal("100")
        assert quant_band_scored_limit_total(under) == under.total_limit == Decimal("100")


def test_lease_single_band_matches_original() -> None:
    """별표 8 임대차는 단일 구간이고 경영상태 20·사후관리 10·입찰가격 70 이다."""
    table = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_NEW}LEASE"]
    assert len(table.bands) == 1
    band = table.bands[0]
    assert band.band_key == "single"
    assert band.band_label == "단일 구간"
    limits = {item.item_name: item.limit for item in band.items}
    assert limits["1. 경영상태(신용평가등급)"] == Decimal("20")
    assert limits["2. 사후관리(A/S)"] == Decimal("10")
    assert limits["입찰가격"] == Decimal("70")
    assert limits["결격사유"] == Decimal("-20")
    assert quant_band_scored_limit_total(band) == Decimal("100")


def test_other_bands_split_on_notice_amount() -> None:
    """별표 9 기타용역은 고시금액 경계로 갈리고 입찰가격이 50/80 이다."""
    table = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_NEW}OTHER"]
    keys = [band.band_key for band in table.bands]
    assert keys == ["notice_under", "notice_over"]
    assert [item.item_name for item in _band(table, "notice_over").items] == [
        row[0] for row in OTHER_ITEMS
    ]
    assert _band(table, "notice_over").items[-2].limit == Decimal("50")
    assert _band(table, "notice_under").items[-2].limit == Decimal("80")
    under, _ = select_quant_band(table, 200_000_000)
    assert under is not None
    assert under.band_key == "notice_under"
    over, _ = select_quant_band(table, 300_000_000)
    assert over is not None
    assert over.band_key == "notice_over"


def test_insurance_grade_boundary_is_130_percent() -> None:
    """별표 6 지급여력비율 A 기준선이 2026-01-01판 150% 에서 130% 로 내려갔다."""
    grades = _insurance_grades()
    assert "A 130% 이상 40/30" in grades
    assert not any("150%" in grade for grade in grades)


def _insurance_grades() -> list[str]:
    import yaml

    from src.app.services.evaluation_quant_institution import SOURCE_YAML

    project_root = Path(__file__).resolve().parent.parent
    spec = yaml.safe_load((project_root / SOURCE_YAML).read_text(encoding="utf-8"))
    institution = next(
        entry for entry in spec["institutions"] if entry["institution_name"] == "한국지역난방공사"
    )
    rule = next(rule for rule in institution["rules"] if rule["rule_id"] == f"{KDHC_NEW}INSURANCE")
    return [
        grade
        for detail in rule.get("details", [])
        for entry in detail["grades"]
        for grade in entry["grades"]
    ]


def test_item_limit_kinds_match_original_columns() -> None:
    """신인도는 reputation, 결격사유는 disqualification, 입찰가격은 price 로 둔다."""
    for service_type in SERVICE_TYPES:
        table = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_NEW}{service_type}"]
        for band in table.bands:
            kinds = {item.item_key: item.limit_kind for item in band.items}
            assert kinds["price"] == QUANT_LIMIT_KIND_PRICE
            assert kinds["disqualification"] == QUANT_LIMIT_KIND_DISQUALIFICATION
            assert kinds["reputation"] == QUANT_LIMIT_KIND_REPUTATION
            for item in band.items:
                if item.item_key in {"price", "disqualification", "reputation"}:
                    continue
                if item.limit_kind == QUANT_LIMIT_KIND_ABSENT:
                    assert item.limit is None
                else:
                    assert item.limit_kind == QUANT_LIMIT_KIND_SCORE


def test_20260818_tables_equal_the_20260101_tables() -> None:
    """두 판본의 심사항목 배점한도가 같아 규칙 ID 별 표 내용도 같다.

    별표 2(시설분야용역)만 예외입니다. 2026-08-18판 원문은 결격사유 -20 을 인쇄하는데
    (kdhc_2608#row613) 2026-01-01판 명세가 그 행을 싣지 않아 항목이 하나 다릅니다.
    """
    for service_type in SERVICE_TYPES:
        new = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_NEW}{service_type}"]
        old = INSTITUTION_QUANT_SCORE_TABLES[f"{KDHC_OLD}{service_type}"]
        assert [(band.band_key, band.total_limit) for band in new.bands] == [
            (band.band_key, band.total_limit) for band in old.bands
        ]
        for new_band, old_band in zip(new.bands, old.bands, strict=True):
            new_items = {item.item_name: item.limit for item in new_band.items}
            old_items = {item.item_name: item.limit for item in old_band.items}
            extra = set(new_items) - set(old_items)
            if service_type == "FACILITY":
                assert extra == {"결격사유"}
                assert new_items["결격사유"] == Decimal("-20")
                new_items.pop("결격사유")
            else:
                assert not extra
            assert new_items == old_items, (service_type, new_band.band_key)
