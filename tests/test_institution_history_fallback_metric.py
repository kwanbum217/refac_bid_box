"""기관 이력 폴백 계측 시험.

집계 표에 없는 신규·비활성 기관이 학습과 다른 폴백 정의로 계산될 때
inst_history_fallback 카운터가 reason 별로 1 오르고, 반환 값은 기존과
같은지 확인합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.config import settings
from src.app.core.db import Base
from src.app.core.observability import (
    INST_HISTORY_FALLBACK,
    reset_observability_for_testing,
    setup_observability,
)
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidResult
from src.ml.institution_history import lookup_institution_stats


@pytest.fixture(autouse=True)
def _cleanup_observability():
    """테스트 전후로 관측성 레지스트리와 설정을 원상 복구합니다."""
    reset_observability_for_testing()
    original = (
        settings.OTEL_ENABLED,
        settings.OTEL_METRICS_ENABLED,
        settings.OTEL_EXPORTER_TYPE,
    )
    yield
    reset_observability_for_testing()
    settings.OTEL_ENABLED, settings.OTEL_METRICS_ENABLED, settings.OTEL_EXPORTER_TYPE = original


@pytest.fixture
def memory_session():
    """BidResult 와 집계 표를 담는 인메모리 SQLite 세션."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _enable_metrics_with_reader() -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    settings.OTEL_ENABLED = True
    settings.OTEL_METRICS_ENABLED = True
    settings.OTEL_EXPORTER_TYPE = "none"
    setup_observability(custom_metric_exporter=reader)
    return reader


def _fallback_points(reader: InMemoryMetricReader) -> list[tuple[dict[str, object], float]]:
    """리더에서 폴백 카운터의 (속성, 값) 목록을 평탄화합니다."""
    metrics_data = reader.get_metrics_data()
    if metrics_data is None:
        return []
    points: list[tuple[dict[str, object], float]] = []
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != INST_HISTORY_FALLBACK:
                    continue
                for data_point in getattr(metric.data, "data_points", []):
                    points.append((dict(data_point.attributes), float(data_point.value)))
    return points


def _seed_results(session, institution_name: str, category: str, rates, reference_date) -> None:
    for idx, rate in enumerate(rates):
        session.add(
            BidResult(
                bid_ntce_no=f"FALLBACK-{idx:04d}",
                bid_ntce_ord="00",
                dminstt_nm=institution_name,
                category=category,
                rl_openg_dt=reference_date - timedelta(days=idx + 1),
                sucsf_bid_rate=rate,
                collected_at=utcnow(),
            )
        )
    session.commit()


def test_default_fallback_records_metric_and_keeps_value():
    """기관명이나 세션이 없으면 기본값을 쓰고 reason=default 로 남깁니다."""
    reader = _enable_metrics_with_reader()

    stats = lookup_institution_stats({"category": "Servc"}, None)

    assert stats == {
        "inst_hist_rate": 0.9011,
        "inst_sample_cnt": 0.0,
        "inst_ewm_rate": 0.9011,
    }
    assert _fallback_points(reader) == [({"reason": "default"}, 1.0)]


def test_recent_window_fallback_records_metric_and_keeps_average(memory_session):
    """집계 표에 없으면 365일 실시간 집계로 내려가고 reason=recent_window 로 남깁니다."""
    reader = _enable_metrics_with_reader()
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    rates = [87.5, 88.0, 88.5, 89.0, 89.5]
    _seed_results(memory_session, "신규기관", "Servc", rates, reference_date)

    stats = lookup_institution_stats(
        {
            "dminstt_nm": "신규기관",
            "category": "Servc",
            "openg_dt": reference_date,
        },
        memory_session,
    )

    expected = sum(rates) / len(rates) / 100.0
    assert stats["inst_hist_rate"] == pytest.approx(expected)
    assert stats["inst_ewm_rate"] == pytest.approx(expected)
    assert stats["inst_sample_cnt"] == 0.0
    assert _fallback_points(reader) == [({"reason": "recent_window"}, 1.0)]


def test_each_fallback_branch_increments_only_its_reason(memory_session):
    """두 폴백이 한 실행에서 각각 한 번씩 오르고 다른 속성은 붙지 않습니다."""
    reader = _enable_metrics_with_reader()
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    _seed_results(memory_session, "신규기관", "Servc", [88.0] * 5, reference_date)

    lookup_institution_stats({"category": "Thng"}, None)
    lookup_institution_stats(
        {
            "dminstt_nm": "신규기관",
            "category": "Servc",
            "openg_dt": reference_date,
        },
        memory_session,
    )

    points = sorted(_fallback_points(reader), key=lambda item: str(item[0]["reason"]))
    assert points == [
        ({"reason": "default"}, 1.0),
        ({"reason": "recent_window"}, 1.0),
    ]


def test_metrics_disabled_keeps_fallback_values():
    """메트릭이 꺼져 있어도 폴백 값과 반환 형태는 그대로입니다."""
    settings.OTEL_ENABLED = False
    settings.OTEL_METRICS_ENABLED = None
    setup_observability()

    stats = lookup_institution_stats({"category": "Thng"}, None)

    assert stats == {
        "inst_hist_rate": 0.9132,
        "inst_sample_cnt": 0.0,
        "inst_ewm_rate": 0.9132,
    }
