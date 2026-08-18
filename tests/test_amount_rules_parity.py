"""
tests/test_amount_rules_parity.py

원본 apps/bids/tests.py 의 금액 규칙 테스트 이식입니다.

기초금액을 예정가격으로 대체하면 낙찰률과 추천 투찰가가 통째로 어긋납니다.
로직(src/app/models/bids.py)은 원본과 같지만 회귀 테스트가 없어, 이후 누군가
"값이 비어 보인다"는 이유로 fallback 을 넣는 것을 막지 못합니다. 그 방어선입니다.

대응하는 원본 테스트:

- test_display_base_amount_does_not_fallback_to_presmpt_price
- test_display_base_amount_recomputes_strict_value_from_raw_data
- test_extract_business_budget_prefers_budget_fields
- test_extract_business_budget_does_not_treat_presmpt_price_as_base_amount
"""

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, extract_business_budget


def _announcement(**overrides) -> BidAnnouncement:
    payload = {
        "bid_ntce_no": "ANN-BASE",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "금액 규칙 검증 공고",
        "dminstt_nm": "테스트발주기관",
        "bid_ntce_dt": utcnow(),
        "category": "Servc",
    }
    payload.update(overrides)
    return BidAnnouncement(**payload)


def test_extract_business_budget_prefers_budget_fields():
    """기초금액은 예산금액/배정예산금액에서만 가져온다."""
    assert extract_business_budget({"bdgtAmt": "55330000", "presmptPrce": "50300000"}) == 55330000
    assert (
        extract_business_budget({"asignBdgtAmt": "142817400", "presmptPrce": "129834000"})
        == 142817400
    )


def test_extract_business_budget_does_not_treat_presmpt_price_as_base_amount():
    """예정가격만 있는 공고는 기초금액을 확정할 수 없다."""
    assert extract_business_budget({"presmptPrce": "129834000"}) is None


def test_display_base_amount_does_not_fallback_to_presmpt_price():
    """기초금액이 없으면 화면에는 비워 두고, 예측 입력만 예정가격을 쓴다."""
    announcement = _announcement(
        bid_ntce_no="ANN-NO-BASE",
        base_amount=None,
        presmpt_prce=3300000,
    )

    assert announcement.display_base_amount is None
    assert announcement.has_base_amount is False
    assert announcement.prediction_reference_amount == 3300000


def test_display_base_amount_recomputes_strict_value_from_raw_data():
    """raw_data 의 예산금액이 DB 컬럼보다 우선한다."""
    announcement = _announcement(
        bid_ntce_no="ANN-STRICT-BASE",
        base_amount=50300000,
        presmpt_prce=50300000,
        category="Thng",
        raw_data={"bdgtAmt": "55330000", "presmptPrce": "50300000"},
    )

    assert announcement.display_base_amount == 55330000
    assert announcement.has_base_amount is True
    assert announcement.prediction_reference_amount == 55330000


def test_raw_data_without_budget_fields_blocks_base_amount():
    """raw_data 가 있는데 예산 필드가 없으면 DB 컬럼으로 되돌아가지 않는다.

    수집 당시 예산 항목이 비어 있었다는 뜻이므로, base_amount 컬럼의 옛 값을
    쓰면 근거 없는 금액이 화면에 남습니다.
    """
    announcement = _announcement(
        bid_ntce_no="ANN-RAW-NO-BUDGET",
        base_amount=50300000,
        presmpt_prce=49000000,
        raw_data={"presmptPrce": "49000000"},
    )

    assert announcement.resolved_base_amount is None
    assert announcement.has_base_amount is False
    assert announcement.prediction_reference_amount == 49000000


def test_missing_raw_data_falls_back_to_stored_column():
    """raw_data 자체가 없으면 DB 컬럼을 신뢰한다 (원본 동일)."""
    announcement = _announcement(
        bid_ntce_no="ANN-NO-RAW",
        base_amount=50300000,
        presmpt_prce=49000000,
        raw_data=None,
    )

    assert announcement.resolved_base_amount == 50300000
    assert announcement.has_base_amount is True
    assert announcement.prediction_reference_amount == 50300000
