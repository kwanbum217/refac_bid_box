"""
tests/test_accuracy_measure_20261122.py

2026-11-22 홈 정확도 화면 계약을 데이터 쪽에서 고정합니다.

1. `compute_distribution` 의 오차 밴드 비율과 error_reduction 이 손으로
   계산한 값과 같다.
2. 구간 예측이 일부 또는 전부 실패해도 실측 적중률과 평가 건수가 맞고,
   전부 실패하면 interval 이 None 이다.
3. 산점도는 300점을 넘지 않고 seed 로 재현되며 좌표는 소수 둘째 자리다.
4. `save_serving_metrics` 는 distribution 을 넘길 때만 키를 더하고,
   넘기지 않으면 종전과 같은 파일을 쓴다.
5. `load_serving_metrics` 는 distribution 이 있어도 종전 반환값이 같다.

운영 모델·DB·네트워크에 기대지 않습니다.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.measure_serving_model import _score, compute_distribution
from src.ml import promotion

MODEL_NAME = "accuracy_measure_tester"


def test_bands_and_error_reduction_match_hand_calculation():
    predicted = np.array([100.0, 98.0, 95.0, 90.0])
    actual = np.array([100.4, 96.5, 93.5, 93.5])

    distribution = compute_distribution(predicted, actual)

    shares = {band["within_pp"]: band["share"] for band in distribution["bands"]}
    assert [band["within_pp"] for band in distribution["bands"]] == [0.5, 1.0, 2.0, 3.0]
    assert shares[0.5] == pytest.approx(0.25)
    assert shares[1.0] == pytest.approx(0.25)
    assert shares[2.0] == pytest.approx(0.75)
    assert shares[3.0] == pytest.approx(0.75)

    # SSE = 16.91, SST = 32.1075
    assert distribution["error_reduction"] == pytest.approx(1 - 16.91 / 32.1075)
    assert distribution["error_reduction"] == pytest.approx(_score(predicted, actual)["r2"])


def test_interval_coverage_counts_only_evaluated_samples():
    predicted = np.array([90.0, 90.0, 90.0])
    actual = np.array([91.0, 92.0, 105.0])

    partial = compute_distribution(
        predicted,
        actual,
        [90.0, None, 80.0],
        [95.0, None, 100.0],
        target=0.9,
    )

    assert partial["interval"] == {
        "coverage": pytest.approx(0.5),
        "evaluated": 2,
        "target": pytest.approx(0.9),
    }

    all_failed = compute_distribution(
        predicted,
        actual,
        [None, None, None],
        [None, None, None],
        target=0.9,
    )
    assert all_failed["interval"] is None


def test_interval_coverage_is_measured_not_target():
    predicted = np.array([90.0, 90.0])
    actual = np.array([90.0, 90.0])

    distribution = compute_distribution(
        predicted,
        actual,
        [89.0, 89.0],
        [91.0, 91.0],
        target=0.8,
    )

    assert distribution["interval"]["coverage"] == pytest.approx(1.0)
    assert distribution["interval"]["target"] == pytest.approx(0.8)


def test_non_finite_rows_are_dropped_consistently():
    distribution = compute_distribution(
        [90.0, float("nan"), 91.0],
        [90.5, 92.0, 91.0],
        [89.0, 90.0, None],
        [91.0, 93.0, 92.0],
        target=0.9,
    )

    assert distribution["scatter"]["points"] == [[90.0, 90.5], [91.0, 91.0]]
    assert distribution["interval"] == {
        "coverage": pytest.approx(1.0),
        "evaluated": 1,
        "target": pytest.approx(0.9),
    }


def test_scatter_is_capped_reproducible_and_rounded():
    rng = np.random.default_rng(3)
    predicted = 70 + rng.random(500) * 40
    actual = 70 + rng.random(500) * 40

    first = compute_distribution(predicted, actual, seed=11)
    again = compute_distribution(predicted, actual, seed=11)

    points = first["scatter"]["points"]
    assert len(points) == 300
    assert first["scatter"]["seed"] == 11
    assert points == again["scatter"]["points"]
    for predicted_value, actual_value in points:
        assert predicted_value == round(predicted_value, 2)
        assert actual_value == round(actual_value, 2)


def test_scatter_keeps_every_point_below_limit():
    distribution = compute_distribution([90.0, 91.0], [90.5, 92.0], seed=5)

    assert distribution["scatter"] == {"points": [[90.0, 90.5], [91.0, 92.0]], "seed": 5}


def test_save_without_distribution_keeps_previous_file_shape(tmp_path):
    metrics = {"rmse": 1.5, "mae": 1.0, "mape": 1.1, "r2": 0.5, "bias": 0.1}
    detail = {"category": "Servc", "holdout_since": "2026-01-01", "samples": 10}

    path = promotion.save_serving_metrics(
        MODEL_NAME, "v1", metrics, detail=detail, metrics_dir=tmp_path
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"model_name", "version", "metrics", "measured_at", *detail}
    assert payload["metrics"] == metrics
    assert "distribution" not in payload


def test_save_with_distribution_adds_key_and_keeps_existing_values(tmp_path):
    metrics = {"rmse": 1.5, "mae": 1.0, "mape": 1.1, "r2": 0.5, "bias": 0.1}
    distribution = compute_distribution([90.0, 91.0], [90.5, 92.0], seed=5)

    path = promotion.save_serving_metrics(
        MODEL_NAME,
        "v1",
        metrics,
        distribution=distribution,
        detail={"samples": 2},
        metrics_dir=tmp_path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["distribution"] == distribution
    assert payload["distribution"]["bands"][0]["within_pp"] == 0.5
    assert payload["metrics"] == metrics
    assert payload["version"] == "v1"
    assert payload["samples"] == 2


def test_load_serving_metrics_ignores_distribution(tmp_path):
    serving_dir = tmp_path / "serving"
    (serving_dir / MODEL_NAME).mkdir(parents=True)
    (serving_dir / MODEL_NAME / "metadata.json").write_text(
        json.dumps({"name": MODEL_NAME, "version": "v1"}), encoding="utf-8"
    )
    metrics = {"rmse": 1.5, "mae": 1.0}
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    distribution = compute_distribution([90.0, 91.0], [90.5, 92.0], seed=5)
    (metrics_dir / f"{MODEL_NAME}.json").write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "version": "v1",
                "metrics": metrics,
                "distribution": distribution,
            }
        ),
        encoding="utf-8",
    )

    version, loaded = promotion.load_serving_metrics(
        MODEL_NAME, serving_dir=serving_dir, metrics_dir=metrics_dir
    )

    assert (version, loaded) == ("v1", metrics)
