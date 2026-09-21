"""
tests/test_benchmark_home_recent_selection.py

홈 최근 공고 선별 실측 하니스(scripts/benchmark_home_recent_selection.py)의 계약을
실제 MySQL·Docker 없이 인메모리 SQLite 로 검증합니다.

이 파일이 증명하는 것:

1. 현재 구현(current)의 호출당 SQL 수는 표본 크기 수(3)를 넘지 않고 변경 전 구현보다
   많지 않으며, 변경 전 구현(legacy)은 같은 데이터 형상에서 조합에 따라 늘어난다.
2. 두 집단이 같은 입력에서 같은 선별 id 목록을 돌려준다.
3. 두 집단의 id 목록이 다르면 하니스가 0 이 아닌 코드로 끝난다.
4. 결과 JSON 에 커밋 SHA, load average 최소·중앙·최대, 버퍼풀 크기, DB 가동 시간,
   공고 행 수가 들어간다.

호출 성공만 보는 테스트는 증명이 아니다. SQL 수 차이와 결과 동일성을 단언한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from scripts.benchmark_home_recent_selection import (
    ALL_RECENT_LIMIT,
    CATEGORY_RECENT_LIMIT,
    CURRENT_GROUP,
    DEFAULT_SCENARIOS,
    LEGACY_GROUP,
    Scenario,
    SelectionMismatchError,
    build_scenarios,
    legacy_recent_unique_announcements,
    main,
    measure_once,
    run_measurement,
)
from src.app.core.db import Base
from src.app.models.bids import BidAnnouncement
from src.app.services import home_context

BASE_TIME = datetime(2026, 9, 20, 12, 0, 0)
CATEGORIES = ("Cnstwk", "Servc", "Thng", "Frgcpt")


# --------------------------------------------------------------------------- #
# 데이터 준비
# --------------------------------------------------------------------------- #


def _new_session(engine=None) -> Session:
    if engine is None:
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


def _latest(db: Session) -> datetime | None:
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
        "bid_ntce_dt": moment,
        "collected_at": moment,
    }


def _clustered_specs(
    count: int,
    *,
    rows_per_key: int,
    category: str = "Servc",
    base: datetime = BASE_TIME,
) -> list[dict[str, Any]]:
    """같은 공고번호를 여러 차수로 반복시켜 중복 제거 압력을 만듭니다.

    rows_per_key 행마다 키가 하나씩 늘어나므로, 서로 다른 키가 limit 만큼 모이려면
    표본을 키워야 합니다. 표본·윈도 조합을 다르게 강제하는 형상을 만들 때 씁니다.
    """
    specs = []
    for index in range(count):
        specs.append(
            _spec(
                index,
                key=f"ANN-{index // rows_per_key:04d}",
                ord_=f"{index % rows_per_key:03d}",
                minutes_ago=index,
                category=category,
                base=base,
            )
        )
    return specs


# --------------------------------------------------------------------------- #
# 시나리오 구성
# --------------------------------------------------------------------------- #


def test_build_scenarios_maps_operational_defaults():
    """기본 시나리오는 운영 홈과 같고, all 은 limit 8, 카테고리는 limit 6 입니다."""
    default_names = tuple(scenario.name for scenario in build_scenarios(DEFAULT_SCENARIOS))
    assert default_names == ("all", *CATEGORIES)

    all_scenario, service_scenario = build_scenarios(["all", "Servc"])
    assert all_scenario.limit == ALL_RECENT_LIMIT
    assert all_scenario.category is None
    assert service_scenario.limit == CATEGORY_RECENT_LIMIT
    assert service_scenario.category == "Servc"


def test_build_scenarios_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_scenarios(["없는시나리오"])


# --------------------------------------------------------------------------- #
# SQL 수 차이
# --------------------------------------------------------------------------- #


def test_current_query_count_bounded_and_legacy_varies_with_combinations():
    """current 는 표본 크기 수(3) 이하이고 legacy 보다 많지 않으며, legacy 는 조합에 따라 늘어납니다."""
    shapes = ((6, 6), (400, 200), (1400, 200))
    scenario = Scenario(name="all", limit=ALL_RECENT_LIMIT, category=None)

    current_counts: list[int] = []
    legacy_counts: list[int] = []
    for count, rows_per_key in shapes:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        db = _new_session(engine)
        _seed(db, _clustered_specs(count, rows_per_key=rows_per_key))
        latest = _latest(db)

        current = measure_once(db, scenario, home_context._recent_unique_announcements, latest)
        legacy = measure_once(db, scenario, legacy_recent_unique_announcements, latest)
        current_counts.append(current["sql_count"])
        legacy_counts.append(legacy["sql_count"])
        assert current["select_count"] <= len(home_context.HOME_RECENT_SAMPLE_SIZES)
        assert legacy["select_count"] > 1

    assert all(count <= len(home_context.HOME_RECENT_SAMPLE_SIZES) for count in current_counts)
    assert all(
        current <= legacy for current, legacy in zip(current_counts, legacy_counts, strict=True)
    )
    assert legacy_counts[0] < legacy_counts[1]
    assert len(set(legacy_counts)) > 1


# --------------------------------------------------------------------------- #
# 결과 동일성
# --------------------------------------------------------------------------- #


def test_groups_return_identical_selection_ids():
    """같은 입력에서 두 집단의 선별 id 와 순서가 같습니다."""
    shapes = ((6, 6), (400, 200), (1400, 200))
    scenarios = build_scenarios(["all", "Servc"])

    for count, rows_per_key in shapes:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        db = _new_session(engine)
        _seed(db, _clustered_specs(count, rows_per_key=rows_per_key))
        latest = _latest(db)

        for scenario in scenarios:
            current = measure_once(db, scenario, home_context._recent_unique_announcements, latest)
            legacy = measure_once(db, scenario, legacy_recent_unique_announcements, latest)
            assert current["announcement_ids"] == legacy["announcement_ids"]


def test_measure_once_records_contract_fields():
    """호출 한 번의 기록은 SQL 수, 벽시계 소요 ms, 반환 id 목록을 담습니다."""
    db = _new_session()
    _seed(db, _clustered_specs(6, rows_per_key=6))

    record = measure_once(
        db,
        Scenario(name="all", limit=ALL_RECENT_LIMIT, category=None),
        home_context._recent_unique_announcements,
        _latest(db),
    )

    assert set(record) == {"sql_count", "select_count", "elapsed_ms", "announcement_ids"}
    assert record["sql_count"] <= len(home_context.HOME_RECENT_SAMPLE_SIZES)
    assert record["elapsed_ms"] >= 0.0
    assert len(record["announcement_ids"]) == len(set(record["announcement_ids"]))


# --------------------------------------------------------------------------- #
# 불일치 시 중단
# --------------------------------------------------------------------------- #


def _reversed_legacy(db, base_stmt, limit, latest):
    return list(reversed(legacy_recent_unique_announcements(db, base_stmt, limit, latest)))


def test_run_measurement_stops_on_group_mismatch():
    """두 집단의 id 목록이 다르면 측정을 중단하고 예외를 올립니다."""
    db = _new_session()
    _seed(db, _clustered_specs(3, rows_per_key=1))

    groups = {
        CURRENT_GROUP: home_context._recent_unique_announcements,
        LEGACY_GROUP: _reversed_legacy,
    }
    with pytest.raises(SelectionMismatchError) as excinfo:
        run_measurement(
            db,
            build_scenarios(["all"]),
            groups,
            rounds=1,
            repeats=1,
            warmup=0,
        )
    assert "scenario=all" in str(excinfo.value)


def test_main_returns_nonzero_on_selection_mismatch():
    """하니스 진입점이 불일치에서 0 이 아닌 코드로 끝납니다."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _seed(_new_session(engine), _clustered_specs(3, rows_per_key=1))

    def factory() -> Session:
        return _new_session(engine)

    exit_code = main(
        ["--scenarios", "all", "--rounds", "1", "--repeats", "1", "--warmup", "0"],
        session_factory=factory,
        group_functions={
            CURRENT_GROUP: home_context._recent_unique_announcements,
            LEGACY_GROUP: _reversed_legacy,
        },
    )

    assert exit_code != 0


