"""무상태 투찰가 추천 계산 API 계약 시험 (설계 5.1~5.4, D-W4).

정본 규칙:
 - 판별은 evaluation_rules, 환산·역산은 evaluation_recommendation,
   모델 출처는 predict_price_api 가 정본이다. 본 시험은 그것을 호출만 한다.
 - 가격배점한도(B)·평점계수(k)·통과점수(T) 는 규칙 레지스트리에 확정값만 선언한다.
   선언되지 않은 값은 요청 수정값(overrides)으로 보완한다.
 - 사정률은 아직 과거 실측이 없어 이론 범위(기초금액 ±2%/±3%)만 쓴다.

실물 서비스(Redis·Chroma·Ollama·MySQL) 와 실제 모델 추론은 호출하지 않는다.
conftest 의 isolated_db(SQLite 인메모리) 와 dependency_overrides 를 쓰고,
predict_price_api 는 autouse fixture 로 항상 대역으로 덮는다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.company_profiles import AccountQualificationFact
from src.app.models.evaluations import BidEvaluationSnapshot
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_recommendation import (
    compute_price_bounds,
    convert_reputation_codes,
)

RECOMMEND_URL = "/api/v1/evaluations/recommend"

ATTACH_01_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
INCHEON_RULE_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"

STUB_OPTIMAL_PRICE = 440_000_000

# 공고문 배점표를 사용자가 입력한 상태를 재현하는 값이다. 별표 1 은 B·k·T 를 선언하지 않는다.
SCORE_TABLE_OVERRIDES = {"max_price_score": 60.0, "multiplier": 2.0, "pass_threshold": 95.0}
DEFAULT_QUANT_ITEMS = {"performance": 20.0, "labor_plan": 10.0}
MEMBER_CREDIT_GRADE = "AAA ~ A-"


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    """어떤 시험도 실제 모델 가중치를 로드하지 않도록 예측 API 를 기본 대역으로 덮는다."""

    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=STUB_OPTIMAL_PRICE,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id="default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_bid(
    db,
    *,
    category: str = "Servc",
    method: str = "시설분야용역 적격심사 추정가격 5억원 이상",
    lwlt_rate: str = "89.995",
    base_amount: int | None = 500_000_000,
    notice_no: str = "EVAL-REC-001",
    dminstt_nm: str = "테스트 수요기관",
    raw_overrides: dict | None = None,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "sucsfbidLwltRate": lwlt_rate,
        "srvceDivNm": "일반용역",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    data.update(raw_overrides or {})
    data = {key: value for key, value in data.items() if value is not None}
    bid = BidAnnouncement(
        bid_ntce_nm="추천 API 테스트 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=dminstt_nm,
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


def _create_local_bid(
    db,
    *,
    method: str = "시설분야용역 적격심사 추정가격 5억원 이상",
    notice_no: str = "EVAL-REC-LOCAL-001",
) -> BidAnnouncement:
    """인천 시·도 규칙으로 판별되는 지방계약 공고. 기관 기준정보를 함께 넣는다."""
    from src.app.models.demand_institutions import G2BDemandInstitution

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
    return _create_bid(
        db,
        method=method,
        lwlt_rate="87.995",
        notice_no=notice_no,
        dminstt_nm="인천광역시 본청",
        raw_overrides={
            "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
            "dminsttCd": "1234",
        },
    )


def _add_member_facts(db, user_id: int, **kwargs) -> AccountQualificationFact:
    facts = AccountQualificationFact(user_id=user_id, version="1.0", **kwargs)
    db.add(facts)
    db.commit()
    db.refresh(facts)
    return facts


def _add_bid_result(db, *, dminstt_nm: str, category: str, participants: int) -> None:
    db.add(
        BidResult(
            bid_ntce_no=f"PAST-{participants}",
            bid_ntce_ord="000",
            dminstt_nm=dminstt_nm,
            category=category,
            rl_openg_dt=utcnow(),
            raw_data={"prtcptCnum": str(participants)},
        )
    )
    db.commit()


def _recommend(client, bid, *, overrides: dict | None = None, selected_model: str | None = None):
    body: dict = {"bid_id": bid.id, "overrides": dict(overrides or {})}
    if selected_model is not None:
        body["selected_model"] = selected_model
    return client.post(RECOMMEND_URL, json=body)


def _registry_overrides(**extra) -> dict:
    overrides = {"quant_items": dict(DEFAULT_QUANT_ITEMS), **SCORE_TABLE_OVERRIDES}
    overrides.update(extra)
    return overrides


# --------------------------------------------------------------------------- #
# 1. 회원 원자료 자동 기입과 우선순위
# --------------------------------------------------------------------------- #


def test_member_credit_grade_is_autofilled(client, isolated_db, as_user):
    """회원 원자료의 신용평가등급이 별표 10 으로 환산되어 경영상태 점수가 자동 기입된다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)

    response = _recommend(client, bid, overrides=_registry_overrides())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success", payload
    assert payload["rule_id"] == ATTACH_01_RULE_ID
    # 수행능력 20 + 경영상태 10(별표 10 이 자동 환산) + 근로조건 10 = 40
    assert payload["non_price_score"] == "40"
    items = {item["item_key"]: item["score"] for item in payload["non_price_items"]}
    assert items["management"] == "10"
    assert items["performance"] == "20"
    assert items["labor_plan"] == "10"


