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
from src.app.models.bids import BidAnnouncement, BidResult
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
    """상위 N 실시간 경로용 세션 대역. 순위 질의와 손상 스냅샷 마커를 구분해 반환합니다."""

    def __init__(self, rows, corrupted=None, skipped: int = 0):
        self.rows = rows
        self.corrupted = corrupted
        self.skipped = skipped if skipped else (1 if corrupted else 0)
        self.executions = 0

    def execute(self, _stmt):
        self.executions += 1
        self._last = _stmt
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.corrupted

    def scalar(self, _stmt=None):
        return self.skipped


def _live_stmt(category: str):
    return (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .where(BidResult.category == category)
        .group_by(BidResult.bidwinnr_nm)
    )


def _top(db, category: str = "", dataset: str = "bid_results", dimension: str = "bidwinnr_nm"):
    return structured_data._top_rows(
        db,
        scope=None,
        dataset=dataset,
        dimension=dimension,
        category=category,
        live_stmt=_live_stmt(category),
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


def test_winner_group_index_ignore_applies_to_institution_without_date():
    """기관명 조건만 걸린 낙찰업체 집계에만 그룹 인덱스 배제 힌트를 붙입니다.

    날짜 범위가 없으면 옵티마이저가 ix_bid_results_bidwinnr_nm 으로 339만 항목을 훑으며
    행마다 본문을 읽습니다("서울" 완전 콜드 7,159~13,218ms). 배제하면 1,258~1,470ms 였고
    결과는 같습니다. 날짜 범위가 있으면 날짜 인덱스 강제가 더 좁히므로 붙이지 않습니다.
    """
    needs = structured_data._needs_result_winner_group_index_ignore
    assert needs(_plan(institution_name="서울"))
    assert needs(_plan(institution_name="서울", category="Servc"))
    assert not needs(_plan(institution_name="서울", date_from="2026-01-01"))
    assert not needs(_plan(category="Servc"))
    assert not needs(_plan())


def test_winner_hints_never_combine_date_force_and_group_ignore():
    """두 힌트의 적용 조건이 겹치지 않아 한 문장에 FORCE 와 IGNORE 가 함께 나오지 않습니다."""
    from sqlalchemy.dialects import mysql, sqlite

    base = (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc())
    )

    def hinted(plan):
        return structured_data._hint_result_winner_group_index(
            structured_data._hint_result_date_index(base, plan), plan
        )

    institution_only = str(hinted(_plan(institution_name="서울")).compile(dialect=mysql.dialect()))
    with_date = str(
        hinted(_plan(institution_name="서울", date_from="2026-01-01")).compile(
            dialect=mysql.dialect()
        )
    )

    assert "IGNORE INDEX (ix_bid_results_bidwinnr_nm)" in institution_only
    assert "FORCE INDEX" not in institution_only
    assert "FORCE INDEX (ix_bid_results_dt_cat)" in with_date
    assert "IGNORE INDEX" not in with_date
    assert "IGNORE INDEX" not in str(
        hinted(_plan(institution_name="서울")).compile(dialect=sqlite.dialect())
    )


def test_announcement_cover_hint_applies_only_to_like_fallback_with_category():
    """상한 초과로 부분 일치에 되돌아간 기관명과 category 가 함께 걸릴 때만 커버링 인덱스를 강제합니다.

    "광주"+Servc 에서 옵티마이저가 category 인덱스로 211만 행 본문을 흩어 읽었습니다(COUNT 완전 콜드
    16,086~50,236ms). 커버링 인덱스를 강제하면 1,136~1,589ms 였고 결과는 같았습니다.
    """
    needs = structured_data._needs_announcement_institution_cover_hint
    assert needs(_plan(institution_name="광주", category="Servc"), None)
    assert not needs(_plan(institution_name="광주", category="Servc"), ["광주광역시"])
    assert not needs(_plan(institution_name="서울"), None)
    assert not needs(_plan(institution_name="광주", category="Servc", date_from="2026-01-01"), None)
    assert not needs(_plan(category="Servc"), None)


