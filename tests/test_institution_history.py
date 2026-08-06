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
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidResult
from src.ml.institution_history import (
    EWM_HALFLIFE,
    _default_institution_rate,
    _normalize_institution_name,
    _rebuild_ewm_rates,
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
            collected_at=utcnow(),
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
        reference_date=utcnow(),
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
    seed_results(
        memory_session, "서울시", "Servc", [87.5], reference_date - timedelta(days=10), prefix="IN"
    )
    seed_results(
        memory_session, "서울시", "Servc", [99.0], reference_date - timedelta(days=40), prefix="OUT"
    )

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
    seed_results(
        memory_session, "서울시", "Servc", [87.5], reference_date - timedelta(days=1), prefix="PAST"
    )
    seed_results(
        memory_session,
        "서울시",
        "Servc",
        [99.0],
        reference_date + timedelta(days=1),
        prefix="FUTURE",
    )

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
    assert (
        _resolve_institution_name({"dminstt_nm": "각 수요기관", "ntce_instt_nm": "공고기관"})
        == "공고기관"
    )
    assert _resolve_institution_name({"dminstt_nm": "수요기관", "ntce_instt_nm": ""}) == ""


def test_calculate_excludes_outlier_rates(memory_session):
    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    seed_results(
        memory_session, "서울시", "Servc", [87.5, 88.0, 99.0, 100.0, 150.0], reference_date
    )

    rate = calculate_institution_win_rate(
        memory_session,
        institution_name="서울시",
        reference_date=reference_date,
        category="Servc",
        min_samples=1,
    )
    assert rate == pytest.approx((87.5 + 88.0 + 99.0) / 3 / 100.0)


def test_lookup_institution_history_without_institution_returns_default(memory_session):
    features = {"category": "Servc", "openg_dt": utcnow()}
    rate = lookup_institution_history(features, memory_session)
    assert rate == pytest.approx(0.9011)


# ---------------------------------------------------------------------------
# 학습/추론 경로 연결 검증
#
# inst_hist_rate 는 낙찰률 예측의 유일한 실질 신호입니다. 양쪽 경로가 같은
# 정의를 써야 하고(AGENTS.md 6항), 한쪽이 상수로 떨어지면 성능이 무너집니다.
# ---------------------------------------------------------------------------


def test_training_path_injects_real_history():
    """trainer 는 특징 생성 전에 프레임 단위로 이력을 붙여야 합니다."""
    import inspect

    from src.ml import trainer

    source = inspect.getsource(trainer.ModelTrainer.train_and_register)
    assert "attach_institution_history(df_raw)" in source
    assert source.index("attach_institution_history") < source.index("build_feature_frame")


def test_serving_path_receives_session():
    """predictor 가 session 을 넘기지 않으면 추론만 상수가 됩니다."""
    import inspect

    from src.ml import predictor

    assert "build_feature_dict(request_data, session)" in inspect.getsource(
        predictor.SingletonPredictor.predict
    )


def test_attach_institution_history_excludes_self_and_future():
    """각 행은 자기 자신과 미래를 뺀 과거 평균만 받아야 합니다."""
    import pandas as pd

    from src.ml.institution_history import attach_institution_history

    df = pd.DataFrame(
        {
            "dminstt_nm": ["A"] * 6,
            "category": ["Servc"] * 6,
            "openg_dt": pd.date_range("2024-01-01", periods=6, freq="D"),
            "winning_rate": [80.0, 82.0, 84.0, 86.0, 88.0, 99.0],
        }
    )
    out = attach_institution_history(df, min_samples=5)

    # 6번째 행만 과거 5건을 갖습니다. 평균 (80+82+84+86+88)/5 = 84.0
    assert out.loc[5, "inst_sample_cnt"] == 5
    assert out.loc[5, "inst_hist_rate"] == pytest.approx(0.84)
    # 자기 값 99.0 은 반영되면 안 됩니다.
    assert out.loc[5, "inst_hist_rate"] != pytest.approx(0.865)
    # 이력이 모자란 앞 행들은 카테고리 기본값입니다.
    assert out.loc[0, "inst_hist_rate"] == pytest.approx(0.9011)


def test_attach_institution_history_preserves_row_order():
    """정렬 후 순서를 되돌리지 않으면 목표값과 특징이 어긋납니다."""
    import pandas as pd

    from src.ml.institution_history import attach_institution_history

    df = pd.DataFrame(
        {
            "dminstt_nm": ["A", "B", "A"],
            "openg_dt": ["2024-03-01", "2024-01-01", "2024-02-01"],
            "winning_rate": [90.0, 85.0, 80.0],
            "marker": [10, 20, 30],
        }
    )
    out = attach_institution_history(df)
    assert list(out["marker"]) == [10, 20, 30]


def test_attach_institution_history_drops_outlier_rates():
    """0 이나 100 을 넘는 낙찰률은 데이터 오류라 이력에서 빠져야 합니다."""
    import pandas as pd

    from src.ml.institution_history import attach_institution_history

    df = pd.DataFrame(
        {
            "dminstt_nm": ["A"] * 7,
            "category": ["Servc"] * 7,
            "openg_dt": pd.date_range("2024-01-01", periods=7, freq="D"),
            "winning_rate": [80.0, 0.0, 82.0, 500.0, 84.0, 86.0, 88.0],
        }
    )
    # 6번 행의 과거 6건 중 0.0 과 500.0 이 빠져 유효 이력은 4건입니다.
    out = attach_institution_history(df, min_samples=4)
    assert out.loc[6, "inst_sample_cnt"] == 4
    assert out.loc[6, "inst_hist_rate"] == pytest.approx((80 + 82 + 84 + 86) / 4 / 100)

    # 최소 표본에 못 미치면 기본값으로 떨어집니다.
    strict = attach_institution_history(df, min_samples=5)
    assert strict.loc[6, "inst_hist_rate"] == pytest.approx(0.9011)


def test_attach_ewm_excludes_self_and_same_timestamp():
    """동시각 공고끼리는 서로의 결과를 이력으로 보면 안 됩니다."""
    import pandas as pd

    from src.ml.institution_history import attach_institution_history

    df = pd.DataFrame(
        {
            "dminstt_nm": ["A"] * 8,
            "category": ["Servc"] * 8,
            "openg_dt": pd.to_datetime(
                ["2024-01-01"] * 2 + ["2024-02-01"] * 2 + ["2024-03-01"] * 2 + ["2024-04-01"] * 2
            ),
            "winning_rate": [80.0, 82.0, 84.0, 86.0, 88.0, 90.0, 99.0, 70.0],
        }
    )

    out = attach_institution_history(df, min_samples=5)

    assert out.loc[0, "inst_ewm_rate"] == pytest.approx(0.9011)
    assert out.loc[1, "inst_ewm_rate"] == pytest.approx(0.9011)
    assert out.loc[6, "inst_ewm_rate"] == pytest.approx(out.loc[7, "inst_ewm_rate"])
    assert 0.80 <= out.loc[6, "inst_ewm_rate"] <= 0.90


def test_streaming_ewm_matches_pandas(memory_session):
    """집계 경로의 스트리밍 계산이 학습 경로의 pandas 정의와 같아야 합니다."""
    import pandas as pd

    reference_date = datetime(2024, 6, 15, 10, 0, 0)
    rates = [87.5, 88.0, 91.0, 89.0, 90.5]
    seed_results(memory_session, "서울시", "Servc", rates, reference_date)

    result = _rebuild_ewm_rates(memory_session, min_samples=5)
    expected = pd.Series(list(reversed(rates))).ewm(halflife=EWM_HALFLIFE).mean().iloc[-1]

    assert result[("서울시", "Servc")] == pytest.approx(expected)
