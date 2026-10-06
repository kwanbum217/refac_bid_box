"""적격심사 정량평가 통합 분석 API 계약 테스트.

정본 규칙:
 - 판별은 src/app/services/evaluation_rules.py, 계산은 src/app/services/evaluation_scoring.py,
   모델 출처는 src/app/api/v1/predictions.py 의 predict_price_api. 본 테스트는 그것을 호출만 한다.
 - 기대값은 도메인 함수의 실제 동작으로 확정한 수치이며, 테스트 안에서 산식을 재계산하지 않는다.
 - 가격배점한도(B)·평점계수(k)·통과점수(T) 는 규칙 레지스트리에 확정값만 선언한다.
   선언되지 않은 값은 QualificationInput 으로 보완하며, 미확정 필드가 남으면 점수 계산만 차단된다.

실물 서비스(Redis·Chroma·Ollama·MySQL) 와 실제 모델 추론은 호출하지 않는다.
conftest 의 isolated_db (SQLite 인메모리) 와 dependency_overrides 를 쓰고,
predict_price_api 는 autouse fixture 로 항상 대역으로 덮은 뒤 필요한 테스트만 출처를 교체한다.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_rules import QUANT_SECTION_2

# 규칙 레지스트리가 확정한 별표 1 (시설분야용역 5억원 미만) 의 실측 낙찰하한율
ATTACH_01_LWLT_RATE = 89.995
ATTACH_01_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"

# 공고문 배점표를 사용자가 입력한 상태를 재현하는 값이다.
# 규칙 레지스트리의 값이 아니라 요청 본문으로 보내는 테스트 데이터이므로 여기서 자유롭게 고른다.
SCORE_TABLE = {"max_price_score": 60, "multiplier": 2, "pass_threshold": 95}
# 별표 2 시설분야 5억원 이상 구간의 배점한도 안에 드는 기본 정량평가 입력입니다.
# 이행실적 20(배점한도 20) + 경영상태 10(AAA~A-, 배점한도 10) + 근로조건 10 = 수행능력 계 40.
DEFAULT_QUANT_ITEMS = {"performance": 20, "labor_plan": 10}
DEFAULT_MANAGEMENT_GRADE = "AAA ~ A-"
# 브라우저가 보낸 점수를 서버가 되돌려주는지 검사하는 센티넬 값입니다.
SENTINEL_SCORE = 999

ANALYZE_URL = "/api/v1/evaluations/analyze"


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    """어떤 테스트도 실제 모델 가중치를 로드하지 않도록 예측 API 를 기본 대역으로 덮는다."""

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


@pytest.fixture
def stub_prediction(monkeypatch):
    """predict_price_api 를 원하는 출처로 덮고 호출 인자를 기록한다."""
    calls: list = []

    def _install(
        *,
        requested_model: str,
        actual_model: str | None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        def _fake_predict(payload, request, db):
            calls.append(payload)
            return PredictPriceResponse(
                status="success",
                optimal_price=440_000_000,
                prediction_rate=88.0,
                model_name="대체 모델" if fallback_used else "요청 모델",
                model_id=actual_model or "unknown",
                requested_model=requested_model,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                message="테스트용 예측 대역 응답",
            )

        monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)

    _install.calls = calls
    return _install


@pytest.fixture
def spy_scenario_builder(monkeypatch):
    """generate_pred_price_scenarios 로 실제로 넘어가는 복수예가 매개변수를 기록한다."""
    real = evaluations.generate_pred_price_scenarios
    calls: list = []

    def _spy(base_amount, *args, **kwargs):
        calls.append((base_amount, args, kwargs))
        return real(base_amount, *args, **kwargs)

    monkeypatch.setattr(evaluations, "generate_pred_price_scenarios", _spy)
    return calls


def _create_bid(
    db,
    *,
    category: str = "Servc",
    base_amount: int | None = 500_000_000,
    raw_overrides: dict | None = None,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 이상",
        "sucsfbidLwltRate": "89.995",
        "srvceDivNm": "일반용역",
        "a_value": "100000000",
        # 실측에서 적격심사 공고 전 건에 채워지는 두 필드.
        # 통상값(15, 4) 과 다른 값을 써서 하드코딩을 기계로 걸러낸다.
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    data.update(raw_overrides or {})
    data = {key: value for key, value in data.items() if value is not None}

    bid = BidAnnouncement(
        bid_ntce_nm="적격심사 API 테스트 공고",
        bid_ntce_no="EVAL-API-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=base_amount,
        presmpt_prce=base_amount,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category=category,
        raw_data=data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _analysis_payload(
    bid_id: int,
    *,
    selected_model: str = "requested-evaluation-model",
    candidate_bid_amount: int = 407_448_800,
    score_table: dict | None = None,
    qualification: dict | None = None,
) -> dict:
    qualification_input = {
        "quant_items": dict(DEFAULT_QUANT_ITEMS),
        "management_grade": DEFAULT_MANAGEMENT_GRADE,
        "reputation_items": None,
        "disqualification": False,
        # 브라우저가 계산해서 보낸 값. 서버는 이것을 신뢰하지 않는다.
        "price_score": SENTINEL_SCORE,
        "total_score": SENTINEL_SCORE,
        "is_qualified": True,
    }
    qualification_input.update(score_table or {})
    qualification_input.update(qualification or {})
    return {
        "bid_id": bid_id,
        "selected_model": selected_model,
        "candidate_bid_amount": candidate_bid_amount,
        "qualification_input": qualification_input,
    }


# --------------------------------------------------------------------------- #
# 1. 정상 분석: 규칙 판정과 점수 계산 결과는 도메인 정본에서 나온다
# --------------------------------------------------------------------------- #


def test_score_table_input_drives_server_calculation(client, isolated_db, as_user):
    """배점표가 입력되면 규칙 판정 결과와 결정론적 점수 계산을 함께 돌려준다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == ATTACH_01_RULE_ID
    # 하한율과 기준비율은 규칙 레지스트리 선언값. API 는 아무 산식 상수도 두지 않는다.
    assert payload["lower_bound_rate"] == pytest.approx(ATTACH_01_LWLT_RATE)
    assert payload["base_rate"] == pytest.approx(93.0)
    # 용역 적격심사는 A값을 적용하지 않는다. raw_data 에 A값이 있어도 두 필드는 항상 null 이다.
    assert payload["a_value_amount"] is None
    assert payload["min_bid_amount_with_a"] is None
    # 최저 투찰금액 경고는 항상 낙찰하한율 기준이다. 예정가격 5억 * 89.995% = 449,975,000.
    warnings_text = " ".join(payload["warnings"])
    assert "449,975,000" in warnings_text
    assert "459,980,000" not in warnings_text

    scenarios = {s["scenario_name"]: s for s in payload["scenario_results"]}
    assert set(scenarios) == {"하단", "기준", "상단"}
    # 기초금액 5억의 국가계약 +-2% 구간 (복수예가 시나리오는 예측이 아니라 공고 사양 구간이다)
    assert scenarios["하단"]["estimated_price"] == 490_000_000
    assert scenarios["기준"]["estimated_price"] == 500_000_000
    assert scenarios["상단"]["estimated_price"] == 510_000_000

    # x = ROUND_HALF_UP(407,448,800 / 500,000,000, 4) = 0.8149
    base = scenarios["기준"]
    assert base["bid_to_estimated_ratio"] == pytest.approx(0.8149)
    # P = 60 - 2 * |0.93 - 0.8149| * 100 = 36.98
    assert base["price_score"] == pytest.approx(36.98)
    # Q = 이행실적 20 + 경영상태 10 + 근로조건 10 = 40, 총점 = 76.98 < T 95
    assert base["qualification_score"] == pytest.approx(40.0)
    assert base["total_score"] == pytest.approx(76.98)
    assert base["pass_threshold"] == pytest.approx(95.0)
    assert base["is_qualified"] is False
    assert scenarios["하단"]["price_score"] == pytest.approx(40.30)
    assert scenarios["상단"]["price_score"] == pytest.approx(33.78)
    # P_req = 95 - 40 = 55 이므로 역산 하한 90.5% 가 공고 하한율 89.995% 를 앞선다
    assert payload["min_possible_bid_rate"] == pytest.approx(90.5)

    # 가격 보완 판정: 도메인 결과를 지수 표기 없는 문자열·정수로 옮긴다
    pc = payload["price_compensation"]
    assert pc is not None
    assert pc["score_status"] == "compensate"
    assert pc["score_status_label"] == "입찰가격으로 보완"
    assert pc["amount_status"] == "verified"
    assert pc["floor_score_basis"] == "forward_verified"
    # pass_threshold 는 배점표 통과점수 T 이지 비밀번호가 아니다 (S105 오탐)
    assert pc["pass_threshold"] == "95"  # noqa: S105
    assert pc["non_price_score"] == "40"
    assert pc["p_req"] == "55"
    assert pc["max_price_score"] == "60"
    assert pc["score_gap"] == "1"
    assert pc["score_slack"] is None
    assert pc["floor_price_score"] == "54"
    assert pc["base_rate_percent"] == "93"
    assert pc["announcement_lwlt_rate"] == "89.995"
    assert pc["calculated_rate_percent"] == "90.5"
    assert pc["effective_rate_percent"] == "90.5"
    assert pc["binding_constraint"] == "CALCULATED_SCORE_RATE"
    assert pc["score_floor_amount"] == 449_975_000
    # 하한 금액은 P_req 55 에 못 미치므로 보완 금액까지 금액을 올린다
    pc_scenarios = {s["scenario_name"]: s for s in pc["scenarios"]}
    assert list(pc_scenarios) == ["하단", "기준", "상단"]
    assert [pc_scenarios[name]["complement_bid_amount"] for name in ("하단", "기준", "상단")] == [
        443_425_500,
        452_475_000,
        461_524_500,
    ]
    for row in pc_scenarios.values():
        assert row["row_status"] == "compensate"
        assert row["verified_price_ratio"] == "0.9050"
        assert row["bid_rate_percent"] == "90.495"
        assert row["verified_price_score"] == "55"
        assert row["ratio_steps_raised"] == 0
        assert row["meets_p_req"] is True


