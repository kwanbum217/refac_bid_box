import warnings

from sklearn.exceptions import InconsistentVersionWarning

from scripts.verify_model_compatibility import validate_model_compatibility


class CompatibleRegistry:
    @classmethod
    def expected_model_ids(cls):
        return ["model"]

    @classmethod
    def load_all_models(cls):
        return 1

    @classmethod
    def available_models(cls):
        return ["model"]

    @classmethod
    def verify_servable_features(cls):
        return {"model": []}


class VersionMismatchRegistry(CompatibleRegistry):
    @classmethod
    def load_all_models(cls):
        warnings.warn(
            InconsistentVersionWarning(
                estimator_name="Estimator",
                current_sklearn_version="1.8.0",
                original_sklearn_version="1.7.0",
            ),
            stacklevel=2,
        )
        return 1


class UnservableRegistry(CompatibleRegistry):
    @classmethod
    def verify_servable_features(cls):
        return {"model": ["unknown_feature"]}


def test_model_compatibility_accepts_matching_runtime_and_features():
    assert validate_model_compatibility(CompatibleRegistry) == (True, [])


def test_model_compatibility_rejects_serialization_version_mismatch():
    passed, messages = validate_model_compatibility(VersionMismatchRegistry)

    assert passed is False
    assert messages == ["scikit-learn 직렬화 버전 불일치 1건"]


def test_model_compatibility_rejects_unservable_features():
    passed, messages = validate_model_compatibility(UnservableRegistry)

    assert passed is False
    assert messages == ["서빙 불가 특징: model=unknown_feature"]


class PartiallyLoadedRegistry(CompatibleRegistry):
    @classmethod
    def expected_model_ids(cls):
        return ["model", "missing"]


def test_model_compatibility_rejects_partially_loaded_registry():
    passed, messages = validate_model_compatibility(PartiallyLoadedRegistry)

    assert passed is False
    assert messages == ["모델 로드 실패: missing"]
