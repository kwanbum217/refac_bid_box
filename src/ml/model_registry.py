import json
import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Protocol, cast

import pandas as pd

import src.ml.model_wrappers as _wrappers
import src.ml.prediction_api as _pred_api
from src.app.core.config import settings
from src.ml.features import (
    apply_categorical_dtypes,
    build_default_feature_map,
    prepare_features,
    prepare_input_frame,
    unservable_features,
)
from src.ml.model_wrappers import (
    BaseModelWrapper,
    EnsembleV25Wrapper,
    HistPremiumEnsembleWrapper,
    JoblibModelWrapper,
    KerasModelWrapper,
    QuantumLeapRuleWrapper,
    V13HybridWrapper,
)
from src.ml.prediction_api import (
    PredictionOutcome,
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_interval,
    predict_optimal_price,
    predict_optimal_price_batch,
    predict_optimal_price_with_provenance,
)

logger = logging.getLogger(__name__)
latency_logger = logging.getLogger("uvicorn.error")


class _WrappersRuntimeBinding(Protocol):
    _coerce_float: object
    _apply_inference_thread_budget: object
    _prepare_input_frame: object


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 경로 정본은 settings 입니다. 여기서 다시 조립하면 설정을 바꿔도 로더가
# 옛 경로를 보게 되므로, 값은 반드시 설정에서 읽습니다.
MODEL_FILES_ROOT = Path(settings.MODEL_FILES_DIR)

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


def _apply_inference_thread_budget(estimator):
    """서빙 예측 스레드 예산을 n_jobs=1 로 고정합니다.

    sklearn LightGBM 추정기는 predict 시점에 self.n_jobs 를 num_threads 로 읽어
    OpenMP 스레드 팀을 만듭니다. 승격 아티팩트의 -1과 기본값 None은 가용 코어를
    모두 쓰므로,
    단건 추론의 스레드 팀 오버헤드와 동시성 oversubscription 이 생깁니다.
    로드 직후 n_jobs=1 로 덮어 쓰면 이 둘이 사라집니다. 학습 기본값·아티팩트는
    바꾸지 않습니다. n_jobs 를 지원하지 않는 추정기는 그대로 둡니다.
    """
    get_params = getattr(estimator, "get_params", None)
    if get_params is None:
        return
    try:
        params = get_params()
    except (TypeError, ValueError):
        return
    if not isinstance(params, dict) or "n_jobs" not in params:
        return
    set_params = getattr(estimator, "set_params", None)
    if set_params is None:
        return
    set_params(n_jobs=1)


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


def _prepare_input_frame(feature_values, column_order, category_levels=None, *, defaults=None):
    """추론 프레임을 만듭니다. 특징 정의는 features.py 단일 공급원을 따릅니다.

    범주 수준은 학습 때 저장한 목록으로 되살립니다. 이 복원을 빼면 추론 시점의
    범주 코드가 학습 때와 달라져 모델이 조용히 다른 값을 읽습니다.
    구 모델은 메타데이터에 수준이 없으므로 None 이 되어 아무 일도 하지 않습니다.

    defaults 는 서빙 경로가 요청당 한 번 구축한 전체 특징 맵입니다.
    프레임 행이 이미 전체 맵을 실은 경우 같은 맵을 다시 구축하지 않게 합니다.
    """
    frame = prepare_input_frame(feature_values, column_order, defaults=defaults)
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


def _prepare_full_frame(features_dict, full_map=None):
    """모든 특징을 실은 1행 프레임을 만듭니다.

    wrapper 는 받은 프레임을 df.iloc[0].to_dict() 로 되돌린 뒤 자기 컬럼으로
    다시 구성합니다. 여기서 프레임을 구 52컬럼으로 좁히면 그 사이에 제도 특징과
    재발주 이력이 사라지고, wrapper 가 전부 기본값으로 채웁니다. 실측에서
    하한율 87.995% 인 건의 예측이 100.776% 로 나왔습니다.
    원본 키도 남깁니다. 규칙 기반 구 모델이 title / agency_name 을 씁니다.

    full_map 은 호출부가 이미 구축한 전체 특징 맵입니다. 같은 맵을 다시
    구축하지 않고 그대로 프레임에 실으며, wrapper 가 defaults 로 재사용할 수
    있도록 프레임 attrs 에도 담아 내려보냅니다.
    """
    if full_map is None:
        full_map = build_default_feature_map(features_dict)
    frame = pd.DataFrame([{**features_dict, **full_map}])
    frame.attrs["feature_defaults"] = full_map
    return frame


