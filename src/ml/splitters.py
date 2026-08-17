"""
src/ml/splitters.py

시계열 교차 검증 및 홀드아웃 분할기.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 홀드아웃 비율. 학습에 쓰지 않은 구간에서 지표를 내야 의미가 있습니다.
# 시계열 데이터이므로 개찰일(rl_openg_dt / openg_dt) 기준으로 정렬한 뒤
# 뒤에서 20%를 최종 검증에 사용합니다.
DEFAULT_VALIDATION_SPLIT = 0.2

# K-Fold 폴드 수. 시간 순서를 존중하는 블록 K-Fold 를 사용합니다.
DEFAULT_N_FOLDS = 5

# 폴드 하나가 가져야 하는 최소 행 수. 트리 모델이 1행 입력에서 예외를 던집니다.
MIN_FOLD_SAMPLES = 2

# 시계열 기준 컬럼. 없으면 프레임 순서를 그대로 사용합니다.
TIME_SORT_COLUMN = "openg_dt"


def has_time_column(df: pd.DataFrame) -> bool:
    """시계열 정렬 기준 컬럼이 실재하는지 확인합니다."""
    return TIME_SORT_COLUMN in df.columns


def _sorted_positions(df: pd.DataFrame) -> np.ndarray:
    """시계열 오름차순 위치 배열을 반환합니다.

    라벨이 아니라 위치를 돌려줍니다. 호출부가 numpy 배열에 위치 색인을 쓰므로
    라벨을 섞어 쓰면 인덱스가 기본 RangeIndex 가 아닐 때 조용히 어긋납니다.

    기준 컬럼이 없거나 값이 비면 프레임 순서를 그대로 씁니다. 파싱 실패(NaT)는
    맨 앞으로 보내 학습 구간에 넣습니다. 검증 구간은 개찰일이 확실한 최신
    구간이어야 의미가 있습니다.
    """
    if not has_time_column(df):
        return np.arange(len(df))
    parsed = pd.to_datetime(df[TIME_SORT_COLUMN], errors="coerce")
    if parsed.isna().all():
        return np.arange(len(df))
    return parsed.reset_index(drop=True).sort_values(na_position="first").index.to_numpy()


def _time_based_split(
    df: pd.DataFrame,
    y: np.ndarray,
    validation_split: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """개찰일 기준으로 정렬한 뒤 뒤에서 validation_split 만큼을 검증에 사용합니다.

    표본이 적어 홀드아웃을 뗄 수 없으면 전체를 학습과 검증에 함께 씁니다.
    빈 검증 구간을 돌려주면 predict 단계에서 0행 입력으로 예외가 납니다.
    이 경우 지표는 과적합된 값이므로 승격 판단에 쓰면 안 됩니다.
    """
    sorted_order = _sorted_positions(df)

    split_at = int(len(sorted_order) * (1.0 - validation_split))
    if split_at <= 0 or split_at >= len(sorted_order):
        return sorted_order, sorted_order, y[sorted_order], y[sorted_order]

    train_idx = sorted_order[:split_at]
    valid_idx = sorted_order[split_at:]
    return train_idx, valid_idx, y[train_idx], y[valid_idx]


def _time_based_kfold_splits(
    df: pd.DataFrame,
    n_folds: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """시계열 순서를 존중하는 K-Fold 인덱스 쌍을 반환합니다.

    각 폴드는 이전 폴드들을 훈련, 현재 폴드를 검증으로 사용합니다.
    """
    sorted_order = _sorted_positions(df)

    fold_size = max(1, len(sorted_order) // n_folds)
    splits = []
    for fold_idx in range(1, n_folds):
        valid_start = fold_idx * fold_size
        valid_end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else len(sorted_order)
        train_idx = sorted_order[:valid_start]
        valid_idx = sorted_order[valid_start:valid_end]
        # 표본이 적으면 fold_size 가 1 이 되어 1행짜리 폴드가 생깁니다.
        # LightGBM/CatBoost 는 1행 입력에서 예외를 던지므로 건너뜁니다.
        if len(train_idx) < MIN_FOLD_SAMPLES or len(valid_idx) < MIN_FOLD_SAMPLES:
            continue
        splits.append((train_idx, valid_idx))
    return splits