def test_announcement_lower_rate_binds_when_score_is_easy(client, isolated_db, as_user):
    """역산 투찰률이 공고 하한율보다 낮으면 공고 하한율이 실질 하한이 된다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            candidate_bid_amount=449_000_000,
            score_table=SCORE_TABLE,
            qualification={
                "quant_items": {"performance": 20, "labor_plan": 10},
                "reputation_items": {
                    "sme_support": 1.5,
                    "disabled_company": 1.5,
                    "woman_company": 0.75,
                    "employment_type_a": 0.5,
                },
            },
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    scenarios = {s["scenario_name"]: s for s in payload["scenario_results"]}
    # Q = 20(실적) + 10(경영 AAA~A-) + 10(근로조건) + 4.25(신인도 상한) = 44.25
    assert scenarios["기준"]["qualification_score"] == pytest.approx(44.25)
    # x = 0.8980 -> P = 60 - 2*3.20 = 53.60 -> 총점 97.85 >= 95
    assert scenarios["기준"]["bid_to_estimated_ratio"] == pytest.approx(0.8980)
    assert scenarios["기준"]["price_score"] == pytest.approx(53.60)
    assert scenarios["기준"]["total_score"] == pytest.approx(97.85)
    assert scenarios["기준"]["is_qualified"] is True
    assert scenarios["하단"]["is_qualified"] is True
    # 상단은 x = 0.8804 -> P = 50.08, Q = 44.25 -> 총점 94.33 < 95 이다
    assert scenarios["상단"]["is_qualified"] is False
    # P_req = 50.75 -> 역산 88.375% < 공고 하한율 89.995% 이므로 하한율이 구속한다
    assert payload["min_possible_bid_rate"] == pytest.approx(ATTACH_01_LWLT_RATE)


def test_price_compensation_reports_impossible_without_duplicating_warning(
    client, isolated_db, as_user
):
    """P_req > B 이면 보완 불가로 판정하고, 도메인 경고를 응답에 두 번 싣지 않는다.

    같은 문장을 도메인 resolve_price_compensation 과 invert_lowest_bid_rate 가 모두
    내므로, 이어 붙이기 전에 중복을 제거해야 한다.
    """
    as_user(10)
    bid = _create_bid(isolated_db)
    # Q = 30(이행실적 20 + 경영상태 10) 이고 T 를 100 으로 올리면 P_req = 70 > B 60 이다.
    table = {**SCORE_TABLE, "pass_threshold": 100}

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id, score_table=table, qualification={"quant_items": {"performance": 20}}
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    pc = payload["price_compensation"]
    assert pc is not None
    assert pc["score_status"] == "impossible"
    assert pc["score_status_label"] == "보완 불가"
    assert pc["p_req"] == "70"
    assert pc["score_gap"] == "10"
    assert pc["score_slack"] is None
    assert pc["guidance"] == (
        "가격점수 만점으로도 통과점수에 닿지 않습니다. 대수 투찰률은 투찰 권고가 아닙니다."
    )
    for row in pc["scenarios"]:
        assert row["row_status"] == "impossible"
        assert row["complement_bid_amount"] is None
        assert row["meets_p_req"] is False
    # 도메인 계약: P_req > B 사유 경고는 응답 전체에 정확히 한 번만 실린다
    capacity_warning = (
        "수행능력 점수(30.0점) 부족으로 가격점수 만점(60.0점)을 받아도 "
        "통과점수(100.0점)에 도달할 수 없습니다."
    )
    assert payload["warnings"].count(capacity_warning) == 1


def test_registry_confirmed_k_and_t_fill_missing_user_fields(client, isolated_db, as_user):
    """사용자가 B만 입력해도 선언된 k=5·T=85를 사용해 점수를 계산한다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={"sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만"},
    )

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(bid.id, score_table={"max_price_score": 60}),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["multiplier"] == "5"
    assert payload["score_table"]["pass_threshold"] == "85"  # noqa: S105 - 배점표 통과점수 T
    assert payload["score_table"]["missing_fields"] == []


