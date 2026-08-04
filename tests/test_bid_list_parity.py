"""
tests/test_bid_list_parity.py

원본 apps/bids/tests.py 의 목록·상세 동작 테스트 이식입니다.

원본은 response.context["bids"] 를 직접 꺼내 순서를 확인했습니다. 이식본 SSR 은
컨텍스트를 노출하지 않으므로, 같은 데이터를 만드는 서비스 계층
(src/app/services/bid_queries.py)을 직접 호출해 동등하게 검증합니다.

대응하는 원본 테스트:

- test_bid_list_prefers_latest_notice_order_for_same_bid_number
- test_bid_detail_uses_latest_notice_order_for_same_bid_number
- test_bid_list_sort_options_change_order
- test_bid_list_region_filter_and_sort
- test_bid_result_list_filter_and_sort_options
"""

from datetime import timedelta

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries


def _add_announcement(db, **overrides) -> BidAnnouncement:
    payload = {
        "bid_ntce_ord": "000",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "bid_ntce_dt": utcnow(),
        "collected_at": utcnow(),
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# 같은 공고번호의 최신 차수만 노출
# --------------------------------------------------------------------------- #


def test_bid_list_prefers_latest_notice_order_for_same_bid_number(isolated_db):
    """같은 공고번호가 여러 차수로 들어와도 목록에는 최신 차수 하나만 나온다."""
    now = utcnow()
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-REV",
        bid_ntce_ord="000",
        bid_ntce_nm="중복 공고 테스트",
        base_amount=66000000,
        presmpt_prce=60000000,
        bid_ntce_dt=now,
    )
    latest = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-REV",
        bid_ntce_ord="002",
        bid_ntce_nm="중복 공고 테스트",
        base_amount=60000000,
        presmpt_prce=54545455,
        bid_ntce_dt=now + timedelta(minutes=1),
    )

    page = bid_queries.list_announcements(isolated_db)
    rows = [row for row in page.object_list if row.bid_ntce_no == "ANN-REV"]

    assert len(rows) == 1
    assert rows[0].id == latest.id


def test_bid_detail_uses_latest_notice_order_for_same_bid_number(isolated_db):
    """과거 차수 id 로 들어와도 상세는 최신 차수를 보여준다."""
    now = utcnow()
    stale = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-DETAIL",
        bid_ntce_ord="000",
        bid_ntce_nm="상세 중복 공고",
        base_amount=66000000,
        presmpt_prce=60000000,
        bid_ntce_dt=now,
    )
    latest = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-DETAIL",
        bid_ntce_ord="002",
        bid_ntce_nm="상세 중복 공고",
        base_amount=60000000,
        presmpt_prce=54545455,
        bid_ntce_dt=now + timedelta(minutes=1),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, stale.id)

    assert detail is not None
    assert detail["bid"].id == latest.id
    assert detail["bid"].display_base_amount == 60000000


# --------------------------------------------------------------------------- #
# 정렬
# --------------------------------------------------------------------------- #


def test_bid_list_sort_options_change_order(isolated_db):
    """notice/deadline/amount 정렬이 실제로 다른 행을 맨 앞에 놓는다."""
    now = utcnow()
    soon_deadline = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-SORT-SOON",
        bid_ntce_nm="마감 임박 공고",
        base_amount=3000000,
        presmpt_prce=2800000,
        bid_ntce_dt=now - timedelta(days=2),
        bid_clse_dt=now + timedelta(days=1),
    )
    latest_notice = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-SORT-LATEST",
        bid_ntce_nm="최신 공고",
        base_amount=1000000,
        presmpt_prce=900000,
        bid_ntce_dt=now + timedelta(hours=1),
        bid_clse_dt=now + timedelta(days=10),
    )

    by_notice = bid_queries.list_announcements(isolated_db, sort="notice")
    by_deadline = bid_queries.list_announcements(isolated_db, sort="deadline")
    by_amount = bid_queries.list_announcements(isolated_db, sort="amount")

    assert by_notice.object_list[0].id == latest_notice.id
    assert by_deadline.object_list[0].id == soon_deadline.id
    assert by_amount.object_list[0].id == soon_deadline.id


@pytest.mark.parametrize("sort_key", ["", "unknown-value"])
def test_bid_list_unknown_sort_falls_back_to_default(isolated_db, sort_key):
    """원본은 허용 목록에 없는 정렬 키를 기본값으로 되돌린다."""
    assert bid_queries.normalize_bid_sort(sort_key) == bid_queries.DEFAULT_BID_LIST_SORT


# --------------------------------------------------------------------------- #
# 지역 필터
# --------------------------------------------------------------------------- #


