import numpy as np

DEFAULT_META_FEATURE_ORDER = [
    "p_v17",
    "p_v18",
    "p_v19",
    "p_v20",
    "p_lgbm_meta",
    "p_cat_meta",
    "meta_mean",
    "meta_std",
    "meta_range",
    "meta_delta_lgbm_cat",
    "rank_spread",
    "pairwise_abs_diff_mean",
]


def _build_v25_meta_feature_map(lgbm_pred, cat_pred):
    base_avg = float((lgbm_pred + cat_pred) / 2.0)
    stack_values = np.array(
        [base_avg, base_avg, base_avg, base_avg, lgbm_pred, cat_pred],
        dtype=float,
    )
    feature_map = {
        "p_v17": base_avg,
        "p_v18": base_avg,
        "p_v19": base_avg,
        "p_v20": base_avg,
        "p_lgbm_meta": float(lgbm_pred),
        "p_cat_meta": float(cat_pred),
        "meta_mean": float(np.mean(stack_values)),
        "meta_std": float(np.std(stack_values)),
        "meta_range": float(np.max(stack_values) - np.min(stack_values)),
        "meta_delta_lgbm_cat": float(lgbm_pred - cat_pred),
        "rank_spread": float(np.std(np.argsort(np.argsort(stack_values)).astype(float))),
        "pairwise_abs_diff_mean": 0.0,
    }
    return feature_map, base_avg


def _blend_meta_predictions(meta, x_meta):
    p_ridge = float(meta["ridge"].predict(x_meta)[0])
    p_mlp = float(meta["mlp"].predict(x_meta)[0])
    ridge_weight = float(meta.get("blend_w", 0.5))
    mlp_weight = float(meta.get("mlp_weight", 0.5))
    total_weight = ridge_weight + mlp_weight
    if total_weight <= 0:
        return float(np.mean([p_ridge, p_mlp]))
    return float((p_ridge * ridge_weight + p_mlp * mlp_weight) / total_weight)


def predict_v25_logic(lgbm, cat, meta, df):
    lgbm_pred = float(lgbm.predict(df)[0])
    cat_pred = float(cat.predict(df)[0]) if cat else lgbm_pred
    feature_map, base_avg = _build_v25_meta_feature_map(lgbm_pred, cat_pred)

    feature_order = meta.get("meta_features") or DEFAULT_META_FEATURE_ORDER
    x_meta = np.array(
        [[float(feature_map.get(name, base_avg)) for name in feature_order]],
        dtype=float,
    )

    try:
        blended_pred = _blend_meta_predictions(meta, x_meta)
        # 메타모델이 base 예측보다 과도하게 튀는 경우 평균값으로 되돌립니다.
        if not np.isfinite(blended_pred) or abs(blended_pred - base_avg) > 0.25:
            return base_avg
        return blended_pred
    except Exception as exc:
        print(f"[v25_helper] 메타 추론 실패: {exc}")
        return base_avg
