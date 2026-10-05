"""공고 상세의 지방계약(LOCAL) 차단 해제 입력 UI 시험.

정본: docs/design/local_user_input_ui_20261005.md 5.2~5.4, 6.1.
 - 상세 페이지 HTML 에 기준비율(base_rate)·용역 세부유형(local_service_type)·비가격
   정량점수(manual_non_price_score) 입력 요소와 LOCAL 차단 코드 사유·안내 매핑이 렌더된다.
 - 용역 세부유형 선택은 자동 확정하지 않고 사용자가 고른 값만 페이로드에 싣는다.
 - 새 필드를 넣어 /api/v1/evaluations/analyze 를 호출하면 LOCAL 차단 4종이 해제된다.

평가 API 끝단은 mock 없이 TestClient 로 호출한다. 규칙 판별·차단 해제 경로는 실제 코드이며,
이 워크트리에 예측 모델 파일이 없어 predict_price_api 만 시험 대역으로 대체한다.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse

ANALYZE_URL = "/api/v1/evaluations/analyze"
INCHEON_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
INCHEON_SIMPLE_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"
CHUNGNAM_FISHERY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05"
CHUNGNAM_FISHERY_METHOD = "적격심사제-어장정화·정비용역"
LOCAL_USER_INPUT_RULE_ID = "SERVC_LOCAL_USER_INPUT"


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="local_input_tester",
        password=make_password("pw-test-1234"),
        email="local_input@example.com",
        nickname="지방입력 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    """예측 모델 파일이 없는 워크트리라 모델 산출물만 대역으로 대체한다."""

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
            rgn_cd="00000",
            rgn_nm=toplvl_nm,
            toplvl_instt_cd="0000000",
            toplvl_instt_nm=toplvl_nm,
            raw_json={},
        )
    )
    db.commit()


def _create_local_bid(
    db,
    *,
    method: str,
    presmpt_prce: int | None = 500_000_000,
    announced_rate: str | None = None,
    business_budget: str | None = None,
    institution_name: str = "인천광역시",
) -> BidAnnouncement:
    data: dict[str, str] = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": "1234",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    if announced_rate is not None:
        data["sucsfbidLwltRate"] = announced_rate
    if business_budget is not None:
        data["asignBdgtAmt"] = business_budget
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 입력 UI 시험 공고",
        bid_ntce_no="EVAL-LOCAL-UI-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{institution_name} 본청",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow() + timedelta(days=7),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _post(client, bid_id: int, qualification: dict | None = None, amount: int = 440_000_000):
    qualification_input: dict = {"disqualification": False}
    qualification_input.update(qualification or {})
    return client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": amount,
            "qualification_input": qualification_input,
        },
    )


def _render_bid(db) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no="EVAL-LOCAL-RENDER-001",
        bid_ntce_ord="000",
        bid_ntce_nm="상세 렌더 시험 공고",
        dminstt_nm="검증기관",
        category="Servc",
        presmpt_prce=100_000_000,
        base_amount=100_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow() + timedelta(days=7),
        collected_at=utcnow(),
        raw_data={"indstrytyLmtYn": "N"},
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# --------------------------------------------------------------------------- #
# 1. 렌더 시험: 입력 요소와 LOCAL 코드 매핑
# --------------------------------------------------------------------------- #


def test_detail_renders_local_input_elements(auth_client, isolated_db):
    """기준비율·용역 세부유형·비가격 정량점수 입력 요소가 상세 페이지에 렌더된다."""
    bid = _render_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="local-input-section"' in body
    assert 'id="input-base-rate"' in body
    assert 'id="input-local-service-type"' in body
    assert 'id="input-manual-non-price-score"' in body
    assert 'id="local-service-type-row"' in body
    assert 'id="local-base-rate-row"' in body
    assert 'id="local-manual-score-row"' in body


def test_detail_local_service_type_select_is_not_auto_selected(auth_client, isolated_db):
    """용역 세부유형 선택 기본값은 빈 값이라 사용자가 고르기 전에는 전송되지 않는다."""
    bid = _render_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text
    section = body.split('id="input-local-service-type"')[1].split("</select>")[0]

    assert '<option value="">선택 안 함</option>' in section
    assert "selected" not in section


def test_detail_payload_uses_qualification_input_field_names(auth_client, isolated_db):
    """화면이 싣는 새 필드 이름이 QualificationInput 스키마와 일치한다."""
    bid = _render_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "inputs.base_rate = baseRate" in body
    assert "inputs.manual_non_price_score = manualScore" in body
    assert "inputs.local_service_type = serviceType" in body
    assert "...buildLocalInputs()" in body


def test_detail_maps_local_blocked_reason_and_guidance(auth_client, isolated_db):
    """LOCAL 차단 4종과 MISSING_SCORE_TABLE 의 사유·안내 매핑이 렌더된다."""
    bid = _render_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text
    reason_scope = body.split("function getBlockedReasonText(code)")[1].split("function ")[0]
    guidance_scope = body.split("function getBlockedGuidanceText(code)")[1].split("function ")[0]

    for code in (
        "LOCAL_SERVICE_TYPE_UNRESOLVED",
        "LOCAL_RULE_NOT_FOUND",
        "LWLT_RATE_UNRESOLVED",
        "LOCAL_QUANT_REQUIRED",
        "MISSING_SCORE_TABLE",
    ):
        assert f"'{code}':" in reason_scope
        assert f"'{code}':" in guidance_scope


# --------------------------------------------------------------------------- #
# 2. 평가 API 끝단: LOCAL 차단 해제 (mock 없음, 규칙 판별은 실제 코드)
# --------------------------------------------------------------------------- #


def test_local_quant_required_released_by_manual_non_price_score(client, isolated_db, as_user):
    """LOCAL_QUANT_REQUIRED 는 비가격 정량점수 입력으로 해제된다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(isolated_db, method="시설분야용역 적격심사 추정가격 5억원 이상")
    bid_id = bid.id

    blocked = _post(client, bid_id).json()
    assert blocked["status"] == "blocked"
    assert "LOCAL_QUANT_REQUIRED" in blocked["blocked_reason"]

    released = _post(client, bid_id, {"manual_non_price_score": 40.0}).json()
    assert released["status"] == "success", released.get("blocked_reason")
    assert released["blocked"] is False
    assert released["rule_id"] == INCHEON_RULE_ID
    assert released["quant_source"] == "USER_INPUT_UNVERIFIED"


