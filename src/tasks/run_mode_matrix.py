"""
src/tasks/run_mode_matrix.py

실행 모드별 스텝 순서 (원본 apps/pipelines/services/run_mode_matrix.py 1:1 이식).
"""

from __future__ import annotations

RUN_MODE_STEP_ORDER: dict[str, tuple[str, ...]] = {
    "preflight_only": tuple(),
    "collect_only": ("collect",),
    "kb_only": ("rag",),
    "predict_only": ("predict",),
    "refresh_data": ("collect", "rag", "inspect"),
    "manual_full": ("collect", "rag", "predict", "inspect"),
    "nightly_schedule": ("collect", "rag", "predict", "inspect"),
    "push_deploy": ("inspect",),
}


def get_run_mode_steps(run_mode: str) -> tuple[str, ...]:
    try:
        return RUN_MODE_STEP_ORDER[run_mode]
    except KeyError as exc:
        raise ValueError(f"Unsupported run mode: {run_mode}") from exc


def should_run_step(run_mode: str, step: str) -> bool:
    return step in get_run_mode_steps(run_mode)