def test_non_positive_score_table_value_is_rejected(client, isolated_db, as_user):
    """배점표 값은 0 을 허용하지 않는다. 0 점 기준으로 오답을 계산하지 않는다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    table = {**SCORE_TABLE, "multiplier": 0}

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=table))

    assert response.status_code == 422
    assert "multiplier" in response.text


# --------------------------------------------------------------------------- #
# 2. 배점표 결측: 점수만 차단하고 계산 가능한 것은 정식 필드로 준다
# --------------------------------------------------------------------------- #


def test_resolved_score_table_keeps_scenarios_and_floor_amounts(
    client, isolated_db, as_user, spy_scenario_builder
):
    """조건부 배점표가 해소되면 시나리오 점수와 하한율을 함께 전달한다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={"sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만"},
    )

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["max_price_score"] == "70"
    # 규칙 판별 자체는 성공했으므로 별표와 하한율은 전달된다
    assert payload["rule_id"] == ATTACH_01_RULE_ID
    assert payload["lower_bound_rate"] == pytest.approx(ATTACH_01_LWLT_RATE)

    # 시나리오는 warnings 문자열이 아니라 정식 필드다.
    scenarios = payload["scenario_results"]
    assert [s["scenario_name"] for s in scenarios] == ["하단", "기준", "상단"]
    assert [s["estimated_price"] for s in scenarios] == [490_000_000, 500_000_000, 510_000_000]
    assert [s["bid_to_estimated_ratio"] for s in scenarios] == pytest.approx(
        [0.8315, 0.8149, 0.7989]
    )
    for scenario in scenarios:
        assert scenario["price_score"] is not None
        assert scenario["qualification_score"] is not None
        assert scenario["total_score"] is not None
        assert scenario["pass_threshold"] == 85
        assert scenario["is_qualified"] is not None
    assert payload["min_possible_bid_rate"] is not None
    assert payload["base_rate"] is not None
    assert payload["price_compensation"] is not None
    # 낙찰하한율 기준 최저 투찰금액은 차단되지 않는다. 용역은 A값을 적용하지 않는다.
    assert payload["a_value_amount"] is None
    assert payload["min_bid_amount_with_a"] is None
    # 예정가격 5억 * 89.995% = 449,975,000. A값을 반영한 459,980,000 은 나오지 않는다.
    warnings_text = " ".join(payload["warnings"])
    assert "449,975,000" in warnings_text
    assert "459,980,000" not in warnings_text
    assert "A값 반영" not in warnings_text
    assert payload["actual_model"] is not None
    assert payload["fallback_used"] is False
    # 복수예가 매개변수는 공고 필드에서 온다 (15/4 하드코딩이 아님)
    assert spy_scenario_builder[0][2]["tot_prdprc_num"] == 12
    assert spy_scenario_builder[0][2]["drwt_prdprc_num"] == 3


# --------------------------------------------------------------------------- #
# 2b. 규칙 선언 배점표(B·k·T): 선언값 자동 적용과 사용자 덮어쓰기
# --------------------------------------------------------------------------- #

# 학술연구용역 고시금액 미만(별표1). 규칙 레지스트리가 B=70·k=4·T=85 를 선언한 규칙이다.
ACADEMIC_METHOD = "학술연구용역 적격심사 추정가격 고시금액 미만"
ACADEMIC_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_06"
ACADEMIC_LWLT_RATE = "86.245"


def _academic_bid(db):
    return _create_bid(
        db,
        raw_overrides={
            "sucsfbidMthdNm": ACADEMIC_METHOD,
            "sucsfbidLwltRate": ACADEMIC_LWLT_RATE,
        },
    )


def test_declared_score_table_computes_without_user_input(client, isolated_db, as_user):
    """규칙이 B·k·T 를 선언한 별표는 사용자 입력 없이도 점수를 계산한다."""
    as_user(10)
    bid = _academic_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(bid.id, qualification={"quant_items": {"performance": 10}}),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == ACADEMIC_RULE_ID
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["multiplier"] == "4"
    assert payload["score_table"]["pass_threshold"] == "85"  # noqa: S105 - 배점표 T
    assert payload["score_table"]["missing_fields"] == []
    assert payload["score_table"]["override_fields"] == []
    assert payload["score_table"]["source"]


def test_user_input_overrides_declared_score_table(client, isolated_db, as_user):
    """사용자 직접 입력은 규칙 선언값을 덮어쓰고 그 사실이 표시된다."""
    as_user(10)
    bid = _academic_bid(isolated_db)
    override = {"max_price_score": 60, "multiplier": 5, "pass_threshold": 88}

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id, score_table=override, qualification={"quant_items": {"performance": 10}}
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["override_fields"] == [
        "max_price_score",
        "multiplier",
        "pass_threshold",
    ]
    assert payload["score_table"]["missing_fields"] == []
    # 계산에는 덮어쓴 값이 쓰인다.
    assert payload["price_compensation"]["max_price_score"] == "60"
    assert payload["price_compensation"]["pass_threshold"] == "88"  # noqa: S105 - 배점표 T
    assert any("덮어썼습니다" in w for w in payload["warnings"])


def test_user_input_equal_to_declared_value_is_not_an_override(client, isolated_db, as_user):
    """선언값과 같은 값을 다시 보낸 것은 덮어쓰기로 보지 않는다."""
    as_user(10)
    bid = _academic_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table={"max_price_score": 70, "multiplier": 4, "pass_threshold": 85},
            qualification={"quant_items": {"performance": 10}},
        ),
    )

    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["override_fields"] == []


