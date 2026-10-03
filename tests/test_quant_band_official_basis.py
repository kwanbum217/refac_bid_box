from decimal import Decimal
from types import SimpleNamespace

from src.app.api.v1.evaluations import _bid_estimated_price
from src.app.services.evaluation_rules import (
    QUANT_BAND_OVER_500M,
    QUANT_BAND_UNDER_500M,
    QUANT_SCORE_TABLES,
    select_quant_band,
)


def test_base_amount_alone_does_not_select_quant_band():
    bid = SimpleNamespace(presmpt_prce=None, base_amount=600_000_000)
    band, note = select_quant_band(QUANT_SCORE_TABLES["ATTACH_07"], _bid_estimated_price(bid))
    assert band is None
    assert "공고서의 추정가격을 확인하십시오" in note


def test_estimated_price_wins_over_base_amount():
    bid = SimpleNamespace(presmpt_prce=300_000_000, base_amount=600_000_000)
    band, note = select_quant_band(QUANT_SCORE_TABLES["ATTACH_07"], _bid_estimated_price(bid))
    assert band.band_key == QUANT_BAND_UNDER_500M
    assert note is None


def test_method_name_selects_band_without_estimated_price():
    band, note = select_quant_band(QUANT_SCORE_TABLES["ATTACH_07"], None, "추정가격 5억원 이상")
    assert band.band_key == QUANT_BAND_OVER_500M
    assert note is None


def test_method_name_wins_over_conflicting_estimated_price_with_warning():
    band, note = select_quant_band(
        QUANT_SCORE_TABLES["ATTACH_07"], Decimal("300000000"), "5억원 이상"
    )
    assert band.band_key == QUANT_BAND_OVER_500M
    assert note is not None
    assert "낙찰방법명" in note
    assert "추정가격" in note


def test_single_band_table_ignores_price():
    table = QUANT_SCORE_TABLES["ATTACH_06"]
    band, note = select_quant_band(table, Decimal("600000000"))
    assert len(table.bands) == 1
    assert band is table.bands[0]
    assert note is None