def test_request_overrides_take_priority_over_member_facts(client, isolated_db, as_user):
    """요청 수정값이 회원 원자료보다 우선한다(우선순위: 수정값 > 회원 원자료 > 빈 값)."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade="CCC+ 이하")
    bid = _create_bid(isolated_db)

    response = _recommend(
        client,
        bid,
        overrides=_registry_overrides(management_grade=MEMBER_CREDIT_GRADE),
    )

    payload = response.json()
    assert payload["status"] == "success", payload
    # 회원 등급(CCC+ 이하)이 아니라 요청 수정값(AAA~A-)으로 환산되어 경영상태 10 점이다.
    items = {item["item_key"]: item["score"] for item in payload["non_price_items"]}
    assert items["management"] == "10"
    assert payload["non_price_score"] == "40"


def test_local_rule_uses_member_manual_non_price_score(client, isolated_db, as_user):
    """레지스트리 정량 배점표가 없는 지방 규칙 공고는 회원 비가격 정량점수를 자동 기입한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, non_price_quant_score=Decimal("50"))
    bid = _create_local_bid(isolated_db)

    response = _recommend(client, bid)
    payload = response.json()

    assert payload["status"] == "success", payload
    assert payload["rule_id"] == INCHEON_RULE_ID
    assert payload["quant_source"] == "USER_INPUT_UNVERIFIED"
    assert payload["quant_notice"]
    assert payload["non_price_score"] == "50"
    # LOCAL 규칙에는 조달청 정량 배점표를 붙이지 않는다.
    assert payload["quant_score_table"] is None


def test_multi_option_reputation_codes_are_not_guessed(client, isolated_db, as_user):
    """복수 선택지 신인도 항목은 코드만으로 평점을 정하지 않고 0 + 선택 필요로 남긴다."""
    as_user(10)
    _add_member_facts(
        isolated_db,
        10,
        credit_grade=MEMBER_CREDIT_GRADE,
        reputation_items=["disabled_company", "sme_consortium"],
    )
    bid = _create_bid(isolated_db)

    response = _recommend(client, bid, overrides=_registry_overrides())
    payload = response.json()

    assert payload["status"] == "success", payload
    # disabled_company 는 선택지가 하나(1.5)라 환산되고, sme_consortium 은 복수라 0 + 선택 필요다.
    assert payload["reputation_grade_required"] == ["sme_consortium"]
    items = {item["item_key"]: item["score"] for item in payload["non_price_items"]}
    assert items["reputation"] == "1.5"
    assert any("평점 선택이 필요한" in warning for warning in payload["warnings"])


