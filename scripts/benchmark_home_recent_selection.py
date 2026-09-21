"""
scripts/benchmark_home_recent_selection.py

홈 최근 공고 선별의 이중 순회 질의 제거(D8) 효과 실측 하니스.

측정 대상은 src/app/services/home_context.py 의
``_recent_unique_announcements(db, base_stmt, limit, latest_collected_at)`` 이다.
운영 호출은 두 형태다.

- 전체 최근 공고: ``base_stmt=select(BidAnnouncement)``, ``limit=8``
- 카테고리 구획: ``base_stmt=select(BidAnnouncement).where(category == 코드)``, ``limit=6``

집단은 두 가지다.

- ``current``: 현재 구현(전역 정렬 접두를 표본 크기 50/200/1000 순서로 필요할 때만 확대)
- ``legacy``: 변경 전 구현(9db0a46d^ 스냅샷, 표본·윈도 이중 순회)을 본 파일에 그대로 옮긴 것

한 회차 안에서 두 집단을 교차 순서로 실행한다. 같은 입력에 대해 두 집단이 돌려준
id 목록이 다르면 그 즉시 ``SelectionMismatchError`` 를 올려 0 이 아닌 코드로 끝낸다.
동일성이 깨진 상태의 소요 비교는 의미가 없기 때문이다.

발행 SQL 수는 SQLAlchemy 엔진의 ``before_cursor_execute`` 이벤트로 센다. 호출 한 번의
기록은 SQL 수, 벽시계 소요 ms, 반환 공고 id 목록이다.

이 하니스는 읽기 전용이다. 어떤 테이블에도 쓰기를 하지 않고 commit 을 부르지 않는다.
측정 환경(커밋 SHA, 정규화 1분 load average, DB 버퍼풀 크기, DB 가동 시간, 공고 행 수,
파이썬 버전과 플랫폼)을 결과 JSON 에 함께 남긴다. 규약은
docs/ops/latency_gate_protocol.md 5.3 과 5.4 이다.

실행 예:

    uv run python scripts/benchmark_home_recent_selection.py \\
        --scenarios all Servc --rounds 3 --repeats 30 --warmup 3 \\
        --output data/benchmarks/home_recent_selection.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import event, func, select, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts.benchmark_provenance import get_git_status  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.services import home_context  # noqa: E402

CURRENT_GROUP = "current"
LEGACY_GROUP = "legacy"
GROUP_ORDER: tuple[str, str] = (CURRENT_GROUP, LEGACY_GROUP)
ALL_GROUPS: tuple[str, ...] = GROUP_ORDER

SCENARIO_ALL = "all"
ALL_RECENT_LIMIT = 8
CATEGORY_RECENT_LIMIT = 6
DEFAULT_SCENARIOS: tuple[str, ...] = (
    SCENARIO_ALL,
    *home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
)
SCENARIO_CHOICES: tuple[str, ...] = (
    SCENARIO_ALL,
    *home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
)

LOAD_SAMPLE_INTERVAL_SECONDS = 5.0

# 호출 한 번의 서명: (db, base_stmt, limit, latest_collected_at) -> 선별된 공고 목록
SelectionFn = Callable[[Session, Any, int, "datetime | None"], list[BidAnnouncement]]

__all__ = [
    "ALL_GROUPS",
    "ALL_RECENT_LIMIT",
    "CATEGORY_RECENT_LIMIT",
    "CURRENT_GROUP",
    "DEFAULT_GROUP_FUNCTIONS",
    "DEFAULT_SCENARIOS",
    "LEGACY_GROUP",
    "LoadAverageSampler",
    "Scenario",
    "SelectionMismatchError",
    "SqlCounter",
    "build_scenarios",
    "collect_db_environment",
    "collect_environment",
    "legacy_recent_unique_announcements",
    "main",
    "measure_once",
    "run_measurement",
    "sample_normalized_load_percent",
]


class SelectionMismatchError(RuntimeError):
    """두 집단이 같은 입력에서 다른 선별 결과를 돌려줬을 때 발생합니다."""


@dataclass(frozen=True)
class Scenario:
    """측정 시나리오 한 건. ``category`` 가 None 이면 전체 최근 공고이다."""

    name: str
    limit: int
    category: str | None

    def base_stmt(self):
        if self.category is None:
            return select(BidAnnouncement)
        return select(BidAnnouncement).where(BidAnnouncement.category == self.category)


def build_scenarios(selected: Sequence[str]) -> list[Scenario]:
    """선택된 이름 목록을 시나리오 객체로 바꿉니다. 알 수 없는 이름은 거부합니다."""
    scenarios: list[Scenario] = []
    for name in selected:
        if name == SCENARIO_ALL:
            scenarios.append(Scenario(name=name, limit=ALL_RECENT_LIMIT, category=None))
        elif name in home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES:
            scenarios.append(Scenario(name=name, limit=CATEGORY_RECENT_LIMIT, category=name))
        else:
            raise ValueError(f"알 수 없는 시나리오입니다: {name}")
    return scenarios


def legacy_recent_unique_announcements(
    db: Session,
    base_stmt,
    limit: int,
    latest_collected_at: datetime | None,
) -> list[BidAnnouncement]:
    """커밋 9db0a46d 이전 home_context.py 의 이중 순회 구현 스냅샷입니다.

    로직을 고치거나 다듬지 않고 그대로 옮겼습니다. 표본 크기마다, 윈도우마다
    SELECT 를 새로 냈고 best_effort 누적 규칙도 원문 그대로입니다. 표본 크기와
    윈도우 상수, 중복 제거 헬퍼는 현재 모듈의 것을 그대로 씁니다.
    """
    ordered_stmt = base_stmt.order_by(
        BidAnnouncement.collected_at.desc(),
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    )
    best_effort: list[BidAnnouncement] = []

    def collect_from(stmt) -> list[BidAnnouncement]:
        nonlocal best_effort

        for sample_size in home_context.HOME_RECENT_SAMPLE_SIZES:
            candidates = list(db.execute(stmt.limit(sample_size)).scalars().all())
            if not candidates:
                return best_effort

            selected = home_context._dedupe_announcements(candidates, limit)
            if len(selected) > len(best_effort):
                best_effort = selected

            if len(selected) >= limit or len(candidates) < sample_size:
                return selected

        return best_effort

    if latest_collected_at is not None:
        for day_window in home_context.HOME_RECENT_DAY_WINDOWS:
            window_start = latest_collected_at - timedelta(days=day_window)
            selected = collect_from(
                ordered_stmt.where(BidAnnouncement.collected_at >= window_start)
            )
            if len(selected) >= limit:
                return selected[:limit]

    return collect_from(ordered_stmt)[:limit]


DEFAULT_GROUP_FUNCTIONS: dict[str, SelectionFn] = {
    CURRENT_GROUP: home_context._recent_unique_announcements,
    LEGACY_GROUP: legacy_recent_unique_announcements,
}


class SqlCounter:
    """엔진에 걸린 SQL 문을 순서대로 모읍니다. 카운터 자체는 SQL 을 내지 않습니다."""

    def __init__(self, bind: Any) -> None:
        self.bind = bind
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(statement)

    def __enter__(self) -> SqlCounter:
        event.listen(self.bind, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: Any) -> bool:
        event.remove(self.bind, "before_cursor_execute", self._record)
        return False

    @property
    def sql_count(self) -> int:
        return len(self.statements)

    @property
    def select_count(self) -> int:
        return sum(
            1 for statement in self.statements if statement.lstrip().upper().startswith("SELECT")
        )


def latest_collected_at(session: Session) -> datetime | None:
    """bid_announcements 의 collected_at 최대값입니다. 두 집단이 같은 입력을 받도록 한 번만 구합니다."""
    return session.scalar(select(func.max(BidAnnouncement.collected_at)))


def measure_once(
    session: Session,
    scenario: Scenario,
    selection_fn: SelectionFn,
    latest: datetime | None,
) -> dict[str, Any]:
    """선별 함수를 한 번 호출하고 SQL 수, 벽시계 소요 ms, 반환 id 목록을 기록합니다."""
    counter = SqlCounter(session.get_bind())
    with counter:
        started = time.perf_counter()
        rows = selection_fn(session, scenario.base_stmt(), scenario.limit, latest)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "sql_count": counter.sql_count,
        "select_count": counter.select_count,
        "elapsed_ms": round(elapsed_ms, 6),
        "announcement_ids": [row.id for row in rows],
    }


def _percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _summarize_group(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    elapsed = [float(record["elapsed_ms"]) for record in records]
    sql_counts = sorted({int(record["sql_count"]) for record in records})
    return {
        "n": len(records),
        "sql_count": {
            "min": sql_counts[0],
            "max": sql_counts[-1],
            "values": sql_counts,
            "all_equal": len(sql_counts) == 1,
        },
        "elapsed_ms": {
            "median": statistics.median(elapsed),
            "p95": _percentile(elapsed, 95.0),
            "min": min(elapsed),
            "max": max(elapsed),
        },
    }


def _summarize_round(
    round_index: int,
    repetitions: Sequence[Mapping[str, Any]],
    warmup: int,
) -> dict[str, Any]:
    counted = [record for record in repetitions if not record["warmup"]]
    groups: dict[str, Any] = {}
    for group in ALL_GROUPS:
        groups[group] = _summarize_group([record for record in counted if record["group"] == group])
    current_median = groups[CURRENT_GROUP]["elapsed_ms"]["median"]
    legacy_median = groups[LEGACY_GROUP]["elapsed_ms"]["median"]
    current_p95 = groups[CURRENT_GROUP]["elapsed_ms"]["p95"]
    legacy_p95 = groups[LEGACY_GROUP]["elapsed_ms"]["p95"]
    return {
        "round": round_index,
        "warmup_repetitions": warmup,
        "repetitions": list(repetitions),
        CURRENT_GROUP: groups[CURRENT_GROUP],
        LEGACY_GROUP: groups[LEGACY_GROUP],
        "difference_ms": {
            "median": legacy_median - current_median,
            "p95": legacy_p95 - current_p95,
            "ratio_median": (legacy_median / current_median) if current_median else None,
        },
    }


def _group_aggregate(rounds: Sequence[Mapping[str, Any]], group: str) -> dict[str, Any]:
    medians = [float(entry[group]["elapsed_ms"]["median"]) for entry in rounds]
    p95s = [float(entry[group]["elapsed_ms"]["p95"]) for entry in rounds]
    sql_min = [int(entry[group]["sql_count"]["min"]) for entry in rounds]
    sql_max = [int(entry[group]["sql_count"]["max"]) for entry in rounds]
    worst_median = max(rounds, key=lambda entry: entry[group]["elapsed_ms"]["median"])
    worst_p95 = max(rounds, key=lambda entry: entry[group]["elapsed_ms"]["p95"])
    return {
        "sql_count": {
            "min": min(sql_min),
            "max": max(sql_max),
            "all_rounds_equal": len(set(sql_min) | set(sql_max)) == 1,
        },
        "elapsed_ms": {
            "median_by_round": medians,
            "p95_by_round": p95s,
            "worst_round_by_median": {
                "round": worst_median["round"],
                "median_ms": worst_median[group]["elapsed_ms"]["median"],
                "p95_ms": worst_median[group]["elapsed_ms"]["p95"],
            },
            "worst_round_by_p95": {
                "round": worst_p95["round"],
                "median_ms": worst_p95[group]["elapsed_ms"]["median"],
                "p95_ms": worst_p95[group]["elapsed_ms"]["p95"],
            },
        },
    }


def _summarize_scenario(scenario: Scenario, rounds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    delta_medians = [float(entry["difference_ms"]["median"]) for entry in rounds]
    delta_p95s = [float(entry["difference_ms"]["p95"]) for entry in rounds]
    worst_delta = max(rounds, key=lambda entry: entry["difference_ms"]["median"])
    return {
        "scenario": scenario.name,
        "category": scenario.category,
        "limit": scenario.limit,
        "rounds": list(rounds),
        "aggregate": {
            CURRENT_GROUP: _group_aggregate(rounds, CURRENT_GROUP),
            LEGACY_GROUP: _group_aggregate(rounds, LEGACY_GROUP),
            "difference_ms": {
                "median_by_round": delta_medians,
                "p95_by_round": delta_p95s,
                "worst_round_by_median": {
                    "round": worst_delta["round"],
                    "median": worst_delta["difference_ms"]["median"],
                    "p95": worst_delta["difference_ms"]["p95"],
                },
            },
        },
    }


def run_measurement(
    session: Session,
    scenarios: Sequence[Scenario],
    groups: Mapping[str, SelectionFn],
    *,
    rounds: int,
    repeats: int,
    warmup: int,
) -> list[dict[str, Any]]:
    """시나리오별로 두 집단을 교차 순서로 실행하고 기록을 모읍니다.

    반복마다 집단 순서를 뒤집어 실행 순서 편향을 없앱니다. 같은 반복에서 두 집단의
    id 목록이 다르면 즉시 ``SelectionMismatchError`` 를 올립니다.
    """
    if warmup >= repeats:
        raise ValueError("warmup 은 repeats 보다 작아야 합니다.")
    latest = latest_collected_at(session)

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        round_summaries: list[dict[str, Any]] = []
        for round_index in range(rounds):
            repetitions: list[dict[str, Any]] = []
            for repetition in range(repeats):
                order = GROUP_ORDER if repetition % 2 == 0 else GROUP_ORDER[::-1]
                per_group: dict[str, dict[str, Any]] = {}
                for position, group in enumerate(order):
                    record = measure_once(session, scenario, groups[group], latest)
                    record.update(
                        {
                            "group": group,
                            "round": round_index,
                            "repetition": repetition,
                            "order_position": position,
                            "warmup": repetition < warmup,
                        }
                    )
                    per_group[group] = record
                    repetitions.append(record)

                current_ids = per_group[CURRENT_GROUP]["announcement_ids"]
                legacy_ids = per_group[LEGACY_GROUP]["announcement_ids"]
                if current_ids != legacy_ids:
                    raise SelectionMismatchError(
                        "선별 결과 불일치: "
                        f"scenario={scenario.name} round={round_index} "
                        f"repetition={repetition} "
                        f"current={current_ids} legacy={legacy_ids}"
                    )

            round_summaries.append(_summarize_round(round_index, repetitions, warmup))
        results.append(_summarize_scenario(scenario, round_summaries))
    return results


def _command_output(command: list[str]) -> str | None:
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)  # nosec B603
    except (OSError, subprocess.CalledProcessError):
        return None
    output = output.strip()
    return output or None


def _cpu_count() -> int:
    raw = _command_output(["sysctl", "-n", "hw.ncpu"])
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return os.cpu_count() or 1


def _load_average_1m() -> float | None:
    raw = _command_output(["sysctl", "-n", "vm.loadavg"])
    if raw is not None:
        parts = raw.strip("{} ").split()
        if parts:
            try:
                return float(parts[0])
            except ValueError:
                pass
    try:
        load_1m, _, _ = os.getloadavg()
    except (OSError, AttributeError):
        return None
    return load_1m


def sample_normalized_load_percent() -> dict[str, Any]:
    """정규화 1분 load average(%) 한 표본입니다. 규약 5.3 의 지표 정의를 따릅니다."""
    cpu_count = _cpu_count()
    load_1m = _load_average_1m()
    normalized = (100.0 * load_1m / cpu_count) if load_1m is not None else None
    return {
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "load_1m": load_1m,
        "cpu_count": cpu_count,
        "normalized_percent": normalized,
    }


class LoadAverageSampler:
    """측정 동안 5초 간격으로 정규화 1분 load average 를 표본하는 백그라운드 수집기입니다."""

    def __init__(
        self,
        interval_seconds: float = LOAD_SAMPLE_INTERVAL_SECONDS,
        sample_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self._sample_fn = sample_fn if sample_fn is not None else sample_normalized_load_percent
        self.samples: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _record(self) -> None:
        self.samples.append(self._sample_fn())

    def _run(self) -> None:
        self._record()
        while not self._stop_event.wait(self.interval_seconds):
            self._record()

    def start(self) -> LoadAverageSampler:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1.0)
        if not self.samples:
            self._record()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        values = [
            float(sample["normalized_percent"])
            for sample in self.samples
            if sample.get("normalized_percent") is not None
        ]
        if values:
            stats: dict[str, float | None] = {
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
        else:
            stats = {"min": None, "median": None, "max": None}
        return {
            "interval_seconds": self.interval_seconds,
            "cpu_count": self.samples[0]["cpu_count"] if self.samples else _cpu_count(),
            "sample_count": len(self.samples),
            "normalized_percent": stats,
            "samples": list(self.samples),
        }


def collect_db_environment(session: Session) -> dict[str, Any]:
    """DB 버퍼풀 크기, 가동 시간, 공고 행 수를 읽습니다. 읽기 전용입니다."""
    errors: list[str] = []

    rows: int | None = None
    try:
        rows = session.scalar(select(func.count(BidAnnouncement.id)))
    except SQLAlchemyError as exc:
        session.rollback()
        errors.append(f"bid_announcements_rows: {type(exc).__name__}")

    buffer_pool_bytes: int | None = None
    try:
        value = session.execute(text("SELECT @@innodb_buffer_pool_size")).scalar()
        buffer_pool_bytes = int(value) if value is not None else None
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        session.rollback()
        errors.append(f"innodb_buffer_pool_size: {type(exc).__name__}")

    uptime_seconds: int | None = None
    try:
        row = session.execute(text("SHOW GLOBAL STATUS LIKE 'Uptime'")).first()
        if row is not None and len(row) >= 2:
            uptime_seconds = int(row[1])
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        session.rollback()
        errors.append(f"uptime: {type(exc).__name__}")

    return {
        "innodb_buffer_pool_size_bytes": buffer_pool_bytes,
        "uptime_seconds": uptime_seconds,
        "bid_announcements_rows": rows,
        "errors": errors,
    }


def collect_environment(session: Session, load_summary: Mapping[str, Any]) -> dict[str, Any]:
    """결과 해석에 필요한 측정 환경을 모읍니다. 규약 5.3 과 5.4 의 항목입니다."""
    git_sha, git_dirty = get_git_status(PROJECT_ROOT)
    return {
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "load_average": dict(load_summary),
        "db": collect_db_environment(session),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="홈 최근 공고 선별 D8 효과 실측 하니스")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(DEFAULT_SCENARIOS),
        choices=list(SCENARIO_CHOICES),
        help="측정할 시나리오. all 은 전체 최근 공고(limit=8), 카테고리 코드는 limit=6. 기본은 운영 홈과 같은 전부",
    )
    parser.add_argument("--rounds", type=int, default=3, help="회차 수")
    parser.add_argument("--repeats", type=int, default=30, help="회차당 반복 수")
    parser.add_argument("--warmup", type=int, default=3, help="집계에서 뺄 선행 반복 수")
    parser.add_argument("--output", type=Path, default=None, help="원시 결과 JSON 경로")
    return parser.parse_args(argv)


def _default_session_factory() -> Session:
    from src.app.core.db import SessionLocal

    return SessionLocal()


def _format_summary(results: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for entry in results:
        aggregate = entry["aggregate"]
        current = aggregate[CURRENT_GROUP]
        legacy = aggregate[LEGACY_GROUP]
        worst = aggregate["difference_ms"]["worst_round_by_median"]
        lines.append(
            f"[{entry['scenario']}] limit={entry['limit']} "
            f"current SQL={current['sql_count']['min']}~{current['sql_count']['max']} "
            f"legacy SQL={legacy['sql_count']['min']}~{legacy['sql_count']['max']} "
            f"legacy-current median 최악={worst['median']:.4f}ms"
        )
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    group_functions: Mapping[str, SelectionFn] | None = None,
) -> int:
    args = parse_args(argv)
    if args.rounds < 1 or args.repeats < 1:
        print("rounds 와 repeats 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.warmup < 0 or args.warmup >= args.repeats:
        print("warmup 은 0 이상 repeats 미만이어야 합니다.", file=sys.stderr)
        return 2
    try:
        scenarios = build_scenarios(args.scenarios)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    factory = session_factory if session_factory is not None else _default_session_factory
    groups = dict(group_functions) if group_functions is not None else dict(DEFAULT_GROUP_FUNCTIONS)

    sampler = LoadAverageSampler(interval_seconds=LOAD_SAMPLE_INTERVAL_SECONDS)
    session = factory()
    try:
        sampler.start()
        try:
            measurements = run_measurement(
                session,
                scenarios,
                groups,
                rounds=args.rounds,
                repeats=args.repeats,
                warmup=args.warmup,
            )
        except SelectionMismatchError as exc:
            print(f"[중단] {exc}", file=sys.stderr)
            return 1
        finally:
            load_summary = sampler.stop()

        environment = collect_environment(session, load_summary)
        latest = latest_collected_at(session)
    finally:
        session.close()

    payload = {
        "schema": "HOME_RECENT_SELECTION_BENCHMARK_V1",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "config": {
            "scenarios": list(args.scenarios),
            "rounds": args.rounds,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "groups": list(ALL_GROUPS),
            "latest_collected_at": latest.isoformat() if latest is not None else None,
        },
        "environment": environment,
        "scenarios": list(measurements),
    }
    text_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text_payload, encoding="utf-8")
        print(f"결과를 {args.output} 에 저장했습니다.")
    else:
        print(text_payload)
    print(_format_summary(measurements))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
