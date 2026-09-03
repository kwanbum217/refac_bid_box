"""tests/test_prediction_feature_parity.py

공고 상세 API와 챗봇 도구가 동일한 런타임 특징을 생성하고 모델에 전달하는지 검증합니다.

과거 AST/문자열 존재 검사는 런타임 값 불일치(DB 세션 미전달로 인한 기관·재발주 이력 결측)를
놓치는 거짓 양성이 발생했습니다.
본 모듈은 mock/fake 세션을 활용하여 실제 런타임 feature dict의 키 집합과
DB 기반 특징 값(inst_hist_rate, inst_sample_cnt, is_repeat, repeat_cnt 등)이
상세 API와 챗봇 도구 간에 100% 일치함을 단언합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement
from src.app.services.tools.bid_prediction_tool import (
    _build_prediction_features,
    _predict_bid,
    execute,
)
from src.ml.dataset import announcement_feature_payload
from src.ml.features import build_feature_dict
from src.ml.prediction_api import PredictionOutcome


@pytest.fixture
def sample_bid() -> BidAnnouncement:
    """제도 특징과 금액 정보가 완비된 용역 공고 객체를 생성합니다."""
    return BidAnnouncement(
        id=1,
        bid_ntce_no="20260903001",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 공공데이터 클라우드 전환 용역",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        cntrct_mthd_nm="일반경쟁",
        bid_methd_nm="전자입찰",
        ntce_kind_nm="등록공고",
        presmpt_prce=150_000_000.0,
        base_amount=150_000_000.0,
        bid_ntce_dt=datetime(2026, 9, 1, 10, 0),
        bid_clse_dt=datetime(2026, 9, 15, 18, 0),
        openg_dt=datetime(2026, 9, 16, 10, 0),
        raw_data={
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


@pytest.fixture
def fake_db_session(sample_bid: BidAnnouncement) -> MagicMock:
    """기관 통계 및 재발주 이력을 모의 응답하는 가짜 DB 세션을 제공합니다."""
    session = MagicMock(spec=Session)

    def fake_execute(stmt):
        s = str(stmt)
        res = MagicMock()
        if "institution_win_rate_stats" in s:
            # avg_rate=88.5, sample_count=42, ewm_rate=87.9
            res.one_or_none.return_value = (88.5, 42, 87.9)
        elif "bid_results" in s:
            # 과거 동일 사업 재발주 이력
            res.all.return_value = [
                ("2025년 공공데이터 클라우드 전환 용역", 88.2, pd.Timestamp("2025-09-01"))
            ]
        elif "bid_announcements" in s:
            res.scalars.return_value.all.return_value = [sample_bid]
        else:
            res.one_or_none.return_value = None
            res.all.return_value = []
            res.scalars.return_value.all.return_value = []
        return res

    session.execute.side_effect = fake_execute
    session.get.return_value = sample_bid
    return session


def _build_api_reference_features(bid: BidAnnouncement, db: Session) -> dict[str, Any]:
    """src/app/api/v1/predictions.py의 정본 특징 생성 로직을 그대로 재현합니다."""
    reference_amount = float(bid.prediction_reference_amount or 0)
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


def test_runtime_feature_parity_between_api_and_chatbot_tool(
    sample_bid: BidAnnouncement,
    fake_db_session: MagicMock,
):
    """상세 API와 챗봇 도구가 생성한 런타임 특징이 완전히 동일해야 합니다."""
    api_features = _build_api_reference_features(sample_bid, fake_db_session)
    chatbot_features = _build_prediction_features(sample_bid, fake_db_session)

    assert set(chatbot_features.keys()) == set(api_features.keys())
    assert len(chatbot_features) == len(api_features)

    for key, api_val in api_features.items():
        chat_val = chatbot_features[key]
        if isinstance(api_val, float):
            assert chat_val == pytest.approx(api_val), (
                f"특징 '{key}' 불일치: 챗봇={chat_val}, API={api_val}"
            )
        else:
            assert chat_val == api_val, f"특징 '{key}' 불일치: 챗봇={chat_val}, API={api_val}"


def test_predict_bid_passes_captured_features_with_db_values(
    sample_bid: BidAnnouncement,
    fake_db_session: MagicMock,
):
    """_predict_bid가 모델에 넘기는 실제 특징 dict에 DB 기관·재발주 이력이 반영되어야 합니다."""
    captured: dict[str, Any] = {}

    def fake_provenance(model_id, features_dict, **kwargs):
        captured.update(features_dict)
        return PredictionOutcome(
            predicted_rate=0.88,
            requested_model=model_id,
            actual_model=model_id,
            fallback_used=False,
        )

    with patch(
        "src.app.services.tools.bid_prediction_tool.predict_optimal_price_with_provenance",
        side_effect=fake_provenance,
    ):
        result = _predict_bid(sample_bid, "servc_institution_v1", db=fake_db_session)

    assert result["model_id"] == "servc_institution_v1"
    assert result["optimal_price"] > 0

    # DB 세션이 전달되어 계산된 기관 이력 통계 확인
    assert captured["inst_hist_rate"] == pytest.approx(0.885)
    assert captured["inst_sample_cnt"] == 42.0
    assert captured["inst_ewm_rate"] == pytest.approx(0.879)

    # DB 세션이 전달되어 계산된 재발주 이력 통계 확인
    assert captured["is_repeat"] == 1.0
    assert captured["repeat_cnt"] == 1.0
    assert captured["repeat_hist_rate"] == pytest.approx(0.882)
    assert captured["repeat_prev_rate"] == pytest.approx(0.882)

    # 제도 특징(raw_data) 반영 확인
    assert captured["lwlt_rate"] == pytest.approx(87.745)
    assert captured["lwlt_rate_missing"] == 0.0
    assert captured["srvce_div_nm"] == "일반용역"
    assert captured["lrg_clsfc_nm"] == "정보통신용역"

    # 기존 규칙 기반 구 모델용 원본 키 보존 확인
    assert captured["title"] == "2026년 공공데이터 클라우드 전환 용역"
    assert captured["agency_name"] == "한국도로공사"
    assert captured["scenario_mode"] == "2"


def test_without_db_session_falls_back_to_defaults(
    sample_bid: BidAnnouncement,
):
    """db 세션이 없으면 기관 이력 표본 수 0, 재발주 이력 없음 기본값으로 떨어집니다."""
    features = _build_prediction_features(sample_bid, db=None)

    assert features["inst_sample_cnt"] == 0.0
    assert features["is_repeat"] == 0.0
    assert features["repeat_cnt"] == 0.0
    assert features["repeat_hist_rate"] == pytest.approx(0.925)


def test_execute_passes_db_session_to_all_selected_bids(
    fake_db_session: MagicMock,
):
    """execute에서 선택한 모든 공고가 동일한 db 세션으로 _predict_bid와 build_feature_dict를 거쳐야 합니다."""
    bid1 = BidAnnouncement(
        id=101,
        bid_ntce_no="20260903101",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 클라우드 1차",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        presmpt_prce=100_000_000.0,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
    )
    bid2 = BidAnnouncement(
        id=102,
        bid_ntce_no="20260903102",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 클라우드 2차",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        presmpt_prce=200_000_000.0,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
    )

    captured_runs: list[dict[str, Any]] = []

    def fake_provenance(model_id, features_dict, **kwargs):
        captured_runs.append(dict(features_dict))
        return PredictionOutcome(
            predicted_rate=0.88,
            requested_model=model_id,
            actual_model=model_id,
            fallback_used=False,
        )

    with (
        patch(
            "src.app.services.tools.bid_prediction_tool._latest_predictable_bids",
            return_value=[bid1, bid2],
        ),
        patch(
            "src.app.services.tools.bid_prediction_tool.predict_optimal_price_with_provenance",
            side_effect=fake_provenance,
        ),
    ):
        result = execute(
            db=fake_db_session,
            query="용역 2개 추천",
            category="Servc",
            limit=2,
        )

    assert result["status"] == "success"
    assert result["result_count"] == 2
    assert len(captured_runs) == 2

    # 두 공고 모두 fake_db_session을 통해 기관 이력이 채워졌음을 확인
    for captured in captured_runs:
        assert captured["inst_sample_cnt"] == 42.0
        assert captured["inst_hist_rate"] == pytest.approx(0.885)


def test_nonprearranged_and_fallback_contracts_preserved(
    fake_db_session: MagicMock,
):
    """비예가 스킵 및 모델 실패 시 에러 계약이 그대로 유지되어야 합니다."""
    nonprearng_bid = BidAnnouncement(
        id=201,
        bid_ntce_no="20260903201",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 비예가 용역",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        presmpt_prce=50_000_000.0,
        raw_data={"prearngPrceDcsnMthdNm": "없음"},
    )
    result = _predict_bid(nonprearng_bid, "servc_institution_v1", db=fake_db_session)
    assert result["skipped"] is True
    assert "비예가 공고는 예정가격을 작성하지 않는 제도라" in result["skip_reason"]

    # 모델 후보 전량 실패 시 fallback/skip 계약 확인
    normal_bid = BidAnnouncement(
        id=202,
        bid_ntce_no="20260903202",
        bid_ntce_ord="000",
        bid_ntce_nm="2026년 정상 용역",
        ntce_instt_nm="한국도로공사",
        dminstt_nm="한국도로공사",
        category="Servc",
        presmpt_prce=50_000_000.0,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가"},
    )
    with patch(
        "src.app.services.tools.bid_prediction_tool.predict_optimal_price_with_provenance",
        side_effect=RuntimeError("all models down"),
    ):
        fail_result = _predict_bid(normal_bid, "servc_institution_v1", db=fake_db_session)

    assert fail_result["skipped"] is True
    assert fail_result["fallback_used"] is True
    assert fail_result["fallback_reason"] == "모델 후보 전량 실패"
    assert "예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다." in fail_result["skip_reason"]
