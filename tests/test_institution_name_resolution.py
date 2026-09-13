"""
tests/test_institution_name_resolution.py

기관명 2단계 해석 계약 검증.

기관명 부분 일치를 정확한 이름 목록으로 먼저 푼 뒤 등호로 조회합니다. 한글 음절만으로 된 검색어는
고유 기관명 목록 캐시에서 고르고, 그 밖의 검색어는 해석 질의를 씁니다. 콜드에서 문장당
16~28초가 4.5~4.9초로 줄었습니다(docs/analysis/rag_coldsql_root_cause_20260913.md).
결과 행 집합은 부분 일치와 같아야 하며, 이름이 상한을 넘으면 부분 일치로 돌아갑니다.

통합 테스트는 실제 MySQL 에서 두 방식의 id 집합을 직접 대조합니다.
    uv run pytest tests/test_institution_name_resolution.py -m mysql_integration -v
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.schemas import RetrievalPlan


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def query_path(monkeypatch):
    """한글 전용 검색어도 목록 경로 대신 해석 질의 경로를 타게 합니다."""
    monkeypatch.setattr(structured_data, "_catalog_eligible", lambda name: False)


def _plan(**filters) -> RetrievalPlan:
    return RetrievalPlan(use_sql=True, filters=filters)


def _sql(conditions) -> str:
    stmt = select(BidAnnouncement.id).where(*conditions)
    return str(stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))


def _seed(db: Session) -> None:
    names = ["세종특별자치시 교육청", "세종특별자치시", "서울특별시", None]
    for index, name in enumerate(names):
        db.add(BidAnnouncement(bid_ntce_no=f"A{index}", dminstt_nm=name, category="Cnstwk"))
        db.add(BidResult(bid_ntce_no=f"R{index}", dminstt_nm=name, category="Cnstwk"))
    db.commit()


def test_conditions_use_in_when_names_resolved():
    plan = _plan(institution_name="세종특별자치시")

    resolved = _sql(
        structured_data._announcement_conditions(plan, institution_names=["세종특별자치시"])
    )
    legacy = _sql(structured_data._announcement_conditions(plan))

    assert "dminstt_nm IN ('세종특별자치시')" in resolved
    assert "LIKE" not in resolved
    assert "LIKE concat('%%', '세종특별자치시', '%%')" in legacy


def test_availability_conditions_follow_resolved_names():
    plan = _plan(institution_name="세종")
    conditions = structured_data._result_availability_conditions(plan, institution_names=["세종"])
    compiled = str(
        select(BidResult.id)
        .where(*conditions)
        .compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "dminstt_nm IN ('세종')" in compiled


def test_resolver_returns_distinct_matching_names(isolated_db):
    _seed(isolated_db)

    names = structured_data._resolve_institution_names(
        isolated_db, BidAnnouncement.dminstt_nm, "세종특별자치시"
    )

    assert sorted(names) == ["세종특별자치시", "세종특별자치시 교육청"]


def test_resolver_falls_back_when_names_exceed_limit(isolated_db, monkeypatch):
    _seed(isolated_db)
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)

    assert (
        structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")
        is None
    )


def test_resolver_caches_names(isolated_db, monkeypatch):
    _seed(isolated_db)
    structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")

    def fail_execute(*args, **kwargs):
        raise AssertionError("캐시 적중 시 DB 를 다시 조회하면 안 됩니다")

    monkeypatch.setattr(isolated_db, "execute", fail_execute)

    names = structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")

    assert sorted(names) == ["세종특별자치시", "세종특별자치시 교육청"]


def test_overflow_is_cached_long_and_name_lists_short(isolated_db, monkeypatch, query_path):
    _seed(isolated_db)
    stored: list[tuple[dict, int]] = []
    monkeypatch.setattr(cache, "set", lambda key, value, ttl: stored.append((value, ttl)))
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)

    assert (
        structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")
        is None
    )
    assert structured_data._resolve_institution_names(
        isolated_db, BidResult.dminstt_nm, "서울특별시"
    ) == ["서울특별시"]

    assert stored == [
        ({"overflow": True}, structured_data.INSTITUTION_OVERFLOW_CACHE_TTL),
        ({"names": ["서울특별시"]}, structured_data.AGGREGATE_CACHE_TTL),
    ]
    assert structured_data.INSTITUTION_OVERFLOW_CACHE_TTL > structured_data.AGGREGATE_CACHE_TTL


def test_cached_overflow_skips_database(isolated_db, monkeypatch, query_path):
    _seed(isolated_db)
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)
    structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")

    def fail_execute(*args, **kwargs):
        raise AssertionError("상한 초과가 캐시돼 있으면 해석 질의를 다시 돌리면 안 됩니다")

    monkeypatch.setattr(isolated_db, "execute", fail_execute)

    assert (
        structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")
        is None
    )


def test_legacy_oversized_name_list_still_falls_back(monkeypatch, query_path):
    """배포 전에 저장된 1,001개짜리 이름 목록 캐시도 되돌림으로 읽습니다."""
    monkeypatch.setattr(structured_data, "INSTITUTION_NAME_RESOLVE_LIMIT", 1)
    monkeypatch.setattr(structured_data, "_timed_cache_get", lambda key: {"names": ["a", "b"]})

    assert structured_data._resolve_institution_names(None, BidResult.dminstt_nm, "a") is None


def test_catalog_serves_other_terms_without_database(isolated_db, monkeypatch):
    _seed(isolated_db)
    structured_data._resolve_institution_names(isolated_db, BidResult.dminstt_nm, "세종")

    def fail_execute(*args, **kwargs):
        raise AssertionError("목록이 캐시돼 있으면 다른 한글 검색어도 DB 를 조회하면 안 됩니다")

    monkeypatch.setattr(isolated_db, "execute", fail_execute)

    assert structured_data._resolve_institution_names(
        isolated_db, BidResult.dminstt_nm, "서울"
    ) == ["서울특별시"]


@pytest.mark.parametrize("term", ["세종 교육청", "LH", "(주)", "제2해병", "세종%"])
def test_non_hangul_terms_use_resolution_query(term):
    assert structured_data._catalog_eligible(term) is False


def test_catalog_is_per_table(isolated_db):
    _seed(isolated_db)
    isolated_db.add(BidResult(bid_ntce_no="R9", dminstt_nm="세종낙찰전용", category="Cnstwk"))
    isolated_db.commit()

    assert "세종낙찰전용" in structured_data._resolve_institution_names(
        isolated_db, BidResult.dminstt_nm, "세종"
    )
    assert "세종낙찰전용" not in structured_data._resolve_institution_names(
        isolated_db, BidAnnouncement.dminstt_nm, "세종"
    )


def test_uncertain_name_falls_back_to_resolution_query():
    assert structured_data._match_institution_catalog(["대\ufff9중소기업", "광주"], "대중") is None
    assert structured_data._match_institution_catalog(["대\ufff9중소기업", "광주"], "광주") == [
        "광주"
    ]


@pytest.mark.parametrize("term", ["세종특별자치시", "서울", "없는기관명"])
def test_resolved_rows_equal_substring_rows(isolated_db, term):
    _seed(isolated_db)
    plan = _plan(institution_name=term)
    names = structured_data._resolve_institution_names(
        isolated_db, BidAnnouncement.dminstt_nm, term
    )

    legacy = set(
        isolated_db.scalars(
            select(BidAnnouncement.id).where(*structured_data._announcement_conditions(plan))
        )
    )
    resolved = set(
        isolated_db.scalars(
            select(BidAnnouncement.id).where(
                *structured_data._announcement_conditions(plan, institution_names=names)
            )
        )
    )

    assert resolved == legacy


def _mysql_engine():
    url = os.environ.get("MYSQL_TEST_URL")
    if not url or "mysql" not in url:
        return None
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.mark.mysql_integration
@pytest.mark.parametrize("term", ["서울회생법원", "유성구", "세종특별자치시"])
@pytest.mark.parametrize("model", [BidAnnouncement, BidResult])
def test_mysql_resolved_id_set_equals_substring(term, model):
    engine = _mysql_engine()
    if engine is None:
        pytest.skip("MYSQL_TEST_URL 이 없거나 MySQL 에 연결할 수 없습니다")

    with Session(engine) as db:
        names = structured_data._resolve_institution_names(db, model.dminstt_nm, term)
        assert names is not None
        legacy = set(
            db.scalars(
                select(model.id).where(model.dminstt_nm.contains(term), model.category == "Cnstwk")
            )
        )
        resolved = set(
            db.scalars(
                select(model.id).where(model.dminstt_nm.in_(names), model.category == "Cnstwk")
            )
        )

    assert resolved == legacy
