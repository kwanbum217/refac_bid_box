"""서빙 경로가 features.py 단일 공급원을 쓰는지 검증합니다.

model_registry 가 특징 맵 복제본을 들고 있던 동안, 신규 제도 특징과 범주형이
추론 프레임에서 조용히 0.0 으로 떨어졌습니다. 예외가 나지 않아 성능만 무너지는
형태였으므로 회귀를 테스트로 고정합니다.
"""

from __future__ import annotations

import inspect
from typing import ClassVar

import pandas as pd
import pytest

from src.ml import model_registry
from src.ml.features import (
    CATEGORICAL_FEATURES,
    MISSING_CATEGORY,
    build_default_feature_map,
    prepare_input_frame,
    unservable_features,
)
from src.ml.model_registry import MODEL_FILES_ROOT
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


def test_unknown_feature_is_rejected_instead_of_zero_filled():
    """모르는 특징을 0.0 으로 채우면 잘못된 예측을 조용히 내놓습니다."""
    with pytest.raises(ValueError, match=r"features\.py 가 만들지 못합니다"):
        prepare_input_frame(SAMPLE_NOTICE, ["log_price", "존재하지않는특징"])


def test_caller_supplied_value_passes_the_guard():
    frame = prepare_input_frame({**SAMPLE_NOTICE, "참여업체수": 7}, ["참여업체수"])
    assert frame["참여업체수"].iloc[0] == 7.0


def test_non_strict_mode_keeps_legacy_behaviour():
    """실험 스크립트가 임의 컬럼을 만들 수 있도록 우회로를 남깁니다."""
    frame = prepare_input_frame({}, ["존재하지않는특징"], strict=False)
    assert frame["존재하지않는특징"].iloc[0] == 0.0


def test_trained_servc_model_is_deployable():
    """재학습이 내놓는 특징 전량이 추론에서 재현돼야 배포할 수 있습니다."""
    assert unservable_features(list(TRAINING_FEATURES)) == []


@pytest.mark.skipif(
    not any(MODEL_FILES_ROOT.glob("*/model.bin")),
    reason="모델 가중치가 없는 환경입니다",
)
def test_all_registered_models_are_servable(monkeypatch):
    """배포 게이트. 하나라도 걸리면 그 모델은 기본값으로 예측하게 됩니다.

    conftest 가 SKIP_MODEL_LOAD 로 가중치 로드를 막으므로 이 검사만 풀어 줍니다.
    게이트가 실제로 돌지 않으면 존재 의미가 없습니다.
    """
    from src.ml.model_registry import ModelRegistry

    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    try:
        report = ModelRegistry.verify_servable_features()
    finally:
        ModelRegistry._models = {}
    assert report, "등록된 모델이 없습니다"
    broken = {model_id: missing for model_id, missing in report.items() if missing}
    assert not broken, f"서빙 불가 특징이 있는 모델: {broken}"


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


def test_full_frame_keeps_institution_features():
    """예측 진입점이 프레임을 좁히면 wrapper 재구성 때 제도 특징이 사라집니다.

    실측에서 하한율 87.995% 인 건의 예측이 100.776% 로 나왔습니다.
    """
    frame = model_registry._prepare_full_frame(SAMPLE_NOTICE)
    row = frame.iloc[0].to_dict()
    for column in ("lwlt_rate", "lwlt_rate_missing", "srvce_div_nm", "mid_clsfc_nm", *TRAINING_FEATURES):
        assert column in row, f"{column} 이 예측 프레임에서 사라졌습니다"
    assert row["lwlt_rate"] == SAMPLE_NOTICE["lwlt_rate"]
    assert row["srvce_div_nm"] == SAMPLE_NOTICE["srvce_div_nm"]


def test_full_frame_keeps_legacy_rule_model_keys():
    """규칙 기반 구 모델은 title / agency_name / scenario_mode 를 씁니다."""
    payload = {**SAMPLE_NOTICE, "title": "도로 유지관리", "agency_name": "서울시", "scenario_mode": "2"}
    row = model_registry._prepare_full_frame(payload).iloc[0].to_dict()
    assert row["title"] == "도로 유지관리"
    assert row["agency_name"] == "서울시"
    assert row["scenario_mode"] == "2"


