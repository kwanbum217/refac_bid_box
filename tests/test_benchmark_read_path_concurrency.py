"""
tests/test_benchmark_read_path_concurrency.py

읽기 경로 동시성 벤치마크 하니스 및 READ_PATH_PRELOAD_ANNOUNCEMENTS 플래그 검증.

검증 항목:
1. READ_PATH_PRELOAD_ANNOUNCEMENTS 플래그의 기본값이 True 인지 확인.
2. 플래그가 True 일 때 일괄 조회가 동작하고, False 로 설정 시 선채움을 건너뛰고
   종전 단건 경로로 동작하며, 두 경로의 직렬화 결과가 1:1 로 동등한지 확인.
3. 백분위 계산(calculate_percentile)이 표본 0개(NaN), 1개, 짝수 개, 홀수 개에서
   정확한 선형 보간 값을 산출하는지 확인.
4. 하니스가 --mode warm, --mode concurrent, --mode ab 를 모두 지원하는지 확인.
5. ab 모드가 A 와 B 를 교대로 최소 3 왕복 반복하는 구조인지 확인 및 3회 미만 시 거부 확인.
6. 하니스의 --dry-run 플래그가 실제 네트워크/Docker 호출 없이 올바른 실행 계획을 출력하는지 확인.
7. --json 옵션으로 실행 계획 및 결과를 기계 판독 가능한 JSON 으로 저장할 수 있는지 확인.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

from sqlalchemy import event

from scripts.benchmark_read_path_concurrency import (
    TARGETS,
    MetricStats,
    build_execution_plan,
    calculate_percentile,
    format_round_comparison,
    main,
)
from src.app.api.v1.bids import _serialize_results
from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult


class QueryCounter:
    """SQLAlchemy 쿼리 실행 횟수 계측기."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self.queries: list[str] = []

    def __enter__(self):
        self.count = 0
        self.queries.clear()
        event.listen(self.engine, "before_cursor_execute", self._callback)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        event.remove(self.engine, "before_cursor_execute", self._callback)

    def _callback(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.queries.append(statement)


def _create_announcement(db, **overrides) -> BidAnnouncement:
    defaults = {
        "bid_ntce_no": "20240199999",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "동시성 테스트 공고",
        "dminstt_nm": "테스트 수요기관",
        "ntce_instt_nm": "테스트 공고기관",
        "category": "Servc",
        "base_amount": 100_000_000,
        "presmpt_prce": 90_000_000,
        "bid_ntce_dt": utcnow(),
        "raw_data": None,
    }
    defaults.update(overrides)
    ann = BidAnnouncement(**defaults)
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def _create_result(db, **overrides) -> BidResult:
    defaults = {
        "bid_ntce_no": "20240199999",
        "bid_ntce_ord": "00",
        "bid_ntce_nm": "동시성 테스트 공고",
        "bidwinnr_nm": "낙찰업체",
        "sucsf_bid_amt": 88_000_000,
        "sucsf_bid_rate": Decimal("88.0000"),
        "rl_openg_dt": utcnow(),
        "dminstt_nm": "테스트 수요기관",
        "category": "Servc",
        "raw_data": None,
    }
    defaults.update(overrides)
    res = BidResult(**defaults)
    db.add(res)
    db.commit()
    db.refresh(res)
    return res


# ==============================================================================
# 1. 설정 플래그 기본값 및 토글/동등성 검증
# ==============================================================================


def test_default_flag_value():
    """READ_PATH_PRELOAD_ANNOUNCEMENTS 의 기본값이 True 여야 함."""
    assert settings.READ_PATH_PRELOAD_ANNOUNCEMENTS is True


def test_flag_toggle_and_output_equivalence(isolated_db, monkeypatch):
    """플래그가 True 일 때 일괄 쿼리 1회, False 일 때 건별 쿼리 수행 및 두 경로의 결과 동등성 검증."""
    # 5개의 공고 및 낙찰 생성
    created_results: list[BidResult] = []
    for i in range(5):
        _create_announcement(
            isolated_db,
            bid_ntce_no=f"ABTEST-{i:03d}",
            bid_ntce_ord="000",
            category="Servc",
            base_amount=100_000_000,
        )
        res = _create_result(
            isolated_db,
            bid_ntce_no=f"ABTEST-{i:03d}",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=85_000_000 + i * 1_000_000,
            sucsf_bid_rate=Decimal(str(85.0 + i)),
        )
        created_results.append(res)

    engine = isolated_db.get_bind()

    # 1. 플래그가 True 인 기본 상태 (A 경로: 선채움 ON)
    monkeypatch.setattr(settings, "READ_PATH_PRELOAD_ANNOUNCEMENTS", True)
    results_a = (
        isolated_db.query(BidResult)
        .filter(BidResult.bid_ntce_no.like("ABTEST%"))
        .order_by(BidResult.id)
        .all()
    )
    for r in results_a:
        if hasattr(r, "_matching_announcement_cache"):
            delattr(r, "_matching_announcement_cache")

    with QueryCounter(engine) as counter_a:
        serialized_a = _serialize_results(isolated_db, results_a)

    # 선채움 쿼리 1회만 발생
    assert counter_a.count == 1
    assert len(serialized_a) == 5

    # 2. 플래그가 False 인 상태 (B 경로: 선채움 OFF, 단건 폴백)
    monkeypatch.setattr(settings, "READ_PATH_PRELOAD_ANNOUNCEMENTS", False)
    results_b = (
        isolated_db.query(BidResult)
        .filter(BidResult.bid_ntce_no.like("ABTEST%"))
        .order_by(BidResult.id)
        .all()
    )
    for r in results_b:
        if hasattr(r, "_matching_announcement_cache"):
            delattr(r, "_matching_announcement_cache")

    with QueryCounter(engine) as counter_b:
        serialized_b = _serialize_results(isolated_db, results_b)

    # 단건 폴백이므로 행마다 최소 1회 이상 쿼리 발생 (5행이면 최소 5회)
    assert counter_b.count >= 5
    assert len(serialized_b) == 5

    # 3. 두 경로의 직렬화 결과가 모든 필드에서 완전히 동일해야 함 (값 동등성)
    for item_a, item_b in zip(serialized_a, serialized_b, strict=True):
        assert item_a == item_b
        assert item_a["display_winning_rate"] is not None


# ==============================================================================
# 2. 백분위 집계 함수 검증 (0개, 1개, 짝수 개, 홀수 개)
# ==============================================================================


def test_calculate_percentile_empty():
    """빈 목록인 경우 math.isnan 을 반환해야 함."""
    val = calculate_percentile([], 50.0)
    assert math.isnan(val)


def test_calculate_percentile_single_sample():
    """표본이 1개인 경우 백분위 q에 관계없이 그 값 자체가 반환되어야 함."""
    val = calculate_percentile([42.5], 50.0)
    assert val == 42.5
    val_95 = calculate_percentile([42.5], 95.0)
    assert val_95 == 42.5
    val_0 = calculate_percentile([42.5], 0.0)
    assert val_0 == 42.5
    val_100 = calculate_percentile([42.5], 100.0)
    assert val_100 == 42.5


def test_calculate_percentile_even_samples():
    """표본이 짝수 개일 때 올바른 선형 보간 값을 산출해야 함."""
    # 2개 표본: [10.0, 20.0]
    # position = (2 - 1) * 0.5 = 0.5 -> lower=0, upper=1, weight=0.5 -> 10*0.5 + 20*0.5 = 15.0
    val_p50 = calculate_percentile([10.0, 20.0], 50.0)
    assert val_p50 == 15.0

    # 4개 표본: [10.0, 20.0, 30.0, 40.0]
    # position = 3 * 0.5 = 1.5 -> lower=1, upper=2, weight=0.5 -> 20*0.5 + 30*0.5 = 25.0
    val_4_p50 = calculate_percentile([10.0, 20.0, 30.0, 40.0], 50.0)
    assert val_4_p50 == 25.0

    # position = 3 * 0.75 = 2.25 -> lower=2, upper=3, weight=0.25 -> 30*0.75 + 40*0.25 = 32.5
    val_4_p75 = calculate_percentile([10.0, 20.0, 30.0, 40.0], 75.0)
    assert val_4_p75 == 32.5


def test_calculate_percentile_odd_samples():
    """표본이 홀수 개일 때 정확한 중앙값 및 백분위를 산출해야 함."""
    samples = [10.0, 20.0, 30.0]
    val_p50 = calculate_percentile(samples, 50.0)
    assert val_p50 == 20.0


def test_metric_stats_aggregation():
    """MetricStats.from_latencies 가 P50, P95, P99, mean, min, max 를 올바르게 집계하는지 검증."""
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = MetricStats.from_latencies(
        name="테스트 경로",
        path="/api/test",
        is_control=False,
        latencies=latencies,
        errors=0,
    )
    assert stats.count == 5
    assert stats.p50_ms == 30.0
    assert stats.p95_ms == 48.0
    assert stats.mean_ms == 30.0
    assert stats.min_ms == 10.0
    assert stats.max_ms == 50.0
    assert stats.errors == 0

    d = stats.to_dict()
    assert d["name"] == "테스트 경로"
    assert d["count"] == 5
    assert d["p50_ms"] == 30.0


# ==============================================================================
# 3. 하니스 모드, 타겟, 실행 계획 및 교대 반복 검증
# ==============================================================================


def test_targets_coverage_and_classification():
    """정본 사양 8개 경로가 모두 포함되어 있고 대조군 5개, 실험군 3개로 올바르게 분류되었는지 검증."""
    assert len(TARGETS) == 8
    controls = [t for t in TARGETS if t.is_control]
    treatments = [t for t in TARGETS if not t.is_control]

    assert len(controls) == 5
    assert len(treatments) == 3

    # 대조군 경로명 확인
    control_names = {t.name for t in controls}
    assert "공고 목록 1쪽" in control_names
    assert "공고 목록 50쪽" in control_names
    assert "공고 목록 용역 필터" in control_names
    assert "대시보드 통계" in control_names
    assert "공고 대비 낙찰 비교 통계" in control_names

    # 실험군 경로명 확인
    treatment_names = {t.name for t in treatments}
    assert "낙찰 목록 1쪽" in treatment_names
    assert "낙찰 목록 50쪽" in treatment_names
    assert "홈 컨텍스트" in treatment_names


def test_build_execution_plan_warm_mode():
    """warm 모드 실행 계획 검증."""
    plan = build_execution_plan(
        mode="warm",
        base_url="http://127.0.0.1:8000",
        rounds=1,
        concurrency=1,
        sample_count=30,
        warmup_count=3,
    )
    assert plan["mode"] == "warm"
    assert plan["concurrency"] == 1
    assert plan["sample_count"] == 30
    assert plan["warmup_count"] == 3
    assert len(plan["targets"]) == 8


def test_build_execution_plan_concurrent_mode():
    """concurrent 모드 실행 계획 검증."""
    plan = build_execution_plan(
        mode="concurrent",
        base_url="http://127.0.0.1:8000",
        rounds=1,
        concurrency=10,
        sample_count=100,
        warmup_count=3,
    )
    assert plan["mode"] == "concurrent"
    assert plan["concurrency"] == 10
    assert plan["sample_count"] == 100


def test_build_execution_plan_ab_mode_interleaved():
    """ab 모드가 최소 3 왕복 교대(A1, B1, A2, B2, A3, B3) 구조를 올바르게 구성하는지 검증."""
    plan = build_execution_plan(
        mode="ab",
        base_url="http://127.0.0.1:8000",
        rounds=3,
        concurrency=10,
        sample_count=100,
        warmup_count=3,
    )
    assert plan["mode"] == "ab"
    assert plan["ab_rounds"] == 3
    seq = plan["execution_sequence"]
    assert len(seq) == 6  # 3 왕복 * 2 (A, B)

    # 교대 순서 검증: A1, B1, A2, B2, A3, B3
    expected = [
        (1, "A", True),
        (1, "B", False),
        (2, "A", True),
        (2, "B", False),
        (3, "A", True),
        (3, "B", False),
    ]
    for actual_step, (exp_round, exp_var, exp_preload) in zip(seq, expected, strict=True):
        assert actual_step["round"] == exp_round
        assert actual_step["variant"] == exp_var
        assert actual_step["preload"] is exp_preload
        assert "READ_PATH_PRELOAD_ANNOUNCEMENTS=" in actual_step["restart_command"]


def test_ab_mode_rejects_less_than_three_rounds():
    """ab 모드에서 왕복 횟수가 3 미만이면 오류 종료해야 함."""
    exit_code = main(["--mode", "ab", "--rounds", "2", "--dry-run"])
    assert exit_code != 0


def test_dry_run_executes_safely_and_outputs_json(tmp_path, capsys):
    """--dry-run 실행 시 실제 요청 없이 0을 반환하고 --json 에 실행 계획을 저장하는지 검증."""
    json_path = tmp_path / "plan_output.json"
    exit_code = main(["--mode", "ab", "--rounds", "3", "--dry-run", "--json", str(json_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "읽기 경로 동시성 하니스 실행 계획 (DRY RUN)" in captured.out
    assert "컨테이너 재시작 명령:" in captured.out
    assert "공고 목록 1쪽" in captured.out
    assert "낙찰 목록 1쪽" in captured.out

    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["dry_run"] is True
    assert data["plan"]["mode"] == "ab"
    assert data["plan"]["target_count"] == 8
    assert len(data["plan"]["execution_sequence"]) == 6


def test_round_comparison_formatter():
    """format_round_comparison 이 A와 B의 P95 차이와 변화율을 정확히 계산하는지 검증."""
    stats_a = {
        "낙찰 목록 1쪽": MetricStats.from_latencies("낙찰 목록 1쪽", "/results", False, [80.0]),
        "공고 목록 1쪽": MetricStats.from_latencies("공고 목록 1쪽", "/bids", True, [60.0]),
    }
    stats_b = {
        "낙찰 목록 1쪽": MetricStats.from_latencies("낙찰 목록 1쪽", "/results", False, [200.0]),
        "공고 목록 1쪽": MetricStats.from_latencies("공고 목록 1쪽", "/bids", True, [62.0]),
    }

    table_str, diffs = format_round_comparison(1, stats_a, stats_b)
    assert "[왕복 1]" in table_str
    assert "낙찰 목록 1쪽" in diffs
    assert diffs["낙찰 목록 1쪽"]["a_p95_ms"] == 80.0
    assert diffs["낙찰 목록 1쪽"]["b_p95_ms"] == 200.0
    assert diffs["낙찰 목록 1쪽"]["diff_ms"] == -120.0
    assert diffs["낙찰 목록 1쪽"]["pct_change"] == -60.0
