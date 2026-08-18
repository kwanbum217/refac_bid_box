"""tests/test_model_registry_split.py

src/ml/model_registry.py 분할 후 재수출 심볼 동일성(object identity),
신규 모듈 순환 import 방지, 줄 수 제약 및 동작 보존 검증 테스트.
"""

import ast
import inspect
from pathlib import Path

import pytest

from src.ml import model_registry, model_wrappers, prediction_api


def test_model_wrappers_symbol_identity():
    symbols = [
        "BaseModelWrapper",
        "JoblibModelWrapper",
        "KerasModelWrapper",
        "V13HybridWrapper",
        "EnsembleV25Wrapper",
        "QuantumLeapRuleWrapper",
        "HistPremiumEnsembleWrapper",
    ]
    for symbol in symbols:
        reg_obj = getattr(model_registry, symbol)
        mod_obj = getattr(model_wrappers, symbol)
        assert reg_obj is mod_obj, (
            f"심볼 {symbol}의 객체 동일성 검증 실패 (model_registry vs model_wrappers)"
        )


def test_prediction_api_symbol_identity():
    symbols = [
        "PriceDecisionMethod",
        "classify_price_decision_method",
        "PredictionOutcome",
        "predict_interval",
        "predict_optimal_price_with_provenance",
        "predict_optimal_price",
        "predict_optimal_price_batch",
    ]
    for symbol in symbols:
        reg_obj = getattr(model_registry, symbol)
        mod_obj = getattr(prediction_api, symbol)
        assert reg_obj is mod_obj, (
            f"심볼 {symbol}의 객체 동일성 검증 실패 (model_registry vs prediction_api)"
        )


def test_model_registry_class_defined_in_registry():
    """ModelRegistry 클래스가 model_registry.py 에 직접 정의되어 있는지 검증합니다."""
    source_file = inspect.getsourcefile(model_registry.ModelRegistry)
    assert source_file is not None
    assert "model_registry.py" in source_file


def test_no_circular_imports_in_new_modules():
    """신규 2개 분할 모듈이 model_registry 를 import 하지 않는지 AST 레벨 검증."""
    submodules = [
        "src/ml/model_wrappers.py",
        "src/ml/prediction_api.py",
    ]
    for subpath in submodules:
        content = Path(subpath).read_text(encoding="utf-8")
        tree = ast.parse(content, filename=subpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "model_registry" not in alias.name, (
                        f"{subpath} 가 model_registry 를 import 함: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "model_registry" not in node.module, (
                    f"{subpath} 가 model_registry 를 importFrom 함: {node.module}"
                )


def test_module_line_count_limits():
    """분할 후 원본 모듈 600줄 이하 및 신규 2개 모듈 각각 550줄 이하 제약 검증."""
    ml_dir = Path("src/ml")
    registry_lines = len((ml_dir / "model_registry.py").read_text(encoding="utf-8").splitlines())
    assert registry_lines <= 600, f"model_registry.py 줄 수 초과: {registry_lines} > 600"

    wrappers_lines = len((ml_dir / "model_wrappers.py").read_text(encoding="utf-8").splitlines())
    assert wrappers_lines <= 550, f"model_wrappers.py 줄 수 초과: {wrappers_lines} > 550"

    prediction_api_lines = len(
        (ml_dir / "prediction_api.py").read_text(encoding="utf-8").splitlines()
    )
    assert prediction_api_lines <= 550, (
        f"prediction_api.py 줄 수 초과: {prediction_api_lines} > 550"
    )


def test_classify_price_decision_method_behavior():
    """classify_price_decision_method 가 정상 분류하는지 검증."""
    assert (
        prediction_api.classify_price_decision_method({"prearngPrceDcsnMthdNm": "복수예가"})
        == prediction_api.PriceDecisionMethod.MULTI
    )
    assert (
        prediction_api.classify_price_decision_method({"prearngPrceDcsnMthdNm": "단일예가"})
        == prediction_api.PriceDecisionMethod.SINGLE
    )
    assert (
        prediction_api.classify_price_decision_method({"prearngPrceDcsnMthdNm": "비예가"})
        == prediction_api.PriceDecisionMethod.NON_PREARNG
    )
    assert (
        prediction_api.classify_price_decision_method({"prearngPrceDcsnMthdNm": ""})
        == prediction_api.PriceDecisionMethod.MISSING
    )
    assert (
        prediction_api.classify_price_decision_method({"prearngPrceDcsnMthdNm": "알수없음_값"})
        == prediction_api.PriceDecisionMethod.UNKNOWN
    )


def test_predict_optimal_price_with_mock(monkeypatch):
    """predict_optimal_price_with_provenance 동작 보존 검증."""

    class _MockWrapper:
        def run_preprocess(self, features_dict):
            return None

        def predict(self, df):
            return 88.5

    monkeypatch.setattr(
        model_registry.ModelRegistry,
        "get_model",
        lambda model_id: _MockWrapper(),
    )

    outcome = model_registry.predict_optimal_price_with_provenance(
        "v25",
        {"category": "Thng", "presmpt_prce": 10000000},
    )
    assert outcome.predicted_rate == pytest.approx(0.885)
    assert outcome.requested_model == "v25"
    assert outcome.actual_model == "v25"
    assert outcome.fallback_used is False

    # float 계약 검증
    rate = model_registry.predict_optimal_price(
        "v25",
        {"category": "Thng", "presmpt_prce": 10000000},
    )
    assert isinstance(rate, float)
    assert rate == pytest.approx(0.885)


def test_predict_optimal_price_batch_with_mock(monkeypatch):
    """predict_optimal_price_batch 동작 보존 검증."""

    class _MockBatchWrapper:
        def predict_batch(self, frames):
            return [88.5, 89.0]

    monkeypatch.setattr(
        model_registry.ModelRegistry,
        "get_model",
        lambda model_id: _MockBatchWrapper(),
    )

    outcomes = model_registry.predict_optimal_price_batch(
        "quantum_leap_v25_pro",
        [
            {"category": "Thng", "presmpt_prce": 10000000},
            {"category": "Thng", "presmpt_prce": 20000000},
        ],
    )
    assert len(outcomes) == 2
    assert outcomes[0].predicted_rate == pytest.approx(0.885)
    assert outcomes[1].predicted_rate == pytest.approx(0.89)
