#!/usr/bin/env python3
"""
공사(Cnstwk) 낙찰률 예측을 연도 경계 홀드아웃에서 비교합니다.

학습 = 개찰일(openg_dt) 기준 2025-01-01 미만
정규 홀드아웃 = 2025년 (openg_dt 기준)
OOS = 2026년 (openg_dt 기준)
  - 레짐 전: 공고일(bid_ntce_dt) < 2026-05-26
  - 레짐 후: 공고일(bid_ntce_dt) >= 2026-05-26

후보 모델: trainer.py 와 training_config.py 가 쓰는 특징/하이퍼파라미터 그대로 재사용.
기준선 v25: EnsembleV25Wrapper 의 서빙 경로(prepare_features -> v25 예측)를 재사용.

모델을 레지스트리에 등록하거나 승격하지 않는다. 학습 모델은 메모리에서만 쓴다.

사용법:
    uv run python scripts/eval_cnstwk_year_holdout.py
    uv run python scripts/eval_cnstwk_year_holdout.py --parquet <path> --output <path> --limit 5000
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.training_config import (  # noqa: E402
    LGB_BASE_PARAMS,
    hyperparams_for_category,
    training_features_for_category,
)

# 계약 1: 연도 경계
TRAIN_CUTOFF = pd.Timestamp("2025-01-01")
REGIME_SHIFT_DATE = pd.Timestamp("2026-05-26")

# 계약 4: 승격 판단 참고 기준
PROMOTION_T_THRESHOLD = 2.0
PROMOTION_MAE_IMPROVEMENT = 0.0074

# 계약 5: 기본 경로
DEFAULT_PARQUET = "data/feature_store/cnstwk_rebuild_20260915/dataset_Cnstwk.parquet"
DEFAULT_OUTPUT = "data/benchmarks/noncanonical/cnstwk_year_holdout_20260915.json"


# ---------------------------------------------------------------------------
# 특징 생성 (trainer.py 의 train_and_register 순서를 그대로 재현한다)
# ---------------------------------------------------------------------------


def build_candidate_features(
    df_raw: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, np.ndarray]:
    """후보 모델용 특징 프레임과 정답 배열을 만든다.

    trainer.train_and_register 가 쓰는 순서(기관 이력 -> 재발주 이력 ->
    build_feature_frame -> apply_categorical_dtypes)를 그대로 따른다.
    학습 구간 행만 넘겨야 홀드아웃 정보가 누수되지 않는다.
    """
    df = attach_institution_history(df_raw)
    df = attach_repeat_history(df)

    records = df.to_dict(orient="records")
    features_list = build_feature_frame(records)
    df_feat = pd.DataFrame(features_list)

    category_levels = collect_category_levels(df_feat)
    df_feat = apply_categorical_dtypes(df_feat, category_levels)

    # 시계열 정렬 기준 컬럼 복원
    if "openg_dt" in df.columns:
        df_feat["openg_dt"] = df["openg_dt"].to_numpy()

    y = df["winning_rate"].to_numpy(dtype=float)
    return df_feat[feature_columns], y, category_levels


def build_holdout_features(
    df_raw: pd.DataFrame,
    feature_columns: list[str],
    category_levels: dict[str, list[str]],
) -> tuple[pd.DataFrame, np.ndarray]:
    """홀드아웃 프레임의 특징을 만든다.

    기관 이력·재발주 이력은 이 함수가 아닌 상위에서 이미 계산된 값이
    df_raw 컬럼에 담겨 있어야 한다. build_feature_frame 이 그 값을 그대로
    꺼내 쓰므로 홀드아웃 정답이 누수되지 않는다.
    """
    records = df_raw.to_dict(orient="records")
    features_list = build_feature_frame(records)
    df_feat = pd.DataFrame(features_list)
    df_feat = apply_categorical_dtypes(df_feat, category_levels)
    y = df_raw["winning_rate"].to_numpy(dtype=float)
    return df_feat[feature_columns], y


# ---------------------------------------------------------------------------
# LightGBM 후보 모델 학습
# ---------------------------------------------------------------------------


def _train_lightgbm_candidate(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    hyperparams: dict[str, Any] | None,
) -> lgb.LGBMRegressor:
    """학습 구간 전체로 후보 모델을 적합한다.

    trainer._train_lightgbm 과 같은 기본 파라미터(huber, alpha=1.0)를 쓰고,
    Cnstwk 카테고리 전용 재정의를 얹는다. 조기 종료는 쓰지 않는다(평가 전용
    단일 모델이라 폴드 분할이 없음). n_estimators 는 설정값 그대로 사용한다.
    """
    params: dict[str, Any] = {**LGB_BASE_PARAMS, "objective": "huber", "alpha": 1.0}
    params.update(hyperparams or {})
    # 조기 종료 없이 학습
    params.pop("callbacks", None)

    cat_cols = [c for c in CATEGORICAL_FEATURES if c in X_train.columns]
    model = lgb.LGBMRegressor(**params)
    model.fit(X_train, y_train, categorical_feature=cat_cols)
    return model


# ---------------------------------------------------------------------------
# v25 예측 경로
# ---------------------------------------------------------------------------


def predict_v25_batch(
    df_raw: pd.DataFrame,
    loader: Callable[[], Any] | None = None,
) -> np.ndarray:
    """v25 wrapper 의 서빙 경로로 배치 예측을 수행한다.

    loader 는 EnsembleV25Wrapper 인스턴스를 반환하는 함수다. None 이면
    ModelRegistry 에서 "v25" 를 꺼낸다. 테스트에서 가짜 모델로 대체할 수 있도록
    함수 인자로 주입한다.
    """
    if loader is not None:
        wrapper = loader()
    else:
        from src.ml.model_registry import ModelRegistry

        wrapper = ModelRegistry.get_model("v25")
        if wrapper is None:
            raise RuntimeError(
                "v25 모델이 ModelRegistry 에 없습니다. data/model_files/v25 경로를 확인하십시오."
            )

    from src.ml.features import build_default_feature_map, prepare_input_frame

    preds: list[float] = []
    serving_columns = wrapper.get_serving_columns()
    category_levels = (
        wrapper.get_category_levels() if hasattr(wrapper, "get_category_levels") else None
    )

    for _, row in df_raw.iterrows():
        row_dict = row.to_dict()
        feature_map = build_default_feature_map(row_dict)
        if serving_columns:
            frame = prepare_input_frame(row_dict, serving_columns, defaults=feature_map)
            from src.ml.features import apply_categorical_dtypes as _apply

            frame = _apply(frame, category_levels)
        else:
            frame = pd.DataFrame([{**row_dict, **feature_map}])
        frame.attrs["feature_defaults"] = feature_map

        try:
            pred = float(wrapper.predict(frame))
        except Exception:
            pred = float("nan")
        preds.append(pred)

    return np.array(preds, dtype=float)


# ---------------------------------------------------------------------------
# 지표 계산
# ---------------------------------------------------------------------------


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _hit_rate(y_true: np.ndarray, y_pred: np.ndarray, threshold: float = 0.5) -> float:
    return float(np.mean(np.abs(y_true - y_pred) <= threshold))


def _paired_t(diff: np.ndarray) -> dict[str, float]:
    """쌍대 차이 d = |후보 오차| - |v25 오차| 의 평균, 표준오차, t 값을 반환한다."""
    d = diff[np.isfinite(diff)]
    n = len(d)
    if n == 0:
        return {"mean_diff": float("nan"), "se": float("nan"), "t": float("nan")}
    mean_d = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean_d / se if se > 0 else 0.0
    return {"mean_diff": round(mean_d, 6), "se": round(se, 6), "t": round(t, 4)}


def _segment_metrics(
    y_true: np.ndarray,
    cand_pred: np.ndarray,
    v25_pred: np.ndarray,
    label: str,
) -> dict[str, Any]:
    """한 구간의 두 모델 지표와 쌍대 검정 결과를 계산한다."""
    n = len(y_true)
    cand_abs = np.abs(y_true - cand_pred)
    v25_abs = np.abs(y_true - v25_pred)
    diff = cand_abs - v25_abs

    paired = _paired_t(diff)
    cand_mae = _mae(y_true, cand_pred)
    v25_mae = _mae(y_true, v25_pred)
    mae_improvement = v25_mae - cand_mae  # 양수면 후보가 개선

    meets_promotion = (
        abs(paired["t"]) >= PROMOTION_T_THRESHOLD and mae_improvement >= PROMOTION_MAE_IMPROVEMENT
    )

    return {
        "segment": label,
        "n": n,
        "candidate": {
            "mae": round(cand_mae, 4),
            "rmse": round(_rmse(y_true, cand_pred), 4),
            "hit_rate_0_5pct": round(_hit_rate(y_true, cand_pred, 0.5), 4),
        },
        "v25": {
            "mae": round(v25_mae, 4),
            "rmse": round(_rmse(y_true, v25_pred), 4),
            "hit_rate_0_5pct": round(_hit_rate(y_true, v25_pred, 0.5), 4),
        },
        "paired": paired,
        "mae_improvement": round(mae_improvement, 6),
        "meets_promotion_criteria": meets_promotion,
    }


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def _git_commit() -> str:
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="공사(Cnstwk) 후보 모델 vs v25 연도 경계 홀드아웃 평가"
    )
    parser.add_argument(
        "--parquet",
        default=DEFAULT_PARQUET,
        help=f"학습 데이터 parquet 경로 (기본: {DEFAULT_PARQUET})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"결과 JSON 저장 경로 (기본: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="학습·평가 행 상한 (0=전체, 시험용)",
    )
    parser.add_argument(
        "--v25-loader",
        default=None,
        help="내부 옵션: v25 로더 모듈.함수 경로 (기본: ModelRegistry 사용)",
    )
    args = parser.parse_args(argv)

    parquet_path = PROJECT_ROOT / args.parquet
    output_path = PROJECT_ROOT / args.output

    if not parquet_path.exists():
        print(f"데이터셋이 없습니다: {parquet_path}")
        return 1

    t0 = time.perf_counter()
    print(f"데이터 로드: {parquet_path}")
    df_all = pd.read_parquet(parquet_path)

    # winning_rate 범위 필터 (capsule: 70~110 으로 정제됨)
    df_all = df_all[df_all["winning_rate"].notna()].copy()

    # 날짜 파싱
    for col in ("openg_dt", "bid_ntce_dt", "bid_clse_dt"):
        if col in df_all.columns:
            df_all[col] = pd.to_datetime(df_all[col], errors="coerce")

    if args.limit > 0:
        df_all = df_all.iloc[: args.limit].copy()

    # 계약 1: 분할
    openg = df_all["openg_dt"]
    mask_train = openg < TRAIN_CUTOFF
    mask_2025 = (openg >= TRAIN_CUTOFF) & (openg < pd.Timestamp("2026-01-01"))
    mask_2026 = openg >= pd.Timestamp("2026-01-01")

    df_train_raw = df_all[mask_train].copy()
    df_2025_raw = df_all[mask_2025].copy()
    df_2026_raw = df_all[mask_2026].copy()

    print(
        f"학습 구간: {len(df_train_raw):,}행"
        f" ({df_train_raw['openg_dt'].min():%Y-%m-%d}"
        f" ~ {df_train_raw['openg_dt'].max():%Y-%m-%d})"
    )
    print(f"홀드아웃 2025: {len(df_2025_raw):,}행")
    print(f"OOS 2026: {len(df_2026_raw):,}행")

    if df_train_raw.empty:
        print("학습 구간이 비었습니다.")
        return 1
    if df_2025_raw.empty and df_2026_raw.empty:
        print("홀드아웃 구간이 모두 비었습니다.")
        return 1

    # ---------------------------------------------------------------------------
    # 기관 이력·재발주 이력을 학습 구간 기준으로 계산 후 홀드아웃에 붙인다.
    # 핵심: 학습 구간 전체(train + holdout)로 attach_institution_history 를 호출하면
    # 홀드아웃 행의 정답이 누적 집계에 들어간다. 따라서 학습 구간만 먼저 계산하고,
    # 홀드아웃 행에는 그 결과를 프레임 조인으로 이어 붙인다.
    #
    # attach_institution_history 는 shift(1).expanding().mean() 을 써서 각 행이
    # 자기 자신을 제외한 이전 행의 이력만 받는다. 학습 구간 전체를 넘겨도 홀드아웃
    # 행을 포함하지 않으므로 누수가 없다. 단, 홀드아웃 행이 프레임에 없으면 그
    # 기관의 이력값을 받을 수 없다. 해결책: 학습+홀드아웃 전체로 attach 를 한 번
    # 실행하되, 학습 구간과 홀드아웃 구간을 시간 순으로 정렬해 shift(1) 이 학습
    # 구간의 마지막 결과를 홀드아웃 첫 행에 전파하도록 한다.
    # attach_institution_history 내부 정렬이 openg_dt 기준이라 이 조건이 자동으로
    # 충족된다.
    # ---------------------------------------------------------------------------
    df_for_history = pd.concat([df_train_raw, df_2025_raw, df_2026_raw], ignore_index=True)
    df_for_history = attach_institution_history(df_for_history)
    df_for_history = attach_repeat_history(df_for_history)

    # 분할 마스크를 재적용 (인덱스가 0-based로 재설정됨)
    n_train = len(df_train_raw)
    n_2025 = len(df_2025_raw)
    idx_train = df_for_history.index[:n_train]
    idx_2025 = df_for_history.index[n_train : n_train + n_2025]
    idx_2026 = df_for_history.index[n_train + n_2025 :]

    df_train_hist = df_for_history.loc[idx_train].copy()
    df_2025_hist = df_for_history.loc[idx_2025].copy()
    df_2026_hist = df_for_history.loc[idx_2026].copy()

    # ---------------------------------------------------------------------------
    # 특징 생성: training_config 의 Cnstwk 특징/하이퍼파라미터 그대로 사용
    # ---------------------------------------------------------------------------
    feature_columns = training_features_for_category("Cnstwk")
    cnstwk_hyperparams = hyperparams_for_category("Cnstwk")
    lgb_hyperparams = cnstwk_hyperparams.get("lightgbm")

    print("후보 모델 특징 생성 중...")
    records_train = df_train_hist.to_dict(orient="records")
    features_list_train = build_feature_frame(records_train)
    df_feat_train = pd.DataFrame(features_list_train)

    # openg_dt 복원 (시계열 정렬 기준)
    if "openg_dt" in df_train_hist.columns:
        df_feat_train["openg_dt"] = df_train_hist["openg_dt"].to_numpy()

    category_levels = collect_category_levels(df_feat_train)
    df_feat_train = apply_categorical_dtypes(df_feat_train, category_levels)
    y_train = df_train_hist["winning_rate"].to_numpy(dtype=float)

    # 학습에 없는 컬럼이 feature_columns 에 있으면 누락 경고
    missing_cols = [c for c in feature_columns if c not in df_feat_train.columns]
    if missing_cols:
        print(f"경고: 학습 프레임에 없는 특징 컬럼: {missing_cols}")

    available_cols = [c for c in feature_columns if c in df_feat_train.columns]
    X_train = df_feat_train[available_cols]

    # ---------------------------------------------------------------------------
    # 후보 모델 학습 (메모리에서만 사용, 레지스트리 저장 없음)
    # ---------------------------------------------------------------------------
    print(f"후보 모델 학습 중 (학습 행: {len(X_train):,}) ...")
    candidate_model = _train_lightgbm_candidate(X_train, y_train, lgb_hyperparams)

    # ---------------------------------------------------------------------------
    # v25 로더 준비
    # ---------------------------------------------------------------------------
    v25_loader: Callable[[], Any] | None = None
    if args.v25_loader:
        module_path, func_name = args.v25_loader.rsplit(".", 1)
        import importlib

        mod = importlib.import_module(module_path)
        v25_loader = getattr(mod, func_name)

    # ---------------------------------------------------------------------------
    # 홀드아웃 평가 함수
    # ---------------------------------------------------------------------------
    def _eval_segment(
        df_holdout_hist: pd.DataFrame,
        label: str,
    ) -> dict[str, Any] | None:
        if df_holdout_hist.empty:
            return None

        records = df_holdout_hist.to_dict(orient="records")
        features_list = build_feature_frame(records)
        df_feat = pd.DataFrame(features_list)
        df_feat = apply_categorical_dtypes(df_feat, category_levels)

        missing_h = [c for c in available_cols if c not in df_feat.columns]
        eval_cols = [c for c in available_cols if c not in missing_h]
        X_holdout = df_feat[eval_cols]
        y_true = df_holdout_hist["winning_rate"].to_numpy(dtype=float)

        cand_pred = np.asarray(candidate_model.predict(X_holdout), dtype=float)

        print(f"  v25 예측 중 ({label}, {len(df_holdout_hist):,}건) ...")
        v25_pred = predict_v25_batch(df_holdout_hist, loader=v25_loader)

        # NaN 행 제거 (v25 예측 실패 행)
        valid = np.isfinite(cand_pred) & np.isfinite(v25_pred) & np.isfinite(y_true)
        if not valid.any():
            print(f"  경고: {label} 구간의 유효 예측이 없습니다.")
            return None

        return _segment_metrics(y_true[valid], cand_pred[valid], v25_pred[valid], label)

    # ---------------------------------------------------------------------------
    # 구간별 평가
    # ---------------------------------------------------------------------------
    print("홀드아웃 평가 시작...")
    segments: list[dict[str, Any]] = []

    seg_2025 = _eval_segment(df_2025_hist, "2025년")
    if seg_2025:
        segments.append(seg_2025)

    if not df_2026_hist.empty and "bid_ntce_dt" in df_2026_hist.columns:
        mask_pre = df_2026_hist["bid_ntce_dt"] < REGIME_SHIFT_DATE
        df_2026_pre = df_2026_hist[mask_pre].copy()
        df_2026_post = df_2026_hist[~mask_pre].copy()
    else:
        df_2026_pre = df_2026_hist.copy()
        df_2026_post = pd.DataFrame()

    seg_2026_pre = _eval_segment(df_2026_pre, "2026년 레짐 전(공고일 2026-05-26 미만)")
    if seg_2026_pre:
        segments.append(seg_2026_pre)

    seg_2026_post = _eval_segment(df_2026_post, "2026년 레짐 후(공고일 2026-05-26 이상)")
    if seg_2026_post:
        segments.append(seg_2026_post)

    elapsed = time.perf_counter() - t0

    # ---------------------------------------------------------------------------
    # 결과 JSON 저장
    # ---------------------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "meta": {
            "parquet_path": str(parquet_path),
            "train_rows": len(df_train_raw),
            "holdout_2025_rows": len(df_2025_raw),
            "oos_2026_rows": len(df_2026_raw),
            "feature_columns": list(available_cols),
            "lgb_hyperparams": lgb_hyperparams or {},
            "git_commit": _git_commit(),
            "elapsed_seconds": round(elapsed, 2),
            "promotion_threshold": {
                "t": PROMOTION_T_THRESHOLD,
                "mae_improvement": PROMOTION_MAE_IMPROVEMENT,
            },
        },
        "segments": segments,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n결과 저장: {output_path}")

    # ---------------------------------------------------------------------------
    # 콘솔 요약
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 92)
    print("구간별 평가 요약")
    print("=" * 92)
    for seg in segments:
        n = seg["n"]
        c = seg["candidate"]
        v = seg["v25"]
        p = seg["paired"]
        meets = seg["meets_promotion_criteria"]
        print(f"\n[{seg['segment']}] n={n:,}")
        print(
            f"  후보 모델 - MAE: {c['mae']:.4f}  RMSE: {c['rmse']:.4f}"
            f"  0.5%p 적중: {c['hit_rate_0_5pct']:.4f}"
        )
        print(
            f"  v25 기준선 - MAE: {v['mae']:.4f}  RMSE: {v['rmse']:.4f}"
            f"  0.5%p 적중: {v['hit_rate_0_5pct']:.4f}"
        )
        print(f"  쌍대 (후보-v25): 평균차={p['mean_diff']:.6f}  SE={p['se']:.6f}  t={p['t']:.4f}")
        print(f"  MAE 개선: {seg['mae_improvement']:.6f}  승격 판단 기준 충족: {meets}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
