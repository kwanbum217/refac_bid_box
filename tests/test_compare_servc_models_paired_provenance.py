import pandas as pd

from scripts.compare_servc_models_paired import (
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
    else:
        data["provenance_valid"] = [True] * size
    if base_fallbacks is not None:
        data["base_fallback"] = base_fallbacks
    else:
        data["base_fallback"] = [False] * size
    if chal_fallbacks is not None:
        data["chal_fallback"] = chal_fallbacks
    else:
        data["chal_fallback"] = [False] * size
    if same_actual_models is not None:
        data["same_actual_model"] = same_actual_models
    else:
        data["same_actual_model"] = [False] * size
    return pd.DataFrame(data)


def test_normal_distinct_models():
    frame = _sample_frame([80.0, 85.0, 90.0, 95.0, 88.0, 82.0, 87.0, 91.0, 84.0, 86.0])
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 0
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
        # missing model_id, requested_model, fallback_used

    monkeypatch.setattr(
        "scripts.compare_servc_models_paired.predict_price_api",
        lambda req, session: LegacyResponse(),
    )

    res = predict_one(session=None, bid_id=101, model_id="legacy_req")
    assert res["pred"] == 87.5
    assert res["model"] == "LegacyModel"
    assert res["model_id"] == ""
    assert res["requested_model"] == ""
    assert res["fallback_used"] is False
    assert res["missing_provenance"] is True


def test_all_invalid_samples_case():
    frame = _sample_frame(
        actuals=[80.0, 85.0],
        provenance_valids=[False, False],
        base_fallbacks=[True, True],
        chal_fallbacks=[True, True],
        same_actual_models=[True, True],
    )

    # Should not raise ValueError anymore, should return valid_pairs = 0 and fail_closed
    eval_res = evaluate_paired_samples(frame)
    assert eval_res["valid_pairs"] == 0
    assert eval_res["fail_closed"] is True
    assert eval_res["invalid_provenance_count"] == 2


def test_no_sensitive_info_exposure_on_api_error(monkeypatch, capsys):
    def _mock_raise_sensitive(*args, **kwargs):
        raise RuntimeError(
            "Secret_URL: http://internal-db:3306, password=secret123, token=JWT12345"
        )

    monkeypatch.setattr(
        "scripts.compare_servc_models_paired.predict_price_api",
        _mock_raise_sensitive,
    )

    res = predict_one(session=None, bid_id=101, model_id="some_model")
    assert res is None

    captured = capsys.readouterr()
    assert "Secret_URL" not in captured.out
    assert "Secret_URL" not in captured.err
    assert "password" not in captured.out
    assert "token" not in captured.out


def test_main_zero_valid_or_empty_scope_nonzero_exit(monkeypatch):
    import sys

    from scripts.compare_servc_models_paired import main

    # Mock collect to return dummy data with an out-of-bounds actual rate
    def _mock_collect(*args, **kwargs):
        return pd.DataFrame([{"bid_id": 1, "actual_rate": 999.0}])  # Scope will be empty

    monkeypatch.setattr("scripts.compare_servc_models_paired.collect", _mock_collect)

    class DummySession:
        def close(self):
            pass

    monkeypatch.setattr("scripts.compare_servc_models_paired.SessionLocal", DummySession)

    def _mock_predict_one(*args, **kwargs):
        return {
            "pred": 80.0,
            "model": "model",
            "low": 75.0,
            "high": 85.0,
            "model_id": "model_id_" + kwargs.get("model_id", args[2]),
            "requested_model": "model_id_" + kwargs.get("model_id", args[2]),
            "fallback_used": False,
            "missing_provenance": False,
        }

    monkeypatch.setattr("scripts.compare_servc_models_paired.predict_one", _mock_predict_one)
    monkeypatch.setattr(sys, "argv", ["script", "--base", "a", "--challenger", "b"])

    exit_code = main()
    assert exit_code == 1
