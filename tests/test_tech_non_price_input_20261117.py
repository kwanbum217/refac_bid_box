"""기술용역 공고별 비가격 점수 입력 계약 시험 (2026-11-17).

정본: .orca/capsules/task_tech_non_price_input_20261117/capsule.yaml

시험 항목:
 (a) 기술용역 공고에 비가격 입력이 없으면 TECH_NON_PRICE_REQUIRED 로 막는다.
 (b) 10억원 이상 구간(B=30, k=1, T=92)에 비가격 70을 넣으면 최저가·최상가가 나온다.
 (c) 통과할 수 없는 값(같은 구간에 비가격 50)은 PRICE_BOUNDS_UNRESOLVED 로 막는다.
 (d) 회원 프로필의 non_price_quant_score 는 기술용역 비가격 점수로 쓰지 않는다.
 (e) 지방 시·도 경로는 회원 저장값 대체와 LOCAL_QUANT_REQUIRED 가 그대로다.
 (f) detail.html 에 새 차단 코드의 문구·배지·입력란 라벨 매핑이 있다.

실물 모델·Redis·MySQL 은 호출하지 않는다. API 시험은 conftest 의 isolated_db(SQLite)
위에서 돌고, predict_price_api 는 대역으로 덮는다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.company_profiles import AccountQualificationFact
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "src/app/templates/bids/detail.html"
ANALYZE_URL = "/api/v1/evaluations/analyze"
RECOMMEND_URL = "/api/v1/evaluations/recommend"

TECH_RULE_ID = "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
INCHEON_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
TECH_METHOD_BELOW_1B = "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준"
TECH_METHOD_OVER_1B = "적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준"


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=560_000_000,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id="default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_tech_bid(
    db,
    *,
    notice_no: str,
    presmpt_prce: int = 600_000_000,
    method: str = TECH_METHOD_BELOW_1B,
    lwlt_rate: str = "87.495",
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="기술용역 비가격 입력 시험 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": method,
            "sucsfbidLwltRate": lwlt_rate,
            "srvceDivNm": "기술용역",
            "bidNtceDt": "2026-11-01 10:00:00",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _create_local_bid(db, *, notice_no: str) -> BidAnnouncement:
    """인천 시·도 규칙으로 판별되는 지방계약 공고."""
    db.add(
        G2BDemandInstitution(
            dminstt_cd="1234",
            dminstt_nm="인천광역시 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="28000",
            rgn_nm="인천광역시 남구",
            toplvl_instt_cd="6270000",
            toplvl_instt_nm="인천광역시",
            raw_json={},
        )
    )
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 비가격 입력 시험 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="인천광역시 본청",
        base_amount=500_000_000,
        presmpt_prce=500_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 이상",
            "sucsfbidLwltRate": "87.995",
            "srvceDivNm": "일반용역",
            "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
            "dminsttCd": "1234",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _add_member_facts(db, user_id: int, **kwargs) -> AccountQualificationFact:
    facts = AccountQualificationFact(user_id=user_id, version="1.0", **kwargs)
    db.add(facts)
    db.commit()
    db.refresh(facts)
    return facts


def _blocked_code(body: dict) -> str:
    return str(body.get("blocked_reason") or "").split(":", 1)[0]


def _recommend(client, bid, overrides: dict | None = None) -> dict:
    response = client.post(
        RECOMMEND_URL,
        json={"bid_id": bid.id, "overrides": dict(overrides or {})},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# (a) 입력이 없으면 TECH_NON_PRICE_REQUIRED
# --------------------------------------------------------------------------- #


def test_recommend_requires_tech_non_price_input(client, isolated_db, as_user) -> None:
    """기술용역 공고에 비가격 점수가 없으면 입력을 요구한다."""
    as_user(10)
    bid = _create_tech_bid(isolated_db, notice_no="TECH-NP-REQ-001")

    body = _recommend(client, bid)

    assert body["blocked"] is True
    assert _blocked_code(body) == "TECH_NON_PRICE_REQUIRED"
    assert body["rule_id"] == TECH_RULE_ID
    assert "사업수행능력평가 등 비가격 점수를 공고마다 입력해야" in body["blocked_reason"]
    assert body["price_bounds"] is None


def test_analyze_requires_tech_non_price_input(client, isolated_db, as_user) -> None:
    """분석 API 도 같은 공통 입력 확정 경로라 같은 차단 코드를 낸다."""
    as_user(10)
    bid = _create_tech_bid(isolated_db, notice_no="TECH-NP-REQ-002")

    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "candidate_bid_amount": 540_000_000,
            "qualification_input": {"disqualification": False},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is True
    assert _blocked_code(body) == "TECH_NON_PRICE_REQUIRED"


# --------------------------------------------------------------------------- #
# (b) 10억원 이상 구간 비가격 70 -> 계산 가능
# --------------------------------------------------------------------------- #


def test_over_1b_with_non_price_70_releases_bounds(client, isolated_db, as_user) -> None:
    """B=30·k=1·T=92 구간에 비가격 70을 넣으면 필요 가격점수 22로 통과 구간이 열린다."""
    as_user(10)
    bid = _create_tech_bid(
        isolated_db,
        notice_no="TECH-NP-OK-001",
        presmpt_prce=1_200_000_000,
        method=TECH_METHOD_OVER_1B,
    )

    body = _recommend(client, bid, {"manual_non_price_score": 70.0})

    assert body["blocked"] is False, body.get("blocked_reason")
    assert body["status"] == "success"
    assert body["rule_id"] == TECH_RULE_ID
    assert body["score_table"]["max_price_score"] == "30"
    assert body["score_table"]["multiplier"] == "1"
    assert body["score_table"]["pass_threshold"] == "92"  # noqa: S105
    assert body["non_price_score"] == "70"
    assert body["required_price_score"] == "22"
    assert body["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert "기술용역" in body["quant_notice"]

    bounds = body["price_bounds"]
    assert bounds["status"] == "ok", bounds.get("reasons")
    assert bounds["min_bid_amount"] is not None
    assert bounds["max_bid_amount"] is not None
    assert bounds["min_bid_amount"] <= bounds["max_bid_amount"]
    assert body["member_recommended_price"] is not None


def test_analyze_uses_tech_non_price_input(client, isolated_db, as_user) -> None:
    """분석 API 도 같은 입력을 비가격 점수로 환산한다."""
    as_user(10)
    bid = _create_tech_bid(
        isolated_db,
        notice_no="TECH-NP-OK-002",
        presmpt_prce=1_200_000_000,
        method=TECH_METHOD_OVER_1B,
    )

    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "candidate_bid_amount": 1_100_000_000,
            "qualification_input": {
                "disqualification": False,
                "manual_non_price_score": 70.0,
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success", body.get("blocked_reason")
    assert body["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert body["quant_notice"]
    assert {row["qualification_score"] for row in body["scenario_results"]} == {70.0}


# --------------------------------------------------------------------------- #
# (c) 통과할 수 없는 값은 PRICE_BOUNDS_UNRESOLVED
# --------------------------------------------------------------------------- #


def test_over_1b_with_non_price_50_blocks_on_price_bounds(client, isolated_db, as_user) -> None:
    """필요 가격점수 42가 배점한도 30을 넘어 통과 금액을 만들지 않는다."""
    as_user(10)
    bid = _create_tech_bid(
        isolated_db,
        notice_no="TECH-NP-BOUNDS-001",
        presmpt_prce=1_200_000_000,
        method=TECH_METHOD_OVER_1B,
    )

    body = _recommend(client, bid, {"manual_non_price_score": 50.0})

    assert body["blocked"] is True
    assert _blocked_code(body) == "PRICE_BOUNDS_UNRESOLVED"
    assert body["non_price_score"] == "50"
    assert body["required_price_score"] == "42"
    bounds = body["price_bounds"]
    assert bounds["status"] == "blocked"
    assert bounds["min_bid_amount"] is None
    assert bounds["max_bid_amount"] is None


# --------------------------------------------------------------------------- #
# (d) 회원 프로필 값은 기술용역에 쓰지 않는다
# --------------------------------------------------------------------------- #


def test_tech_ignores_member_non_price_quant_score(client, isolated_db, as_user) -> None:
    """회원 저장 일반용역 정량점수가 있어도 기술용역은 공고별 입력을 따로 요구한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, non_price_quant_score=Decimal("50"))
    bid = _create_tech_bid(isolated_db, notice_no="TECH-NP-MEMBER-001")

    body = _recommend(client, bid)

    assert body["blocked"] is True
    assert _blocked_code(body) == "TECH_NON_PRICE_REQUIRED"
    assert body["non_price_score"] is None


