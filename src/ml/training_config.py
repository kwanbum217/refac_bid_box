"""
src/ml/training_config.py

모델 학습 설정 및 카테고리별 하이퍼파라미터/특징 설정.
"""

from __future__ import annotations

from typing import Any

from src.ml.features import CATEGORICAL_FEATURES
from src.ml.repeat_history import REPEAT_FEATURES

# 점 추정 모델의 LightGBM 용량 설정입니다. 분위 모델은 아래
# QUANTILE_PARAM_OVERRIDES 로 따로 잡습니다.
#
# scripts/tune_servc_hyperparams.py 좌표 하강 17회 실측(2026-08-04, 학습
# 765,150행 / 검증 96,141행)에서 값어치가 있어 보인 축은 num_leaves 하나
# 뿐이었습니다.
#
# 그때 255 를 기각한 근거에는 사각지대가 있었습니다. 이 설정을 점 추정과 분위
# 모델이 함께 쓰고 있었기 때문에 리프를 올리면 **두 모델이 동시에** 바뀌었고,
# 관측된 "MAE 개선 + 구간 폭 11.2% 악화" 는 분리되지 않은 합계였습니다.
# 그래서 아래 QUANTILE_PARAM_OVERRIDES 로 두 축을 갈랐습니다. 분리 후에는 점
# 추정 용량을 키워도 구간 폭이 움직이지 않습니다(운영 실측 1.423%p 동일).
#
# 전량 재적합 결함 수정 전에는 리프를 올린 이득이 운영에서 나타나지 않았습니다.
# 같은 표본 1,000건의 당시 실측입니다.
#
#              홀드아웃 MAE   운영 MAE   운영 RMSE   운영 0.5%p 적중
#   리프  63       1.2838     0.9848      3.1195         75.2%
#   리프 127       1.2710     0.9863      3.1455         74.5%
#
# 이후 모델 선택 뒤 최신 20%를 버리던 결함을 고치고 동일 학습 상한으로 다시
# 평가하자 용역 리프 255 + EWM이 우세했습니다. 운영 3,999건에서도 MAE 3.42%
# 개선, 쌍대 절대오차 t=-7.50으로 재현됐습니다. 이 기본값 63은 물품과 미지정
# 카테고리에 유지하고, 용역만 CATEGORY_HYPERPARAMS에서 255로 재정의합니다.
# 근거는 docs/design/servc_unbiased_candidate_recheck_20260805.md 입니다.
#
# subsample 은 LightGBM 이 subsample_freq(기본 0)가 0 이면 통째로 무시합니다.
# 탐색에서 0.6/0.8/1.0 의 MAE 가 소수점 넷째 자리까지 같게 나온 것이 그
# 증거이며, 즉 이 설정은 지금까지 아무 일도 하지 않았습니다. 값을 지우면
# 과거 아티팩트와 파라미터 비교가 어긋나므로 남기되, 무효임을 여기 적습니다.
LGB_BASE_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 40,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "verbose": -1,
    "n_jobs": -1,
}

# 카테고리별 모델 네임스페이스. 물품과 용역은 예정가격 산정과 낙찰자 결정이
# 서로 다른 제도라 한 이름을 공유하면 champion 비교가 뒤섞입니다.
#
# 공사는 아직 전용 모델을 학습하지 않았지만 이름은 미리 갈라 둡니다. 예전에는
# 미등록 카테고리가 DEFAULT_MODEL_NAME 으로 떨어져, 공사 재학습이 물품 디렉터리에
# 저장되고 물품 champion 과 비교됐을 것입니다. 학습을 돌리는 순간 물품 승격본을
# 덮어쓰는 경로였습니다.
#
# 서빙 매핑은 model_registry.CATEGORY_DEFAULT_MODELS 이며 지금은 공사를 v25 로
# 보냅니다. cnstwk_institution_v1 이 실제로 승격되기 전까지 두 매핑이 다른 것은
# 의도된 상태입니다. 승격 시점에 서빙 매핑도 함께 옮겨야 합니다.
DEFAULT_MODEL_NAME = "quantum_leap_v25_pro"
CATEGORY_MODEL_NAMES = {
    "Thng": "quantum_leap_v25_pro",
    "Servc": "servc_institution_v1",
    "Cnstwk": "cnstwk_institution_v1",
}

