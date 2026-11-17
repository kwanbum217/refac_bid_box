"""조달청 기술용역 적격심사 별표1 배점표 반영 계약 시험 (2026-11-17).

정본:
 - .orca/capsules/task_tech_score_table_20261117/capsule.yaml
 - data/reference/pps_tech_lwlt_pre_20260526.yaml

시험 항목:
 (a) 두 규칙의 네 구간 B·k·T·기준비율이 YAML 과 같다.
 (b) 10억·5억·고시금액 경계값이 원문 구간(이상·미만)대로 들어간다.
 (c) 2026-05-26 전후 공고가 각각 88·90 기준비율을 쓴다.
 (d) 기술용역 공고가 MISSING_SCORE_TABLE 로 막히지 않고 점수·최저가·최상가가 계산된다.
 (e) 2022-11-01 이전 공고는 종전처럼 규칙 판별 단계에서 막힌다.
 (f) 낙찰하한율은 여전히 공고 sucsfbidLwltRate 다.

실물 모델·Redis·MySQL 은 호출하지 않는다. API 시험은 conftest 의 isolated_db(SQLite)
위에서 돌고, predict_price_api 는 대역으로 덮는다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import _score_table, require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.evaluations import QualificationInput
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_recommendation import compute_price_bounds
from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)
from src.ml.notice_amount import notice_amount_for_year

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_YAML = PROJECT_ROOT / "data/reference/pps_tech_lwlt_pre_20260526.yaml"
CURRENT_RULE_ID = "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
PRE_RULE_ID = "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526"
ANALYZE_URL = "/api/v1/evaluations/analyze"
RECOMMEND_URL = "/api/v1/evaluations/recommend"
TECH_METHOD = "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준"


def _reference() -> dict:
    return yaml.safe_load(REFERENCE_YAML.read_text(encoding="utf-8"))


def _revision(notice_key: str) -> dict:
    return next(
        revision for revision in _reference()["revisions"] if revision["notice_key"] == notice_key
    )


def _yaml_bands(notice_key: str) -> dict[int, dict]:
    revision = _revision(notice_key)
    return {int(band["source_band"]): band for band in revision["attachments"][0]["bands"]}


def _price_band_by_source_band(rule, source_band: int):
    # 선언 구간은 추정가격 오름차순(4 -> 1)이라 원문 구간 번호를 뒤집어 찾는다.
    return rule.price_bands[4 - source_band]


def _tech_raw_data(
    *,
    announced: str | None,
    lwlt_rate: str = "87.495",
    estimated_price: int = 600_000_000,
) -> dict:
    raw_data = {
        "srvceDivNm": "기술용역",
        "sucsfbidMthdNm": TECH_METHOD,
        "sucsfbidLwltRate": lwlt_rate,
        "prearngPrceDcsnMthdNm": "복수예가",
    }
    if announced is not None:
        raw_data["bidNtceDt"] = announced
    return raw_data


# --------------------------------------------------------------------------- #
# (a) YAML 값 대조
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("notice_key", ["2025-6352", "2026-654"])
def test_pre_rule_bands_match_reference_yaml(notice_key: str) -> None:
    """개정 전 두 판의 네 구간 B·k·T·기준비율이 YAML 과 같다."""
    bands = _yaml_bands(notice_key)
    rule = SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526

    assert len(rule.price_bands) == 4
    assert len(rule.threshold_bands) == 2
    for source_band in (1, 2, 3, 4):
        yaml_band = bands[source_band]
        tier = yaml_band["score_tiers"][0]
        price_band = _price_band_by_source_band(rule, source_band)
        assert price_band.max_price_score == Decimal(str(yaml_band["B"]))
        assert price_band.multiplier == Decimal(str(tier["k"]))
        assert price_band.base_rate == Decimal(str(tier["base_ratio"])) / Decimal("100")
        assert price_band.label == yaml_band["source_label"]
        threshold = 92 if source_band == 1 else 95
        assert tier["pass_score"] == threshold


def test_current_rule_bands_match_reference_yaml() -> None:
    """현행 규칙의 B·k·T 는 개정 전과 같고 기준비율만 90 이다."""
    data = _reference()
    boundary = data["boundary_reference"]
    pre_bands = _yaml_bands("2025-6352")
    rule = SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT

    assert {band.base_rate * Decimal("100") for band in rule.price_bands} == {
        Decimal(value) for value in boundary["base_ratio_row"]
    }
    for source_band in (1, 2, 3, 4):
        yaml_band = pre_bands[source_band]
        tier = yaml_band["score_tiers"][0]
        price_band = _price_band_by_source_band(rule, source_band)
        assert price_band.max_price_score == Decimal(str(yaml_band["B"]))
        assert price_band.multiplier == Decimal(str(tier["k"]))
        assert price_band.label == yaml_band["source_label"]
    assert [band.pass_threshold for band in rule.threshold_bands] == [
        Decimal("95"),
        Decimal("92"),
    ]
    assert "평점계수·배점한도·통과점수는 그대로다" in boundary["delta_from_pre"]


# --------------------------------------------------------------------------- #
# (b) 경계값
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rule", "announced", "notice_amount", "price", "expected_b", "expected_k", "expected_t"),
    [
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            1_000_000_000,
            "30",
            "1",
            "92",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            999_999_999,
            "50",
            "2",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            500_000_000,
            "50",
            "2",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            499_999_999,
            "70",
            "4",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            230_000_000,
            "70",
            "4",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
            "2026-06-01",
            230_000_000,
            229_999_999,
            "90",
            "20",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2022-12-01",
            210_000_000,
            210_000_000,
            "70",
            "4",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2022-12-01",
            210_000_000,
            209_999_999,
            "90",
            "20",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2023-06-01",
            220_000_000,
            220_000_000,
            "70",
            "4",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2023-06-01",
            220_000_000,
            219_999_999,
            "90",
            "20",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2025-06-01",
            230_000_000,
            230_000_000,
            "70",
            "4",
            "95",
        ),
        (
            SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
            "2025-06-01",
            230_000_000,
            229_999_999,
            "90",
            "20",
            "95",
        ),
    ],
)
def test_band_boundaries_follow_printed_lower_inclusive_upper_exclusive(
    rule,
    announced: str,
    notice_amount: int,
    price: int,
    expected_b: str,
    expected_k: str,
    expected_t: str,
) -> None:
    """10억·5억·고시금액 경계값이 원문 구간 표기대로 들어간다."""
    assert notice_amount_for_year(int(announced[:4])) == notice_amount
    resolution = resolve_score_params(rule, Decimal(price), announced, None)

    assert resolution.max_price_score == Decimal(expected_b)
    assert resolution.multiplier == Decimal(expected_k)
    assert resolution.pass_threshold == Decimal(expected_t)
    assert resolution.warnings == ()


def test_pre_rule_notice_boundary_uses_announcement_year_not_fixed_2026_value() -> None:
    """개정 전 규칙의 고시금액 경계는 공고일 연도 값이다."""
    rule = SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526

    for announced in ("2022-12-01", "2023-06-01", "2025-06-01"):
        notice_amount = notice_amount_for_year(int(announced[:4]))
        below = resolve_score_params(rule, Decimal(notice_amount - 1), announced, None)
        at = resolve_score_params(rule, Decimal(notice_amount), announced, None)
        assert below.max_price_score == Decimal("90")
        assert at.max_price_score == Decimal("70")


# --------------------------------------------------------------------------- #
# (c) 2026-05-26 판 경계
# --------------------------------------------------------------------------- #


def test_regime_boundary_switches_base_rate() -> None:
    """2026-05-26 전후 공고가 각각 88·90 기준비율을 쓴다."""
    pre_result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2026-05-25 10:00:00")
    )
    current_result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2026-05-26 09:00:00")
    )

    assert pre_result.is_blocked is False
    assert current_result.is_blocked is False
    assert pre_result.rule is not None
    assert pre_result.rule.rule_id == PRE_RULE_ID
    assert current_result.rule is not None
    assert current_result.rule.rule_id == CURRENT_RULE_ID
    assert pre_result.rule.base_rate == Decimal("0.88")
    assert current_result.rule.base_rate == Decimal("0.90")

    pre_resolution = resolve_score_params(pre_result.rule, Decimal("600000000"), "2026-05-25", None)
    current_resolution = resolve_score_params(
        current_result.rule, Decimal("600000000"), "2026-05-26", None
    )
    assert pre_resolution.base_rate == Decimal("0.88")
    assert current_resolution.base_rate == Decimal("0.90")


# --------------------------------------------------------------------------- #
# (d) MISSING_SCORE_TABLE 해소와 최저가·최상가
# --------------------------------------------------------------------------- #


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


def _create_tech_bid(db, *, notice_no: str = "EVAL-TECH-001") -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="기술용역 적격심사 테스트 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=600_000_000,
        presmpt_prce=600_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=_tech_raw_data(announced="2026-11-01 10:00:00"),
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def test_score_table_resolves_without_user_input() -> None:
    """규칙 선언만으로 B·k·T 가 채워져 MISSING_SCORE_TABLE 이 나지 않는다."""
    rule_result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2026-11-01 10:00:00")
    )
    assert rule_result.rule is not None
    bid = BidAnnouncement(
        bid_ntce_nm="기술용역 적격심사 테스트 공고",
        bid_ntce_no="EVAL-TECH-UNIT-001",
        bid_ntce_ord="000",
        base_amount=600_000_000,
        presmpt_prce=600_000_000,
        bid_ntce_dt=utcnow(),
        category="Servc",
        raw_data=_tech_raw_data(announced="2026-11-01 10:00:00"),
    )

    table, missing, overridden, resolution = _score_table(
        QualificationInput(), rule_result.rule, bid
    )

    assert table is not None
    assert missing == []
    assert overridden == []
    assert table.max_price_score == Decimal("50")
    assert table.multiplier == Decimal("2")
    assert table.pass_threshold == Decimal("95")
    assert table.base_rate == Decimal("0.90")
    assert resolution.price_band_label == "추정가격이 10억원 미만 5억원 이상인 용역"


def test_tech_price_bounds_are_computed_with_declared_table() -> None:
    """선언 배점표로 기술용역 최저가·최상가를 계산한다."""
    bounds = compute_price_bounds(
        base_amount=Decimal("600000000"),
        rate_low=Decimal("0.98"),
        rate_high=Decimal("1.02"),
        pass_threshold=Decimal("95"),
        non_price_score=Decimal("50"),
        base_rate=Decimal("0.90"),
        max_price_score=Decimal("50"),
        multiplier=Decimal("2"),
        announcement_lwlt_rate=Decimal("87.495"),
    )

    assert bounds.status == "ok", bounds.reasons
    assert bounds.min_bid_amount is not None
    assert bounds.max_bid_amount is not None
    assert bounds.min_bid_amount <= bounds.max_bid_amount


def test_tech_analyze_is_not_blocked_by_missing_score_table(client, isolated_db, as_user) -> None:
    """공고 상세 분석이 기술용역 배점표를 스스로 확정해 막히지 않는다."""
    as_user(10)
    bid = _create_tech_bid(isolated_db)

    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": 540_000_000,
            "qualification_input": {"disqualification": False},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success", body.get("blocked_reason")
    assert body["blocked"] is False
    assert "MISSING_SCORE_TABLE" not in (body.get("blocked_reason") or "")
    assert body["rule_id"] == CURRENT_RULE_ID

    table = body["score_table"]
    assert table["max_price_score"] == "50"
    assert table["multiplier"] == "2"
    assert table["pass_threshold"] == "95"  # noqa: S105
    assert body["base_rate"] == 90.0
    assert table["price_band_label"] == "추정가격이 10억원 미만 5억원 이상인 용역"

    scenarios = {row["scenario_name"]: row for row in body["scenario_results"]}
    assert set(scenarios) == {"하단", "기준", "상단"}
    for scenario in scenarios.values():
        # 최저가·최상가 시나리오 모두 가격점수가 계산된다.
        assert scenario["price_score"] is not None
        assert scenario["total_score"] is not None


def test_tech_recommend_is_not_blocked_by_missing_score_table(client, isolated_db, as_user) -> None:
    """투찰가 추천도 배점표 미확인으로 막히지 않고 선언값을 응답한다."""
    as_user(10)
    bid = _create_tech_bid(isolated_db, notice_no="EVAL-TECH-RECOMMEND-001")

    response = client.post(RECOMMEND_URL, json={"bid_id": bid.id, "overrides": {}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rule_id"] == CURRENT_RULE_ID
    assert "MISSING_SCORE_TABLE" not in (body.get("blocked_reason") or "")
    assert body["score_table"]["max_price_score"] == "50"
    assert body["score_table"]["multiplier"] == "2"
    assert body["score_table"]["pass_threshold"] == "95"  # noqa: S105
    assert body["price_bounds"] is not None


# --------------------------------------------------------------------------- #
# (e) 2022-11-01 이전 공고
# --------------------------------------------------------------------------- #


def test_announcement_before_2022_11_01_stays_blocked_at_rule_resolution() -> None:
    """2022-11-01 이전 공고는 종전처럼 규칙 판별 단계에서 막힌다."""
    result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2022-10-31 10:00:00")
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
    assert result.rule is not None
    assert result.rule.rule_id == PRE_RULE_ID
    assert result.effective_lwlt_rate is None


def test_announcement_on_2022_11_01_uses_pre_rule_bands() -> None:
    """적용 첫날인 2022-11-01 공고는 개정 전 규칙으로 계산한다."""
    result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2022-11-01 09:00:00")
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PRE_RULE_ID
    resolution = resolve_score_params(result.rule, Decimal("600000000"), "2022-11-01", None)
    assert resolution.max_price_score == Decimal("50")
    assert resolution.multiplier == Decimal("2")
    assert resolution.base_rate == Decimal("0.88")


# --------------------------------------------------------------------------- #
# (f) 낙찰하한율 출처
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rate", ["79.995", "83.123", "87.495"])
def test_tech_lwlt_still_comes_from_announcement_rate(rate: str) -> None:
    """낙찰하한율은 별표 파생값이 아니라 공고 sucsfbidLwltRate 다."""
    result = resolve_evaluation_rule_from_raw_data(
        "Servc", _tech_raw_data(announced="2026-11-01 10:00:00", lwlt_rate=rate)
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.effective_lwlt_rate == Decimal(rate)
    assert result.rate_source == "ANNOUNCEMENT"
    assert result.rule.lwlt_rate is None
    assert all(band.lwlt_rate is None for band in result.rule.price_bands)