def test_tech_request_value_wins_even_with_member_score(client, isolated_db, as_user) -> None:
    """요청 수정값이 있으면 그 값만 쓰고 회원 저장값과 합치지 않는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, non_price_quant_score=Decimal("50"))
    bid = _create_tech_bid(
        isolated_db,
        notice_no="TECH-NP-MEMBER-002",
        presmpt_prce=1_200_000_000,
        method=TECH_METHOD_OVER_1B,
    )

    body = _recommend(client, bid, {"manual_non_price_score": 70.0})

    assert body["blocked"] is False, body.get("blocked_reason")
    assert body["non_price_score"] == "70"


# --------------------------------------------------------------------------- #
# (e) 지방 경로는 그대로다
# --------------------------------------------------------------------------- #


def test_local_path_still_uses_member_non_price_quant_score(client, isolated_db, as_user) -> None:
    """지방 시·도 규칙은 회원 저장 정량점수를 종전처럼 자동 기입한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, non_price_quant_score=Decimal("50"))
    bid = _create_local_bid(isolated_db, notice_no="TECH-NP-LOCAL-001")

    body = _recommend(client, bid)

    assert body["blocked"] is False, body.get("blocked_reason")
    assert body["rule_id"] == INCHEON_RULE_ID
    assert body["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert body["non_price_score"] == "50"


def test_local_path_still_blocks_without_any_non_price_score(client, isolated_db, as_user) -> None:
    """회원 저장값도 요청 수정값도 없으면 종전처럼 LOCAL_QUANT_REQUIRED 다."""
    as_user(10)
    bid = _create_local_bid(isolated_db, notice_no="TECH-NP-LOCAL-002")

    body = _recommend(client, bid)

    assert body["blocked"] is True
    assert _blocked_code(body) == "LOCAL_QUANT_REQUIRED"


# --------------------------------------------------------------------------- #
# (f) 화면 문구·배지·입력란 라벨
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_detail_maps_tech_non_price_required_text(template_source: str) -> None:
    """사유·안내 문구와 입력란 노출 코드에 TECH_NON_PRICE_REQUIRED 가 들어 있다."""
    reason_scope = template_source.split("function getBlockedReasonText(code)")[1].split(
        "function "
    )[0]
    guidance_scope = template_source.split("function getBlockedGuidanceText(code)")[1].split(
        "function "
    )[0]
    input_codes = template_source.split("const localInputCodes = {")[1].split("};", 1)[0]

    assert "'TECH_NON_PRICE_REQUIRED':" in reason_scope
    assert "'TECH_NON_PRICE_REQUIRED':" in guidance_scope
    assert "'TECH_NON_PRICE_REQUIRED': true" in input_codes
    assert "기술용역 비가격 점수(사업수행능력평가 등)" in reason_scope


def test_detail_shows_amber_badge_for_tech_non_price_required(template_source: str) -> None:
    """공고 기준 분석 배지가 새 코드를 '입력하면 계산 가능' 계열로 분류한다."""
    badge_scope = template_source.split("const scopeBadgeInputCodes = {")[1].split("};", 1)[0]

    assert "'TECH_NON_PRICE_REQUIRED': '비가격 점수 입력'" in badge_scope


def test_detail_uses_tech_specific_input_label(template_source: str) -> None:
    """기술용역일 때만 입력란 라벨을 사업수행능력 등 비가격 점수로 바꾼다."""
    assert 'id="label-manual-non-price-score"' in template_source
    assert "'비가격 점수(사업수행능력 등, 0~100)'" in template_source
    assert "'비가격 정량점수 (0~100)'" in template_source


def test_direct_input_section_stays_after_user_input_solves_block():
    from pathlib import Path

    body = (Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html").read_text(
        encoding="utf-8"
    )
    start = body.index("function renderLocalInputs(data)")
    render = body[start : body.index("function buildLocalInputs", start)]
    assert "data.quant_source === 'USER_INPUT_UNVERIFIED'" in render
    assert "SERVC_TECH_QUAL" in render
    assert "입력한 점수로 계산했습니다" in render
