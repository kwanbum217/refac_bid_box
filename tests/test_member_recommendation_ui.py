"""내 조건 추천가 블록의 표시·문구를 실제 실행으로 검증합니다."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_evaluation_scope_badge_per_notice import _function_source

TEMPLATE_PATH = Path("src/app/templates/bids/detail.html")

CASES = {
    "raised": (
        {
            "member_recommended_price": 1000,
            "member_recommendation_basis": "raised_to_min",
            "non_price_score": "25",
            "prediction": {"optimal_price": 900},
        },
        True,
    ),
    "kept": (
        {
            "member_recommended_price": 950,
            "member_recommendation_basis": "ai",
            "non_price_score": "30",
            "prediction": {"optimal_price": 950},
        },
        True,
    ),
    "absent": ({"member_recommended_price": None, "member_recommendation_basis": None}, True),
    "bounds_not_ready": (
        {
            "member_recommended_price": 950,
            "member_recommendation_basis": "ai",
            "prediction": {"optimal_price": 950},
        },
        False,
    ),
}


@pytest.fixture(scope="module")
def rendered() -> dict[str, dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 를 사용할 수 없습니다")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    source = "\n".join(
        _function_source(template, name)
        for name in ("scoreText", "memberRecommendationText", "renderMemberRecommendation")
    )
    script = f"""
const state = {{}};
function el(id) {{
  state[id] = state[id] || {{ classes: new Set(id === '#res-member-recommendation' ? ['hidden'] : []), text: '' }};
  const node = state[id];
  const handle = {{
    toggleClass(names, on) {{ names.split(' ').forEach(n => on ? node.classes.add(n) : node.classes.delete(n)); return handle; }},
    text(value) {{ node.text = value; return handle; }},
  }};
  return handle;
}}
const $ = el;
const amountText = value => value == null ? '-' : String(value) + '원';
{source}
const out = {{}};
for (const [key, [data, ready]] of Object.entries({json.dumps(CASES, ensure_ascii=False)})) {{
  for (const k of Object.keys(state)) delete state[k];
  renderMemberRecommendation(data, ready);
  const box = state['#res-member-recommendation'];
  out[key] = {{
    hidden: box.classes.has('hidden'),
    amber: box.classes.has('bg-amber-50'),
    price: (state['#res-member-price'] || {{}}).text || '',
    reason: (state['#res-member-reason'] || {{}}).text || '',
  }};
}}
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(  # noqa: S603 - node 경로와 인자를 이 테스트가 직접 고정합니다
        [node, "-e", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_raised_price_is_highlighted_with_reason(rendered):
    out = rendered["raised"]
    assert out["hidden"] is False
    assert out["amber"] is True
    assert out["price"] == "1000원"
    assert out["reason"] == (
        "AI 예측가 900원은 정량점수 25점으로는 어떤 예정가격에서도 적격 통과점수에 못 미쳐 "
        "최저가로 올렸습니다."
    )


def test_unchanged_price_explains_it_is_inside_range(rendered):
    out = rendered["kept"]
    assert out["hidden"] is False
    assert out["amber"] is False
    assert (
        out["reason"]
        == "정량점수 30점 기준 통과 구간(최저가~최상가) 안이라 AI 예측가를 그대로 추천합니다."
    )


@pytest.mark.parametrize("case", ["absent", "bounds_not_ready"])
def test_block_is_hidden_without_member_range(rendered, case):
    assert rendered[case]["hidden"] is True


def test_block_sits_inside_prediction_result_and_is_rendered():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.index('id="prediction-result"')
    assert (
        start
        < template.index('id="res-member-recommendation"')
        < template.index('id="res-prediction-warning"')
    )
    amounts = _function_source(template, "renderRecommendAmounts")
    assert "renderMemberRecommendation(data, boundsReady);" in amounts
