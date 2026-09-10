"""compare-stats 구간 계측과 측정 하네스 짝짓기 고정 테스트.

기존 테스트 파일을 수정하지 않고 이 파일에서만 검증합니다.
"""

import importlib
import json
import logging
from datetime import datetime
from types import SimpleNamespace

from src.app.core import latency_segments
from src.app.services import dashboard

harness = importlib.import_module("scripts.benchmark_compare_stats")

EXPECTED_SEGMENTS = [
    "announcement_summary",
    "result_summary",
    "cache_lookup",
    "matched_count",
    "announce_by_month",
    "result_by_month",
    "agency_announce_top10",
    "cache_store",
    "result_assembly",
]

_FIXED_NOW = datetime(2026, 9, 10)


def _stub_miss_path(monkeypatch, isolated_db):
    """캐시 미적중 경로의 외부 의존성을 고정합니다."""
    summaries = {
        "announcement": SimpleNamespace(total_count=3, total_amount=3000, is_stale=False),
        "result": SimpleNamespace(total_count=3, total_amount=2700, is_stale=False),
    }
    monkeypatch.setattr(dashboard.cache, "get", lambda _key: None)
    captured = {}
    monkeypatch.setattr(dashboard.cache, "set", lambda *args: captured.setdefault("set", args))
    monkeypatch.setattr(dashboard, "_compare_stats_cache_key", lambda *_args: "test-key")
    monkeypatch.setattr(dashboard, "_build_monthly_counts", lambda *_args: [])
    monkeypatch.setattr(dashboard, "utcnow", lambda: _FIXED_NOW)
    monkeypatch.setattr(
        dashboard,
        "get_bid_dataset_summary",
        lambda _db, dataset: summaries[dataset],
    )
    monkeypatch.setattr("src.app.core.config.settings.LATENCY_SEGMENT_LOGGING", True, raising=False)
    return captured


def _segment_payload_from_caplog(caplog):
    lines = [
        record.getMessage()
        for record in caplog.records
        if harness.LOG_MARKER in record.getMessage()
    ]
    assert len(lines) == 1, f"구간 로그 줄이 정확히 하나여야 합니다: {lines}"
    return json.loads(lines[0].split(harness.LOG_MARKER, 1)[1])


def test_flag_off_records_nothing(monkeypatch, caplog):
    """플래그가 꺼져 있으면 레코더가 아무 것도 기록하지 않고 로그 줄도 남지 않습니다."""
    monkeypatch.setattr(
        "src.app.core.config.settings.LATENCY_SEGMENT_LOGGING", False, raising=False
    )
    with caplog.at_level(logging.INFO, logger="src.app.services.dashboard"):
        assert latency_segments.open_compare_stats_record() is None
        with latency_segments.compare_stats_segment("matched_count"):
            pass
        latency_segments.close_compare_stats_record(None)
        assert latency_segments.get_compare_stats_segments() is None
        assert latency_segments.build_compare_stats_payload(False) is None
        latency_segments.log_compare_stats_segments(dashboard.logger, False)
    assert not [record for record in caplog.records if harness.LOG_MARKER in record.getMessage()]


def test_cache_miss_emits_all_nine_segments(isolated_db, monkeypatch, caplog):
    """플래그가 켜져 있으면 미적중 회차에 아홉 구간과 집계값이 모두 남습니다."""
    _stub_miss_path(monkeypatch, isolated_db)
    with caplog.at_level(logging.INFO, logger="src.app.services.dashboard"):
        data = dashboard.get_compare_stats_data(isolated_db)
    assert data["announce_count"] == 3
    assert data["matched_count"] == 0
    payload = _segment_payload_from_caplog(caplog)
    assert payload["cache_hit"] is False
    assert sorted(payload["segments"]) == sorted(EXPECTED_SEGMENTS)
    for value in payload["segments"].values():
        assert isinstance(value, float)
    assert isinstance(payload["cursor_ms"], float)
    assert isinstance(payload["cursor_count"], int)
    assert payload["cursor_count"] >= 1
    assert isinstance(payload["total_ms"], float)
    assert payload["residual_ms"] >= 0.0


def test_cache_hit_marks_cache_hit_true(isolated_db, monkeypatch, caplog):
    """캐시 적중 회차도 cache_hit 참으로 줄을 남깁니다."""
    cached = {"announce_count": 3, "matched_count": 1}
    summaries = {
        "announcement": SimpleNamespace(total_count=3, total_amount=3000, is_stale=False),
        "result": SimpleNamespace(total_count=3, total_amount=2700, is_stale=False),
    }
    monkeypatch.setattr(dashboard.cache, "get", lambda _key: cached)
    monkeypatch.setattr(dashboard, "_compare_stats_cache_key", lambda *_args: "test-key")
    monkeypatch.setattr("src.app.core.config.settings.LATENCY_SEGMENT_LOGGING", True, raising=False)
    monkeypatch.setattr(
        dashboard,
        "get_bid_dataset_summary",
        lambda _db, dataset: summaries[dataset],
    )
    with caplog.at_level(logging.INFO, logger="src.app.services.dashboard"):
        data = dashboard.get_compare_stats_data(isolated_db)
    assert data is cached
    payload = _segment_payload_from_caplog(caplog)
    assert payload["cache_hit"] is True
    assert sorted(payload["segments"]) == sorted(EXPECTED_SEGMENTS)


