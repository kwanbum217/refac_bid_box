"""공고 상세 내 조건 추천의 안내 두 건을 고정한다.

추천 금액 옆에 정량점수와 금액의 관계를 알리는 문장을 두고, 시나리오 표의
투찰률은 행마다 반복하지 않고 표 위에 한 번만 보여준다.
"""

from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"
NOTICE = "정량점수가 낮을수록 추천 금액이 올라갑니다"


def _template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_member_recommendation_shows_score_notice_beside_amount():
    """추천 금액과 같은 줄(같은 flex 행)에 정량점수 안내 문장이 있다."""
    template = _template()

    assert NOTICE in template
    price_index = template.index('id="res-member-price"')
    rate_index = template.index('id="res-member-rate"')
    notice_index = template.index(NOTICE)
    assert price_index < notice_index < rate_index, "안내 문장이 추천 금액 옆에 없다"

    row_start = template.rindex('<div class="mt-2 flex flex-wrap items-baseline', 0, price_index)
    row_end = template.index('<p id="res-member-band-note"', price_index)
    assert row_start < notice_index < row_end, "안내 문장이 추천 금액 행을 벗어났다"


def test_member_recommendation_rate_is_shown_once_above_table():
    """시나리오 표의 투찰률은 행마다 그리지 않고 표 위에 한 번만 둔다."""
    template = _template()

    rate_marker = 'id="res-member-scenario-rate"'
    assert rate_marker in template, "투찰률 안내가 표 위에 없다"

    scenarios_index = template.index('id="res-member-scenarios"')
    rows_index = template.index('id="res-member-scenario-rows"')
    assert scenarios_index < template.index(rate_marker) < rows_index, "투찰률 안내가 표 위에 없다"

    thead_start = template.index("<thead", scenarios_index)
    thead_end = template.index("</thead>", thead_start)
    assert "투찰률" not in template[thead_start:thead_end], "표 머리글에 투찰률 열이 남아 있다"

    builder_start = template.index("$('#res-member-scenario-rows').html(")
    builder_end = template.index("}).join(''));", builder_start)
    builder = template[builder_start:builder_end]
    assert "verified_price_ratio" not in builder, "시나리오 행마다 투찰률을 다시 그린다"
    assert builder.count("<td") == 4, "시나리오 행 칸 수가 예정가격·투찰금액·판정 구성과 다르다"
