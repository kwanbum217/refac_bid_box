"""tests/test_openg_collection_metrics.py

정기 수집(collect_bids) 지표와 Grafana 대시보드 계약 시험.

- (a) 지표 비활성 상태에서 record 함수가 예외 없이 무동작
- (b) InMemoryMetricReader 로 kind·category 속성별 카운터 누적 확인
- (c) 대시보드 JSON 파싱 및 모든 target expr 의 수집 지표 참조 확인
- (d) collect_bids 를 돌리지 않고 metrics 딕셔너리 -> 지표 변환 함수만 시험
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.app.core.config import settings
from src.app.core.observability import (
    BID_COLLECTION_FAILED_RANGES,
    BID_COLLECTION_SAVED_ROWS,
    get_metric_instruments,
    is_metrics_enabled,
    record_collection_failed_ranges,
    record_collection_metrics,
    record_collection_saved_rows,
    reset_observability_for_testing,
    setup_observability,
)

DASHBOARD_PATH = (
    Path(__file__).resolve().parents[1]
    / "docker"
    / "grafana"
    / "dashboards"
    / "openg_collection.json"
)

PROMETHEUS_SAVED_ROWS = "bid_collection_saved_rows_total"
PROMETHEUS_FAILED_RANGES = "bid_collection_failed_ranges_total"


@pytest.fixture(autouse=True)
def _cleanup_observability():
    """테스트 전후로 관측성 레지스트리와 설정을 원상 복구합니다."""
    reset_observability_for_testing()
    orig_otel_enabled = settings.OTEL_ENABLED
    orig_metrics_enabled = settings.OTEL_METRICS_ENABLED
    orig_exporter_type = settings.OTEL_EXPORTER_TYPE
    yield
    reset_observability_for_testing()
    settings.OTEL_ENABLED = orig_otel_enabled
    settings.OTEL_METRICS_ENABLED = orig_metrics_enabled
    settings.OTEL_EXPORTER_TYPE = orig_exporter_type


def _enable_metrics_with_reader() -> InMemoryMetricReader:
    """수집 지표를 켜고 인메모리 리더를 반환합니다."""
    reader = InMemoryMetricReader()
    settings.OTEL_ENABLED = True
    settings.OTEL_METRICS_ENABLED = True
    settings.OTEL_EXPORTER_TYPE = "none"
    setup_observability(custom_metric_exporter=reader)
    assert is_metrics_enabled()
    return reader


def _metric_points(reader: InMemoryMetricReader) -> list[tuple[str, dict[str, Any], float]]:
    """리더에서 (지표명, 속성, 값) 목록을 평탄화합니다."""
    metrics_data = reader.get_metrics_data()
    if metrics_data is None:
        return []
    points: list[tuple[str, dict[str, Any], float]] = []
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                for data_point in getattr(metric.data, "data_points", []):
                    points.append(
                        (
                            metric.name,
                            dict(data_point.attributes),
                            float(data_point.value),
                        )
                    )
    return points


def _saved_rows_by_attributes(
    points: list[tuple[str, dict[str, Any], float]],
) -> dict[tuple[Any, Any], float]:
    return {
        (attrs.get("category"), attrs.get("kind")): value
        for name, attrs, value in points
        if name == BID_COLLECTION_SAVED_ROWS
    }


def _failed_ranges_by_kind(
    points: list[tuple[str, dict[str, Any], float]],
) -> dict[Any, float]:
    return {
        attrs.get("kind"): value
        for name, attrs, value in points
        if name == BID_COLLECTION_FAILED_RANGES
    }


def test_record_functions_are_noop_when_metrics_disabled():
    """(a) 메트릭이 비활성일 때 record 함수가 예외 없이 아무것도 하지 않는다."""
    settings.OTEL_ENABLED = False
    settings.OTEL_METRICS_ENABLED = None
    setup_observability()

    assert not is_metrics_enabled()
    instruments = get_metric_instruments()
    assert instruments["bid_collection_saved_rows"] is None
    assert instruments["bid_collection_failed_ranges"] is None

    record_collection_saved_rows("openg_result", 12, "Cnstwk")
    record_collection_failed_ranges("openg_result", 2)
    record_collection_metrics(
        {
            "categories": {"Cnstwk": {"openg_result_count": 12}},
            "failed_ranges": [{"kind": "openg_result", "category": "Cnstwk"}],
        }
    )


def test_record_functions_accumulate_by_kind_and_category():
    """(b) kind·category 속성별로 카운터 값이 누적된다."""
    reader = _enable_metrics_with_reader()

    record_collection_saved_rows("openg_result", 5, "Cnstwk")
    record_collection_saved_rows("openg_result", 3, "Cnstwk")
    record_collection_saved_rows("result", 4, "Servc")
    record_collection_failed_ranges("openg_result", 2)
    record_collection_failed_ranges("license_limit", 1)

    points = _metric_points(reader)
    saved = _saved_rows_by_attributes(points)
    failed = _failed_ranges_by_kind(points)

    assert saved[("Cnstwk", "openg_result")] == 8.0
    assert saved[("Servc", "result")] == 4.0
    assert len(saved) == 2

    assert failed["openg_result"] == 2.0
    assert failed["license_limit"] == 1.0
    assert len(failed) == 2

    # 고유값(공고번호·기관명·날짜)이 속성에 들어가지 않는다.
    for _name, attrs, _value in points:
        assert set(attrs) <= {"kind", "category"}


def test_dashboard_json_targets_reference_collection_metrics():
    """(c) 대시보드 JSON 이 로드되고 모든 target expr 이 수집 지표를 참조한다."""
    payload = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    panels = payload.get("panels") or []
    assert len(panels) >= 3

    exprs: list[str] = []
    for panel in panels:
        assert panel["datasource"]["uid"] == "prometheus"
        for target in panel.get("targets", []):
            exprs.append(str(target.get("expr", "")))

    assert exprs
    metric_names = (BID_COLLECTION_SAVED_ROWS, BID_COLLECTION_FAILED_RANGES)
    for expr in exprs:
        assert any(name in expr for name in metric_names), (
            f"대시보드 질의가 수집 지표를 참조하지 않음: {expr}"
        )

    # Prometheus 노출 이름(_total 접미사)으로 질의한다.
    assert any(PROMETHEUS_SAVED_ROWS in expr for expr in exprs)
    assert any(PROMETHEUS_FAILED_RANGES in expr for expr in exprs)

    assert payload["uid"] == "bidbox-openg-collection"
    assert payload["schemaVersion"] == 39


def test_record_collection_metrics_maps_metrics_dict_to_instruments():
    """(d) collect_bids 의 metrics 딕셔너리가 카테고리별 적재 수와 실패 구간으로 변환된다."""
    reader = _enable_metrics_with_reader()

    metrics: dict[str, Any] = {
        "categories": {
            "Cnstwk": {
                "announcement_count": 3,
                "result_count": 4,
                "openg_result_count": 7,
            },
            "Servc": {
                "announcement_count": 0,
                "result_count": 1,
                "openg_result_count": 2,
            },
        },
        "failed_ranges": [
            {
                "category": "Cnstwk",
                "kind": "openg_result",
                "start_date": "20261001",
                "end_date": "20261002",
            },
            {
                "category": "Cnstwk",
                "kind": "openg_result",
                "start_date": "20261003",
                "end_date": "20261004",
            },
            {
                "category": "Servc",
                "kind": "result",
                "start_date": "20261005",
                "end_date": "20261006",
            },
        ],
    }

    record_collection_metrics(metrics)

    points = _metric_points(reader)
    saved = _saved_rows_by_attributes(points)
    failed = _failed_ranges_by_kind(points)

    assert saved == {
        ("Cnstwk", "announcement"): 3.0,
        ("Cnstwk", "result"): 4.0,
        ("Cnstwk", "openg_result"): 7.0,
        ("Servc", "result"): 1.0,
        ("Servc", "openg_result"): 2.0,
    }
    assert failed == {"openg_result": 2.0, "result": 1.0}


def test_record_collection_metrics_tolerates_malformed_entries():
    """(d) metrics 딕셔너리에 비정상 항목이 섞여도 예외 없이 넘어간다."""
    reader = _enable_metrics_with_reader()

    record_collection_metrics(
        {
            "categories": {
                "Cnstwk": None,
                "Servc": {"result_count": "invalid"},
            },
            "failed_ranges": [None, {"kind": None}, "junk"],
        }
    )
    record_collection_metrics({})

    assert _metric_points(reader) == []
