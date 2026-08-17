"""
tests/test_trainer_split.py

src/ml/trainer.py 분할 및 심볼 재수출 검증 테스트.
trainer.py 에서 재수출하는 심볼들이 누락되거나 분할된 모듈과 어긋나면 깨지도록 구성합니다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def test_reexported_symbols_from_trainer():
    """trainer.py 에서 모든 이동된 심볼이 올바르게 재수출되는지 검증합니다.

    trainer.py 에서 재수출을 제거하면 이 테스트가 즉시 깨집니다.
    """
    import src.ml.conformal as conformal_module
    import src.ml.splitters as splitters_module
    import src.ml.trainer as trainer_module
    import src.ml.training_config as config_module

    # splitters 심볼
    splitter_symbols = [
        "TIME_SORT_COLUMN",
        "DEFAULT_VALIDATION_SPLIT",
        "DEFAULT_N_FOLDS",
        "MIN_FOLD_SAMPLES",
        "has_time_column",
        "_sorted_positions",
        "_time_based_split",
        "_time_based_kfold_splits",
    ]
    for sym in splitter_symbols:
        assert hasattr(trainer_module, sym), f"trainer.py 에 {sym} 재수출 누락"
        assert getattr(trainer_module, sym) is getattr(splitters_module, sym)

    # training_config 심볼
    config_symbols = [
        "DEFAULT_MODEL_NAME",
        "CATEGORY_MODEL_NAMES",
        "LGB_BASE_PARAMS",
        "CATEGORY_HYPERPARAMS",
        "NUMERIC_FEATURES",
        "TRAINING_FEATURES",
        "SERVC_EXTRA_FEATURES",
        "model_name_for_category",
        "training_features_for_category",
        "hyperparams_for_category",
    ]
    for sym in config_symbols:
        assert hasattr(trainer_module, sym), f"trainer.py 에 {sym} 재수출 누락"
        assert getattr(trainer_module, sym) is getattr(config_module, sym)

    # conformal 심볼
    conformal_symbols = [
        "INTERVAL_QUANTILES",
        "INTERVAL_TARGET_COVERAGE",
        "CALIBRATION_SPLIT",
        "QUANTILE_PARAM_OVERRIDES",
        "QUANTILE_HYPERPARAM_KEY",
        "_conformal_scale",
        "_train_quantile_models",
    ]
    for sym in conformal_symbols:
        assert hasattr(trainer_module, sym), f"trainer.py 에 {sym} 재수출 누락"
        assert getattr(trainer_module, sym) is getattr(conformal_module, sym)

    # trainer 고유 심볼
    assert hasattr(trainer_module, "ModelTrainer")
    assert hasattr(trainer_module, "trainer")


def test_splitters_functionality():
    """splitters 모듈 및 trainer 재수출 함수의 동작을 검증합니다."""
    from src.ml.trainer import (
        TIME_SORT_COLUMN,
        _sorted_positions,
        _time_based_kfold_splits,
        _time_based_split,
        has_time_column,
    )

    df = pd.DataFrame({
        TIME_SORT_COLUMN: ["2024-03-01", "2024-01-01", "2024-02-01"],
        "val": [30, 10, 20],
    })
    assert has_time_column(df) is True

    df_no_time = pd.DataFrame({"val": [1, 2, 3]})
    assert has_time_column(df_no_time) is False

    sorted_pos = _sorted_positions(df)
    np.testing.assert_array_equal(sorted_pos, np.array([1, 2, 0]))

    # _time_based_split
    y = np.array([300.0, 100.0, 200.0])
    train_idx, valid_idx, _y_train, _y_valid = _time_based_split(df, y, validation_split=0.34)
    # 정렬 순서: 1(1월), 2(2월), 0(3월) -> split_at: int(3 * 0.66) = 1
    assert len(train_idx) == 1
    assert len(valid_idx) == 2
    assert train_idx[0] == 1

    # _time_based_kfold_splits
    df_large = pd.DataFrame({
        TIME_SORT_COLUMN: [f"2024-{i:02d}-01" for i in range(1, 11)],
        "val": list(range(10)),
    })
    splits = _time_based_kfold_splits(df_large, n_folds=3)
    assert len(splits) > 0
    for train_idx, valid_idx in splits:
        assert len(train_idx) >= 2
        assert len(valid_idx) >= 2


def test_training_config_functionality():
    """training_config 모듈 및 trainer 재수출 설정/함수의 동작을 검증합니다."""
    from src.ml.trainer import (
        DEFAULT_MODEL_NAME,
        SERVC_EXTRA_FEATURES,
        TRAINING_FEATURES,
        hyperparams_for_category,
        model_name_for_category,
        training_features_for_category,
    )

    assert model_name_for_category(None) == DEFAULT_MODEL_NAME
    assert model_name_for_category("") == DEFAULT_MODEL_NAME
    assert model_name_for_category("Thng") == "quantum_leap_v25_pro"
    assert model_name_for_category("Servc") == "servc_institution_v1"
    assert model_name_for_category("Cnstwk") == "cnstwk_institution_v1"

    with pytest.raises(ValueError):
        model_name_for_category("UnknownCategory")

    servc_feats = training_features_for_category("Servc")
    assert "inst_ewm_rate" in servc_feats
    assert len(servc_feats) == len(TRAINING_FEATURES) + len(SERVC_EXTRA_FEATURES)

    thng_feats = training_features_for_category("Thng")
    assert "inst_ewm_rate" not in thng_feats
    assert len(thng_feats) == len(TRAINING_FEATURES)

    servc_params = hyperparams_for_category("Servc")
    assert "lightgbm" in servc_params
    assert servc_params["lightgbm"]["num_leaves"] == 255


def test_conformal_functionality():
    """conformal 모듈 및 trainer 재수출 함수의 동작을 검증합니다."""
    from src.ml.trainer import (
        CALIBRATION_SPLIT,
        INTERVAL_QUANTILES,
        INTERVAL_TARGET_COVERAGE,
        QUANTILE_HYPERPARAM_KEY,
        QUANTILE_PARAM_OVERRIDES,
        _conformal_scale,
    )

    assert INTERVAL_QUANTILES == (0.1, 0.9)
    assert INTERVAL_TARGET_COVERAGE == 0.90
    assert CALIBRATION_SPLIT == 0.15
    assert QUANTILE_PARAM_OVERRIDES == {"num_leaves": 63}
    assert QUANTILE_HYPERPARAM_KEY == "lightgbm_quantile"

    y_cal = np.array([88.0, 88.5, 87.5])
    lo_cal = np.array([87.0, 87.0, 87.0])
    hi_cal = np.array([89.0, 89.0, 89.0])
    scale = _conformal_scale(y_cal, lo_cal, hi_cal, 0.90)
    assert isinstance(scale, float)
    assert scale > 0


def test_line_counts():
    """각 모듈의 라인 수가 600줄 미만인지 검증합니다."""
    ml_dir = Path("src/ml")
    for filename in ["trainer.py", "splitters.py", "training_config.py", "conformal.py"]:
        file_path = ml_dir / filename
        assert file_path.exists()
        line_count = len(file_path.read_text(encoding="utf-8").splitlines())
        assert line_count < 600, f"{filename} 은 600줄 미만이어야 합니다 (현재: {line_count}줄)"


def test_ast_function_definitions():
    """분할된 모듈의 함수 정의들이 유효한 파이썬 AST 구문 트리를 갖는지 검증합니다."""
    ml_dir = Path("src/ml")
    for filename in ["trainer.py", "splitters.py", "training_config.py", "conformal.py"]:
        content = (ml_dir / filename).read_text(encoding="utf-8")
        tree = ast.parse(content, filename=filename)
        assert isinstance(tree, ast.Module)
