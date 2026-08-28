"""
tests/test_cpu_utilization_metric.py

CPU utilization 계측 및 정규화 부하 지표 정합성 회귀 테스트.
- (a) /proc/stat 대역 입력으로 utilization 계산이 맞다.
- (b) 측정 실패가 None과 사유로 처리되고 벤치마크가 계속 진행된다.
- (c) 기존 load average 필드(load_1m, normalized_load_1m_percent, per_core_percent)가 유지된다.
"""

from __future__ import annotations

from scripts.benchmark_provenance import (
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
        util, reason = measure_cpu_utilization(platform_name="win32")
        assert util is None
        assert reason == "unsupported_platform: win32"

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
            cpu_util_sampler=lambda: (15.5, None),
        )
        # 기존 필드 불변 검증
        assert sample["cpu_count"] == 4
        assert sample["load_1m"] == 1.2
        assert sample["normalized_load_1m_percent"] == 30.0
        assert sample["per_core_percent"] == 30.0
        assert "observed_at_utc" in sample

        # 신규 필드 공존 검증
        assert sample["cpu_utilization_percent"] == 15.5
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
