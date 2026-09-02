"""
tests/test_missing_lwlt_serving.py

Servc 취약 집단 missing_lwlt 의 운영 서빙 및 불확실성 경고 검증.
- 응답 스키마 필드 (lwlt_missing, lwlt_missing_reason, wide_interval_warning, extreme_prediction_warning, uncertainty_warning)
- 결측 공고(missing_lwlt)와 정상 공고(with_lwlt)의 응답 필드 및 경고 유무
- 넓은 구간(wide_interval_warning) 및 극단 예측(extreme_prediction_warning) 경고
- 결측 사유 분류 (_classify_lwlt_missing_reason)
- detail.html 템플릿 안내 배지 및 자바스크립트 연동
- 하드 차단 부재 (HTTP 200 유지)
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.app.api.v1.predictions import (
    _classify_lwlt_missing_reason,
)
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import PredictPriceResponse
from src.ml.model_registry import ModelRegistry


class _FakeWrapper:
    def __init__(self, model_id: str, rate: float = 0.885, display_name: str | None = None):
        self.model_id = model_id
        self.rate = rate
        self.display_name = display_name or model_id

    def run_preprocess(self, features_dict):
        return pd.DataFrame([{"x": 1.0}])

    def predict(self, df):
        return self.rate

    def get_display_name(self):
        return self.display_name


def _create_test_bid(db, **overrides) -> BidAnnouncement:
    defaults = {
        "bid_ntce_nm": "용역 데이터베이스 구축 사업",
        "bid_ntce_no": "BID-SERV-2026-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "한국지능정보사회진흥원",
        "dminstt_nm": "한국지능정보사회진흥원",
        "base_amount": 100_000_000,
        "presmpt_prce": 100_000_000,
        "bid_ntce_dt": utcnow(),
        "bid_clse_dt": utcnow(),
        "openg_dt": utcnow(),
        "category": "Servc",
        "cntrct_mthd_nm": "수의계약",
        "bid_methd_nm": "전자입찰",
        "raw_data": {
            "prearngPrceDcsnMthdNm": "복수예가",
            "cntrctCnclsMthdNm": "수의(총액)소액수의",
        },
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


class TestPredictPriceResponseSchema:
    """PredictPriceResponse 스키마의 신규 필드 및 이전 계약 보존을 검증합니다."""

    def test_schema_contains_missing_lwlt_fields(self):
        schema = PredictPriceResponse.model_json_schema()
        properties = schema["properties"]

        # 신규 필드 존재 확인
        assert "lwlt_missing" in properties
        assert "lwlt_missing_reason" in properties
        assert "wide_interval_warning" in properties
        assert "extreme_prediction_warning" in properties
        assert "uncertainty_warning" in properties

        # 기존 필드 불변 보존 확인
        required_legacy_fields = [
            "status",
            "optimal_price",
            "prediction_rate",
            "user_bid_similarity",
            "model_name",
            "model_id",
            "requested_model",
            "fallback_used",
            "fallback_reason",
            "message",
            "rate_low",
            "rate_high",
            "price_low",
            "price_high",
            "interval_coverage",
        ]
        for field in required_legacy_fields:
            assert field in properties, f"Legacy field {field} is missing"


class TestMissingLwltServing:
    """결측 공고와 정상 공고에 대한 예측 API 서빙 동작을 검증합니다."""

    @patch("src.app.api.v1.predictions.predict_interval", return_value=(86.0, 90.0, 0.90))
    def test_missing_lwlt_announcement_response(
        self, mock_interval, client, isolated_db, monkeypatch
    ):
        """하한율이 없는 수의계약 공고는 lwlt_missing=True 및 불확실성 경고를 반환한다."""
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="수의(총액)소액수의",
            raw_data={
                "prearngPrceDcsnMthdNm": "복수예가",
                "cntrctCnclsMthdNm": "수의(총액)소액수의",
            },
        )
        fake_model = _FakeWrapper("servc_institution_v1", rate=0.885)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_model)

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": bid.id,
                "user_price": "88500000",
                "selected_model": "servc_institution_v1",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["lwlt_missing"] is True
        assert data["lwlt_missing_reason"] is not None
        assert "수의" in data["lwlt_missing_reason"]
        assert data["uncertainty_warning"] is not None
        assert "낙찰하한율" in data["uncertainty_warning"]
        assert "불확실성" in data["message"]

    @patch("src.app.api.v1.predictions.predict_interval", return_value=(86.0, 89.0, 0.90))
    def test_with_lwlt_announcement_response(self, mock_interval, client, isolated_db, monkeypatch):
        """하한율이 존재하는 일반경쟁 공고는 lwlt_missing=False 및 경고 없음을 반환한다."""
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="일반경쟁",
            raw_data={
                "prearngPrceDcsnMthdNm": "복수예가",
                "sucsfbidLwltRate": "87.745",
                "cntrctCnclsMthdNm": "일반경쟁",
            },
        )
        fake_model = _FakeWrapper("servc_institution_v1", rate=0.885)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_model)

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": bid.id,
                "user_price": "88500000",
                "selected_model": "servc_institution_v1",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["lwlt_missing"] is False
        assert data["lwlt_missing_reason"] is None
        assert data["uncertainty_warning"] is None
        assert "낙찰하한율 부재 공고로" not in data["message"]

    def test_no_hard_blocking_for_missing_lwlt(self, client, isolated_db, monkeypatch):
        """결측 집단이라는 사유만으로 422 또는 거부하지 않고 200을 정상 응답한다."""
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="협상에 의한 계약",
            raw_data={
                "prearngPrceDcsnMthdNm": "복수예가",
                "cntrctCnclsMthdNm": "협상에의한계약",
            },
        )
        fake_model = _FakeWrapper("servc_institution_v1", rate=0.92)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_model)

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": bid.id,
                "user_price": "92000000",
                "selected_model": "servc_institution_v1",
            },
        )
        assert response.status_code == 200


class TestUncertaintyAndWarningThresholds:
    """구간 폭 및 극단 예측값 경고 임계값 로직을 검증합니다."""

    @patch("src.app.api.v1.predictions.predict_interval")
    def test_wide_interval_warning_triggered(self, mock_interval, client, isolated_db, monkeypatch):
        """구간 폭이 15%p 를 초과하면 wide_interval_warning=True 가 설정된다."""
        # 98.0 - 80.0 = 18.0%p > 15.0%p
        mock_interval.return_value = (80.0, 98.0, 0.90)
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="일반경쟁",
            raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
        )
        fake_model = _FakeWrapper("servc_institution_v1", rate=0.885)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_model)

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "selected_model": "servc_institution_v1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["wide_interval_warning"] is True
        assert data["uncertainty_warning"] is not None

    @patch("src.app.api.v1.predictions.predict_interval")
    def test_narrow_interval_no_warning(self, mock_interval, client, isolated_db, monkeypatch):
        """구간 폭이 15%p 이하이면 wide_interval_warning=False 이다."""
        # 90.0 - 87.0 = 3.0%p <= 15.0%p
        mock_interval.return_value = (87.0, 90.0, 0.90)
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="일반경쟁",
            raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
        )
        fake_model = _FakeWrapper("servc_institution_v1", rate=0.885)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_model)

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "selected_model": "servc_institution_v1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["wide_interval_warning"] is False

    def test_extreme_prediction_warning(self, client, isolated_db, monkeypatch):
        """낙찰률이 80% 미만 또는 100% 초과일 때 extreme_prediction_warning=True 이다."""
        bid = _create_test_bid(
            isolated_db,
            cntrct_mthd_nm="일반경쟁",
            raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
        )

        # 75.0% < 80.0%
        fake_low = _FakeWrapper("servc_institution_v1", rate=0.75)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_low)
        resp_low = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "selected_model": "servc_institution_v1"},
        )
        assert resp_low.json()["extreme_prediction_warning"] is True

        # 102.0% > 100.0%
        fake_high = _FakeWrapper("servc_institution_v1", rate=1.02)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_high)
        resp_high = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "selected_model": "servc_institution_v1"},
        )
        assert resp_high.json()["extreme_prediction_warning"] is True

        # 88.0% (정상 범위)
        fake_normal = _FakeWrapper("servc_institution_v1", rate=0.88)
        monkeypatch.setattr(ModelRegistry, "get_model", lambda mid: fake_normal)
        resp_normal = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "selected_model": "servc_institution_v1"},
        )
        assert resp_normal.json()["extreme_prediction_warning"] is False


class TestMissingReasonClassification:
    """결측 사유 판별 함수(_classify_lwlt_missing_reason)의 분류 동작을 검증합니다."""

    def test_sui_contract(self):
        reason = _classify_lwlt_missing_reason({"cntrct_mthd_nm": "수의(총액)소액수의"})
        assert "수의계약" in reason

    def test_negotiation_contract(self):
        reason = _classify_lwlt_missing_reason({"cntrct_mthd_nm": "협상에 의한 계약"})
        assert "협상" in reason

    def test_standard_price_simultaneous(self):
        reason = _classify_lwlt_missing_reason({"sucsfbid_mthd_nm": "규격가격동시입찰"})
        assert "규격" in reason

    def test_lowest_price(self):
        reason = _classify_lwlt_missing_reason({"sucsfbid_mthd_nm": "최저가낙찰제"})
        assert "최저가" in reason

    def test_generic_fallback(self):
        reason = _classify_lwlt_missing_reason({"cntrct_mthd_nm": "기타"})
        assert "낙찰하한율 미적용 공고" in reason


class TestDetailTemplateElements:
    """detail.html 템플릿에 결측 안내 및 불확실성 경고 요소가 올바르게 배치되어 있는지 검증합니다."""

    def test_template_contains_warning_elements(self):
        with open("src/app/templates/bids/detail.html", encoding="utf-8") as f:
            content = f.read()

        # HTML 요소 확인
        assert 'id="res-lwlt-missing"' in content
        assert 'id="res-lwlt-reason"' in content
        assert 'id="res-wide-interval"' in content
        assert "근거 데이터 부족 (낙찰하한율 부재)" in content

        # JS 연동 확인
        assert "data.lwlt_missing" in content
        assert "data.wide_interval_warning" in content