def test_bid_list_region_filter_and_sort(isolated_db):
    """지역 필터는 해당 지역만 남기고, 지역 정렬은 정해진 순위를 따른다."""
    now = utcnow()
    seoul = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-REGION-SEOUL",
        bid_ntce_nm="서울 지역 공고",
        ntce_instt_nm="서울특별시",
        dminstt_nm="서울특별시 강남구",
        base_amount=1000000,
        presmpt_prce=900000,
        bid_ntce_dt=now - timedelta(days=1),
    )
    busan = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-REGION-BUSAN",
        bid_ntce_nm="부산 지역 공고",
        ntce_instt_nm="부산광역시",
        dminstt_nm="부산광역시 해운대구",
        base_amount=2000000,
        presmpt_prce=1900000,
        bid_ntce_dt=now,
    )
    daegu = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-REGION-DAEGU",
        bid_ntce_nm="대구 지역 공고",
        ntce_instt_nm="대구광역시",
        dminstt_nm="대구광역시 중구",
        base_amount=3000000,
        presmpt_prce=2900000,
        bid_ntce_dt=now + timedelta(hours=1),
    )

    filtered = bid_queries.list_announcements(isolated_db, sort="region", region="seoul")
    assert [row.id for row in filtered.object_list] == [seoul.id]

    ordered = bid_queries.list_announcements(isolated_db, sort="region")
    assert [row.id for row in ordered.object_list[:3]] == [seoul.id, busan.id, daegu.id]


def test_unknown_region_code_is_ignored(isolated_db):
    """등록되지 않은 지역 코드는 필터로 쓰지 않는다 (원본 동일)."""
    assert bid_queries.normalize_region_code("존재하지않는지역") == ""


# --------------------------------------------------------------------------- #
# 낙찰결과 목록·상세
# --------------------------------------------------------------------------- #


def test_bid_result_list_sort_options(isolated_db):
    """개찰일/금액/낙찰률 정렬이 각각 다른 행을 맨 앞에 놓는다."""
    now = utcnow()
    rows = [
        BidResult(
            bid_ntce_no="RES-OLD-BIG",
            bid_ntce_ord="000",
            bid_ntce_nm="과거 대형 낙찰",
            dminstt_nm="테스트발주기관",
            category="Servc",
            sucsf_bid_amt=900000000,
            sucsf_bid_rate=70.0,
            rl_openg_dt=now - timedelta(days=5),
            collected_at=now,
        ),
        BidResult(
            bid_ntce_no="RES-NEW-SMALL",
            bid_ntce_ord="000",
            bid_ntce_nm="최근 소형 낙찰",
            dminstt_nm="테스트발주기관",
            category="Servc",
            sucsf_bid_amt=1000000,
            sucsf_bid_rate=99.5,
            rl_openg_dt=now,
            collected_at=now,
        ),
    ]
    isolated_db.add_all(rows)
    isolated_db.commit()
    for row in rows:
        isolated_db.refresh(row)
    old_big, new_small = rows

    by_opening = bid_queries.list_results(isolated_db, sort="opening")
    by_amount = bid_queries.list_results(isolated_db, sort="amount")
    by_rate = bid_queries.list_results(isolated_db, sort="rate")

    assert by_opening.object_list[0].id == new_small.id
    assert by_amount.object_list[0].id == old_big.id
    # 원본은 낙찰률을 오름차순으로 정렬합니다 (낮은 낙찰률이 유리한 사례라 먼저 봅니다).
    assert by_rate.object_list[0].id == old_big.id


def test_result_detail_uses_announcement_reference_winning_rate(isolated_db):
    """낙찰률은 공고의 기초금액을 기준으로 다시 계산한다.

    수집 원본의 sucsf_bid_rate 는 기관마다 기준이 달라 그대로 쓰면 화면 값이
    공고 금액과 맞지 않습니다. 원본은 기초금액 기준으로 환산해 보여줍니다.
    """
    now = utcnow()
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-RATE",
        bid_ntce_ord="000",
        bid_ntce_nm="낙찰률 환산 공고",
        base_amount=66000000,
        presmpt_prce=60000000,
        bid_ntce_dt=now,
        raw_data={"bdgtAmt": "66000000"},
    )
    result = BidResult(
        bid_ntce_no="ANN-RATE",
        bid_ntce_ord="000",
        bid_ntce_nm="낙찰률 환산 공고",
        dminstt_nm="테스트발주기관",
        category="Servc",
        sucsf_bid_amt=57000000,
        sucsf_bid_rate=95.0,
        rl_openg_dt=now,
        collected_at=now,
    )
    isolated_db.add(result)
    isolated_db.commit()
    isolated_db.refresh(result)

    detail = bid_queries.get_result_detail(isolated_db, result.id)

    assert detail is not None
    # 57,000,000 / 66,000,000 = 86.3636%. 수집 원본의 95.0 을 그대로 쓰면 안 됩니다.
    rate = detail["result"].display_winning_rate(isolated_db)
    assert str(rate).startswith("86.36")
    assert float(rate) != 95.0
