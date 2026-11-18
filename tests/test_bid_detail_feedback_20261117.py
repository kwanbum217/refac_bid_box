"""2026-11-17 사용자 웹 피드백 반영 시험.

정본: .orca/capsules/task_fb_detail_20261117/capsule.yaml
 - 기초금액은 헤더 우측 끝이 아니라 공고명 아래 좌측에 둔다.
 - AI 투찰 금액 분석기에서 모델 블록을 지우고 투찰가 추천 계산을 카드 맨 아래로 옮긴다.
 - 입찰 예상가는 최저가~최상가 축의 가로 범위 그래프로 그리고, 위치 계산은
   priceRangePositions 순수 함수로 분리한다.
 - 공고 기준 분석 카드에서 규칙 표시 블록을 지운다.

렌더 시험은 로그인 회원 컨텍스트로 실제 SSR HTML 을 본다. 위치 계산 시험은
템플릿에서 함수를 그대로 떼어 node 로 실행하며, node 가 없는 환경에서는 건너뛴다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"
SRC_APP_PATH = Path(__file__).resolve().parents[1] / "src/app"
LEGACY_SUPPORT_PHRASE = "일반용역 적격심사만 지원"


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="detail_feedback_tester",
        password=make_password("pw-test-1234"),
        email="detail_feedback@example.com",
        nickname="상세 피드백 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _create_bid(
    db, *, notice_no: str = "FB-DETAIL-001", with_amount: bool = True
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        bid_ntce_nm="상세 피드백 반영 시험 공고",
        dminstt_nm="검증기관",
        category="Servc",
        base_amount=400_000_000 if with_amount else None,
        presmpt_prce=400_000_000 if with_amount else None,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow() + timedelta(days=7),
        collected_at=utcnow(),
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _header_slice(body: str) -> str:
    return body.split("<h1", 1)[1].split("h-content-padding", 1)[0]


# --------------------------------------------------------------------------- #
# 1. 기초금액: 헤더 좌측, 공고명·메타 줄 아래
# --------------------------------------------------------------------------- #


def test_header_places_base_amount_under_notice_name(auth_client, isolated_db) -> None:
    """기초금액은 공고명과 기관·게시일 아래 좌측에 크게 표시한다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text
    header = _header_slice(body)

    assert header.index("게시일") < header.index("기초금액")
    assert "₩400,000,000" in header
    # 우측 끝 정렬 블록은 사라졌다.
    assert "items-end shrink-0" not in body


def test_header_keeps_dash_branch_without_base_amount(auth_client, isolated_db) -> None:
    """기초금액이 없으면 같은 좌측 블록에서 '-' 를 보여 준다."""
    bid = _create_bid(isolated_db, notice_no="FB-DETAIL-002", with_amount=False)
    body = auth_client.get(f"/bids/{bid.id}/").text

    match = re.search(
        r'<div class="mt-4">\s*<div class="detail-label">기초금액</div>\s*<div[^>]*>(.*?)</div>',
        body,
        re.S,
    )
    assert match, "좌측 기초금액 블록을 찾지 못했습니다"
    assert match.group(1).strip() == "-"


# --------------------------------------------------------------------------- #
# 2. 분석기 카드: 모델 블록 삭제, 추천 계산은 카드 맨 아래
# --------------------------------------------------------------------------- #


def test_analyzer_card_drops_model_block(auth_client, isolated_db) -> None:
    """모델 블록과 그 화면 갱신용 스크립트가 남아 있지 않다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    for removed in (
        'id="model-summary"',
        'id="model-fit"',
        'id="model-details"',
        'id="model-select-wrap"',
        'id="selected-model"',
        "분석 모델",
        "loadModels",
        "updateModelInfo",
        "buildModelSummary",
    ):
        assert removed not in body, f"제거됐어야 할 모델 요소가 남아 있음: {removed}"

    # 모델 선택 UI 가 없으므로 추천 요청은 기본 모델을 쓰도록 null 을 보낸다.
    assert "selected_model: null" in body


def test_recommend_calculation_is_last_in_analyzer_card(auth_client, isolated_db) -> None:
    """분석기 카드는 정량평가 입력표 아래에 있고, 추천 계산 블록은 그 카드 맨 끝에 온다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert body.index('id="evaluation-card"') < body.index('id="recommend-intro"')
    recommend_index = body.index('id="recommend-status"')
    assert body.index('id="prediction-result"') < recommend_index
    assert body.index("res-common-reason") < recommend_index
    assert body.index('id="recommend-blocked"') < recommend_index
    # 분석기 카드가 왼쪽 칼럼의 마지막 카드다.
    assert recommend_index < body.index("Right Column: Sidebar")
    assert "grid grid-cols-1 md:grid-cols-2 gap-6" not in body


