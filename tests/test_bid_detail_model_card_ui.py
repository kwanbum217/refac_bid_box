"""공고 상세 AI 투찰 금액 분석기 모델 카드 UI 회귀 시험.

모델 카드는 한 줄 요약만 기본으로 보이고, 개발자용 정보는 기본 닫힌
"모델 상세" 안에만 있어야 한다. 모델 선택과 추천 계산 요청 경로는 유지한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    match = re.search(rf"function {name}\([^)]*\) \{{(.*?)\n    \}}", source, re.S)
    assert match, f"{name} 함수를 찾지 못했습니다"
    return match.group(1)


def test_default_view_excludes_developer_details(template_source: str) -> None:
    assert "joblib" not in template_source
    assert "weekday_sin" not in template_source
    assert "model.type" not in template_source
    assert "type: ${" not in template_source


def test_model_details_is_closed_by_default(template_source: str) -> None:
    match = re.search(r"<details\b[^>]*id=\"model-details\"[^>]*>", template_source)
    assert match, "모델 상세 details 요소를 찾지 못했습니다"
    assert "open" not in match.group(0)
    assert ">모델 상세<" in template_source
    assert template_source.index('id="model-details"') < template_source.index('id="model-desc"')


def test_summary_line_uses_one_line_format(template_source: str) -> None:
    body = function_body(template_source, "buildModelSummary")
    assert "예측 모델" in body
    assert "${trainingDate} 학습" in body
    assert "${rowText} 기준" in body
    assert "모델 ID" not in body
    assert "type" not in body


def test_training_date_only_from_version_prefix(template_source: str) -> None:
    assert "/^v_(\\d{4})(\\d{2})(\\d{2})/" in template_source


def test_version_label_not_double_prefixed(template_source: str) -> None:
    assert "vv_" not in template_source
    assert "v${escapeHtml(model.version)}" not in template_source
    assert "/^v/i.test(version) ? version : `v${version}`" in template_source


def test_model_metrics_only_render_existing_values(template_source: str) -> None:
    assert "formatMetricValue" not in template_source
    assert "'성능', value: '대기'" not in template_source
    assert "$metrics.toggleClass('hidden', metricItems.length === 0)" in template_source
    assert 'id="model-metrics" class="mt-3 grid grid-cols-2 gap-2"' in template_source


def test_selector_contract_preserved(template_source: str) -> None:
    assert 'id="selected-model"' in template_source
    assert "$('#selected-model').change" in template_source
    assert "selected_model: $('#selected-model').val()" in template_source
    assert "scheduleRecommend();" in template_source
    assert (
        "$('#model-select-wrap').toggleClass('hidden', categoryModelCount <= 1)" in template_source
    )
