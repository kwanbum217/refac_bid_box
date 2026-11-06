"""
tests/test_ml_tools_cleanup.py

2026-11-06 ML 감사 후속 정리 회귀 시험.

1. 주간 재학습·드리프트 따라잡기 태스크가 HEAVY_TASK_NAMES 에 포함된다.
2. 진단·측정 스크립트가 원본 슬롯 루트가 아니라 resolve_serving_tree 결과를 읽는다.
3. champion 조회가 전달받은 serving_dir 을 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_metadata(path: Path, payload: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_weekly_retrain_catchup_is_heavy() -> None:
    """주간 재학습 따라잡기는 원 태스크와 같은 3시간 상한을 받아야 합니다.

    드리프트 따라잡기는 의도적으로 1시간 예산을 유지합니다.
    """
    from src.tasks.worker import HEAVY_TASK_NAMES

    assert "run_weekly_retrain_catchup_task" in HEAVY_TASK_NAMES
    assert "run_drift_monitor_catchup_task" not in HEAVY_TASK_NAMES


def test_diagnose_reads_resolved_serving_tree(monkeypatch, tmp_path: Path) -> None:
    """진단 스크립트는 LIVE 세대 경로로 해석한 뒤 그 트리에서 모델을 읽습니다."""
    from scripts import diagnose_serving_vs_holdout_model as diag

    tree = tmp_path / "generations" / "v_live"
    _write_metadata(tree, {"required_features": ["a"], "category_levels": {"c": ["x"]}})

    calls: list[Path] = []

    def fake_resolve_serving_tree(slot: Path) -> Path:
        calls.append(Path(slot))
        return tree

    monkeypatch.setattr(diag, "resolve_serving_tree", fake_resolve_serving_tree)
    monkeypatch.setattr(diag.joblib, "load", lambda path: ("model", Path(path)))

    model, features, levels = diag.load_serving_model()

    assert calls == [diag.SERVING_DIR]
    assert model == ("model", tree / "model.bin")
    assert features == ["a"]
    assert levels == {"c": ["x"]}


def test_eval_conformal_reads_resolved_serving_tree(monkeypatch, tmp_path: Path) -> None:
    """구간 배율 스크립트도 슬롯 루트 직독 대신 서빙 세대를 읽습니다."""
    from scripts import eval_servc_segment_conformal as ev

    tree = tmp_path / "generations" / "v_live"
    _write_metadata(tree, {"interval": {"conformal_scale": 1.25}})

    calls: list[Path] = []

    def fake_resolve_serving_tree(slot: Path) -> Path:
        calls.append(Path(slot))
        return tree

    monkeypatch.setattr(ev, "resolve_serving_tree", fake_resolve_serving_tree)
    monkeypatch.setattr(ev.joblib, "load", lambda path: ("quantile", Path(path)))

    meta, q10, q90 = ev.load_interval_models()

    assert calls == [ev.MODEL_SLOT]
    assert meta["interval"]["conformal_scale"] == 1.25
    assert q10 == ("quantile", tree / "model_q10.bin")
    assert q90 == ("quantile", tree / "model_q90.bin")


def test_serving_metrics_uses_given_serving_dir(monkeypatch, tmp_path: Path) -> None:
    """_serving_metrics 는 전달된 serving_dir 의 슬롯을 읽습니다."""
    from src.ml import promotion
    from src.tasks import retrain_task

    serving = tmp_path / "serving"
    _write_metadata(serving / "m", {"version": "v_alt", "source_metrics": {"r2": 0.5}})
    monkeypatch.setattr(promotion, "METRICS_ROOT", tmp_path / "metrics")

    assert retrain_task._serving_metrics("m", serving_dir=serving) == ("v_alt", {"r2": 0.5})


def test_champion_lookup_passes_serving_dir(monkeypatch, tmp_path: Path) -> None:
    """champion 조회도 대체 serving_dir 을 반영합니다."""
    from src.ml import promotion
    from src.tasks import retrain_task

    serving = tmp_path / "serving"
    _write_metadata(serving / "m", {"version": "v_alt", "source_metrics": {"r2": 0.5}})
    monkeypatch.setattr(promotion, "METRICS_ROOT", tmp_path / "metrics")

    version, metrics = retrain_task._load_champion_metrics(
        "m",
        registry_dir=str(tmp_path / "registry"),
        serving_dir=str(serving),
    )

    assert version == "v_alt"
    assert metrics == {"r2": 0.5}


@pytest.mark.parametrize("model_name", ["m"])
def test_no_metrics_still_returns_version(monkeypatch, tmp_path: Path, model_name: str) -> None:
    """서빙본은 있으나 지표가 없으면 레지스트리로 대체하지 않습니다."""
    from src.ml import promotion
    from src.tasks import retrain_task

    serving = tmp_path / "serving"
    _write_metadata(serving / model_name, {"version": "25.1"})
    monkeypatch.setattr(promotion, "METRICS_ROOT", tmp_path / "metrics")

    assert retrain_task._serving_metrics(model_name, serving_dir=serving) == ("25.1", {})
