"""적격심사 분석 API 의 관리규정외 수기심사(MANUAL_EVALUATION) 차단 해제 계약 시험.

코디네이터 확인 사실(2026-10-17):
 - 입력이 없거나 일부만 들어오면 지금처럼 차단하고 부족한 항목을 안내한다.
 - 가격배점한도(B)·평점계수(k)·기준비율·통과점수가 모두 들어오면 그 값으로 계산한다.
 - 결과 근거에 '수기심사 공고: 사용자 입력 기준' 임을 남긴다.
 - 다른 차단 코드(RULE_NOT_FOUND, RULE_REGIME_MISMATCH 등)의 동작은 바꾸지 않는다.

LOCAL_RULE_NOT_FOUND 해제 경로(_local_user_input_rule)와 같은 구조라, 가격 파라미터 네 값과
함께 비가격 정량점수(manual_non_price_score)도 입력해야 총점이 계산된다.

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
from src.app.schemas.predictions import PredictPriceResponse

ANALYZE_URL = "/api/v1/evaluations/analyze"
RECOMMEND_URL = "/api/v1/evaluations/recommend"
MANUAL_METHOD = "적격심사제-관리규정외 수기심사"
MANUAL_RULE_ID = "SERVC_MANUAL_USER_INPUT"
MANUAL_SOURCE = "수기심사 공고: 사용자 입력 기준"
MANUAL_NOTICE = "수기심사 공고: 사용자 입력 기준으로 계산합니다."
PRICE_INPUTS = {
    "max_price_score": 60.0,
    "multiplier": 2.0,
    "pass_threshold": 95.0,
    "base_rate": 0.88,
}


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db, *args, **kwargs):
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


def _create_manual_bid(
    db,
    *,
    presmpt_prce: int = 500_000_000,
    raw_overrides: dict | None = None,
) -> BidAnnouncement:
    """낙찰방법이 관리규정외 수기심사인 일반용역 공고를 만든다. 수요기관 기준정보는 두지 않는다."""
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": MANUAL_METHOD,
        "sucsfbidLwltRate": "88.0",
        "srvceDivNm": "일반용역",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    data.update(raw_overrides or {})
    bid = BidAnnouncement(
        bid_ntce_nm="수기심사 적격심사 테스트 공고",
        bid_ntce_no="EVAL-MANUAL-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
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


def _payload(bid_id: int, qualification: dict | None = None, amount: int = 440_000_000) -> dict:
    qualification_input: dict = {"disqualification": False}
    qualification_input.update(qualification or {})
    return {
        "bid_id": bid_id,
        "selected_model": "requested-evaluation-model",
        "candidate_bid_amount": amount,
        "qualification_input": qualification_input,
    }


def _client_post(client, bid_id: int, qualification: dict | None = None, amount: int = 440_000_000):
    return client.post(ANALYZE_URL, json=_payload(bid_id, qualification, amount))


def test_manual_without_input_stays_blocked(client, isolated_db, as_user):
    """입력이 없으면 지금처럼 MANUAL_EVALUATION 으로 막고 부족한 항목을 안내한다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

    response = _client_post(client, bid.id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert "MANUAL_EVALUATION" in payload["blocked_reason"]
    assert (
        "부족한 항목: 가격배점한도(B), 평점계수(k), 통과점수, 기준비율" in payload["blocked_reason"]
    )


def test_manual_partial_input_stays_blocked_with_missing_items(client, isolated_db, as_user):
    """네 값 중 일부만 들어오면 계산하지 않고 비어 있는 항목만 안내한다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

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
    assert "MANUAL_EVALUATION" in payload["blocked_reason"]
    assert "부족한 항목: 기준비율" in payload["blocked_reason"]


def test_manual_all_price_inputs_without_quant_stays_blocked(client, isolated_db, as_user):
    """가격 파라미터 네 값만으로는 총점을 만들지 않고 정량점수 입력을 요구한다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

    payload = _client_post(client, bid.id, dict(PRICE_INPUTS)).json()

    assert payload["status"] == "blocked"
    assert "LOCAL_QUANT_REQUIRED" in payload["blocked_reason"]


def test_manual_all_inputs_computes_with_user_basis(client, isolated_db, as_user):
    """네 값과 정량점수가 모두 들어오면 사용자 입력 기준으로 계산하고 근거를 남긴다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

    response = _client_post(
        client,
        bid.id,
        {**PRICE_INPUTS, "manual_non_price_score": 40.0},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == MANUAL_RULE_ID
    assert payload["quant_source"] == "USER_INPUT_UNVERIFIED"
    # 자체 배점표를 반영하지 않았으므로 조달청 정량 배점표를 붙이지 않는다.
    assert payload["quant_score_table"] is None
    table = payload["score_table"]
    assert table is not None
    assert table["max_price_score"] == "60"
    assert table["multiplier"] == "2"
    assert table["pass_threshold"] == "95"  # noqa: S105
    assert table["source"] == MANUAL_SOURCE
    assert MANUAL_NOTICE in payload["warnings"]

    base = next(row for row in payload["scenario_results"] if row["scenario_name"] == "기준")
    # B=60, k=2, 기준비율 88%, x = 440/500 = 0.88 → P = 60 - 2*|0.88-0.88|*100 = 60
    assert base["price_score"] == pytest.approx(60.0)
    assert base["qualification_score"] == pytest.approx(40.0)
    assert base["total_score"] == pytest.approx(100.0)
    assert base["is_qualified"] is True


def test_manual_recommend_opens_same_path(client, isolated_db, as_user):
    """화면이 쓰는 /recommend 도 같은 해제 경로로 사용자 입력 기준을 적용한다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

    response = client.post(
        RECOMMEND_URL,
        json={
            "bid_id": bid.id,
            "selected_model": "requested-evaluation-model",
            "overrides": {**PRICE_INPUTS, "manual_non_price_score": 40.0},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rule_id"] == MANUAL_RULE_ID
    assert payload["status"] == "success", payload.get("blocked_reason")
    assert MANUAL_NOTICE in payload["warnings"]
    assert payload["score_table"]["source"] == MANUAL_SOURCE


def test_manual_recommend_partial_input_stays_blocked(client, isolated_db, as_user):
    """/recommend 에서도 일부만 들어오면 MANUAL_EVALUATION 차단을 유지한다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db)

    response = client.post(
        RECOMMEND_URL,
        json={
            "bid_id": bid.id,
            "overrides": {"max_price_score": 60.0, "multiplier": 2.0},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert "MANUAL_EVALUATION" in payload["blocked_reason"]


def test_other_block_codes_unchanged(client, isolated_db, as_user):
    """수기심사가 아닌 차단 코드는 해제 입력 없이 그대로 막힌다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, raw_overrides={"sucsfbidMthdNm": "알 수 없는 낙찰방법"})

    payload = _client_post(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0}).json()

    assert payload["status"] == "blocked"
    assert "RULE_NOT_FOUND" in payload["blocked_reason"]
    assert MANUAL_RULE_ID not in payload["blocked_reason"]
