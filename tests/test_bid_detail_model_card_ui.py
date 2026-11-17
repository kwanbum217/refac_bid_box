"""공고 상세 AI 투찰 금액 분석기 모델 카드 회귀 시험.

2026-11-17 사용자 피드백으로 모델 카드('분석 모델' 블록)를 삭제했다. 모델 목록
요청과 모델 상세·선택 UI 가 템플릿에 다시 들어오지 않는지, 추천 요청이 화면
선택값 대신 서버 기본 모델을 쓰도록 null 을 보내는지 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_model_card_is_removed(template_source: str) -> None:
    for removed in (
        'id="model-summary"',
        'id="model-fit"',
        'id="model-details"',
        'id="model-select-wrap"',
        'id="selected-model"',
        'id="model-desc"',
        'id="model-tags"',
        'id="model-metrics"',
        "분석 모델",
    ):
        assert removed not in template_source, f"삭제된 모델 카드 요소가 남아 있음: {removed}"


def test_model_loading_script_is_removed(template_source: str) -> None:
    for removed in (
        "loadModels",
        "updateModelInfo",
        "buildModelSummary",
        "buildModelFit",
        "buildModelDescription",
        "renderModelTags",
        "renderModelMetrics",
        "predictions:list_models",
    ):
        assert removed not in template_source, f"삭제된 모델 스크립트가 남아 있음: {removed}"


def test_server_chooses_default_model(template_source: str) -> None:
    """선택 UI 가 없으므로 화면은 모델을 고르지 않고 서버 기본값에 맡긴다."""
    assert "selected_model: null" in template_source
    assert "$('#selected-model')" not in template_source


def test_default_view_excludes_developer_details(template_source: str) -> None:
    assert "joblib" not in template_source
    assert "weekday_sin" not in template_source
    assert "model.type" not in template_source
    assert "type: ${" not in template_source
