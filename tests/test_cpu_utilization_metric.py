"""
tests/test_cpu_utilization_metric.py

CPU utilization 계측 및 정규화 부하 지표 정합성 회귀 테스트.
- (a) /proc/stat 대역 입력으로 utilization 계산이 맞다.
- (b) 측정 실패가 None과 사유로 처리되고 벤치마크가 계속 진행된다.
- (c) 기존 load average 필드(load_1m, normalized_load_1m_percent, per_core_percent)가 유지된다.
"""

from __future__ import annotations

import functools
import time

from scripts import benchmark_provenance
from scripts.benchmark_provenance import (
    CPU_UTILIZATION_METHOD_PROC_STAT_DELTA,
    CPU_UTILIZATION_METHOD_UNSUPPORTED,
    HostLoadMonitor,
    calculate_cpu_utilization_from_ticks,
    check_ambient_load_protocol,
    compute_host_load_stats,
    measure_cpu_utilization,
    measure_macos_cpu_utilization,
    parse_proc_stat,
    read_proc_stat_ticks,
    single_host_load_sample,
)


class TestProcStatParsingAndCalculation:
    """(a) /proc/stat 파싱 및 CPU utilization(%) 계산 검증."""

    def test_parse_proc_stat_standard_line(self):
        sample_stat = (
            "cpu  2255 34 2290 22625563 6290 127 456 0 0 0\n"
            "cpu0 1132 17 1441 11311718 3675 127 438 0 0 0\n"
            "cpu1 1123 17 849 11313845 2614 0 18 0 0 0\n"
        )
        ticks = parse_proc_stat(sample_stat)
        assert ticks is not None
        total_ticks, idle_ticks = ticks
        # total = 2255 + 34 + 2290 + 22625563 + 6290 + 127 + 456 + 0 + 0 + 0 = 22637015
        assert total_ticks == 22637015
        # idle_total = idle (22625563) + iowait (6290) = 22631853
        assert idle_ticks == 22631853

    def test_calculate_cpu_utilization_from_ticks_standard(self):
        # start: total 1000, idle 800
        # end: total 2000, idle 1600
        # delta: total 1000, idle 800 -> busy 200 -> 20.0%
        util, reason = calculate_cpu_utilization_from_ticks((1000, 800), (2000, 1600))
        assert reason is None
        assert util == 20.0

    def test_calculate_cpu_utilization_with_multi_component_ticks(self):
        # start: total 10000, idle 7000
        # end: total 18000, idle 12000
        # delta: total 8000, idle 5000 -> busy 3000 -> 3000/8000 * 100 = 37.5%
        util, reason = calculate_cpu_utilization_from_ticks((10000, 7000), (18000, 12000))
        assert reason is None
        assert util == 37.5

    def test_calculate_cpu_utilization_bounds_0_and_100(self):
        # 0% utilization (모든 틱이 idle)
        util_0, reason_0 = calculate_cpu_utilization_from_ticks((1000, 800), (2000, 1800))
        assert reason_0 is None
        assert util_0 == 0.0

        # 100% utilization (idle 증가 0)
        util_100, reason_100 = calculate_cpu_utilization_from_ticks((1000, 800), (2000, 800))
        assert reason_100 is None
        assert util_100 == 100.0

    def test_read_proc_stat_ticks_with_tmp_file(self, tmp_path):
        proc_file = tmp_path / "proc_stat"
        proc_file.write_text(
            "cpu  100 0 100 800 0 0 0 0\nintr 12345\n",
            encoding="utf-8",
        )
        ticks, reason = read_proc_stat_ticks(str(proc_file))
        assert reason is None
        assert ticks == (1000, 800)


