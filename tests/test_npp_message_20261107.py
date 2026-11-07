"""비예가(NON_PRED_PRICE) 차단 문구와 공고 공개값 표시 시험.

docs/analysis/non_pred_price_211_20261107.md 5절 결정에 따라 차단은 유지하고, 문구를
'예정가격(기초금액) 미공개'로 정정했다. 화면에는 공고 공개값만 표시하며 계산값은 만들지 않는다.
"""

from pathlib import Path

from src.app.services.evaluation_rules import (
    BLOCK_CODE_NON_PRED_PRICE,
    resolve_evaluation_rule_from_raw_data,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETAIL_TEMPLATE = PROJECT_ROOT / "src" / "app" / "templates" / "bids" / "detail.html"


def _non_pred_result():
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "비예가",
            "sucsfbidLwltRate": "79.995",
        },
    )


def test_non_pred_price_block_stays_and_message_says_price_is_not_disclosed():
    result = _non_pred_result()

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_NON_PRED_PRICE
    message = result.block_reason_message or ""
    assert "공개되지 않" in message
    assert "예정가격이 없" not in message


def test_detail_template_shows_disclosed_values_without_calculating():
    source = DETAIL_TEMPLATE.read_text(encoding="utf-8")

    assert "'NON_PRED_PRICE'" in source
    assert "공개되지 않" in source
    assert "예정가격이 없" not in source
    assert "recommend-blocked-public" in source
    assert "이 값으로 투찰가를 계산하지 않습니다" in source
    assert "noticeLwltRate" in source
    assert "noticeEstimatedPrice" in source


def test_detail_template_hides_disclosed_values_when_missing():
    source = DETAIL_TEMPLATE.read_text(encoding="utf-8")

    assert "toggleClass('hidden', !hasRate)" in source
    assert "toggleClass('hidden', !hasEstimated)" in source
    assert "!isNonPred || (!hasRate && !hasEstimated)" in source
