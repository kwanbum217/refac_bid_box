"""Dispatch 시 권한 자동 승인 감시기가 반드시 붙는지 검증합니다."""

from __future__ import annotations

import importlib.util
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


def test_start_auto_approve_spawns_watcher(taskctl, monkeypatch):
    captured = {}

    class FakeProcess:
        pass

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(taskctl.subprocess, "Popen", fake_popen)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is True
    assert captured["args"][0] == sys.executable
    assert captured["args"][1].endswith("orca_auto_approve.py")
    assert captured["args"][2] == "term_abc"
    assert captured["kwargs"]["start_new_session"] is True
    assert detail.endswith("term_abc.log")


def test_start_auto_approve_reports_failure_without_raising(taskctl, monkeypatch):
    def fake_popen(args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(taskctl.subprocess, "Popen", fake_popen)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is False
    assert "자동 승인 감시기 기동 실패" in detail


def test_start_auto_approve_reports_missing_script(taskctl, monkeypatch):
    monkeypatch.setattr(taskctl.Path, "exists", lambda self: False)

    started, detail = taskctl.start_auto_approve("term_abc")

    assert started is False
    assert "찾지 못했습니다" in detail