def test_local_service_type_unresolved_released_by_user_selection(client, isolated_db, as_user):
    """LOCAL_SERVICE_TYPE_UNRESOLVED 는 사용자가 고른 세부유형으로 해제된다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="인천광역시")
    bid = _create_local_bid(
        isolated_db, method="추정가격 2억원 미만인 용역", presmpt_prce=150_000_000
    )
    bid_id = bid.id

    blocked = _post(client, bid_id, {"manual_non_price_score": 40.0}).json()
    assert blocked["status"] == "blocked"
    assert "LOCAL_SERVICE_TYPE_UNRESOLVED" in blocked["blocked_reason"]

    released = _post(
        client,
        bid_id,
        {"manual_non_price_score": 40.0, "local_service_type": "SIMPLE_LABOR"},
    ).json()
    assert released["status"] == "success", released.get("blocked_reason")
    assert released["blocked"] is False
    assert released["rule_id"] == INCHEON_SIMPLE_RULE_ID


def test_local_rule_not_found_released_by_user_base_rate_inputs(client, isolated_db, as_user):
    """LOCAL_RULE_NOT_FOUND 는 B·k·기준비율·통과점수 입력으로 해제된다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="(없음)")
    bid = _create_local_bid(isolated_db, method="일반용역 적격심사 추정가격 5억원 미만")
    bid_id = bid.id

    blocked = _post(client, bid_id, {"manual_non_price_score": 40.0}).json()
    assert blocked["status"] == "blocked"
    assert "LOCAL_RULE_NOT_FOUND" in blocked["blocked_reason"]

    released = _post(
        client,
        bid_id,
        {
            "max_price_score": 60.0,
            "multiplier": 2.0,
            "pass_threshold": 95.0,
            "base_rate": 0.88,
            "manual_non_price_score": 40.0,
        },
    ).json()
    assert released["status"] == "success", released.get("blocked_reason")
    assert released["blocked"] is False
    assert released["rule_id"] == LOCAL_USER_INPUT_RULE_ID
    assert released["score_table"]["source"] == "사용자 입력(지자체 기준 미확보)"


def test_lwlt_rate_unresolved_released_by_estimated_price(client, isolated_db, as_user):
    """LWLT_RATE_UNRESOLVED 는 추정가격 입력으로 구간 하한율이 확정돼 해제된다."""
    as_user(10)
    _create_institution(isolated_db, code="1234", toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=None,
        business_budget="900000000",
        institution_name="충청남도",
    )
    bid_id = bid.id

    blocked = _post(client, bid_id, {"manual_non_price_score": 40.0}).json()
    assert blocked["status"] == "blocked"
    assert "LWLT_RATE_UNRESOLVED" in blocked["blocked_reason"]

    released = _post(
        client,
        bid_id,
        {"manual_non_price_score": 40.0, "estimated_price": 600_000_000},
    ).json()
    assert released["status"] == "success", released.get("blocked_reason")
    assert released["blocked"] is False
    assert released["rule_id"] == CHUNGNAM_FISHERY_ID
    assert released["lower_bound_rate"] == pytest.approx(80.495)


def test_detail_local_inputs_are_omitted_when_empty(auth_client, isolated_db):
    """빈 입력은 키 자체를 싣지 않아 LOCAL 차단이 없는 공고의 기존 페이로드가 유지된다."""
    bid = _render_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "if (Number.isFinite(baseRate)) inputs.base_rate = baseRate;" in body
    assert "if (Number.isFinite(manualScore)) inputs.manual_non_price_score = manualScore;" in body
    assert "if (serviceType) inputs.local_service_type = serviceType;" in body
    assert "Object.assign(buildQualificationInput(), buildLocalInputs())" in body