def test_method_name_resolves_conditional_b_without_user_input(client, isolated_db, as_user):
    """시설 규칙의 조건부 B는 공고 낙찰방법명 구간으로 선택한다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={"sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만"},
    )  # 시설 ATTACH_01: 5억원 가격 구간에 따라 B가 달라짐

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["multiplier"] == "5"
    assert payload["score_table"]["pass_threshold"] == "85"  # noqa: S105 - 배점표 통과점수 T
    assert payload["score_table"]["missing_fields"] == []
    assert payload["score_table"]["max_price_score_basis"].startswith("낙찰방법명")


def test_pre_20230501_facility_uses_method_name_for_conditional_b(client, isolated_db, as_user):
    """제2023-53호 시설분야도 원문 k·T 와 공고명 구간 B 를 사용한다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={
            "bidNtceDt": "20230601",
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
        },
    )
    isolated_db.commit()

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["rule_id"] == "SERVC_QUAL_PRE_20230501_ATTACH_01"
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["multiplier"] == "5"
    assert payload["score_table"]["pass_threshold"] == "85"  # noqa: S105 - 배점표 통과점수 T
    assert payload["score_table"]["missing_fields"] == []
    assert payload["score_table"]["max_price_score_basis"].startswith("낙찰방법명")


def test_method_name_resolves_conditional_b_and_fixed_k(client, isolated_db, as_user):
    """낙찰방법명 5억원 미만 표기와 단일 k·T 를 선택값으로 사용한다."""
    as_user(10)
    # 별표1 학술연구 고시금액 이상: k=2·T=85 는 단일값이고 B 는 공고명으로 선택합니다.
    bid = _create_bid(
        isolated_db,
        raw_overrides={
            "sucsfbidMthdNm": "학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상",
            "sucsfbidLwltRate": "82.495",
        },
    )

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(bid.id, qualification={"quant_items": {"performance": 10}}),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["multiplier"] == "2"
    assert payload["score_table"]["pass_threshold"] == "85"  # noqa: S105 - 배점표 T
    assert payload["score_table"]["missing_fields"] == []
    assert payload["score_table"]["max_price_score_basis"].startswith("낙찰방법명")


def test_floor_amount_without_a_value_is_still_reported(client, isolated_db, as_user):
    """A값이 없는 공고도 낙찰하한율 기준 최저 투찰금액은 제공된다."""
    as_user(10)
    bid = _create_bid(isolated_db, raw_overrides={"a_value": None})

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["a_value_amount"] is None
    # 예정가격 5억 * 89.995% = 449,975,000
    assert "449,975,000" in " ".join(payload["warnings"])


def test_scenario_counts_fall_back_to_domain_contract_when_absent(
    client, isolated_db, as_user, spy_scenario_builder
):
    """공고에 복수예가 필드가 없으면 API 는 수치를 채우지 않고 도메인 계약에 맡긴다."""
    as_user(10)
    bid = _create_bid(isolated_db, raw_overrides={"totPrdprcNum": None, "drwtPrdprcNum": None})

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    kwargs = spy_scenario_builder[0][2]
    assert "tot_prdprc_num" not in kwargs
    assert "drwt_prdprc_num" not in kwargs


def test_prediction_price_api_is_not_called_without_score_table(
    client, isolated_db, as_user, monkeypatch
):
    """점수 계산을 차단한 경로에서 예측 모델을 태우지 않는다."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("배점표가 없는 분석에서 예측 모델이 호출되면 안 된다")

    monkeypatch.setattr(evaluations, "predict_price_api", _forbidden)
    as_user(10)
    bid = _create_bid(isolated_db)
    bid.presmpt_prce = None
    isolated_db.commit()

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text


def test_quant_band_unresolved_without_estimated_price_or_method_band(client, isolated_db, as_user):
    """추정가격과 방법명 5억 표기가 모두 없으면 기초금액이 있어도 구간을 고르지 않는다.

    소프트웨어용역 고시금액 미만 규칙은 방법명에 5억 표기가 없지만 배점표 구간이 둘이다.
    """
    as_user(10)
    bid = _create_bid(
        isolated_db,
        base_amount=600_000_000,
        raw_overrides={
            "sucsfbidMthdNm": "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만",
            "asignBdgtAmt": "600000000",
        },
    )
    bid.presmpt_prce = None
    isolated_db.commit()

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is True
    assert "QUANT_BAND_UNRESOLVED" in payload["blocked_reason"]
    assert "추정가격" in payload["blocked_reason"]


# 소프트웨어용역(중소기업자간 경쟁제품 비대상) 고시금액 미만(별표3). 낙찰방법명에 5억원
# 구간 표기가 없어 배점표 구간이 둘이고, 추정가격만으로 구간을 고른다.
SW_NON_SME_METHOD = "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만"
SW_NON_SME_LWLT_RATE = "86.245"


def _sw_non_sme_bid(db, *, business_budget: str = "600000000"):
    """추정가격이 없는 SW 비대상 공고. 예정가격 기준액은 사업예산으로만 채운다."""
    return _create_bid(
        db,
        raw_overrides={
            "sucsfbidMthdNm": SW_NON_SME_METHOD,
            "sucsfbidLwltRate": SW_NON_SME_LWLT_RATE,
            "asignBdgtAmt": business_budget,
        },
    )


@pytest.mark.parametrize(
    ("estimated_price", "expected_band", "expected_b"),
    [(600_000_000, "over_500m", "60"), (400_000_000, "under_500m", "70")],
)
def test_user_estimated_price_resolves_quant_band_and_score_params(
    client, isolated_db, as_user, estimated_price, expected_band, expected_b
):
    """공고 추정가격이 없으면 사용자 입력이 정량평가 구간과 조건부 B에 함께 쓰인다."""
    as_user(10)
    bid = _sw_non_sme_bid(isolated_db)
    bid.presmpt_prce = None
    isolated_db.commit()

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            qualification={"estimated_price": estimated_price, "quant_items": {}},
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False, payload.get("blocked_reason")
    assert payload["quant_score_table"]["active_band_key"] == expected_band
    assert "사용자 입력 추정가격" in payload["quant_score_table"]["band_note"]
    assert payload["score_table"]["max_price_score"] == expected_b
    assert payload["score_table"]["max_price_score_basis"].startswith("사용자 입력 추정가격")


def test_announcement_estimated_price_wins_over_user_input(client, isolated_db, as_user):
    """공고 추정가격이 있으면 반대 구간 사용자 입력은 무시하고 안내한다."""
    as_user(10)
    bid = _sw_non_sme_bid(isolated_db)
    bid.presmpt_prce = 600_000_000
    isolated_db.commit()

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            qualification={"estimated_price": 400_000_000, "quant_items": {}},
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False, payload.get("blocked_reason")
    assert payload["quant_score_table"]["active_band_key"] == "over_500m"
    assert any(
        "사용자 입력 추정가격은 구간 판정에 사용하지 않았습니다" in warning
        for warning in payload["warnings"]
    )
    assert payload["score_table"]["max_price_score"] == "60"
    assert not payload["score_table"]["max_price_score_basis"].startswith("사용자 입력 추정가격")


def test_method_name_band_precedes_user_estimated_price(client, isolated_db, as_user):
    """낙찰방법명에 5억원 미만이 있으면 사용자 입력보다 우선한다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
            "asignBdgtAmt": "600000000",
        },
    )
    bid.presmpt_prce = None
    isolated_db.commit()

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            qualification={"estimated_price": 600_000_000, "quant_items": {}},
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is False, payload.get("blocked_reason")
    assert payload["quant_score_table"]["active_band_key"] == "under_500m"
    assert payload["score_table"]["max_price_score"] == "70"
    assert payload["score_table"]["max_price_score_basis"].startswith("낙찰방법명")


