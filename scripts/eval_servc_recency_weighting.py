#!/usr/bin/env python3
"""
용역 모델에 최근 구간 표본 가중을 주면 나아지는지 홀드아웃에서 잽니다.

가설의 출처는 잔차 진단입니다
([`docs/design/servc_lwlt_residual_diagnosis_20260806.md`](../docs/design/servc_lwlt_residual_diagnosis_20260806.md)).
낙찰방법(`sucsfbid_mthd_nm`)은 학습 표본 917,629행의 90.8% 에서 '공고서참조'
한 값뿐이고 2025년부터만 실제 값이 관측됩니다. 그런데 관측되는 구간에서는
낙찰방법에 따라 MAE 가 0.47 부터 4.50 까지 벌어집니다. 신호가 강한 특징을
최근 15만 행에서만 배운 셈이라, 최근 구간에 가중을 주면 이 특징을 더 쓰게
되어 나아질 수 있습니다.

**반대 방향의 위험도 같이 잽니다.** 가중을 주면 과거 구간이 사실상 얇아져
기관 이력·재발주 이력처럼 오래 쌓아야 하는 특징이 손해를 볼 수 있습니다.
그래서 전체뿐 아니라 하한율 보유/결측 집단과 기관 이력 표본 수 구간을 함께
봅니다.

승격하지 않습니다. 레지스트리에도 쓰지 않습니다. 운영 경로 쌍대 검정은
별도이며(`compare_servc_models_paired.py`), 이 스크립트가 홀드아웃에서
방향을 못 만들면 거기까지 갈 이유가 없습니다.

사용법:
    .venv/bin/python scripts/eval_servc_recency_weighting.py
    .venv/bin/python scripts/eval_servc_recency_weighting.py --half-lives 365 730
"""

from __future__ import annotations

import argparse
import sys
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
    BASE_PARAMS,
    CATEGORY,
    INNER_VALID_RATIO,
    SAMPLE_BANDS,
    build_full_frame,
    report,
)
from src.ml.trainer import hyperparams_for_category, training_features_for_category  # noqa: E402

# 쌍대 판정 임계값. compare_servc_models_paired.py 와 같은 값을 씁니다.
T_THRESHOLD = 2.0


def fit_weighted(
    df_feat: pd.DataFrame,
    y: np.ndarray,
    valid_year: int,
    half_life_days: float | None,
) -> pd.DataFrame:
    """평가 연도 직전까지 학습합니다. half_life_days 가 None 이면 균등 가중입니다.

    가중치는 학습 구간의 **마지막 개찰일**을 기준으로 한 지수감쇠입니다. 평가
    연도를 기준으로 삼으면 평가 구간 정보가 가중치에 스며듭니다.
    """
    feature_columns = training_features_for_category(CATEGORY)
    params = {**BASE_PARAMS, **hyperparams_for_category(CATEGORY).get("lightgbm", {})}

    is_train = df_feat["year"] < valid_year
    is_valid = df_feat["year"] == valid_year
    train = df_feat[is_train]
    valid = df_feat[is_valid].copy()
    y_train = y[is_train.to_numpy()]
    y_valid = y[is_valid.to_numpy()]

    if half_life_days is None:
        weights = np.ones(len(train), dtype=float)
    else:
        anchor = train["openg_dt"].max()
        age_days = (anchor - train["openg_dt"]).dt.total_seconds().to_numpy() / 86400.0
        weights = np.power(0.5, age_days / float(half_life_days))

    cut = int(len(train) * (1.0 - INNER_VALID_RATIO))
    X = train[feature_columns]
    model = lgb.LGBMRegressor(**params)
    model.fit(
        X.iloc[:cut],
        y_train[:cut],
        sample_weight=weights[:cut],
        eval_set=[(X.iloc[cut:], y_train[cut:])],
        eval_sample_weight=[weights[cut:]],
        categorical_feature=[c for c in feature_columns if str(X[c].dtype) == "category"],
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )

    valid["actual"] = y_valid
    valid["pred"] = model.predict(valid[feature_columns])
    valid["err"] = valid["pred"] - valid["actual"]
    valid["abs_err"] = valid["err"].abs()
    return valid


def score_rows(valid: pd.DataFrame, label: str) -> list[dict]:
    """전체와 하한율 집단별 요약입니다."""
    rows = []
    for name, part in [("전체", valid), *list(valid.groupby("lwlt_group", observed=True))]:
        rows.append(
            {
                "후보": label,
                "모집단": str(name),
                "건수": len(part),
                "MAE": round(float(part["abs_err"].mean()), 4),
                "RMSE": round(float(np.sqrt((part["err"] ** 2).mean())), 4),
                "편향": round(float(part["err"].mean()), 4),
                "0.5%p 적중": round(float((part["abs_err"] <= 0.5).mean()), 4),
            }
        )
    return rows


def paired_stats(diff: np.ndarray, label: str) -> dict:
    """diff = 후보 - 기준선. 음수면 후보가 낫습니다.

    최소 감지 차이를 함께 냅니다. 관측 차이가 이보다 작으면 이 표본으로는
    방향을 말할 수 없다는 뜻입니다.
    """
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
    """같은 공고의 절대오차를 직접 뺍니다. 요약값 비교는 네 번 뒤집혔습니다."""
    rows = [paired_stats((cand["abs_err"] - base["abs_err"]).to_numpy(), "전체")]
    for name in ("보유", "결측"):
        mask = (base["lwlt_group"] == name).to_numpy()
        rows.append(
            paired_stats(
                (cand["abs_err"].to_numpy()[mask] - base["abs_err"].to_numpy()[mask]), name
            )
        )
    for label, low, high in SAMPLE_BANDS:
        cnt = base["inst_sample_cnt"].to_numpy()
        mask = (cnt >= low) & (cnt < high)
        if mask.sum() < 200:
            continue
        rows.append(
            paired_stats(
                (cand["abs_err"].to_numpy()[mask] - base["abs_err"].to_numpy()[mask]),
                f"기관 이력 {label}",
            )
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--valid-year", type=int, default=2026)
    parser.add_argument(
        "--half-lives",
        type=float,
        nargs="+",
        default=[365.0, 730.0],
        help="지수감쇠 반감기(일). 작을수록 최근 구간에 몰립니다",
    )
    parser.add_argument("--chunk-rows", type=int, default=100_000)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df_feat, y = build_full_frame(path, args.chunk_rows)
    train_rows = int((df_feat["year"] < args.valid_year).sum())
    report(
        "0. 설계",
        f"학습 ~{args.valid_year - 1}년 {train_rows:,}행 / 평가 {args.valid_year}년 "
        f"{int((df_feat['year'] == args.valid_year).sum()):,}행\n"
        f"반감기 후보 {args.half_lives} 일 / 기준선은 균등 가중\n"
        "학습 상한과 하이퍼파라미터는 후보와 기준선이 동일합니다",
    )

    base = fit_weighted(df_feat, y, args.valid_year, None)
    summary = score_rows(base, "기준선(균등)")
    candidates: dict[float, pd.DataFrame] = {}
    for half_life in args.half_lives:
        cand = fit_weighted(df_feat, y, args.valid_year, half_life)
        candidates[half_life] = cand
        summary.extend(score_rows(cand, f"반감기 {int(half_life)}일"))

    report(f"1. {args.valid_year}년 out-of-sample 요약", pd.DataFrame(summary))

    for half_life, cand in candidates.items():
        report(
            f"2-{int(half_life)}. 반감기 {int(half_life)}일 쌍대 비교 (후보 - 기준선)",
            paired_table(base, cand),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