def test_member_reputation_ratings_are_autofilled(client, isolated_db, as_user):
    """회원이 고른 항목별 평점(dict)은 그대로 추천 계산에 자동 기입되고 경고가 없다."""
    as_user(10)
    _add_member_facts(
        isolated_db,
        10,
        credit_grade=MEMBER_CREDIT_GRADE,
        reputation_items={"sme_consortium": 1.5, "job_creation": 2.0},
    )
    bid = _create_bid(isolated_db)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["status"] == "success", payload
    assert payload["reputation_grade_required"] == []
    items = {item["item_key"]: item["score"] for item in payload["non_price_items"]}
    # 수행능력 20 + 경영상태 10 + 근로조건 10 + 신인도(1.5 + 2.0) = 43.5
    assert items["reputation"] == "3.5"
    assert payload["non_price_score"] == "43.5"
    assert not any("평점 선택이 필요한" in warning for warning in payload["warnings"])


def test_request_reputation_override_wins_per_item(client, isolated_db, as_user):
    """요청 수정값 reputation_items 는 항목별로 저장 평점을 덮고, 나머지 항목은 저장값을 쓴다."""
    as_user(10)
    _add_member_facts(
        isolated_db,
        10,
        credit_grade=MEMBER_CREDIT_GRADE,
        reputation_items={"sme_consortium": 1.5, "job_creation": 2.0},
    )
    bid = _create_bid(isolated_db)

    payload = _recommend(
        client,
        bid,
        overrides=_registry_overrides(reputation_items={"sme_consortium": 1.0}),
    ).json()

    assert payload["status"] == "success", payload
    assert payload["reputation_grade_required"] == []
    items = {item["item_key"]: item["score"] for item in payload["non_price_items"]}
    # 수정값 sme_consortium 1.0 이 저장값 1.5 를 덮고, job_creation 2.0 은 저장값이 남는다.
    assert items["reputation"] == "3"


def test_request_override_clears_reputation_grade_required(client, isolated_db, as_user):
    """구형 코드 목록의 '평점 선택 필요'는 요청 수정값이 그 항목을 채우면 사라진다."""
    as_user(10)
    _add_member_facts(
        isolated_db,
        10,
        credit_grade=MEMBER_CREDIT_GRADE,
        reputation_items=["disabled_company", "sme_consortium"],
    )
    bid = _create_bid(isolated_db)

    payload = _recommend(
        client,
        bid,
        overrides=_registry_overrides(reputation_items={"sme_consortium": 1.0}),
    ).json()

    assert payload["status"] == "success", payload
    assert payload["reputation_grade_required"] == []
    assert not any("평점 선택이 필요한" in warning for warning in payload["warnings"])


# --------------------------------------------------------------------------- #
# 2. 세 금액: AI 예측가와 최저가·최상가
# --------------------------------------------------------------------------- #


