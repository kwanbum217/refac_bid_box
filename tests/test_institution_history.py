"""
tests/test_institution_history.py

기관별 낙찰률 이력 계산 모듈 단위 테스트.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.bids import BidResult
from src.ml.institution_history import (
    _default_institution_rate,
    _normalize_institution_name,
    _resolve_category,
    _resolve_institution_name,
    _resolve_reference_date,
    calculate_institution_win_rate,
    lookup_institution_history,
)


@pytest.fixture
def memory_session():
    """BidResult 만 사용하는 인메모리 SQLite 세션."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def seed_results(session, institution_name, category, rates, reference_date, prefix="TEST"):
    """seed_count 개의 낙찰 결과를 reference_date 이전으로 생성합니다."""
    for idx, rate in enumerate(rates):
        result = BidResult(
            bid_ntce_no=f"{prefix}-{idx:04d}",
            bid_ntce_ord="00",
            dminstt_nm=institution_name,
            category=category,
            rl_openg_dt=reference_date - timedelta(days=idx + 1),
            sucsf_bid_rate=rate,
            collected_at=datetime.utcnow(),
        )
        session.add(result)
    session.commit()


def test_default_rate_by_category():
    assert _default_institution_rate("Servc") == 0.9011
    assert _default_institution_rate("Thng") == 0.9132
    assert _default_institution_rate("Cnstwk") == 0.8859
    assert _default_institution_rate("") == 0.9001


def test_normalize_institution_name():
    assert _normalize_institution_name("  서울시  교육청  ") == "서울시 교육청"
    assert _normalize_institution_name("경기도\t청") == "경기도 청"


def test_resolve_institution_name_prefers_dminstt_nm():
    features = {
        "dminstt_nm": "실제수요기관",
        "ntce_instt_nm": "공고기관",
        "ntceInsttNm": "기관별칭",
    }
    assert _resolve_institution_name(features) == "실제수요기관"


def test_resolve_institution_name_falls_back_to_ntce_instt_nm():
    features = {"ntce_instt_nm": "공고기관"}
    assert _resolve_institution_name(features) == "공고기관"


def test_resolve_institution_name_returns_empty_when_missing():
    assert _resolve_institution_name({}) == ""


def test_resolve_category():
    assert _resolve_category({"category": "Servc"}) == "Servc"
    assert _resolve_category({"category_code": "Thng"}) == "Thng"
    assert _resolve_category({}) == ""


def test_resolve_reference_date_uses_openg_dt():
    target = datetime(2024, 6, 15, 10, 0, 0)
    features = {
        "openg_dt": target,
        "bid_clse_dt": target + timedelta(days=1),
        "bid_ntce_dt": target + timedelta(days=2),
    }
    assert _resolve_reference_date(features) == target


def test_resolve_reference_date_falls_back_to_bid_clse_dt():
    target = datetime(2024, 6, 15, 10, 0, 0)
    features = {"bid_clse_dt": target, "bid_ntce_dt": target + timedelta(days=1)}
    assert _resolve_reference_date(features) == target


def test_resolve_reference_date_falls_back_to_now():
    result = _resolve_reference_date({})
    assert isinstance(result, datetime)


def test_calculate_returns_default_for_missing_institution_name(memory_session):
    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="",
        reference_date=datetime.utcnow(),
        category="Servc",
    )
    assert rate == pytest.approx(0.9011)


def test_calculate_returns_default_when_insufficient_samples(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5, 88.0], reference_date)

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=5,
    )
    assert rate == pytest.approx(0.9011)


def test_calculate_averages_percent_rate_values(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    rates = [87.5, 88.0, 88.5, 89.0, 89.5]
    seed_results(memory_session, "서울시", "Servc", rates, reference_date)

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=5,
    )
    assert rate == pytest.approx(sum(rates) / len(rates) / 100.0)


def test_calculate_filters_by_category(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5, 88.0], reference_date)
    seed_results(memory_session, "서울시", "Thng", [84.0, 85.0], reference_date)

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=2,
    )
    assert rate == pytest.approx((87.5 + 88.0) / 2 / 100.0)