# --------------------------------------------------------------------------- #
# 3. 입찰 예상가 범위 그래프
# --------------------------------------------------------------------------- #


def test_price_range_chart_markup_precedes_amount_cells(auth_client, isolated_db) -> None:
    """범위 그래프는 예측 결과의 세 칸 위에 있고, 세 칸과 팝업은 그대로 남는다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="price-range-chart"' in body
    assert 'id="price-range-track"' in body
    assert 'id="price-range-markers"' in body
    assert body.index('id="price-range-chart"') < body.index('id="res-min-price-cell"')
    for cell in ('id="res-min-price"', 'id="res-optimal-price"', 'id="res-max-price"'):
        assert cell in body
    assert 'data-price-help="optimal"' in body


def test_chart_is_updated_where_amounts_are_filled(auth_client, isolated_db) -> None:
    """세 칸 숫자를 채우는 같은 경로에서 그래프도 갱신한다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "function priceRangePositions" in body
    render_amounts = body.split("function renderRecommendAmounts", 1)[1].split(
        "let recommendInFlight", 1
    )[0]
    assert "renderPriceRangeChart(data, boundsReady)" in render_amounts
    assert "function renderPriceRangeChart" in body
    # 그래프 표식은 라이브러리 없이 절대 위치 백분율로 그린다.
    assert "style=\"left:' + positions[marker.key] + '%;\"" in body


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node 가 없어 템플릿 스크립트를 실행할 수 없음")
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        # 정상 범위: 최저가 0%, 최상가 100%, 예측가 50%, 내 조건 추천가 80%.
        ((100, 150, 200, 180), {"min": 0, "optimal": 50, "max": 100, "member": 80}),
        # 최저가=최상가: 0 나누기 없이 같은 금액 표식이 가운데에 겹친다.
        ((100, 100, 100, None), {"min": 50, "optimal": 50, "max": 50, "member": None}),
        # 범위 밖: 0~100 으로 자른다.
        ((100, 50, 200, 500), {"min": 0, "optimal": 0, "max": 100, "member": 100}),
        # 최저가·최상가 없음: AI 예측가 한 점만 가운데, 축은 그리지 않는다.
        ((None, 150, None, None), {"min": None, "optimal": 50, "max": None, "member": None}),
    ],
)
def test_price_range_positions_boundaries(
    template_source: str, args: tuple, expected: dict
) -> None:
    """priceRangePositions 는 순수 함수이며 경계에서도 0~100 을 벗어나지 않는다."""
    start = template_source.index("function priceRangePositions")
    end = template_source.index("\n    }", start) + len("\n    }")
    function_source = template_source[start:end]
    call_args = ", ".join(json.dumps(value) for value in args)
    script = f"{function_source}\nconsole.log(JSON.stringify(priceRangePositions({call_args})));"

    completed = subprocess.run(  # noqa: S603
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    positions = json.loads(completed.stdout)

    assert positions["hasScale"] is (args[0] is not None and args[2] is not None)
    for key, value in expected.items():
        assert positions[key] == value, f"{key}: {positions[key]} != {value}"


# --------------------------------------------------------------------------- #
# 4. 공고 기준 분석 카드: 규칙 표시 블록 삭제
# --------------------------------------------------------------------------- #


def test_evaluation_card_drops_rule_block(auth_client, isolated_db) -> None:
    """규칙 표시 블록은 사라지고 계약 법령 범위·낙찰률 분포는 남는다."""
    bid = _create_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    for removed in (
        'id="evaluation-rule"',
        'id="rule-id"',
        'id="rule-name"',
        'id="rule-basis"',
        "적용 규칙",
    ):
        assert removed not in body, f"제거됐어야 할 규칙 요소가 남아 있음: {removed}"

    assert 'id="contract-regime-range"' in body
    assert 'id="negotiation-distribution"' in body


def test_legacy_support_phrase_is_gone() -> None:
    """'일반용역 적격심사만 지원' 고정 문구가 템플릿과 src/app 어디에도 없다."""
    candidates = [TEMPLATE_PATH, *sorted(SRC_APP_PATH.rglob("*"))]
    for path in candidates:
        if not path.is_file() or path.suffix not in {".html", ".py", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert LEGACY_SUPPORT_PHRASE not in text, f"고정 문구가 남아 있음: {path.as_posix()}"


def test_price_range_amounts_live_in_legend_not_on_track():
    body = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'id="price-range-legend"' in body
    start = body.index("function renderPriceRangeChart")
    render = body[start : body.index("function hasMemberQuantData", start)]
    assert "$('#price-range-legend').html(legend)" in render
    track_markup = render[render.index("const markers") : render.index("const legend")]
    assert "currencyFormatter" not in track_markup
