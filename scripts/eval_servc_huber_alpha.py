#!/usr/bin/env python3
"""
용역 모델의 손실함수를 바꿔 봅니다. Huber alpha 탐색과 quantile 대조입니다.

`servc_hyperparam_search_20260804.md` 의 좌표 하강 17회는 `num_leaves`,
`min_child_samples`, `learning_rate`, `n_estimators`, `colsample_bytree`,
`subsample`, `reg_lambda` 를 다뤘습니다. **손실함수는 축에 없었습니다.**
`trainer._train_lightgbm` 은 `objective="huber", alpha=1.0` 으로 고정돼 있고
한 번도 재본 적이 없습니다.

이 축이 중요한 이유가 있습니다. Huber 는 잔차가 alpha 보다 작으면 L2(평균
겨냥), 크면 L1(중앙값 겨냥)으로 동작합니다. 현재 alpha 는 1.0 인데 운영
실측에서 오차가 0.5%p 이내인 건이 64% 입니다. **핵심 지표가 걸린 구간이 통째로
평균 겨냥으로 학습되고 있습니다.**

전날·당일 진단에서 세 번 만난 "모델이 조건부 중앙값을 겨냥해 평균 편향이
남는다" 는 현상도 이 손잡이가 정하는 동작입니다.

quantile(alpha=0.5)는 MAE 를 직접 최적화합니다. Huber 는 그 근사이므로 함께
겨룹니다.

승격하지 않습니다. 레지스트리에도 쓰지 않습니다. 홀드아웃에서 방향이 나오면
`compare_servc_models_paired.py` 로 운영 경로 쌍대 검정을 따로 거쳐야 합니다.

사용법:
    .venv/bin/python scripts/eval_servc_huber_alpha.py
    .venv/bin/python scripts/eval_servc_huber_alpha.py --alphas 0.5 1.0 --no-quantile
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

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.diagnose_servc_lwlt_residuals import (  # noqa: E402
    CATEGORY,
    INNER_VALID_RATIO,
    build_full_frame,
    report,
)
from src.ml.trainer import (  # noqa: E402
    LGB_BASE_PARAMS,
    hyperparams_for_category,
    training_features_for_category,
)

# 현행 서빙 설정입니다. 이것이 기준선입니다.
BASELINE_ALPHA = 1.0

# 쌍대 판정 임계값. compare_servc_models_paired.py 와 같은 값을 씁니다.
T_THRESHOLD = 2.0


def fit_objective(
    df_feat: pd.DataFrame,
    y: np.ndarray,
    valid_year: int,
    objective: str,
    alpha: float,
) -> tuple[pd.DataFrame, float]:
    """평가 연도 직전까지 학습해 그 해를 예측합니다. 손실함수만 바꿉니다."""
    feature_columns = training_features_for_category(CATEGORY)
    params = {
        **LGB_BASE_PARAMS,
        **hyperparams_for_category(CATEGORY).get("lightgbm", {}),
        "objective": objective,
        "alpha": alpha,
    }

    is_train = df_feat["year"] < valid_year
    is_valid = df_feat["year"] == valid_year
    train = df_feat[is_train]
    valid = df_feat[is_valid].copy()
    y_train = y[is_train.to_numpy()]

    cut = int(len(train) * (1.0 - INNER_VALID_RATIO))
    X = train[feature_columns]
    started = time.perf_counter()
    model = lgb.LGBMRegressor(**params)
    model.fit(
        X.iloc[:cut],
        y_train[:cut],
        eval_set=[(X.iloc[cut:], y_train[cut:])],
        categorical_feature=[c for c in feature_columns if str(X[c].dtype) == "category"],
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    elapsed = time.perf_counter() - started

    valid["actual"] = y[is_valid.to_numpy()]
    valid["pred"] = model.predict(valid[feature_columns])
    valid["err"] = valid["pred"] - valid["actual"]
    valid["abs_err"] = valid["err"].abs()
    return valid, elapsed


def summarize(valid: pd.DataFrame, label: str, elapsed: float) -> dict:
    err = valid["err"].to_numpy(dtype=float)
    return {
        "후보": label,
        "MAE": round(float(valid["abs_err"].mean()), 4),
        "RMSE": round(float(np.sqrt((err**2).mean())), 4),
        "편향": round(float(err.mean()), 4),
        "0.5%p 적중": round(float((valid["abs_err"] <= 0.5).mean()), 4),
        "1%p 적중": round(float((valid["abs_err"] <= 1.0).mean()), 4),
        "3%p 적중": round(float((valid["abs_err"] <= 3.0).mean()), 4),
        "학습 초": round(elapsed, 1),
    }


def paired_stats(diff: np.ndarray, label: str) -> dict:
    """diff = 후보 - 기준선. 음수면 후보가 낫습니다."""
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0
    if abs(t) < T_THRESHOLD:
        verdict = "판별 불가"
    elif mean < 0:
        verdict = "후보 우세"
    else:
        verdict = "기준선 우세"
    return {
        "모집단": label,
        "건수": n,
        "평균 차이": round(mean, 5),
        "표준오차": round(se, 5),
        "t": round(t, 2),
        "최소 감지 차이": round(T_THRESHOLD * se, 5),
        "판정": verdict,
    }


def paired_table(base: pd.DataFrame, cand: pd.DataFrame) -> pd.DataFrame:
    """같은 공고의 절대오차를 직접 뺍니다.

    전체만 보면 집단별 악화를 숨기고, 집단만 보면 전체 방향을 잃습니다.
    당일 진단에서 확인한 축(하한율·용역구분·이력 깊이)을 함께 냅니다.
    """
    b, c = base["abs_err"].to_numpy(), cand["abs_err"].to_numpy()
    rows = [paired_stats(c - b, "전체")]

    for name in ("보유", "결측"):
        mask = (base["lwlt_group"] == name).to_numpy()
        rows.append(paired_stats(c[mask] - b[mask], f"하한율 {name}"))

    for name in base["srvce_div_nm"].dropna().unique():
        mask = (base["srvce_div_nm"] == name).to_numpy()
        if mask.sum() < 500:
            continue
        rows.append(paired_stats(c[mask] - b[mask], f"{name}"))

    shallow = (base["inst_sample_cnt"] < 50).to_numpy()
    rows.append(paired_stats(c[shallow] - b[shallow], "기관 이력 얕음(<50)"))
    rows.append(paired_stats(c[~shallow] - b[~shallow], "기관 이력 두꺼움(>=50)"))
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--valid-year", type=int, default=2026)
    parser.add_argument(
        "--alphas",
        type=float,
        nargs="+",
        default=[0.2, 0.5, 1.0, 2.0, 5.0],
        help="Huber alpha 후보. 1.0 이 현행 기준선입니다",
    )
    parser.add_argument(
        "--no-quantile",
        action="store_true",
        help="quantile(0.5) 대조를 빼고 Huber 축만 봅니다",
    )
    parser.add_argument("--chunk-rows", type=int, default=100_000)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    if BASELINE_ALPHA not in args.alphas:
        print(f"기준선 alpha {BASELINE_ALPHA} 를 후보에 포함해야 비교가 됩니다.")
        return 1

    df_feat, y = build_full_frame(path, args.chunk_rows)
    report(
        "0. 설계",
        f"학습 ~{args.valid_year - 1}년 {int((df_feat['year'] < args.valid_year).sum()):,}행 / "
        f"평가 {args.valid_year}년 {int((df_feat['year'] == args.valid_year).sum()):,}행\n"
        f"Huber alpha 후보 {args.alphas} (기준선 {BASELINE_ALPHA})\n"
        f"{'quantile(0.5) 대조 포함' if not args.no_quantile else 'Huber 축만'}\n"
        "손실함수 외 하이퍼파라미터와 학습 상한은 전부 동일합니다",
    )

    results: dict[str, pd.DataFrame] = {}
    rows = []
    for alpha in args.alphas:
        label = f"huber a={alpha:g}" + (" (기준선)" if alpha == BASELINE_ALPHA else "")
        valid, elapsed = fit_objective(df_feat, y, args.valid_year, "huber", alpha)
        results[label] = valid
        rows.append(summarize(valid, label, elapsed))
    if not args.no_quantile:
        label = "quantile a=0.5"
        valid, elapsed = fit_objective(df_feat, y, args.valid_year, "quantile", 0.5)
        results[label] = valid
        rows.append(summarize(valid, label, elapsed))

    report(f"1. {args.valid_year}년 out-of-sample 요약", pd.DataFrame(rows))

    base_label = f"huber a={BASELINE_ALPHA:g} (기준선)"
    base = results[base_label]
    for label, cand in results.items():
        if label == base_label:
            continue
        report(f"2. 쌍대 비교: {label} - 기준선", paired_table(base, cand))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
