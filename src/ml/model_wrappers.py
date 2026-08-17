import importlib.util
import os
from abc import ABC, abstractmethod
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.ml.features import (
    DEFAULT_INSTITUTION_NAME,
    _is_missing,
    apply_categorical_dtypes,
)

# 방어적 임포트
try:
    from catboost import CatBoostRegressor
except ImportError:
    CatBoostRegressor = None

try:
    import tensorflow as tf
except ImportError:
    tf = None

# model_registry.py 에서 로드 시점에 주입받는 런타임 종속성 (순환 import 방지)
_coerce_float = None
_apply_inference_thread_budget = None
_prepare_input_frame = None


class BaseModelWrapper(ABC):
    """모든 분석 모델의 베이스 어댑터 클래스"""

    def __init__(self, model_dir, metadata=None):
        self.model_dir = model_dir
        self.metadata = metadata or {}
        self.model_path = os.path.join(
            model_dir,
            self.metadata.get("model_file", "model.bin"),
        )
        self.model = None
        self.preprocessor = None
        self._load_preprocessor()
        self.load()

    def _load_preprocessor(self):
        """커스텀 preprocess.py가 있을 경우 동적 로드"""
        preprocess_path = os.path.join(self.model_dir, "preprocess.py")
        if not os.path.exists(preprocess_path):
            return
        try:
            spec = importlib.util.spec_from_file_location(
                "model_preprocess",
                preprocess_path,
            )
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "preprocess"):
                self.preprocessor = module.preprocess
                print(
                    f"[BaseModelWrapper] 커스텀 전처리 스크립트 로드됨: {self.model_dir}"
                )
        except Exception as exc:
            print(
                f"[BaseModelWrapper] 전처리 스크립트 로드 실패 ({self.model_dir}): {exc}"
            )

    @abstractmethod
    def load(self):
        raise NotImplementedError

    @abstractmethod
    def predict(self, df):
        raise NotImplementedError

    def run_preprocess(self, features_dict):
        """본 모델에 정의된 커스텀 전처리 수행"""
        if self.preprocessor:
            return self.preprocessor(features_dict)
        return None

    def get_features(self):
        return self.metadata.get("required_features", [])

    def get_category_levels(self):
        """학습 때 저장한 범주 수준. 구 모델은 없으므로 None 입니다."""
        return self.metadata.get("category_levels")

    def get_serving_columns(self):
        """추론 프레임에 요구하는 컬럼. 자체 전처리를 쓰는 모델은 빈 목록입니다."""
        return []

    def get_display_name(self):
        return self.metadata.get("name", os.path.basename(self.model_dir))


