"""
tests/test_model_wrappers_coverage.py

src/ml/model_wrappers.py 의 모델 래퍼 클래스들에 대한 단위 테스트.
BaseModelWrapper, JoblibModelWrapper, KerasModelWrapper, V13HybridWrapper,
EnsembleV25Wrapper, QuantumLeapRuleWrapper, HistPremiumEnsembleWrapper 의
예외, 실패 경로, 경계 조건 및 추론 파이프라인을 격리 환경(tmp_path)에서 검증한다.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import joblib
import numpy as np
import pandas as pd
import pytest

# model_registry 가 로드 시점에 model_wrappers 에 런타임 종속성을 주입하므로 먼저 임포트
import src.ml.model_registry  # noqa: F401
import src.ml.model_wrappers as mw
from src.ml.model_wrappers import (
    BaseModelWrapper,
    EnsembleV25Wrapper,
    HistPremiumEnsembleWrapper,
    JoblibModelWrapper,
    KerasModelWrapper,
    QuantumLeapRuleWrapper,
    V13HybridWrapper,
)

# ==============================================================================
# 모듈 최상위 Mock 클래스들 (joblib / pickle 직렬화 가능)
# ==============================================================================


class DummyPredictor:
    """테스트용 단일/다건 예측 모델 모의 객체."""

    def __init__(self, feature_names: list[str] | None = None, return_val: float = 88.5):
        self.feature_name_ = feature_names if feature_names is not None else []
        self.return_val = return_val

    def predict(self, data):
        count = len(data) if hasattr(data, "__len__") else 1
        return np.full((count,), self.return_val)


class MismatchPredictor(DummyPredictor):
    """배치 추론 시 요청 수와 다른 행 수를 반환하는 모의 객체."""

    def predict(self, data):
        return np.array([self.return_val])


class ConcreteBaseWrapper(BaseModelWrapper):
    """BaseModelWrapper 의 추상 메서드를 구현한 테스트 전용 서브클래스."""

    def load(self):
        pass

    def predict(self, df):
        return 90.0


class MockClf:
    """v13 하이브리드용 분류기 모의 객체."""

    feature_name_: ClassVar[list[str]] = ["log_price", "lwlt_rate"]

    def __init__(self, tier: int = 2):
        self.tier = tier

    def predict(self, x):
        return np.array([self.tier])


class MockQuantile:
    """v13 하이브리드용 분위 회귀기 모의 객체."""

    def __init__(self, val: float):
        self.val = val

    def predict(self, x):
        return np.array([self.val])


class MockEncoder:
    """v13 하이브리드용 LOO 인코더 모의 객체."""

    def transform(self, df):
        return df


class MockSiloModel:
    """v13 하이브리드 2단계 사일로 모델 모의 객체."""

    feature_name_: ClassVar[list[str]] = ["log_price", "silo_id"]

    def __init__(self, return_val: float = 88.9):
        self.return_val = return_val

    def predict(self, x):
        return np.array([self.return_val])


class MockHistSubmodel:
    """HistPremiumEnsembleWrapper 용 하위 모델 모의 객체."""

    def __init__(self, premium: float = 0.025):
        self.premium = premium

    def predict(self, df):
        return np.array([self.premium])


# ==============================================================================
# 1. BaseModelWrapper 전처리 및 메타데이터 메서드 검증
# ==============================================================================


def test_base_model_wrapper_without_preprocessor(tmp_path):
    """preprocess.py 가 없는 경우 run_preprocess 는 None 을 반환해야 한다."""
    wrapper = ConcreteBaseWrapper(
        model_dir=str(tmp_path),
        metadata={"name": "custom_name", "required_features": ["feat1", "feat2"]},
    )
    assert wrapper.run_preprocess({"feat1": 1.0}) is None
    assert wrapper.get_features() == ["feat1", "feat2"]
    assert wrapper.get_category_levels() is None
    assert wrapper.get_serving_columns() == []
    assert wrapper.get_display_name() == "custom_name"


def test_base_model_wrapper_with_valid_preprocessor(tmp_path):
    """preprocess.py 가 존재하고 preprocess 함수가 정의된 경우 정상 로드 및 실행되어야 한다."""
    script_content = (
        "def preprocess(features_dict):\n"
        "    return {'processed': True, 'count': len(features_dict)}\n"
    )
    (tmp_path / "preprocess.py").write_text(script_content, encoding="utf-8")

    wrapper = ConcreteBaseWrapper(model_dir=str(tmp_path))
    assert wrapper.preprocessor is not None

    res = wrapper.run_preprocess({"a": 10, "b": 20})
    assert res == {"processed": True, "count": 2}


def test_base_model_wrapper_preprocessor_load_failure(tmp_path):
    """preprocess.py 에 문법 오류 또는 로드 중 예외가 발생하면 예외를 잡고 preprocessor 는 None 이어야 한다."""
    (tmp_path / "preprocess.py").write_text("def broken_syntax(:\n", encoding="utf-8")

    wrapper = ConcreteBaseWrapper(model_dir=str(tmp_path))
    assert wrapper.preprocessor is None
    assert wrapper.run_preprocess({"x": 1}) is None


def test_base_model_wrapper_preprocessor_without_target_attribute(tmp_path):
    """preprocess.py 에 preprocess 속성이 없으면 preprocessor 는 None 으로 남아야 한다."""
    (tmp_path / "preprocess.py").write_text("x = 42\n", encoding="utf-8")

    wrapper = ConcreteBaseWrapper(model_dir=str(tmp_path))
    assert wrapper.preprocessor is None


def test_base_model_wrapper_preprocessor_spec_none(tmp_path, monkeypatch):
    """spec_from_file_location 이 None 이거나 loader 가 없으면 조기 반환해야 한다."""
    (tmp_path / "preprocess.py").write_text("def preprocess(x): return x\n", encoding="utf-8")
    import importlib.util

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
    wrapper = ConcreteBaseWrapper(model_dir=str(tmp_path))
    assert wrapper.preprocessor is None


# ==============================================================================
# 2. JoblibModelWrapper 검증 (단건, 분위 구간, 배치 추론, 실패 경로)
# ==============================================================================


def test_joblib_model_wrapper_load_missing_file(tmp_path):
    """model.bin 파일이 없으면 FileNotFoundError 가 발생해야 한다."""
    with pytest.raises(FileNotFoundError) as exc_info:
        JoblibModelWrapper(model_dir=str(tmp_path))
    assert "모델 파일을 찾을 수 없습니다" in str(exc_info.value)


def test_joblib_model_wrapper_predict_single(tmp_path):
    """단건 프레임에 대한 joblib 모델의 예측 및 get_serving_columns 폴백 검증."""
    model_file = tmp_path / "model.bin"
    dummy = DummyPredictor(feature_names=["log_price", "lwlt_rate"], return_val=87.3)
    joblib.dump(dummy, model_file)

    wrapper = JoblibModelWrapper(
        model_dir=str(tmp_path),
        metadata={"category_levels": {"mid_clsfc_nm": ["기타"]}},
    )
    assert wrapper.get_serving_columns() == ["log_price", "lwlt_rate"]

    df = pd.DataFrame([{"log_price": 10.0, "lwlt_rate": 88.0}])
    df.attrs["feature_defaults"] = {"log_price": 0.0, "lwlt_rate": 0.0}
    pred = wrapper.predict(df)
    assert isinstance(pred, float)
    assert pred == 87.3


def test_joblib_model_wrapper_predict_interval(tmp_path):
    """분위 모델 파일(model_q10.bin, model_q90.bin)이 존재할 때 예측 구간을 정상 산출해야 한다."""
    main_model = DummyPredictor(feature_names=["log_price"], return_val=88.0)
    joblib.dump(main_model, tmp_path / "model.bin")

    q10_model = DummyPredictor(feature_names=["log_price"], return_val=85.0)
    joblib.dump(q10_model, tmp_path / "model_q10.bin")

    q90_model = DummyPredictor(feature_names=["log_price"], return_val=95.0)
    joblib.dump(q90_model, tmp_path / "model_q90.bin")

    # 손상된 파일명도 glob 에 걸리지만 로드 실패 후 스킵되는지 확인
    (tmp_path / "model_qbroken.bin").write_text("broken content", encoding="utf-8")

    wrapper = JoblibModelWrapper(
        model_dir=str(tmp_path),
        metadata={"interval": {"conformal_scale": 1.2}},
    )

    df = pd.DataFrame([{"log_price": 12.0}])
    df.attrs["feature_defaults"] = {"log_price": 0.0}
    low, high = wrapper.predict_interval(df)
    # low=85.0, high=95.0 -> center=90.0, half=5.0 * 1.2 = 6.0 -> 84.0, 96.0
    assert low == pytest.approx(84.0)
    assert high == pytest.approx(96.0)


def test_joblib_model_wrapper_predict_interval_insufficient_models(tmp_path):
    """분위 모델이 2개 미만이거나 서빙 컬럼이 없으면 predict_interval 은 None 을 반환해야 한다."""
    main_model = DummyPredictor(feature_names=["log_price"], return_val=88.0)
    joblib.dump(main_model, tmp_path / "model.bin")

    wrapper = JoblibModelWrapper(model_dir=str(tmp_path))
    df = pd.DataFrame([{"log_price": 12.0}])
    assert wrapper.predict_interval(df) is None

    # 분위 모델은 2개 있지만 서빙 컬럼이 빈 경우
    joblib.dump(DummyPredictor(feature_names=[], return_val=80.0), tmp_path / "model_q10.bin")
    joblib.dump(DummyPredictor(feature_names=[], return_val=90.0), tmp_path / "model_q90.bin")
    no_col_model = DummyPredictor(feature_names=[], return_val=88.0)
    joblib.dump(no_col_model, tmp_path / "model.bin")

    wrapper2 = JoblibModelWrapper(model_dir=str(tmp_path))
    assert wrapper2.predict_interval(df) is None


def test_joblib_model_wrapper_predict_batch_success(tmp_path):
    """다건 프레임에 대해 배치 추론이 정상 작동하고 float 리스트를 반환해야 한다."""
    dummy = DummyPredictor(feature_names=["log_price", "str_col"], return_val=88.2)
    joblib.dump(dummy, tmp_path / "model.bin")

    wrapper = JoblibModelWrapper(
        model_dir=str(tmp_path),
        metadata={"category_levels": {"str_col": ["A", "B", "미상"]}},
    )

    f1 = pd.DataFrame([{"log_price": 10.0, "str_col": "A"}])
    f1.attrs["feature_defaults"] = {"log_price": 0.0, "str_col": "미상"}

    f2 = pd.DataFrame([{"log_price": None, "str_col": None}])
    f2.attrs["feature_defaults"] = {"log_price": 0.0, "str_col": "미상"}

    preds = wrapper.predict_batch([f1, f2])
    assert len(preds) == 2
    assert preds == [88.2, 88.2]


def test_joblib_model_wrapper_predict_batch_exceptions(tmp_path):
    """서브클래스에서 predict 를 재정의했거나, 컬럼 누락 또는 결과 행 수 불일치 시 ValueError 가 발생해야 한다."""
    dummy = DummyPredictor(feature_names=["feat1"], return_val=80.0)
    joblib.dump(dummy, tmp_path / "model.bin")

    class CustomWrapper(JoblibModelWrapper):
        def predict(self, df):
            return 99.0

    custom = CustomWrapper(model_dir=str(tmp_path))
    f = pd.DataFrame([{"feat1": 1.0}])
    with pytest.raises(ValueError) as exc_info:
        custom.predict_batch([f])
    assert "사용자 정의 래퍼는 단건 추론 경로를 유지합니다" in str(exc_info.value)

    # 컬럼 없는 모델인 경우
    dummy_no_cols = DummyPredictor(feature_names=[], return_val=80.0)
    joblib.dump(dummy_no_cols, tmp_path / "model.bin")
    wrapper_no_cols = JoblibModelWrapper(model_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc_info:
        wrapper_no_cols.predict_batch([f])
    assert "배치 추론에 필요한 모델 컬럼이 없습니다" in str(exc_info.value)

    # 행 수 불일치인 경우
    joblib.dump(MismatchPredictor(feature_names=["feat1"]), tmp_path / "model.bin")
    wrapper_mismatch = JoblibModelWrapper(model_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc_info:
        wrapper_mismatch.predict_batch([f, f])
    assert "배치 추론 결과 행 수가 요청 수와 다릅니다" in str(exc_info.value)


# ==============================================================================
# 3. KerasModelWrapper 검증
# ==============================================================================


def test_keras_model_wrapper_tf_missing(tmp_path, monkeypatch):
    """TensorFlow 미설치 시 load 호출 시 ImportError 가 발생해야 한다."""
    monkeypatch.setattr(mw, "tf", None)
    with pytest.raises(ImportError) as exc_info:
        KerasModelWrapper(model_dir=str(tmp_path))
    assert "TensorFlow 미설치" in str(exc_info.value)


def test_keras_model_wrapper_mock_predict(tmp_path, monkeypatch):
    """TensorFlow 가 있을 때 KerasModelWrapper 가 정상 로드 및 추론되어야 한다."""
    mock_tf = MagicMock()
    mock_keras_model = MagicMock()
    mock_keras_model.predict.return_value = np.array([[91.75]])
    mock_tf.keras.models.load_model.return_value = mock_keras_model
    monkeypatch.setattr(mw, "tf", mock_tf)

    # model_path 파일 생성
    (tmp_path / "model.bin").write_text("fake_keras_model", encoding="utf-8")

    wrapper = KerasModelWrapper(
        model_dir=str(tmp_path),
        metadata={"required_features": ["feat_a", "feat_b"]},
    )
    assert wrapper.model is mock_keras_model

    df = pd.DataFrame([{"feat_a": 1.0, "feat_b": 2.0}])
    pred = wrapper.predict(df)
    assert pred == pytest.approx(91.75)


# ==============================================================================
# 4. V13HybridWrapper 검증
# ==============================================================================


def test_v13_hybrid_wrapper_missing_file(tmp_path):
    """v13_hybrid 모델 파일이 없으면 FileNotFoundError 가 발생해야 한다."""
    with pytest.raises(FileNotFoundError):
        V13HybridWrapper(model_dir=str(tmp_path / "non_existent"))


def test_v13_hybrid_wrapper_invalid_bundle(tmp_path):
    """필수 키가 누락된 번들일 경우 load 시 ValueError 가 발생해야 한다."""
    model_file = tmp_path / "model.bin"
    joblib.dump({"incomplete_key": 1}, model_file)

    with pytest.raises(ValueError) as exc_info:
        V13HybridWrapper(model_dir=str(tmp_path))
    assert "v13_hybrid 번들 구조가 올바르지 않습니다" in str(exc_info.value)


def test_v13_hybrid_wrapper_predict_pipeline(tmp_path):
    """V13HybridWrapper 의 1단계 분류, 분위수 예측, 2단계 사일로 추론이 정상 동작해야 한다."""
    bundle = {
        "s1_tier_clf": MockClf(tier=2),
        "s1_q10": MockQuantile(85.0),
        "s1_q50": MockQuantile(88.0),
        "s1_q90": MockQuantile(91.0),
        "loo_s1": MockEncoder(),
        "silo_models": {
            np.int32(2): {"model": MockSiloModel(return_val=88.9), "loo": MockEncoder()}
        },
    }
    joblib.dump(bundle, tmp_path / "model.bin")

    wrapper = V13HybridWrapper(model_dir=str(tmp_path))
    columns = wrapper.get_serving_columns()
    assert "log_price" in columns
    assert "silo_id" in columns

    df = pd.DataFrame([{"log_price": 10.0, "lwlt_rate": 88.0}])
    df.attrs["feature_defaults"] = {"log_price": 0.0, "lwlt_rate": 0.0, "silo_id": 0.0}
    pred = wrapper.predict(df)
    assert pred == pytest.approx(88.9)

    # 분류된 티어가 silo_models 에 없을 때 fallback 브랜치(next(iter(silo_models.values()))) 검증
    bundle_fallback = dict(bundle, s1_tier_clf=MockClf(tier=999))
    joblib.dump(bundle_fallback, tmp_path / "model.bin")
    wrapper_fallback = V13HybridWrapper(model_dir=str(tmp_path))
    pred_fallback = wrapper_fallback.predict(df)
    assert pred_fallback == pytest.approx(88.9)


# ==============================================================================
# 5. EnsembleV25Wrapper 검증
# ==============================================================================


def test_ensemble_v25_wrapper_missing_file(tmp_path):
    """EnsembleV25Wrapper 모델 파일이 없으면 FileNotFoundError 가 발생해야 한다."""
    with pytest.raises(FileNotFoundError):
        EnsembleV25Wrapper(model_dir=str(tmp_path / "non_existent"))


def test_ensemble_v25_wrapper_with_catboost(tmp_path, monkeypatch):
    """v25_cat_final.bin 파일이 있을 때 CatBoostRegressor 가 로드되어야 한다."""
    meta = {"threshold": 0.5}
    joblib.dump(meta, tmp_path / "model.bin")
    joblib.dump(DummyPredictor(feature_names=["f1"]), tmp_path / "v25_lgbm_final.joblib")

    # cat 파일 생성 및 CatBoostRegressor 모의
    (tmp_path / "v25_cat_final.bin").write_text("fake_cat", encoding="utf-8")
    mock_cat_cls = MagicMock()
    mock_cat_instance = MagicMock()
    mock_cat_cls.return_value = mock_cat_instance
    monkeypatch.setattr(mw, "CatBoostRegressor", mock_cat_cls)

    wrapper = EnsembleV25Wrapper(model_dir=str(tmp_path))
    assert wrapper.cat is mock_cat_instance
    mock_cat_instance.load_model.assert_called_once()


def test_ensemble_v25_wrapper_pipeline(tmp_path, monkeypatch):
    """EnsembleV25Wrapper 가 lgbm, catboost 모델을 로드하고 predict_v25_logic 을 호출해야 한다."""
    meta = {"threshold": 0.5}
    joblib.dump(meta, tmp_path / "model.bin")

    lgbm_mock = DummyPredictor(feature_names=["f1", "f2"], return_val=89.0)
    joblib.dump(lgbm_mock, tmp_path / "v25_lgbm_final.joblib")

    # cat_final.bin 은 없는 상태로 테스트
    wrapper = EnsembleV25Wrapper(model_dir=str(tmp_path))
    assert wrapper.cat is None
    assert wrapper.get_serving_columns() == ["f1", "f2"]

    # helper 모의
    mock_helper = MagicMock(return_value=89.4)
    import src.ml.predictor_v25_helper as p_helper

    monkeypatch.setattr(p_helper, "predict_v25_logic", mock_helper)

    df = pd.DataFrame([{"f1": 1.0, "f2": 2.0}])
    df.attrs["feature_defaults"] = {"f1": 0.0, "f2": 0.0}
    pred = wrapper.predict(df)
    assert pred == pytest.approx(89.4)
    mock_helper.assert_called_once()


# ==============================================================================
# 6. QuantumLeapRuleWrapper 검증 (키워드 탐지, 지역 가중치, 하한율, 규칙 추론)
# ==============================================================================


def test_quantum_leap_rule_wrapper_missing_file(tmp_path):
    """QuantumLeapRuleWrapper 모델 파일이 없으면 FileNotFoundError 가 발생해야 한다."""
    with pytest.raises(FileNotFoundError):
        QuantumLeapRuleWrapper(model_dir=str(tmp_path / "non_existent"))


def test_quantum_leap_rule_wrapper_invalid_bundle(tmp_path):
    """dict 가 아닌 번들이 들어오면 ValueError 가 발생해야 한다."""
    joblib.dump(["not_a_dict"], tmp_path / "model.bin")
    with pytest.raises(ValueError) as exc_info:
        QuantumLeapRuleWrapper(model_dir=str(tmp_path))
    assert "quantum_leap_v25_pro 번들 형식이 올바르지 않습니다" in str(exc_info.value)


def test_quantum_leap_rule_wrapper_helpers_and_predict(tmp_path):
    """QuantumLeapRuleWrapper 의 섹터/지역/하한선 분기와 점수 산출 공식을 검증한다."""
    bundle = {
        "sector_keywords": {"전산": ["SW", "소프트웨어", "전산"]},
        "regional_keywords": {"metro": ["서울", "경기"], "regional": ["강원", "충남"]},
        "regional_multipliers": {"metro": 1.02, "regional": 0.98, "default": 1.0},
        "price_thresholds": {"small_max": 20_000_000, "large_min": 210_000_000},
        "price_floors": {"small": 87.995, "large": 80.495, "mid": 84.245},
        "stats": {
            "전산": {"base_delta": 4.5, "median_rate": 88.0, "q10_rate": 85.0},
            "일반/물품": {"base_delta": 6.0, "median_rate": 89.0, "q10_rate": 86.0},
        },
        "mode_adjustments": {"1": 0.78, "2": 1.05, "3": 1.45},
        "default_scenario_mode": "2",
    }
    joblib.dump(bundle, tmp_path / "model.bin")

    wrapper = QuantumLeapRuleWrapper(model_dir=str(tmp_path))

    # 1. 보조 메서드 검증
    assert wrapper._contains_keyword("서울특별시 전산망 구축", ["서울"]) is True
    assert wrapper._contains_keyword(None, ["서울"]) is False
    assert wrapper._detect_sector("소프트웨어 유지보수") == "전산"
    assert wrapper._detect_sector("사무용 가구") == "일반/물품"
    assert wrapper._resolve_region_multiplier("서울특별시 교육청") == pytest.approx(1.02)
    assert wrapper._resolve_region_multiplier("강원특별자치도") == pytest.approx(0.98)
    assert wrapper._resolve_region_multiplier("제주특별자치도") == pytest.approx(1.0)
    assert wrapper._resolve_floor(10_000_000) == pytest.approx(87.995)
    assert wrapper._resolve_floor(250_000_000) == pytest.approx(80.495)
    assert wrapper._resolve_floor(50_000_000) == pytest.approx(84.245)

    # 2. predict 연산 검증 (소액 전산 건)
    df_small = pd.DataFrame(
        [
            {
                "title": "전산 시스템 유지보수",
                "agency_name": "서울특별시청",
                "presmpt_prce": 15_000_000,
                "scenario_mode": "2",
            }
        ]
    )
    pred_small = wrapper.predict(df_small)
    assert pred_small >= 87.995
    assert pred_small <= 104.95

    # 3. 대형 건 (price > 200,000,000)
    df_large = pd.DataFrame(
        [
            {
                "title": "물품 납품 건",
                "agency_name": "한국도로공사",
                "presmpt_prce": 300_000_000,
                "scenario_mode": "1",
            }
        ]
    )
    pred_large = wrapper.predict(df_large)
    assert pred_large >= 80.495
    assert pred_large <= 104.95


# ==============================================================================
# 7. HistPremiumEnsembleWrapper 검증
# ==============================================================================


def test_hist_premium_ensemble_wrapper_missing_file(tmp_path):
    """HistPremiumEnsembleWrapper 모델 파일이 없으면 FileNotFoundError 가 발생해야 한다."""
    with pytest.raises(FileNotFoundError):
        HistPremiumEnsembleWrapper(model_dir=str(tmp_path / "non_existent"))


def test_hist_premium_ensemble_wrapper_invalid_bundle(tmp_path):
    """필수 키가 누락된 번들은 load 시 ValueError 가 발생해야 한다."""
    joblib.dump({"models": []}, tmp_path / "model.bin")
    with pytest.raises(ValueError) as exc_info:
        HistPremiumEnsembleWrapper(model_dir=str(tmp_path))
    assert "ssh_hist_premium 번들 형식이 올바르지 않습니다" in str(exc_info.value)


def test_hist_premium_ensemble_wrapper_helpers_and_predict(tmp_path):
    """HistPremiumEnsembleWrapper 의 하한율 결정, 카테고리 인코딩 및 예측 파이프라인 검증."""
    bundle = {
        "models": [MockHistSubmodel(0.025), MockHistSubmodel(0.025)],
        "feature_names": ["log_price", "lower_rate", "method_enc", "bid_enc"],
        "method_categories": ["일반경쟁", "수의계약"],
        "bid_categories": ["전자입찰", "직접입찰"],
        "lower_rate_by_group": {"일반경쟁_전자입찰_조달청": 0.879},
        "fallback_lower_rate": 0.84,
    }
    joblib.dump(bundle, tmp_path / "model.bin")

    wrapper = HistPremiumEnsembleWrapper(model_dir=str(tmp_path))

    # 1. 보조 메서드 검증
    assert wrapper._normalize_ratio(-1) is None
    assert wrapper._normalize_ratio(0) is None
    assert wrapper._normalize_ratio(88.5) == pytest.approx(0.885)
    assert wrapper._normalize_ratio(0.885) == pytest.approx(0.885)

    assert wrapper._fallback_lower_rate({"cntrctCnclsMthdNm": "적격심사낙찰제"}) == pytest.approx(
        0.87745
    )
    assert wrapper._fallback_lower_rate({"category": "Thng"}) == pytest.approx(0.84)
    assert wrapper._fallback_lower_rate({"category": "Servc"}) == pytest.approx(0.88)
    assert wrapper._fallback_lower_rate({"title": "기타공고"}) == pytest.approx(0.84)

    assert wrapper._encode_category("일반경쟁", ["일반경쟁", "수의계약"]) == 0.0
    assert wrapper._encode_category("미상방식", ["일반경쟁", "수의계약"]) == -1.0

    # 2. lower_rate 가 행에 직접 주어진 경우
    row_direct = {"lower_rate": 88.0, "presmpt_prce": 100_000_000}
    assert wrapper._resolve_lower_rate(row_direct) == pytest.approx(0.88)

    # 3. lower_rate 매핑이 있는 경우
    row_mapped = {
        "cntrctCnclsMthdNm": "일반경쟁",
        "bidMethdNm": "전자입찰",
        "ntceInsttNm": "조달청",
        "presmpt_prce": 100_000_000,
    }
    pred_mapped = wrapper.predict(pd.DataFrame([row_mapped]))
    # lower_rate=0.879 + mean(0.025, 0.025)=0.025 -> 0.904
    assert pred_mapped == pytest.approx(0.904)

    # 4. lower_rate 매핑이 없는 그룹일 때 폴백 하한율 적용 검증
    row_unmapped = {
        "cntrctCnclsMthdNm": "미상계약",
        "bidMethdNm": "미상입찰",
        "ntceInsttNm": "미상기관",
        "category": "Thng",
        "presmpt_prce": 50_000_000,
    }
    pred_unmapped = wrapper.predict(pd.DataFrame([row_unmapped]))
    # lower_rate=0.84 (Thng fallback) + 0.025 = 0.865
    assert pred_unmapped == pytest.approx(0.865)

    # 5. 모델이 비어 있을 때 예외 검증
    bundle_empty_models = dict(bundle, models=[])
    joblib.dump(bundle_empty_models, tmp_path / "model.bin")
    wrapper_empty = HistPremiumEnsembleWrapper(model_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc_info:
        wrapper_empty.predict(pd.DataFrame([row_mapped]))
    assert "ssh_hist_premium 모델이 비어 있습니다" in str(exc_info.value)
