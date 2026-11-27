"""권한 설정 자식에게 확정된 ORCA_TERMINAL_HANDLE 을 넘기는지 검증합니다.

런처는 코디네이터 셸에서 기동되므로 부모 환경의 ORCA_TERMINAL_HANDLE 에
코디네이터 핸들이 남아 있을 수 있습니다. spawn_permission_setup 이 그 값을
그대로 상속시키면 자식의 prepare-worker 가 다른 Dispatch 를 건드립니다.
"""

from pathlib import Path


def _fake_popen(captured: dict):
    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return object()

    return fake_popen


def test_child_env_overrides_inherited_handle(tmp_path: Path, monkeypatch):
    import os

    from scripts.orca_worker_launch_common import spawn_permission_setup

    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_inherited_coordinator")
    captured: dict = {}

    spawn_permission_setup(
        "scripts/orca_agy_launch.py",
        "term_worker_target",
        "model_a",
        log_path=tmp_path / "permission_setup.log",
        popen=_fake_popen(captured),
    )

    env = captured["kwargs"].get("env")
    assert env is not None
    assert env["ORCA_TERMINAL_HANDLE"] == "term_worker_target"
    assert env["ORCA_TERMINAL_HANDLE"] != "term_inherited_coordinator"
    assert os.environ["ORCA_TERMINAL_HANDLE"] == "term_inherited_coordinator"


def test_child_env_strips_terminal_argument(tmp_path: Path, monkeypatch):
    import os

    from scripts.orca_worker_launch_common import spawn_permission_setup

    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_inherited_coordinator")
    captured: dict = {}

    spawn_permission_setup(
        "scripts/orca_agy_launch.py",
        "  term_worker_target  ",
        "model_a",
        log_path=tmp_path / "permission_setup.log",
        popen=_fake_popen(captured),
    )

    env = captured["kwargs"]["env"]
    assert env["ORCA_TERMINAL_HANDLE"] == "term_worker_target"
    assert os.environ["ORCA_TERMINAL_HANDLE"] == "term_inherited_coordinator"


def test_child_env_keeps_other_parent_variables(tmp_path: Path, monkeypatch):
    import os

    from scripts.orca_worker_launch_common import spawn_permission_setup

    monkeypatch.setenv("ORCA_PARENT_MARKER_FOR_CHILD", "kept")
    captured: dict = {}

    spawn_permission_setup(
        "scripts/orca_agy_launch.py",
        "term_worker_target",
        "model_a",
        log_path=tmp_path / "permission_setup.log",
        popen=_fake_popen(captured),
    )

    env = captured["kwargs"]["env"]
    assert env["ORCA_PARENT_MARKER_FOR_CHILD"] == os.environ["ORCA_PARENT_MARKER_FOR_CHILD"]
