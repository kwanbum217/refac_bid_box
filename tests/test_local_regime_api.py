"""적격심사 분석 API 의 지방계약(LOCAL) 경로 계약 시험.

정본: docs/design/local_regime_rules_design_20261005.md 0.1·6.5·8.3절.
 - LOCAL 시·도 규칙은 가격 배점표(B·k·T)를 확정하므로 MISSING_SCORE_TABLE 로 막지 않는다.
 - 정량 배점표는 기관 원문 미반영이라 manual_non_price_score 직접 입력을 요구한다.
 - 시·도 기준이 없으면 B·k·기준비율·통과점수를 모두 입력해야 계산하고, 응답에 미검증을 표시한다.

실물 모델·Redis·MySQL 은 호출하지 않는다. conftest 의 isolated_db(SQLite) 위에서 동작한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse

ANALYZE_URL = "/api/v1/evaluations/analyze"
INCHEON_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
INCHEON_SIMPLE_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=440_000_000,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_institution(db, *, code: str, toplvl_nm: str) -> None:
    db.add(
        G2BDemandInstitution(
            dminstt_cd=code,
            dminstt_nm=f"{toplvl_nm} 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="28000",
            rgn_nm=f"{toplvl_nm} 남구",
            toplvl_instt_cd="6270000",
            toplvl_instt_nm=toplvl_nm,
            raw_json={},
        )
    )
    db.commit()


def _create_local_bid(
    db,
    *,
    method: str = "시설분야용역 적격심사 추정가격 5억원 이상",
    presmpt_prce: int = 500_000_000,
    raw_overrides: dict | None = None,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "sucsfbidLwltRate": "87.995",
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": "1234",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    data.update(raw_overrides or {})
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 적격심사 테스트 공고",
        bid_ntce_no="EVAL-LOCAL-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="인천광역시 본청",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _payload(bid_id: int, qualification: dict | None = None, amount: int = 407_448_800) -> dict:
    qualification_input: dict = {"disqualification": False}
    qualification_input.update(qualification or {})
    return {
        "bid_id": bid_id,
        "selected_model": "requested-evaluation-model",
        "candidate_bid_amount": amount,
        "qualification_input": qualification_input,
    }


def _client_post(client, bid_id: int, qualification: dict | None = None, amount: int = 407_448_800):
    return client.post(ANALYZE_URL, json=_payload(bid_id, qualification, amount))


def test_local_price_only_response_requires_manual_quant(client, isolated_db, as_user):
    """manual_non_price_score 가 없으면 LOCAL_QUANT_REQUIRED 로 막는다(8.3)."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(isolated_db)

    response = _client_post(client, bid.id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert "LOCAL_QUANT_REQUIRED" in payload["blocked_reason"]


def test_local_price_only_response_marks_unverified(client, isolated_db, as_user):
    """manual_non_price_score 를 입력하면 가격점수를 계산하고 미검증 출처를 표시한다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(isolated_db)

    response = _client_post(client, bid.id, {"manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == INCHEON_RULE_ID
    assert payload["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert payload["quant_notice"]
    # LOCAL 규칙에는 조달청 정량 배점표를 붙이지 않는다.
    assert payload["quant_score_table"] is None
    table = payload["score_table"]
    assert table is not None
    assert table["price_band_label"] == "10억원 미만 5억원 이상"
    assert table["threshold_band_label"] == "추정가격 10억원 미만"
    assert table["max_price_score"] == "50"
    assert table["multiplier"] == "2"
    assert table["pass_threshold"] == "95"  # noqa: S105
    assert table["source"]


def test_local_price_only_computes_price_score(client, isolated_db, as_user):
    """가격점수와 종합점수가 사용자 정량점수(미검증)로 계산된다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(isolated_db)

    payload = _client_post(
        client, bid.id, {"manual_non_price_score": 40.0}, amount=440_000_000
    ).json()

    base = next(s for s in payload["scenario_results"] if s["scenario_name"] == "기준")
    # B=50, k=2, 기준 88%, x = 440/500 = 0.88 → P = 50 - 2*|0.88-0.88|*100 = 50
    assert base["price_score"] == pytest.approx(50.0)
    assert base["qualification_score"] == pytest.approx(40.0)
    assert base["total_score"] == pytest.approx(90.0)


def test_local_no_rule_user_input_computes_price_only(client, isolated_db, as_user):
    """시·도 기준이 없어도 B·k·기준비율·통과점수를 모두 입력하면 계산하고 미확보를 표시한다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="서울특별시")
    bid = _create_local_bid(isolated_db)

    response = _client_post(
        client,
        bid.id,
        {
            "max_price_score": 60.0,
            "multiplier": 2.0,
            "pass_threshold": 95.0,
            "base_rate": 0.88,
            "manual_non_price_score": 40.0,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["rule_id"] == "SERVC_LOCAL_USER_INPUT"
    assert payload["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert payload["score_table"]["source"] == "사용자 입력(지자체 기준 미확보)"
    assert payload["score_table"]["pass_threshold"] == "95"  # noqa: S105


def test_local_no_rule_without_all_inputs_stays_blocked(client, isolated_db, as_user):
    """B·k·기준비율·통과점수 중 하나라도 비면 LOCAL_RULE_NOT_FOUND 차단을 유지한다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="서울특별시")
    bid = _create_local_bid(isolated_db)

    payload = _client_post(
        client,
        bid.id,
        {
            "max_price_score": 60.0,
            "multiplier": 2.0,
            "pass_threshold": 95.0,
            # base_rate 누락
            "manual_non_price_score": 40.0,
        },
    ).json()

    assert payload["status"] == "blocked"
    assert "LOCAL_RULE_NOT_FOUND" in payload["blocked_reason"]


def test_local_service_type_unresolved_then_user_selection(client, isolated_db, as_user):
    """일반 띠는 세부유형 미확정으로 막고, 사용자가 고르면 그 별표를 쓴다(D5)."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(
        isolated_db, method="추정가격 2억원 미만인 용역", presmpt_prce=150_000_000
    )
    bid_id = bid.id

    unresolved = _client_post(client, bid_id, {"manual_non_price_score": 40.0}).json()
    assert unresolved["status"] == "blocked"
    assert "LOCAL_SERVICE_TYPE_UNRESOLVED" in unresolved["blocked_reason"]
    assert "local_service_type" in unresolved["blocked_reason"]

    selected = _client_post(
        client,
        bid_id,
        {"manual_non_price_score": 40.0, "local_service_type": "SIMPLE_LABOR"},
    ).json()
    assert selected["status"] == "success"
    assert selected["rule_id"] == INCHEON_SIMPLE_RULE_ID
