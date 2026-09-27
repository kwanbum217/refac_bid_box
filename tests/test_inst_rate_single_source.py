"""
src/ml/predictor.py 가 기관 낙찰률 기본값을 src/ml/features.DEFAULT_INST_RATE
단일 공급원으로만 쓰는지 검사하는 재발 방지 테스트.
"""

import ast
from pathlib import Path

import pytest

from src.ml import predictor
from src.ml.features import DEFAULT_INST_RATE
from src.ml.predictor import SingletonPredictor

SRC_DIR = Path("src")

# 0.925 리터럴을 허용하는 유일한 두 선언. DEFAULT_REPEAT_RATE 는 반복 낙찰률이라
# 별개의 개념이며, 이 테스트는 둘이 합쳐지는 것도 잡습니다.
ALLOWED_DECLARATIONS = {
    "src/ml/features.py": {"DEFAULT_INST_RATE"},
    "src/ml/repeat_history.py": {"DEFAULT_REPEAT_RATE"},
}


def _bare_predictor() -> SingletonPredictor:
    return object.__new__(SingletonPredictor)


def test_skip_model_load_falls_back_to_default_inst_rate():
    result = _bare_predictor()._predict_from_features({"presumed_price": 1_000_000})
    assert result["predicted_rate"] == pytest.approx(DEFAULT_INST_RATE * 100.0)


def test_skip_model_load_follows_patched_default_inst_rate(monkeypatch):
    monkeypatch.setattr(predictor, "DEFAULT_INST_RATE", 0.75)
    result = _bare_predictor()._predict_from_features({"presumed_price": 1_000_000})
    assert result["predicted_rate"] == pytest.approx(75.0)


def test_no_other_0_925_literals_in_src():
    for path in sorted(SRC_DIR.rglob("*.py")):
        rel = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed_lines: set[int] = set()
        for stmt in tree.body:
            targets: list[ast.AST] = []
            if isinstance(stmt, ast.Assign):
                targets = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ALLOWED_DECLARATIONS.get(
                    rel, set()
                ):
                    allowed_lines.add(stmt.lineno)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, float)
                and (node.value == 0.925)
            ):
                assert node.lineno in allowed_lines, (
                    f"{rel}:{node.lineno} 에 허용 목록 밖의 0.925 리터럴이 있습니다. "
                    "src/ml/features.DEFAULT_INST_RATE 를 사용하십시오."
                )
