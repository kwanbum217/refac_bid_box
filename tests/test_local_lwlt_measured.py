"""LOCAL GENERAL 규칙 6개의 구간 하한율 시험 (서울 공고 실측 + 5곳 원문 산식 역산).

정본:
 - docs/analysis/local_10eok_lwlt_derivation_20261006.md (인천·제주·강원·경남·경북 원문 역산)
 - docs/analysis/local_lwlt_announcement_measure_20261005.md 6.1절 (서울 공고 실측 최빈값)
 - .orca/capsules/task_b1c4b69f0e6f/capsule.yaml
 - src/app/services/evaluation_rules.py 의 PriceBand.lwlt_rate

2026-10-06 부로 서울 GENERAL 만 10억원 미만 3개 구간에 공고 실측 최빈값을 쓰고, 인천·제주·
강원·경남은 원문 별표 산식과 본문 통과점수로 역산한 5구간(87.745/86.745/85.495/77.995/
72.995), 경북 04 는 원문 별표 4 두 행(5억원 미만 87.745%, 5억원 이상 86.745%)을 씁니다.
평가 API 끝단은 mock 없이 TestClient 로 호출하고, 이 워크트리에 모델 파일이 없어 예측 모델만
시험 대역으로 대체합니다. 규칙 판별·구간 하한율·최저 투찰금액은 실제 코드다.
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
from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
)

ANALYZE_URL = "/api/v1/evaluations/analyze"

INCHEON_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
JEJU_ID = "SERVC_LOCAL_JEJU_20240101_ATTACH_01"
GANGWON_ID = "SERVC_LOCAL_GANGWON_20230611_ATTACH_01"
GB_GENERAL_ID = "SERVC_LOCAL_GB_20260108_ATTACH_04"
GN_GENERAL_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"
SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"

TARGET_RULE_IDS = (
    INCHEON_ID,
    JEJU_ID,
    GANGWON_ID,
    GB_GENERAL_ID,
    GN_GENERAL_ID,
    SEOUL_GENERAL_ID,
)

REGION_BY_RULE: dict[str, tuple[str, str]] = {
    INCHEON_ID: ("28", "인천광역시"),
    JEJU_ID: ("50", "제주특별자치도"),
    GANGWON_ID: ("51", "강원특별자치도"),
    GB_GENERAL_ID: ("47", "경상북도"),
    GN_GENERAL_ID: ("48", "경상남도"),
    SEOUL_GENERAL_ID: ("11", "서울특별시"),
}

GENERAL_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"
SIMPLE_LABOR_METHOD = "단순노무용역 적격심사 추정가격 5억원 미만"
SW_METHOD = "소프트웨어용역 적격심사 추정가격 5억원 미만"
INSURANCE_METHOD = "보험용역 적격심사 추정가격 5억원 미만"

# (상한, 하한율, 구간 라벨). 10억원 이상을 30억원 경계로 나눈 5구간.
FIVE_BANDS = (
    ("200000000", "87.745", "추정가격 2억원 미만"),
    ("500000000", "86.745", "5억원 미만 2억원 이상"),
    ("1000000000", "85.495", "10억원 미만 5억원 이상"),
    ("3000000000", "77.995", "30억원 미만 10억원 이상"),
    (None, "72.995", "추정가격 30억원 이상"),
)
# 경북 별표 4 는 5억원 기준 두 행만 인쇄해 각 하위 구간에 두 값을 적용한다.
GB_BANDS = (
    ("200000000", "87.745", "추정가격 2억원 미만"),
    ("500000000", "87.745", "5억원 미만 2억원 이상"),
    ("1000000000", "86.745", "10억원 미만 5억원 이상"),
    (None, "86.745", "추정가격 10억원 이상"),
)

BANDS_BY_RULE: dict[str, tuple[tuple[str | None, str, str], ...]] = {
    INCHEON_ID: FIVE_BANDS,
    JEJU_ID: FIVE_BANDS,
    GANGWON_ID: FIVE_BANDS,
    GN_GENERAL_ID: FIVE_BANDS,
    SEOUL_GENERAL_ID: FIVE_BANDS,
    GB_GENERAL_ID: GB_BANDS,
}

# (rule_id, 규칙 source 에 있어야 하는 원문 추출 경로 조각)
SOURCE_TOKEN_BY_RULE = {
    INCHEON_ID: "EXT/qual_raw/3.txt",
    JEJU_ID: "EXT/qual_raw/6.txt",
    GANGWON_ID: "EXT/qual_raw/1.txt",
    GN_GENERAL_ID: "EXT/qual_raw/5.txt",
    GB_GENERAL_ID: "EXT/gb/gb_byp004.tbl.txt",
}
MEASURED_SOURCE_DOC = "docs/analysis/local_lwlt_announcement_measure_20261005.md"


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
# 1. 구간 값과 근거 (서울 공고 실측 / 5곳 원문 역산)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_target_rule_band_values(rule_id: str) -> None:
    """대상 규칙의 구간 상한·하한율·라벨이 확정값과 순서대로 같다."""
    rule = _rule(rule_id)
    bands = rule.price_bands or ()
    expected_bands = BANDS_BY_RULE[rule_id]
    assert len(bands) == len(expected_bands), rule_id
    for band, (upper, rate, label) in zip(bands, expected_bands, strict=True):
        assert band.upper_bound == (Decimal(upper) if upper is not None else None), (rule_id, upper)
        assert band.lwlt_rate == Decimal(rate), (rule_id, upper)
        assert band.label == label, (rule_id, upper)
    # 규칙 대표값은 분할 전과 같은 87.995 로 두어 구간 하한율 없는 경로가 바뀌지 않는다.
    assert rule.lwlt_rate == Decimal("87.995"), rule_id


@pytest.mark.parametrize(("rule_id", "source_token"), tuple(SOURCE_TOKEN_BY_RULE.items()))
def test_original_band_sources_cite_ext(rule_id: str, source_token: str) -> None:
    """원문 역산 5곳은 구간 source 가 공고 실측이 아니라 원문 추출 위치를 가리킨다."""
    rule = _rule(rule_id)
    for band in rule.price_bands or ():
        assert source_token in (band.source or ""), (rule_id, band.label)
        assert "공고 실측" not in (band.source or ""), (rule_id, band.label)


def test_seoul_bands_stay_measured() -> None:
    """서울 01 은 10억원 이상을 30억원 경계로 나눈 공고 실측 5구간이다."""
    rule = _rule(SEOUL_GENERAL_ID)
    bands = rule.price_bands or ()
    for band, (upper, rate, label) in zip(bands, FIVE_BANDS, strict=True):
        assert band.upper_bound == (Decimal(upper) if upper is not None else None), upper
        assert band.lwlt_rate == Decimal(rate), upper
        assert band.label == label, upper
    # 실측 하한율을 붙인 구간은 공고 실측임을 함께 밝힌다.
    for band in bands[:3]:
        assert MEASURED_SOURCE_DOC in (band.source or ""), band.label
        assert "원문 미확인" in (band.source or ""), band.label


# --------------------------------------------------------------------------- #
# 2. 구간 선택과 경계값 (공고 하한율 없음)
# --------------------------------------------------------------------------- #

# (rule_id, 추정가격, 기대 구간 인덱스). 경계값(10억·30억)은 이상 쪽 구간에 속한다.
BOUNDARY_CASES = (
    (INCHEON_ID, "150000000", 0),
    (INCHEON_ID, "200000000", 1),
    (INCHEON_ID, "500000000", 2),
    (INCHEON_ID, "999999999", 2),
    (INCHEON_ID, "1000000000", 3),
    (INCHEON_ID, "2999999999", 3),
    (INCHEON_ID, "3000000000", 4),
    (SEOUL_GENERAL_ID, "1500000000", 3),
    (SEOUL_GENERAL_ID, "4000000000", 4),
    (GB_GENERAL_ID, "199999999", 0),
    (GB_GENERAL_ID, "499999999", 1),
    (GB_GENERAL_ID, "500000000", 2),
    (GB_GENERAL_ID, "4000000000", 3),
)


@pytest.mark.parametrize(("rule_id", "price", "band_index"), BOUNDARY_CASES)
def test_band_selected_by_price(rule_id: str, price: str, band_index: int) -> None:
    """추정가격이 원문 구간 표기대로 구간을 고르고, 그 구간 하한율을 쓴다."""
    code, name = REGION_BY_RULE[rule_id]
    expected_rate = BANDS_BY_RULE[rule_id][band_index][1]
    expected_label = BANDS_BY_RULE[rule_id][band_index][2]
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
        f"별표 구간 하한율({expected_rate}%" in warning and expected_label in warning
        for warning in result.warnings
    ), (rule_id, price)


# (rule_id, 추정가격, 기대 하한율) — 10억원 이상 구간.
TOP_BAND_CASES = (
    (INCHEON_ID, "1500000000", "77.995"),
    (INCHEON_ID, "3000000000", "72.995"),
    (JEJU_ID, "2500000000", "77.995"),
    (GANGWON_ID, "4000000000", "72.995"),
    (GN_GENERAL_ID, "2000000000", "77.995"),
    (GB_GENERAL_ID, "3000000000", "86.745"),
    (SEOUL_GENERAL_ID, "1500000000", "77.995"),
)


@pytest.mark.parametrize(("rule_id", "price", "expected_rate"), TOP_BAND_CASES)
def test_top_band_rate_selected_by_price(rule_id: str, price: str, expected_rate: str) -> None:
    """10억원 이상 구간(경북은 5억원 이상)이 원문 역산·실측 하한율을 쓴다."""
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


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_unknown_price_is_not_guessed(rule_id: str) -> None:
    """구간별 하한율이 서로 다른데 추정가격이 없으면 대표값으로 추측하지 않는다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert result.effective_lwlt_rate is None, rule_id
    assert result.rate_source is None
    assert any("추정가격을 입력해야" in warning for warning in result.warnings)


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_announcement_rate_wins_over_band(rule_id: str) -> None:
    """공고 하한율이 있으면 구간 하한율보다 우선한다(종전 동작)."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price="150000000",
        announcement_rate="89.745",
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal("89.745")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("구간 하한율" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 3. 다른 규칙 불변 (공유 헬퍼 누수 없음)
# --------------------------------------------------------------------------- #

SEOUL_SIMPLE_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
GB_SW_ID = "SERVC_LOCAL_GB_20260108_ATTACH_02"
GG_INSURANCE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_5"

# (rule_id, 지역코드, 지역명, 낙찰방법명, 규칙 대표값). 모두 구간 하한율이 없어야 한다.
# 서울 단순노무는 2026-10-07 원문 산식 대조로 대표값이 87.745% 로 정정됐다(구간 하한율은 없음).
UNCHANGED_CASES = (
    (SEOUL_SIMPLE_ID, "11", "서울특별시", SIMPLE_LABOR_METHOD, "87.745"),
    (GB_SW_ID, "47", "경상북도", SW_METHOD, "87.995"),
    (GG_INSURANCE_ID, "41", "경기도", INSURANCE_METHOD, "47.995"),
)


@pytest.mark.parametrize(("rule_id", "code", "name", "method", "expected_rate"), UNCHANGED_CASES)
def test_unrelated_rules_keep_rule_default(
    rule_id: str, code: str, name: str, method: str, expected_rate: str
) -> None:
    """같은 구간 구조를 쓰는 다른 규칙은 구간 하한율이 생기지 않고 대표값 경로 그대로다."""
    rule = _rule(rule_id)
    bands = rule.price_bands or ()
    assert bands, rule_id
    assert all(band.lwlt_rate is None for band in bands), rule_id
    result = _resolve(
        region_code=code,
        region_name=name,
        method=method,
        estimated_price="300000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert result.rate_source == "RULE_DEFAULT"
    assert any("별표 기본값" in warning for warning in result.warnings)
    assert not any("구간 하한율" in warning for warning in result.warnings)


def test_national_facility_rule_unchanged() -> None:
    """조달청 규칙은 이번 변경 밖이라 대표값 89.995% 그대로다."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm="적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        bid_ntce_dt="2026-08-01",
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"
    assert result.effective_lwlt_rate == Decimal("89.995")
    assert result.rate_source == "RULE_DEFAULT"


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