# --------------------------------------------------------------------------- #
# 측정 환경 기록
# --------------------------------------------------------------------------- #


def test_main_writes_environment_record_and_raw_rounds(tmp_path):
    """성공 실행이 원시 기록과 측정 환경을 담은 JSON 을 남깁니다."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    seeded = _clustered_specs(6, rows_per_key=6)
    _seed(_new_session(engine), seeded)

    output = tmp_path / "home_recent_selection.json"
    exit_code = main(
        [
            "--scenarios",
            "all",
            "--rounds",
            "1",
            "--repeats",
            "3",
            "--warmup",
            "1",
            "--output",
            str(output),
        ],
        session_factory=lambda: _new_session(engine),
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))

    environment = payload["environment"]
    assert isinstance(environment["git_sha"], str)
    assert environment["git_sha"]
    assert environment["git_dirty"] in (True, False, None)
    assert environment["python_version"]
    assert environment["platform"]
    assert set(environment["load_average"]["normalized_percent"]) == {"min", "median", "max"}

    db_environment = environment["db"]
    assert db_environment["innodb_buffer_pool_size_bytes"] is None or isinstance(
        db_environment["innodb_buffer_pool_size_bytes"], int
    )
    assert db_environment["uptime_seconds"] is None or isinstance(
        db_environment["uptime_seconds"], int
    )
    assert db_environment["bid_announcements_rows"] == len(seeded)

    assert payload["config"]["latest_collected_at"] is not None
    repetitions = payload["scenarios"][0]["rounds"][0]["repetitions"]
    assert len(repetitions) == 3 * 2
    for record in repetitions:
        assert record["group"] in (CURRENT_GROUP, LEGACY_GROUP)
        assert {"sql_count", "elapsed_ms", "announcement_ids"} <= set(record)
    current_records = [record for record in repetitions if record["group"] == CURRENT_GROUP]
    assert all(
        record["sql_count"] <= len(home_context.HOME_RECENT_SAMPLE_SIZES)
        for record in current_records
    )
