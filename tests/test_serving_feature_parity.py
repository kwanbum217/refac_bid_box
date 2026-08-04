"""서빙 경로가 features.py 단일 공급원을 쓰는지 검증합니다.

model_registry 가 특징 맵 복제본을 들고 있던 동안, 신규 제도 특징과 범주형이
추론 프레임에서 조용히 0.0 으로 떨어졌습니다. 예외가 나지 않아 성능만 무너지는
형태였으므로 회귀를 테스트로 고정합니다.
"""

from __future__ import annotations

import inspect

import pandas as pd
import pytest

from src.ml import model_registry
from src.ml.features import (
    CATEGORICAL_FEATURES,
    MISSING_CATEGORY,
    build_default_feature_map,
)
from src.ml.trainer import TRAINING_FEATURES

SAMPLE_NOTICE = {
    "srvce_div_nm": "일반용역",
    "lrg_clsfc_nm": "건설관리",
    "mid_clsfc_nm": "건축설계",
    "clsfc_nm": "건축설계용역",
    "cntrct_mthd_nm": "제한경쟁",
    "prearng_mthd": "복수예가",
    "sucsfbid_mthd_nm": "적격심사",
    "ntce_kind_nm": "일반공고",
    "bid_methd_nm": "전자입찰",
    "intrbid_yn": "N",
    "ppsw_gnrl_srvce_yn": "Y",
    "lwlt_rate": 87.745,
    "presumed_price": 500_000_000,
    "base_amount": 505_000_000,
    "bid_ntce_dt": "2025-03-10",
    "openg_dt": "2025-03-24",
    "dminstt_nm": "한국도로공사",
    "is_repeat": 1.0,
    "repeat_cnt": 3.0,
    "repeat_hist_rate": 0.881,
    "repeat_prev_rate": 0.879,
    "repeat_hist_std": 0.004,
    "repeat_days_since": 358.0,
}

CATEGORY_LEVELS = {
    column: [MISSING_CATEGORY, str(SAMPLE_NOTICE[column]), "다른값"]
    for column in CATEGORICAL_FEATURES
}


def test_registry_has_no_duplicate_feature_map():
    """AGENTS.md 6항. 특징 생성 로직은 features.py 한 곳에만 있어야 합니다."""
    source = inspect.getsource(model_registry)
    assert "def _build_default_feature_map" not in source
    assert "sem_" not in source, "구 특징 목록이 registry 에 남아 있습니다"


def test_categorical_values_survive_as_strings():
    """복제본 시절 문자열 범주가 float 변환에 실패해 0.0 이 되던 결함입니다."""
    columns = list(CATEGORICAL_FEATURES)
    frame = model_registry._prepare_input_frame(SAMPLE_NOTICE, columns)
    for column in columns:
        value = frame[column].iloc[0]
        assert value == SAMPLE_NOTICE[column]
        assert value != 0.0


def test_category_levels_restore_training_codes():
    columns = list(CATEGORICAL_FEATURES)
    frame = model_registry._prepare_input_frame(SAMPLE_NOTICE, columns, CATEGORY_LEVELS)
    for column in columns:
        assert isinstance(frame[column].dtype, pd.CategoricalDtype)
        assert list(frame[column].cat.categories) == CATEGORY_LEVELS[column]
        # 수준 목록이 학습과 같아야 코드가 일치합니다.
        assert int(frame[column].cat.codes.iloc[0]) == 1


def test_unseen_category_falls_back_to_missing():
    columns = ["srvce_div_nm"]
    payload = {**SAMPLE_NOTICE, "srvce_div_nm": "학습에없던구분"}
    frame = model_registry._prepare_input_frame(payload, columns, CATEGORY_LEVELS)
    assert frame["srvce_div_nm"].iloc[0] == MISSING_CATEGORY


def test_legacy_model_without_levels_still_works():
    """구 모델은 메타데이터에 수준이 없습니다. 하위호환이 깨지면 안 됩니다."""
    columns = ["srvce_div_nm", "log_price"]
    frame = model_registry._prepare_input_frame(SAMPLE_NOTICE, columns, None)
    assert frame["srvce_div_nm"].iloc[0] == "일반용역"
    assert frame["log_price"].iloc[0] > 0


def test_missing_lower_limit_sets_indicator():
    """하한율 결측을 0 으로 채우면 "하한율 0" 과 구분되지 않습니다."""
    payload = {key: value for key, value in SAMPLE_NOTICE.items() if key != "lwlt_rate"}
    frame = model_registry._prepare_input_frame(
        payload, ["lwlt_rate", "lwlt_rate_missing"]
    )
    assert frame["lwlt_rate"].iloc[0] == 0.0
    assert frame["lwlt_rate_missing"].iloc[0] == 1.0


@pytest.mark.parametrize("column", TRAINING_FEATURES)
def test_every_training_feature_is_servable(column):
    """학습이 쓰는 특징은 전부 추론 프레임에서 산출돼야 합니다.

    복제본에 없던 컬럼은 0.0 으로 조용히 채워졌습니다. 기본 특징 맵에 키가
    존재하는지로 그 구멍을 막습니다.
    """
    defaults = build_default_feature_map(SAMPLE_NOTICE)
    assert column in defaults, f"{column} 이 features.py 기본 맵에 없습니다"

    frame = model_registry._prepare_input_frame(SAMPLE_NOTICE, [column])
    assert frame[column].iloc[0] == defaults[column]
