"""
tests/test_structured_data_cache.py

RAG 정형 집계 캐시 검증.

3,405,928 행 위의 COUNT/AVG/SUM 은 질의당 약 190ms 이고, 챗봇 한 번에 아홉
번 돌아 1.72초를 씁니다(2026-08-05 프로파일). 그동안 첫 토큰은 나오지 않습니다.

캐시가 값을 바꾸면 안 되고, 조건이 다른 질의가 서로의 값을 물려받아서도 안
됩니다. 후자는 조용히 틀린 답을 만드는 사고라 특히 중요합니다.
"""

import pytest
from sqlalchemy import func, select

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.rag import structured_data


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_connected", True)
    monkeypatch.setattr(cache, "_local", {})
    return cache


class CountingSession:
    """실행 횟수를 세는 최소 세션 대역입니다."""

    def __init__(self, row):
        self.row = row
        self.executions = 0

    def execute(self, _stmt):
        self.executions += 1
        return self

    def one(self):
        return self.row


def _stmt(category: str):
    return select(
        func.count(BidResult.id),
        func.avg(BidResult.sucsf_bid_rate),
    ).where(BidResult.category == category)


def test_second_call_does_not_hit_db():
    db = CountingSession([858026, 90.4017469])

    first = structured_data._cached_aggregate(db, _stmt("Thng"))
    second = structured_data._cached_aggregate(db, _stmt("Thng"))

    assert db.executions == 1
    assert first == second == [858026, 90.4017469]


def test_different_conditions_do_not_share_a_key():
    """물품 집계가 용역 답변에 실리면 조용히 틀린 답이 됩니다."""
    thng = CountingSession([858026, 90.40])
    servc = CountingSession([1079077, 90.11])

    structured_data._cached_aggregate(thng, _stmt("Thng"))
    result = structured_data._cached_aggregate(servc, _stmt("Servc"))

    assert servc.executions == 1
    assert result == [1079077, 90.11]


def test_decimal_values_survive_as_numbers():
    """Redis 경로는 JSON 직렬화라 Decimal 이 문자열이 됩니다."""
    from decimal import Decimal

    db = CountingSession([10, Decimal("90.4017"), Decimal("150962584218069")])
    row = structured_data._cached_aggregate(db, _stmt("Cnstwk"))

    assert row == [10, 90.4017, 150962584218069.0]
    assert all(isinstance(value, (int, float)) for value in row)


def test_none_aggregate_is_preserved():
    """표본이 없으면 AVG 는 NULL 입니다. 0 으로 바뀌면 없는 값이 값처럼 보입니다."""
    db = CountingSession([0, None, None])
    assert structured_data._cached_aggregate(db, _stmt("Frgcpt")) == [0, None, None]
