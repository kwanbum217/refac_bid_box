"""
tests/test_home_context_query_count.py

홈 최근 공고 선별의 결과 동일성과 질의 수 계약을 검증합니다.

수정 전 구현은 표본 크기(50/200/1000)와 수집일 윈도우(1/3/7)를 이중으로 순회하며
조합마다 SELECT 를 새로 냈습니다. 최악의 경우 3 x 3 + 3 = 12회이고, 호출 지점이
공통 1회 + 분야 4회이므로 홈 한 번에 수십 회가 됩니다.

이 파일이 증명하는 것:

1. 결과 동일성 - 수정 전 알고리즘을 참조 구현으로 그대로 옮겨 두고, 빈 표, 중복
   밀집, 윈도우 분산, 시각 동률, 분야 필터, 최대 표본이 필요한 대규모 형상에서
   선별 id 와 순서가 같음을 단언합니다.
2. 질의 수 - 첫 표본에서 limit 을 채우는 형상에서는 SELECT 1회와 읽는 행 50 이하를,
   어떤 형상에서도 호출당 SELECT 3회 이하와 참조 구현 이하를 단언합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.bids import BidAnnouncement
from src.app.services import home_context
from src.app.services.home_context import (
    HOME_RECENT_DAY_WINDOWS,
    HOME_RECENT_SAMPLE_SIZES,
    _recent_unique_announcements,
)

BASE_TIME = datetime(2026, 9, 20, 12, 0, 0)
CATEGORIES = ("Servc", "Thng", "Cnstwk", "Frgcpt")


# --------------------------------------------------------------------------- #
# 계측과 참조 구현
# --------------------------------------------------------------------------- #


def _limit_value(statement: str, parameters: Any) -> int | None:
    """실행된 SQL 의 LIMIT 값입니다. LIMIT 절이 없으면 None 입니다.

    SQLite 는 LIMIT 을 바인딩하므로 문장에는 ? 로 남고, 값은 앞선 조건절의 바인딩
    수만큼 뒤에 온 같은 순서의 파라미터 자리에 있습니다.
    """
    limit_index = statement.upper().find("LIMIT")
    if limit_index < 0:
        return None
    if not isinstance(parameters, (tuple, list)):
        return None
    position = statement[:limit_index].count("?")
    if position >= len(parameters):
        return None
    value = parameters[position]
    return int(value) if isinstance(value, int) else None


class _QueryRecorder:
    """세션에 실행된 SQL 문과 그 LIMIT 값을 순서대로 모읍니다."""

    def __init__(self, session: Session) -> None:
        self.connection = session.get_bind()
        self.statements: list[str] = []
        self.limit_values: list[int | None] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(statement)
        self.limit_values.append(_limit_value(statement, parameters))

    def __enter__(self) -> _QueryRecorder:
        event.listen(self.connection, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: Any) -> bool:
        event.remove(self.connection, "before_cursor_execute", self._record)
        return False

    def select_count(self) -> int:
        return len(
            [
                statement
                for statement in self.statements
                if statement.lstrip().upper().startswith("SELECT")
            ]
        )

    def select_limits(self) -> list[int]:
        """SELECT 문이 스스로 제한한 행 수(LIMIT) 목록입니다. LIMIT 없는 SELECT 는 빠집니다."""
        limits: list[int] = []
        for statement, limit in zip(self.statements, self.limit_values, strict=True):
            if limit is None:
                continue
            if statement.lstrip().upper().startswith("SELECT"):
                limits.append(limit)
        return limits

    def selection_select_count(self) -> int:
        """최근 공고 선별 질의(수집일 내림차순 정렬)만 셉니다."""
        marker = f"{BidAnnouncement.__tablename__}.collected_at DESC"
        return len([statement for statement in self.statements if marker in statement])


def _legacy_dedupe(candidates: list[BidAnnouncement], limit: int) -> list[BidAnnouncement]:
    seen: set[tuple[str, str]] = set()
    selected: list[BidAnnouncement] = []

    for announcement in candidates:
        key = (announcement.category, announcement.bid_ntce_no)
        if key in seen:
            continue

        seen.add(key)
        selected.append(announcement)
        if len(selected) >= limit:
            break

    return selected


def _legacy_recent_unique_announcements(db, base_stmt, limit: int, latest_collected_at):
    """수정 전 home_context.py 의 이중 순회 구현 스냅샷입니다.

    표본 크기마다, 윈도우마다 SELECT 를 새로 냈고 best_effort 누적 규칙도 그대로
    옮겼습니다. 이 참조본과 결과가 다르면 리팩터링이 판정을 바꾼 것입니다.
    """
    ordered_stmt = base_stmt.order_by(
        BidAnnouncement.collected_at.desc(),
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    )
    best_effort: list[BidAnnouncement] = []

    def collect_from(stmt) -> list[BidAnnouncement]:
        nonlocal best_effort

        for sample_size in HOME_RECENT_SAMPLE_SIZES:
            candidates = list(db.execute(stmt.limit(sample_size)).scalars().all())
            if not candidates:
                return best_effort

            selected = _legacy_dedupe(candidates, limit)
            if len(selected) > len(best_effort):
                best_effort = selected

            if len(selected) >= limit or len(candidates) < sample_size:
                return selected

        return best_effort

    if latest_collected_at is not None:
        for day_window in HOME_RECENT_DAY_WINDOWS:
            window_start = latest_collected_at - timedelta(days=day_window)
            selected = collect_from(
                ordered_stmt.where(BidAnnouncement.collected_at >= window_start)
            )
            if len(selected) >= limit:
                return selected[:limit]

    return collect_from(ordered_stmt)[:limit]


# --------------------------------------------------------------------------- #
# 데이터 준비
# --------------------------------------------------------------------------- #


def _new_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _seed(db: Session, specs: list[dict[str, Any]]) -> None:
    db.add_all([BidAnnouncement(**spec) for spec in specs])
    db.commit()


def _latest_collected_at(db: Session) -> datetime | None:
    return db.scalar(select(func.max(BidAnnouncement.collected_at)))


def _spec(
    index: int,
    *,
    key: str,
    ord_: str,
    minutes_ago: int,
    category: str = "Servc",
    base: datetime = BASE_TIME,
) -> dict[str, Any]:
    moment = base - timedelta(minutes=minutes_ago)
    return {
        "bid_ntce_no": key,
        "bid_ntce_ord": ord_,
        "bid_ntce_nm": f"공고 {key} {ord_}",
        "category": category,
        "base_amount": 1_000_000 + index,
        "presmpt_prce": 990_000 + index,
        "bid_ntce_dt": moment,
        "collected_at": moment,
    }


def _clustered_specs(
    count: int,
    *,
    rows_per_key: int,
    minutes_step: int = 1,
    base: datetime = BASE_TIME,
) -> list[dict[str, Any]]:
    """같은 공고번호를 여러 차수로 반복시켜 중복 제거 압력을 만듭니다.

    rows_per_key 행마다 키가 하나씩 늘어나므로, 서로 다른 키가 limit 만큼 모이려면
    표본을 키워야 합니다. 최대 표본(1000)까지 읽어야 하는 형상도 이 함수로 만듭니다.
    """
    specs = []
    for index in range(count):
        specs.append(
            _spec(
                index,
                key=f"ANN-{index // rows_per_key:04d}",
                ord_=f"{index % rows_per_key:03d}",
                minutes_ago=index * minutes_step,
                base=base,
            )
        )
    return specs


def _seeded_specs(
    seed: int,
    count: int,
    *,
    key_pool: int,
    step_choices: tuple[int, ...],
) -> list[dict[str, Any]]:
    """키 중복 밀도와 수집일 분산을 무작위로 섞은 형상입니다. 시드는 고정입니다."""
    rng = np.random.default_rng(seed)
    counters: dict[tuple[str, str], int] = {}
    specs = []
    minutes_ago = 0
    for index in range(count):
        minutes_ago += int(rng.choice(step_choices))
        key = f"ANN-{int(rng.integers(key_pool)):04d}"
        category = CATEGORIES[int(rng.integers(len(CATEGORIES)))]
        slot = counters.get((key, category), 0)
        counters[(key, category)] = slot + 1
        specs.append(
            _spec(
                index,
                key=key,
                ord_=f"{slot:03d}",
                minutes_ago=minutes_ago,
                category=category,
            )
        )
    return specs


# --------------------------------------------------------------------------- #
# 단언 도우미
# --------------------------------------------------------------------------- #


def _statement(base_stmt=None):
    return base_stmt if base_stmt is not None else select(BidAnnouncement)


def _assert_same_selection(db, *, limit: int, latest_collected_at, base_stmt=None) -> list[int]:
    legacy = _legacy_recent_unique_announcements(
        db, _statement(base_stmt), limit, latest_collected_at
    )
    fixed = _recent_unique_announcements(db, _statement(base_stmt), limit, latest_collected_at)

    legacy_ids = [row.id for row in legacy]
    fixed_ids = [row.id for row in fixed]
    assert fixed_ids == legacy_ids
    return fixed_ids


def _count_selection_selects(db, *, limit: int, latest_collected_at, base_stmt=None) -> int:
    recorder = _QueryRecorder(db)
    with recorder:
        _recent_unique_announcements(db, _statement(base_stmt), limit, latest_collected_at)
    return recorder.select_count()


def _count_legacy_selects(db, *, limit: int, latest_collected_at, base_stmt=None) -> int:
    recorder = _QueryRecorder(db)
    with recorder:
        _legacy_recent_unique_announcements(db, _statement(base_stmt), limit, latest_collected_at)
    return recorder.select_count()


def _context_select_counts(db: Session) -> tuple[int, int]:
    """홈 컨텍스트 한 번의 (전체 SELECT 수, 최근 공고 선별 SELECT 수) 입니다."""
    recorder = _QueryRecorder(db)
    with recorder:
        home_context.get_home_page_context(db)
    return recorder.select_count(), recorder.selection_select_count()


# --------------------------------------------------------------------------- #
# 결과 동일성
# --------------------------------------------------------------------------- #


def test_recent_selection_constants_are_part_of_the_contract():
    """표본 크기와 윈도우 값은 판정 규칙의 일부이므로 값을 고정합니다."""
    assert HOME_RECENT_SAMPLE_SIZES == (50, 200, 1000)
    assert HOME_RECENT_DAY_WINDOWS == (1, 3, 7)


def test_selection_matches_legacy_algorithm_on_empty_table():
    """공고가 없으면 윈도우를 순회해도 빈 선별입니다."""
    db = _new_session()

    assert _assert_same_selection(db, limit=8, latest_collected_at=None) == []
    assert _assert_same_selection(db, limit=8, latest_collected_at=BASE_TIME) == []


def test_selection_matches_legacy_algorithm_on_window_spread_dataset():
    """1일 안쪽, 3일·7일 경계, 7일 밖 행을 섞어 윈도우 폴백을 지나갑니다."""
    db = _new_session()
    minutes_ago_values = (
        10,
        30,
        60,
        90,
        60 * 12,
        60 * 24 * 2,
        60 * 24 * 5,
        60 * 24 * 9,
        60 * 24 * 20,
    )
    _seed(
        db,
        [
            _spec(index, key=f"ANN-SPREAD-{index:02d}", ord_="000", minutes_ago=minutes_ago)
            for index, minutes_ago in enumerate(minutes_ago_values)
        ],
    )

    selected = _assert_same_selection(db, limit=8, latest_collected_at=_latest_collected_at(db))

    # 7일 윈도우가 limit 8 을 채우고 9일·20일 행은 폴백까지 내려가야 보입니다.
    assert len(selected) == 8


def test_selection_matches_legacy_algorithm_when_largest_sample_is_required():
    """서로 다른 키 8개가 모이려면 1,000행 표본까지 읽어야 하는 형상입니다."""
    db = _new_session()
    _seed(db, _clustered_specs(1300, rows_per_key=130))

    selected = _assert_same_selection(db, limit=8, latest_collected_at=_latest_collected_at(db))

    assert len(selected) == 8


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_selection_matches_legacy_algorithm_on_seeded_datasets(seed):
    """중복 밀도와 수집일 분산을 섞은 형상에서도 판정이 같습니다."""
    db = _new_session()
    _seed(db, _seeded_specs(seed, 260, key_pool=24, step_choices=(1, 45, 1440, 10080)))
    latest = _latest_collected_at(db)

    for limit in (8, 6):
        _assert_same_selection(db, limit=limit, latest_collected_at=latest)

    _assert_same_selection(
        db,
        limit=6,
        latest_collected_at=latest,
        base_stmt=select(BidAnnouncement).where(BidAnnouncement.category == "Servc"),
    )


def test_selection_order_uses_notice_time_then_id_when_collected_at_ties():
    """수집일시가 같으면 공고일시 내림차순, 그것도 같으면 id 내림차순입니다."""
    db = _new_session()
    collected = BASE_TIME - timedelta(hours=1)
    # 공고일시를 삽입 순서와 어긋나게 두고, 마지막 행은 공고일시가 같은 동률로 둡니다.
    notice_offsets = (3, 5, 1, 0, 4, 2)
    rows: list[BidAnnouncement] = []
    for offset in notice_offsets:
        row = BidAnnouncement(
            bid_ntce_no=f"ANN-ORD-{offset}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"정렬 공고 {offset}",
            category="Servc",
            bid_ntce_dt=collected - timedelta(minutes=offset),
            collected_at=collected,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    tie = BidAnnouncement(
        bid_ntce_no="ANN-ORD-TIE",
        bid_ntce_ord="000",
        bid_ntce_nm="정렬 공고 동률",
        category="Servc",
        bid_ntce_dt=collected - timedelta(minutes=5),
        collected_at=collected,
    )
    db.add(tie)
    db.commit()

    selected = _recent_unique_announcements(
        db,
        select(BidAnnouncement),
        limit=8,
        latest_collected_at=collected,
    )

    # 공고일시가 최근인 행이 앞이고, 동률이면 id 가 큰 행이 앞입니다.
    assert [row.id for row in selected] == [
        rows[3].id,
        rows[2].id,
        rows[5].id,
        rows[0].id,
        rows[4].id,
        tie.id,
        rows[1].id,
    ]


# --------------------------------------------------------------------------- #
# 질의 수
# --------------------------------------------------------------------------- #


def test_first_sample_fills_limit_uses_one_query_and_reads_at_most_first_sample():
    """첫 표본에서 limit 을 채우는 형상은 SELECT 1회와 읽는 행 50 이하로 끝납니다."""
    db = _new_session()
    _seed(db, _clustered_specs(400, rows_per_key=1))
    latest = _latest_collected_at(db)

    for base_stmt, limit in (
        (select(BidAnnouncement), 8),
        (select(BidAnnouncement).where(BidAnnouncement.category == "Servc"), 6),
    ):
        recorder = _QueryRecorder(db)
        with recorder:
            selected = _recent_unique_announcements(db, base_stmt, limit, latest)

        assert len(selected) == limit
        assert recorder.select_count() == 1
        assert recorder.select_limits() == [HOME_RECENT_SAMPLE_SIZES[0]]


def test_query_count_bounded_by_sample_sizes_regardless_of_data_scale():
    """어떤 데이터 규모에서도 선별 한 번의 SELECT 가 표본 크기 수(3) 이하이고 참조 구현 이하입니다."""
    scale_shapes = ((6, 6), (400, 200), (1400, 200))
    current_counts = []
    legacy_counts = []

    for count, rows_per_key in scale_shapes:
        db = _new_session()
        _seed(db, _clustered_specs(count, rows_per_key=rows_per_key))
        latest = _latest_collected_at(db)
        current_counts.append(_count_selection_selects(db, limit=8, latest_collected_at=latest))
        legacy_counts.append(_count_legacy_selects(db, limit=8, latest_collected_at=latest))

    assert all(count <= len(HOME_RECENT_SAMPLE_SIZES) for count in current_counts)
    assert all(
        current <= legacy for current, legacy in zip(current_counts, legacy_counts, strict=True)
    )


def test_query_count_reduced_versus_legacy_double_loop():
    """이중 순회는 표본·윈도 조합 수만큼 질의를 내고, 점진 확대는 그보다 적습니다."""
    db = _new_session()
    _seed(db, _clustered_specs(1400, rows_per_key=200))
    latest = _latest_collected_at(db)

    legacy_count = _count_legacy_selects(db, limit=8, latest_collected_at=latest)
    current_count = _count_selection_selects(db, limit=8, latest_collected_at=latest)
    worst_case = len(HOME_RECENT_DAY_WINDOWS) * len(HOME_RECENT_SAMPLE_SIZES) + len(
        HOME_RECENT_SAMPLE_SIZES
    )

    assert legacy_count == worst_case
    assert current_count <= len(HOME_RECENT_SAMPLE_SIZES)
    assert current_count < legacy_count


def test_home_page_context_query_count_never_above_legacy_across_data_scale(monkeypatch):
    """홈 컨텍스트 전체의 SELECT 수가 어떤 데이터 규모에서도 참조 구현보다 많지 않습니다."""
    scale_shapes = ((6, 6), (400, 200), (1400, 200))
    calls_per_page = 1 + len(home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
    current_counts = []

    for index, (count, rows_per_key) in enumerate(scale_shapes):
        db = _new_session()
        _seed(
            db,
            _clustered_specs(
                count,
                rows_per_key=rows_per_key,
                base=BASE_TIME - timedelta(days=index),
            ),
        )
        current_counts.append(_context_select_counts(db))

    monkeypatch.setattr(
        home_context, "_recent_unique_announcements", _legacy_recent_unique_announcements
    )
    legacy_counts = []

    for index, (count, rows_per_key) in enumerate(scale_shapes):
        db = _new_session()
        _seed(
            db,
            _clustered_specs(
                count,
                rows_per_key=rows_per_key,
                base=BASE_TIME - timedelta(days=10 + index),
            ),
        )
        legacy_counts.append(_context_select_counts(db))

    for (current_total, current_selection), (legacy_total, _) in zip(
        current_counts, legacy_counts, strict=True
    ):
        assert current_selection <= calls_per_page * len(HOME_RECENT_SAMPLE_SIZES)
        assert current_total < legacy_total
