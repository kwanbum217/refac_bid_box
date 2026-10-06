"""인천·제주·강원·경남 GENERAL 10억원 이상 30억 분할과 경북 기타 일반용역 5억 하한율 시험.

정본:
 - .orca/capsules/task_b1c4b69f0e6f/capsule.yaml
 - docs/analysis/local_10eok_lwlt_derivation_20261006.md (원문 위치·산식·역산·info21c 대조)
 - src/app/services/evaluation_rules.py 의 _five_band_price, _four_band_price, _threshold_30_10
 - src/app/services/evaluation_flat_zones.py 의 _five_band_general_under_30_only

네 GENERAL 규칙은 원문 별표 산식과 본문 통과점수로 역산해 87.745/86.745/85.495/77.995/72.995
5구간을 씁니다. 경북 별표 4 는 5억원 기준 두 구간만 인쇄하므로 5억원 미만 87.745%, 5억원
이상 86.745% 입니다. 인천·제주·강원 단순노무는 전 구간 87.745% 입니다. 평가 API 끝단은
mock 없이 TestClient 로 호출하고, 이 워크트리에 모델 파일이 없어 예측 모델만 시험 대역으로
대체합니다. 규칙 판별·구간 하한율·최저 투찰금액은 실제 코드가 계산합니다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_flat_zones import flat_zone_for
from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
)

ANALYZE_URL = "/api/v1/evaluations/analyze"

INCHEON_GENERAL_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
INCHEON_SIMPLE_ID = "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"
JEJU_GENERAL_ID = "SERVC_LOCAL_JEJU_20240101_ATTACH_01"
JEJU_SIMPLE_ID = "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR"
GANGWON_GENERAL_ID = "SERVC_LOCAL_GANGWON_20230611_ATTACH_01"
GANGWON_SIMPLE_ID = "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR"
GN_GENERAL_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"
GB_GENERAL_ID = "SERVC_LOCAL_GB_20260108_ATTACH_04"

SIMPLE_LABOR_RULE_IDS = (INCHEON_SIMPLE_ID, JEJU_SIMPLE_ID, GANGWON_SIMPLE_ID)

GENERAL_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"
SIMPLE_LABOR_METHOD = "단순노무용역 적격심사 추정가격 5억원 미만"

# (지역코드, 지역명) — 네 GENERAL 규칙과 단순노무 규칙의 판별에 씁니다.
REGION_BY_RULE: dict[str, tuple[str, str]] = {
    INCHEON_GENERAL_ID: ("28", "인천광역시"),
    INCHEON_SIMPLE_ID: ("28", "인천광역시"),
    JEJU_GENERAL_ID: ("50", "제주특별자치도"),
    JEJU_SIMPLE_ID: ("50", "제주특별자치도"),
    GANGWON_GENERAL_ID: ("51", "강원특별자치도"),
    GANGWON_SIMPLE_ID: ("51", "강원특별자치도"),
    GN_GENERAL_ID: ("48", "경상남도"),
    GB_GENERAL_ID: ("47", "경상북도"),
}

GENERAL_RULE_IDS = (
    INCHEON_GENERAL_ID,
    JEJU_GENERAL_ID,
    GANGWON_GENERAL_ID,
    GN_GENERAL_ID,
)

# (상한, 기대 하한율, 구간 라벨). 10억원 이상을 30억원 경계로 나눈 5구간입니다.
GENERAL_BANDS = (
    ("200000000", "87.745", "추정가격 2억원 미만"),
    ("500000000", "86.745", "5억원 미만 2억원 이상"),
    ("1000000000", "85.495", "10억원 미만 5억원 이상"),
    ("3000000000", "77.995", "30억원 미만 10억원 이상"),
    (None, "72.995", "추정가격 30억원 이상"),
)

# (rule_id, 규칙 source 에 있어야 하는 원문 추출 경로 조각)
GENERAL_SOURCE_TOKENS = (
    (INCHEON_GENERAL_ID, "EXT/qual_raw/3.txt"),
    (JEJU_GENERAL_ID, "EXT/qual_raw/6.txt"),
    (GANGWON_GENERAL_ID, "EXT/qual_raw/1.txt"),
    (GN_GENERAL_ID, "EXT/qual_raw/5.txt"),
)


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(
    *,
    region_code: str,
    region_name: str,
    method: str,
    estimated_price: str | None = None,
    announcement_rate: str | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        sucsfbid_lwlt_rate=announcement_rate,
        contract_regime="LOCAL",
        bid_ntce_dt="2026-08-01",
        region_code=region_code,
        region_name=region_name,
        raw_data={"sucsfbidMthdNm": method},
        estimated_price=estimated_price,
    )


# --------------------------------------------------------------------------- #
# 1. 규칙 객체의 구간 값과 원문 근거
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_id", GENERAL_RULE_IDS)
def test_general_rules_have_five_source_bands(rule_id: str) -> None:
    """네 GENERAL 규칙은 10억원 이상을 30억원 경계로 나눈 5구간이고 값은 원문 역산값이다."""
    rule = _rule(rule_id)
    assert rule.price_bands is not None
    assert len(rule.price_bands) == len(GENERAL_BANDS)
    for band, (upper, rate, label) in zip(rule.price_bands, GENERAL_BANDS, strict=True):
        assert band.upper_bound == (Decimal(upper) if upper is not None else None), (rule_id, upper)
        assert band.lwlt_rate == Decimal(rate), (rule_id, upper)
        assert band.label == label, (rule_id, upper)
    # 분할한 두 구간의 B·k·기준비율은 분할 전 10억원 이상 값(B 30·k 1·0.88) 그대로다.
    for band in rule.price_bands[-2:]:
        assert band.max_price_score == Decimal("30"), (rule_id, band.label)
        assert band.multiplier == Decimal("1"), (rule_id, band.label)
        assert band.base_rate == Decimal("0.88"), (rule_id, band.label)
    # 규칙 대표값은 분할 전과 같은 87.995 로 두어 구간 하한율 없는 경로가 바뀌지 않는다.
    assert rule.lwlt_rate == Decimal("87.995"), rule_id


@pytest.mark.parametrize(("rule_id", "source_token"), GENERAL_SOURCE_TOKENS)
def test_general_band_sources_cite_original(rule_id: str, source_token: str) -> None:
    """각 구간의 source 는 공고 실측이 아니라 원문 추출 위치를 가리킨다."""
    rule = _rule(rule_id)
    for band in rule.price_bands or ():
        assert source_token in (band.source or ""), (rule_id, band.label)
        assert "공고 실측" not in (band.source or ""), (rule_id, band.label)


def test_gb_general_bands_follow_five_eok_two_rows() -> None:
    """경북 별표 4 는 5억원 기준 두 행이므로 5억원 미만 87.745%, 5억원 이상 86.745% 다."""
    rule = _rule(GB_GENERAL_ID)
    assert rule.price_bands is not None
    assert [band.lwlt_rate for band in rule.price_bands] == [
        Decimal("87.745"),
        Decimal("87.745"),
        Decimal("86.745"),
        Decimal("86.745"),
    ]
    assert [band.upper_bound for band in rule.price_bands] == [
        Decimal("200000000"),
        Decimal("500000000"),
        Decimal("1000000000"),
        None,
    ]
    # 5억원 미만 행은 B 70·k 20, 5억원 이상 행은 B 50·k 4 다.
    assert [(band.max_price_score, band.multiplier) for band in rule.price_bands] == [
        (Decimal("70"), Decimal("20")),
        (Decimal("70"), Decimal("20")),
        (Decimal("50"), Decimal("4")),
        (Decimal("50"), Decimal("4")),
    ]
    for band in rule.price_bands:
        assert "EXT/gb/gb_byp004.tbl.txt" in (band.source or ""), band.label


@pytest.mark.parametrize("rule_id", list(SIMPLE_LABOR_RULE_IDS))
def test_simple_labor_rule_rate_is_87745(rule_id: str) -> None:
    """단순노무 규칙은 구간 하한율 없이 규칙 대표값 87.745% 를 전 구간에 쓴다."""
    rule = _rule(rule_id)
    assert rule.lwlt_rate == Decimal("87.745")
    assert all(band.lwlt_rate is None for band in rule.price_bands or ())


# --------------------------------------------------------------------------- #
# 2. 구간 선택과 경계값 (공고 하한율 없음)
# --------------------------------------------------------------------------- #

# 경계: 9.99억·10억·29.99억·30억. 경계값은 이상 쪽 구간에 속한다.
GENERAL_BOUNDARY_CASES = (
    ("999999999", "85.495", "10억원 미만 5억원 이상"),
    ("1000000000", "77.995", "30억원 미만 10억원 이상"),
    ("1500000000", "77.995", "30억원 미만 10억원 이상"),
    ("2999999999", "77.995", "30억원 미만 10억원 이상"),
    ("3000000000", "72.995", "추정가격 30억원 이상"),
    ("4000000000", "72.995", "추정가격 30억원 이상"),
)


@pytest.mark.parametrize("rule_id", GENERAL_RULE_IDS)
@pytest.mark.parametrize(("price", "expected_rate", "band_label"), GENERAL_BOUNDARY_CASES)
def test_general_band_boundary_selects_upper_band(
    rule_id: str, price: str, expected_rate: str, band_label: str
) -> None:
    """경계값(10억·30억)은 이상 쪽 구간에 속하고, 추정가격이 그 구간 하한율을 고른다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate), (rule_id, price)
    assert result.rate_source == "RULE_DEFAULT"
    assert any(
        f"별표 구간 하한율({expected_rate}%" in warning and band_label in warning
        for warning in result.warnings
    ), (rule_id, price)


