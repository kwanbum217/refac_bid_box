"""적격심사 정량평가 통합 분석 API 계약 테스트.

정본 규칙:
 - 판별은 src/app/services/evaluation_rules.py, 계산은 src/app/services/evaluation_scoring.py,
   모델 출처는 src/app/api/v1/predictions.py 의 predict_price_api. 본 테스트는 그것을 호출만 한다.
 - 기대값은 도메인 함수의 실제 동작으로 확정한 수치이며, 테스트 안에서 산식을 재계산하지 않는다.

실물 서비스(Redis·Chroma·Ollama·MySQL)는 호출하지 않는다. conftest 의 isolated_db
(SQLite 인메모리) 와 dependency_overrides 를 쓰고, 예측 모델은 대역으로 덮는다.

HTTP 로는 검증할 수 없는 경로가 하나 있다. 가격배점한도·평점계수·통과점수는
규칙 레지스트리가 실측으로 확정하지 않은 값이라 사용자 입력이 정본인데,
src/app/schemas/evaluations.py 의 QualificationInput 에 아직 그 필드가 없다
(스키마 파일은 이 작업의 쓰기 범위 밖이다. 코디네이터가 max_price_score·multiplier·
pass_threshold 세 필드를 추가할 예정이다). 따라서 배점표가 주입된 성공 경로는
QualificationInput 하위 클래스로 _analyze_bid 에 직접 넣어 검증하고,
스키마 확장 후 HTTP 계약으로 승격하면 된다.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.evaluations import EvaluationRequest, QualificationInput
from src.app.schemas.predictions import PredictPriceResponse

# 규칙 레지스트리가 확정한 별표 1 (시설분야용역 5억원 미만) 의 실측 낙찰하한율
ATTACH_01_LWLT_RATE = 89.995
ATTACH_01_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture
def stub_prediction(monkeypatch):
    """predict_price_api 를 대역으로 덮고 호출 기록을 남긴다. 실 모델 추론을 호출하지 않는다."""
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


class _QualificationWithScoreTable(QualificationInput):
    """스키마 확장이 예정된 배점표 필드를 선취한 사용자 입력 대역."""

    max_price_score: float | None = None
    multiplier: float | None = None
    pass_threshold: float | None = None


def _create_bid(
    db,
    *,
    category: str = "Servc",
    base_amount: int | None = 500_000_000,
    raw_overrides: dict | None = None,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        # 실측에서 적격심사 공고 전 건에 채워지는 두 필드.
        # 통상값(15, 4)과 다른 값을 써서 하드코딩을 기계로 걸러낸다.
        "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
        "sucsfbidLwltRate": "89.995",
        "srvceDivNm": "일반용역",
        "a_value": "100000000",
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
    selected_model: str = "evaluation-model",
    candidate_bid_amount: int = 407_448_800,
    qualification: dict | None = None,
) -> dict:
    return {
        "bid_id": bid_id,
        "selected_model": selected_model,
        "candidate_bid_amount": candidate_bid_amount,
        "qualification_input": {
            "performance_score": 60,
            "management_score": 15,
            "labor_plan_score": 0,
            "credibility_score": 0,
            "disqualification": False,
            # 브라우저가 계산해서 보낸 값. 서버는 이것을 신뢰하지 않는다.
            "price_score": 999,
            "total_score": 999,
            "is_qualified": True,
            **(qualification or {}),
        },
    }


def _analyze_with_score_table(
    db,
    bid,
    *,
    table: dict,
    candidate_bid_amount: int = 407_448_800,
    qualification: dict | None = None,
    selected_model: str = "requested-evaluation-model",
):
    """배점표가 입력된 경로를 서버 안에서 실행한다 (스키마 확장 전에는 HTTP 로 못 보낸다)."""
    qualification_input = {
        "performance_score": 60,
        "management_score": 15,
        "labor_plan_score": 0,
        "credibility_score": 0,
        "disqualification": False,
        # 서버가 신뢰하지 않는 브라우저 계산값
        "price_score": 999,
        "total_score": 999,
    }
    qualification_input.update(qualification or {})
    qualification_input.update(table)
    payload = EvaluationRequest(
        bid_id=bid.id,
        selected_model=selected_model,
        candidate_bid_amount=candidate_bid_amount,
        qualification_input=_QualificationWithScoreTable(**qualification_input),
    )
    return evaluations._analyze_bid(bid, payload, SimpleNamespace(scope={}), db)


# --------------------------------------------------------------------------- #
# 1. 정상 분석: 규칙 판정과 점수 계산 결과는 도메인 정본에서 나온다
# --------------------------------------------------------------------------- #


def test_score_table_input_drives_server_calculation(isolated_db, stub_prediction):
    """배점표가 입력되면 규칙 판정 결과와 결정론적 점수 계산을 함께 돌려준다."""
    stub_prediction(requested_model="requested-evaluation-model", actual_model="answered-model-v9")
    bid = _create_bid(isolated_db)

    response = _analyze_with_score_table(
        isolated_db,
        bid,
        table={
            "max_price_score": 20,
            "multiplier": 2,
            "pass_threshold": 95,
        },
    )

    assert response.status == "success"
    assert response.blocked is False
    assert response.rule_id == ATTACH_01_RULE_ID
    # 하한율과 기준비율은 규칙 레지스트리 실측값. API 는 아무 상수도 두지 않는다.
    assert response.lower_bound_rate == pytest.approx(ATTACH_01_LWLT_RATE)
    assert response.base_rate == pytest.approx(90.0)
    # (예정가격 - A값) * 하한율 + A값
    assert response.a_value_amount == 100_000_000
    assert response.min_bid_amount_with_a == 459_980_000

    scenarios = {s.scenario_name: s for s in response.scenario_results}
    assert set(scenarios) == {"하단", "기준", "상단"}
    # 기초금액 5억의 국가계약 +-2% 구간 (복수예가 시나리오는 예측이 아니라 공고 사양 구간이다)
    assert scenarios["하단"].estimated_price == 490_000_000
    assert scenarios["기준"].estimated_price == 500_000_000
    assert scenarios["상단"].estimated_price == 510_000_000

    # x = ROUND_HALF_UP(407,448,800 / 500,000,000, 4) = 0.8149
    base = scenarios["기준"]
    assert base.bid_to_estimated_ratio == pytest.approx(0.8149)
    # P = 20 - 2 * |0.90 - 0.8149| * 100 = 2.98
    assert base.price_score == pytest.approx(2.98)
    # Q = (60 + 15) + 0 + 0 = 75, 총점 = 77.98 < T 95
    assert base.qualification_score == pytest.approx(75.0)
    assert base.total_score == pytest.approx(77.98)
    assert base.pass_threshold == pytest.approx(95.0)
    assert base.is_qualified is False
    assert scenarios["하단"].price_score == pytest.approx(6.30)
    assert scenarios["상단"].price_score == pytest.approx(-0.22)

    # 근로조건 이행계획 0점 경고가 각 시나리오에 남는다
    assert any("근로조건 이행계획" in w for w in base.warnings)
    # P_req = 95 - 75 = 20 = B 이므로 역산 하한이 기준비율 자체(90%) 로 실질 구속된다
    assert response.min_possible_bid_rate == pytest.approx(90.0)


def test_announcement_lower_rate_binds_when_score_is_easy(isolated_db, stub_prediction):
    """역산 투찰률이 공고 하한율보다 낮으면 공고 하한율이 실질 하한이 된다."""
    stub_prediction(requested_model="requested-evaluation-model", actual_model="answered-model-v9")
    bid = _create_bid(isolated_db)

    response = _analyze_with_score_table(
        isolated_db,
        bid,
        candidate_bid_amount=449_000_000,
        table={
            "max_price_score": 20,
            "multiplier": 2,
            "pass_threshold": 95,
        },
        qualification={"labor_plan_score": 8},
    )

    scenarios = {s.scenario_name: s for s in response.scenario_results}
    # x = 0.8980 -> P = 20 - 2*0.20 = 19.60, Q = 83 -> 총점 102.60 >= 95
    assert scenarios["기준"].bid_to_estimated_ratio == pytest.approx(0.8980)
    assert scenarios["기준"].price_score == pytest.approx(19.60)
    assert scenarios["기준"].total_score == pytest.approx(102.60)
    assert scenarios["기준"].is_qualified is True
    assert scenarios["하단"].is_qualified is True
    assert scenarios["상단"].is_qualified is True
    # P_req = 12 -> 역산 86.0% < 공고 하한율 89.995% 이므로 하한율이 구속한다
    assert response.min_possible_bid_rate == pytest.approx(ATTACH_01_LWLT_RATE)


# --------------------------------------------------------------------------- #
# 2. 배점표 결측: 점수만 차단하고 계산 가능한 것은 그대로 준다
# --------------------------------------------------------------------------- #


def test_missing_score_table_blocks_scores_but_keeps_computable_amounts(
    client, isolated_db, as_user, spy_scenario_builder
):
    """스키마에 배점표 필드가 없는 현재, 점수 계산은 차단되고 하한율 계산은 살아있다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["blocked"] is True
    assert "MISSING_SCORE_TABLE" in payload["blocked_reason"]
    assert "배점표" in payload["blocked_reason"]
    # 규칙 판별 자체는 성공했으므로 별표와 하한율은 전달된다
    assert payload["rule_id"] == ATTACH_01_RULE_ID
    assert payload["lower_bound_rate"] == pytest.approx(ATTACH_01_LWLT_RATE)
    # 점수 계열은 계산되지 않는다 (추측값도 0도 넣지 않는다)
    assert payload["scenario_results"] == []
    assert payload["min_possible_bid_rate"] is None
    assert payload["base_rate"] is None
    # 계산 가능한 A값 반영 최저 투찰금액은 그대로 제공한다
    assert payload["a_value_amount"] == 100_000_000
    assert payload["min_bid_amount_with_a"] == 459_980_000
    warnings = " ".join(payload["warnings"])
    assert "459,980,000" in warnings
    assert "490,000,000" in warnings
    assert "510,000,000" in warnings
    # 예측 API 를 호출하지 않았으므로 모델 출처를 지어내지 않는다
    assert payload["actual_model"] is None
    assert payload["fallback_used"] is False
    # 복수예가 매개변수는 공고 필드에서 온다 (15/4 하드코딩이 아님)
    assert spy_scenario_builder[0][2]["tot_prdprc_num"] == 12
    assert spy_scenario_builder[0][2]["drwt_prdprc_num"] == 3


