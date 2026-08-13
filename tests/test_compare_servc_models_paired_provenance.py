import pandas as pd

from scripts.compare_servc_models_paired import (
    EXCLUSION_CATEGORIES,
    classify_pair,
    evaluate_paired_samples,
    predict_one,
    print_paired_evaluation,
)


def _sample_frame(
    actuals: list[float],
    base_fallbacks: list[bool] | None = None,
    challenger_fallbacks: list[bool] | None = None,
    same_actual_models: list[bool] | None = None,
    missing_provenances: list[bool] | None = None,
) -> pd.DataFrame:
    size = len(actuals)
    base_errs = [1.5, 1.6, 1.4, 1.7, 1.5, 1.6, 1.4, 1.7, 1.5, 1.6][:size]
    chal_errs = [0.2, 0.5, 0.3, 0.4, 0.2, 0.5, 0.3, 0.4, 0.2, 0.5][:size]
    return pd.DataFrame(
        {
            "actual": actuals,
            "base_err": base_errs,
            "chal_err": chal_errs,
            "base_width": [2.0] * size,
            "chal_width": [1.8] * size,
            "base_covered": [True] * size,
            "chal_covered": [True] * size,
            "base_fallback": base_fallbacks or [False] * size,
            "challenger_fallback": challenger_fallbacks or [False] * size,
            "same_actual_model": same_actual_models or [False] * size,
            "missing_provenance": missing_provenances or [False] * size,
        }
    )


def test_normal_distinct_models():
    frame = _sample_frame([80.0, 85.0, 90.0, 95.0, 88.0, 82.0, 87.0, 91.0, 84.0, 86.0])
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 0
    assert eval_res["fail_closed"] is False
    assert eval_res["decision"]["verdict"] == "challenger 우세"


def test_one_arm_fallback():
    frame = _sample_frame(
        actuals=[80.0, 85.0, 90.0, 95.0],
        base_fallbacks=[False, False, False, False],
        challenger_fallbacks=[False, False, False, True],
        same_actual_models=[False, False, False, False],
    )
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["invalid_provenance_count"] == 1
    assert eval_res["challenger_fallback_count"] == 1
    assert eval_res["fail_closed"] is True
    assert eval_res["decision"]["verdict"] == "판정 불가 (대체 모델 발생)"
    assert eval_res["decision"]["n"] == 3


def test_both_arms_same_actual_model():
    frame = _sample_frame(
        actuals=[80.0, 85.0, 90.0],
        base_fallbacks=[True, True, False],
        challenger_fallbacks=[True, True, False],
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
        base_fallbacks=[True, True],
        challenger_fallbacks=[True, True],
        same_actual_models=[True, True],
    )

    # ValueError 를 내지 않고 유효 쌍 0건과 fail_closed 를 돌려주어야 합니다.
    eval_res = evaluate_paired_samples(frame)
    assert eval_res["valid_pairs"] == 0
    assert eval_res["fail_closed"] is True
    assert eval_res["invalid_provenance_count"] == 2


def test_frame_without_provenance_columns_is_fail_closed():
    frame = _sample_frame([80.0, 85.0]).drop(
        columns=["base_fallback", "challenger_fallback", "same_actual_model"]
    )
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["valid_pairs"] == 0
    assert eval_res["fail_closed"] is True


def test_missing_provenance_alone_blocks_promotion():
    frame = _sample_frame(
        actuals=[80.0, 85.0, 90.0],
        missing_provenances=[False, False, True],
    )
    eval_res = evaluate_paired_samples(frame)

    assert eval_res["exclusion_counts"]["missing_provenance"] == 1
    assert eval_res["valid_pairs"] == 2
    assert eval_res["fail_closed"] is True


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


def _arm_response(model_id: str, **overrides) -> dict:
    payload = {
        "pred": 80.0,
        "model": "model",
        "low": 75.0,
        "high": 85.0,
        "model_id": model_id,
        "requested_model": model_id,
        "fallback_used": False,
        "missing_provenance": False,
    }
    payload.update(overrides)
    return payload


def _run_main(monkeypatch, actual_rates: list[float], predict_one_impl):
    """collect/세션/예측을 대체해 main 을 실행하고 종료 코드를 돌려줍니다."""
    import sys

    from scripts.compare_servc_models_paired import main

    frame = pd.DataFrame(
        [{"bid_id": i + 1, "actual_rate": rate} for i, rate in enumerate(actual_rates)]
    )
    monkeypatch.setattr("scripts.compare_servc_models_paired.collect", lambda *a, **k: frame.copy())

    class DummySession:
        def close(self):
            pass

    monkeypatch.setattr("scripts.compare_servc_models_paired.SessionLocal", DummySession)
    if predict_one_impl is not None:
        monkeypatch.setattr("scripts.compare_servc_models_paired.predict_one", predict_one_impl)
    monkeypatch.setattr(sys, "argv", ["script", "--base", "a", "--challenger", "b"])
    return main()


def test_main_zero_valid_or_empty_scope_nonzero_exit(monkeypatch):
    # 학습 범위 밖 표본만 있으면 판정 범위가 비므로 종료 코드는 1 이어야 합니다.
    def _mock_predict_one(session, bid_id, model_id):
        return _arm_response(f"model_id_{model_id}")

    assert _run_main(monkeypatch, [999.0], _mock_predict_one) == 1


def test_main_returns_zero_only_when_all_pairs_are_clean(monkeypatch):
    def _mock_predict_one(session, bid_id, model_id):
        return _arm_response(f"model_id_{model_id}")

    assert _run_main(monkeypatch, [80.0, 85.0, 90.0, 95.0], _mock_predict_one) == 0


