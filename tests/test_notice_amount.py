"""`src/ml/notice_amount.py` 의 규칙용/ML 특징용 고시금액 표 분리 시험.

규칙용 표는 2021~2022 년 원문 값(기획재정부 고시 제2020-39호 2.1억)을 담고,
ML 특징용 표(NOTICE_AMOUNT_BY_YEAR)는 학습 특징 값을 고정하기 위해 그대로 둡니다.
"""

from __future__ import annotations

from src.ml.notice_amount import (
    DEFAULT_NOTICE_AMOUNT,
    NOTICE_AMOUNT_BY_YEAR,
    RULE_NOTICE_AMOUNT_BY_YEAR,
    notice_amount_for_year,
)


def test_rule_notice_amount_includes_2021_and_2022() -> None:
    assert notice_amount_for_year(2021) == 210_000_000
    assert notice_amount_for_year(2022) == 210_000_000


def test_rule_notice_amount_keeps_later_years() -> None:
    assert notice_amount_for_year(2023) == 220_000_000
    assert notice_amount_for_year(2024) == 220_000_000
    assert notice_amount_for_year(2025) == 230_000_000
    assert notice_amount_for_year(2026) == 230_000_000


def test_rule_notice_amount_defaults_to_220m_for_unknown_year() -> None:
    assert notice_amount_for_year(2019) == 220_000_000
    assert notice_amount_for_year(2027) == 220_000_000


def test_ml_feature_table_excludes_2021_and_2022() -> None:
    assert 2021 not in NOTICE_AMOUNT_BY_YEAR
    assert 2022 not in NOTICE_AMOUNT_BY_YEAR
    assert DEFAULT_NOTICE_AMOUNT == 220_000_000


def test_rule_table_has_evidenced_2021_and_2022_only() -> None:
    assert RULE_NOTICE_AMOUNT_BY_YEAR[2021] == 210_000_000
    assert RULE_NOTICE_AMOUNT_BY_YEAR[2022] == 210_000_000
