"""Dispatch 시 권한 자동 승인 감시기가 반드시 붙고, 터미널별 단일 인스턴스가 보장되는지 검증합니다."""

from __future__ import annotations

import importlib.util
import signal
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "orca_taskctl.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("orca_taskctl_attach", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def taskctl():
    return _load_module()


@pytest.fixture(autouse=True)
def _enable_auto_approve(monkeypatch):
    """이 파일은 부착 동작 자체를 검증하므로 전역 차단 가드를 해제합니다."""
    monkeypatch.delenv("ORCA_DISABLE_AUTO_APPROVE", raising=False)


def test_start_auto_approve_is_disabled_by_env_guard(taskctl, monkeypatch):
    def fail_popen(args, **kwargs):
        raise AssertionError("가드가 걸린 상태에서 프로세스를 띄우면 안 됩니다")

    monkeypatch.setenv("ORCA_DISABLE_AUTO_APPROVE", "1")
    monkeypatch.setattr(taskctl.subprocess, "Popen", fail_popen)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is False
    assert "ORCA_DISABLE_AUTO_APPROVE" in detail


def test_start_auto_approve_spawns_watcher(taskctl, monkeypatch, tmp_path):
    monkeypatch.setattr(taskctl.tempfile, "gettempdir", lambda: str(tmp_path))
    captured = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(taskctl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: False)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is True
    assert captured["args"][0] == sys.executable
    assert captured["args"][1].endswith("orca_auto_approve.py")
    assert captured["args"][2] == "term_abc"
    assert captured["kwargs"]["start_new_session"] is True
    assert detail.endswith("term_abc.log")

    # PID 파일 기록 확인
    pid_path = taskctl.get_watcher_pid_path("term_abc")
    assert pid_path.exists()
    assert taskctl.read_watcher_pid(pid_path) == 12345


def test_start_auto_approve_skips_when_alive_pid_exists(taskctl, monkeypatch, tmp_path):
    """(a) 살아 있는 PID 가 기록된 상태에서 start_auto_approve 를 부르면 Popen 이 호출되지 않음."""
    monkeypatch.setattr(taskctl.tempfile, "gettempdir", lambda: str(tmp_path))

    pid_path = taskctl.get_watcher_pid_path("term_alive")
    taskctl.write_watcher_pid(pid_path, 11111)

    # 11111 PID 가 살아있는 것으로 모킹
    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: pid == 11111)

    def fail_popen(args, **kwargs):
        raise AssertionError("살아 있는 감시기가 있으면 Popen 을 호출하면 안 됩니다")

    monkeypatch.setattr(taskctl.subprocess, "Popen", fail_popen)

    started, detail = taskctl.start_auto_approve("term_alive")

    assert started is True
    assert detail.endswith("term_alive.log")
    # PID 파일이 11111 로 유지되어야 함
    assert taskctl.read_watcher_pid(pid_path) == 11111


def test_start_auto_approve_respawns_when_dead_pid_exists(taskctl, monkeypatch, tmp_path):
    """(b) 죽은 PID 가 기록된 상태에서는 새로 띄우고 PID 파일이 갱신됨."""
    monkeypatch.setattr(taskctl.tempfile, "gettempdir", lambda: str(tmp_path))

    pid_path = taskctl.get_watcher_pid_path("term_dead")
    taskctl.write_watcher_pid(pid_path, 99999)

    # 기존 99999 PID 는 죽은 것으로 모킹
    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: False)

    class FakeProcess:
        pid = 54321

    popen_called = False

    def fake_popen(args, **kwargs):
        nonlocal popen_called
        popen_called = True
        return FakeProcess()

    monkeypatch.setattr(taskctl.subprocess, "Popen", fake_popen)

    started, _ = taskctl.start_auto_approve("term_dead")

    assert started is True
    assert popen_called is True
    # PID 파일이 새 PID 54321 로 갱신되어야 함
    assert taskctl.read_watcher_pid(pid_path) == 54321


def test_start_auto_approve_recovers_from_corrupted_pid_file(taskctl, monkeypatch, tmp_path):
    """(c) 손상된 PID 파일(빈 파일, 비숫자)에서도 예외 없이 새로 띄움."""
    monkeypatch.setattr(taskctl.tempfile, "gettempdir", lambda: str(tmp_path))

    pid_path = taskctl.get_watcher_pid_path("term_corrupt")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("not_a_valid_pid\n", encoding="utf-8")

    class FakeProcess:
        pid = 67890

    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: False)
    monkeypatch.setattr(taskctl.subprocess, "Popen", lambda args, **kwargs: FakeProcess())

    started, _ = taskctl.start_auto_approve("term_corrupt")

    assert started is True
    assert taskctl.read_watcher_pid(pid_path) == 67890


def test_stop_auto_approve_terminates_and_deletes_pid(taskctl, monkeypatch, tmp_path):
    """(d) stop_auto_approve 가 프로세스에 시그널을 보내고 PID 파일을 지움."""
    monkeypatch.setattr(taskctl.tempfile, "gettempdir", lambda: str(tmp_path))

    pid_path = taskctl.get_watcher_pid_path("term_stop")
    taskctl.write_watcher_pid(pid_path, 77777)
    assert pid_path.exists()

    killed_signals = []

    def fake_kill(pid, sig):
        killed_signals.append((pid, sig))

    monkeypatch.setattr(taskctl.os, "kill", fake_kill)
    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: True)

    stopped, _ = taskctl.stop_auto_approve("term_stop")

    assert stopped is True
    assert (77777, signal.SIGTERM) in killed_signals
    assert not pid_path.exists()


def test_pid_pure_helpers(taskctl, tmp_path):
    """PID 보조 순수 함수 단위 검증."""
    test_file = tmp_path / "test.pid"

    # 존재하지 않는 파일
    assert taskctl.read_watcher_pid(test_file) is None

    # 빈 파일
    test_file.write_text("", encoding="utf-8")
    assert taskctl.read_watcher_pid(test_file) is None

    # 숫자가 아닌 파일
    test_file.write_text("invalid", encoding="utf-8")
    assert taskctl.read_watcher_pid(test_file) is None

    # 정상 PID
    taskctl.write_watcher_pid(test_file, 42)
    assert taskctl.read_watcher_pid(test_file) == 42

    # 삭제
    taskctl.remove_watcher_pid(test_file)
    assert not test_file.exists()


def test_start_auto_approve_reports_failure_without_raising(taskctl, monkeypatch):
    def fake_popen(args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(taskctl, "watcher_alive", lambda pid: False)
    monkeypatch.setattr(taskctl.subprocess, "Popen", fake_popen)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is False
    assert "자동 승인 감시기 기동 실패" in detail


def test_start_auto_approve_reports_missing_script(taskctl, monkeypatch):
    monkeypatch.setattr(taskctl.Path, "exists", lambda self: False)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is False
    assert "찾지 못했습니다" in detail
