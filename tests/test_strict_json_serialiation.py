"""
tests/test_strict_json_serialiation.py

scripts/_strict_json.py 헬퍼의 정규화, 직렬화, 엄격 역직렬화 회귀 테스트.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import pytest

from scripts._strict_json import (
    dump_strict_json,
    dumps_strict_json,
    load_strict_json,
    loads_strict_json,
    sanitize_nan_to_none,
)


def test_sanitize_nan_to_none_scalars():
    assert sanitize_nan_to_none(float("nan")) is None
    assert sanitize_nan_to_none(float("inf")) is None
    assert sanitize_nan_to_none(float("-inf")) is None
    assert sanitize_nan_to_none(0.0) == 0.0
    assert sanitize_nan_to_none(123.456) == 123.456
    assert sanitize_nan_to_none("nan") == "nan"
    assert sanitize_nan_to_none("NaN") == "NaN"
    assert sanitize_nan_to_none(True) is True
    assert sanitize_nan_to_none(False) is False
    assert sanitize_nan_to_none(None) is None
    assert sanitize_nan_to_none(42) == 42


def test_sanitize_nan_to_none_nested_structures():
    raw = {
        "nan_val": float("nan"),
        "inf_val": float("inf"),
        "neg_inf_val": float("-inf"),
        "valid_val": 42.5,
        "nested_list": [1.0, float("nan"), {"inner_inf": float("inf"), "ok": "text"}],
        "nested_tuple": (float("nan"), 2.0, (float("-inf"),)),
    }
    sanitized = sanitize_nan_to_none(raw)

    assert sanitized["nan_val"] is None
    assert sanitized["inf_val"] is None
    assert sanitized["neg_inf_val"] is None
    assert sanitized["valid_val"] == 42.5
    assert sanitized["nested_list"] == [1.0, None, {"inner_inf": None, "ok": "text"}]
    assert sanitized["nested_tuple"] == [None, 2.0, [None]]


def test_dump_strict_json_serialization():
    raw_data = {
        "name": "benchmark_test",
        "p50_ms": 12.3,
        "p95_ms": float("nan"),
        "p99_ms": float("inf"),
        "nested": [1.0, float("-inf"), {"tail": float("nan")}],
    }

    # 기본 allow_nan=False는 표준 라이브러리에서 ValueError 발생
    with pytest.raises(ValueError):
        json.dumps(raw_data, allow_nan=False)

    # dump_strict_json은 정상 직렬화
    serialized = dump_strict_json(raw_data)
    assert "NaN" not in serialized
    assert "Infinity" not in serialized
    assert "-Infinity" not in serialized
    assert "null" in serialized

    # 직렬화 결과를 표준 json.loads로 파싱 가능
    parsed = json.loads(serialized)
    assert parsed["name"] == "benchmark_test"
    assert parsed["p50_ms"] == 12.3
    assert parsed["p95_ms"] is None
    assert parsed["p99_ms"] is None
    assert parsed["nested"] == [1.0, None, {"tail": None}]

    # alias 검증
    assert dumps_strict_json(raw_data) == serialized


def test_dump_strict_json_custom_options():
    raw = {"a": float("nan"), "b": "한글"}
    # compact json (indent=None)
    compact = dump_strict_json(raw, indent=None)
    assert "\n" not in compact
    assert compact == '{"a": null, "b": "한글"}'


def test_load_strict_json_rejects_non_standard_constants():
    # 비표준 부동소수점 상수 거부
    with pytest.raises(ValueError):
        load_strict_json("NaN")

    with pytest.raises(ValueError):
        load_strict_json("Infinity")

    with pytest.raises(ValueError):
        load_strict_json("-Infinity")

    with pytest.raises(ValueError):
        load_strict_json('{"p95": NaN}')

    with pytest.raises(ValueError):
        load_strict_json('{"p95": Infinity}')

    with pytest.raises(ValueError):
        load_strict_json('{"p95": -Infinity}')

    with pytest.raises(ValueError):
        load_strict_json('[1.0, 2.0, NaN]')

    with pytest.raises(ValueError):
        load_strict_json('[1.0, 2.0, Infinity]')

    with pytest.raises(ValueError):
        load_strict_json('[1.0, 2.0, -Infinity]')


def test_load_strict_json_rejects_syntax_errors():
    # 트레일링 콤마 거부
    with pytest.raises(ValueError):
        load_strict_json('{"a": 1,}')

    with pytest.raises(ValueError):
        load_strict_json("[1, 2, ]")

    with pytest.raises(ValueError):
        load_strict_json("{malformed json")


def test_load_strict_json_accepts_valid_payloads():
    valid_json = '{"a": 1, "b": null, "c": [1.5, true, false, "NaN", "Infinity"]}'
    parsed = load_strict_json(valid_json)

    assert parsed["a"] == 1
    assert parsed["b"] is None
    assert parsed["c"] == [1.5, True, False, "NaN", "Infinity"]
    assert loads_strict_json(valid_json) == parsed


def test_load_strict_json_source_types(tmp_path: Path):
    data = {"metric": "latency", "p95": 15.2, "fallback": None}
    serialized = dump_strict_json(data)

    # 1. str
    assert load_strict_json(serialized) == data

    # 2. bytes
    assert load_strict_json(serialized.encode("utf-8")) == data

    # 3. bytearray
    assert load_strict_json(bytearray(serialized.encode("utf-8"))) == data

    # 4. StringIO / file-like
    assert load_strict_json(io.StringIO(serialized)) == data

    # 5. Path
    test_file = tmp_path / "evidence.json"
    test_file.write_text(serialized, encoding="utf-8")
    assert load_strict_json(test_file) == data

    # 6. 잘못된 타입
    with pytest.raises(TypeError):
        load_strict_json(12345)


def test_strict_json_evidence_roundtrip():
    evidence = {
        "status": "success",
        "p50_ms": 50.0,
        "p95_ms": float("nan"),
        "p99_ms": float("inf"),
        "records": [
            {"request_id": 1, "latency_ms": 45.2},
            {"request_id": 2, "latency_ms": float("nan")},
        ],
    }

    dumped = dump_strict_json(evidence)
    loaded = load_strict_json(dumped)

    assert loaded["status"] == "success"
    assert loaded["p50_ms"] == 50.0
    assert loaded["p95_ms"] is None
    assert loaded["p99_ms"] is None
    assert loaded["records"][0]["latency_ms"] == 45.2
    assert loaded["records"][1]["latency_ms"] is None