# 편향 없는 동일 학습 상한 재평가에서 용역은 리프 255와 기관 EWM 조합이
# 기준 대비 MAE 3.13%를 낮췄습니다. 물품에는 검증되지 않았으므로 적용하지 않습니다.
#
# objective 는 _train_lightgbm 의 기본값 huber(alpha=1.0)를 덮어씁니다. 용역 잔차는
# 0 에 몰린 비대칭 분포라 조건부 중앙값을 직접 겨냥하는 quantile(0.5)이 낫습니다.
# 2026년 out-of-sample 56,338건 실측에서 MAE 1.3554 -> 1.3312, 0.5%p 이내 적중
# 58.53% -> 59.65% 이고 7개 모집단 중 악화가 없었습니다. RMSE 는 2.7454 -> 2.7834
# 로 나빠지며 이는 L1 최적화의 대가로 수용한 값입니다.
#
# huber 의 alpha 를 줄여 L1 에 다가가는 방향은 기각됐습니다. alpha=0.2 는 gradient
# 가 +-alpha 로 고정돼 학습 신호가 평평해지고 MAE 1.7971 로 32% 나빴습니다. 두
# 목적함수는 연속적으로 이어지지 않습니다.
#
# 이 "lightgbm" 키는 점 추정 전용입니다. 분위 모델은 QUANTILE_HYPERPARAM_KEY
# 로 따로 받으므로 여기 objective quantile alpha 0.5 와 리프 255 는 구간에
# 닿지 않습니다. 두 키를 합치면 10·90분위가 중앙값으로 무너집니다.
# 근거: docs/design/servc_loss_function_20260807.md
#
# num_leaves 는 huber 아래에서 고른 255 가 quantile 에서도 최적이었습니다.
# 511 은 MAE 1.2560 으로 나쁘고 0.5%p 적중은 61.49% 로 더 떨어집니다. 용량은
# 손실함수가 아니라 범주 조합 구조가 정합니다. 목적함수를 바꿨다는 이유만으로
# 용량 축을 다시 훑을 필요가 없습니다.
#
# quantile 아래 좌표 하강이 찾은 min_child_samples 160 / learning_rate 0.03 /
# n_estimators 2000 / subsample_freq 5 조합은 기각했습니다. 홀드아웃에서 MAE
# 1.2562 -> 1.2525 였고 시드 3개 전부 일관이었는데도, 운영 8,995건 쌍대에서
# 1.4050 -> 1.4188 로 t=5.14 만큼 나빴습니다. 6개 집단 중 challenger 우세는
# 0개입니다. 원인은 조기 종료입니다. _train_lightgbm 은 early_stopping(10)을
# 걸지만 탐색 스크립트는 걸지 않아, 낮춘 학습률이 탐색에서는 2000 그루로
# 보상되고 운영에서는 조기 종료로 잘립니다.
# 근거: docs/design/servc_hyperparam_quantile_20260807.md
#
# alpha 는 0.5 를 유지합니다. 2026-08-10 에 0.45 를 후보로 올렸다가 운영 쌍대에서
# 기각했습니다. 홀드아웃(2025년 96,141건)에서는 0.45 가 꼭짓점인 U 자형이고 MAE
# 1.2407 -> 1.2323, 0.5%p 적중 62.2995% -> 62.4642% 로 여섯 지표가 모두 좋아졌으나,
# 운영 9,997건 쌍대에서 MAE t=-0.44 로 판별 불가였고 적중률은 63.99% -> 63.92% 로
# 오히려 뒤집혔습니다. RMSE 만 t=-5.60 으로 유의했는데 이 지표 단독으로는 승격
# 하지 않습니다.
#
# **편향을 근거로 방향을 정하지 마십시오.** 편향 -0.0477 을 과소예측으로 보고
# alpha 를 올린 것이 처음 오류였습니다. 0.52 부터 전 지표가 단조 악화했고, 편향이
# 네 배 커지는 0.45 쪽이 홀드아웃에서 최선이었습니다. 낙찰률 분포가 위로 꼬리를
# 끌어 최적 예측점이 조건부 중앙값보다 아래에 있습니다. 평균 편향은 그 사실의
# 부산물이지 고칠 결함이 아닙니다.
# 근거: docs/design/servc_quantile_alpha_20260810.md
CATEGORY_HYPERPARAMS = {
    "Servc": {"lightgbm": {"num_leaves": 255, "objective": "quantile", "alpha": 0.5}}
}


