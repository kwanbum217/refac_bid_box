import pandas as pd
import pytest

from scripts.compare_servc_models_paired import (
    _sanitize_fallback_reason,
    evaluate_paired_samples,
    predict_one,
)


def _sample_frame(
    actuals: list[float],
    provenance_valids: list[bool] | None = None,
    base_fallbacks: list[bool] | None = None,
    chal_fallbacks: list[bool] | None = None,
    same_actual_models: list[bool] | None = None,
) -> pd.DataFrame:
    size = len(actuals)
    base_errs = [1.5, 1.6, 1.4, 1.7, 1.5, 1.6, 1.4, 1.7, 1.5, 1.6][:size]
    chal_errs = [0.2, 0.5, 0.3, 0.4, 0.2, 0.5, 0.3, 0.4, 0.2, 0.5][:size]
    data = {
        "actual": actuals,
        "base_err": base_errs,
        "chal_err": chal_errs,
        "base_width": [2.0] * size,
        "chal_width": [1.8] * size,
        "base_covered": [True] * size,
        "chal_covered": [True] * size,
    }
    if provenance_valids is not None:
        data["provenance_valid"] = provenance_valids
    if base_fallbacks is not None:
        data["base_fallback"] = base_fallbacks
    if chal_fallbacks is not None:
        data["chal_fallback"] = chal_fallbacks
    if same_actual_models is not None:
        data["same_actual_model"] = same_actual_models
    return pd.DataFrame(data)


def test_normal_distinct_models():
    frame = _sample_frame([80.0, 85.0, 90.0, 95.0, 88.0, 82.0, 87.0, 91.0, 84.0, 86.0])
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 0
    assert eval_res["invalid_provenance_ratio"] == 0.0
    assert eval_res["fail_closed"] is False
    assert eval_res["decision"]["verdict"] == "challenger 우세"


def test_one_arm_fallback():
    frame = _sample_frame(
        actuals=[80.0, 85.0, 90.0, 95.0],
        provenance_valids=[True, True, True, False],
        base_fallbacks=[False, False, False, False],
        chal_fallbacks=[False, False, False, True],
        same_actual_models=[False, False, False, False],
    )
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 1
    assert eval_res["chal_fallback_count"] == 1
    assert eval_res["fail_closed"] is True
    assert eval_res["decision"]["verdict"] == "판정 불가 (대체 모델 발생)"
    assert eval_res["decision"]["n"] == 3


def test_both_arms_same_actual_model():
    frame = _sample_frame(
        actuals=[80.0, 85.0, 90.0],
        provenance_valids=[False, False, True],
        base_fallbacks=[True, True, False],
        chal_fallbacks=[True, True, False],
        same_actual_models=[True, True, False],
    )
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 2
    assert eval_res["same_actual_model_count"] == 2
    assert eval_res["fail_closed"] is True
    assert eval_res["decision"]["verdict"] == "판정 불가 (대체 모델 발생)"


def test_missing_response_fields_legacy(monkeypatch):
    class LegacyResponse:
        prediction_rate = 87.5
        model_name = "LegacyModel"
        rate_low = 85.0
        rate_high = 90.0

    monkeypatch.setattr(
        "scripts.compare_servc_models_paired.predict_price_api",
        lambda req, session: LegacyResponse(),
    )

    res = predict_one(session=None, bid_id=101, model_id="legacy_req")
    assert res["pred"] == 87.5
    assert res["model"] == "LegacyModel"
    assert res["model_id"] == "LegacyModel"
    assert res["requested_model"] == "legacy_req"
    assert res["fallback_used"] is False
    assert res["fallback_reason"] is None


def test_all_invalid_samples_case():
    frame = _sample_frame(
        actuals=[80.0, 85.0],
        provenance_valids=[False, False],
        base_fallbacks=[True, True],
        chal_fallbacks=[True, True],
        same_actual_models=[True, True],
    )
    with pytest.raises(ValueError, match="정상 출처"):
        evaluate_paired_samples(frame)


def test_sanitize_fallback_reason():
    raw_traceback = (
        "Traceback (most recent call last):\n"
        '  File "/internal/secret/path/model_loader.py", line 42, in load\n'
        "ValueError: Model weights file missing at /secret/path/weights.bin"
    )
    sanitized = _sanitize_fallback_reason(raw_traceback)
    assert "/secret/path" not in sanitized
    assert "Traceback Exception" in sanitized or "Traceback" in sanitized

    raw_val_error = "ValueError: Model failed to converge after 100 iterations"
    sanitized_val = _sanitize_fallback_reason(raw_val_error)
    assert sanitized_val == "ValueError"