def test_bid_without_pred_price_is_blocked(client, isolated_db, as_user):
    """기초금액과 예정가격이 모두 없는 공고는 분모가 없어 계산하지 않는다."""
    as_user(10)
    bid = _create_bid(isolated_db, base_amount=None)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is True
    assert "PRED_PRICE_UNAVAILABLE" in payload["blocked_reason"]


# --------------------------------------------------------------------------- #
# 3. 차단 코드 4종: 500 이 아니라 정상 응답 상태로 전달된다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("category", "raw_overrides", "block_code"),
    [
        ("Thng", {}, "NOT_SERVC"),
        ("Servc", {"prearngPrceDcsnMthdNm": "비예가"}, "NON_PRED_PRICE"),
        (
            "Servc",
            {"sucsfbidMthdNm": "적격심사제-관리규정외 수기심사(총점입력)"},
            "MANUAL_EVALUATION",
        ),
        ("Servc", {"sucsfbidMthdNm": "적격심사제-등록되지 않은 기준"}, "RULE_NOT_FOUND"),
        ("Servc", {"sucsfbidMthdNm": None}, "RULE_NOT_FOUND"),
    ],
)
def test_analyze_returns_blocked_result_with_reason_code(
    client, isolated_db, as_user, category, raw_overrides, block_code
):
    """지원 범위 밖 조건은 500 이 아니라 코드가 있는 정상 차단 응답으로 전달한다."""
    as_user(10)
    bid = _create_bid(isolated_db, category=category, raw_overrides=raw_overrides)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["contract_regime"]["label"] == "계약 법령 미상"
    assert payload["contract_regime"]["range_rate_label"] == "±2% (기본값, 법령 미상)"
    assert payload["blocked"] is True
    assert f"{block_code}:" in payload["blocked_reason"]
    assert payload["scenario_results"] == []
    # 규칙을 매칭하지 못하면 별표 정보도 없다
    assert payload["lower_bound_rate"] is None
    # 규칙 차단 응답에는 가격 보완 판정이 없다
    assert payload["price_compensation"] is None


def test_blocked_analysis_still_saves_snapshot(client, isolated_db, as_user):
    """차단 응답도 이력 보존을 위해 스냅샷으로 남는다."""
    as_user(10)
    bid = _create_bid(isolated_db, category="Thng")
    # conftest 의 get_db 대역이 요청마다 session.close() 를 하여 ORM 객체가 detach 된다.
    # 그래서 request 이후에 쓸 식별자는 미리 확보해 둔다.
    bid_id = bid.id

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid_id))
    assert response.status_code == 200

    snapshots = client.get("/api/v1/evaluations/snapshots")
    assert snapshots.status_code == 200
    snapshot_rows = snapshots.json()
    assert len(snapshot_rows) == 1
    assert snapshot_rows[0]["rule_id"] == "BLOCKED"
    assert snapshot_rows[0]["bid_id"] == bid_id
    assert "NOT_SERVC" in snapshot_rows[0]["result_json"]["blocked_reason"]


def test_snapshot_save_failure_does_not_block_response(client, isolated_db, as_user, monkeypatch):
    """저장 실패가 분석 응답을 막지 않는다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    bid.presmpt_prce = None
    isolated_db.commit()

    def _boom(*args, **kwargs):
        raise RuntimeError("스냅샷 저장 불가")

    monkeypatch.setattr(isolated_db, "commit", _boom)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    assert response.json()["blocked"] is True


def test_analyze_returns_404_for_unknown_bid(client, isolated_db, as_user):
    as_user(10)

    response = client.post(ANALYZE_URL, json=_analysis_payload(999_999))

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# 4. 서버 계산 원칙: 브라우저가 보낸 점수는 신뢰하지 않는다
# --------------------------------------------------------------------------- #


def _echoed_sentinel_paths(node, path="$"):
    """응답 어디에도 클라이언트가 보낸 센티넬 값이 되돌아오지 않았는지 확인합니다.

    원문 문자열에서 "999" 를 찾으면 타임스탬프나 금액이나 ID 에 우연히 들어간
    999 까지 잡아 무작위로 실패합니다. 검사 대상은 문자열 부분일치가 아니라
    값 자체이므로 파싱한 JSON 을 순회하며 값이 정확히 999 인 자리만 모읍니다.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_echoed_sentinel_paths(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_echoed_sentinel_paths(value, f"{path}[{index}]"))
    elif isinstance(node, bool):
        pass
    elif (isinstance(node, (int, float)) and node == SENTINEL_SCORE) or (
        isinstance(node, str) and node.strip() == str(SENTINEL_SCORE)
    ):
        found.append(path)
    return found


def test_browser_supplied_scores_are_never_echoed(client, isolated_db, as_user):
    """클라이언트가 보낸 999 점 계열 값은 응답의 어떤 자리에도 나타나지 않는다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    echoed = _echoed_sentinel_paths(response.json())
    assert echoed == [], f"클라이언트가 보낸 {SENTINEL_SCORE} 가 응답에 되돌아왔습니다: {echoed}"


def test_server_scores_are_not_the_requested_ones(client, isolated_db, as_user):
    """배점표가 있어도 가격점수와 총점은 서버 계산값이지 요청값이 아니다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    echoed = _echoed_sentinel_paths(payload)
    assert echoed == [], f"클라이언트가 보낸 {SENTINEL_SCORE} 가 응답에 되돌아왔습니다: {echoed}"
    base = {s["scenario_name"]: s for s in payload["scenario_results"]}["기준"]
    assert base["price_score"] == pytest.approx(36.98)
    assert base["total_score"] == pytest.approx(76.98)