def model_name_for_category(category_code: str | None) -> str:
    """카테고리 코드를 모델 네임스페이스로 옮깁니다.

    모르는 코드를 조용히 DEFAULT_MODEL_NAME 으로 떨어뜨리지 않습니다. 그 동작은
    다른 제도의 학습 산출물을 물품 이름으로 저장해 물품 champion 을 덮어씁니다.
    카테고리를 새로 학습하려면 CATEGORY_MODEL_NAMES 에 먼저 등록하십시오.
    """
    code = (category_code or "").strip()
    if not code:
        return DEFAULT_MODEL_NAME
    if code not in CATEGORY_MODEL_NAMES:
        raise ValueError(
            f"모델 네임스페이스가 없는 카테고리입니다: {code}. "
            f"CATEGORY_MODEL_NAMES 에 등록하십시오 (등록됨: {sorted(CATEGORY_MODEL_NAMES)})"
        )
    return CATEGORY_MODEL_NAMES[code]


# 학습에 쓰는 특징. features.py 산출물 중 실측으로 선정했습니다 (2026-08-02).
#
# inst_hist_rate 가 사실상 유일한 신호입니다. 이 값 하나만으로 R2 0.33 이고,
# 빼면 전체 R2 가 0.36 에서 0.03 으로 떨어집니다.
#
# 제외한 것들과 근거입니다.
#   inst_rate_mean_30d  inst_hist_rate 를 그대로 복사한 값이라 중복입니다
#   inst_rate_std_90d   입력이 없어 항상 상수 0.015 입니다
#   price_ratio         기초금액은 제도상 예정가격의 1.1 배라 표준편차 0.017,
#                       목표 상관 0.05 로 신호가 없습니다
#
# 2026-08-03 에 제도 특징을 추가했습니다. 용역 917,629행 시간순 홀드아웃 실측입니다.
#
#   기존 6종            R2 0.5600  RMSE 3.1780
#   + 제도 수치         R2 0.6433  RMSE 2.8615
#   + 제도 범주         R2 0.6683  RMSE 2.7591
#
# 근거: docs/design/servc_segment_experiment_20260803.md
#
# 같은 날 세부분류(중/소)와 공고속성을 더했습니다. 학습 2024년까지, 검증 2025년
# 96,141건 실측입니다.
#
#   범주 5종            R2 0.6767  RMSE 2.7312
#   범주 11종           R2 0.6910  RMSE 2.6701
#
# 근거: docs/design/servc_restricted_competition_20260803.md
NUMERIC_FEATURES = [
    "log_price",
    "month_sin",
    "month_cos",
    "weekday_sin",
    "weekday_cos",
    "notice_duration",
    "inst_hist_rate",
    "inst_sample_cnt",
    "lwlt_rate",
    "lwlt_rate_missing",
    "is_post_regime_shift",
    "notice_amt_ratio",
    "is_over_notice_amt",
    "tech_ablt_evl_rt",
    "bid_prce_evl_rt",
    "tot_prdprc_num",
    "drwt_prdprc_num",
    *REPEAT_FEATURES,
]

TRAINING_FEATURES = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
SERVC_EXTRA_FEATURES = ["inst_ewm_rate"]


def training_features_for_category(category_code: str | None) -> list[str]:
    """검증된 카테고리에만 추가 특징을 적용합니다."""
    if (category_code or "").strip() == "Servc":
        return [*TRAINING_FEATURES, *SERVC_EXTRA_FEATURES]
    return list(TRAINING_FEATURES)


def hyperparams_for_category(
    category_code: str | None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """카테고리 기본값에 호출자 재정의를 모델별로 병합합니다."""
    effective = {
        name: dict(params)
        for name, params in CATEGORY_HYPERPARAMS.get((category_code or "").strip(), {}).items()
    }
    for name, params in (overrides or {}).items():
        effective[name] = {**effective.get(name, {}), **params}
    return effective
