"""지역 통계 SQL 의 인덱스 활용과 통계 캐시 유지 시간을 고정합니다.

지역 질문("인천 용역 낙찰률")은 기관명 부분 일치(`LIKE '%인천%'`)로 처리되어
선행 와일드카드라 인덱스를 쓰지 못했습니다. 2026-11-22 실측에서 캐시 미적중
응답이 39.36초였고, 그중 공고 집계 세 문장이 38.2초씩 걸렸습니다. 지역 별칭을
정확한 기관명 목록으로 풀어 IN 조건으로 바꾸면 같은 결과를 인덱스 범위
조회로 냅니다. 이 파일은 (a) 바뀐 경로의 결과가 종전 부분 일치와 같은지,
(b) 인덱스 힌트가 MySQL 방언에만 붙는지, (c) 통계 캐시가 24시간인지,
(d) 무효화 접두사가 집계 키를 덮는지 확인합니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import mysql, sqlite

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data as sd
from src.rag.schemas import RetrievalPlan

SEEDED_AT = datetime(2026, 5, 1, 9, 0, 0)
REGION = "인천"
MYSQL_DIALECT = mysql.dialect()
SQLITE_DIALECT = sqlite.dialect()

REGION_INSTITUTIONS = (
    "인천광역시",
    "인천광역시 강화군",
    "인천광역시교육청",
)


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _seed(session) -> None:
    announcements = (
        (1, "인천광역시", "인천 청소 용역", "Servc", 1),
        (2, "인천광역시 강화군", "강화 청소 용역", "Servc", 2),
        (3, "인천광역시교육청", "인천 청소 용역", "Servc", 3),
        (4, "서울특별시", "서울 청소 용역", "Servc", 4),
        (5, "인천광역시", "인천 공사", "Thng", 5),
        (6, "인천광역시 강화군", "강화 청소 용역", "Servc", 6),
    )
    for row_id, institution, name, category, day in announcements:
        session.add(
            BidAnnouncement(
                id=row_id,
                bid_ntce_no=f"REGION-ANN-{row_id:03d}",
                bid_ntce_ord="000",
                bid_ntce_nm=name,
                dminstt_nm=institution,
                bid_ntce_dt=datetime(2026, 5, day, 9, 0, 0),
                category=category,
                raw_data=None,
            )
        )
    results = (
        (1, "인천광역시", "청소업체A", 100_000_000, 88.5, 1),
        (2, "인천광역시 강화군", "청소업체B", 200_000_000, 90.0, 2),
        (3, "서울특별시", "청소업체C", 300_000_000, 80.0, 3),
        (4, "인천광역시교육청", "청소업체D", 50_000_000, None, 4),
    )
    for row_id, institution, winner, amount, rate, day in results:
        session.add(
            BidResult(
                id=row_id,
                bid_ntce_no=f"REGION-RES-{row_id:03d}",
                bid_ntce_ord="00",
                bid_ntce_nm=f"낙찰 {row_id}",
                dminstt_nm=institution,
                bidwinnr_nm=winner,
                sucsf_bid_amt=amount,
                sucsf_bid_rate=rate,
                rl_openg_dt=datetime(2026, 5, day, 9, 0, 0),
                category="Servc",
            )
        )
    session.commit()


def _region_plan() -> RetrievalPlan:
    return RetrievalPlan(
        use_sql=True,
        filters={"category": "Servc", "institution_name": REGION},
    )


def _compiled(stmt, dialect) -> str:
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_resolved_region_scope_matches_partial_match(isolated_db, monkeypatch):
    """지역 별칭을 IN 목록으로 푼 결과가 종전 부분 일치 경로와 같습니다."""
    _seed(isolated_db)
    plan = _region_plan()

    resolved_summary = sd.retrieve_structured_data(isolated_db, plan)["summary"]

    # 종전 동작: 이름 목록이 해석 상한을 넘어 부분 일치로 되돌아간 경로입니다.
    monkeypatch.setattr(sd, "_resolve_institution_scope_names", lambda *args, **kwargs: None)
    cache._local.clear()
    partial_summary = sd.retrieve_structured_data(isolated_db, plan)["summary"]

    assert resolved_summary == partial_summary
    assert resolved_summary["announcement_count"] == 4
    assert resolved_summary["total_bids"] == 3
    assert resolved_summary["average_winning_rate"] == 89.25
    assert resolved_summary["total_winning_amount"] == 350_000_000.0


def test_region_scope_names_are_resolved_exactly(isolated_db):
    """지역 별칭은 부분 일치와 같은 기관명 집합으로 풀립니다."""
    _seed(isolated_db)

    names = sd._resolve_institution_scope_names(isolated_db, BidAnnouncement.dminstt_nm, REGION, [])

    assert set(names or []) == set(REGION_INSTITUTIONS)


def test_region_alias_uses_larger_resolve_limit(isolated_db, monkeypatch):
    """지역 별칭만 큰 상한을 쓰고 다른 검색어는 기본 상한을 지킵니다."""
    names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 50)]
    monkeypatch.setattr(sd, "_institution_name_catalog", lambda db, column: names)

    assert sd._resolve_institution_names(isolated_db, BidAnnouncement.dminstt_nm, REGION) is None
    resolved = sd._resolve_institution_scope_names(
        isolated_db, BidAnnouncement.dminstt_nm, REGION, []
    )
    assert resolved is not None
    assert len(resolved) == len(names)
    assert sd.REGION_NAME_RESOLVE_LIMIT > sd.INSTITUTION_NAME_RESOLVE_LIMIT

    # 지역 별칭이 아닌 검색어는 같은 이름 수에서도 종전 상한으로 되돌아갑니다.
    assert (
        sd._resolve_institution_scope_names(isolated_db, BidAnnouncement.dminstt_nm, "기관", [])
        is None
    )


def test_top_ranking_ties_are_deterministic(isolated_db):
    """동률 순위는 이름 오름차순으로 확정되어 목록 순서가 재현됩니다."""
    _seed(isolated_db)

    summary = sd.retrieve_structured_data(isolated_db, _region_plan())["summary"]

    counts = {item["bid_ntce_nm"]: item["ntce_count"] for item in summary["top_announcements"]}
    assert counts == {"인천 청소 용역": 2, "강화 청소 용역": 2}
    assert [item["bid_ntce_nm"] for item in summary["top_announcements"]] == [
        "강화 청소 용역",
        "인천 청소 용역",
    ]


def test_announcement_scope_hint_is_mysql_only():
    """지역 목록 건수 힌트는 MySQL 에서만 붙고 SQLite 시험 경로에는 남지 않습니다."""
    region_names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 1)]
    stmt = select(func.count(BidAnnouncement.id)).where(
        BidAnnouncement.dminstt_nm.in_(region_names)
    )

    hinted = sd._hint_announcement_resolved_scope(stmt, region_names)

    assert "FORCE INDEX (ix_bid_ann_inst_cat_dt)" in _compiled(hinted, MYSQL_DIALECT)
    assert "FORCE INDEX" not in _compiled(hinted, SQLITE_DIALECT)
    assert sd._hint_announcement_resolved_scope(stmt, region_names[:10]) is stmt
    assert sd._hint_announcement_resolved_scope(stmt, None) is stmt


def test_announcement_name_cover_hint_requires_open_window():
    """공고명 순위 힌트는 지역 목록이고 날짜 범위가 없을 때만 붙습니다."""
    region_names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 1)]
    stmt = select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id)).where(
        BidAnnouncement.dminstt_nm.in_(region_names)
    )
    open_plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    windowed_plan = RetrievalPlan(
        use_sql=True,
        filters={"category": "Servc", "date_from": "2021-11-24", "date_to": "2026-11-22"},
    )

    hinted = sd._hint_announcement_name_cover(stmt, open_plan, region_names)

    assert "FORCE INDEX (ix_bid_ann_inst_cat_ntce)" in _compiled(hinted, MYSQL_DIALECT)
    assert "FORCE INDEX" not in _compiled(hinted, SQLITE_DIALECT)
    assert sd._hint_announcement_name_cover(stmt, windowed_plan, region_names) is stmt
    assert sd._hint_announcement_name_cover(stmt, open_plan, region_names[:10]) is stmt


def test_result_region_hint_picks_index_by_window():
    """낙찰 집계는 날짜 범위 유무에 따라 다른 기관명 선두 인덱스를 씁니다."""
    region_names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 1)]
    stmt = select(func.count(BidResult.id)).where(BidResult.dminstt_nm.in_(region_names))
    open_plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    windowed_plan = RetrievalPlan(
        use_sql=True,
        filters={"category": "Servc", "date_from": "2021-11-24", "date_to": "2026-11-22"},
    )

    open_hinted = sd._hint_result_region_resolved_cover(stmt, open_plan, region_names)
    windowed_hinted = sd._hint_result_region_resolved_cover(
        stmt, windowed_plan, region_names, prefer_window_index=True
    )
    winner_hinted = sd._hint_result_region_resolved_cover(stmt, windowed_plan, region_names)

    assert "FORCE INDEX (ix_bid_results_inst_cat_stats)" in _compiled(open_hinted, MYSQL_DIALECT)
    assert "FORCE INDEX (ix_bid_results_repeat_hist)" in _compiled(windowed_hinted, MYSQL_DIALECT)
    assert "FORCE INDEX (ix_bid_results_inst_cat_stats)" in _compiled(winner_hinted, MYSQL_DIALECT)
    assert "FORCE INDEX" not in _compiled(windowed_hinted, SQLITE_DIALECT)


def test_sample_hint_requires_default_order_and_region_scope():
    """표본 조회 힌트는 정렬 표지가 없는 지역 목록에서만 붙습니다."""
    region_names = [f"인천{i:04d}기관" for i in range(sd.INSTITUTION_NAME_RESOLVE_LIMIT + 1)]
    stmt = select(BidAnnouncement.bid_ntce_no).where(BidAnnouncement.dminstt_nm.in_(region_names))

    hinted = sd._hint_announcement_latest_sample(stmt, {}, region_names)

    assert "FORCE INDEX (ix_bid_ann_dt_cat)" in _compiled(hinted, MYSQL_DIALECT)
    assert "FORCE INDEX" not in _compiled(hinted, SQLITE_DIALECT)
    assert (
        sd._hint_announcement_latest_sample(stmt, {"order_by": "bid_ntce_nm"}, region_names) is stmt
    )
    assert sd._hint_announcement_latest_sample(stmt, {}, region_names[:10]) is stmt


def test_aggregate_cache_ttl_is_24_hours():
    """통계 캐시는 24시간을 유지합니다."""
    assert sd.AGGREGATE_CACHE_TTL == 24 * 60 * 60


def test_invalidation_prefixes_cover_aggregate_keys():
    """수집 뒤 무효화가 집계·다행·순위 키 접두사를 모두 지웁니다."""
    stmt = select(func.count(BidResult.id))

    for prefix in ("rag:agg:", "rag:rows:", "rag:top:"):
        key = sd._stmt_cache_key(prefix, stmt)
        assert any(key.startswith(item) for item in sd.RAG_AGGREGATE_CACHE_PREFIXES)
