"""
tests/test_drift_verdict_rules.py

PSI 드리프트 판정 규칙(제외 특징, 정족수, 지속성) 검증 테스트.
- 달력 4종과 is_post_regime_shift 는 PSI 를 계산하되 판정에서 제외
- 제외 후 비제외 드리프트 특징이 정족수(2개) 이상일 때만 창 드리프트
- 정족수 미만이면 STABLE + below_quorum
- 직전 겹치지 않는 창이 창 드리프트일 때만 DRIFT_DETECTED, 아니면 DRIFT_PENDING
- DRIFT_PENDING 에서는 알림을 보내지 않음
- 여섯 계약(제외 상수, 정족수, 지속성, 기존 동작 하위 호환)을 단위로 고정
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from src.app.core.config import settings
from src.app.models.predictions import RetrainLog
from src.ml.monitoring import (
    DRIFT_FEATURE_QUORUM,
    DRIFT_PERSISTENCE_WINDOWS,
    DRIFT_VERDICT_EXCLUDED_FEATURES,
    apply_drift_persistence,
    check_dataset_drift,
    save_baseline_distributions,
)
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks.scheduled_tasks import _previous_window_drift, drift_monitor_task


def _constant_frame(values: dict[str, float], n: int = 200) -> pd.DataFrame:
    return pd.DataFrame({name: [value] * n for name, value in values.items()})


def _grouped_frame(
    price: float,
    inst_rate: float,
    month_sin: float,
    n: int = 100,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "log_price": [price] * (2 * n),
            "inst_hist_rate": [inst_rate] * (2 * n),
            "month_sin": [month_sin] * (2 * n),
            "lwlt_rate_missing": [0.0] * n + [1.0] * n,
        }
    )


def _drift() -> dict:
    return {
        "status": "DRIFT_DETECTED",
        "overall_action": "TRIGGER_RETRAIN",
        "drift_features": [{"feature": "log_price", "psi": 0.5, "sample_size": 200}],
        "by_subgroup": {"0.0": {"status": "DRIFT_DETECTED"}},
        "drift_subgroup_type": "with_lwlt_only",
    }


def test_excluded_features_default_constants():
    """제외 특징 상수와 정족수, 지속성 창 수가 확정값으로 고정됩니다."""
    assert (
        frozenset(
            {
                "month_sin",
                "month_cos",
                "weekday_sin",
                "weekday_cos",
                "is_post_regime_shift",
            }
        )
        == DRIFT_VERDICT_EXCLUDED_FEATURES
    )
    assert DRIFT_FEATURE_QUORUM == 2
    assert DRIFT_PERSISTENCE_WINDOWS == 2


def test_calendar_and_regime_only_drift_is_stable(tmp_path):
    """달력·레짐 특징만 드리프트하면 STABLE 이고 excluded_drift_features 에 실립니다."""
    baseline_frame = _constant_frame(
        {"log_price": 10.0, "month_sin": -0.9, "is_post_regime_shift": 0.0}
    )
    recent_frame = _constant_frame(
        {"log_price": 10.0, "month_sin": 0.9, "is_post_regime_shift": 1.0}
    )
    baseline = save_baseline_distributions(
        df_feat=baseline_frame,
        feature_columns=["log_price", "month_sin", "is_post_regime_shift"],
        target_dir=tmp_path / "baseline",
        model_name="servc_model",
        model_version="v_001",
    )

    result = check_dataset_drift(baseline, recent_frame)

    assert result["status"] == "STABLE"
    assert result["overall_action"] == "STABLE"
    assert result["drift_feature_count"] == 0
    assert result["drift_features"] == []
    assert result["below_quorum"] is False
    assert result["quorum"] == DRIFT_FEATURE_QUORUM
    assert "is_post_regime_shift" in result["excluded_features"]

    excluded_names = {feat["feature"] for feat in result["excluded_drift_features"]}
    assert {"month_sin", "is_post_regime_shift"} <= excluded_names
    assert result["drift_results"]["month_sin"]["drift_detected"] is True
    assert result["drift_results"]["month_sin"]["excluded_from_verdict"] is True
    assert result["drift_results"]["log_price"]["drift_detected"] is False
    assert "excluded_from_verdict" not in result["drift_results"]["log_price"]


def test_single_non_excluded_drift_is_stable_below_quorum(tmp_path):
    """비제외 특징 1개만 드리프트하면 STABLE 이고 below_quorum True 입니다."""
    baseline_frame = _constant_frame({"log_price": 10.0, "inst_hist_rate": 1.0})
    recent_frame = _constant_frame({"log_price": 25.0, "inst_hist_rate": 1.0})
    baseline = save_baseline_distributions(
        df_feat=baseline_frame,
        feature_columns=["log_price", "inst_hist_rate"],
        target_dir=tmp_path / "baseline",
        model_name="servc_model",
        model_version="v_001",
    )

    result = check_dataset_drift(baseline, recent_frame)

    assert result["status"] == "STABLE"
    assert result["overall_action"] == "STABLE"
    assert result["below_quorum"] is True
    assert result["drift_feature_count"] == 1
    assert result["drift_features"][0]["feature"] == "log_price"


def test_quorum_reached_is_drift_detected(tmp_path):
    """비제외 특징이 정족수 2개 이상일 때만 DRIFT_DETECTED / TRIGGER_RETRAIN 입니다."""
    baseline_frame = _constant_frame({"log_price": 10.0, "inst_hist_rate": 1.0})
    recent_frame = _constant_frame({"log_price": 25.0, "inst_hist_rate": -5.0})
    baseline = save_baseline_distributions(
        df_feat=baseline_frame,
        feature_columns=["log_price", "inst_hist_rate"],
        target_dir=tmp_path / "baseline",
        model_name="servc_model",
        model_version="v_001",
    )

    result = check_dataset_drift(baseline, recent_frame)

    assert result["status"] == "DRIFT_DETECTED"
    assert result["overall_action"] == "TRIGGER_RETRAIN"
    assert result["below_quorum"] is False
    assert result["drift_feature_count"] == 2
    assert {feat["feature"] for feat in result["drift_features"]} == {
        "log_price",
        "inst_hist_rate",
    }


def test_subgroup_path_applies_same_rules(tmp_path):
    """두 집단 경로에서도 제외·정족수 규칙이 집단마다 같게 적용됩니다."""
    baseline_frame = _grouped_frame(10.0, 1.0, -0.9)
    baseline = save_baseline_distributions(
        df_feat=baseline_frame,
        feature_columns=["log_price", "inst_hist_rate", "month_sin", "lwlt_rate_missing"],
        target_dir=tmp_path / "baseline",
        model_name="servc_model",
        model_version="v_001",
    )
    assert "by_lwlt_missing" in baseline

    # 1) 제외 특징만 드리프트
    excluded_only = _grouped_frame(10.0, 1.0, 0.9)
    res_excluded = check_dataset_drift(baseline, excluded_only)
    assert res_excluded["status"] == "STABLE"
    sub_0 = res_excluded["by_subgroup"]["0.0"]
    assert sub_0["status"] == "STABLE"
    assert sub_0["below_quorum"] is False
    assert {feat["feature"] for feat in sub_0["excluded_drift_features"]} == {"month_sin"}
    combined_excluded = {
        (feat["feature"], feat["subgroup_key"]) for feat in res_excluded["excluded_drift_features"]
    }
    assert combined_excluded == {("month_sin", "0.0"), ("month_sin", "1.0")}

    # 2) 비제외 특징 1개만 드리프트
    one_drift = _grouped_frame(25.0, 1.0, -0.9)
    res_one = check_dataset_drift(baseline, one_drift)
    assert res_one["status"] == "STABLE"
    assert res_one["by_subgroup"]["0.0"]["below_quorum"] is True
    assert res_one["by_subgroup"]["1.0"]["below_quorum"] is True

    # 3) 비제외 특징 2개 드리프트
    two_drift = _grouped_frame(25.0, -5.0, -0.9)
    res_two = check_dataset_drift(baseline, two_drift)
    assert res_two["status"] == "DRIFT_DETECTED"
    assert res_two["drift_subgroup_type"] == "both"
    assert res_two["by_subgroup"]["0.0"]["status"] == "DRIFT_DETECTED"
    assert res_two["by_subgroup"]["1.0"]["status"] == "DRIFT_DETECTED"


def test_legacy_arguments_restore_previous_behavior(tmp_path):
    """excluded_features=() 와 quorum=1 을 주면 규칙 도입 이전 동작이 됩니다."""
    baseline_frame = _constant_frame(
        {"log_price": 10.0, "month_sin": -0.9, "is_post_regime_shift": 0.0}
    )
    recent_frame = _constant_frame(
        {"log_price": 10.0, "month_sin": 0.9, "is_post_regime_shift": 1.0}
    )
    baseline = save_baseline_distributions(
        df_feat=baseline_frame,
        feature_columns=["log_price", "month_sin", "is_post_regime_shift"],
        target_dir=tmp_path / "baseline",
        model_name="servc_model",
        model_version="v_001",
    )

    result = check_dataset_drift(baseline, recent_frame, excluded_features=(), quorum=1)

    assert result["status"] == "DRIFT_DETECTED"
    assert result["overall_action"] == "TRIGGER_RETRAIN"
    assert result["excluded_features"] == []
    assert result["quorum"] == 1
    assert result["drift_feature_count"] == 2


def test_apply_drift_persistence_confirms_on_previous_window():
    """직전 창도 창 드리프트면 DRIFT_DETECTED 를 유지하고 지속성 정보를 싣습니다."""
    result = apply_drift_persistence(_drift(), True)

    assert result["status"] == "DRIFT_DETECTED"
    assert result["overall_action"] == "TRIGGER_RETRAIN"
    assert result["window_drift"] is True
    assert result["previous_window_drift"] is True
    assert result["persistence_required_windows"] == DRIFT_PERSISTENCE_WINDOWS
    assert result["drift_features"] == [{"feature": "log_price", "psi": 0.5, "sample_size": 200}]
    assert result["drift_subgroup_type"] == "with_lwlt_only"
    assert result["by_subgroup"] == {"0.0": {"status": "DRIFT_DETECTED"}}


@pytest.mark.parametrize("previous", [False, None])
def test_apply_drift_persistence_pends_without_previous_window(previous):
    """직전 창이 창 드리프트가 아니면 DRIFT_PENDING / PENDING_PERSISTENCE 로 보류합니다."""
    result = apply_drift_persistence(_drift(), previous)

    assert result["status"] == "DRIFT_PENDING"
    assert result["overall_action"] == "PENDING_PERSISTENCE"
    assert result["window_drift"] is True
    assert result["previous_window_drift"] is previous
    assert result["drift_features"] == [{"feature": "log_price", "psi": 0.5, "sample_size": 200}]


def test_apply_drift_persistence_single_window_keeps_status():
    """required_windows=1 이면 직전 창이 없어도 상태를 그대로 둡니다."""
    result = apply_drift_persistence(_drift(), None, required_windows=1)

    assert result["status"] == "DRIFT_DETECTED"
    assert result["overall_action"] == "TRIGGER_RETRAIN"
    assert result["window_drift"] is True
    assert result["persistence_required_windows"] == 1


def test_apply_drift_persistence_stable_verdict_and_invalid_windows():
    """창 드리프트가 아닌 판정은 그대로 두고, 지원하지 않는 창 수는 ValueError 입니다."""
    stable = apply_drift_persistence({"status": "STABLE", "overall_action": "STABLE"}, None)
    assert stable["status"] == "STABLE"
    assert stable["window_drift"] is False

    with pytest.raises(ValueError):
        apply_drift_persistence(_drift(), True, required_windows=3)


def test_apply_drift_persistence_does_not_mutate_input():
    """입력 판정 dict 를 제자리에서 바꾸지 않습니다."""
    verdict = _drift()
    apply_drift_persistence(verdict, None)

    assert "window_drift" not in verdict
    assert verdict["status"] == "DRIFT_DETECTED"


def _add_log(
    db,
    created_at: datetime,
    metrics_summary: dict,
    *,
    trigger_source: str = "drift_monitor",
    champion_version: str = "servc_model",
) -> None:
    db.add(
        RetrainLog(
            trigger_source=trigger_source,
            champion_version=champion_version,
            challenger_version="-",
            status="STABLE",
            metrics_summary=metrics_summary,
            created_at=created_at,
        )
    )
    db.commit()


def test_previous_window_drift_window_boundaries(isolated_db, monkeypatch):
    """겹치지 않는 직전 창만 읽고, 경계 포함·키 부재·비 bool 은 None 입니다."""
    factory = sessionmaker(bind=isolated_db.get_bind(), autocommit=False, autoflush=False)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", factory)

    now = datetime(2026, 9, 28, 12, 0, 0)
    # 구간: 2026-09-14 00:00:00 <= created_at <= 2026-09-22 00:00:00

    assert _previous_window_drift("m_none", now, 7) is None

    _add_log(isolated_db, datetime(2026, 9, 18), {"psi": 0.1}, champion_version="m_nokey")
    assert _previous_window_drift("m_nokey", now, 7) is None

    _add_log(
        isolated_db,
        datetime(2026, 9, 18),
        {"window_drift": "yes"},
        champion_version="m_nonbool",
    )
    assert _previous_window_drift("m_nonbool", now, 7) is None

    _add_log(
        isolated_db,
        datetime(2026, 9, 25),
        {"window_drift": True},
        champion_version="m_overlap",
    )
    assert _previous_window_drift("m_overlap", now, 7) is None

    _add_log(
        isolated_db,
        datetime(2026, 9, 10),
        {"window_drift": True},
        champion_version="m_old",
    )
    assert _previous_window_drift("m_old", now, 7) is None

    _add_log(
        isolated_db,
        datetime(2026, 9, 16),
        {"window_drift": True},
        champion_version="m_recent",
    )
    _add_log(
        isolated_db,
        datetime(2026, 9, 20),
        {"window_drift": False},
        champion_version="m_recent",
    )
    assert _previous_window_drift("m_recent", now, 7) is False

    _add_log(
        isolated_db,
        datetime(2026, 9, 22, 0, 0, 0),
        {"window_drift": True},
        champion_version="m_end",
    )
    assert _previous_window_drift("m_end", now, 7) is True

    _add_log(
        isolated_db,
        datetime(2026, 9, 14, 0, 0, 0),
        {"window_drift": True},
        champion_version="m_start",
    )
    assert _previous_window_drift("m_start", now, 7) is True

    _add_log(
        isolated_db,
        datetime(2026, 9, 18),
        {"window_drift": True},
        trigger_source="weekly_schedule",
        champion_version="other_model",
    )
    assert _previous_window_drift("other_model", now, 7) is None


def test_previous_window_drift_returns_none_on_query_failure(monkeypatch, caplog):
    """조회 중 예외가 나면 경고를 남기고 None(fail-safe)을 돌려줍니다."""

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

        def close(self) -> None:
            pass

    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", _BrokenSession)

    with caplog.at_level("WARNING"):
        result = _previous_window_drift("servc_model", datetime(2026, 9, 28, 12, 0, 0), 7)

    assert result is None
    assert any("직전 창" in record.message for record in caplog.records)


def _write_baselines(tmp_path: Path, n_samples: int = 150) -> None:
    df_train = pd.DataFrame(
        {
            "log_price": [10.0] * n_samples,
            "srvce_div_nm": ["일반용역"] * n_samples,
        }
    )
    for _category, model_name in CATEGORY_MODEL_NAMES.items():
        save_baseline_distributions(
            df_feat=df_train,
            feature_columns=["log_price", "srvce_div_nm"],
            target_dir=tmp_path / model_name / "baseline",
            model_name=model_name,
            model_version="v_20260928_001",
        )


def _drifted_frame(n_samples: int = 150) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "presumed_price": 100_000_000.0,
                "base_price": 99_000_000.0,
                "winning_rate": 88.0,
                "openg_dt": "2026-09-01",
                "srvce_div_nm": "기술용역",
                "log_price": 25.0,
            }
            for _ in range(n_samples)
        ]
    )


@pytest.mark.asyncio
async def test_run_drift_monitor_pending_does_not_notify(isolated_db, tmp_path, monkeypatch):
    """이번 창만 드리프트면 DRIFT_PENDING 으로 기록하고 알림을 보내지 않습니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)
    _write_baselines(tmp_path)
    monkeypatch.setattr(
        "src.tasks.scheduled_tasks.build_training_dataset",
        lambda db, category_code, **kwargs: _drifted_frame(),
    )
    monkeypatch.setattr("src.tasks.scheduled_tasks._previous_window_drift", lambda *a, **k: None)

    mock_notify = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.notify_drift_detected", mock_notify)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    servc = outcome["categories"]["Servc"]
    assert servc["status"] == "DRIFT_PENDING"
    assert servc["window_drift"] is True
    assert mock_notify.await_count == 0

    logs = isolated_db.query(RetrainLog).filter(RetrainLog.trigger_source == "drift_monitor").all()
    assert len(logs) == len(CATEGORY_MODEL_NAMES)
    assert all(log_item.status == "DRIFT_PENDING" for log_item in logs)
    assert all(log_item.metrics_summary["window_drift"] is True for log_item in logs)


