#!/usr/bin/env python3
"""
용역 모델의 잔차를 하한율 결측 여부·낙찰방법·기관 이력 표본 수로 분해합니다.

읽기 전용 진단입니다. 레지스트리에 아무것도 쓰지 않고 승격도 하지 않습니다.

**서빙 champion 을 그대로 재지 않는 이유가 있습니다.** champion 은 모델 선택
뒤 전량으로 재적합(`refit_on_full`)한 아티팩트라, 데이터셋 어느 행을 물어도
학습 구간입니다. 그 위에서 잰 잔차는 in-sample 낙관이 섞여 집단 간 편향
구조를 왜곡합니다. 그래서 학습 경로와 같은 특징·같은 하이퍼파라미터로
**평가 연도 직전까지만** 학습한 모델을 세우고, 그 해를 out-of-sample 로 잽니다.

특징은 `src/ml/features.py` 단일 공급원만 씁니다. 기관 이력과 재발주 이력은
`attach_*` 가 기준 시점 이전만 보도록 shift(1) 로 만들어져 있으므로, 전량
프레임에 한 번 붙인 뒤 연도로 잘라도 미래 정보가 새지 않습니다.

낙찰률 하한 절단은 하지 않습니다. 운영 추론 경로(`src/ml/predictor.py`)가
절단하지 않으므로, 절단하면 서빙과 다른 잔차를 재게 됩니다.

**낙찰방법(`sucsfbid_mthd_nm`)은 2025년부터만 관측됩니다.** 2015~2024년은 전량이
'공고서참조' 한 값입니다. 수집 결함이 아니라 G2B API 가 과거 공고에 실제
낙찰방법을 주지 않는 것으로, 2015년 행도 2026-03~08 에 같은 API 로 다시
수집했는데 같은 값이 나옵니다. 그래서 낙찰방법별 편향의 연도 안정성은
2025년과 2026년 두 해로만 판정할 수 있습니다.

사용법:
    .venv/bin/python scripts/diagnose_servc_lwlt_residuals.py
    .venv/bin/python scripts/diagnose_servc_lwlt_residuals.py --years 2024 2025
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

from src.ml.features import (  # noqa: E402
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    LGB_BASE_PARAMS,
    hyperparams_for_category,
    training_features_for_category,
)

CATEGORY = "Servc"

# 학습 경로(_train_lightgbm)와 같은 목적함수입니다. 여기서 어긋나면 진단이
# 운영과 다른 모델의 잔차를 보게 됩니다.
BASE_PARAMS = {**LGB_BASE_PARAMS, "objective": "huber", "alpha": 1.0}

# 조기 종료용 내부 검증 구간. 학습 구간의 뒤쪽에서 뗍니다. 평가 연도를
# 조기 종료에 쓰면 그 해 성능이 낙관 쪽으로 새므로 쓰지 않습니다.
INNER_VALID_RATIO = 0.1

# 기관 이력 표본 수 구간. 모델이 이력값을 얼마나 믿을지 가르는 축입니다.
SAMPLE_BANDS = [
    ("0건", 0, 1),
    ("1~9건", 1, 10),
    ("10~49건", 10, 50),
    ("50~199건", 50, 200),
    ("200건 이상", 200, np.inf),
]

# 표가 읽히려면 집단이 충분히 커야 합니다. 이보다 작으면 평균 편향의
# 표준오차가 편향 자체보다 커서 방향을 말할 수 없습니다.
MIN_GROUP_ROWS = 200


def build_full_frame(parquet_path: Path, chunk_rows: int) -> tuple[pd.DataFrame, np.ndarray]:
    """전량 프레임에 이력을 붙이고 단일 공급원으로 특징을 만듭니다.

    `build_feature_frame` 은 행마다 dict 를 만들어 90여 키를 담습니다. 91만 행을
    한 번에 펼치면 필요 없는 컬럼까지 메모리에 올라오므로, 덩어리로 나눠
    학습 특징만 남기고 버립니다.
    """
    df_raw = pd.read_parquet(parquet_path)
    df_raw = df_raw[df_raw["winning_rate"].notna()].copy()
    df_raw["openg_dt"] = pd.to_datetime(df_raw["openg_dt"], errors="coerce")
    df_raw = df_raw[df_raw["openg_dt"].notna()]
    df_raw = df_raw.sort_values("openg_dt").reset_index(drop=True)

    df_raw = attach_institution_history(df_raw)
    df_raw = attach_repeat_history(df_raw)

    feature_columns = training_features_for_category(CATEGORY)
    records = df_raw.to_dict(orient="records")

    parts = []
    for start in range(0, len(records), chunk_rows):
        chunk = pd.DataFrame(build_feature_frame(records[start : start + chunk_rows]))
        parts.append(chunk[feature_columns])
    df_feat = pd.concat(parts, ignore_index=True)

    # 범주 수준은 학습 경로와 같이 전량에서 확정합니다. 목표값이 아닌 범주의
    # 존재 여부만 담으므로 시간 분할의 의미를 해치지 않습니다.
    df_feat = apply_categorical_dtypes(df_feat, collect_category_levels(df_feat))

    # 진단 축입니다. 학습 특징이 아니므로 feature_columns 에는 넣지 않습니다.
    df_feat["openg_dt"] = df_raw["openg_dt"].to_numpy()
    df_feat["year"] = df_raw["openg_dt"].dt.year.to_numpy()
    df_feat["sucsfbid_mthd_raw"] = df_raw["sucsfbid_mthd_nm"].fillna("미상").astype(str).to_numpy()
    df_feat["lwlt_group"] = np.where(df_feat["lwlt_rate_missing"] == 1, "결측", "보유")

    return df_feat, df_raw["winning_rate"].to_numpy(dtype=float)


def fit_until(df_feat: pd.DataFrame, y: np.ndarray, valid_year: int) -> pd.DataFrame:
    """평가 연도 직전까지 학습해 그 해를 예측합니다."""
    feature_columns = training_features_for_category(CATEGORY)
    params = {**BASE_PARAMS, **hyperparams_for_category(CATEGORY).get("lightgbm", {})}

    is_train = df_feat["year"] < valid_year
    is_valid = df_feat["year"] == valid_year
    train = df_feat[is_train]
    valid = df_feat[is_valid].copy()
    y_train = y[is_train.to_numpy()]
    y_valid = y[is_valid.to_numpy()]

    cut = int(len(train) * (1.0 - INNER_VALID_RATIO))
    X = train[feature_columns]
    model = lgb.LGBMRegressor(**params)
    model.fit(
        X.iloc[:cut],
        y_train[:cut],
        eval_set=[(X.iloc[cut:], y_train[cut:])],
        categorical_feature=[c for c in feature_columns if str(X[c].dtype) == "category"],
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )

    valid["actual"] = y_valid
    valid["pred"] = model.predict(valid[feature_columns])
    valid["err"] = valid["pred"] - valid["actual"]
    valid["abs_err"] = valid["err"].abs()
    return valid


def summarize(part: pd.DataFrame) -> dict[str, float]:
    """집단 하나의 편향과 오차입니다.

    편향에는 표준오차와 t 를 붙입니다. 평균만 보면 표본이 작은 집단의 잡음을
    구조로 착각합니다.
    """
    err = part["err"].to_numpy(dtype=float)
    n = len(err)
    bias = float(err.mean())
    se = float(err.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {
        "건수": n,
        "편향": round(bias, 4),
        "편향 표준오차": round(se, 4),
        "t": round(bias / se, 2) if se and np.isfinite(se) and se > 0 else float("nan"),
        "MAE": round(float(part["abs_err"].mean()), 4),
        "RMSE": round(float(np.sqrt((err**2).mean())), 4),
        "0.5%p 적중": round(float((part["abs_err"] <= 0.5).mean()), 4),
        "실제 표준편차": round(float(part["actual"].std()), 3),
    }


def group_table(valid: pd.DataFrame, key: str, min_rows: int = MIN_GROUP_ROWS) -> pd.DataFrame:
    rows = []
    for name, part in valid.groupby(key, observed=True):
        if len(part) < min_rows:
            continue
        rows.append({key: str(name), **summarize(part)})
    return pd.DataFrame(rows).sort_values("건수", ascending=False)


def sample_band_table(valid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, low, high in SAMPLE_BANDS:
        cnt = valid["inst_sample_cnt"]
        part = valid[(cnt >= low) & (cnt < high)]
        if len(part) < MIN_GROUP_ROWS:
            continue
        rows.append({"기관 이력 표본": label, **summarize(part)})
    return pd.DataFrame(rows)


def method_table(valid: pd.DataFrame, lwlt_group: str) -> pd.DataFrame:
    part = valid[valid["lwlt_group"] == lwlt_group]
    if part.empty:
        return pd.DataFrame()
    return group_table(part, "sucsfbid_mthd_raw")


def stability_table(by_year: dict[int, pd.DataFrame], key: str) -> pd.DataFrame:
    """연도별 편향을 나란히 놓고 부호가 유지되는지 봅니다.

    방향이 해마다 뒤집히면 그것은 구조가 아니라 그 해의 사정입니다.
    인수인계 3.4 의 중단 기준 첫 항목이 이 표로 판정됩니다.
    """
    frames = []
    for year, valid in by_year.items():
        table = group_table(valid, key)
        if table.empty:
            continue
        # 기본 인자로 연도를 묶습니다. 람다가 루프 변수를 참조하면 모든 표가
        # 마지막 연도 이름을 갖게 됩니다.
        frames.append(
            table.set_index(key)[["편향", "건수"]].rename(columns=lambda c, y=year: f"{y} {c}")
        )
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, axis=1)
    bias_columns = [c for c in merged.columns if c.endswith("편향")]
    signs = np.sign(merged[bias_columns].to_numpy(dtype=float))
    observed = np.isfinite(signs).sum(axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        consistent = np.nanmin(signs, axis=1) == np.nanmax(signs, axis=1)
    merged["관측 연도"] = observed
    # 한 해에만 나타난 집단은 부호가 유지된 것이 아니라 비교된 적이 없습니다.
    merged["부호 유지"] = np.where(observed < 2, "판정 불가", np.where(consistent, "예", "아니오"))
    return merged.reset_index()


def offset_counterfactual(by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """편향을 빼면 오차가 줄어드는지 봅니다.

    평균 편향이 남아 있다는 사실만으로는 고칠 것이 있다는 뜻이 아닙니다. 학습
    손실이 Huber(alpha=1.0)라 모델은 조건부 중앙값 쪽을 겨냥하는데, 낙찰률
    분포가 비대칭이면 중앙값 예측에는 평균 편향이 **정상적으로** 남습니다.
    그 편향을 빼면 예측이 중앙값에서 밀려나 MAE 가 오히려 나빠질 수 있습니다.

    그래서 두 가지를 함께 냅니다.

      직전 연도 오프셋  운영에서 실제로 쓸 수 있는 값. 작년 편향을 올해에 적용
      오라클 오프셋      올해 편향을 올해에 적용. 이 방식이 낼 수 있는 상한

    상한조차 이득이 없으면 오프셋 계열은 더 볼 필요가 없습니다.
    """
    rows = []
    years = sorted(by_year)
    for idx, year in enumerate(years):
        valid = by_year[year]
        prior = by_year[years[idx - 1]] if idx > 0 else None
        for group, part in valid.groupby("lwlt_group", observed=True):
            base = float(part["abs_err"].mean())
            oracle = float((part["err"] - part["err"].mean()).abs().mean())
            row = {
                "연도": year,
                "하한율": str(group),
                "건수": len(part),
                "현행 MAE": round(base, 4),
                "오라클 오프셋 MAE": round(oracle, 4),
                "오라클 개선": round(base - oracle, 4),
            }
            if prior is not None:
                prior_part = prior[prior["lwlt_group"] == group]
                shift = float(prior_part["err"].mean()) if len(prior_part) else 0.0
                lagged = float((part["err"] - shift).abs().mean())
                row["직전 연도 오프셋"] = round(shift, 4)
                row["직전 오프셋 MAE"] = round(lagged, 4)
                row["직전 오프셋 개선"] = round(base - lagged, 4)
            rows.append(row)
    return pd.DataFrame(rows)


def skew_table(by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """실제 낙찰률의 비대칭도입니다.

    평균과 중앙값이 벌어져 있으면 중앙값을 겨냥한 예측에 평균 편향이 남는 것이
    당연합니다. 편향을 결함으로 읽기 전에 이 표를 먼저 봐야 합니다.
    """
    rows = []
    for year, valid in sorted(by_year.items()):
        for group, part in valid.groupby("lwlt_group", observed=True):
            actual = part["actual"]
            rows.append(
                {
                    "연도": year,
                    "하한율": str(group),
                    "건수": len(part),
                    "실제 평균": round(float(actual.mean()), 4),
                    "실제 중앙값": round(float(actual.median()), 4),
                    "평균-중앙값": round(float(actual.mean() - actual.median()), 4),
                    "왜도": round(float(actual.skew()), 3),
                    "예측 평균": round(float(part["pred"].mean()), 4),
                    "예측 중앙값": round(float(part["pred"].median()), 4),
                }
            )
    return pd.DataFrame(rows)


def report(title: str, frame: pd.DataFrame | str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    if isinstance(frame, str):
        print(frame)
    elif frame.empty:
        print("표본이 부족해 표를 만들지 않았습니다.")
    else:
        print(frame.to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=[2023, 2024, 2025, 2026],
        help="평가 연도. 각 연도 직전까지만 학습합니다",
    )
    parser.add_argument("--chunk-rows", type=int, default=100_000)
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="연도별 잔차 프레임을 parquet 으로 남깁니다. 후속 분석에서 재학습을 피합니다",
    )
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df_feat, y = build_full_frame(path, args.chunk_rows)
    report(
        "0. 진단 대상",
        f"전량 {len(df_feat):,}행 "
        f"({df_feat['openg_dt'].min():%Y-%m-%d} ~ {df_feat['openg_dt'].max():%Y-%m-%d})\n"
        f"하한율 결측 {int((df_feat['lwlt_group'] == '결측').sum()):,}행 "
        f"({(df_feat['lwlt_group'] == '결측').mean():.1%})\n"
        f"평가 연도 {args.years} / 학습은 각 연도 직전까지",
    )

    by_year: dict[int, pd.DataFrame] = {}
    for year in args.years:
        if not (df_feat["year"] == year).any():
            print(f"{year}년 표본이 없어 건너뜁니다.")
            continue
        valid = fit_until(df_feat, y, year)
        by_year[year] = valid
        if args.dump_dir:
            dump_dir = Path(args.dump_dir)
            dump_dir.mkdir(parents=True, exist_ok=True)
            # 컬럼을 골라 남기지 않습니다. 한 번 돌리는 데 35분이 걸리는데, 나중에
            # 필요한 축이 빠져 있으면 그 35분을 다시 써야 합니다. 연도당 10만 행에
            # 40여 컬럼이라 통째로 남겨도 parquet 이 작습니다.
            valid.to_parquet(dump_dir / f"servc_residuals_{year}.parquet", index=False)
        report(
            f"1-{year}. {year}년 out-of-sample 전체 (학습 ~{year - 1}년, {len(valid):,}건)",
            pd.DataFrame([summarize(valid)]),
        )
        report(f"2-{year}. 하한율 보유 여부별", group_table(valid, "lwlt_group"))
        report(f"3-{year}. 하한율 결측 집단의 낙찰방법별", method_table(valid, "결측"))
        report(f"4-{year}. 하한율 보유 집단의 낙찰방법별", method_table(valid, "보유"))
        report(f"5-{year}. 기관 이력 표본 수 구간별", sample_band_table(valid))

    if len(by_year) > 1:
        report("6. 하한율 집단별 편향의 연도 안정성", stability_table(by_year, "lwlt_group"))
        report("7. 낙찰방법별 편향의 연도 안정성", stability_table(by_year, "sucsfbid_mthd_raw"))

    report("8. 실제 낙찰률의 비대칭도", skew_table(by_year))
    report("9. 편향 오프셋 반사실 검정", offset_counterfactual(by_year))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
