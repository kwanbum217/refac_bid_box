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
    """프로세스 공용 캐시를 테스트마다 비웁니다.

    백오프 시각을 무한대로 밀어 Redis 재연결을 막고 로컬 저장소만 쓰게 합니다.
    """
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
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


# --------------------------------------------------------------------------- #
# 상위 N 실시간 경로
# --------------------------------------------------------------------------- #
#
# 스냅샷은 날짜 필터가 붙는 순간 포기합니다. "2026년" 같은 흔한 표현이 곧 날짜
# 필터이므로 실시간 경로가 자주 타며, 2026-08-06 측정에서 그 경로가 GROUP BY 로
# 질의당 1.9초를 썼습니다. 같은 질의를 반복해도 값이 줄지 않았습니다.


class RowSession:
    """상위 N 실시간 경로용 세션 대역. 순위 질의와 손상 탐지를 구분해 셉니다."""

    def __init__(self, rows, corrupted=None):
        self.rows = rows
        self.corrupted = corrupted
        self.executions = 0

    def execute(self, _stmt):
        self.executions += 1
        self._last = _stmt
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.corrupted


def _live_stmt(category: str):
    return (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .where(BidResult.category == category)
        .group_by(BidResult.bidwinnr_nm)
    )


def _top(db, category: str):
    return structured_data._top_rows(
        db,
        scope=None,
        dataset="bid_results",
        dimension="bidwinnr_nm",
        live_stmt=_live_stmt(category),
        corrupted_probe=select(BidResult.id),
    )


def test_top_rows_second_call_does_not_hit_db():
    db = RowSession([("번성 주식회사", 812), ("대한건설", 640)])

    first = _top(db, "Cnstwk")
    executions_after_first = db.executions
    second = _top(db, "Cnstwk")

    assert db.executions == executions_after_first
    assert first == second


def test_top_rows_preserves_names_and_counts():
    """이름은 문자열로 남아야 합니다. 숫자 변환을 태우면 여기서 깨집니다."""
    db = RowSession([("번성 주식회사", 812)])

    rows, _ = _top(db, "Cnstwk")
    cached_rows, _ = _top(db, "Cnstwk")

    assert rows == [("번성 주식회사", 812)]
    assert cached_rows == [("번성 주식회사", 812)]


def test_top_rows_different_categories_do_not_share_a_key():
    """공사 순위가 물품 답변에 실리면 조용히 틀린 답이 됩니다."""
    cnstwk = RowSession([("대한건설", 640)])
    thng = RowSession([("한국물산", 91)])

    _top(cnstwk, "Cnstwk")
    rows, _ = _top(thng, "Thng")

    assert rows == [("한국물산", 91)]


def test_top_rows_caches_corruption_flag():
    """탐지 결과까지 담지 않으면 적중할 때마다 탐지 질의가 다시 돕니다."""
    db = RowSession([("대한건설", 640)], corrupted=(1,))

    _, first_dropped = _top(db, "Cnstwk")
    executions_after_first = db.executions
    _, cached_dropped = _top(db, "Cnstwk")

    assert first_dropped == cached_dropped == 1
    assert db.executions == executions_after_first


# ===========================================================================
# 낙찰업체 집계의 날짜 인덱스 힌트 조건 검증
# ===========================================================================


def _plan(**filters):
    from src.rag.schemas import RetrievalPlan

    return RetrievalPlan(semantic_query="", filters=filters)


def test_date_index_hint_applies_only_without_category():
    """날짜만 걸린 낙찰 집계에만 힌트를 붙입니다.

    category 가 없으면 옵티마이저가 그룹 인덱스(ix_bid_results_bidwinnr_nm)를 골라
    3,267,347행 전부를 훑습니다(2026-08-30 실측 13,446ms, 버퍼 풀이 식으면 최대
    97초). 날짜 인덱스를 강제하면 698ms 로 떨어지며 결과 15행은 완전히 동일합니다.
    category 가 있으면 ix_bid_results_cat_dt_stats 로 182,902행까지 이미 좁혀지므로
    힌트를 주지 않습니다.
    """
    assert structured_data._needs_result_date_index_hint(_plan(date_from="2026-01-01"))
    assert structured_data._needs_result_date_index_hint(_plan(date_to="2026-12-31"))
    assert not structured_data._needs_result_date_index_hint(
        _plan(date_from="2026-01-01", category="Servc")
    )
    assert not structured_data._needs_result_date_index_hint(_plan(category="Servc"))
    assert not structured_data._needs_result_date_index_hint(_plan())


def test_date_index_hint_emits_force_index_for_mysql_only():
    """힌트는 MySQL 방언에서만 나타나고 결과 집합에는 영향을 주지 않습니다."""
    base = (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc())
    )
    hinted = structured_data._hint_result_date_index(base, _plan(date_from="2026-01-01"))
    unhinted = structured_data._hint_result_date_index(
        base, _plan(date_from="2026-01-01", category="Servc")
    )

    from sqlalchemy.dialects import mysql, sqlite

    mysql_sql = str(hinted.compile(dialect=mysql.dialect()))
    assert "FORCE INDEX (ix_bid_results_dt_cat)" in mysql_sql
    assert "FORCE INDEX" not in str(hinted.compile(dialect=sqlite.dialect()))
    assert "FORCE INDEX" not in str(unhinted.compile(dialect=mysql.dialect()))


def test_date_index_hint_preserves_select_and_grouping():
    """힌트가 선택 컬럼, 그룹 기준, 정렬 기준을 바꾸지 않습니다."""
    base = (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc())
    )
    hinted = structured_data._hint_result_date_index(base, _plan(date_from="2026-01-01"))
    assert [c.name for c in base.selected_columns] == [c.name for c in hinted.selected_columns]
    assert str(base.whereclause) == str(hinted.whereclause)