class JoblibModelWrapper(BaseModelWrapper):
    """Joblib 기반 모델 어댑터 (model.bin)"""

    def __init__(self, model_dir, metadata=None):
        # load() 안에서 쓰지 않으므로 부모 __init__ 전에 둘 필요는 없지만,
        # 부모가 load() 를 호출하므로 속성 선언은 먼저 해 둡니다.
        self._quantile_models = None
        super().__init__(model_dir, metadata)

    def load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {self.model_path}"
            )
        self.model = joblib.load(self.model_path)
        _apply_inference_thread_budget(self.model)

    def get_serving_columns(self):
        return list(getattr(self.model, "feature_name_", []) or self.get_features())

    def _load_quantile_models(self):
        """분위 모델을 지연 로드합니다. 없으면 빈 dict 라 구간을 내지 않습니다."""
        if self._quantile_models is None:
            loaded = {}
            for path in sorted(Path(self.model_dir).glob("model_q*.bin")):
                try:
                    quantile = int(path.stem.split("_q")[1]) / 100.0
                    quantile_model = joblib.load(path)
                    _apply_inference_thread_budget(quantile_model)
                    loaded[quantile] = quantile_model
                except (ValueError, IndexError, OSError) as exc:
                    print(f"[JoblibModelWrapper] 분위 모델 로드 실패 ({path}): {exc}")
            self._quantile_models = loaded
        return self._quantile_models

    def predict_interval(self, df):
        """예측 구간 (하단, 상단) 을 돌려줍니다. 구간이 없으면 None 입니다.

        소박한 분위 회귀 구간은 보정에 실패하므로(명목 80% 대비 실제 75.52%)
        학습 때 산정한 등각예측 배율로 중앙 기준 확대합니다.
        """
        models = self._load_quantile_models()
        if len(models) < 2:
            return None
        columns = self.get_serving_columns()
        if not columns:
            return None
        frame = _prepare_input_frame(
            df.iloc[0].to_dict(),
            columns,
            self.get_category_levels(),
            defaults=df.attrs.get("feature_defaults"),
        )
        bounds = sorted(
            float(np.asarray(model.predict(frame)).reshape(-1)[0])
            for model in models.values()
        )
        low, high = bounds[0], bounds[-1]
        interval_meta = self.metadata.get("interval") or {}
        scale = float(interval_meta.get("conformal_scale") or 1.0)
        center, half = (low + high) / 2, (high - low) / 2 * scale
        return center - half, center + half

    def predict(self, df):
        features = self.get_serving_columns()
        input_df = (
            _prepare_input_frame(
                df.iloc[0].to_dict(),
                features,
                self.get_category_levels(),
                defaults=df.attrs.get("feature_defaults"),
            )
            if features
            else df
        )
        prediction = self.model.predict(input_df)
        return float(np.asarray(prediction).reshape(-1)[0])

    def predict_batch(self, frames):
        """여러 요청의 동일 모델 추론을 한 번의 LightGBM 호출로 처리합니다."""
        if type(self).predict is not JoblibModelWrapper.predict:
            raise ValueError("사용자 정의 래퍼는 단건 추론 경로를 유지합니다.")
        columns = self.get_serving_columns()
        if not columns:
            raise ValueError("배치 추론에 필요한 모델 컬럼이 없습니다.")
        levels = self.get_category_levels()
        prepared_rows = []
        for frame in frames:
            values = frame.iloc[0].to_dict()
            defaults = frame.attrs.get("feature_defaults") or {}
            row = {}
            for column in columns:
                default = defaults.get(column, 0.0)
                value = values.get(column, default)
                if _is_missing(value):
                    value = default
                if isinstance(default, str):
                    row[column] = str(value) if value not in (None, "") else default
                else:
                    row[column] = _coerce_float(value, default)
            prepared_rows.append(row)
        # 단건 프레임을 반복 생성·concat 하지 않고 행을 한 번에 만들어
        # 동일한 범주 수준을 한 번만 적용해 배치 자체의 GIL 비용을 줄입니다.
        batch = pd.DataFrame(
            prepared_rows,
            columns=columns,
        )
        batch = apply_categorical_dtypes(batch, levels)
        predictions = np.asarray(self.model.predict(batch)).reshape(-1)
        if len(predictions) != len(frames):
            raise ValueError("배치 추론 결과 행 수가 요청 수와 다릅니다.")
        return [float(value) for value in predictions]


class KerasModelWrapper(BaseModelWrapper):
    """Keras 기반 딥러닝 모델 어댑터 (model.bin)"""

    def load(self):
        if tf is None:
            raise ImportError("TensorFlow 미설치")
        self.model = tf.keras.models.load_model(self.model_path)

    def predict(self, df):
        features = self.get_features()
        input_data = df[features].values if features else df.values
        prediction = self.model.predict(input_data, verbose=0)
        return float(np.asarray(prediction).reshape(-1)[0])


class V13HybridWrapper(BaseModelWrapper):
    """v13 하이브리드 번들 어댑터"""

    def load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {self.model_path}"
            )
        self.model = joblib.load(self.model_path)
        required_keys = {
            "s1_tier_clf",
            "s1_q50",
            "s1_q10",
            "s1_q90",
            "loo_s1",
            "silo_models",
        }
        if not isinstance(self.model, dict) or not required_keys.issubset(self.model):
            raise ValueError("v13_hybrid 번들 구조가 올바르지 않습니다.")

    def get_serving_columns(self):
        # 2단계 컬럼은 예측 결과로 고른 실로마다 달라, 합집합으로 봅니다.
        columns = list(self.model["s1_tier_clf"].feature_name_)
        for bundle in self.model["silo_models"].values():
            for name in bundle["model"].feature_name_:
                if name not in columns:
                    columns.append(name)
        return columns

    def predict(self, df):
        base_values = df.iloc[0].to_dict()
        defaults = df.attrs.get("feature_defaults")
        stage1_columns = list(self.model["s1_tier_clf"].feature_name_)
        stage1_df = _prepare_input_frame(
            base_values, stage1_columns, self.get_category_levels(), defaults=defaults
        )
        stage1_encoded = self.model["loo_s1"].transform(stage1_df)

        pred_tier = int(self.model["s1_tier_clf"].predict(stage1_encoded)[0])
        q10 = float(self.model["s1_q10"].predict(stage1_encoded)[0])
        q50 = float(self.model["s1_q50"].predict(stage1_encoded)[0])
        q90 = float(self.model["s1_q90"].predict(stage1_encoded)[0])

        silo_models = self.model["silo_models"]
        silo_bundle = silo_models.get(np.int32(pred_tier))
        if silo_bundle is None:
            silo_bundle = next(iter(silo_models.values()))

        stage2_values = dict(base_values)
        stage2_values.update(
            {
                "silo_id": float(pred_tier),
                "pred_tier": float(pred_tier),
                "q50": q50,
                "count_spread": max(q90 - q10, 0.0),
                "log_price_density_q50": q50 / max(
                    _coerce_float(base_values.get("log_price"), 1.0),
                    1.0,
                ),
            }
        )
        stage2_columns = list(silo_bundle["model"].feature_name_)
        stage2_df = _prepare_input_frame(
            stage2_values, stage2_columns, self.get_category_levels(), defaults=defaults
        )
        encoded_stage2 = silo_bundle["loo"].transform(stage2_df)
        prediction = silo_bundle["model"].predict(encoded_stage2)
        return float(np.asarray(prediction).reshape(-1)[0])


