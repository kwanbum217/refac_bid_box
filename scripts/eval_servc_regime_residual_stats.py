#!/usr/bin/env python3
"""2026-05-26 레짐 구간의 잔차 분포 통계를 신·구 제도로 나누어 냅니다.

`eval_servc_regime_lwlt_levels.py` 와 **같은 절차**를 씁니다. 컷 이전만 학습하고
이후를 예측하는 역사적 out-of-sample 대리 측정이며, 서빙 champion
(`data/model_files/servc_institution_v1/model.bin`)을 직접 재는 것이 아닙니다.
champion 은 `refit_on_full` 아티팩트라 이 parquet 의 어느 행도 학습 구간이고,
그 위에서 잰 잔차는 in-sample 낙관이 섞입니다
(`diagnose_servc_lwlt_residuals.py` 의 같은 주의를 따릅니다).

기존 스크립트가 내지 않는 RMSE, 중앙 잔차, 중앙절대오차, 평균 편향 95% 신뢰
구간을 추가로 냅니다. 판정 자체는 기존 스크립트가 냈고 이 스크립트는 그 판정의
불확실성을 읽기 위한 보조입니다.

사용법:
    uv run python scripts/eval_servc_regime_residual_stats.py
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.eval_servc_regime_lwlt_levels import (  # noqa: E402
    REGIME_DATE,
    build_frame,
    classify,
    fit_operational,
)
from src.ml.trainer import TRAINING_FEATURES  # noqa: E402

# 정규 근사 95% 구간입니다. 각 집단이 수백 건 이상이라 t 분포와 차이가 없습니다.
Z_95 = 1.959964

GROUP_ORDER = ["학습 충분 수준", "2%p 인상 희소 수준", "기타 희소 수준", "하한율 결측"]


def residual_stats(error: np.ndarray, label: str) -> dict:
    """잔차 한 벌의 위치·산포·불확실성을 함께 냅니다."""
    n = int(error.size)
    mean = float(error.mean())
    # ddof=1 은 표본 표준편차입니다. n=1 이면 정의되지 않으므로 구간을 비웁니다.
    se = float(error.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    half = Z_95 * se if np.isfinite(se) else float("nan")
    return {
        "집단": label,
        "건수": n,
        "MAE": round(float(np.abs(error).mean()), 4),
        "RMSE": round(float(np.sqrt((error**2).mean())), 4),
        "평균 편향": round(mean, 4),
        "95% CI 하한": round(mean - half, 4) if np.isfinite(half) else None,
        "95% CI 상한": round(mean + half, 4) if np.isfinite(half) else None,
        "0 포함": ("예" if np.isfinite(half) and (mean - half) <= 0 <= (mean + half) else "아니오"),
        "중앙 잔차": round(float(np.median(error)), 4),
        "중앙절대오차": round(float(np.median(np.abs(error))), 4),
    }


def run_split(frame: pd.DataFrame, cut: pd.Timestamp, end: pd.Timestamp, thin: int, title: str):
    train = frame[frame["openg_dt"] < cut].copy()
    valid = frame[(frame["openg_dt"] >= cut) & (frame["openg_dt"] <= end)].copy()
    if train.empty or valid.empty:
        print(f"[{title}] 구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return None

    features = list(TRAINING_FEATURES)
    started = time.perf_counter()
    model = fit_operational(train, features)
    pred = np.asarray(model.predict(valid[features]), dtype=float)
    actual = valid["winning_rate"].to_numpy(dtype=float)
    error = pred - actual
    labels = classify(valid, train, thin)

    print(f"\n=== {title} ===")
    print(
        f"학습 {len(train):,}행 (~{cut.date()}) / 검증 {len(valid):,}행 "
        f"({cut.date()}~{end.date()}) / 학습 {time.perf_counter() - started:.1f}초"
    )

    rows = [residual_stats(error, "전체")]
    for name in GROUP_ORDER:
        mask = (labels == name).to_numpy()
        if mask.any():
            rows.append(residual_stats(error[mask], name))
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--thin", type=int, default=300, help="희소 수준 판정 임계 표본 수")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)
    print(f"학습 프레임 최신 개찰일: {frame['openg_dt'].max()}")

    cut = pd.Timestamp(REGIME_DATE)
    end = frame["openg_dt"].max()
    span = end - cut

    run_split(frame, cut, end, args.thin, f"신제도 구간 (컷 {cut.date()})")
    control_cut = cut - pd.DateOffset(years=1)
    run_split(
        frame,
        control_cut,
        control_cut + span,
        args.thin,
        f"대조군 1년 전 동기간 (컷 {control_cut.date()})",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