def test_prediction_and_price_bounds_are_returned(client, isolated_db, as_user):
    """AI 예측가와 최저가·최상가, 근거 재료가 한 번에 돌아온다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)
    _add_bid_result(isolated_db, dminstt_nm=bid.dminstt_nm, category=bid.category, participants=5)
    _add_bid_result(isolated_db, dminstt_nm=bid.dminstt_nm, category=bid.category, participants=9)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["status"] == "success", payload
    assert payload["prediction"]["optimal_price"] == STUB_OPTIMAL_PRICE

    bounds = payload["price_bounds"]
    assert bounds["status"] == "ok", bounds
    assert bounds["min_bid_amount"] is not None
    assert bounds["max_bid_amount"] is not None
    # 최저가 <= 최상가. AI 예측가와의 대소 관계는 단정하지 않는다.
    assert bounds["min_bid_amount"] <= bounds["max_bid_amount"]
    # 최저가는 사정률 하한 예정가격의 낙찰하한율 금액 이상이다.
    lwlt_floor = int(Decimal(bounds["min_pred_price"]) * Decimal("89.995") / Decimal("100"))
    assert bounds["min_bid_amount"] >= lwlt_floor

    # 근거 문장 재료: B, Q(S), T, P, 사정률 하한·상한, 참가업체 수.
    assert payload["max_price_score"] == "60"
    assert payload["non_price_score"] == "40"
    assert payload["pass_threshold"] == "95"  # noqa: S105
    assert payload["required_price_score"] == "55"
    assert bounds["rate_low_percent"] == "98"
    assert bounds["rate_high_percent"] == "102"
    assert payload["participant_stats"] == {
        "sample_count": 2,
        "average": "7",
        "minimum": 5,
        "maximum": 9,
    }
    # 사정률 범위는 이론값이며 과거 실측이 아님을 표시한다.
    assert payload["rate_source"] == "theoretical"
    assert payload["rate_notice"]


def test_disqualification_omitted_is_not_checked(client, isolated_db, as_user):
    """결격 입력을 생략하면 '미확인'으로 표시하고 결격 없이 계산한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["status"] == "success", payload
    assert payload["disqualification_status"] == "not_checked"


def test_disqualification_explicit_true_is_disqualified(client, isolated_db, as_user):
    """결격을 명시하면 disqualified 로 표시한다(기존 명시 입력 동작 유지)."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)

    payload = _recommend(client, bid, overrides=_registry_overrides(disqualification=True)).json()

    assert payload["status"] == "success", payload
    assert payload["disqualification_status"] == "disqualified"


# --------------------------------------------------------------------------- #
# 3. 저장 없음(무상태)과 인증
# --------------------------------------------------------------------------- #


def test_recommend_does_not_persist_snapshots(client, isolated_db, as_user):
    """추천 계산은 스냅샷을 저장하지 않는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)
    before = isolated_db.query(BidEvaluationSnapshot).count()

    response = _recommend(client, bid, overrides=_registry_overrides())

    assert response.status_code == 200, response.text
    assert isolated_db.query(BidEvaluationSnapshot).count() == before


def test_recommend_requires_login(client, isolated_db):
    """비로그인 요청은 401 로 거부한다."""
    bid = _create_bid(isolated_db)

    response = client.post(RECOMMEND_URL, json={"bid_id": bid.id, "overrides": {}})

    assert response.status_code == 401, response.text


# --------------------------------------------------------------------------- #
# 4. 규칙 차단 상태
# --------------------------------------------------------------------------- #


def test_unresolved_rule_returns_blocked_with_prediction(client, isolated_db, as_user):
    """규칙 판별이 막혀도 AI 예측가는 함께 돌려주고 차단 사유를 담는다."""
    as_user(10)
    bid = _create_bid(isolated_db, method="알수없는특수용역적격심사방식", lwlt_rate="85.000")

    payload = _recommend(client, bid).json()

    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert payload["blocked_reason"]
    assert payload["price_bounds"] is None
    # 설계 5.1: 규칙 판별이 막혀도 AI 예측가는 표시한다.
    assert payload["prediction"]["optimal_price"] == STUB_OPTIMAL_PRICE


