"""
tests/test_run_mode_matrix.py

원본 apps/pipelines/tests.py RunModeMatrixTests 이식.
실행 모드별 스텝 순서 계약이 변경되지 않았는지 검증합니다.
"""

import pytest

from src.tasks.run_mode_matrix import get_run_mode_steps, should_run_step


def test_nightly_schedule_includes_prediction_validation():
    assert get_run_mode_steps("nightly_schedule") == ("collect", "rag", "predict", "inspect")
    assert should_run_step("nightly_schedule", "predict")


def test_refresh_data_keeps_lightweight_followup_path():
    assert get_run_mode_steps("refresh_data") == ("collect", "rag", "inspect")
    assert not should_run_step("refresh_data", "predict")


@pytest.mark.parametrize(
    "run_mode, expected_steps",
    [
        ("preflight_only", tuple()),
        ("collect_only", ("collect",)),
        ("kb_only", ("rag",)),
        ("predict_only", ("predict",)),
        ("manual_full", ("collect", "rag", "predict", "inspect")),
        ("nightly_schedule", ("collect", "rag", "predict", "inspect")),
        ("push_deploy", ("inspect",)),
    ],
)
def test_explicit_run_modes_map_to_expected_steps(run_mode, expected_steps):
    assert get_run_mode_steps(run_mode) == expected_steps


def test_unknown_run_mode_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported run mode"):
        get_run_mode_steps("unsupported_mode")


def test_should_run_step_false_for_excluded():
    assert not should_run_step("preflight_only", "collect")
    assert not should_run_step("collect_only", "rag")
    assert not should_run_step("kb_only", "predict")