def test_disqualification_status_reports_input_state(client, isolated_db, as_user):
    """결격 입력을 생략하면 not_checked, 명시 True/False 는 disqualified/clear 로 표시한다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    bid_id = bid.id

    omitted_payload = _analysis_payload(bid_id, score_table=SCORE_TABLE)
    del omitted_payload["qualification_input"]["disqualification"]
    omitted = client.post(ANALYZE_URL, json=omitted_payload)
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["disqualification_status"] == "not_checked"

    explicit_false = client.post(
        ANALYZE_URL, json=_analysis_payload(bid_id, score_table=SCORE_TABLE)
    )
    assert explicit_false.json()["disqualification_status"] == "clear"

    explicit_true = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid_id, score_table=SCORE_TABLE, qualification={"disqualification": True}
        ),
    )
    assert explicit_true.json()["disqualification_status"] == "disqualified"


def test_disqualification_makes_the_announcement_unqualified(client, isolated_db, as_user):
    """결격사유가 있으면 총점이 높아도 적격이 아니다 (판정 3 조건은 도메인 정본)."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            candidate_bid_amount=449_000_000,
            score_table=SCORE_TABLE,
            qualification={
                "quant_items": {"performance": 20, "labor_plan": 10},
                "reputation_items": {
                    "sme_support": 1.5,
                    "disabled_company": 1.5,
                    "woman_company": 0.75,
                    "employment_type_a": 0.5,
                },
                "disqualification": True,
            },
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    base = {s["scenario_name"]: s for s in payload["scenario_results"]}["기준"]
    # Q = 44.25, P = 53.60 -> 총점 97.85 이지만 결격사유가 있어 적격이 아니다
    assert base["total_score"] == pytest.approx(97.85)
    assert base["is_qualified"] is False
    assert any("결격" in w for w in base["warnings"])


# --------------------------------------------------------------------------- #
# 5. 모델 출처: predict_price_api 의 산출물을 그대로 전달한다
# --------------------------------------------------------------------------- #


def test_model_provenance_is_passed_through_from_prediction_api(
    client, isolated_db, as_user, stub_prediction
):
    """요청 모델과 실제 모델이 다르면 대체 사실이 응답에 그대로 드러난다."""
    stub_prediction(
        requested_model="requested-evaluation-model",
        actual_model="fallback-model-v3",
        fallback_used=True,
        fallback_reason="requested-evaluation-model 추론 실패",
    )
    as_user(10)
    bid = _create_bid(isolated_db)
    bid_id = bid.id

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid_id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_model"] == "requested-evaluation-model"
    assert payload["actual_model"] == "fallback-model-v3"
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "requested-evaluation-model 추론 실패"
    # 위임이 실제로 일어났는지: 예측 API 가 받은 요청 파라미터로 확인한다
    called = stub_prediction.calls[-1]
    assert called.bid_id == bid_id
    assert called.selected_model == "requested-evaluation-model"
    assert called.user_price == "407448800"


def test_model_provenance_keeps_identity_when_no_fallback(
    client, isolated_db, as_user, stub_prediction
):
    """대체가 없으면 대체 사실을 거짓으로 만들지 않는다."""
    stub_prediction(requested_model="requested-evaluation-model", actual_model="answered-model-v9")
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id, selected_model="requested-evaluation-model", score_table=SCORE_TABLE
        ),
    )

    payload = response.json()
    assert payload["requested_model"] == "requested-evaluation-model"
    assert payload["actual_model"] == "answered-model-v9"
    assert payload["fallback_used"] is False
    assert payload["fallback_reason"] is None


def test_model_provenance_reports_unavailable_prediction(client, isolated_db, as_user, monkeypatch):
    """예측 모델을 쓸 수 없을 때 대체 사실을 숨기지 않는다."""

    def _unavailable(*args, **kwargs):
        raise HTTPException(
            status_code=503, detail="예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다."
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _unavailable)
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["actual_model"] is None
    assert payload["fallback_used"] is True
    assert "503" in payload["fallback_reason"]
    assert any("모델 출처" in w for w in payload["warnings"])


# --------------------------------------------------------------------------- #
# 6. 소유권 격리: 조회·수정·삭제·목록 네 경로 모두
# --------------------------------------------------------------------------- #