def test_announcement_payload_extracts_institution_fields():
    """API 가 raw_data 를 펼치지 않으면 34개 중 30개가 기본값이 됩니다."""
    from types import SimpleNamespace

    from src.ml.dataset import INSTITUTION_FIELDS, announcement_feature_payload

    raw = {json_key: f"값-{column}" for column, json_key in INSTITUTION_FIELDS.items()}
    bid = SimpleNamespace(raw_data=raw, bid_ntce_nm="테스트", dminstt_nm="테스트기관")
    payload = announcement_feature_payload(bid)
    for column in INSTITUTION_FIELDS:
        assert payload[column] == f"값-{column}"


def test_interval_is_optional_for_legacy_models():
    """분위 아티팩트가 없는 구 모델은 구간 없이 점 추정만 냅니다."""

    class _Legacy:
        model_dir = "/tmp/does-not-exist"
        metadata: ClassVar[dict] = {}

        get_serving_columns = model_registry.JoblibModelWrapper.get_serving_columns
        _load_quantile_models = model_registry.JoblibModelWrapper._load_quantile_models
        predict_interval = model_registry.JoblibModelWrapper.predict_interval

        def __init__(self):
            self._quantile_models = None
            self.model = None

        def get_features(self):
            return ["log_price"]

        def get_category_levels(self):
            return None

    assert _Legacy().predict_interval(pd.DataFrame([SAMPLE_NOTICE])) is None


def test_malformed_interval_does_not_break_prediction():
    """구간은 부가 정보입니다. 형태가 어긋나도 점 추정을 막으면 안 됩니다."""

    class _Broken:
        metadata: ClassVar[dict] = {"interval": {"target_coverage": 0.9}}

        def predict_interval(self, df):
            return "이상한 값"

    original = model_registry.ModelRegistry.get_model
    model_registry.ModelRegistry.get_model = classmethod(lambda cls, _id: _Broken())
    try:
        assert model_registry.predict_interval("x", SAMPLE_NOTICE) is None
    finally:
        model_registry.ModelRegistry.get_model = original


def test_trainer_records_interval_metadata():
    """승격 판정과 서빙이 배율을 읽으므로 메타데이터에 남아야 합니다."""
    from src.ml.trainer import INTERVAL_QUANTILES, INTERVAL_TARGET_COVERAGE

    assert INTERVAL_TARGET_COVERAGE == 0.90, "80% 는 보정 후에도 76.77% 라 쓰지 않습니다"
    assert tuple(INTERVAL_QUANTILES) == (0.1, 0.9)


# 키가 있는 것과 값이 맞는 것은 다릅니다. `inst_sample_cnt` 는 기본 맵에 키가
# 있어 위 테스트를 통과했지만, 학습이 채우는 파생 컬럼이라 서빙 payload 에는
# 없고 조회 폴백도 없어 **항상 0** 이 나갔습니다. 2026-08-05 대조 실측에서
# 학습값과의 평균절대차가 761 이었습니다. 아래는 그 형태의 결함을 잡습니다.
#
# 판정 기준: 학습이 attach 로 채우는 이력 특징은 세션이 주어지면 조회로
# 살아나야 하고, 세션이 없을 때만 기본값으로 떨어져야 합니다.
HISTORY_LOOKUP_FEATURES = ("inst_hist_rate", "inst_sample_cnt")


class _StubResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _StubSession:
    """집계 표에 값이 있는 상황을 흉내 냅니다."""

    def __init__(self, sample_count: int = 812, avg_rate: float = 88.5):
        self._values = [avg_rate, sample_count]

    def execute(self, _stmt):
        return _StubResult(self._values.pop(0) if self._values else None)


@pytest.mark.parametrize("column", HISTORY_LOOKUP_FEATURES)
def test_history_feature_is_not_silently_defaulted(column):
    """세션이 있으면 이력 특징은 조회값을 받아야 합니다.

    payload 에 값이 없을 때 조회 없이 상수로 떨어지면, 모델은 학습 때와 다른
    입력을 받고도 예외 없이 예측을 냅니다.
    """
    notice = dict(SAMPLE_NOTICE)
    notice.pop(column, None)

    without_session = build_default_feature_map(notice)
    with_session = build_default_feature_map(notice, session=_StubSession())

    assert with_session[column] != without_session[column], (
        f"{column} 이 세션 유무와 무관하게 같은 값입니다. 조회 폴백이 없습니다"
    )


def test_sample_count_reaches_serving_frame():
    """표본 수가 0 이 아닌 조회값으로 서빙 프레임에 실려야 합니다."""
    notice = dict(SAMPLE_NOTICE)
    notice.pop("inst_sample_cnt", None)
    served = build_default_feature_map(notice, session=_StubSession(sample_count=812))
    assert float(served["inst_sample_cnt"]) == 812.0