@pytest.mark.asyncio
async def test_run_drift_monitor_notifies_only_on_confirmed_drift(
    isolated_db, tmp_path, monkeypatch
):
    """직전 창도 창 드리프트면 DRIFT_DETECTED 로 확정하고 알림을 보냅니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)
    _write_baselines(tmp_path)
    monkeypatch.setattr(
        "src.tasks.scheduled_tasks.build_training_dataset",
        lambda db, category_code, **kwargs: _drifted_frame(),
    )
    monkeypatch.setattr("src.tasks.scheduled_tasks._previous_window_drift", lambda *a, **k: True)

    mock_notify = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.notify_drift_detected", mock_notify)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    servc = outcome["categories"]["Servc"]
    assert servc["status"] == "DRIFT_DETECTED"
    assert servc["window_drift"] is True

    servc_notify_calls = [
        call
        for call in mock_notify.await_args_list
        if call.kwargs.get("model_name") == CATEGORY_MODEL_NAMES["Servc"]
    ]
    assert len(servc_notify_calls) == 1

    logs = isolated_db.query(RetrainLog).filter(RetrainLog.trigger_source == "drift_monitor").all()
    assert all(log_item.status == "DRIFT_DETECTED" for log_item in logs)


@pytest.mark.asyncio
async def test_run_drift_monitor_skips_previous_lookup_when_stable(
    isolated_db, tmp_path, monkeypatch
):
    """창 드리프트가 아니면 직전 창 조회를 하지 않습니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)
    _write_baselines(tmp_path)

    stable_frame = pd.DataFrame(
        [
            {
                "presumed_price": 100_000_000.0,
                "base_price": 99_000_000.0,
                "winning_rate": 88.0,
                "openg_dt": "2026-09-01",
                "srvce_div_nm": "일반용역",
                "log_price": 10.0,
            }
            for _ in range(150)
        ]
    )
    monkeypatch.setattr(
        "src.tasks.scheduled_tasks.build_training_dataset",
        lambda db, category_code, **kwargs: stable_frame,
    )

    def _must_not_lookup(*args, **kwargs):
        raise AssertionError("창 드리프트가 아니면 직전 창 조회를 하면 안 됩니다")

    monkeypatch.setattr("src.tasks.scheduled_tasks._previous_window_drift", _must_not_lookup)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    assert all(result["status"] == "STABLE" for result in outcome["categories"].values())
