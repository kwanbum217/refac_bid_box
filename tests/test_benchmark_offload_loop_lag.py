"""
tests/test_benchmark_offload_loop_lag.py

scripts/benchmark_offload_loop_lag.py 단위 테스트.

실제 DB·Redis·Docker 없이 돕니다. 대상 함수를 time.sleep 으로 흉내 낸 fake 로 바꿔
A 집단(동기 직접 호출)의 탐침 지연이 B 집단(asyncio.to_thread)보다 커진다는 것을
단언합니다. 호출 성공만 보는 테스트는 증명이 아닙니다.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from scripts.benchmark_offload_loop_lag import (
    ARM_OFFLOAD,
    ARM_SYNC,
    D3_EXCLUSION_REASON,
    EXCLUDED_TARGETS,
    HARNESS_KEY_PREFIX,
    HARNESS_SCHEDULE_CLAIM_KEY,
    HARNESS_SCHEDULE_NAME,
    HARNESS_WORKER_HEARTBEAT_KEY,
    SCHEMA,
    TargetSpec,
    _remove_schedule_status_entry,
    build_d2_claim_cycle_target,
    build_d9_heartbeat_target,
    build_d9_schedule_result_target,
    build_target_specs,
    collect_db_environment,
    collect_environment,
    format_target_list,
    measure_target,
    percentile,
    select_specs,
)

SLEEP_SECONDS = 0.2
LAG_THRESHOLD_MS = 100.0


def _sleep_spec(sleep_seconds: float = SLEEP_SECONDS, repeats: int = 4) -> TargetSpec:
    def build() -> Any:
        return lambda: time.sleep(sleep_seconds)

    return TargetSpec(
        target_id="FAKE.sleep",
        defect="TEST",
        description="time.sleep 대역",
        default_repeats=repeats,
        writes=False,
        side_effect_note="",
        build=build,
    )


class TestArmComparison:
    """A·B 집단의 탐침 지연 차이를 단언합니다."""

    async def test_arm_a_lag_exceeds_arm_b_lag(self):
        result = await measure_target(_sleep_spec(), rounds=1, repeats=4, warmup=1, interval_ms=1.0)
        summary = result["summary"]
        a_max = summary[ARM_SYNC]["probe_max_worst_round_ms"]
        b_max = summary[ARM_OFFLOAD]["probe_max_worst_round_ms"]

        assert a_max is not None
        assert b_max is not None
        # A 는 루프를 실제로 멈추므로 지연이 sleep 시간 근처로 커집니다.
        assert a_max >= LAG_THRESHOLD_MS
        # B 는 루프를 멈추지 않으므로 지연이 작게 남습니다.
        assert b_max < LAG_THRESHOLD_MS
        assert a_max > b_max
        assert summary["lag_max_ratio_a_over_b"] > 1.0

    async def test_both_arms_spend_wall_time_near_sleep(self):
        result = await measure_target(_sleep_spec(), rounds=1, repeats=4, warmup=1, interval_ms=1.0)
        summary = result["summary"]
        sleep_ms = SLEEP_SECONDS * 1000.0
        for arm in (ARM_SYNC, ARM_OFFLOAD):
            wall_median = summary[arm]["wall_ms_median"]
            assert wall_median is not None
            assert sleep_ms * 0.75 <= wall_median <= sleep_ms * 2.5

    async def test_arm_a_runs_on_loop_thread_and_arm_b_off_thread(self):
        loop_thread_id = threading.get_ident()
        seen_thread_ids: list[int] = []

        def build() -> Any:
            def call() -> None:
                seen_thread_ids.append(threading.get_ident())

            return call

        spec = TargetSpec(
            target_id="FAKE.thread",
            defect="TEST",
            description="스레드 식별 대역",
            default_repeats=2,
            writes=False,
            side_effect_note="",
            build=build,
        )
        result = await measure_target(spec, rounds=1, repeats=2, warmup=0, interval_ms=1.0)

        records = result["records"]
        assert len(seen_thread_ids) == len(records)
        for record, thread_id in zip(records, seen_thread_ids, strict=True):
            if record["arm"] == ARM_SYNC:
                assert thread_id == loop_thread_id
            else:
                assert thread_id != loop_thread_id


class TestInterleavingAndAggregation:
    """ABBA 교차 순서와 warmup 제외를 단언합니다."""

    async def test_abba_interleaving_order(self):
        result = await measure_target(
            _sleep_spec(0.001), rounds=1, repeats=4, warmup=0, interval_ms=1.0
        )
        arms = [record["arm"] for record in result["records"]]
        assert arms == [
            ARM_SYNC,
            ARM_OFFLOAD,
            ARM_OFFLOAD,
            ARM_SYNC,
            ARM_SYNC,
            ARM_OFFLOAD,
            ARM_OFFLOAD,
            ARM_SYNC,
        ]

    async def test_warmup_records_excluded_from_aggregation(self):
        result = await measure_target(
            _sleep_spec(0.001), rounds=2, repeats=3, warmup=1, interval_ms=1.0
        )

        a_flags = [r["warmup"] for r in result["records"] if r["arm"] == ARM_SYNC]
        assert a_flags == [True, False, False, True, False, False]
        assert result["summary"][ARM_SYNC]["call_count"] == 4
        assert result["summary"][ARM_OFFLOAD]["call_count"] == 4
        for aggregate in result["summary"][ARM_SYNC]["rounds"]:
            assert aggregate["call_count"] == 2
            assert aggregate["wall_ms_median"] is not None

    async def test_cleanup_runs_before_and_after_measurement(self):
        cleanup_calls: list[int] = []

        def cleanup() -> None:
            cleanup_calls.append(1)

        spec = _sleep_spec(0.001)
        spec.cleanup = cleanup
        await measure_target(spec, rounds=1, repeats=2, warmup=0, interval_ms=1.0)
        assert len(cleanup_calls) == 2

    async def test_cleanup_runs_even_when_target_raises(self):
        cleanup_calls: list[int] = []

        def build() -> Any:
            def boom() -> None:
                raise RuntimeError("target failure")

            return boom

        spec = TargetSpec(
            target_id="FAKE.boom",
            defect="TEST",
            description="예외 대상",
            default_repeats=1,
            writes=False,
            side_effect_note="",
            build=build,
            cleanup=lambda: cleanup_calls.append(1),
        )
        with pytest.raises(RuntimeError, match="target failure"):
            await measure_target(spec, rounds=1, repeats=1, warmup=0, interval_ms=1.0)
        assert len(cleanup_calls) == 2


class TestSideEffectIsolation:
    """D2·D9 부수효과가 하니스 전용 키로 격리되고 정리되는지 단언합니다."""

    def test_harness_keys_scoped_away_from_production(self):
        from src.tasks.scheduled_tasks import SCHEDULE_COLLECTION_CLAIM_KEY
        from src.tasks.worker import WORKER_HEARTBEAT_KEY

        assert HARNESS_SCHEDULE_CLAIM_KEY.startswith(HARNESS_KEY_PREFIX)
        assert HARNESS_WORKER_HEARTBEAT_KEY.startswith(HARNESS_KEY_PREFIX)
        assert HARNESS_SCHEDULE_CLAIM_KEY != SCHEDULE_COLLECTION_CLAIM_KEY
        assert HARNESS_WORKER_HEARTBEAT_KEY != WORKER_HEARTBEAT_KEY

    def test_d2_claim_cycle_uses_harness_key_and_releases_it(self):
        events: list[tuple[Any, ...]] = []

        class _Claim:
            acquired = True
            key = HARNESS_SCHEDULE_CLAIM_KEY
            token = "harness-token"  # noqa: S105 - 대역 토큰 문자열
            status = type("Status", (), {"value": "acquired"})()

        def acquire(owner, *, key, ttl_seconds):
            events.append(("acquire", owner, key, ttl_seconds))
            return _Claim()

        def release(key, *, token):
            events.append(("release", key, token))
            return True

        deleted: list[str] = []
        spec = build_d2_claim_cycle_target(
            acquire=acquire,
            release=release,
            redis_deleter=lambda *keys: deleted.extend(keys),
        )
        result = spec.build()()

        assert events[0][0] == "acquire"
        assert events[0][2] == HARNESS_SCHEDULE_CLAIM_KEY
        assert events[1] == ("release", HARNESS_SCHEDULE_CLAIM_KEY, "harness-token")
        assert result == "acquired"

        spec.cleanup()
        assert deleted == [HARNESS_SCHEDULE_CLAIM_KEY]

    def test_d9_heartbeat_uses_harness_key_and_cleans_up(self):
        from src.tasks.worker import WORKER_HEARTBEAT_KEY

        recorded: list[str] = []
        deleted: list[str] = []
        spec = build_d9_heartbeat_target(
            heartbeat=lambda key: recorded.append(key),
            redis_deleter=lambda *keys: deleted.extend(keys),
        )
        spec.build()()
        assert recorded == [HARNESS_WORKER_HEARTBEAT_KEY]
        assert HARNESS_WORKER_HEARTBEAT_KEY != WORKER_HEARTBEAT_KEY

        spec.cleanup()
        assert deleted == [HARNESS_WORKER_HEARTBEAT_KEY]

    def test_d9_schedule_result_uses_harness_name_and_removes_entry(self):
        recorded: list[tuple[Any, ...]] = []
        removed: list[str] = []
        spec = build_d9_schedule_result_target(
            recorder=lambda name, outcome, success: recorded.append((name, outcome, success)),
            entry_remover=lambda name: removed.append(name),
        )
        spec.build()()
        assert recorded[0][0] == HARNESS_SCHEDULE_NAME
        assert recorded[0][2] is True

        spec.cleanup()
        assert removed == [HARNESS_SCHEDULE_NAME]

    def test_remove_schedule_status_entry_preserves_other_entries(self):
        from src.tasks.worker import SCHEDULE_STATUS_KEY

        class _FakeCache:
            def __init__(self) -> None:
                self.store: dict[str, Any] = {
                    SCHEDULE_STATUS_KEY: {
                        "nightly_schedule": {"success": True},
                        HARNESS_SCHEDULE_NAME: {"success": True},
                    }
                }
                self.deleted: list[str] = []

            def get(self, key: str) -> Any:
                return self.store.get(key)

            def set(self, key: str, value: Any, ttl: int) -> None:
                self.store[key] = value

            def delete(self, key: str) -> None:
                self.deleted.append(key)
                self.store.pop(key, None)

        fake = _FakeCache()
        assert _remove_schedule_status_entry(HARNESS_SCHEDULE_NAME, cache_layer=fake) is True
        assert HARNESS_SCHEDULE_NAME not in fake.store[SCHEDULE_STATUS_KEY]
        assert "nightly_schedule" in fake.store[SCHEDULE_STATUS_KEY]
        assert fake.deleted == []

    def test_remove_schedule_status_entry_deletes_key_when_empty(self):
        from src.tasks.worker import SCHEDULE_STATUS_KEY

        class _FakeCache:
            def __init__(self) -> None:
                self.store: dict[str, Any] = {SCHEDULE_STATUS_KEY: {HARNESS_SCHEDULE_NAME: {}}}
                self.deleted: list[str] = []

            def get(self, key: str) -> Any:
                return self.store.get(key)

            def set(self, key: str, value: Any, ttl: int) -> None:
                self.store[key] = value

            def delete(self, key: str) -> None:
                self.deleted.append(key)
                self.store.pop(key, None)

        fake = _FakeCache()
        assert _remove_schedule_status_entry(HARNESS_SCHEDULE_NAME, cache_layer=fake) is True
        assert fake.deleted == [SCHEDULE_STATUS_KEY]


class TestTargetDefinitions:
    """대상 목록, D3 제외 표시, 선택 로직을 단언합니다."""

    def test_target_specs_cover_d1_d2_d7_d9_without_d3(self):
        defects = {spec.defect for spec in build_target_specs()}
        assert defects == {"D1", "D2", "D7", "D9"}
        assert "D3" not in defects

    def test_list_output_marks_d3_excluded_with_reason(self):
        text = format_target_list(build_target_specs())
        assert "D1" in text
        assert "D9" in text
        assert "D3" in text
        assert D3_EXCLUSION_REASON in text
        assert EXCLUDED_TARGETS["D3"] == D3_EXCLUSION_REASON

    def test_select_specs_by_group_and_exact_id(self):
        specs = build_target_specs()
        group_ids = {spec.target_id for spec in select_specs(specs, ["D9"])}
        assert group_ids == {"D9.heartbeat", "D9.schedule_result"}

        exact = select_specs(specs, ["D2.catchup_check"])
        assert [spec.target_id for spec in exact] == ["D2.catchup_check"]

        assert len(select_specs(specs, None)) == len(specs)

    def test_select_specs_rejects_unknown_token(self):
        with pytest.raises(ValueError, match="알 수 없는 대상"):
            select_specs(build_target_specs(), ["D999"])

    def test_d1_targets_are_marked_as_writing(self):
        specs = {spec.target_id: spec for spec in build_target_specs()}
        for target_id in ("D1.announcement", "D1.result", "D1.catalogs"):
            assert specs[target_id].writes is True
        assert specs["D7.count_today"].writes is False


class TestHelpers:
    def test_percentile_interpolates(self):
        assert percentile([10.0, 20.0, 30.0, 40.0], 50.0) == 25.0
        assert percentile([5.0], 95.0) == 5.0
        assert percentile([], 95.0) is None

    def test_collect_db_environment_reads_buffer_pool_and_uptime(self):
        def executor(sql: str) -> list[tuple[Any, ...]]:
            if sql == "SELECT @@innodb_buffer_pool_size":
                return [(1073741824,)]
            if sql.startswith("SHOW GLOBAL STATUS"):
                return [("Uptime", "4231")]
            return []

        env = collect_db_environment(executor)
        assert env["status"] == "ok"
        assert env["buffer_pool_size_bytes"] == 1073741824
        assert env["buffer_pool_size_gb"] == 1.0
        assert env["uptime_seconds"] == 4231

    def test_collect_db_environment_records_failure_without_raising(self):
        def boom(sql: str) -> list[tuple[Any, ...]]:
            raise RuntimeError("no database")

        env = collect_db_environment(boom)
        assert env["status"] == "unavailable"
        assert env["buffer_pool_size_bytes"] is None
        assert env["uptime_seconds"] is None
        assert "no database" in env["error"]

    def test_collect_environment_includes_git_load_and_db(self):
        load_summary = {"min": 1.0, "median": 2.0, "max": 3.0, "samples": []}
        db_environment = {"status": "ok", "buffer_pool_size_gb": 1.0, "uptime_seconds": 10}
        env = collect_environment(load_summary, db_environment)

        assert env["host_load"]["max"] == 3.0
        assert env["db"]["uptime_seconds"] == 10
        assert "sha" in env["git"]
        assert "dirty" in env["git"]
        assert env["python_version"]
        assert env["platform"]

    def test_schema_identifier_is_stable(self):
        assert SCHEMA == "ORCA_OFFLOAD_LOOP_LAG_V1"
