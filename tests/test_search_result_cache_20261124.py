"""
tests/test_search_result_cache_20261124.py

공고 목록·낙찰 결과 목록의 Meilisearch 검색 결과(id 목록과 다음 페이지 여부)를
짧게 캐시하는 경로를 검증합니다. 운영 Redis 와 Meilisearch 없이 가짜 cache 와
가짜 검색 클라이언트로 확인하며, 캐시 적중 시에도 화면에 보이는 행과 순서,
다음 페이지 여부가 캐시 미적중과 같아야 합니다.
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.bid_queries import (
    PAGE_SIZE,
    SEARCH_RESULT_CACHE_PREFIX,
    SEARCH_RESULT_CACHE_TTL_SECONDS,
    _search_index_page,
    _search_result_cache_key,
)
from src.app.services.search_index import SearchBackendUnavailable, SearchPage


class FakeCache:
    """cache.get/set 만 흉내 내는 대역입니다. 장애 주입 플래그를 가집니다."""

    def __init__(self, fail_get: bool = False, fail_set: bool = False) -> None:
        self.store: dict[str, object] = {}
        self.get_keys: list[str] = []
        self.set_calls: list[tuple[str, object, int]] = []
        self.fail_get = fail_get
        self.fail_set = fail_set

    def get(self, key: str) -> object:
        self.get_keys.append(key)
        if self.fail_get:
            raise RuntimeError("cache get down")
        return copy.deepcopy(self.store.get(key))

    def set(self, key: str, value: object, ttl: int) -> None:
        if self.fail_set:
            raise RuntimeError("cache set down")
        self.set_calls.append((key, copy.deepcopy(value), ttl))
        self.store[key] = copy.deepcopy(value)


@pytest.fixture
def fake_cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(bid_queries, "cache", fake)
    return fake


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'search_cache.sqlite3'}")
    BidAnnouncement.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            [
                BidAnnouncement(
                    bid_ntce_no="R26-CACHE-1",
                    bid_ntce_dt=datetime(2026, 11, 20, 10, 0),
                    dminstt_nm="기관",
                    category="Servc",
                ),
                BidAnnouncement(
                    bid_ntce_no="R26-CACHE-2",
                    bid_ntce_dt=datetime(2026, 11, 21, 10, 0),
                    dminstt_nm="기관",
                    category="Servc",
                ),
                BidAnnouncement(
                    bid_ntce_no="R26-CACHE-3",
                    bid_ntce_dt=datetime(2026, 11, 22, 10, 0),
                    dminstt_nm="기관",
                    category="Servc",
                ),
            ]
        )
        session.commit()
        yield session


def _patch_search(monkeypatch, ids, has_next=False, error=None):
    """검색 클라이언트를 대역으로 바꾸고 호출 인자를 모읍니다."""
    calls: list[dict] = []

    class FakeClient:
        def search(self, **kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return SearchPage(ids=list(ids), has_next=has_next)

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        FakeClient,
    )
    return calls


def _page_args(**overrides):
    args = {
        "query": "",
        "dataset": "result",
        "category": None,
        "region": None,
        "sort": ["rl_openg_dt:desc", "source_id:desc"],
        "page_number": 1,
        "license_codes": None,
        "qualification_only": False,
    }
    args.update(overrides)
    return args


BASE_KEY_ARGS = {
    "query": "",
    "dataset": "result",
    "category": None,
    "region": None,
    "sort": ["rl_openg_dt:desc", "source_id:desc"],
    "offset": 0,
    "limit": PAGE_SIZE,
}


def test_same_conditions_call_search_once_and_cache_ids(db, fake_cache, monkeypatch):
    """(a) 같은 조건을 두 번 부르면 Meilisearch 검색은 한 번만 호출됩니다."""
    calls = _patch_search(monkeypatch, ids=[1, 2, 3], has_next=True)

    first = _search_index_page(db, model=BidAnnouncement, **_page_args())
    second = _search_index_page(db, model=BidAnnouncement, **_page_args())

    assert len(calls) == 1
    assert [row.id for row in first.object_list] == [1, 2, 3]
    assert [row.id for row in second.object_list] == [1, 2, 3]
    assert first.has_next is True
    assert second.has_next is True
    assert len(fake_cache.set_calls) == 1
    key, value, ttl = fake_cache.set_calls[0]
    assert key.startswith(SEARCH_RESULT_CACHE_PREFIX)
    assert value == {"ids": [1, 2, 3], "has_next": True}
    assert ttl == SEARCH_RESULT_CACHE_TTL_SECONDS


@pytest.mark.parametrize(
    "overrides",
    [
        {"query": "도로"},
        {"dataset": "announcement"},
        {"category": "Servc"},
        {"region": "seoul"},
        {"sort": ["rl_openg_dt:asc", "source_id:desc"]},
        {"offset": PAGE_SIZE},
        {"limit": PAGE_SIZE + 1},
        {"license_code": "1234"},
        {"license_codes": ["1234", "5678"]},
        {"qualification_only": True},
    ],
)
def test_different_conditions_produce_different_keys(overrides):
    """(b) 검색 조건이 하나라도 다르면 캐시 키가 달라집니다."""
    base = dict(BASE_KEY_ARGS)
    changed = {**BASE_KEY_ARGS, **overrides}
    assert _search_result_cache_key(base) != _search_result_cache_key(changed)


def test_license_code_order_does_not_change_key():
    """(c) license_codes 는 순서만 다르면 같은 키가 됩니다."""
    first = {**BASE_KEY_ARGS, "license_codes": ["1234", "5678"]}
    second = {**BASE_KEY_ARGS, "license_codes": ["5678", "1234"]}
    assert _search_result_cache_key(first) == _search_result_cache_key(second)


def test_search_unavailable_is_not_cached(db, fake_cache, monkeypatch):
    """(d) 검색 백엔드 장애는 캐시에 쓰지 않고 그대로 예외를 올립니다."""
    _patch_search(monkeypatch, ids=[], error=SearchBackendUnavailable("down"))

    with pytest.raises(SearchBackendUnavailable):
        _search_index_page(db, model=BidAnnouncement, **_page_args())

    assert fake_cache.set_calls == []


def test_cache_get_failure_falls_back_to_search(db, monkeypatch):
    """(e) 캐시 조회가 실패하면 캐시 없이 검색으로 진행합니다."""
    fake = FakeCache(fail_get=True)
    monkeypatch.setattr(bid_queries, "cache", fake)
    calls = _patch_search(monkeypatch, ids=[2], has_next=False)

    page = _search_index_page(db, model=BidAnnouncement, **_page_args())

    assert len(calls) == 1
    assert [row.id for row in page.object_list] == [2]
    assert page.has_next is False


def test_cache_set_failure_keeps_search_result(db, monkeypatch):
    """(e) 캐시 저장이 실패해도 검색 결과는 그대로 돌려줍니다."""
    fake = FakeCache(fail_set=True)
    monkeypatch.setattr(bid_queries, "cache", fake)
    calls = _patch_search(monkeypatch, ids=[1], has_next=True)

    page = _search_index_page(db, model=BidAnnouncement, **_page_args())

    assert len(calls) == 1
    assert [row.id for row in page.object_list] == [1]
    assert page.has_next is True


def test_cache_hit_keeps_rows_order_and_has_next(db, fake_cache, monkeypatch):
    """(f) 캐시 적중 페이지의 행·순서·has_next 는 미적중과 같습니다."""
    calls = _patch_search(monkeypatch, ids=[3, 1, 2], has_next=True)

    missed = _search_index_page(db, model=BidAnnouncement, **_page_args())
    hit = _search_index_page(db, model=BidAnnouncement, **_page_args())

    assert len(calls) == 1
    assert [row.id for row in missed.object_list] == [3, 1, 2]
    assert [row.id for row in hit.object_list] == [3, 1, 2]
    assert missed.has_next == hit.has_next is True
    assert missed.number == hit.number == 1
    assert missed.per_page == hit.per_page == PAGE_SIZE


def test_empty_result_is_cached(db, fake_cache, monkeypatch):
    """빈 결과도 캐시해 같은 조건의 반복 검색이 백엔드를 다시 부르지 않습니다."""
    calls = _patch_search(monkeypatch, ids=[], has_next=False)

    first = _search_index_page(db, model=BidAnnouncement, **_page_args(page_number=2))
    second = _search_index_page(db, model=BidAnnouncement, **_page_args(page_number=2))

    assert len(calls) == 1
    assert first.object_list == []
    assert second.object_list == []
    assert second.has_next is False