GB_BOUNDARY_CASES = (
    ("199999999", "87.745"),
    ("499999999", "87.745"),
    ("500000000", "86.745"),
    ("1000000000", "86.745"),
    ("100000000000", "86.745"),
)


@pytest.mark.parametrize(("price", "expected_rate"), GB_BOUNDARY_CASES)
def test_gb_band_boundary_follows_five_eok(price: str, expected_rate: str) -> None:
    """경북은 5억원 경계에서만 값이 갈리고, 5억원 경계값은 이상 쪽 구간에 속한다."""
    result = _resolve(
        region_code="47",
        region_name="경상북도",
        method=GENERAL_METHOD,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == GB_GENERAL_ID
    assert result.effective_lwlt_rate == Decimal(expected_rate), price


SIMPLE_LABOR_PRICES = ("150000000", "300000000", "700000000", "1500000000", "4000000000")


@pytest.mark.parametrize("rule_id", list(SIMPLE_LABOR_RULE_IDS))
@pytest.mark.parametrize("price", SIMPLE_LABOR_PRICES)
def test_simple_labor_rate_is_uniform(rule_id: str, price: str) -> None:
    """인천·제주·강원 단순노무는 금액과 무관하게 전 구간 87.745% 다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=SIMPLE_LABOR_METHOD,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal("87.745"), (rule_id, price)
    assert result.rate_source == "RULE_DEFAULT"


@pytest.mark.parametrize("rule_id", GENERAL_RULE_IDS)
def test_general_unknown_price_is_not_guessed(rule_id: str) -> None:
    """구간 하한율이 서로 다른데 추정가격이 없으면 대표값으로 추측하지 않는다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate is None
    assert any("추정가격을 입력해야" in warning for warning in result.warnings)


@pytest.mark.parametrize("rule_id", GENERAL_RULE_IDS)
def test_announcement_rate_wins_over_band_rate(rule_id: str) -> None:
    """공고 하한율이 있으면 구간 하한율보다 우선한다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price="1500000000",
        announcement_rate="89.745",
    )
    assert result.rule is not None
    assert result.effective_lwlt_rate == Decimal("89.745")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("구간 하한율" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 3. 평탄 구간: 30억원 미만 키만 있고 30억원 이상은 평탄 없음
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_id", GENERAL_RULE_IDS)
def test_flat_zone_under_30_only(rule_id: str) -> None:
    """10억~30억 구간에는 원문 단서 평탄(98%→20점)이 있고 30억원 이상에는 평탄이 없다."""
    under_30 = flat_zone_for(rule_id, "3000000000")
    over_30 = flat_zone_for(rule_id, None)
    assert under_30 is not None, rule_id
    assert under_30.flat_ratio == Decimal("0.98")
    assert under_30.flat_score == Decimal("20")
    assert over_30 is None, rule_id


# --------------------------------------------------------------------------- #
# 4. 실제 평가 API 끝단 (mock 없음, 예측 모델만 대역)
# --------------------------------------------------------------------------- #


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


API_INSTITUTION_CODE = "7000010"


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
    institution_code: str,
    institution_name: str,
    method: str,
    presmpt_prce: int,
) -> BidAnnouncement:
    """공고 하한율 키를 넣지 않아 구간 하한율 경로를 탄다."""
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="LOCAL 10억/30억 하한율 끝단 시험 공고",
        bid_ntce_no="EVAL-LOCAL-10EOK-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{institution_name} 본청",
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


def _analyze(client, bid_id: int, bid_amount: int) -> dict:
    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": bid_amount,
            "qualification_input": {"disqualification": False, "manual_non_price_score": 40.0},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# (지역명, 낙찰방법명, 규칙 ID, 추정가격, 기대 하한율). 최저투찰금액 = 추정가격 x 하한율.
API_CASES = (
    ("인천광역시", GENERAL_METHOD, INCHEON_GENERAL_ID, 1_500_000_000, 77.995, 1_169_925_000),
    ("제주특별자치도", GENERAL_METHOD, JEJU_GENERAL_ID, 2_500_000_000, 77.995, 1_949_875_000),
    ("강원특별자치도", GENERAL_METHOD, GANGWON_GENERAL_ID, 3_000_000_000, 72.995, 2_189_850_000),
    ("경상남도", GENERAL_METHOD, GN_GENERAL_ID, 2_000_000_000, 77.995, 1_559_900_000),
    ("인천광역시", SIMPLE_LABOR_METHOD, INCHEON_SIMPLE_ID, 1_500_000_000, 87.745, 1_316_175_000),
    ("경상북도", GENERAL_METHOD, GB_GENERAL_ID, 700_000_000, 86.745, 607_215_000),
    ("경상북도", GENERAL_METHOD, GB_GENERAL_ID, 300_000_000, 87.745, 263_235_000),
)


@pytest.mark.parametrize(
    (
        "region_name",
        "method",
        "expected_rule_id",
        "presmpt_prce",
        "expected_rate",
        "expected_min_bid",
    ),
    API_CASES,
)
def test_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    method: str,
    expected_rule_id: str,
    presmpt_prce: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """공고 하한율 없는 공고가 구간 하한율로 최저투찰금액을 실제 코드로 계산한다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=method,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, presmpt_prce // 2)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == expected_rule_id
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    ), (expected_rule_id, presmpt_prce)
