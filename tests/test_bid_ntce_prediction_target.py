"""tests/test_bid_ntce_prediction_target.py

공고번호가 지정된 낙찰가 예측은 그 공고의 최신 차수만 예측합니다.

증명하는 것:
  1. 해석 단계가 뽑은 공고번호를 실행 파라미터로 넘기고, 역량 레지스트리가
     그 파라미터를 허용한다.
  2. 실행 단계는 번호가 있으면 그 공고의 최신 차수 한 건만 예측한다.
     limit 이 더 커도 다른 공고로 채우지 않는다.
  3. 그 공고가 없거나, 최신 차수가 취소공고이거나, 예측 기준 금액이 0 이면
     다른 공고로 대체하지 않고 status=error 로 사유를 알린다.
  4. 번호가 없는 요청은 기존처럼 최근 공고 N건을 예측한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.app.models.bids import BidAnnouncement
from src.app.services import planner_interpreter
from src.app.services.capability_registry import get_capability
from src.app.services.tools import bid_prediction_tool as tool
from src.ml.model_registry import PredictionOutcome

TARGET_NO = "R26BK01789522"
COLLECTED_AT = datetime(2026, 11, 20, 9, 0)


def _outcome() -> PredictionOutcome:
    return PredictionOutcome(
        predicted_rate=0.97,
        requested_model="v25",
        actual_model="v25",
        fallback_used=False,
        fallback_reason=None,
    )


def _seed_bid(
    db,
    *,
    no: str,
    ord: str = "000",
    category: str = "Servc",
    base_amount: int | None = 100_000_000,
    presmpt_prce: int | None = 90_000_000,
    ntce_kind_nm: str | None = None,
    collected_at: datetime = COLLECTED_AT,
    raw_data: dict | None = None,
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord=ord,
        bid_ntce_nm=f"{no} 차수 {ord}",
        ntce_instt_nm="조달청",
        dminstt_nm="한국도로공사",
        category=category,
        base_amount=base_amount,
        presmpt_prce=presmpt_prce,
        ntce_kind_nm=ntce_kind_nm,
        bid_ntce_dt=COLLECTED_AT,
        bid_clse_dt=COLLECTED_AT + timedelta(days=7),
        openg_dt=COLLECTED_AT + timedelta(days=8),
        raw_data={} if raw_data is None else raw_data,
        collected_at=collected_at,
    )
    db.add(bid)
    db.commit()
    return bid


def _patch_prediction(monkeypatch) -> None:
    monkeypatch.setattr(
        tool, "predict_optimal_price_with_provenance", lambda *args, **kwargs: _outcome()
    )


def test_interpret_request_forwards_notice_number():
    """해석 단계가 뽑은 공고번호를 예측 도구 파라미터로 넘긴다."""
    plan = planner_interpreter.interpret_request(f"{TARGET_NO} 낙찰가 예측해줘")

    assert plan.requested_capabilities == ["bid_prediction_tool"]
    assert plan.parameters.get("bid_ntce_no") == TARGET_NO


def test_capability_registry_allows_notice_number():
    """허용 목록에 없으면 실행 전에 파라미터가 버려지므로 레지스트리도 맞춘다."""
    capability = get_capability("bid_prediction_tool")

    assert capability is not None
    assert "bid_ntce_no" in capability.allowed_params


def test_execute_predicts_only_latest_order_of_target_notice(isolated_db, monkeypatch):
    """번호가 있으면 그 공고의 최신 차수 한 건만 예측하고 limit 으로 채우지 않는다."""
    _seed_bid(isolated_db, no=TARGET_NO, ord="000", collected_at=COLLECTED_AT)
    _seed_bid(
        isolated_db,
        no=TARGET_NO,
        ord="001",
        collected_at=COLLECTED_AT + timedelta(days=1),
    )
    # 다른 공고가 더 최근이어도 대체 선택되면 안 된다.
    _seed_bid(
        isolated_db,
        no="R26BK99999999",
        collected_at=COLLECTED_AT + timedelta(days=2),
    )
    _patch_prediction(monkeypatch)

    result = tool.execute(db=isolated_db, query="낙찰가 예측 5건", limit=5, bid_ntce_no=TARGET_NO)

    assert result["status"] == "success"
    assert result["result_count"] == 1
    assert result["bid"]["bid_ntce_no"] == TARGET_NO
    assert result["bid"]["bid_ntce_ord"] == "001"


def test_execute_reports_error_when_target_notice_missing(isolated_db, monkeypatch):
    """지정 공고가 없으면 다른 공고를 예측하지 않고 오류로 알린다."""
    _seed_bid(isolated_db, no="R26BK99999999")
    _patch_prediction(monkeypatch)

    result = tool.execute(
        db=isolated_db, query="낙찰가 예측 5건", limit=5, bid_ntce_no="R26BK00000000"
    )

    assert result["status"] == "error"
    assert result["reason"] == "bid_not_found"
    assert result["bid_ntce_no"] == "R26BK00000000"
    assert result["result_count"] == 0
    assert "predictions" not in result


def test_execute_reports_error_when_reference_amount_is_zero(isolated_db, monkeypatch):
    """예측 기준 금액이 0 이면 다른 공고로 대체하지 않고 오류로 알린다."""
    _seed_bid(
        isolated_db,
        no=TARGET_NO,
        base_amount=None,
        presmpt_prce=0,
    )
    _seed_bid(
        isolated_db,
        no="R26BK99999999",
        collected_at=COLLECTED_AT + timedelta(days=1),
    )
    _patch_prediction(monkeypatch)

    result = tool.execute(db=isolated_db, query="낙찰가 예측", limit=5, bid_ntce_no=TARGET_NO)

    assert result["status"] == "error"
    assert result["reason"] == "zero_reference_amount"
    assert result["result_count"] == 0


def test_execute_reports_error_when_latest_order_is_cancelled(isolated_db, monkeypatch):
    """최신 차수가 취소공고면 이전 차수나 다른 공고로 대체하지 않고 오류로 알린다."""
    _seed_bid(isolated_db, no=TARGET_NO, ord="000")
    _seed_bid(
        isolated_db,
        no=TARGET_NO,
        ord="001",
        ntce_kind_nm="취소공고",
        collected_at=COLLECTED_AT + timedelta(days=1),
    )
    _patch_prediction(monkeypatch)

    result = tool.execute(db=isolated_db, query="낙찰가 예측", limit=5, bid_ntce_no=TARGET_NO)

    assert result["status"] == "error"
    # 기준 코드는 번호를 무시하고 최신 차수 취소를 목록 필터로 걸러 빈 결과만 돌려준다.
    # 지정 공고 사유를 구분해 알리는지가 이 시험의 판별점이다.
    assert "reason" in result
    assert result["reason"] == "cancelled_latest_order"
    assert result["result_count"] == 0


def test_execute_without_notice_number_keeps_recent_limit_behavior(isolated_db, monkeypatch):
    """번호가 없는 요청은 기존처럼 최근 공고 N건을 예측한다."""
    for index in range(3):
        _seed_bid(
            isolated_db,
            no=f"R26BK0000000{index}",
            collected_at=COLLECTED_AT + timedelta(minutes=index),
        )
    _patch_prediction(monkeypatch)

    result = tool.execute(db=isolated_db, query="낙찰가 예측 3건", limit=3)

    assert result["status"] == "success"
    assert result["result_count"] == 3
    assert {item["bid"]["bid_ntce_no"] for item in result["predictions"]} == {
        "R26BK00000000",
        "R26BK00000001",
        "R26BK00000002",
    }
