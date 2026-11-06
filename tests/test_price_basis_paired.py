"""두 금액 기준 쌍대 실측의 회귀를 고정합니다.

(a) `build_serving_features` 의 'reference' 결과가 리팩터 전 API 가 만들던
    특징 딕셔너리와 같아야 합니다. 응답 동작 불변의 근거입니다.
(b) 'presmpt' 는 presmpt_prce·presmptPrce·real_budget 을 추정가격으로 채웁니다.
(c) 추정가격이 없거나 0 이하이면 기준금액으로 대체하고 플래그를 남깁니다.
(d) 측정 스크립트의 짝짓기·판정 표본 분리가 고정 입력에서 기대 수치를 냅니다.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from scripts.compare_servc_price_basis_paired import (
    boundary_crossed,
    build_pair_record,
    evaluate_basis_paired,
    split_decision_sample,
)
from src.app.api.v1.predictions import (
    FEATURE_AMOUNT_BASIS_PRESMPT,
    FEATURE_AMOUNT_BASIS_REFERENCE,
    build_serving_features,
)
from src.app.models.bids import BidAnnouncement
from src.ml.dataset import announcement_feature_payload
from src.ml.features import build_feature_dict


class _StubResult:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row

    def all(self):
        return []


class _StubSession:
    """기관 이력 표에 값이 있는 상황을 흉내 냅니다."""

    def execute(self, _stmt):
        return _StubResult((88.5, 42, 87.9))


@pytest.fixture
def sample_bid() -> BidAnnouncement:
    return BidAnnouncement(
        id=1,
        bid_ntce_no="20261106001",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 공공데이터 클라우드 전환 용역",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        cntrct_mthd_nm="일반경쟁",
        bid_methd_nm="전자입찰",
        ntce_kind_nm="등록공고",
        presmpt_prce=100_000_000,
        base_amount=110_000_000,
        bid_ntce_dt=datetime(2026, 9, 1, 10, 0),
        bid_clse_dt=datetime(2026, 9, 15, 18, 0),
        openg_dt=datetime(2026, 9, 16, 10, 0),
        raw_data={
            "bdgtAmt": "110000000",
            "sucsfbidLwltRate": "87.745",
            "prearngPrceDcsnMthdNm": "복수예가",
            "srvceDivNm": "일반용역",
            "pubPrcrmntLrgClsfcNm": "정보통신용역",
            "pubPrcrmntMidClsfcNm": "소프트웨어유지및지원서비스",
            "pubPrcrmntClsfcNm": "전산업무(소프트웨어개발)",
            "intrbidYn": "N",
            "ppswGnrlSrvceYn": "Y",
            "techAbltEvlRt": "80",
            "bidPrceEvlRt": "20",
            "totPrdprcNum": "15",
            "drwtPrdprcNum": "4",
            "sucsfbidMthdNm": "적격심사",
        },
    )


def _legacy_reference_features(bid: BidAnnouncement, db, reference_amount: float) -> dict:
    """리팩터 전 predict_price_api 가 만들던 특징 딕셔너리를 그대로 재현합니다."""
    features = {
        **announcement_feature_payload(bid),
        "title": bid.bid_ntce_nm or "",
        "agency_name": bid.dminstt_nm or bid.ntce_instt_nm or "",
        "scenario_mode": "2",
        "presmpt_prce": reference_amount,
        "presmptPrce": reference_amount,
        "real_budget": reference_amount,
        "bid_ntce_nm": bid.bid_ntce_nm or "",
        "ntce_instt_nm": bid.ntce_instt_nm or "",
        "ntceInsttNm": bid.ntce_instt_nm or "",
        "dminstt_nm": bid.dminstt_nm or "",
        "bidMethdNm": bid.bid_methd_nm or "",
        "cntrctCnclsMthdNm": bid.cntrct_mthd_nm or "",
        "category": bid.category or "",
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
    }
    return {**features, **build_feature_dict(features, db)}


def test_reference_basis_matches_pre_refactor_dict(sample_bid: BidAnnouncement):
    db = _StubSession()
    reference_amount = float(sample_bid.prediction_reference_amount or 0)
    assert reference_amount == 110_000_000.0

    features = build_serving_features(sample_bid, db, reference_amount)

    assert features == _legacy_reference_features(sample_bid, db, reference_amount)
    assert "_feature_amount_fallback" not in features
    # DB 세션이 빠지면 기관 이력이 기본값으로 떨어집니다. 회귀를 값으로 고정합니다.
    assert features["inst_hist_rate"] == pytest.approx(0.885)
    assert features["inst_sample_cnt"] == 42.0


def test_presmpt_basis_uses_estimate_price(sample_bid: BidAnnouncement):
    features = build_serving_features(
        sample_bid,
        _StubSession(),
        110_000_000.0,
        feature_amount_basis=FEATURE_AMOUNT_BASIS_PRESMPT,
    )

    assert features["presmpt_prce"] == 100_000_000.0
    assert features["presmptPrce"] == 100_000_000.0
    assert features["real_budget"] == 100_000_000.0
    # 금액 파생 특징도 추정가격 기준으로 다시 계산돼야 합니다.
    assert features["log_price"] == pytest.approx(np.log1p(100_000_000.0))
    assert features["base_price"] == 110_000_000.0
    assert features["price_ratio"] == pytest.approx(1.1)
    assert "_feature_amount_fallback" not in features


@pytest.mark.parametrize("missing_amount", [None, 0])
def test_presmpt_basis_falls_back_and_flags(
    sample_bid: BidAnnouncement, missing_amount: int | None
):
    sample_bid.presmpt_prce = missing_amount
    features = build_serving_features(
        sample_bid,
        _StubSession(),
        110_000_000.0,
        feature_amount_basis=FEATURE_AMOUNT_BASIS_PRESMPT,
    )

    assert features["presmpt_prce"] == 110_000_000.0
    assert features["presmptPrce"] == 110_000_000.0
    assert features["real_budget"] == 110_000_000.0
    assert features["_feature_amount_fallback"] is True


def test_reference_basis_does_not_flag_missing_presmpt(sample_bid: BidAnnouncement):
    sample_bid.presmpt_prce = None
    features = build_serving_features(
        sample_bid,
        _StubSession(),
        110_000_000.0,
        feature_amount_basis=FEATURE_AMOUNT_BASIS_REFERENCE,
    )

    assert features["real_budget"] == 110_000_000.0
    assert "_feature_amount_fallback" not in features


def test_unknown_basis_is_rejected(sample_bid: BidAnnouncement):
    with pytest.raises(ValueError, match="feature_amount_basis"):
        build_serving_features(
            sample_bid, _StubSession(), 110_000_000.0, feature_amount_basis="other"
        )


def test_two_bases_differ_only_in_amount_features(sample_bid: BidAnnouncement):
    """쌍대 비교가 금액 기준만 바꾸는지 고정합니다."""
    db = _StubSession()
    reference = build_serving_features(sample_bid, db, 110_000_000.0)
    presmpt = build_serving_features(
        sample_bid, db, 110_000_000.0, feature_amount_basis=FEATURE_AMOUNT_BASIS_PRESMPT
    )

    amount_features = {
        "presmpt_prce",
        "presmptPrce",
        "real_budget",
        "presumed_price",
        "price_ratio",
        "log_price",
        "notice_amt_ratio",
        "is_over_notice_amt",
    }
    assert set(reference) == set(presmpt)
    for key in set(reference) - amount_features:
        assert reference[key] == presmpt[key], key

    assert reference["notice_amt_ratio"] != presmpt["notice_amt_ratio"]


def test_boundary_crossed_detects_diverging_notice_amount_flag():
    crossed = boundary_crossed({"is_over_notice_amt": 0.0}, {"is_over_notice_amt": 1.0})
    same = boundary_crossed({"is_over_notice_amt": 1.0}, {"is_over_notice_amt": 1.0})

    assert crossed is True
    assert same is False


def test_build_pair_record_keeps_both_arms_on_the_same_row():
    record = build_pair_record(
        89.0,
        {"rate_percent": 88.0, "low": 85.0, "high": 91.0},
        {"rate_percent": 90.0, "low": 87.0, "high": 93.0},
        feature_amount_fallback=False,
        boundary_crossed=True,
    )

    assert record["base_err"] == 1.0
    assert record["chal_err"] == 1.0
    assert record["base_width"] == 6.0
    assert record["chal_width"] == 6.0
    assert record["base_covered"] is True
    assert record["chal_covered"] is True
    assert record["feature_amount_fallback"] is False
    assert record["boundary_crossed"] is True


def _paired_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "actual": [70.0, 90.0, 110.0, 50.0],
            "base_err": [1.0, 0.8, 1.2, 0.1],
            "chal_err": [0.4, 0.6, 0.2, 0.0],
            "base_width": [2.0, 2.0, 2.0, 2.0],
            "chal_width": [1.8, 1.8, 1.8, 1.8],
            "base_covered": [True, True, False, True],
            "chal_covered": [True, True, True, True],
            "feature_amount_fallback": [False, True, False, False],
            "boundary_crossed": [False, True, False, True],
        }
    )


def test_split_decision_sample_keeps_all_rows_and_filters_scope():
    reporting, decision = split_decision_sample(_paired_frame())

    assert reporting["actual"].tolist() == [70.0, 90.0, 110.0, 50.0]
    # 경계 70 과 110 은 학습 범위 안입니다.
    assert decision["actual"].tolist() == [70.0, 90.0, 110.0]


def test_evaluate_basis_paired_reports_both_scopes():
    evaluation = evaluate_basis_paired(_paired_frame())

    assert evaluation["requested_pairs"] == 4
    assert evaluation["outside_count"] == 1
    assert evaluation["outside_ratio"] == 0.25
    assert evaluation["feature_amount_fallback_count"] == 1
    assert evaluation["boundary_crossed_count"] == 2

    assert evaluation["reporting"]["n"] == 4
    assert evaluation["decision"]["n"] == 3
    assert evaluation["reporting"]["hit_0_5"] == {
        "reference": 0.25,
        "presmpt": 0.75,
    }
    assert evaluation["decision"]["hit_0_5"]["presmpt"] == pytest.approx(2 / 3)
    assert evaluation["decision"]["coverage"]["reference"] == pytest.approx(2 / 3)
    assert evaluation["decision"]["coverage"]["presmpt"] == 1.0

    # chal_err 가 모든 쌍에서 낮으므로 challenger(presmpt) 우세입니다.
    assert evaluation["reporting"]["verdict"] == "challenger 우세"
    assert evaluation["decision"]["verdict"] == "challenger 우세"
    assert evaluation["verdict_mismatch"] is False


def test_evaluate_basis_paired_requires_paired_columns():
    with pytest.raises(ValueError, match="쌍대 평가 컬럼"):
        evaluate_basis_paired(pd.DataFrame({"actual": [90.0]}))