class EnsembleV25Wrapper(BaseModelWrapper):
    """v25 특화 앙상블 모델 어댑터"""

    def load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {self.model_path}"
            )
        self.meta = joblib.load(self.model_path)
        self.lgbm = joblib.load(os.path.join(self.model_dir, "v25_lgbm_final.joblib"))
        self.cat = None
        cat_bin = os.path.join(self.model_dir, "v25_cat_final.bin")
        if CatBoostRegressor and os.path.exists(cat_bin):
            self.cat = CatBoostRegressor()
            self.cat.load_model(cat_bin)

    def get_serving_columns(self):
        return list(getattr(self.lgbm, "feature_name_", []))

    def predict(self, df):
        from .predictor_v25_helper import predict_v25_logic

        feature_order = self.get_serving_columns() or list(df.columns)
        aligned_df = _prepare_input_frame(
            df.iloc[0].to_dict(),
            feature_order,
            self.get_category_levels(),
            defaults=df.attrs.get("feature_defaults"),
        )
        return predict_v25_logic(self.lgbm, self.cat, self.meta, aligned_df)


class QuantumLeapRuleWrapper(BaseModelWrapper):
    """Notebook-derived heuristic bundle for goods bidding."""

    def load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {self.model_path}"
            )
        self.model = joblib.load(self.model_path)
        if not isinstance(self.model, dict):
            raise ValueError("quantum_leap_v25_pro 번들 형식이 올바르지 않습니다.")

    def _contains_keyword(self, text, keywords):
        base_text = str(text or "")
        return any(keyword in base_text for keyword in keywords or [])

    def _detect_sector(self, title):
        sector_keywords = self.model.get("sector_keywords") or {}
        for sector_name, keywords in sector_keywords.items():
            if self._contains_keyword(title, keywords):
                return sector_name
        return "일반/물품"

    def _resolve_region_multiplier(self, agency_name):
        regional_keywords = self.model.get("regional_keywords") or {}
        regional_multipliers = self.model.get("regional_multipliers") or {}
        if self._contains_keyword(agency_name, regional_keywords.get("metro")):
            return _coerce_float(regional_multipliers.get("metro"), 1.0)
        if self._contains_keyword(agency_name, regional_keywords.get("regional")):
            return _coerce_float(regional_multipliers.get("regional"), 1.0)
        return _coerce_float(regional_multipliers.get("default"), 1.0)

    def _resolve_floor(self, price):
        thresholds = self.model.get("price_thresholds") or {}
        price_floors = self.model.get("price_floors") or {}
        small_max = _coerce_float(thresholds.get("small_max"), 20_000_000)
        large_min = _coerce_float(thresholds.get("large_min"), 210_000_000)

        if price < small_max:
            return _coerce_float(price_floors.get("small"), 87.995)
        if price >= large_min:
            return _coerce_float(price_floors.get("large"), 80.495)
        return _coerce_float(price_floors.get("mid"), 84.245)

    def predict(self, df):
        row = df.iloc[0].to_dict()
        title = row.get("title") or row.get("bid_ntce_nm") or ""
        agency_name = (
            row.get("agency_name")
            or row.get("dminstt_nm")
            or row.get("ntce_instt_nm")
            or DEFAULT_INSTITUTION_NAME
        )
        scenario_mode = str(
            row.get("scenario_mode") or self.model.get("default_scenario_mode") or "2"
        )
        price = max(_coerce_float(row.get("presmpt_prce"), 0.0), 0.0)

        sector_name = self._detect_sector(title)
        sector_stats = (self.model.get("stats") or {}).get(sector_name) or {}
        gravity = 1.2 if price < 50_000_000 else (0.85 if price > 200_000_000 else 1.0)
        regional_mult = self._resolve_region_multiplier(agency_name)
        base_delta = _coerce_float(sector_stats.get("base_delta"), 6.0)
        mode_adjustments = self.model.get("mode_adjustments") or {"1": 0.78, "2": 1.05, "3": 1.45}
        scenario_multiplier = _coerce_float(
            mode_adjustments.get(scenario_mode, mode_adjustments.get("2", 1.05)),
            1.05,
        )
        floor = self._resolve_floor(price)

        historical_spread = max(
            _coerce_float(sector_stats.get("median_rate"), floor)
            - _coerce_float(sector_stats.get("q10_rate"), floor),
            0.0,
        )
        blended_delta = (base_delta * gravity * regional_mult * scenario_multiplier)
        if historical_spread > 0:
            blended_delta = (blended_delta * 0.65) + (historical_spread * 0.35)

        target_rate = floor + blended_delta
        return float(max(floor, min(104.95, target_rate)))