def test_scenario_counts_fall_back_to_domain_contract_when_absent(
    client, isolated_db, as_user, spy_scenario_builder
):
    """공고에 복수예가 필드가 없으면 API 는 수치를 채우지 않고 도메인 계약에 맡긴다."""
    as_user(10)
    bid = _create_bid(
        isolated_db,
        raw_overrides={"totPrdprcNum": None, "drwtPrdprcNum": None},
    )

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

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

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text


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

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert f"{block_code}:" in payload["blocked_reason"]
    assert payload["scenario_results"] == []
    # 규칙을 매칭하지 못하면 별표 정보도 없다
    assert payload["lower_bound_rate"] is None


def test_blocked_analysis_still_saves_snapshot(client, isolated_db, as_user):
    """차단 응답도 이력 보존을 위해 스냅샷으로 남는다."""
    as_user(10)
    bid = _create_bid(isolated_db, category="Thng")
    # conftest 의 get_db 대역이 요청마다 session.close() 를 하여 ORM 객체가 detach 된다.
    # 그래서 request 이후에 쓸 식별자는 미리 확보해 둔다.
    bid_id = bid.id

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid_id))
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

    def _boom(*args, **kwargs):
        raise RuntimeError("스냅샷 저장 불가")

    monkeypatch.setattr(isolated_db, "commit", _boom)

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    assert response.json()["blocked"] is True