def test_registry_declared_score_table_is_used_without_overrides(client, isolated_db, as_user):
    """규칙 레지스트리가 B·k·T 를 선언하면 요청에 배점표가 없어도 계산한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)

    payload = _recommend(client, bid, overrides={"quant_items": dict(DEFAULT_QUANT_ITEMS)}).json()

    assert payload["status"] == "success", payload
    assert payload["max_price_score"] == "60"
    # 별표 1 이 선언한 통과점수는 85 다. 요청에 배점표가 없으면 이 선언값을 쓴다.
    assert payload["pass_threshold"] == "85"  # noqa: S105
    assert payload["non_price_score"] == "40"


def test_local_rule_without_member_quant_score_is_blocked(client, isolated_db, as_user):
    """지방 규칙 공고에서 정량점수를 정할 수 없으면 계산을 막고 사유를 담는다."""
    as_user(10)
    # 신용평가등급만 있고 비가격 정량점수 기본값이 없어 지방 공고 정량점수를 정할 수 없다.
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_local_bid(isolated_db)

    payload = _recommend(client, bid).json()

    assert payload["status"] == "blocked"
    assert "LOCAL_QUANT_REQUIRED" in payload["blocked_reason"]
    assert payload["price_bounds"] is None
    # 규칙은 판별됐으므로 AI 예측가는 함께 돌려준다.
    assert payload["prediction"]["optimal_price"] == STUB_OPTIMAL_PRICE


def test_recommend_by_notice_number_and_ord(client, isolated_db, as_user):
    """공고 키는 bid_id 없이 공고번호+차수로도 받는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    _create_bid(isolated_db, notice_no="EVAL-REC-777")

    response = client.post(
        RECOMMEND_URL,
        json={
            "bid_ntce_no": "EVAL-REC-777",
            "bid_ntce_ord": "000",
            "overrides": _registry_overrides(),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["rule_id"] == ATTACH_01_RULE_ID


# --------------------------------------------------------------------------- #
# 5. 순수 함수 단위 시험
# --------------------------------------------------------------------------- #


class TestComputePriceBounds:
    """사정률 범위를 인자로 받는 순수 함수의 경계 동작."""

    def test_min_is_not_below_lwlt_and_not_above_max(self) -> None:
        result = compute_price_bounds(
            base_amount=Decimal("500000000"),
            rate_low=Decimal("0.98"),
            rate_high=Decimal("1.02"),
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("40"),
            base_rate=Decimal("0.93"),
            max_price_score=Decimal("60"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
        )
        assert result.status == "ok"
        assert result.min_bid_amount is not None
        assert result.max_bid_amount is not None
        assert result.min_bid_amount <= result.max_bid_amount
        lwlt_floor = (result.min_pred_price or Decimal("0")) * Decimal("0.89995")
        assert result.min_bid_amount >= lwlt_floor

    def test_blocked_when_required_score_exceeds_max(self) -> None:
        result = compute_price_bounds(
            base_amount=Decimal("500000000"),
            rate_low=Decimal("0.98"),
            rate_high=Decimal("1.02"),
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("20"),
            base_rate=Decimal("0.93"),
            max_price_score=Decimal("60"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
        )
        # P_req 75 > B 60 이므로 만점으로도 통과할 수 없어 차단된다.
        assert result.status == "blocked"
        assert result.min_bid_amount is None
        assert result.reasons


class TestConvertReputationCodes:
    """신인도 원자료 환산: dict 는 저장 평점을 쓰고, 구형 list 는 단일 선택지만 환산한다."""

    def test_single_option_is_converted_and_multi_option_is_flagged(self) -> None:
        result = convert_reputation_codes(["disabled_company", "sme_consortium", "unknown_code"])
        assert result.values == {"disabled_company": 1.5}
        assert result.needs_grade_selection == ["sme_consortium", "unknown_code"]

    def test_stored_ratings_are_used_for_multi_option_and_range(self) -> None:
        result = convert_reputation_codes({"sme_consortium": 1.5, "job_creation": 2.0})
        assert result.values == {"sme_consortium": 1.5, "job_creation": 2.0}
        assert result.needs_grade_selection == []

    def test_unknown_code_in_stored_ratings_is_flagged(self) -> None:
        result = convert_reputation_codes({"sme_consortium": 1.5, "unknown_code": 1.0})
        assert result.values == {"sme_consortium": 1.5}
        assert result.needs_grade_selection == ["unknown_code"]