def test_calculate_respects_reference_date_boundaries(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    # lookback_days=30 범위 안에 1건만 포함
    seed_results(memory_session, "서울시", "Servc", [87.5], reference_date - timedelta(days=10), prefix="IN")
    seed_results(memory_session, "서울시", "Servc", [99.0], reference_date - timedelta(days=40), prefix="OUT")

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        lookback_days=30,
        min_samples=1,
    )
    assert rate == pytest.approx(87.5 / 100.0)


def test_calculate_excludes_future_results(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5], reference_date - timedelta(days=1), prefix="PAST")
    seed_results(memory_session, "서울시", "Servc", [99.0], reference_date + timedelta(days=1), prefix="FUTURE")

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=1,
    )
    assert rate == pytest.approx(87.5 / 100.0)


def test_calculate_excludes_zero_rate_records(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5, 0.0], reference_date)

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=1,
    )
    assert rate == pytest.approx(87.5 / 100.0)


def test_lookup_institution_history_without_session_returns_default():
    features = {"category": "Servc"}
    rate = lookup_institution_history(features)
    assert rate == pytest.approx(0.9011)


def test_lookup_institution_history_with_session(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    rates = [87.5, 88.0, 88.5, 89.0, 89.5]
    seed_results(memory_session, "서울시", "Servc", rates, reference_date)

    features = {
        "dminstt_nm": "서울시",
        "category": "Servc",
        "openg_dt": reference_date,
    }
    rate = lookup_institution_history(features, memory_session)
    assert rate == pytest.approx(sum(rates) / len(rates) / 100.0)


def test_lookup_institution_history_uses_normalized_name(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5, 88.0, 88.5, 89.0, 89.5], reference_date)

    features = {
        "dminstt_nm": "  서울시  ",
        "category": "Servc",
        "openg_dt": reference_date,
    }
    rate = lookup_institution_history(features, memory_session)
    assert rate == pytest.approx((87.5 + 88.0 + 88.5 + 89.0 + 89.5) / 5 / 100.0)


def test_resolve_institution_name_skips_placeholder_institutions():
    assert _resolve_institution_name({"dminstt_nm": "각 수요기관", "ntce_instt_nm": "공고기관"}) == "공고기관"
    assert _resolve_institution_name({"dminstt_nm": "수요기관", "ntce_instt_nm": ""}) == ""


def test_calculate_excludes_outlier_rates(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(memory_session, "서울시", "Servc", [87.5, 88.0, 99.0, 100.0, 150.0], reference_date)

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=1,
    )
    assert rate == pytest.approx((87.5 + 88.0 + 99.0) / 3 / 100.0)


def test_lookup_institution_history_without_institution_returns_default(memory_session):
    features = {"category": "Servc", "openg_dt": datetime.utcnow()}
    rate = lookup_institution_history(features, memory_session)
    assert rate == pytest.approx(0.9011)


# ---------------------------------------------------------------------------
# 학습/추론 경로 연결 상태 고정
#
# institution_history 는 아직 production 경로에 연결돼 있지 않습니다.
# 한쪽만 연결하면 AGENTS.md 6항이 금지하는 train/serve skew 가 생기므로,
# 현재 상태를 테스트로 못박아 문서와 코드가 어긋나지 않게 합니다.
# ---------------------------------------------------------------------------


def test_production_feature_path_still_uses_constant():
    """trainer/predictor 는 session 을 넘기지 않으므로 상수가 나와야 합니다."""
    from src.ml.features import build_default_feature_map

    features = {
        "dminstt_nm": "서울특별시",
        "category": "Servc",
        "presumed_price": 1.0e8,
        "openg_dt": "2025-01-01",
    }
    assert build_default_feature_map(features)["inst_hist_rate"] == pytest.approx(0.9011)


def test_train_and_serve_use_the_same_session_policy():
    """학습과 추론이 같은 방식으로 특징을 만들어야 합니다.

    한쪽만 session 을 넘기도록 바뀌면 이 테스트가 실패합니다.
    양쪽을 함께 바꾸고 이 테스트를 갱신하십시오.
    """
    import inspect

    from src.ml import predictor, trainer

    trainer_call = "build_feature_frame(records)"
    predictor_call = "build_feature_dict(request_data)"
    assert trainer_call in inspect.getsource(trainer.ModelTrainer.train_and_register)
    assert predictor_call in inspect.getsource(predictor.SingletonPredictor.predict)