class TestMeasurementFailureAndGracefulFallback:
    """(b) 측정 실패 시 None 및 사유 기록, 벤치마크 중단 없는 Graceful Fallback 검증."""

    def test_non_positive_ticks_delta_returns_none_with_reason(self):
        # start ticks == end ticks (total_delta = 0)
        util, reason = calculate_cpu_utilization_from_ticks((1000, 800), (1000, 800))
        assert util is None
        assert reason == "non_positive_total_ticks_delta"

        # end ticks < start ticks (counter overflow/reset)
        util2, reason2 = calculate_cpu_utilization_from_ticks((1000, 800), (500, 400))
        assert util2 is None
        assert reason2 == "non_positive_total_ticks_delta"

    def test_missing_proc_stat_file_returns_none_with_reason(self):
        ticks, reason = read_proc_stat_ticks("/non/existent/path/proc_stat")
        assert ticks is None
        assert reason == "proc_stat_not_found"

    def test_corrupted_proc_stat_returns_none_with_reason(self, tmp_path):
        proc_file = tmp_path / "bad_stat"
        proc_file.write_text("cpu invalid non_numeric tokens\n", encoding="utf-8")
        ticks, reason = read_proc_stat_ticks(str(proc_file))
        assert ticks is None
        assert reason == "proc_stat_parse_failed"

        empty_file = tmp_path / "empty_stat"
        empty_file.write_text("", encoding="utf-8")
        ticks_empty, reason_empty = read_proc_stat_ticks(str(empty_file))
        assert ticks_empty is None
        assert reason_empty == "proc_stat_parse_failed"

    def test_macos_ps_failure_returns_none_with_reason(self):
        def failing_runner(cmd):
            raise OSError("ps command not found")

        util, reason = measure_macos_cpu_utilization(command_runner=failing_runner, cpu_count=4)
        assert util is None
        assert reason is not None
        assert "macos_ps_failed" in reason

    def test_macos_ps_empty_output_returns_none_with_reason(self):
        def empty_runner(cmd):
            return ""

        util, reason = measure_macos_cpu_utilization(command_runner=empty_runner, cpu_count=4)
        assert util is None
        assert reason == "empty_ps_output"

    def test_unsupported_platform_returns_none_with_reason(self):
        util, reason, method, probe_ms, observation_ms = measure_cpu_utilization(
            platform_name="win32"
        )
        assert util is None
        assert reason == "unsupported_platform: win32"
        assert method == CPU_UTILIZATION_METHOD_UNSUPPORTED
        assert probe_ms >= 0.0
        assert observation_ms >= 0.0

    def test_single_host_load_sample_unsupported_platform(self):
        class MockWindowsOS:
            name = "nt"

            @staticmethod
            def cpu_count():
                return 8

        sample = single_host_load_sample(os_module=MockWindowsOS, platform_name="win32")
        assert sample["cpu_count"] == 8
        assert sample["load_1m"] is None
        assert sample["normalized_load_1m_percent"] is None
        assert sample["per_core_percent"] is None
        assert sample["cpu_utilization_percent"] is None
        assert sample["cpu_utilization_method"] == CPU_UTILIZATION_METHOD_UNSUPPORTED
        assert sample["cpu_utilization_probe_ms"] >= 0.0
        assert sample["cpu_utilization_unavailable_reason"] == "unsupported_platform: win32"

    def test_host_load_monitor_on_unsupported_platform_does_not_crash(self):
        def mock_win_sampler():
            return {
                "observed_at_utc": "2026-08-28T00:00:00Z",
                "load_1m": None,
                "cpu_count": 8,
                "normalized_load_1m_percent": None,
                "per_core_percent": None,
                "cpu_utilization_percent": None,
                "cpu_utilization_method": CPU_UTILIZATION_METHOD_UNSUPPORTED,
                "cpu_utilization_probe_ms": 0.0,
                "cpu_utilization_unavailable_reason": "unsupported_platform: win32",
            }

        monitor = HostLoadMonitor(
            interval_seconds=0.001,
            min_samples=3,
            sampler=mock_win_sampler,
        )
        monitor.start()
        summary = monitor.stop()
        assert len(summary["samples"]) >= 3
        assert summary["load_1m"] == {"min": None, "median": None, "max": None}
        assert summary["cpu_utilization_percent"] == {"min": None, "median": None, "max": None}
        assert summary["cpu_utilization_unavailable_reason"] == "unsupported_platform: win32"


