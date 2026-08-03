"""
tests/test_bids_api.py

원본 apps/bids/tests.py 중 이식 가능한 검증을 FastAPI 환경으로 변환.
Django 템플릿 렌더링 테스트는 React 프론트엔드로 대체되어 제외.
 - extract_business_budget 단위 테스트
 - resolved_base_amount / display_base_amount / prediction_reference_amount property
 - 대시보드 통계 API / 비교 통계 API 기본 동작
"""

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, extract_business_budget


def test_extract_business_budget_prefers_bdgtAmt():
    assert extract_business_budget({"bdgtAmt": "55330000", "presmptPrce": "50300000"}) == 55330000


def test_extract_business_budget_prefers_asignBdgtAmt():
    assert (
        extract_business_budget({"asignBdgtAmt": "142817400", "presmptPrce": "129834000"})
        == 142817400
    )


def test_extract_business_budget_does_not_treat_presmpt_price_as_base_amount():
    assert extract_business_budget({"presmptPrce": "129834000"}) is None


def test_extract_business_budget_returns_fallback_for_non_dict():
    assert extract_business_budget(None) is None
    assert extract_business_budget("string") is None


def _make_announcement(**overrides):
    defaults = {
        "bid_ntce_no": "ANN-TEST",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "테스트 공고",
        "dminstt_nm": "Test agency",
        "base_amount": 110000000,
        "presmpt_prce": 100000000,
        "bid_ntce_dt": utcnow(),
        "category": "Thng",
        "raw_data": None,
    }
    defaults.update(overrides)
    return BidAnnouncement(**defaults)


def test_display_base_amount_uses_base_amount_when_raw_data_none():
    bid = _make_announcement()
    assert bid.display_base_amount == 110000000
    assert bid.has_base_amount is True


def test_display_base_amount_is_none_when_base_amount_none_and_raw_data_none():
    bid = _make_announcement(base_amount=None)
    assert bid.display_base_amount is None
    assert bid.has_base_amount is False


def test_prediction_reference_amount_falls_back_to_presmpt_prce():
    bid = _make_announcement(base_amount=None, presmpt_prce=3300000)
    assert bid.display_base_amount is None
    assert bid.prediction_reference_amount == 3300000


def test_prediction_reference_amount_prefers_base_amount():
    bid = _make_announcement(base_amount=110000000, presmpt_prce=100000000)
    assert bid.prediction_reference_amount == 110000000


def test_display_base_amount_recomputes_from_raw_data():
    bid = _make_announcement(
        base_amount=50300000,
        presmpt_prce=50300000,
        raw_data={"bdgtAmt": "55330000", "presmptPrce": "50300000"},
    )
    assert bid.display_base_amount == 55330000
    assert bid.has_base_amount is True
    assert bid.prediction_reference_amount == 55330000


def test_dashboard_stats_api_returns_basic_structure(client, isolated_db):
    from src.app.models.bids import BidResult

    result = BidResult(
        bid_ntce_no="ANN-001",
        bid_ntce_ord="000",
        bid_ntce_nm="Dashboard test",
        bidwinnr_nm="Test vendor",
        sucsf_bid_amt=950000,
        sucsf_bid_rate=95.0,
        rl_openg_dt=utcnow(),
        dminstt_nm="Test agency",
        category="Servc",
    )
    isolated_db.add(result)
    isolated_db.commit()

    response = client.get("/api/v1/bids/stats")

    assert response.status_code == 200
    payload = response.json()
    assert "total_count" in payload
    assert "by_month" in payload
    assert payload["total_count"] >= 1


def test_compare_stats_api_returns_basic_structure(client, isolated_db):
    bid = _make_announcement(
        bid_ntce_no="ANN-CMP",
        bid_ntce_nm="Compare test",
        category="Thng",
    )
    isolated_db.add(bid)
    isolated_db.commit()

    response = client.get("/api/v1/bids/compare-stats")

    assert response.status_code == 200
    payload = response.json()
    assert "announce_count" in payload
    assert "result_count" in payload
    assert payload["announce_count"] >= 1


def test_bid_detail_returns_404_for_unknown_id(client, isolated_db):
    response = client.get("/api/v1/bids/99999")
    assert response.status_code == 404


def test_bid_result_detail_returns_404_for_unknown_id(client, isolated_db):
    response = client.get("/api/v1/bids/results/99999")
    assert response.status_code == 404
