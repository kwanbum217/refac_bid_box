import importlib.util
import json
import math
import os
from abc import ABC, abstractmethod
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.ml.features import (
    DEFAULT_INSTITUTION_NAME,
    apply_categorical_dtypes,
    build_default_feature_map,
    prepare_features,
    prepare_input_frame,
    unservable_features,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_FILES_ROOT = PROJECT_ROOT / "data" / "model_files"

# 방어적 임포트
try:
    from catboost import CatBoostRegressor
except ImportError:
    CatBoostRegressor = None

try:
    import tensorflow as tf
except ImportError:
    tf = None


MODEL_ALIASES = {
    "v13_pruned_hybrid": "v13_hybrid",
}

# 카테고리별 기본 서빙 모델. 이 dict 가 정본이며 app 계층은 여기서 가져다 씁니다.
# 종전 용역 기본값 ssh_hist_premium 은 5폴드 중 3개가 R2 0.9999999999999998 인
# 타깃 누수 모델이었습니다. 근거: docs/design/servc_prediction_model_design.md 1장
CATEGORY_DEFAULT_MODELS = {
    "Thng": "quantum_leap_v25_pro",
    "Servc": "servc_institution_v1",
}

DEFAULT_RATIO_MIN = 0.75
DEFAULT_RATIO_MAX = 1.05


def _coerce_float(value, default=0.0):
    if value is None:
        return float(default)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return numeric


def _load_champion_metrics(model_dir):
    summary_path = os.path.join(model_dir, "champion_summary.json")
    if not os.path.exists(summary_path):
        return {
            "validation_label": "요약 없음",
            "validation_type": "missing_summary",
        }
    try:
        with open(summary_path, encoding="utf-8") as handle:
            summary = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {
            "validation_label": "요약 없음",
            "validation_type": "invalid_summary",
        }

    aggregate = summary.get("aggregate") or {}
    acceptance = summary.get("acceptance") or {}
    n_holdouts = aggregate.get("n_holdouts")
    fold_count = aggregate.get("fold_count") or len(summary.get("folds") or [])
    training_rows = aggregate.get("training_rows")
    sector_count = len(summary.get("sectors") or {})
    validation_label = "요약 없음"
    validation_type = "missing_summary"
    if n_holdouts:
        validation_label = f"{n_holdouts}회"
        validation_type = "holdout"
    elif fold_count:
        validation_label = f"{fold_count}-fold"
        validation_type = "cross_validation"
    elif sector_count:
        validation_label = "프로파일"
        validation_type = "profile"
    elif training_rows:
        validation_label = "학습 요약"
        validation_type = "training_profile"

    return {
        "avg_r2": aggregate.get("avg_r2"),
        "avg_mae": aggregate.get("avg_mae"),
        "min_r2": aggregate.get("min_r2"),
        "max_mae": aggregate.get("max_mae"),
        "n_holdouts": n_holdouts,
        "fold_count": fold_count,
        "training_rows": training_rows,
        "sector_count": sector_count,
        "validation_label": validation_label,
        "validation_type": validation_type,
        "baseline_r2": acceptance.get("baseline_r2"),
        "baseline_mae": acceptance.get("baseline_mae"),
        "pass_all": acceptance.get("pass_all"),
    }


def _prepare_input_frame(feature_values, column_order, category_levels=None):
    """추론 프레임을 만듭니다. 특징 정의는 features.py 단일 공급원을 따릅니다.

    범주 수준은 학습 때 저장한 목록으로 되살립니다. 이 복원을 빼면 추론 시점의
    범주 코드가 학습 때와 달라져 모델이 조용히 다른 값을 읽습니다.
    구 모델은 메타데이터에 수준이 없으므로 None 이 되어 아무 일도 하지 않습니다.
    """
    frame = prepare_input_frame(feature_values, column_order)
    return apply_categorical_dtypes(frame, category_levels)


def _normalize_prediction_rate(raw_prediction):
    prediction = _coerce_float(raw_prediction, 0.0)
    if prediction <= 0:
        raise ValueError(f"예측값이 비정상입니다: {raw_prediction}")
    if prediction >= 10:
        prediction /= 100.0
    return max(DEFAULT_RATIO_MIN, min(DEFAULT_RATIO_MAX, prediction))


def _prepare_features(features_dict):
    return prepare_features(features_dict)


def _prepare_full_frame(features_dict):
    """모든 특징을 실은 1행 프레임을 만듭니다.

    wrapper 는 받은 프레임을 df.iloc[0].to_dict() 로 되돌린 뒤 자기 컬럼으로
    다시 구성합니다. 여기서 프레임을 구 52컬럼으로 좁히면 그 사이에 제도 특징과
    재발주 이력이 사라지고, wrapper 가 전부 기본값으로 채웁니다. 실측에서
    하한율 87.995% 인 건의 예측이 100.776% 로 나왔습니다.
    원본 키도 남깁니다. 규칙 기반 구 모델이 title / agency_name 을 씁니다.
    """
    return pd.DataFrame([{**features_dict, **build_default_feature_map(features_dict)}])


def _resolve_model_id(model_id):
    normalized = (model_id or "v25").strip()
    return MODEL_ALIASES.get(normalized, normalized)


def _preferred_model_for_features(features_dict):
    category = str(features_dict.get("category") or "").strip()
    return CATEGORY_DEFAULT_MODELS.get(category, "v25")


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

    def get_serving_columns(self):
        return list(getattr(self.model, "feature_name_", []) or self.get_features())

    def _load_quantile_models(self):
        """분위 모델을 지연 로드합니다. 없으면 빈 dict 라 구간을 내지 않습니다."""
        if self._quantile_models is None:
            loaded = {}
            for path in sorted(Path(self.model_dir).glob("model_q*.bin")):
                try:
                    quantile = int(path.stem.split("_q")[1]) / 100.0
                    loaded[quantile] = joblib.load(path)
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
            df.iloc[0].to_dict(), columns, self.get_category_levels()
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
            )
            if features
            else df
        )
        prediction = self.model.predict(input_df)
        return float(np.asarray(prediction).reshape(-1)[0])


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
        stage1_columns = list(self.model["s1_tier_clf"].feature_name_)
        stage1_df = _prepare_input_frame(base_values, stage1_columns, self.get_category_levels())
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
        stage2_df = _prepare_input_frame(stage2_values, stage2_columns, self.get_category_levels())
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
            df.iloc[0].to_dict(), feature_order, self.get_category_levels()
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


