"""콜드 스타트 SQL 비용 귀속 측정 하네스 단위 및 회귀 테스트.

다음 5대 핵심 보증을 격리 환경(Mock 기반, 실제 DB/Redis 없이)에서 검증합니다:
1. 캐시 비우기 플래그(--flush-cache)가 없으면 절대 Redis FLUSHALL 을 실행하지 않는다.
2. performance_schema digest 피코초(ps) 단위 변환이 정확하다 (1e12 초, 1e9 밀리초).
3. cold 와 warm 상태의 쿼리별 비용 차이(delta) 계산이 정확하다.
4. performance_schema 가 비활성화되어 있거나 조회 실패 시 fail-closed 로 비정상 종료(exit 2)한다.
5. 미등록 fixture 해시 또는 게이트 미충족 환경에서 canonical=false 가 된다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.measure_coldsql_attribution import (
    AttributionMeasurementError,
    DigestStat,
    PerformanceSchemaUnavailableError,
    calculate_attribution_diff,
    check_performance_schema,
    convert_timer_ps_to_ms,
    convert_timer_ps_to_sec,
    fetch_digest_statistics,
    flush_redis_cache,
    main,
    reset_performance_schema_digest,
    run_attribution_measurement,
)


# ---------------------------------------------------------------------------
# 1. 캐시 비우기 안전장치 검증 (기본값 실행 방지)
# ---------------------------------------------------------------------------
def test_flush_cache_disabled_by_default_does_not_execute_flushall():
    """flush_requested=False 일 때 redis client 의 flushall 이 절대 호출되지 않아야 합니다."""
    mock_redis = MagicMock()
    result = flush_redis_cache(mock_redis, flush_requested=False)

    assert result is False
    mock_redis.flushall.assert_not_called()


def test_flush_cache_enabled_executes_flushall():
    """flush_requested=True 일 때 redis client 의 flushall 이 정상 호출되어야 합니다."""
    mock_redis = MagicMock()
    result = flush_redis_cache(mock_redis, flush_requested=True)

    assert result is True
    mock_redis.flushall.assert_called_once()


def test_flush_cache_enabled_without_client_raises_error():
    """클라이언트 없이 flush 를 요청하면 예외를 발생시켜야 합니다."""
    with pytest.raises(AttributionMeasurementError) as excinfo:
        flush_redis_cache(None, flush_requested=True)
    assert "Redis 클라이언트가 제공되지 않아" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 2. digest 피코초 단위 변환 정밀도 검증
# ---------------------------------------------------------------------------
def test_timer_conversion_precision():
    """피코초(ps) -> 초(sec: 1e12), 밀리초(ms: 1e9) 변환이 정확해야 합니다."""
    assert convert_timer_ps_to_sec(1_000_000_000_000) == pytest.approx(1.0)
    assert convert_timer_ps_to_sec(89_090_000_000_000) == pytest.approx(89.09)
    assert convert_timer_ps_to_sec(0) == 0.0
    assert convert_timer_ps_to_sec(None) == 0.0

    assert convert_timer_ps_to_ms(1_000_000_000) == pytest.approx(1.0)
    assert convert_timer_ps_to_ms(15_539_000_000) == pytest.approx(15.539)
    assert convert_timer_ps_to_ms(0) == 0.0
    assert convert_timer_ps_to_ms(None) == 0.0


def test_fetch_digest_statistics_converts_units_properly():
    """DB 행 데이터에서 DigestStat 객체로의 단위 변환 및 필터링을 검증합니다."""
    sample_rows = [
        {
            "DIGEST": "digest_abc123",
            "DIGEST_TEXT": "SELECT * FROM bid_announcements WHERE dminstt_nm LIKE concat('%',?,'%')",
            "COUNT_STAR": 10,
            "SUM_TIMER_WAIT": 89_090_000_000_000,
            "MIN_TIMER_WAIT": 5_000_000_000,
            "AVG_TIMER_WAIT": 8_909_000_000,
            "MAX_TIMER_WAIT": 15_539_000_000,
        },
        {
            "DIGEST": "digest_internal",
            "DIGEST_TEXT": "SELECT * FROM performance_schema.events_statements_summary_by_digest",
            "COUNT_STAR": 1,
            "SUM_TIMER_WAIT": 100_000_000,
            "MIN_TIMER_WAIT": 100_000_000,
            "AVG_TIMER_WAIT": 100_000_000,
            "MAX_TIMER_WAIT": 100_000_000,
        },
    ]

    mock_executor = MagicMock(return_value=sample_rows)
    stats = fetch_digest_statistics(mock_executor, exclude_internal=True)

    # 내부 performance_schema 쿼리는 제외되어 1건만 남아야 합니다.
    assert len(stats) == 1
    s = stats[0]
    assert s.digest == "digest_abc123"
    assert s.count_star == 10
    assert s.sum_timer_wait_sec == pytest.approx(89.09)
    assert s.min_timer_wait_ms == pytest.approx(5.0)
    assert s.avg_timer_wait_ms == pytest.approx(8.909)
    assert s.max_timer_wait_ms == pytest.approx(15.539)


# ---------------------------------------------------------------------------
# 3. cold 와 warm 차이 계산 쿼리별 검증
# ---------------------------------------------------------------------------
def test_calculate_attribution_diff_computes_delta_correctly():
    """cold 와 warm 상태의 쿼리별 소비 차이 계산과 정렬 순서를 검증합니다."""
    cold_stats = [
        DigestStat(
            digest="d1",
            digest_text="SELECT count(*) FROM bid_announcements WHERE dminstt_nm LIKE ...",
            count_star=4,
            sum_timer_wait_ps=89_090_000_000_000,
            sum_timer_wait_sec=89.09,
            min_timer_wait_ms=5000.0,
            avg_timer_wait_ms=22272.5,
            max_timer_wait_ms=27668.0,
        ),
        DigestStat(
            digest="d2",
            digest_text="SELECT bidwinnr_nm, count(id) FROM bid_results GROUP BY ...",
            count_star=4,
            sum_timer_wait_ps=78_410_000_000_000,
            sum_timer_wait_sec=78.41,
            min_timer_wait_ms=10000.0,
            avg_timer_wait_ms=19602.5,
            max_timer_wait_ms=23030.0,
        ),
    ]

    warm_stats = [
        DigestStat(
            digest="d1",
            digest_text="SELECT count(*) FROM bid_announcements WHERE dminstt_nm LIKE ...",
            count_star=0,
            sum_timer_wait_ps=0,
            sum_timer_wait_sec=0.0,
            min_timer_wait_ms=0.0,
            avg_timer_wait_ms=0.0,
            max_timer_wait_ms=0.0,
        ),
        DigestStat(
            digest="d2",
            digest_text="SELECT bidwinnr_nm, count(id) FROM bid_results GROUP BY ...",
            count_star=1,
            sum_timer_wait_ps=10_000_000_000,
            sum_timer_wait_sec=0.01,
            min_timer_wait_ms=10.0,
            avg_timer_wait_ms=10.0,
            max_timer_wait_ms=10.0,
        ),
    ]

    diffs = calculate_attribution_diff(cold_stats, warm_stats)

    assert len(diffs) == 2
    # 1위 d1 (delta 89.09s), 2위 d2 (delta 78.40s)
    assert diffs[0].digest == "d1"
    assert diffs[0].delta_sum_sec == pytest.approx(89.09)
    assert diffs[0].delta_count == 4
    assert diffs[0].delta_max_ms == pytest.approx(27668.0)

    assert diffs[1].digest == "d2"
    assert diffs[1].delta_sum_sec == pytest.approx(78.40)
    assert diffs[1].delta_count == 3
    assert diffs[1].delta_max_ms == pytest.approx(23020.0)


# ---------------------------------------------------------------------------
# 4. performance_schema 비활성/오류 시 fail-closed 검증
# ---------------------------------------------------------------------------
def test_check_performance_schema_disabled_raises():
    """performance_schema=OFF 이면 PerformanceSchemaUnavailableError 를 발생시켜야 합니다."""
    mock_executor = MagicMock(return_value=[{"ps_enabled": "OFF"}])
    with pytest.raises(PerformanceSchemaUnavailableError) as excinfo:
        check_performance_schema(mock_executor)
    assert "비활성화" in str(excinfo.value)


def test_check_performance_schema_query_failure_raises():
    """performance_schema 조회 실패 시 PerformanceSchemaUnavailableError 를 발생시켜야 합니다."""
    mock_executor = MagicMock(
        side_effect=Exception("Access denied for table events_statements_summary_by_digest")
    )
    with pytest.raises(PerformanceSchemaUnavailableError) as excinfo:
        check_performance_schema(mock_executor)
    assert "확인 실패" in str(excinfo.value) or "조회 실패" in str(excinfo.value)


def test_reset_performance_schema_failure_raises():
    """초기화 쿼리 실패 시 PerformanceSchemaUnavailableError 를 발생시켜야 합니다."""
    mock_executor = MagicMock(side_effect=Exception("Permission denied"))
    with pytest.raises(PerformanceSchemaUnavailableError):
        reset_performance_schema_digest(mock_executor)


def test_main_returns_code_2_on_performance_schema_unavailable():
    """CLI 실행 시 performance_schema 미가용 상태면 종료 코드 2를 반환해야 합니다."""
    with patch("scripts.measure_coldsql_attribution.default_sqlalchemy_executor") as mock_get_exec:
        mock_get_exec.return_value = MagicMock(
            side_effect=PerformanceSchemaUnavailableError("PS OFF")
        )
        exit_code = main(["--fixture", "tests/fixtures/dummy.json"])
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 5. Canonical 게이트 판정 및 fixture 검증
# ---------------------------------------------------------------------------
def test_canonical_false_on_unregistered_fixture_hash(tmp_path: Path):
    """등록되지 않은 fixture 파일에 대해 canonical=false 와 실패 게이트가 기록되어야 합니다."""
    custom_fixture = tmp_path / "custom_fixture.json"
    custom_fixture.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "q01", "question": "테스트 질문 1"},
                    {"id": "q02", "question": "테스트 질문 2"},
                ]
            }
        ),
        encoding="utf-8",
    )

    mock_db = MagicMock(return_value=[{"ps_enabled": "ON"}])
    mock_query_sender = MagicMock(return_value={"ok": True, "elapsed_ms": 100.0, "payload": {}})

    with patch(
        "scripts.measure_coldsql_attribution.get_git_status", return_value=("abc1234", False)
    ):
        report = run_attribution_measurement(
            db_executor=mock_db,
            fixture_path=custom_fixture,
            limit=0,
            repetitions=3,
            query_sender=mock_query_sender,
        )

    canonical_eval = report["canonical_evaluation"]
    assert canonical_eval["is_canonical"] is False
    assert "fixture_sha256_canonical" in canonical_eval["failed_gates"]


# ---------------------------------------------------------------------------
# 6. 전체 측정 흐름 통합 테스트 (Mock 기반)
# ---------------------------------------------------------------------------
def test_run_attribution_measurement_complete_flow(tmp_path: Path):
    """cold 와 warm 단계가 정상 수행되고 결과 dict 구조가 완전한지 검증합니다."""
    fixture_file = tmp_path / "fixture.json"
    fixture_file.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "q03", "question": "수요기관별 낙찰 질문"},
                    {"id": "q08", "question": "2026년 물품 질문"},
                ]
            }
        ),
        encoding="utf-8",
    )

    db_calls = []

    def mock_db(sql: str) -> list[dict[str, Any]]:
        db_calls.append(sql)
        if "ps_enabled" in sql:
            return [{"ps_enabled": "ON"}]
        if "LIMIT 1" in sql:
            return [
                {"DIGEST": "d0", "DIGEST_TEXT": "SELECT 1", "COUNT_STAR": 1, "SUM_TIMER_WAIT": 1000}
            ]
        if "TRUNCATE" in sql:
            return []
        if "SUM_TIMER_WAIT DESC" in sql:
            # Cold vs Warm 호출 구분
            call_count = sum(1 for c in db_calls if "SUM_TIMER_WAIT DESC" in c)
            if call_count == 1:
                # Cold 응답
                return [
                    {
                        "DIGEST": "d_like",
                        "DIGEST_TEXT": "SELECT count(*) FROM bid_announcements WHERE dminstt_nm LIKE ?",
                        "COUNT_STAR": 2,
                        "SUM_TIMER_WAIT": 20_000_000_000_000,
                        "MIN_TIMER_WAIT": 10_000_000_000,
                        "AVG_TIMER_WAIT": 10_000_000_000,
                        "MAX_TIMER_WAIT": 10_000_000_000,
                    }
                ]
            else:
                # Warm 응답 (캐시 적중으로 SQL 미호출)
                return []
        return []

    mock_redis = MagicMock()
    mock_sender = MagicMock(
        return_value={"ok": True, "elapsed_ms": 50.0, "payload": {"answer": "ok"}}
    )

    with patch(
        "scripts.measure_coldsql_attribution.get_git_status", return_value=("abc1234", False)
    ):
        report = run_attribution_measurement(
            db_executor=mock_db,
            redis_client=mock_redis,
            flush_cache_requested=True,
            fixture_path=fixture_file,
            item_ids=["q03", "q08"],
            limit=0,
            repetitions=1,
            query_sender=mock_sender,
            allow_unknown_provenance=True,
        )

    # Redis FLUSHALL 호출 확인
    mock_redis.flushall.assert_called_once()
    assert report["metadata"]["cache_flushed"] is True
    assert report["metadata"]["flush_cache_requested"] is True

    # HTTP 질의: cold 2문항 + warm 2문항 = 총 4회
    assert mock_sender.call_count == 4
    assert len(report["cold_measurements"]["queries"]) == 2
    assert len(report["warm_measurements"]["queries"]) == 2

    # Diff 및 Summary 확인
    assert len(report["attribution_diff_table"]) == 1
    top_item = report["attribution_diff_table"][0]
    assert top_item["digest"] == "d_like"
    assert top_item["delta_sum_sec"] == pytest.approx(20.0)

    assert report["summary"]["total_cold_sql_sec"] == pytest.approx(20.0)
    assert report["summary"]["total_warm_sql_sec"] == 0.0
    assert report["summary"]["top_cost_query_delta_sec"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 7. Canonical 게이트의 캐시 비우기 결박 회귀 검증
# ---------------------------------------------------------------------------
def test_canonical_failed_gate_when_flush_cache_not_requested(tmp_path: Path):
    """--flush-cache 가 지정되지 않으면 canonical=false 이고 flush_cache_executed 실패 게이트가 기록되어야 합니다."""
    fixture_file = tmp_path / "fixture.json"
    fixture_file.write_text(
        json.dumps({"items": [{"id": "q03", "question": "테스트"}]}),
        encoding="utf-8",
    )
    mock_db = MagicMock(return_value=[{"ps_enabled": "ON"}])
    mock_sender = MagicMock(return_value={"ok": True, "elapsed_ms": 10.0, "payload": {}})

    with patch(
        "scripts.measure_coldsql_attribution.get_git_status", return_value=("abc1234", False)
    ):
        report = run_attribution_measurement(
            db_executor=mock_db,
            redis_client=None,
            flush_cache_requested=False,
            fixture_path=fixture_file,
            item_ids=["q03"],
            query_sender=mock_sender,
            allow_unknown_provenance=True,
        )

    canonical_eval = report["canonical_evaluation"]
    assert canonical_eval["is_canonical"] is False
    assert "flush_cache_executed" in canonical_eval["failed_gates"]


def test_canonical_gate_cleared_when_both_flush_requested_and_cache_flushed(tmp_path: Path):
    """flush_cache_requested 와 cache_flushed 가 모두 True 일 때만 flush_cache_executed 게이트가 통과(해제)되어야 합니다."""
    fixture_file = tmp_path / "fixture.json"
    fixture_file.write_text(
        json.dumps({"items": [{"id": "q03", "question": "테스트"}]}),
        encoding="utf-8",
    )
    mock_db = MagicMock(return_value=[{"ps_enabled": "ON"}])
    mock_redis = MagicMock()
    mock_sender = MagicMock(return_value={"ok": True, "elapsed_ms": 10.0, "payload": {}})

    with patch(
        "scripts.measure_coldsql_attribution.get_git_status", return_value=("abc1234", False)
    ):
        report = run_attribution_measurement(
            db_executor=mock_db,
            redis_client=mock_redis,
            flush_cache_requested=True,
            fixture_path=fixture_file,
            item_ids=["q03"],
            query_sender=mock_sender,
            allow_unknown_provenance=True,
        )

    canonical_eval = report["canonical_evaluation"]
    assert "flush_cache_executed" not in canonical_eval["failed_gates"]


# ---------------------------------------------------------------------------
# 6. 산출물 저장 경로
# ---------------------------------------------------------------------------
def test_main_writes_output_file_when_output_given(tmp_path: Path):
    """--output 지정 시 측정 보고서가 실제 파일로 저장되어야 합니다.

    2026-09-01 에 이 경로가 dump_strict_json(report, out_path) 로 잘못 호출되어
    32문항 x 3회 측정을 완주하고도 TypeError 로 결과 전량이 유실됐습니다.
    측정은 되돌리기 비싼 작업이므로 저장 경로를 회귀로 고정합니다.
    """
    out_path = tmp_path / "nested" / "report.json"
    report = {"metadata": {"item_count": 32}, "summary": {"cold_total_sql_sec": 1.5}}

    with patch("scripts.measure_coldsql_attribution.run_attribution_measurement") as mock_run:
        mock_run.return_value = report
        exit_code = main(
            [
                "--fixture",
                "data/eval/llm_quality_fixture_v2.json",
                "--output",
                str(out_path),
            ]
        )

    assert exit_code == 0
    assert out_path.exists(), "--output 경로에 보고서 파일이 생성되어야 합니다."
    assert json.loads(out_path.read_text(encoding="utf-8")) == report