def test_analyze_returns_404_for_unknown_bid(client, isolated_db, as_user):
    as_user(10)

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(999_999))

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# 4. 서버 계산 원칙: 브라우저가 보낸 점수는 신뢰하지 않는다
# --------------------------------------------------------------------------- #


def test_browser_supplied_scores_are_never_echoed(client, isolated_db, as_user):
    """클라이언트가 보낸 999 점 계열 값은 응답의 어떤 자리에도 나타나지 않는다."""
    as_user(10)
    bid = _create_bid(isolated_db)

    response = client.post("/api/v1/evaluations/analyze", json=_analysis_payload(bid.id))

    assert response.status_code == 200, response.text
    assert "999" not in response.text


def test_server_ignores_client_scores_when_table_is_supplied(isolated_db, stub_prediction):
    """배점표가 있어도 가격점수와 총점은 서버 계산값이지 요청값이 아니다."""
    stub_prediction(requested_model="requested-evaluation-model", actual_model="answered-model-v9")
    bid = _create_bid(isolated_db)

    response = _analyze_with_score_table(
        isolated_db,
        bid,
        table={"max_price_score": 20, "multiplier": 2, "pass_threshold": 95},
    )

    dumped = response.model_dump()
    assert "999" not in str(dumped)
    assert dumped["scenario_results"][1]["price_score"] == pytest.approx(2.98)
    assert dumped["scenario_results"][1]["total_score"] == pytest.approx(77.98)


# --------------------------------------------------------------------------- #
# 5. 모델 출처: predict_price_api 의 산출물을 그대로 전달한다
# --------------------------------------------------------------------------- #


