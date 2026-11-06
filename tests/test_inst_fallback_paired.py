"""기관 이력 폴백 쌍대 실측 시험.

(a) `fallback_definition` 기본값 경로가 기존 서빙 결과와 같은지,
(b) "training" 경로가 학습 정의(전 이력·50~120·실제 표본 수)로 계산되는지,
(c) 측정 스크립트의 폴백 대상 선별과 짝짓기 함수가 고정 입력에서 기대 수치를
내는지 확인합니다. 모델 예측은 monkeypatch 로 대체하므로 모델 파일이 없어도
돌아갑니다.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scripts.compare_servc_inst_fallback_paired import (
    build_paired_frame,
    is_fallback_target,
    select_fallback_targets,
    summarize_pairs,
)
from src.app.core.db import Base
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult, InstitutionWinRateStat
from src.ml.institution_history import (
    EWM_HALFLIFE,
    HISTORY_MIN_SAMPLES,
    calculate_institution_win_rate_training_parity,
    lookup_institution_history,
    lookup_institution_sample_count,
    lookup_institution_stats,
)

REFERENCE_DATE = datetime(2025, 6, 1, 10, 0, 0)


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


def _seed_result(
    session,
    *,
    no: str,
    institution: str,
    category: str,
    rate: float,
    opened_at: datetime,
) -> None:
    session.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord="00",
            dminstt_nm=institution,
            category=category,
            rl_openg_dt=opened_at,
            sucsf_bid_rate=rate,
            collected_at=utcnow(),
        )
    )
    session.commit()


def _fallback_payload(institution: str = "폴백기관", category: str = "Servc") -> dict:
    return {
        "dminstt_nm": institution,
        "category": category,
        "openg_dt": REFERENCE_DATE,
    }


def _seed_mixed_history(session) -> None:
    """365일 창·이상치 범위가 두 정의를 실제로 가르는 이력을 심습니다."""
    rows = [
        ("M-01", 60.0, datetime(2023, 1, 1)),
        ("M-02", 70.0, datetime(2023, 6, 1)),
        ("M-03", 80.0, datetime(2024, 3, 1)),
        ("M-04", 40.0, datetime(2025, 5, 10)),
        ("M-05", 130.0, datetime(2025, 5, 5)),
        ("M-06", 86.0, datetime(2025, 5, 25)),
        ("M-07", 88.0, datetime(2025, 5, 20)),
        ("M-08", 90.0, datetime(2025, 5, 15)),
        ("M-09", 96.0, datetime(2025, 4, 30)),
    ]
    for no, rate, opened_at in rows:
        _seed_result(
            session,
            no=no,
            institution="폴백기관",
            category="Servc",
            rate=rate,
            opened_at=opened_at,
        )


# ---------------------------------------------------------------------------
# (a) 기본값 경로 불변
# ---------------------------------------------------------------------------


def test_default_path_matches_explicit_current_definition(memory_session):
    """인자를 주지 않은 결과와 명시적 current 결과가 완전히 같아야 합니다."""
    _seed_result(
        memory_session,
        no="C-01",
        institution="폴백기관",
        category="Servc",
        rate=87.0,
        opened_at=REFERENCE_DATE - pd.Timedelta(days=30),
    )
    for idx, rate in enumerate([88.0, 89.0, 90.0, 91.0], start=2):
        _seed_result(
            memory_session,
            no=f"C-{idx:02d}",
            institution="폴백기관",
            category="Servc",
            rate=rate,
            opened_at=REFERENCE_DATE - pd.Timedelta(days=40 + idx),
        )

    payload = _fallback_payload()
    default_stats = lookup_institution_stats(payload, memory_session)
    current_stats = lookup_institution_stats(payload, memory_session, fallback_definition="current")

    assert default_stats == current_stats
    assert default_stats["inst_hist_rate"] == pytest.approx(0.89)
    assert default_stats["inst_ewm_rate"] == pytest.approx(0.89)
    assert default_stats["inst_sample_cnt"] == 0.0
    assert lookup_institution_sample_count(payload, memory_session) == 0.0


def test_cached_stats_row_is_shared_by_both_definitions(memory_session):
    """집계 표에 있는 기관은 폴백 정의와 무관하게 표 값을 씁니다."""
    memory_session.add(
        InstitutionWinRateStat(
            institution_name="표기관",
            category="Servc",
            sample_count=12,
            avg_rate=87.5,
            ewm_rate=88.0,
            rebuilt_at=utcnow(),
        )
    )
    memory_session.commit()

    payload = _fallback_payload("표기관")
    current = lookup_institution_stats(payload, memory_session)
    training = lookup_institution_stats(payload, memory_session, fallback_definition="training")

    assert current == training
    assert training == {
        "inst_hist_rate": pytest.approx(0.875),
        "inst_sample_cnt": 12.0,
        "inst_ewm_rate": pytest.approx(0.88),
    }


def test_unknown_fallback_definition_is_rejected(memory_session):
    with pytest.raises(ValueError, match="fallback_definition"):
        lookup_institution_stats(_fallback_payload(), memory_session, fallback_definition="학습")


def test_missing_session_keeps_category_default_for_training_definition():
    stats = lookup_institution_stats({"category": "Servc"}, None, fallback_definition="training")
    assert stats == {
        "inst_hist_rate": 0.9011,
        "inst_sample_cnt": 0.0,
        "inst_ewm_rate": 0.9011,
    }


# ---------------------------------------------------------------------------
# (b) training 정의
# ---------------------------------------------------------------------------


def test_training_definition_uses_full_history_and_real_sample_count(memory_session):
    """365일 창 밖 이력과 50~120 경계값을 학습 정의대로 반영해야 합니다."""
    _seed_mixed_history(memory_session)
    payload = _fallback_payload()

    current = lookup_institution_stats(payload, memory_session)
    training = lookup_institution_stats(payload, memory_session, fallback_definition="training")

    # 서빙: 365일 창 안에서 0<rate<100 → 40, 86, 88, 90, 96 평균 80.0, 표본 수는 0.
    assert current["inst_hist_rate"] == pytest.approx(0.80)
    assert current["inst_sample_cnt"] == 0.0
    # 학습: 전 이력에서 50~120 → 60, 70, 80, 86, 88, 90, 96 평균 570/7, 표본 7.
    assert training["inst_hist_rate"] == pytest.approx(570.0 / 7.0 / 100.0)
    assert training["inst_sample_cnt"] == 7.0


def test_training_definition_ewm_matches_streaming_halflife(memory_session):
    _seed_mixed_history(memory_session)
    expected = 0.0
    denominator = 0.0
    decay = 0.5 ** (1.0 / EWM_HALFLIFE)
    # 개찰일 오름차순: 60, 70, 80, 96, 90, 88, 86 (40 과 130 은 이상치로 제외).
    for rate in (60.0, 70.0, 80.0, 96.0, 90.0, 88.0, 86.0):
        expected = rate + decay * expected
        denominator = 1.0 + decay * denominator
    expected_ratio = expected / denominator / 100.0

    _, _, ewm_rate = calculate_institution_win_rate_training_parity(
        memory_session, "폴백기관", REFERENCE_DATE, "Servc"
    )

    assert ewm_rate == pytest.approx(expected_ratio)


def test_training_definition_under_min_samples_keeps_actual_count(memory_session):
    """표본 미달이면 낙찰률은 기본값, 표본 수는 실제 개수를 돌려줘야 합니다."""
    for idx in range(HISTORY_MIN_SAMPLES - 2):
        _seed_result(
            memory_session,
            no=f"S-{idx:02d}",
            institution="소표본기관",
            category="Servc",
            rate=80.0 + idx,
            opened_at=datetime(2023, 1, 1 + idx),
        )

    stats = lookup_institution_stats(
        _fallback_payload("소표본기관"), memory_session, fallback_definition="training"
    )

    assert stats["inst_hist_rate"] == pytest.approx(0.9011)
    assert stats["inst_ewm_rate"] == pytest.approx(0.9011)
    assert stats["inst_sample_cnt"] == float(HISTORY_MIN_SAMPLES - 2)


def test_training_definition_scopes_history_to_category(memory_session):
    """학습 데이터셋이 카테고리별이므로 다른 업무구분 이력은 빼야 합니다."""
    for idx, rate in enumerate([80.0, 82.0, 84.0, 86.0, 88.0], start=1):
        _seed_result(
            memory_session,
            no=f"P-{idx:02d}",
            institution="혼합기관",
            category="Servc",
            rate=rate,
            opened_at=datetime(2024, 1, idx),
        )
    _seed_result(
        memory_session,
        no="P-99",
        institution="혼합기관",
        category="Thng",
        rate=120.0,
        opened_at=datetime(2024, 2, 1),
    )

    stats = lookup_institution_stats(
        _fallback_payload("혼합기관"), memory_session, fallback_definition="training"
    )

    assert stats["inst_sample_cnt"] == 5.0
    assert stats["inst_hist_rate"] == pytest.approx(0.84)


def test_lookup_wrappers_forward_training_definition(memory_session):
    _seed_mixed_history(memory_session)
    payload = _fallback_payload()

    assert lookup_institution_history(
        payload, memory_session, fallback_definition="training"
    ) == pytest.approx(570.0 / 7.0 / 100.0)
    assert (
        lookup_institution_sample_count(payload, memory_session, fallback_definition="training")
        == 7.0
    )


# ---------------------------------------------------------------------------
# (c) 측정 스크립트의 선별·짝짓기 함수
# ---------------------------------------------------------------------------


def test_is_fallback_target_requires_exact_institution_and_category():
    stats_keys = {("표기관", "Servc")}

    assert is_fallback_target("신규기관", "Servc", stats_keys) is True
    assert is_fallback_target("표기관", "Servc", stats_keys) is False
    # 같은 기관이라도 업무구분이 다르면 서빙은 그 (기관, 업무구분) 키를 못 찾습니다.
    assert is_fallback_target("표기관", "Thng", stats_keys) is True


def test_select_fallback_targets_keeps_only_missing_keys():
    frame = pd.DataFrame(
        [
            {"bid_id": 1, "dminstt_nm": "신규기관", "category": "Servc"},
            {"bid_id": 2, "dminstt_nm": "표기관", "category": "Servc"},
            {"bid_id": 3, "dminstt_nm": "표기관", "category": "Thng"},
        ]
    )

    selected = select_fallback_targets(frame, {("표기관", "Servc")})

    assert selected["bid_id"].tolist() == [1, 3]


def _arm(pred: float, interval: tuple[float | None, float | None]) -> dict:
    low, high = interval
    return {
        "pred": pred,
        "model_id": "v25",
        "low": low,
        "high": high,
        "coverage": 0.9 if low is not None else None,
    }


def _record(
    bid_id: int,
    actual: float,
    current_pred: float,
    training_pred: float,
    current_interval: tuple[float | None, float | None],
    training_interval: tuple[float | None, float | None],
    current_rate: float,
    training_rate: float,
    current_count: float = 0.0,
    training_count: float = 6.0,
) -> dict:
    return {
        "bid_id": bid_id,
        "actual": actual,
        "current": _arm(current_pred, current_interval),
        "training": _arm(training_pred, training_interval),
        "current_rate": current_rate,
        "training_rate": training_rate,
        "current_count": current_count,
        "training_count": training_count,
    }


def test_summarize_pairs_reports_expected_numbers():
    records = [
        _record(1, 80.0, 82.0, 81.0, (78.0, 86.0), (79.0, 84.0), 0.90, 0.88),
        _record(2, 75.0, 70.0, 76.0, (None, None), (None, None), 0.85, 0.80),
        _record(3, 120.0, 110.0, 115.0, (100.0, 125.0), (105.0, 130.0), 0.92, 0.91),
        _record(4, 90.0, 92.0, 90.5, (85.0, 95.0), (86.0, 94.0), 0.87, 0.86),
    ]

    summary = summarize_pairs(build_paired_frame(records))

    assert summary["complete_pairs"] == 4
    assert summary["decision_pairs"] == 3
    assert summary["outside_count"] == 1

    reporting = summary["reporting"]
    assert reporting["summary"][0]["모델"] == "current(365일)"
    assert reporting["summary"][1]["모델"] == "training(전 이력)"
    assert reporting["summary"][0]["MAE"] == pytest.approx(4.75)
    assert reporting["summary"][1]["MAE"] == pytest.approx(1.875)
    assert reporting["summary"][0]["0.5%p 적중"] == pytest.approx(0.0)
    assert reporting["summary"][1]["0.5%p 적중"] == pytest.approx(0.25)
    assert reporting["summary"][0]["피복률"] == pytest.approx(0.75)
    assert reporting["summary"][1]["피복률"] == pytest.approx(0.75)

    decision = summary["decision"]
    assert decision["summary"][0]["MAE"] == pytest.approx(3.0)
    assert decision["summary"][1]["MAE"] == pytest.approx(0.8333)
    assert decision["stats"][0]["평균 차이"] == pytest.approx(-2.16667)
    assert decision["verdict"] == "challenger 우세"

    assert summary["inst_rate_mean_current"] == pytest.approx(0.885)
    assert summary["inst_rate_mean_training"] == pytest.approx(0.8625)
    assert summary["inst_rate_mean_diff"] == pytest.approx(-0.0225)
    assert summary["inst_rate_stats"]["평균 차이"] == pytest.approx(-0.0225)
    assert summary["inst_rate_stats"]["판정"] == "challenger 우세"
    assert summary["inst_count_mean_current"] == pytest.approx(0.0)
    assert summary["inst_count_mean_training"] == pytest.approx(6.0)


def test_evaluate_bid_overrides_both_definitions_and_recomputes_interactions(
    memory_session, monkeypatch
):
    """같은 공고를 두 정의로 예측하고 모델 호출 전에 특징이 실제로 갈리는지 봅니다."""
    import scripts.compare_servc_inst_fallback_paired as script

    _seed_mixed_history(memory_session)
    bid = BidAnnouncement(
        bid_ntce_no="EVAL-01",
        bid_ntce_ord="000",
        category="Servc",
        dminstt_nm="폴백기관",
        ntce_instt_nm="공고기관",
        bid_ntce_nm="용역 시험 공고",
        presmpt_prce=100_000_000,
        bid_ntce_dt=REFERENCE_DATE - pd.Timedelta(days=10),
        bid_clse_dt=REFERENCE_DATE - pd.Timedelta(days=2),
        openg_dt=REFERENCE_DATE,
        raw_data={},
        collected_at=utcnow(),
    )
    memory_session.add(bid)
    memory_session.commit()
    memory_session.refresh(bid)

    seen: list[dict] = []

    def fake_predict(model_id, features):
        seen.append(dict(features))
        rate = 0.80 if len(seen) == 1 else 0.82
        return SimpleNamespace(predicted_rate=rate, actual_model="v25")

    monkeypatch.setattr(script, "predict_optimal_price_with_provenance", fake_predict)
    monkeypatch.setattr(script, "predict_interval", lambda model_id, features: (79.0, 85.0, 0.9))

    record = script.evaluate_bid(memory_session, bid, 80.0, "v25")

    assert record is not None
    assert record["current_rate"] == pytest.approx(0.80)
    assert record["training_rate"] == pytest.approx(570.0 / 7.0 / 100.0)
    assert record["current_count"] == 0.0
    assert record["training_count"] == 7.0

    assert len(seen) == 2
    assert seen[0]["inst_hist_rate"] == pytest.approx(0.80)
    assert seen[0]["inst_sample_cnt"] == 0.0
    assert seen[1]["inst_hist_rate"] == pytest.approx(570.0 / 7.0 / 100.0)
    assert seen[1]["inst_sample_cnt"] == 7.0
    for features in seen:
        expected_interaction = features["inst_hist_rate"] * features["sem_10"]
        assert features["inst_inter_sem_10"] == pytest.approx(expected_interaction)

    # 낙찰률은 비율로 돌려오므로 레코드에서 퍼센트로 맞춥니다.
    assert record["current"]["pred"] == pytest.approx(80.0)
    assert record["training"]["pred"] == pytest.approx(82.0)
    assert record["current"]["low"] == pytest.approx(79.0)
    assert record["training"]["high"] == pytest.approx(85.0)