API_INSTITUTION_CODE = "7000009"


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
    presmpt_prce: int | None,
) -> BidAnnouncement:
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
        bid_ntce_nm="LOCAL 구간 하한율 끝단 시험 공고",
        bid_ntce_no="EVAL-MEASURED-LWLT-001",
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


# (지역명, 규칙 ID, 추정가격, 기대 하한율, 기대 최저투찰금액). 최저투찰금액 = 추정가격 x 하한율.
API_CASES = (
    ("인천광역시", INCHEON_ID, 150_000_000, 87.745, 131_617_500),
    ("인천광역시", INCHEON_ID, 1_500_000_000, 77.995, 1_169_925_000),
    ("제주특별자치도", JEJU_ID, 300_000_000, 86.745, 260_235_000),
    ("강원특별자치도", GANGWON_ID, 3_000_000_000, 72.995, 2_189_850_000),
    ("경상남도", GN_GENERAL_ID, 700_000_000, 85.495, 598_465_000),
    ("경상남도", GN_GENERAL_ID, 2_000_000_000, 77.995, 1_559_900_000),
    ("경상북도", GB_GENERAL_ID, 300_000_000, 87.745, 263_235_000),
    ("경상북도", GB_GENERAL_ID, 700_000_000, 86.745, 607_215_000),
    ("서울특별시", SEOUL_GENERAL_ID, 1_500_000_000, 77.995, 1_169_925_000),
)