def _resolve_model_id(model_id):
    normalized = (model_id or "v25").strip()
    return MODEL_ALIASES.get(normalized, normalized)


def _preferred_model_for_features(features_dict):
    category = str(features_dict.get("category") or "").strip()
    if category == "Servc":
        method_class = classify_price_decision_method(features_dict)
        if method_class == PriceDecisionMethod.NON_PREARNG:
            raise ValueError(
                "비예가 공고는 예정가격을 작성하지 않는 제도라 낙찰률 기반 투찰가를 산출할 수 없습니다."
            )
    return CATEGORY_DEFAULT_MODELS.get(category, "v25")


class ModelRegistry:
    _models: dict[str, Any] = {}
    _load_lock = threading.RLock()

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
            cls.load_all_models(force=force)

    @classmethod
    def discover_models(cls, registry: dict[str, Any] | None = None):
        registry = cls._models if registry is None else registry
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
                wrapper: BaseModelWrapper
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
                cls._register(model_id, wrapper, registry=registry)
            except Exception as exc:
                print(f"[ModelRegistry] 모델 로드 오류 ({model_id}): {exc}")

    @classmethod
    def _register(cls, model_id, wrapper, registry: dict[str, Any] | None = None):
        registry = cls._models if registry is None else registry
        registry[model_id] = wrapper
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
    def load_all_models(cls, force=False):
        """모델을 한 번만 적재하고, 완성된 레지스트리만 공개합니다."""
        with cls._load_lock:
            disk_model_ids = cls._discover_model_ids_on_disk()
            if not force and disk_model_ids == sorted(cls._models.keys()):
                return len(cls._models)

            candidate: dict[str, Any] = {}
            cls.discover_models(registry=candidate)
            cls._models = candidate
            return len(candidate)

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


# 런타임 종속성을 model_wrappers 모듈에 연결 (순환 import 방지)
_wrappers_runtime = cast(_WrappersRuntimeBinding, _wrappers)
_wrappers_runtime._coerce_float = _coerce_float
_wrappers_runtime._apply_inference_thread_budget = _apply_inference_thread_budget
_wrappers_runtime._prepare_input_frame = _prepare_input_frame

# 런타임 종속성을 prediction_api 모듈에 연결 (순환 import 방지)
_pred_api.ModelRegistry = ModelRegistry
_pred_api._resolve_model_id = _resolve_model_id
_pred_api._preferred_model_for_features = _preferred_model_for_features
_pred_api._prepare_full_frame = _prepare_full_frame
_pred_api._normalize_prediction_rate = _normalize_prediction_rate

__all__ = [
    "CATEGORY_DEFAULT_MODELS",
    "DEFAULT_RATIO_MAX",
    "DEFAULT_RATIO_MIN",
    "MODEL_ALIASES",
    "MODEL_FILES_ROOT",
    "PROJECT_ROOT",
    "BaseModelWrapper",
    "EnsembleV25Wrapper",
    "HistPremiumEnsembleWrapper",
    "JoblibModelWrapper",
    "KerasModelWrapper",
    "ModelRegistry",
    "PredictionOutcome",
    "PriceDecisionMethod",
    "QuantumLeapRuleWrapper",
    "V13HybridWrapper",
    "_apply_inference_thread_budget",
    "_coerce_float",
    "_load_champion_metrics",
    "_normalize_prediction_rate",
    "_preferred_model_for_features",
    "_prepare_features",
    "_prepare_full_frame",
    "_prepare_input_frame",
    "_resolve_model_id",
    "classify_price_decision_method",
    "predict_interval",
    "predict_optimal_price",
    "predict_optimal_price_batch",
    "predict_optimal_price_with_provenance",
]