class HistPremiumEnsembleWrapper(BaseModelWrapper):
    """SSH 실험 코드를 서비스 번들 규격으로 옮긴 프리미엄 앙상블 모델."""

    def load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {self.model_path}"
            )
        self.model = joblib.load(self.model_path)
        required_keys = {
            "models",
            "feature_names",
            "method_categories",
            "bid_categories",
            "lower_rate_by_group",
            "fallback_lower_rate",
        }
        if not isinstance(self.model, dict) or not required_keys.issubset(self.model):
            raise ValueError("ssh_hist_premium 번들 형식이 올바르지 않습니다.")

    def _normalize_ratio(self, value):
        numeric = _coerce_float(value, 0.0)
        if numeric <= 0:
            return None
        return numeric / 100.0 if numeric > 1 else numeric

    def _fallback_lower_rate(self, row):
        contract_method = str(row.get("cntrctCnclsMthdNm") or "")
        category = str(row.get("category") or "")
        title = str(row.get("title") or row.get("bid_ntce_nm") or "")
        combined = " ".join((contract_method, category, title))
        if "적격심사" in contract_method:
            return 0.87745
        if "물품" in combined or category == "Thng":
            return 0.84
        if "용역" in combined or category == "Servc":
            return 0.88
        return _coerce_float(self.model.get("fallback_lower_rate"), 0.84)

    def _resolve_lower_rate(self, row):
        direct = self._normalize_ratio(row.get("lower_rate"))
        if direct is not None:
            return direct

        institution_name = (
            row.get("ntceInsttNm")
            or row.get("ntce_instt_nm")
            or row.get("agency_name")
            or row.get("dminstt_nm")
            or DEFAULT_INSTITUTION_NAME
        )
        group_key = "_".join(
            [
                str(row.get("cntrctCnclsMthdNm") or ""),
                str(row.get("bidMethdNm") or ""),
                str(institution_name),
            ]
        )
        mapped = (self.model.get("lower_rate_by_group") or {}).get(group_key)
        if mapped is not None:
            return _coerce_float(mapped, self._fallback_lower_rate(row))
        return self._fallback_lower_rate(row)

    def _encode_category(self, value, categories):
        normalized = str(value or "")
        try:
            return float(categories.index(normalized))
        except ValueError:
            return -1.0

    def predict(self, df):
        row = df.iloc[0].to_dict()
        price = max(
            _coerce_float(
                row.get("presmpt_prce", row.get("presmptPrce")),
                0.0,
            ),
            0.0,
        )
        lower_rate = self._resolve_lower_rate(row)
        feature_row = {
            "log_price": np.log1p(price) if price > 0 else 0.0,
            "lower_rate": lower_rate,
            "method_enc": self._encode_category(
                row.get("cntrctCnclsMthdNm"),
                list(self.model.get("method_categories") or []),
            ),
            "bid_enc": self._encode_category(
                row.get("bidMethdNm"),
                list(self.model.get("bid_categories") or []),
            ),
        }
        feature_names = list(self.model.get("feature_names") or feature_row.keys())
        input_df = pd.DataFrame([[feature_row[name] for name in feature_names]], columns=feature_names)
        models = list(self.model.get("models") or [])
        if not models:
            raise ValueError("ssh_hist_premium 모델이 비어 있습니다.")
        premiums = [float(np.asarray(model.predict(input_df)).reshape(-1)[0]) for model in models]
        predicted_rate = lower_rate + float(np.mean(premiums))
        return float(predicted_rate)
