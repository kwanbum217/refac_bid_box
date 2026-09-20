"""
tests/test_structured_data.py

정형 통계 조회의 루프 집계를 일괄 집계로 바꾼 뒤에도 응답 값이 그대로이고,
발생하는 SELECT 수가 대상 건수와 무관하게 고정됨을 증명합니다.

- 다중 기관 비교: 기관 수와 무관하게 집계 1회 + 최신 결과 1회
- 분기 시계열: 분기 수와 무관하게 낙찰 집계 1회 + 공고 집계 1회
- 결과가 없는 기관·분기는 기존과 같은 기본값(건수 0, 비율 0.0)으로 채움

호출 성공만 확인하는 테스트는 증명이 아닙니다. 아래 질의 수 테스트는 실제
엔진이 실행한 SELECT 문 수를 세어 대상 건수가 늘어도 늘지 않음을 단언합니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


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
    opened_at: datetime | None,
    rate: float | None = None,
    amount: int = 1000,
    ntce_no: str | None = None,
    category: str = "Thng",
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=ntce_no or f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=amount,
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
    ntce_dt: datetime | None,
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


# ===========================================================================
# 질의 수 고정 증명
# ===========================================================================


def test_multi_institution_select_count_is_constant(isolated_db):
    """기관 수가 2개든 4개든 발생하는 SELECT 수가 늘지 않습니다."""
    now = datetime(2026, 5, 1, 10, 0, 0)
    institutions = ["가나다교육청", "라마바교육청", "사아자교육청", "차카타교육청"]
    for index, name in enumerate(institutions):
        for offset in range(2):
            _seed_result(
                isolated_db,
                row_id=index * 10 + offset + 1,
                institution=name,
                opened_at=now.replace(day=offset + 1),
                rate=90.0,
            )
    isolated_db.commit()
    engine = isolated_db.get_bind()

    small_plan = RetrievalPlan(use_sql=True, filters={"institution_names": institutions[:2]})
    big_plan = RetrievalPlan(use_sql=True, filters={"institution_names": institutions})

    _clear_cache()
    with _SelectCounter(engine) as small_counter:
        small_result = retrieve_structured_data(isolated_db, small_plan)

    _clear_cache()
    with _SelectCounter(engine) as big_counter:
        big_result = retrieve_structured_data(isolated_db, big_plan)

    assert len(small_result["summary"]["by_institution"]) == 2
    assert len(big_result["summary"]["by_institution"]) == 4
    # 기관 수가 두 배가 되어도 질의 수는 그대로여야 합니다.
    assert small_counter.count == big_counter.count
    # 기관별 루프 질의가 남아 있으면 기관 수에 비례해 이 상한을 넘습니다.
    assert small_counter.count <= 3
    assert big_counter.count <= 3


def test_quarter_series_select_count_is_constant(isolated_db):
    """분기 수가 4개든 8개든 발생하는 SELECT 수가 늘지 않습니다."""
    for year in (2024, 2025):
        for quarter in range(1, 5):
            month = (quarter - 1) * 3 + 1
            _seed_result(
                isolated_db,
                row_id=year * 10 + quarter,
                institution="서울특별시",
                opened_at=datetime(year, month, 15, 10, 0, 0),
                rate=90.0,
            )
            _seed_announcement(
                isolated_db,
                row_id=year * 10 + quarter,
                institution="서울특별시",
                ntce_dt=datetime(year, month, 10, 10, 0, 0),
            )
    isolated_db.commit()
    engine = isolated_db.get_bind()

    small_plan = RetrievalPlan(
        use_sql=True,
        filters={
            "time_bucket": "quarter",
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        },
    )
    big_plan = RetrievalPlan(
        use_sql=True,
        filters={
            "time_bucket": "quarter",
            "date_from": "2024-01-01",
            "date_to": "2025-12-31",
        },
    )

    _clear_cache()
    with _SelectCounter(engine) as small_counter:
        small_result = retrieve_structured_data(isolated_db, small_plan)

    _clear_cache()
    with _SelectCounter(engine) as big_counter:
        big_result = retrieve_structured_data(isolated_db, big_plan)

    assert len(small_result["summary"]["time_series"]) == 4
    assert len(big_result["summary"]["time_series"]) == 8
    # 분기 수가 두 배가 되어도 질의 수는 그대로여야 합니다.
    assert small_counter.count == big_counter.count


# ===========================================================================
# 응답 값·순서·기본값 보존
# ===========================================================================


def test_multi_institution_values_and_missing_defaults(isolated_db):
    """입력 기관 순서와 값이 유지되고, 창 밖 기관은 기존 기본값으로 채워집니다."""
    in_window = datetime(2026, 5, 10, 10, 0, 0)
    for offset in range(3):
        _seed_result(
            isolated_db,
            row_id=offset + 1,
            institution="서울특별시교육청",
            opened_at=in_window.replace(day=offset + 1),
            rate=80.0 + offset + 1,
        )
    # 부산 기관은 카탈로그에는 있으나 조회 기간 밖에만 실적이 있습니다.
    _seed_result(
        isolated_db,
        row_id=99,
        institution="부산광역시교육청",
        opened_at=datetime(2025, 1, 10, 10, 0, 0),
        rate=50.0,
    )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "institution_names": ["서울특별시교육청", "부산광역시교육청"],
            "date_from": "2026-05-01",
            "date_to": "2026-05-31",
        },
    )
    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    by_institution = summary["by_institution"]

    assert [item["institution_name"] for item in by_institution] == [
        "서울특별시교육청",
        "부산광역시교육청",
    ]

    seoul = by_institution[0]
    assert seoul["bid_count"] == 3
    assert seoul["avg_rate"] == pytest.approx(82.0, rel=1e-4)
    assert len(seoul["recent_results"]) == 3

    busan = by_institution[1]
    assert busan["bid_count"] == 0
    assert busan["avg_rate"] == 0.0
    assert busan["recent_results"] == []

    assert summary["total_bids"] == 3
    assert summary["average_winning_rate"] == pytest.approx(82.0, rel=1e-4)


def test_multi_institution_recent_results_cap_and_order(isolated_db):
    """기관별 최신 3건 상한과 개찰일 내림차순 정렬이 유지됩니다."""
    for offset in range(5):
        _seed_result(
            isolated_db,
            row_id=offset + 1,
            institution="서울특별시교육청",
            opened_at=datetime(2026, 5, offset + 1, 9, 0, 0),
            rate=90.0,
            ntce_no=f"R{offset + 1}",
        )
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"institution_names": ["서울특별시교육청"]})
    recent = retrieve_structured_data(isolated_db, plan)["summary"]["by_institution"][0][
        "recent_results"
    ]

    assert len(recent) == 3
    assert [item["bid_ntce_no"] for item in recent] == ["R5", "R4", "R3"]


def test_quarter_series_values_and_empty_defaults(isolated_db):
    """분기 순서·label·반올림이 유지되고 실적 없는 분기는 0/0.0 입니다."""
    _seed_result(
        isolated_db,
        row_id=1,
        institution="서울특별시",
        opened_at=datetime(2026, 2, 10, 9, 0, 0),
        rate=91.2345,
    )
    _seed_result(
        isolated_db,
        row_id=2,
        institution="서울특별시",
        opened_at=datetime(2026, 8, 10, 9, 0, 0),
        rate=88.0,
    )
    _seed_announcement(
        isolated_db,
        row_id=1,
        institution="서울특별시",
        ntce_dt=datetime(2026, 2, 5, 9, 0, 0),
    )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "time_bucket": "quarter",
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        },
    )
    series = retrieve_structured_data(isolated_db, plan)["summary"]["time_series"]

    assert [item["label"] for item in series] == [
        "2026년 1분기",
        "2026년 2분기",
        "2026년 3분기",
        "2026년 4분기",
    ]
    assert series[0]["avg_rate"] == pytest.approx(91.2345, rel=1e-6)
    assert series[0]["bid_count"] == 1
    assert series[0]["announcement_count"] == 1
    assert series[0]["ntce_count"] == 1

    empty = series[1]
    assert empty["bid_count"] == 0
    assert empty["avg_rate"] == 0.0
    assert empty["announcement_count"] == 0

    assert series[2]["avg_rate"] == pytest.approx(88.0, rel=1e-6)
    assert series[2]["bid_count"] == 1