class ModelRegistry:
    _models = {}

    @classmethod
    def _get_model_root(cls):
        return str(MODEL_FILES_ROOT)

    @classmethod
    def _discover_model_ids_on_disk(cls):
        model_root = cls._get_model_root()
        if not os.path.exists(model_root):
            os.makedirs(model_root, exist_ok=True)
            return []
        return sorted(
            entry
            for entry in os.listdir(model_root)
            if os.path.isdir(os.path.join(model_root, entry))
        )

    @classmethod
    def expected_model_ids(cls):
        """가중치 디렉터리에 등록된 모델 식별자를 반환합니다."""
        return cls._discover_model_ids_on_disk()

    @classmethod
    def _sync_registry(cls, force=False):
        disk_model_ids = cls._discover_model_ids_on_disk()
        loaded_model_ids = sorted(cls._models.keys())
        if force or disk_model_ids != loaded_model_ids:
            cls.load_all_models()

    @classmethod
    def discover_models(cls):
        if os.getenv("SKIP_MODEL_LOAD", "false").lower() == "true":
            print("[ModelRegistry] SKIP_MODEL_LOAD=true: skipping heavy model loading.")
            return

        model_root = cls._get_model_root()
        if not os.path.exists(model_root):
            os.makedirs(model_root, exist_ok=True)
            return

        for entry in sorted(os.listdir(model_root)):
            model_dir = os.path.join(model_root, entry)
            if not os.path.isdir(model_dir):
                continue

            metadata = {}
            metadata_path = os.path.join(model_dir, "metadata.json")
            if os.path.exists(metadata_path):
                with open(metadata_path, encoding="utf-8") as handle:
                    metadata = json.load(handle)

            model_id = entry
            model_type = metadata.get("type", "joblib")
            try:
                if model_id == "v25":
                    wrapper = EnsembleV25Wrapper(model_dir, metadata)
                elif model_id == "v13_hybrid":
                    wrapper = V13HybridWrapper(model_dir, metadata)
                elif model_type == "quantum_leap_rule":
                    wrapper = QuantumLeapRuleWrapper(model_dir, metadata)
                elif model_type == "hist_premium_ensemble":
                    wrapper = HistPremiumEnsembleWrapper(model_dir, metadata)
                elif model_type == "keras":
                    wrapper = KerasModelWrapper(model_dir, metadata)
                else:
                    wrapper = JoblibModelWrapper(model_dir, metadata)
                cls._register(model_id, wrapper)
            except Exception as exc:
                print(f"[ModelRegistry] 모델 로드 오류 ({model_id}): {exc}")

    @classmethod
    def _register(cls, model_id, wrapper):
        cls._models[model_id] = wrapper
        unservable = unservable_features(wrapper.get_serving_columns())
        if unservable:
            # 등록 자체는 막지 않습니다. 모델 하나 때문에 서버가 못 뜨면 안 됩니다.
            # 실제 예측은 prepare_input_frame 이 거부하므로 조용히 넘어가지 않습니다.
            print(
                f"[ModelRegistry] 배포 불가 경고: {model_id} 가 요구하는 특징을 "
                f"features.py 가 만들지 못합니다: {unservable}"
            )
        print(f"[ModelRegistry] 규격화 모델 등록됨: {model_id}")

    @classmethod
    def verify_servable_features(cls):
        """등록된 모델별로 서빙 불가 특징을 돌려줍니다. 전부 빈 목록이어야 합니다.

        신규 모델 배포 전 게이트로 씁니다. 값이 있으면 그 모델은 해당 특징을
        기본값으로 채운 채 예측하게 되므로 배포해서는 안 됩니다.
        """
        cls._sync_registry()
        return {
            model_id: unservable_features(wrapper.get_serving_columns())
            for model_id, wrapper in cls._models.items()
        }

    @classmethod
    def load_all_models(cls):
        cls._models = {}
        cls.discover_models()
        return len(cls._models)

    @classmethod
    def available_models(cls):
        cls._sync_registry()
        return sorted(cls._models.keys())

    @classmethod
    def get_model(cls, model_id):
        resolved_id = _resolve_model_id(model_id)
        cls._sync_registry()
        if resolved_id not in cls._models:
            cls._sync_registry(force=True)
        return cls._models.get(resolved_id)

    @classmethod
    def list_models_info(cls):
        cls._sync_registry()
        ordered = sorted(
            cls._models.items(),
            key=lambda item: (item[0] != "v25", item[0]),
        )
        return [
            {
                "id": model_id,
                "name": wrapper.get_display_name(),
                "description": wrapper.metadata.get("description", "분석 엔진"),
                "version": wrapper.metadata.get("version", "1.0"),
                "type": wrapper.metadata.get("type", "joblib"),
                "specialization": wrapper.metadata.get("specialization", ""),
                "specialized_categories": wrapper.metadata.get("specialized_categories", []),
                "required_features": wrapper.metadata.get("required_features", []),
                "training_rows": wrapper.metadata.get("training_rows"),
                "metrics": _load_champion_metrics(wrapper.model_dir),
            }
            for model_id, wrapper in ordered
        ]