def test_instrumentation_error_keeps_return_value(isolated_db, monkeypatch, caplog):
    """레코더 내부 예외가 나도 get_compare_stats_data 의 반환값이 달라지지 않습니다."""
    _stub_miss_path(monkeypatch, isolated_db)
    monkeypatch.setattr(
        latency_segments,
        "close_compare_stats_record",
        lambda _record: (_ for _ in ()).throw(RuntimeError("계측 종료 실패")),
    )
    monkeypatch.setattr(
        latency_segments,
        "log_compare_stats_segments",
        lambda _logger, _hit: (_ for _ in ()).throw(RuntimeError("계측 로그 실패")),
    )
    with caplog.at_level(logging.INFO, logger="src.app.services.dashboard"):
        data = dashboard.get_compare_stats_data(isolated_db)
    assert data["announce_count"] == 3
    assert data["result_count"] == 3
    assert data["announce_by_month"] == []
    assert data["agency_announce_top10"] == []


def test_harness_pairing_respects_round_boundary():
    """회차 경계 이후의 줄만 후보로 삼습니다."""
    lines = [
        'app log compare_stats_segments={"cache_hit": false} 이전 회차 줄',
        "app 일반 로그",
        'app log compare_stats_segments={"cache_hit": true} 이번 회차 줄',
    ]
    candidates = harness.pair_round_candidates(lines, 2)
    assert len(candidates) == 1
    assert "이번 회차" in candidates[0]


def test_harness_marks_ambiguous_and_missing_invalid():
    """후보가 없거나 둘 이상이면 그 회차를 무효로 기록합니다."""
    missing = harness.classify_round(0, 10.0, [])
    assert missing["valid"] is False
    assert missing["invalid_reason"] == harness.REASON_NO_CANDIDATE
    ambiguous = harness.classify_round(
        1, 12.0, ['compare_stats_segments={"a": 1}', 'compare_stats_segments={"a": 2}']
    )
    assert ambiguous["valid"] is False
    assert ambiguous["invalid_reason"] == harness.REASON_AMBIGUOUS
    assert ambiguous["candidate_count"] == 2


def test_harness_classify_valid_round_keeps_raw_values():
    """후보가 하나이면 원값을 그대로 담습니다."""
    payload = {
        "cache_hit": False,
        "segments": {"matched_count": 11.5},
        "cursor_ms": 9.25,
        "cursor_count": 4,
        "total_ms": 20.0,
        "residual_ms": 10.75,
    }
    line = f"app log {harness.LOG_MARKER}{json.dumps(payload, ensure_ascii=False)} 끝"
    entry = harness.classify_round(2, 21.5, [line])
    assert entry["valid"] is True
    assert entry["invalid_reason"] is None
    assert entry["wall_ms"] == 21.5
    assert entry["cache_hit"] is False
    assert entry["segments"] == {"matched_count": 11.5}
    assert entry["cursor_count"] == 4
    assert entry["raw_line"].startswith("app log")


def test_harness_summary_excludes_invalid_rounds():
    """집계는 유효 회차만으로 P50, 최소, 최대, 합계를 냅니다."""
    rounds = [
        {
            "index": 0,
            "wall_ms": 10.0,
            "valid": True,
            "invalid_reason": None,
            "cache_hit": False,
            "segments": {"matched_count": 4.0},
            "cursor_ms": 3.0,
        },
        {
            "index": 1,
            "wall_ms": 30.0,
            "valid": True,
            "invalid_reason": None,
            "cache_hit": False,
            "segments": {"matched_count": 8.0},
            "cursor_ms": 7.0,
        },
        {"index": 2, "wall_ms": 999.0, "valid": False, "invalid_reason": "ambiguous"},
    ]
    summary = harness.summarize_rounds(rounds)
    assert summary["valid_rounds"] == 2
    assert summary["invalid_rounds"] == 1
    assert summary["wall_ms"]["min_ms"] == 10.0
    assert summary["wall_ms"]["max_ms"] == 30.0
    assert summary["wall_ms"]["sum_ms"] == 40.0
    assert summary["wall_ms"]["p50_ms"] == 20.0
    assert summary["by_segment"]["matched_count"]["sum_ms"] == 12.0
    assert summary["by_segment"]["matched_count"]["n"] == 2


def test_harness_segment_names_match_recorder():
    """하네스와 레코더의 구간 이름이 어긋나지 않습니다."""
    assert set(harness.SEGMENT_NAMES) == set(latency_segments.COMPARE_STATS_SEGMENT_NAMES)
    assert set(harness.SEGMENT_NAMES) == set(EXPECTED_SEGMENTS)