@pytest.mark.parametrize(
    ("region_name", "expected_rule_id", "presmpt_prce", "expected_rate", "expected_min_bid"),
    API_CASES,
)
def test_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    expected_rule_id: str,
    presmpt_prce: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """대상 규칙이 실제 평가 API 에서 구간 하한율과 최저투찰금액을 그대로 쓴다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=GENERAL_METHOD,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, expected_min_bid)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == expected_rule_id
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    ), (expected_rule_id, presmpt_prce)


UNKNOWN_PRICE_API_CASES = tuple(
    (REGION_BY_RULE[rule_id][1], rule_id) for rule_id in TARGET_RULE_IDS
)


@pytest.mark.parametrize(("region_name", "expected_rule_id"), UNKNOWN_PRICE_API_CASES)
def test_unknown_price_blocks_through_analyze_api(
    client, isolated_db, as_user, region_name: str, expected_rule_id: str
) -> None:
    """추정가격이 없는 공고는 규칙까지 확정되지만 하한율 미확정으로 계산이 막힌다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=GENERAL_METHOD,
        presmpt_prce=None,
    )

    payload = _analyze(client, bid.id, 130_000_000)

    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert "LWLT_RATE_UNRESOLVED" in payload["blocked_reason"]
    assert payload["rule_id"] == expected_rule_id
    assert "추정가격을 입력" in payload["blocked_reason"]