def test_announcement_cover_and_date_hints_never_combine():
    from sqlalchemy.dialects import mysql

    from src.app.models.bids import BidAnnouncement

    base = select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id)).group_by(
        BidAnnouncement.dminstt_nm
    )

    def hinted(plan, names=None):
        stmt = structured_data._hint_announcement_date_index(base, plan)
        stmt = structured_data._hint_announcement_institution_cover(stmt, plan, names)
        return str(stmt.compile(dialect=mysql.dialect()))

    covered = hinted(_plan(institution_name="광주", category="Servc"))
    dated = hinted(_plan(institution_name="광주", date_from="2026-01-01"))

    assert "FORCE INDEX (ix_bid_ann_inst_cat_ntce)" in covered
    assert "ix_bid_ann_dt_cat" not in covered
    assert "FORCE INDEX (ix_bid_ann_dt_cat)" in dated
    assert "ix_bid_ann_inst_cat_ntce" not in dated
    assert "FORCE INDEX" not in hinted(
        _plan(institution_name="광주", category="Servc"), ["광주광역시"]
    )


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


# ===========================================================================
# 공고(발주기관/공고명) 집계의 날짜 인덱스 힌트 조건 검증
# ===========================================================================


def test_announcement_date_index_hint_applies_only_without_category():
    """날짜만 걸린 공고 집계에만 힌트를 붙입니다."""
    assert structured_data._needs_announcement_date_index_hint(_plan(date_from="2026-01-01"))
    assert structured_data._needs_announcement_date_index_hint(_plan(date_to="2026-12-31"))
    assert not structured_data._needs_announcement_date_index_hint(
        _plan(date_from="2026-01-01", category="Servc")
    )
    assert not structured_data._needs_announcement_date_index_hint(_plan(category="Servc"))
    assert not structured_data._needs_announcement_date_index_hint(_plan())


def test_announcement_date_index_hint_emits_force_index_for_mysql_only():
    """공고 힌트는 MySQL 방언에서만 나타나고 SQLite 등에는 나타나지 않습니다."""
    base = (
        select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.count(BidAnnouncement.id).desc())
    )
    hinted = structured_data._hint_announcement_date_index(base, _plan(date_from="2026-01-01"))
    unhinted = structured_data._hint_announcement_date_index(
        base, _plan(date_from="2026-01-01", category="Servc")
    )

    from sqlalchemy.dialects import mysql, sqlite

    mysql_sql = str(hinted.compile(dialect=mysql.dialect()))
    assert "FORCE INDEX (ix_bid_ann_dt_cat)" in mysql_sql
    assert "FORCE INDEX" not in str(hinted.compile(dialect=sqlite.dialect()))
    assert "FORCE INDEX" not in str(unhinted.compile(dialect=mysql.dialect()))


def test_announcement_date_index_hint_preserves_select_and_grouping():
    """공고 힌트가 선택 컬럼, 그룹 기준, 정렬 기준, where 절을 바꾸지 않습니다."""
    base = (
        select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
        .group_by(BidAnnouncement.bid_ntce_nm)
        .order_by(func.count(BidAnnouncement.id).desc())
    )
    hinted = structured_data._hint_announcement_date_index(base, _plan(date_from="2026-01-01"))
    assert [c.name for c in base.selected_columns] == [c.name for c in hinted.selected_columns]
    assert str(base.whereclause) == str(hinted.whereclause)


# ===========================================================================
# 손상 행 탐지 및 제외 플래그 판정 검증
# ===========================================================================


def test_top_rows_dropped_true_when_corrupted_rows_present():
    """반환 행에 손상 문자가 포함되어 있으면 제외되고 dropped 가 참이 됩니다."""
    db = RowSession([("손상업체\ufffd", 100), ("정상건설", 50)])

    kept, dropped = _top(db, "Cnstwk")

    assert dropped == 1
    assert kept == [("정상건설", 50)]


def test_top_rows_dropped_true_when_snapshot_marker_exists():
    """반환 행은 정상이나 스냅샷에 손상 제외 마커(rank=0)가 있으면 dropped 가 참이 됩니다."""
    db = RowSession([("정상건설", 50)], skipped=1)

    kept, dropped = _top(db, "Cnstwk")

    assert dropped == 1
    assert kept == [("정상건설", 50)]


def test_top_rows_dropped_false_when_clean_and_no_marker():
    """반환 행도 정상이고 스냅샷 마커도 없으면 dropped 가 거짓이 됩니다."""
    db = RowSession([("정상건설", 50)], skipped=0)

    kept, dropped = _top(db, "Cnstwk")

    assert dropped == 0
    assert kept == [("정상건설", 50)]
