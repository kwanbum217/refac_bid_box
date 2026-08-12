"""상세 페이지가 예측 구간을 실제로 그리는지 검증합니다.

API 는 구간을 내놓는데 화면이 점 추정만 보여 주면 사용자는 단일 숫자를 그대로
신뢰합니다. 응답 스키마 필드명이 바뀌어도 템플릿은 조용히 undefined 를 읽을 뿐
예외가 나지 않으므로, 필드명 일치를 테스트로 고정합니다.
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
def test_template_reads_every_interval_field(markup: str, field: str):
    assert f"data.{field}" in markup, f"템플릿이 {field} 를 읽지 않습니다"


def test_interval_block_starts_hidden(markup: str):
    """구 모델은 구간이 null 입니다. 기본 노출이면 빈 값이 그대로 보입니다."""
    assert 'id="res-interval" class="hidden' in markup


def test_interval_block_is_toggled_both_ways(markup: str):
    """감추기만 하고 켜지 않거나 그 반대면 화면이 직전 예측을 남깁니다."""
    assert "$('#res-interval').removeClass('hidden')" in markup
    assert "$('#res-interval').addClass('hidden')" in markup


@pytest.mark.parametrize(
    "element_id", ["res-interval-rate", "res-interval-price", "res-interval-coverage"]
)
def test_interval_targets_exist(markup: str, element_id: str):
    assert f'id="{element_id}"' in markup


def test_interval_is_guarded_by_null_check(markup: str):
    """null 을 toFixed 하면 예외가 나 점 추정 표시까지 함께 죽습니다."""
    assert "data.rate_low != null" in markup


# --------------------------------------------------------------------------- #
# 근접도 막대와 대체 표기
# --------------------------------------------------------------------------- #


def test_template_no_longer_reads_confidence(markup: str):
    """confidence 는 계약에서 사라졌습니다. 남아 있으면 undefined 를 그립니다."""
    assert "data.confidence" not in markup


def test_template_reads_similarity_field(markup: str):
    assert "data.user_bid_similarity" in markup


def test_similarity_label_does_not_claim_model_confidence(markup: str):
    """막대는 입력 투찰가 근접도입니다. 신뢰도로 읽히는 문구를 남기면 안 됩니다."""
    assert "입력 투찰가 근접도" in markup
    assert "CONFIDENCE SCORE" not in markup
    assert "분석 신뢰도" not in markup


def test_similarity_block_is_toggled_both_ways(markup: str):
    """투찰가 미입력 시 근접도는 null 입니다. 감추지 않으면 직전 값이 남습니다."""
    assert "data.user_bid_similarity != null" in markup
    assert "$('#res-similarity').removeClass('hidden')" in markup
    assert "$('#res-similarity').addClass('hidden')" in markup


def test_template_surfaces_fallback(markup: str):
    """대체가 일어난 사실을 화면에서도 감추지 않습니다."""
    assert "data.fallback_used" in markup
    assert "data.requested_model" in markup
    assert 'id="res-fallback"' in markup
    assert "$('#res-fallback').removeClass('hidden')" in markup
    assert "$('#res-fallback').addClass('hidden')" in markup