def test_main_blocks_promotion_on_partial_fallback(monkeypatch, capsys):
    # 4쌍 중 1쌍만 challenger 대체가 나도 승격은 차단되어야 합니다.
    def _mock_predict_one(session, bid_id, model_id):
        if bid_id == 2 and model_id == "b":
            return _arm_response("model_id_a", requested_model="model_id_b", fallback_used=True)
        return _arm_response(f"model_id_{model_id}")

    exit_code = _run_main(monkeypatch, [80.0, 85.0, 90.0, 95.0], _mock_predict_one)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "challenger_fallback: 1건 (25.0%)" in output
    assert "판정 불가 (대체 모델 발생)" in output


def test_main_blocks_promotion_on_partial_api_error(monkeypatch, capsys):
    def _mock_predict_one(session, bid_id, model_id):
        if bid_id == 3:
            return None
        return _arm_response(f"model_id_{model_id}")

    exit_code = _run_main(monkeypatch, [80.0, 85.0, 90.0, 95.0], _mock_predict_one)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "api_error: 1건 (25.0%)" in output
    assert "판정 불가 (대체 모델 발생)" in output


def test_main_all_api_errors_reports_counts_and_exits_nonzero(monkeypatch, capsys):
    exit_code = _run_main(monkeypatch, [80.0, 85.0, 90.0], lambda *a, **k: None)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "요청 쌍: 3건" in output
    assert "완전 쌍(Complete): 0건 (0.0%)" in output
    assert "유효 쌍(Valid): 0건 (0.0%)" in output
    assert "api_error: 3건 (100.0%)" in output
    assert "판정 불가 (대체 모델 발생)" in output


def test_main_output_exposes_only_fixed_categories(monkeypatch, capsys):
    sensitive = "/opt/secret/model.bin password=secret123 token=JWT12345"

    def _mock_predict_price_api(request, session):
        raise RuntimeError(sensitive)

    monkeypatch.setattr(
        "scripts.compare_servc_models_paired.predict_price_api", _mock_predict_price_api
    )
    exit_code = _run_main(monkeypatch, [80.0, 85.0], None)
    captured = capsys.readouterr()

    assert exit_code == 1
    for stream in (captured.out, captured.err):
        assert sensitive not in stream
        assert "secret123" not in stream
        assert "JWT12345" not in stream
        assert "Traceback" not in stream
    for category in EXCLUSION_CATEGORIES:
        assert f"{category}:" in captured.out


def test_verdict_is_printed_once(capsys):
    frame = _sample_frame([80.0, 85.0, 90.0, 95.0])
    print_paired_evaluation(evaluate_paired_samples(frame))
    output = capsys.readouterr().out

    verdict_lines = [line for line in output.splitlines() if line.startswith("최종 판정")]
    assert len(verdict_lines) == 1
    assert "전량과 범위 내 판정이 같습니다" not in output


def test_predict_one_rejects_non_string_model_id(monkeypatch):
    _patch_response(monkeypatch, model_id=12345, requested_model="req", fallback_used=False)

    res = predict_one(session=None, bid_id=1, model_id="req")
    assert res["missing_provenance"] is True
    assert res["model_id"] == ""


def test_predict_one_rejects_blank_model_id(monkeypatch):
    _patch_response(monkeypatch, model_id="   ", requested_model="req", fallback_used=False)

    res = predict_one(session=None, bid_id=1, model_id="req")
    assert res["missing_provenance"] is True
    assert res["model_id"] == ""


def test_predict_one_rejects_non_bool_fallback_used(monkeypatch):
    # 1 은 truthy 이지만 bool 이 아니므로 출처 계약 위반입니다.
    _patch_response(monkeypatch, model_id="m", requested_model="req", fallback_used=1)

    res = predict_one(session=None, bid_id=1, model_id="req")
    assert res["missing_provenance"] is True
    assert res["fallback_used"] is False


def test_predict_one_accepts_valid_provenance(monkeypatch):
    _patch_response(monkeypatch, model_id=" m ", requested_model="m", fallback_used=False)

    res = predict_one(session=None, bid_id=1, model_id="m")
    assert res["missing_provenance"] is False
    assert res["model_id"] == "m"
    assert res["fallback_used"] is False


def _patch_response(monkeypatch, **fields):
    class Response:
        prediction_rate = 87.5
        model_name = "Model"
        rate_low = 85.0
        rate_high = 90.0

    for key, value in fields.items():
        setattr(Response, key, value)
    monkeypatch.setattr(
        "scripts.compare_servc_models_paired.predict_price_api",
        lambda req, session: Response(),
    )


def test_classify_pair_does_not_double_count_missing_provenance():
    missing_arm = {"missing_provenance": True, "model_id": "", "requested_model": ""}
    flags = classify_pair(missing_arm, dict(missing_arm))

    assert flags == {
        "missing_provenance": True,
        "base_fallback": False,
        "challenger_fallback": False,
        "same_actual_model": False,
    }


def test_classify_pair_detects_same_actual_model():
    arm = {
        "missing_provenance": False,
        "model_id": "champion",
        "requested_model": "champion",
        "fallback_used": False,
    }
    challenger = {
        "missing_provenance": False,
        "model_id": "champion",
        "requested_model": "challenger",
        "fallback_used": True,
    }
    flags = classify_pair(arm, challenger)

    assert flags["same_actual_model"] is True
    assert flags["challenger_fallback"] is True
    assert flags["base_fallback"] is False
