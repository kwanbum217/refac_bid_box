"""검색어의 LIKE 와일드카드가 리터럴로 취급되는지 검증합니다.

사용자 검색어를 그대로 LIKE 에 넣으면 % 와 _ 가 와일드카드로 해석되어,
검색어에 그 문자가 들어간 경우 의도보다 훨씬 넓은 결과가 나옵니다.
bid_queries 의 사용자 검색 경로는 autoescape 로 그 문자를 리터럴 처리합니다.

SQLite 로 검증합니다. autoescape 는 SQLAlchemy 가 ESCAPE 절을 붙이는
방식이라 MySQL 과 SQLite 가 같은 규약을 따릅니다.
"""

from __future__ import annotations

from src.app.core.config import settings
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


def _add_result(db, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_ord": "000",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "sucsf_bid_amt": 1000,
        "sucsf_bid_rate": 90.0,
        "rl_openg_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_announcement_search_treats_percent_as_literal(monkeypatch, isolated_db):
    """q='50%' 는 '50%' 를 포함하는 공고만 찾아야 합니다.

    이스케이프하지 않으면 '%50%%' 이 되어 '5000' 처럼 50 만 포함한 공고까지
    끌어옵니다.
    """
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    literal = _add_announcement(
        isolated_db, bid_ntce_no="ANN-PCT", bid_ntce_nm="용역 50% 할인 공고"
    )
    decoy = _add_announcement(
        isolated_db, bid_ntce_no="ANN-DECOY-PCT", bid_ntce_nm="용역 5000 예산 공고"
    )

    page = bid_queries.list_announcements(isolated_db, q="50%")
    ids = {row.id for row in page.object_list}

    assert literal.id in ids
    assert decoy.id not in ids


def test_announcement_search_treats_underscore_as_literal(monkeypatch, isolated_db):
    """q='A_B' 의 _ 는 임의 한 글자가 아니라 밑줄 문자 그대로여야 합니다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    literal = _add_announcement(isolated_db, bid_ntce_no="ANN-UNDER", bid_ntce_nm="코드 A_B 공고")
    decoy = _add_announcement(
        isolated_db, bid_ntce_no="ANN-DECOY-UNDER", bid_ntce_nm="코드 AXB 공고"
    )

    page = bid_queries.list_announcements(isolated_db, q="A_B")
    ids = {row.id for row in page.object_list}

    assert literal.id in ids
    assert decoy.id not in ids


def test_result_search_treats_percent_as_literal(monkeypatch, isolated_db):
    """낙찰결과 검색도 같은 규칙을 따릅니다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    literal = _add_result(isolated_db, bid_ntce_no="RES-PCT", bid_ntce_nm="낙찰 50% 공고")
    decoy = _add_result(isolated_db, bid_ntce_no="RES-DECOY-PCT", bid_ntce_nm="낙찰 5000 공고")

    page = bid_queries.list_results(isolated_db, q="50%")
    ids = {row.id for row in page.object_list}

    assert literal.id in ids
    assert decoy.id not in ids


def test_result_search_treats_underscore_as_literal(monkeypatch, isolated_db):
    """낙찰결과 검색의 _ 도 문자 그대로 매칭합니다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    literal = _add_result(isolated_db, bid_ntce_no="RES-UNDER", bidwinnr_nm="업체 A_B")
    decoy = _add_result(isolated_db, bid_ntce_no="RES-DECOY-UNDER", bidwinnr_nm="업체 AXB")

    page = bid_queries.list_results(isolated_db, q="A_B")
    ids = {row.id for row in page.object_list}

    assert literal.id in ids
    assert decoy.id not in ids


def test_announcement_plain_substring_search_still_matches(monkeypatch, isolated_db):
    """이스케이프 도입이 일반 부분 문자열 검색을 막지 않아야 합니다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    row = _add_announcement(isolated_db, bid_ntce_no="ANN-PLAIN", bid_ntce_nm="일반 용역 공고")
    _add_announcement(isolated_db, bid_ntce_no="ANN-OTHER", bid_ntce_nm="다른 공고")

    page = bid_queries.list_announcements(isolated_db, q="용역")

    assert row.id in {item.id for item in page.object_list}
