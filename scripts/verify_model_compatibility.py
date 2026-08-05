#!/usr/bin/env python3
"""등록 모델의 직렬화 버전과 서빙 특징 호환성을 검증합니다."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

from sklearn import __version__ as sklearn_version
from sklearn.exceptions import InconsistentVersionWarning

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ml.model_registry import ModelRegistry  # noqa: E402


def validate_model_compatibility(registry=ModelRegistry) -> tuple[bool, list[str]]:
    messages: list[str] = []
    expected_models = set(registry.expected_model_ids())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", InconsistentVersionWarning)
        loaded = registry.load_all_models()

    version_warnings = [
        str(item.message) for item in caught if isinstance(item.message, InconsistentVersionWarning)
    ]
    if loaded <= 0:
        messages.append("등록된 모델이 없습니다")
    if version_warnings:
        messages.append(f"scikit-learn 직렬화 버전 불일치 {len(version_warnings)}건")

    loaded_models = set(registry.available_models())
    missing_models = sorted(expected_models - loaded_models)
    if missing_models:
        messages.append(f"모델 로드 실패: {', '.join(missing_models)}")

    serving_report = registry.verify_servable_features() if loaded > 0 else {}
    unservable = {model_id: features for model_id, features in serving_report.items() if features}
    if unservable:
        details = ", ".join(
            f"{model_id}={','.join(features)}" for model_id, features in sorted(unservable.items())
        )
        messages.append(f"서빙 불가 특징: {details}")

    return not messages, messages


def main() -> int:
    print(f"scikit-learn 런타임: {sklearn_version}")
    passed, messages = validate_model_compatibility()
    models = ModelRegistry.available_models()
    expected_models = ModelRegistry.expected_model_ids()
    print(
        f"등록 모델: {len(models)}/{len(expected_models)}개 "
        f"({', '.join(models) or '-'})"
    )
    if passed:
        print("모델 직렬화 버전과 서빙 특징 호환성 검증 통과")
        return 0
    for message in messages:
        print(f"FAIL: {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
