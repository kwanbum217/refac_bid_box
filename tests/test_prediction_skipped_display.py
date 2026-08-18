"""예측 실패·산출 불가 공고가 정상 예측처럼 보이지 않는지 검증합니다.

`skipped: True` 항목은 `optimal_price: 0`, `prediction_rate: 0` 을 담습니다.
포맷터가 이를 그대로 찍으면 사용자는 "추천 투찰가 0원"을 유효한 답으로 읽습니다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.api.v1.chatbot_format import _build_direct_tool_answer
from src.ml.monitoring import InsufficientSampleError, calculate_psi, check_feature_drift


def _skipped_item(index: int = 1) -> dict:
    return {
        "bid": {"bid_ntce_nm": f"공고{index}", "bid_ntce_no": f"2026{index}", "bid_ntce_ord": "00"},
        "reference_amount": 1_000_000,
        "optimal_price": 0,
        "prediction_rate": 0,
        "skipped": True,
        "skip_reason": "비예가 공고는 예정가격을 작성하지 않는 제도입니다.",
    }


def _normal_item(index: int = 2) -> dict:
    return {
        "bid": {"bid_ntce_nm": f"공고{index}", "bid_ntce_no": f"2026{index}", "bid_ntce_ord": "00"},
        "reference_amount": 2_000_000,
        "optimal_price": 1_800_000,
        "prediction_rate": 90.0,
        "model_name": "lgbm",
    }


def _list_context(predictions: list[dict]) -> dict:
    """목록 뷰는 predictions 항목이 2건 이상일 때만 쓰입니다."""
    return {
        "tool_results": {
            "bid_prediction": {
                "status": "success",
                "predictions": predictions,
                "result_count": len(predictions),
                "requested_count": len(predictions),
            }
        }
    }


def _single_context(item: dict) -> dict:
    """단건 뷰는 bid_prediction 최상위 필드를 직접 읽습니다."""
    payload = {"status": "success", "predictions": [item]}
    payload.update(item)
    return {"tool_results": {"bid_prediction": payload}}


def _row_cells(answer: str, title: str) -> list[str]:
    for line in answer.splitlines():
        if line.startswith("|") and title in line:
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError(f"{title} 행을 찾지 못했습니다:\n{answer}")


def test_skipped_row_shows_no_price_instead_of_zero_won():
    answer = _build_direct_tool_answer(_list_context([_skipped_item(), _normal_item()]))

    skipped_cells = _row_cells(answer, "공고1")
    assert skipped_cells[-1] == "산출 불가"
    assert skipped_cells[-2] == "-"

    normal_cells = _row_cells(answer, "공고2")
    assert "1,800,000원" in normal_cells[-1]
    assert normal_cells[-2] == "90.0%"

    assert "1건은 투찰가를 산출하지 못했습니다" in answer
    assert "비예가 공고" in answer
    # 산출하지 못한 공고는 사용 모델 요약에 들어가지 않는다
    assert "사용 모델: **lgbm**" in answer


def test_single_skipped_prediction_shows_no_price_instead_of_zero_won():
    single = _skipped_item()
    single["skip_reason"] = "예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다."
    answer = _build_direct_tool_answer(_single_context(single))

    assert "| 추천 투찰가 | 산출 불가 |" in answer
    assert "| 예상 낙찰률 | - |" in answer
    assert "0원" not in answer.split("추천 투찰가")[1]
    assert "예측 모델을 사용할 수 없어" in answer


def test_single_normal_prediction_display_unchanged():
    answer = _build_direct_tool_answer(_single_context(_normal_item()))

    assert "| 추천 투찰가 | **1,800,000원** |" in answer
    assert "| 예상 낙찰률 | 90.0% |" in answer
    assert "산출 불가" not in answer


def test_calculate_psi_rejects_empty_samples():
    """표본이 없으면 0.0(변화 없음)이 아니라 예외입니다."""
    with pytest.raises(InsufficientSampleError):
        calculate_psi(np.array([]), np.array([1.0, 2.0]))
    with pytest.raises(InsufficientSampleError):
        calculate_psi(np.array([1.0, 2.0]), np.array([]))


def test_check_feature_drift_reports_insufficient_data_not_stable():
    """표본 부재가 STABLE 로 승격되면 드리프트 감시가 조용히 꺼집니다."""
    result = check_feature_drift(np.array([]), np.array([]))

    assert result["action"] == "INSUFFICIENT_DATA"
    assert result["action"] != "STABLE"
    assert result["psi_value"] is None
    assert result["drift_detected"] is None
    assert "표본 부족" in result["reason"]


def test_check_feature_drift_normal_path_unchanged():
    rng = np.random.default_rng(0)
    result = check_feature_drift(rng.normal(0, 1, 200), rng.normal(0, 1, 200))

    assert result["action"] in {"STABLE", "TRIGGER_RETRAIN"}
    assert isinstance(result["psi_value"], float)