class TestPreservationOfExistingLoadFields:
    """(c) 기존 load average 필드 보존 및 신규 CPU utilization 필드 공존 검증."""

    def test_single_host_load_sample_field_structure(self):
        class MockLinuxOS:
            name = "posix"

            @staticmethod
            def cpu_count():
                return 4

            @staticmethod
            def getloadavg():
                return (1.2, 0.8, 0.4)

        sample = single_host_load_sample(
            os_module=MockLinuxOS,
            cpu_util_sampler=lambda: (
                15.5,
                None,
                CPU_UTILIZATION_METHOD_PROC_STAT_DELTA,
                0.25,
                0.20,
            ),
        )
        # 기존 필드 불변 검증
        assert sample["cpu_count"] == 4
        assert sample["load_1m"] == 1.2
        assert sample["normalized_load_1m_percent"] == 30.0
        assert sample["per_core_percent"] == 30.0
        assert "observed_at_utc" in sample

        # 신규 필드 공존 검증
        assert sample["cpu_utilization_percent"] == 15.5
        assert sample["cpu_utilization_method"] == CPU_UTILIZATION_METHOD_PROC_STAT_DELTA
        assert sample["cpu_utilization_probe_ms"] == 0.25
        assert sample["cpu_utilization_unavailable_reason"] is None

    def test_compute_host_load_stats_preserves_and_computes_all_metrics(self):
        samples = [
            {
                "observed_at_utc": "t1",
                "load_1m": 1.0,
                "cpu_count": 4,
                "normalized_load_1m_percent": 25.0,
                "per_core_percent": 25.0,
                "cpu_utilization_percent": 10.0,
                "cpu_utilization_unavailable_reason": None,
            },
            {
                "observed_at_utc": "t2",
                "load_1m": 2.0,
                "cpu_count": 4,
                "normalized_load_1m_percent": 50.0,
                "per_core_percent": 50.0,
                "cpu_utilization_percent": 30.0,
                "cpu_utilization_unavailable_reason": None,
            },
            {
                "observed_at_utc": "t3",
                "load_1m": 3.0,
                "cpu_count": 4,
                "normalized_load_1m_percent": 75.0,
                "per_core_percent": 75.0,
                "cpu_utilization_percent": 20.0,
                "cpu_utilization_unavailable_reason": None,
            },
        ]
        stats = compute_host_load_stats(samples)
        # 기존 load_1m, normalized_load_1m_percent, per_core_percent 통계 검증
        assert stats["cpu_count"] == 4
        assert stats["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
        assert stats["normalized_load_1m_percent"] == {"min": 25.0, "median": 50.0, "max": 75.0}
        assert stats["per_core_percent"] == {"min": 25.0, "median": 50.0, "max": 75.0}

        # 신규 cpu_utilization_percent 통계 검증
        assert stats["cpu_utilization_percent"] == {"min": 10.0, "median": 20.0, "max": 30.0}
        assert "cpu_utilization_unavailable_reason" not in stats

    def test_compute_host_load_stats_legacy_samples_without_cpu_util(self):
        legacy_samples = [
            {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 4, "per_core_percent": 25.0},
            {"observed_at_utc": "t2", "load_1m": 2.0, "cpu_count": 4, "per_core_percent": 50.0},
        ]
        stats = compute_host_load_stats(legacy_samples)
        assert stats["normalized_load_1m_percent"] == {"min": 25.0, "median": 37.5, "max": 50.0}
        assert stats["per_core_percent"] == {"min": 25.0, "median": 37.5, "max": 50.0}
        assert stats["cpu_utilization_percent"] == {"min": None, "median": None, "max": None}
        assert stats["cpu_utilization_unavailable_reason"] == "not_measured"

    def test_ambient_load_protocol_remains_unaffected(self):
        stats = {
            "normalized_load_1m_percent": {"min": 5.0, "median": 20.0, "max": 40.0},
            "cpu_utilization_percent": {"min": 80.0, "median": 85.0, "max": 90.0},
        }
        compliant, detail = check_ambient_load_protocol(stats)
        assert compliant is True
        assert detail["median_percent"] == 20.0
        assert detail["max_percent"] == 40.0


class TestMacOSPsUtilCalculation:
    """macOS ps 기반 CPU utilization 계산 검증."""

    def test_measure_macos_cpu_utilization_calculation(self):
        def mock_runner(cmd):
            return "%CPU\n 20.0\n 10.0\n 10.0\n"

        util, reason = measure_macos_cpu_utilization(command_runner=mock_runner, cpu_count=4)
        assert reason is None
        # sum = 40.0, cpu_count = 4 -> 40.0 / 4 = 10.0%
        assert util == 10.0

    def test_measure_macos_cpu_utilization_clamped(self):
        def mock_runner(cmd):
            return "%CPU\n 300.0\n 300.0\n"

        util, reason = measure_macos_cpu_utilization(command_runner=mock_runner, cpu_count=2)
        assert reason is None
        # sum = 600.0, cpu_count = 2 -> 300% -> clamped to 100.0%
        assert util == 100.0


class TestObservationTimeSeparation:
    """cpu_utilization_observation_ms (의도적 대기 제외) vs probe_ms (대기 포함) 분리 회귀.

    - (a) Linux 경로에서 observation_ms < probe_ms 이다.
    - (b) sleep 시간을 모킹해 대기 시간이 observation_ms 에 포함되지 않는다.
    - (c) macOS 경로에서 observation_ms == probe_ms 이다.
    - (d) proc/stat 읽기 실패 경로에서도 두 키가 모두 기록된다.
    - (e) HostLoadMonitor 백그라운드 샘플러 표본에도 두 키가 들어간다.
    """

    def test_linux_observation_ms_strictly_less_than_probe_ms(self, tmp_path, monkeypatch):
        proc_file = tmp_path / "proc_stat"
        proc_file.write_text("cpu  100 0 100 800 0 0 0 0\n", encoding="utf-8")

        real_sleep = time.sleep

        def fake_sleep(seconds):
            # sleep 자체는 실제 시간이 흐르지 않도록 즉시 반환.
            return None

        monkeypatch.setattr(time, "sleep", fake_sleep)

        (
            _util,
            _reason,
            method,
            probe_ms,
            observation_ms,
        ) = measure_cpu_utilization(
            interval_seconds=0.05,
            platform_name="linux",
            proc_stat_path=str(proc_file),
        )
        assert method == CPU_UTILIZATION_METHOD_PROC_STAT_DELTA
        assert observation_ms < probe_ms
        # 가짜 sleep 으로 probe_ms 가 sleep 시간만큼 늘어나도 observation_ms 는 변하지 않는다.
        # 가짜 sleep 이 0 초이므로 probe_ms 도 매우 작아야 한다.
        assert observation_ms >= 0.0
        assert probe_ms >= 0.0
        # time.sleep 모킹을 복원하지 않으면 다른 테스트가 영향을 받을 수 있다.
        monkeypatch.setattr(time, "sleep", real_sleep)

    def test_linux_observation_ms_excludes_sleep_when_sleep_elapses(self, tmp_path):
        """실제 sleep 으로 시간을 보내면 observation_ms 가 sleep 만큼 늘어나지 않는다."""
        proc_file = tmp_path / "proc_stat"
        proc_file.write_text("cpu  100 0 100 800 0 0 0 0\n", encoding="utf-8")

        sleep_seconds = 0.08
        (
            _util,
            _reason,
            method,
            probe_ms,
            observation_ms,
        ) = measure_cpu_utilization(
            interval_seconds=sleep_seconds,
            platform_name="linux",
            proc_stat_path=str(proc_file),
        )
        assert method == CPU_UTILIZATION_METHOD_PROC_STAT_DELTA
        # observation_ms 는 두 read_proc_stat_ticks 호출의 합이므로 sleep_seconds 보다는 작다.
        assert observation_ms < sleep_seconds * 1000.0
        # probe_ms 는 sleep 을 포함하므로 sleep_seconds * 1000 이상.
        assert probe_ms >= sleep_seconds * 1000.0
        # probe_ms - observation_ms 가 sleep 시간 근처여야 한다 (허용 오차 50ms).
        assert (probe_ms - observation_ms) >= (sleep_seconds * 1000.0 - 50.0)

    def test_macos_observation_ms_equals_probe_ms(self, monkeypatch):
        def mock_runner(cmd):
            return "%CPU\n 20.0\n 10.0\n 10.0\n"

        (
            util,
            reason,
            method,
            probe_ms,
            observation_ms,
        ) = measure_cpu_utilization(
            platform_name="darwin",
            command_runner=mock_runner,
            cpu_count=4,
        )
        assert reason is None
        assert method == "ps_process_sum"
        assert util is not None
        # macOS 경로는 의도적 대기가 없으므로 두 값이 같다.
        assert probe_ms == observation_ms

    def test_proc_stat_read_failure_records_both_keys(self, monkeypatch):
        """proc/stat 읽기 실패 경로에서도 두 키가 모두 반환된다."""
        (
            util,
            reason,
            method,
            probe_ms,
            observation_ms,
        ) = measure_cpu_utilization(
            platform_name="linux",
            proc_stat_path="/non/existent/path/proc_stat",
        )
        assert util is None
        assert reason == "proc_stat_not_found"
        assert method == CPU_UTILIZATION_METHOD_PROC_STAT_DELTA
        # 실패 경로에서도 두 키가 모두 기록되어 호출부가 누락 없이 받을 수 있다.
        assert probe_ms >= 0.0
        assert observation_ms >= 0.0

    def test_end_ticks_read_failure_records_both_keys(self, tmp_path, monkeypatch):
        """두 번째 read_proc_stat_ticks 가 실패해도 두 키가 모두 반환된다."""
        proc_file = tmp_path / "proc_stat"
        proc_file.write_text("cpu  100 0 100 800 0 0 0 0\n", encoding="utf-8")
        original_read = benchmark_provenance.read_proc_stat_ticks
        call_count = {"n": 0}

        def flaky_read(path):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                return None, "proc_stat_parse_failed"
            return original_read(path)

        monkeypatch.setattr(benchmark_provenance, "read_proc_stat_ticks", flaky_read)
        (
            util,
            reason,
            method,
            probe_ms,
            observation_ms,
        ) = measure_cpu_utilization(
            platform_name="linux",
            proc_stat_path=str(proc_file),
        )
        assert util is None
        assert reason == "proc_stat_parse_failed"
        assert method == CPU_UTILIZATION_METHOD_PROC_STAT_DELTA
        assert probe_ms >= 0.0
        assert observation_ms >= 0.0

    def test_host_load_monitor_linux_samples_include_observation_key(self, tmp_path, monkeypatch):
        proc_file = tmp_path / "proc_stat"
        proc_file.write_text("cpu  100 0 100 800 0 0 0 0\n", encoding="utf-8")

        class _OS:
            @staticmethod
            def cpu_count():
                return 4

            @staticmethod
            def getloadavg():
                return (0.5, 0.4, 0.3)

        monitor = HostLoadMonitor(
            interval_seconds=0.001,
            min_samples=2,
            sampler=functools.partial(single_host_load_sample, os_module=_OS),
            proc_stat_path=str(proc_file),
        )
        monitor.start()
        summary = monitor.stop()
        assert len(summary["samples"]) >= 2
        for sample in summary["samples"]:
            assert "cpu_utilization_probe_ms" in sample
            assert "cpu_utilization_observation_ms" in sample
            # Linux 경로의 표본은 observation_ms 가 probe_ms 보다 작거나 같아야 한다.
            assert sample["cpu_utilization_observation_ms"] <= sample["cpu_utilization_probe_ms"]
