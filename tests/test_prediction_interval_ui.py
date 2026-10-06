"""상세 페이지가 예측 구간·근접도를 더 이상 그리지 않고 세 금액을 그리는지 검증합니다.

2026-10-06 피드백 개정으로 상세 화면의 투찰가 계산이 POST /api/v1/evaluations/recommend
자동 호출로 바뀌면서 입력 투찰가(#user-price)와 그에 딸린 예측 구간·근접도 표시가
제거되고 최저가·AI 예측가·최상가 카드가 대체했습니다. 응답 스키마에는 구간 필드가 남아
있으므로(서버 미변경), 템플릿이 그 필드를 읽지 않는 것을 고정합니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app.schemas.predictions import PredictPriceResponse

TEMPLATE = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"

INTERVAL_FIELDS = ("rate_low", "rate_high", "price_low", "price_high", "interval_coverage")


@pytest.fixture(scope="module")
def markup() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_response_schema_exposes_interval_fields():
    for field in INTERVAL_FIELDS:
        assert field in PredictPriceResponse.model_fields, f"{field} 가 응답 스키마에 없습니다"


@pytest.mark.parametrize("field", INTERVAL_FIELDS)
def test_template_no_longer_reads_interval_fields(markup: str, field: str):
    assert f"data.{field}" not in markup, f"템플릿이 제거된 {field} 를 읽습니다"


@pytest.mark.parametrize(
    "element_id",
    ["res-interval", "res-interval-rate", "res-interval-price", "res-interval-coverage"],
)
def test_interval_targets_removed(markup: str, element_id: str):
    assert f'id="{element_id}"' not in markup, (
        f"제거된 예측 구간 요소 {element_id} 가 남아 있습니다"
    )


def test_interval_and_similarity_blocks_toggled_nowhere(markup: str):
    """제거된 구간·근접도 블록을 켜고 끄는 코드가 남아 있으면 직전 값이 그대로 보입니다."""
    assert "$('#res-interval').removeClass('hidden')" not in markup
    assert "$('#res-interval').addClass('hidden')" not in markup
    assert "$('#res-similarity').removeClass('hidden')" not in markup


def test_template_no_longer_reads_confidence(markup: str):
    """confidence 는 계약에서 사라졌습니다. 남아 있으면 undefined 를 그립니다."""
    assert "data.confidence" not in markup


def test_template_no_longer_reads_similarity_field(markup: str):
    """입력 투찰가가 사라져 근접도도 제거됐습니다."""
    assert "data.user_bid_similarity" not in markup
    assert "입력 투찰가 근접도" not in markup
    assert 'id="res-similarity"' not in markup


def test_template_surfaces_prediction_fallback(markup: str):
    """모델 대체가 일어난 사실을 화면에서도 감추지 않습니다."""
    assert "prediction.fallback_used" in markup
    assert "prediction.requested_model" in markup
    assert 'id="res-fallback"' in markup
    assert "$('#res-fallback').removeClass('hidden')" in markup
    assert "$('#res-fallback').addClass('hidden')" in markup
