"""
scripts/_strict_json.py

RFC-8259 엄격 준수 JSON 직렬화 및 역직렬화 헬퍼 모듈.

모든 evidence 출력 스크립트가 표준 JSON 규격을 준수하도록
NaN/Inf 부동소수점을 None(null)으로 정규화하고 allow_nan=False로 직렬화합니다.
또한 역직렬화 시 비표준 상수(NaN, Infinity, -Infinity)를 거부합니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TextIO

__all__ = [
    "dump_strict_json",
    "dumps_strict_json",
    "load_strict_json",
    "loads_strict_json",
    "sanitize_nan_to_none",
]


def sanitize_nan_to_none(obj: Any) -> Any:
    """JSON 직렬화 전 NaN/Inf 부동소수점 값을 None(null)으로 재귀 정규화합니다."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_nan_to_none(v) for v in obj]
    return obj


def dump_strict_json(data: Any, **kwargs: Any) -> str:
    """NaN/Inf를 None으로 정규화한 뒤 allow_nan=False로 엄격한 JSON 문자열을 직렬화합니다."""
    sanitized = sanitize_nan_to_none(data)
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("indent", 2)
    kwargs["allow_nan"] = False
    return json.dumps(sanitized, **kwargs)


dumps_strict_json = dump_strict_json


def _reject_non_standard_constant(constant: str) -> None:
    raise ValueError(f"비표준 JSON 상수({constant})는 허용되지 않습니다. RFC-8259 준수 JSON이어야 합니다.")


def load_strict_json(source: Any, **kwargs: Any) -> Any:
    """비표준 상수(NaN, Infinity, -Infinity)를 거부하는 엄격한 JSON 파서입니다."""
    kwargs.setdefault("parse_constant", _reject_non_standard_constant)
    if hasattr(source, "read"):
        return json.load(source, **kwargs)
    if isinstance(source, Path):
        with source.open("r", encoding="utf-8") as f:
            return json.load(f, **kwargs)
    if isinstance(source, (str, bytes, bytearray)):
        return json.loads(source, **kwargs)
    raise TypeError(f"지원되지 않는 source 타입: {type(source)}")


loads_strict_json = load_strict_json
