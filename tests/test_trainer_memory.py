"""
tests/test_trainer_memory.py

재학습 최대 메모리 축소 회귀 테스트.

고정하는 것:
1. 선택되지 않은 후보 모델과 폴드 모델은 학습이 끝나는 대로 반납된다
   (전량 재적합이 시작되는 시점에 후보 모델 객체가 남아 있으면 결함).
2. 청크로 나눠 만든 특징 프레임과 범주 수준은 전체를 한 번에 만든 것과 같다.
3. 정답 컬럼이 없어도 학습이 성공한다 (y 폴백은 df_raw 행 수 기준).
"""

from __future__ import annotations

import gc
import weakref
from datetime import datetime, timedelta

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.ml.features import (
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.trainer import (
    ModelTrainer,
    _build_feature_frame_chunked,
    _collect_category_levels_chunked,
)


def _frame(rows: int = 240) -> pd.DataFrame:
    base = datetime(2024, 1, 1, 9, 0, 0)
    return pd.DataFrame(
        {
            "presmpt_prce": [100_000_000 + i * 7_000 for i in range(rows)],
            "base_amount": [95_000_000 + i * 7_000 for i in range(rows)],
            "category": ["Servc"] * rows,
            "winning_rate": [85.0 + (i % 12) for i in range(rows)],
            "openg_dt": [base + timedelta(days=i) for i in range(rows)],
            "dminstt_nm": [f"기관{i % 5}" for i in range(rows)],
            "bid_ntce_nm": [f"용역 {i % 40}" for i in range(rows)],
        }
    )


def test_candidate_and_fold_models_are_released_before_refit(tmp_path, monkeypatch):
    """전량 재적합이 시작될 때 후보·폴드 모델 객체가 이미 반납돼 있어야 합니다.

    candidates 에 후보 모델을 끝까지 보관하면 재적합과 분위 학습이 진행되는
    동안 선택되지 않은 후보까지 모두 메모리에 남아 최대 메모리가 불어납니다.
    재적합에는 조기 종료가 고른 트리 수만 필요하므로 객체는 학습 직후 반납합니다.
    """
    import src.ml.trainer as trainer_module

    tracked: list[weakref.ref] = []
    trainers_to_wrap = (
        "_train_ridge_cv",
        "_train_lightgbm",
        "_train_catboost",
    )
    originals = {name: getattr(trainer_module, name) for name in trainers_to_wrap}

    def make_spy(name: str, original):
        def wrapped(*args, **kwargs):
            model = original(*args, **kwargs)
            tracked.append(weakref.ref(model))
            return model

        return wrapped

    for name in trainers_to_wrap:
        monkeypatch.setattr(trainer_module, name, make_spy(name, originals[name]))

    release_state: dict[str, bool | None] = {"released_at_refit": None}
    original_refit = trainer_module._refit_on_full

    def spy_refit(*args, **kwargs):
        gc.collect()
        release_state["released_at_refit"] = all(ref() is None for ref in tracked)
        return original_refit(*args, **kwargs)

    monkeypatch.setattr(trainer_module, "_refit_on_full", spy_refit)

    metadata = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(_frame())

    # 트리 후보와 폴드 학습이 실제로 돌아 스파이가 의미 있게 동작했는지 확인합니다.
    assert len(tracked) >= 3
    assert release_state["released_at_refit"] is True

    # 반납은 지표 수집을 바꾸지 않아야 합니다.
    assert set(metadata["candidate_cv_metrics"]) == {"ridge", "lightgbm", "catboost"}
    assert set(metadata["candidate_holdout_metrics"]) == {"ridge", "lightgbm", "catboost"}
    assert metadata["model_type"] in {"ridge", "lightgbm", "catboost"}
    assert metadata["metrics"]["rmse"] > 0.0

    # 학습 종료 후에도 어떤 학습 모델도 참조에 걸려 있으면 안 됩니다.
    gc.collect()
    assert all(ref() is None for ref in tracked)


def test_chunked_feature_frame_matches_batch(tmp_path, monkeypatch):
    """청크로 나눠 만든 특징 프레임은 전체를 한 번에 만든 것과 같아야 합니다.

    특징 구축을 청크로 나눠도 결과가 달라지면 모델 지표가 바뀝니다. dtype 과
    값이 정확히 일치하는지 비교합니다. FEATURE_CHUNK_ROWS 를 줄여 여러 청크에
    걸치는 경계까지 검사합니다.
    """
    import src.ml.trainer as trainer_module

    monkeypatch.setattr(trainer_module, "FEATURE_CHUNK_ROWS", 40)

    df_raw = _frame(rows=150)

    records = df_raw.to_dict(orient="records")
    features_list = build_feature_frame(records)
    df_feat_batch = pd.DataFrame(features_list)
    levels_batch = collect_category_levels(df_feat_batch)
    del records, features_list

    df_feat_chunked = _build_feature_frame_chunked(df_raw)
    levels_chunked = _collect_category_levels_chunked(df_feat_chunked)

    assert levels_chunked == levels_batch
    df_feat_batch = apply_categorical_dtypes(df_feat_batch, levels_batch)
    df_feat_chunked = apply_categorical_dtypes(df_feat_chunked, levels_chunked)
    assert_frame_equal(df_feat_batch, df_feat_chunked, check_exact=True, check_dtype=True)


def test_missing_target_falls_back_per_input_rows(tmp_path):
    """정답 컬럼이 없는 입력에서 폴백 정답의 행 수는 입력 행 수를 따라야 합니다.

    트리 모델이 상수 타깃을 거부하므로 표본은 홀드아웃을 뗄 수 없는 2행으로
    두고, 폴백 정답 행 수가 입력 행 수와 일치하는지만 단정합니다.
    """
    df_raw = _frame(rows=2).drop(columns=["winning_rate"])
    metadata = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(df_raw)
    assert metadata["samples_count"] == 2
    assert metadata["train_samples"] + metadata["validation_samples"] == 2


def test_empty_input_builds_empty_feature_frame(monkeypatch):
    """빈 입력은 빈 특징 프레임이 됩니다 (이전 일괄 구축과 같은 결과)."""
    monkeypatch.setattr("src.ml.trainer.FEATURE_CHUNK_ROWS", 40)
    empty = pd.DataFrame({"winning_rate": pd.Series(dtype=float)})
    chunked = _build_feature_frame_chunked(empty)
    batch = pd.DataFrame(build_feature_frame(empty.to_dict(orient="records")))
    assert chunked.empty
    assert batch.empty
    assert _collect_category_levels_chunked(empty) == collect_category_levels(empty)


@pytest.mark.parametrize("rows", [41, 199, 400])
def test_chunk_row_count_is_preserved(monkeypatch, rows):
    """청크 경계에 걸쳐도 행 수와 순서가 유지됩니다."""
    from src.ml.training_config import TRAINING_FEATURES

    monkeypatch.setattr("src.ml.trainer.FEATURE_CHUNK_ROWS", 40)
    df_raw = _frame(rows=rows)
    df_feat = _build_feature_frame_chunked(df_raw)
    assert len(df_feat) == rows
    for column in TRAINING_FEATURES:
        assert column in df_feat.columns