def _create_profile(client, name: str) -> int:
    response = client.post(
        "/api/v1/evaluations/profiles",
        json={"name": name, "input_json": {"performance_score": 10}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_snapshot(client, bid_id: int, rule_id: str) -> int:
    response = client.post(
        "/api/v1/evaluations/snapshots",
        json={
            "bid_id": bid_id,
            "rule_id": rule_id,
            "model_id": "MODEL-1",
            "model_version": "1.0",
            "input_json": {"source": rule_id},
            "result_json": {"score": 1},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_profile_is_isolated_on_read_update_delete_and_list(client, isolated_db, as_user):
    """타인 프로필은 조회·수정·삭제가 404 로 차단되고 목록에 노출되지 않는다."""
    as_user(2)
    other_id = _create_profile(client, "남의 프로필")

    as_user(1)
    own_id = _create_profile(client, "내 프로필")

    assert client.get(f"/api/v1/evaluations/profiles/{other_id}").status_code == 404
    assert (
        client.put(
            f"/api/v1/evaluations/profiles/{other_id}", json={"name": "탈취 시도"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/evaluations/profiles/{other_id}").status_code == 404
    # 목록은 본인 자원만 담는다 (빈 목록이 아니라 필터가 걸려 있다는 것을 증명한다)
    assert [p["id"] for p in client.get("/api/v1/evaluations/profiles").json()] == [own_id]

    # 차단되었으므로 남의 자원은 그대로이고, 내 자원은 정상 수정·삭제가 된다
    as_user(2)
    other = client.get(f"/api/v1/evaluations/profiles/{other_id}")
    assert other.status_code == 200
    assert other.json()["name"] == "남의 프로필"
    assert [p["id"] for p in client.get("/api/v1/evaluations/profiles").json()] == [other_id]

    as_user(1)
    assert client.get(f"/api/v1/evaluations/profiles/{own_id}").status_code == 200
    assert (
        client.put(
            f"/api/v1/evaluations/profiles/{own_id}", json={"name": "내 새 이름"}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/evaluations/profiles/{own_id}").status_code == 204
    assert client.get("/api/v1/evaluations/profiles").json() == []


def test_snapshot_is_isolated_on_read_delete_and_list(client, isolated_db, as_user):
    """타인 스냅샷은 조회·삭제가 404 로 차단되고 목록과 bid_id 필터에 노출되지 않는다."""
    bid = _create_bid(isolated_db)
    bid_id = bid.id
    as_user(2)
    other_id = _create_snapshot(client, bid_id, "RULE-2")

    as_user(1)
    own_id = _create_snapshot(client, bid_id, "RULE-1")

    assert client.get(f"/api/v1/evaluations/snapshots/{other_id}").status_code == 404
    assert client.delete(f"/api/v1/evaluations/snapshots/{other_id}").status_code == 404
    assert [s["id"] for s in client.get("/api/v1/evaluations/snapshots").json()] == [own_id]
    # 같은 공고의 두 스냅샷 중 목록과 bid_id 필터 모두 본인 자원만 담는다
    assert [
        s["id"] for s in client.get(f"/api/v1/evaluations/snapshots?bid_id={bid_id}").json()
    ] == [own_id]

    # 차단되었으므로 남의 스냅샷은 그대로 살아있다
    as_user(2)
    assert client.get(f"/api/v1/evaluations/snapshots/{other_id}").status_code == 200

    # 내 스냅샷 삭제는 정상 동작하고 남의 스냅샷은 남는다
    as_user(1)
    assert client.delete(f"/api/v1/evaluations/snapshots/{own_id}").status_code == 204
    assert client.get("/api/v1/evaluations/snapshots").json() == []
    as_user(2)
    assert client.get(f"/api/v1/evaluations/snapshots/{other_id}").status_code == 200


def test_analyze_snapshot_belongs_to_requesting_user(client, isolated_db, as_user):
    """분석이 남긴 스냅샷도 요청자 소유로만 조회된다."""
    bid = _create_bid(isolated_db)
    bid_id = bid.id
    as_user(7)
    assert client.post(ANALYZE_URL, json=_analysis_payload(bid_id)).status_code == 200
    rows = client.get("/api/v1/evaluations/snapshots").json()
    assert [row["user_id"] for row in rows] == [7]

    as_user(8)
    assert client.get("/api/v1/evaluations/snapshots").json() == []
    assert client.get(f"/api/v1/evaluations/snapshots/{rows[0]['id']}").status_code == 404


class _QueryRecorder:
    """실행된 SQL 을 수집하는 컨텍스트 매니저."""

    def __init__(self, session):
        self.bind = session.get_bind()
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.bind, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self.bind, "before_cursor_execute", self._record)
        return False

    @property
    def select_statements(self) -> list[str]:
        return [stmt for stmt in self.statements if stmt.strip().upper().startswith("SELECT")]


def test_list_evaluation_snapshots_eager_loads_evidence_items_with_fixed_queries(
    client, isolated_db, as_user
):
    """스냅샷 목록 조회 시 증빙 항목을 일괄 로딩하여 건수와 무관하게 고정된 질의 수(2회)로 조회된다."""
    bid = _create_bid(isolated_db)
    bid_id = bid.id
    user_id = 99
    as_user(user_id)

    # 1. 스냅샷 1건 생성 (증빙 2건 포함)
    evidence_1 = [
        {"item_code": "performance", "issuer": "기관A", "reference_no": "REF-001", "note": "실적"},
        {"item_code": "management", "issuer": "기관B", "reference_no": "REF-002", "note": "경영"},
    ]
    resp = client.post(
        "/api/v1/evaluations/snapshots",
        json={
            "bid_id": bid_id,
            "rule_id": "RULE-SNAP-1",
            "model_id": "MODEL-1",
            "model_version": "1.0",
            "input_json": {"step": 1},
            "result_json": {"score": 10},
            "evidence_items": evidence_1,
        },
    )
    assert resp.status_code == 201

    # 스냅샷 1건일 때 목록 조회 질의 수 측정
    with _QueryRecorder(isolated_db) as recorder_1:
        res_1 = client.get("/api/v1/evaluations/snapshots")
    assert res_1.status_code == 200
    rows_1 = res_1.json()
    assert len(rows_1) == 1
    assert len(rows_1[0]["evidence_items"]) == 2
    select_count_1 = len(recorder_1.select_statements)
    # 스냅샷 목록 1회 + 증빙 일괄 IN 1회 = 총 2회 SELECT
    assert select_count_1 == 2, (
        f"기대 2회이나 실제 {select_count_1}회: {recorder_1.select_statements}"
    )

    # 2. 스냅샷 4건 추가 생성 (총 5건, 각 증빙 2건씩 총 10건)
    for idx in range(2, 6):
        evidence_items = [
            {
                "item_code": f"code_{idx}_1",
                "issuer": f"기관_{idx}_1",
                "reference_no": f"REF-{idx}-1",
            },
            {
                "item_code": f"code_{idx}_2",
                "issuer": f"기관_{idx}_2",
                "reference_no": f"REF-{idx}-2",
            },
        ]
        resp = client.post(
            "/api/v1/evaluations/snapshots",
            json={
                "bid_id": bid_id,
                "rule_id": f"RULE-SNAP-{idx}",
                "model_id": "MODEL-1",
                "model_version": "1.0",
                "input_json": {"step": idx},
                "result_json": {"score": idx * 10},
                "evidence_items": evidence_items,
            },
        )
        assert resp.status_code == 201

    # 스냅샷 5건일 때 목록 조회 질의 수 측정
    with _QueryRecorder(isolated_db) as recorder_5:
        res_5 = client.get("/api/v1/evaluations/snapshots")
    assert res_5.status_code == 200
    rows_5 = res_5.json()
    assert len(rows_5) == 5

    # 1+N 지연 로딩이었다면 1 + 5 = 6회 발생했을 것이나, selectinload 일괄 적재로 질의 수가 증가하지 않음
    select_count_5 = len(recorder_5.select_statements)
    assert select_count_5 == select_count_1 == 2, (
        f"스냅샷이 1건에서 5건으로 증가했으나 SELECT 질의 수는 2회로 고정되어야 함. "
        f"실제 1건 시: {select_count_1}회, 5건 시: {select_count_5}회"
    )

    # 데이터 및 순서 정합성 검증: created_at 내림차순 및 각 스냅샷의 증빙 메타데이터 온전성
    for row in rows_5:
        assert len(row["evidence_items"]) == 2
        for item in row["evidence_items"]:
            assert item["item_code"]
            assert item["issuer"]
            assert item["reference_no"]

    # created_at 내림차순 정렬 유지 확인
    created_ats = [r["created_at"] for r in rows_5]
    assert created_ats == sorted(created_ats, reverse=True)


# --------------------------------------------------------------------------- #
# 7. 금지 표현과 산식 상수 회귀 방어
# --------------------------------------------------------------------------- #


def test_api_layer_declares_no_scoring_constants():
    """API 파일에 반려된 산식 상수와 자체 판별 함수가 되살아나면 실패한다."""
    source = Path(evaluations.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'Decimal("0.88")',
        'Decimal("70")',
        'Decimal("95")',
        'Decimal("85")',
        "tot_prdprc_num=15",
        "drwt_prdprc_num=4",
        "evaluation_default",
        "_determine_pass_threshold",
        "_determine_scoring_params",
    ):
        assert forbidden not in source, forbidden


def test_no_forbidden_marketing_phrases():
    """금지된 마케팅 표현(낙찰 + 확률/보장, 예정가격 + 예측) 이 코드와 테스트에 없다.

    금어를 리터럴로 적으면 이 파일 자체가 위반이 되므로 두 조각으로 나눠 붙인다.
    """
    texts = [
        Path(evaluations.__file__).read_text(encoding="utf-8"),
        Path(__file__).read_text(encoding="utf-8"),
    ]
    forbidden = ("낙찰" + "확률", "낙찰" + "보장", "예정가격 " + "예측")
    for phrase in forbidden:
        for text in texts:
            assert phrase not in text, phrase


# --------------------------------------------------------------------------- #
# 8. 별표 배점표 검증: 배점한도 초과·배점표 밖 항목은 자르지 않고 막는다
# --------------------------------------------------------------------------- #


def _active_band(payload: dict) -> dict:
    table = payload["quant_score_table"]
    return next(band for band in table["bands"] if band["band_key"] == table["active_band_key"])


def test_quant_score_table_payload_declares_sections_and_band(client, isolated_db, as_user):
    """적용 별표 배점표가 심사분야 번호·항목명·배점한도와 근거 경로를 함께 전달한다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(ANALYZE_URL, json=_analysis_payload(bid.id, score_table=SCORE_TABLE))

    payload = response.json()
    table = payload["quant_score_table"]
    assert table["attachment"] == "별표 2"
    assert table["active_band_key"] == "over_500m"
    items = {item["item_key"]: item for item in _active_band(payload)["items"]}
    assert items["performance"]["limit"] == "20"
    assert items["management"]["limit_kind"] == "credit_grade"
    # 근로조건은 별표 2 에만 있고 심사분야 번호가 II(로마 숫자) 다
    assert items["labor_plan"]["limit"] == "10"
    assert items["labor_plan"]["section_no"] == QUANT_SECTION_2
    assert "docs/analysis/" in items["performance"]["source"]
    # 결격사유는 합계 정합성에서 분리된다
    assert items["disqualification"]["limit_kind"] == "disqualification"
    assert any(grade["grade_group"] == "AAA ~ A-" for grade in table["credit_grades"])
    assert any(item["item_code"] == "sme_support" for item in table["reputation_items"])


def test_quant_item_exceeding_limit_blocks_scoring(client, isolated_db, as_user):
    """배점한도를 넘긴 항목은 조용히 자르지 않고 사유와 함께 계산을 막는다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={"quant_items": {"performance": 20, "labor_plan": 20}},
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is True
    assert "QUANT_LIMIT_EXCEEDED" in payload["blocked_reason"]
    assert "근로조건 이행계획" in payload["blocked_reason"]
    assert payload["price_compensation"] is None
    # 적용 배점표는 그대로 전달되어 사용자가 한도를 볼 수 있다
    assert payload["quant_score_table"]["attachment"] == "별표 2"


def test_quant_item_not_in_table_blocks_scoring(client, isolated_db, as_user):
    """배점표에 없는 항목(시설분야의 기술능력)은 입력 자체를 막는다."""
    as_user(10)
    bid = _create_bid(isolated_db)  # 별표 2 시설분야에는 기술능력 항목이 없다

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={"quant_items": {"performance": 20, "technical_capacity": 5}},
        ),
    )

    payload = response.json()
    assert payload["blocked"] is True
    assert "QUANT_ITEM_NOT_IN_TABLE" in payload["blocked_reason"]


def test_labor_plan_is_rejected_outside_facility(client, isolated_db, as_user):
    """근로조건 이행계획은 별표 2 밖에서 입력할 수 없다."""
    as_user(10)
    bid = _academic_bid(isolated_db)  # 별표 1 학술연구

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={"quant_items": {"performance": 10, "labor_plan": 5}},
        ),
    )

    payload = response.json()
    assert payload["blocked"] is True
    assert "QUANT_ITEM_NOT_IN_TABLE" in payload["blocked_reason"]


def test_unknown_management_grade_blocks_scoring(client, isolated_db, as_user):
    """별표 10 에 없는 등급은 임의 점수로 바꾸지 않고 막는다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={
                "quant_items": {"performance": 20},
                "management_grade": "존재하지않는등급",
            },
        ),
    )

    payload = response.json()
    assert payload["blocked"] is True
    assert "QUANT_GRADE_UNKNOWN" in payload["blocked_reason"]


def test_management_grade_uses_annex_10_score_for_band_limit(client, isolated_db, as_user):
    """경영상태는 배점한도 기준(10점)에 맞는 별표 10 점수로 환산된다."""
    as_user(10)
    bid = _create_bid(isolated_db)  # 별표 2 5억원 이상: 경영상태 배점한도 10

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={"quant_items": {"performance": 20}, "management_grade": "BBB+"},
        ),
    )

    payload = response.json()
    # Q = 이행실적 20 + 경영상태 9.8 = 29.8
    base = {s["scenario_name"]: s for s in payload["scenario_results"]}["기준"]
    assert base["qualification_score"] == pytest.approx(29.8)


def test_reputation_items_sum_and_cap(client, isolated_db, as_user):
    """신인도는 항목 합계를 내고 가점 상한 4.25 를 적용한다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={
                "quant_items": {"performance": 20},
                "reputation_items": {"job_creation": 3.0, "disabled_employment": 2.0},
            },
        ),
    )

    payload = response.json()
    # 항목 합계 5.0 -> 가점 상한 4.25, Q = 20 + 10(경영) + 4.25 = 34.25
    base = {s["scenario_name"]: s for s in payload["scenario_results"]}["기준"]
    assert base["qualification_score"] == pytest.approx(34.25)


def test_reputation_items_penalty_cap(client, isolated_db, as_user):
    """신인도 감점 합계는 감점 상한 -5.0 으로 제한된다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json=_analysis_payload(
            bid.id,
            score_table=SCORE_TABLE,
            qualification={
                "quant_items": {"performance": 20},
                "reputation_items": {
                    "wage_arrears": -2.0,
                    "delayed_delivery": -2.0,
                    "unfair_subcontract": -2.0,
                },
            },
        ),
    )

    payload = response.json()
    # 감점 합계 -6.0 -> 감점 상한 -5.0, Q = 20 + 10 - 5 = 25
    base = {s["scenario_name"]: s for s in payload["scenario_results"]}["기준"]
    assert base["qualification_score"] == pytest.approx(25.0)