def predict_interval(model_id, features_dict):
    """예측 구간 (하단%, 상단%, 명목 피복률) 을 돌려줍니다. 없으면 None 입니다.

    점 추정과 달리 구간은 선택 기능입니다. 구 모델은 분위 아티팩트가 없어
    None 이 나오며, 호출부는 그 경우 구간 없이 응답해야 합니다.
    """
    wrapper = ModelRegistry.get_model(_resolve_model_id(model_id))
    if wrapper is None or not hasattr(wrapper, "predict_interval"):
        return None
    try:
        bounds = wrapper.predict_interval(_prepare_full_frame(features_dict))
    except Exception as exc:
        print(f"[Predictor] 구간 산출 실패 ({model_id}): {exc}")
        return None
    # 구간은 부가 정보입니다. 형태가 어긋나면 점 추정까지 막지 않고 조용히 뺍니다.
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        return None
    try:
        low, high = (_normalize_prediction_rate(value) * 100 for value in bounds)
        coverage = (wrapper.metadata.get("interval") or {}).get("target_coverage")
    except (TypeError, ValueError) as exc:
        print(f"[Predictor] 구간 값이 비정상입니다 ({model_id}): {exc}")
        return None
    return low, high, float(coverage) if coverage is not None else None


def predict_optimal_price(model_id, features_dict):
    requested_id = _resolve_model_id(model_id or _preferred_model_for_features(features_dict))
    preferred_id = _preferred_model_for_features(features_dict)
    candidate_ids = []
    for candidate in (requested_id, preferred_id, "v25", "v13_hybrid"):
        if candidate not in candidate_ids:
            candidate_ids.append(candidate)

    last_error = None
    for candidate_id in candidate_ids:
        wrapper = ModelRegistry.get_model(candidate_id)
        if not wrapper:
            continue

        try:
            custom_df = wrapper.run_preprocess(features_dict)
            df = custom_df if custom_df is not None else _prepare_full_frame(features_dict)
            raw_prediction = wrapper.predict(df)
            return float(_normalize_prediction_rate(raw_prediction))
        except Exception as exc:
            last_error = exc
            print(f"[Predictor] 모델 '{candidate_id}' 추론 실패: {exc}")

    if last_error:
        raise last_error
    raise ValueError(f"모델 '{requested_id}'을 찾을 수 없습니다.")
