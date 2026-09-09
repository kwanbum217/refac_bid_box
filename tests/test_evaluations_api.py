"""적격심사 정량평가 통합 분석 API 계약 테스트."""

from types import SimpleNamespace

import pytest

from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


def _create_bid(db, *, category: str = "Servc", raw_data: dict | None = None) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
        "sucsfbidLwltRate": "89.995",
        "srvceDivNm": "일반용역",
        "a_value": "100000000",
    }
    if raw_data is not None:
        data.update(raw_data)

    bid = BidAnnouncement(
        bid_ntce_nm="적격심사 API 테스트 공고",
        bid_ntce_no="EVAL-API-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=500_000_000,
        presmpt_prce=500_000_000,
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


def _analysis_payload(bid_id: int, *, selected_model: str = "evaluation-model") -> dict:
    return {
        "bid_id": bid_id,
        "selected_model": selected_model,
        "candidate_bid_amount": 407_448_800,
        "qualification_input": {
            "performance_score": 30,
            "management_score": 10,
            "labor_plan_score": 0,
            "credibility_score": 0,
            "disqualification": False,
            "price_score": 999,
            "total_score": 999,
        },
        "price_scenarios": [
            {
                "scenario_name": "기준",
                "scenario_type": "base",
                "estimated_price": 500_000_000,
            }
        ],
    }


def test_analyze_returns_rule_scores_server_provenance_and_snapshot(client, isolated_db, as_user):
    """정상 분석은 서버 계산 결과와 모델 출처를 반환하고 스냅샷을 남긴다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    bid_id = bid.id

    response = client.post(
        "/api/v1/evaluations/analyze",
        json=_analysis_payload(bid_id, selected_model="requested-evaluation-model"),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == "SERVC_QUAL_POST_20260526_ATTACH_01"
    assert payload["requested_model"] == "requested-evaluation-model"
    assert payload["actual_model"] == "requested-evaluation-model"
    assert payload["fallback_used"] is False
    assert payload["a_value_amount"] == 100_000_000
    assert payload["min_bid_amount_with_a"] == 459_980_000

    scenario = payload["scenario_results"][0]
    assert scenario["bid_to_estimated_ratio"] == pytest.approx(0.8149)
    assert scenario["price_score"] == pytest.approx(56.98)
    assert scenario["qualification_score"] == pytest.approx(40.0)
    assert scenario["total_score"] == pytest.approx(96.98)
    assert scenario["is_qualified"] is True
    assert scenario["warnings"]

    snapshots = client.get("/api/v1/evaluations/snapshots")
    assert snapshots.status_code == 200, snapshots.text
    snapshot_payload = snapshots.json()
    assert len(snapshot_payload) == 1
    assert snapshot_payload[0]["user_id"] == 10
    assert snapshot_payload[0]["bid_id"] == bid_id
    assert snapshot_payload[0]["rule_id"] == payload["rule_id"]
    assert snapshot_payload[0]["result_json"]["scenario_results"][0][
        "price_score"
    ] == pytest.approx(56.98)


@pytest.mark.parametrize(
    ("category", "raw_data", "block_code"),
    [
        ("Thng", {}, "NOT_SERVC"),
        ("Servc", {"prearngPrceDcsnMthdNm": "비예가"}, "NON_PRED_PRICE"),
        (
            "Servc",
            {"sucsfbidMthdNm": "적격심사제-관리규정외 수기심사(총점입력)"},
            "MANUAL_EVALUATION",
        ),
        ("Servc", {"sucsfbidMthdNm": "적격심사제-등록되지 않은 기준"}, "RULE_NOT_FOUND"),
    ],
)
def test_analyze_returns_blocked_result_with_reason_code(
    client, isolated_db, as_user, category, raw_data, block_code
):
    """지원 범위 밖 조건은 500이 아니라 코드가 있는 정상 차단 응답으로 전달한다."""
    as_user(10)
    bid = _create_bid(isolated_db, category=category, raw_data=raw_data)
    bid_id = bid.id

    response = client.post(
        "/api/v1/evaluations/analyze",
        json=_analysis_payload(bid_id),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert block_code in payload["blocked_reason"]
    assert payload["scenario_results"] == []


def test_analyze_ignores_browser_supplied_scores(client, isolated_db, as_user):
    """클라이언트가 보낸 가짜 점수는 서버의 결정론적 계산을 덮어쓰지 못한다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    bid_id = bid.id

    response = client.post(
        "/api/v1/evaluations/analyze",
        json=_analysis_payload(bid_id),
    )

    assert response.status_code == 200
    scenario = response.json()["scenario_results"][0]
    assert scenario["price_score"] == pytest.approx(56.98)
    assert scenario["total_score"] == pytest.approx(96.98)
    assert scenario["total_score"] != 999


def test_evaluation_resources_are_isolated_by_owner(client, isolated_db, as_user):
    """타 사용자의 프로필·스냅샷은 조회·수정·삭제할 수 없다."""
    bid = _create_bid(isolated_db)
    bid_id = bid.id
    as_user(2)
    profile_response = client.post(
        "/api/v1/evaluations/profiles",
        json={"name": "다른 사용자 프로필", "input_json": {"performance_score": 10}},
    )
    snapshot_response = client.post(
        "/api/v1/evaluations/snapshots",
        json={
            "bid_id": bid_id,
            "rule_id": "RULE-1",
            "model_id": "MODEL-1",
            "model_version": "1.0",
            "input_json": {"source": "test"},
            "result_json": {"score": 1},
        },
    )
    assert profile_response.status_code == 201, profile_response.text
    assert snapshot_response.status_code == 201, snapshot_response.text
    profile_id = profile_response.json()["id"]
    snapshot_id = snapshot_response.json()["id"]

    as_user(1)
    assert client.get(f"/api/v1/evaluations/profiles/{profile_id}").status_code == 404
    assert (
        client.put(
            f"/api/v1/evaluations/profiles/{profile_id}",
            json={"name": "탈취 시도"},
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/evaluations/snapshots/{snapshot_id}").status_code == 404
    assert client.delete(f"/api/v1/evaluations/snapshots/{snapshot_id}").status_code == 404