def test_model_provenance_is_passed_through_from_prediction_api(isolated_db, stub_prediction):
    """요청 모델과 실제 모델이 다르면 대체 사실이 응답에 그대로 드러난다."""
    stub_prediction(
        requested_model="requested-evaluation-model",
        actual_model="fallback-model-v3",
        fallback_used=True,
        fallback_reason="requested-evaluation-model 추론 실패",
    )
    bid = _create_bid(isolated_db)

    response = _analyze_with_score_table(
        isolated_db,
        bid,
        table={"max_price_score": 20, "multiplier": 2, "pass_threshold": 95},
        selected_model="requested-evaluation-model",
    )

    assert response.requested_model == "requested-evaluation-model"
    assert response.actual_model == "fallback-model-v3"
    assert response.fallback_used is True
    assert response.fallback_reason == "requested-evaluation-model 추론 실패"
    # 위임이 실제로 일어났는지: 예측 API 가 받은 요청 파라미터로 확인한다
    called = stub_prediction.calls[-1]
    assert called.bid_id == bid.id
    assert called.selected_model == "requested-evaluation-model"
    assert called.user_price == "407448800"


def test_model_provenance_reports_unavailable_prediction(isolated_db, monkeypatch):
    """예측 모델을 쓸 수 없을 때 대체 사실을 숨기지 않는다."""

    def _unavailable(*args, **kwargs):
        raise HTTPException(
            status_code=503, detail="예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다."
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _unavailable)
    bid = _create_bid(isolated_db)

    response = _analyze_with_score_table(
        isolated_db,
        bid,
        table={"max_price_score": 20, "multiplier": 2, "pass_threshold": 95},
    )

    assert response.status == "success"
    assert response.actual_model is None
    assert response.fallback_used is True
    assert "503" in (response.fallback_reason or "")
    assert any("모델 출처" in w for w in response.warnings)


# --------------------------------------------------------------------------- #
# 6. 소유권 격리: 조회·수정·삭제·목록 네 경로 모두
# --------------------------------------------------------------------------- #


def test_profile_is_isolated_on_read_update_delete_and_list(client, isolated_db, as_user):
    """타인 프로필은 조회·수정·삭제가 404 로 차단되고 목록에 노출되지 않는다."""
    as_user(2)
    owned = client.post(
        "/api/v1/evaluations/profiles",
        json={"name": "남의 프로필", "input_json": {"performance_score": 10}},
    )
    assert owned.status_code == 201, owned.text
    profile_id = owned.json()["id"]

    as_user(1)
    assert client.get(f"/api/v1/evaluations/profiles/{profile_id}").status_code == 404
    assert (
        client.put(
            f"/api/v1/evaluations/profiles/{profile_id}", json={"name": "탈취 시도"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/evaluations/profiles/{profile_id}").status_code == 404
    assert client.get("/api/v1/evaluations/profiles").json() == []
    # 차단되었으므로 자원은 원 소유자에게 그대로 남아 있다
    as_user(2)
    listing = client.get("/api/v1/evaluations/profiles").json()
    assert [p["id"] for p in listing] == [profile_id]
    assert listing[0]["name"] == "남의 프로필"


def test_snapshot_is_isolated_on_read_delete_and_list(client, isolated_db, as_user):
    """타인 스냅샷은 조회·삭제가 404 로 차단되고 목록과 bid_id 필터에 노출되지 않는다."""
    bid = _create_bid(isolated_db)
    bid_id = bid.id
    as_user(2)
    owned = client.post(
        "/api/v1/evaluations/snapshots",
        json={
            "bid_id": bid_id,
            "rule_id": "RULE-2",
            "model_id": "MODEL-2",
            "model_version": "1.0",
            "input_json": {"source": "owner"},
            "result_json": {"score": 1},
        },
    )
    assert owned.status_code == 201, owned.text
    snapshot_id = owned.json()["id"]

    as_user(1)
    assert client.get(f"/api/v1/evaluations/snapshots/{snapshot_id}").status_code == 404
    assert client.delete(f"/api/v1/evaluations/snapshots/{snapshot_id}").status_code == 404
    assert client.get("/api/v1/evaluations/snapshots").json() == []
    assert client.get(f"/api/v1/evaluations/snapshots?bid_id={bid_id}").json() == []

    # 같은 공고에 내 스냅샷을 만들어도 남의 스냅샷이 섞여 나오지 않는다
    mine = client.post(
        "/api/v1/evaluations/snapshots",
        json={
            "bid_id": bid_id,
            "rule_id": "RULE-1",
            "model_id": "MODEL-1",
            "model_version": "1.0",
            "input_json": {"source": "attacker"},
            "result_json": {"score": 2},
        },
    )
    assert mine.status_code == 201, mine.text
    own_rows = client.get("/api/v1/evaluations/snapshots").json()
    assert [s["id"] for s in own_rows] == [mine.json()["id"]]

    # 차단되었으므로 남의 스냅샷은 그대로 살아있다
    as_user(2)
    assert client.get(f"/api/v1/evaluations/snapshots/{snapshot_id}").status_code == 200


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
