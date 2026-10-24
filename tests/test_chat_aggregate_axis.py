"""
tests/test_chat_aggregate_axis.py

축별 집계(분류·기관·지역)의 결과 키와 SQL 형태를 검증합니다.

기존 summary 키를 바꾸지 않고 axis_breakdown/aggregate_meta 를 가법적으로
추가하는 계약, 문자열 라벨이 캐시 미스에서도 살아남는 계약, 기관별 공고 건수가
기존 institution_ranking 을 재사용해 추가 SELECT 를 내지 않는 계약을 고정합니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event, func, select

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import _cached_rows, retrieve_structured_data


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _clear_cache() -> None:
    cache._local.clear()


class _SelectCounter:
    """엔진이 실행한 SELECT 문 수를 세는 컨텍스트 관리자입니다."""

    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self) -> _SelectCounter:
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc) -> bool:
        event.remove(self._engine, "before_cursor_execute", self._record)
        return False

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self.statements.append(statement)

    @property
    def count(self) -> int:
        return len(self.statements)


def _seed_result(
    session,
    *,
    row_id: int,
    institution: str,
    opened_at: datetime,
    rate: float | None,
    category: str = "Thng",
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=1000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def _seed_announcement(
    session,
    *,
    row_id: int,
    institution: str,
    ntce_dt: datetime,
    category: str = "Thng",
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ANN-{row_id}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bid_ntce_dt=ntce_dt,
            category=category,
            raw_data=None,
        )
    )


def _window(**overrides):
    filters = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    filters.update(overrides)
    return filters


def test_category_axis_announcement_count_returns_breakdown(isolated_db):
    """분류별 공고 건수는 분류 4행을 라벨과 함께 돌려줍니다."""
    now = datetime(2026, 5, 1, 9, 0, 0)
    _seed_announcement(
        isolated_db, row_id=1, institution="서울특별시", ntce_dt=now, category="Servc"
    )
    _seed_announcement(
        isolated_db, row_id=2, institution="부산광역시", ntce_dt=now, category="Servc"
    )
    _seed_announcement(
        isolated_db, row_id=3, institution="대구광역시", ntce_dt=now, category="Thng"
    )
    _seed_announcement(
        isolated_db, row_id=4, institution="인천광역시", ntce_dt=now, category="Cnstwk"
    )
    _seed_announcement(
        isolated_db, row_id=5, institution="광주광역시", ntce_dt=now, category="Frgcpt"
    )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters=_window(group_by="category", metric="announcement_count"),
    )
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    breakdown = summary["axis_breakdown"]
    assert len(breakdown) == 4
    servc = next(item for item in breakdown if item["label"] == "용역")
    assert servc["key"] == "Servc"
    assert servc["announcement_count"] == 2
    assert servc["avg_rate"] is None
    assert summary["aggregate_meta"]["group_by"] == "category"
    assert summary["aggregate_meta"]["metric"] == "announcement_count"
    assert summary["aggregate_meta"]["window"] == {
        "date_from": "2026-01-01",
        "date_to": "2026-12-31",
    }


def test_category_axis_avg_rate_keeps_none_for_empty_samples(isolated_db):
    """낙찰률이 모두 NULL 인 축은 0.0 이 아니라 None 이고 표본 수도 0 입니다."""
    now = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, institution="서울특별시", opened_at=now, rate=90.0)
    _seed_result(isolated_db, row_id=2, institution="부산광역시", opened_at=now, rate=80.0)
    _seed_result(
        isolated_db, row_id=3, institution="대구광역시", opened_at=now, rate=None, category="Frgcpt"
    )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters=_window(group_by="category", metric="avg_rate"),
    )
    breakdown = retrieve_structured_data(isolated_db, plan)["summary"]["axis_breakdown"]

    thng = next(item for item in breakdown if item["key"] == "Thng")
    assert thng["bid_count"] == 2
    assert thng["avg_rate"] == pytest.approx(85.0, rel=1e-4)
    assert thng["sample_count"] == 2

    frgcpt = next(item for item in breakdown if item["key"] == "Frgcpt")
    assert frgcpt["avg_rate"] is None
    assert frgcpt["sample_count"] == 0


def test_institution_axis_reuses_ranking_without_extra_select(isolated_db):
    """기관별 공고 건수는 기존 institution_ranking 을 그대로 써서 SELECT 수가 늘지 않습니다."""
    now = datetime(2026, 5, 1, 9, 0, 0)
    institutions = ("가나다교육청", "라마바교육청", "사아자교육청")
    row_id = 1
    for index, institution in enumerate(institutions):
        for offset in range(index + 2):
            _seed_announcement(
                isolated_db,
                row_id=row_id,
                institution=institution,
                ntce_dt=now.replace(day=offset + 1),
            )
            row_id += 1
    isolated_db.commit()
    engine = isolated_db.get_bind()

    base_plan = RetrievalPlan(use_sql=True, filters=_window(metric="announcement_count"))
    axis_plan = RetrievalPlan(
        use_sql=True,
        filters=_window(group_by="institution", metric="announcement_count"),
    )

    _clear_cache()
    with _SelectCounter(engine) as base_counter:
        retrieve_structured_data(isolated_db, base_plan)

    _clear_cache()
    with _SelectCounter(engine) as axis_counter:
        summary = retrieve_structured_data(isolated_db, axis_plan)["summary"]

    counts = {item["label"]: item["announcement_count"] for item in summary["axis_breakdown"]}
    assert counts == {"가나다교육청": 2, "라마바교육청": 3, "사아자교육청": 4}
    assert axis_counter.count == base_counter.count


def test_region_axis_matches_full_name_aliases(isolated_db):
    """충청북도 같은 정식 명칭이 충북 라벨로 묶입니다."""
    now = datetime(2026, 5, 1, 9, 0, 0)
    _seed_announcement(isolated_db, row_id=1, institution="충청북도교육청", ntce_dt=now)
    _seed_announcement(isolated_db, row_id=2, institution="충청북도교육청", ntce_dt=now)
    _seed_announcement(isolated_db, row_id=3, institution="충북대학교", ntce_dt=now)
    _seed_announcement(isolated_db, row_id=4, institution="서울특별시", ntce_dt=now)
    _seed_announcement(isolated_db, row_id=5, institution="경상북도", ntce_dt=now)
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters=_window(group_by="region", metric="announcement_count"),
    )
    result = retrieve_structured_data(isolated_db, plan)
    breakdown = {
        item["label"]: item["announcement_count"] for item in result["summary"]["axis_breakdown"]
    }

    assert breakdown["충북"] == 3
    assert breakdown["서울"] == 1
    assert breakdown["경북"] == 1
    assert any("지역 구분은 기관명 부분 일치" in hint for hint in result["insufficiency_hints"])


def test_axis_keys_absent_without_axis_marker(isolated_db):
    """축 마커가 없는 질문에는 axis_breakdown/aggregate_meta 를 넣지 않습니다."""
    plan = build_retrieval_plan("용역 공고 건수")
    assert "group_by" not in plan.filters

    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert "axis_breakdown" not in summary
    assert "aggregate_meta" not in summary


@pytest.mark.parametrize(
    ("query", "axis", "metric"),
    [
        ("분류별 평균 낙찰률 알려줘", "category", "avg_rate"),
        ("기관별 평균 낙찰률 알려줘", "institution", "avg_rate"),
        ("분류별 공고 건수 알려줘", "category", "announcement_count"),
        ("지역별 공고 건수 알려줘", "region", "announcement_count"),
    ],
)
def test_required_axis_questions_set_group_by_and_metric(query, axis, metric):
    """프로브 R10·R13·S01·S07 질문이 축과 지표를 정확히 고릅니다."""
    filters = build_retrieval_plan(query).filters

    assert filters.get("group_by") == axis
    assert filters.get("metric") == metric
    assert filters.get("group_limit") == 20
    assert "result_limit" not in filters
    assert "announcement_limit" not in filters


def test_quarter_announcement_count_question_records_time_axis():
    """S06 질문은 축을 time 으로 기록해 응답 단계가 공고 건수를 고르게 합니다."""
    filters = build_retrieval_plan("2026년 분기별 공고 건수 추이 알려줘").filters

    assert filters.get("group_by") == "time"
    assert filters.get("metric") == "announcement_count"
    assert "group_limit" not in filters


class _RowsSession:
    """여러 행 집계 결과를 돌려주는 최소 세션 대역입니다."""

    def __init__(self, rows):
        self.rows = rows
        self.executions = 0

    def execute(self, _stmt):
        self.executions += 1
        return self

    def all(self):
        return self.rows


def test_cached_rows_accepts_string_labels(isolated_db):
    """문자열 라벨은 캐시 미스의 값 정규화에서 float 변환을 타지 않습니다."""
    db = _RowsSession([("용역", 10), (None, 1)])
    stmt = (
        select(BidAnnouncement.category, func.count())
        .where(BidAnnouncement.category == "Servc")
        .group_by(BidAnnouncement.category)
    )

    first = _cached_rows(db, stmt)
    second = _cached_rows(db, stmt)

    assert first == [("용역", 10), (None, 1)]
    assert second == first
    assert db.executions == 1
    assert structured_data._cacheable("용역") == "용역"
