"""Chromium 가용성 판정 로직 회귀 테스트.

tests/e2e/conftest.py 의 판정 로직을 실제 브라우저를 띄우지 않고 검증한다.
부하 상황에서 판정 제한 시간 초과로 e2e 전체가 skip 되는 결함의 재발을 막는다.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).parent / "e2e" / "conftest.py"
ENV_VAR = "E2E_BROWSER_PROBE_TIMEOUT"
DEFAULT_TIMEOUT = 30.0


def _load_conftest():
    spec = importlib.util.spec_from_file_location("e2e_conftest_under_test", CONFTEST_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conftest_module(monkeypatch: pytest.MonkeyPatch):
    module = _load_conftest()
    monkeypatch.setattr(module, "_CHROMIUM_AVAILABLE", None)
    monkeypatch.setattr(module, "_CHROMIUM_LAST_FAILURE", None)
    monkeypatch.delenv(ENV_VAR, raising=False)
    return module


class TestResolveProbeTimeout:
    def test_환경변수가_없으면_기본값(self, conftest_module, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert conftest_module._resolve_probe_timeout() == DEFAULT_TIMEOUT

    def test_환경변수가_양의_실수면_그_값(self, conftest_module, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(ENV_VAR, "12.5")
        assert conftest_module._resolve_probe_timeout() == 12.5

    def test_환경변수가_음수나_비수면_기본값(
        self, conftest_module, monkeypatch: pytest.MonkeyPatch
    ):
        for bad in ("-1", "0", "abc", ""):
            monkeypatch.setenv(ENV_VAR, bad)
            assert conftest_module._resolve_probe_timeout() == DEFAULT_TIMEOUT


class TestProbeRetry:
    def test_첫_실패_두번째_성공이면_True(self, conftest_module, monkeypatch: pytest.MonkeyPatch):
        calls: list[int] = []

        def fake_probe() -> bool:
            calls.append(len(calls) + 1)
            return len(calls) > 1

        monkeypatch.setattr(conftest_module, "_probe_chromium", fake_probe)
        assert conftest_module.is_chromium_available() is True
        assert len(calls) == 2
        assert conftest_module._CHROMIUM_LAST_FAILURE is None

    def test_두번_모두_실패하면_False_캐시(self, conftest_module, monkeypatch: pytest.MonkeyPatch):
        calls: list[int] = []

        def fake_probe() -> bool:
            calls.append(len(calls) + 1)
            return False

        monkeypatch.setattr(conftest_module, "_probe_chromium", fake_probe)
        assert conftest_module.is_chromium_available() is False
        assert len(calls) == 2
        assert conftest_module._CHROMIUM_LAST_FAILURE == "failed"
        assert conftest_module.is_chromium_available() is False
        assert len(calls) == 2

    def test_시간_초과는_재시도_후_타임아웃으로_캐시(
        self, conftest_module, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ENV_VAR, "0.05")
        calls: list[int] = []

        def slow_probe() -> bool:
            calls.append(len(calls) + 1)
            time.sleep(0.3)
            return True

        monkeypatch.setattr(conftest_module, "_probe_chromium", slow_probe)
        assert conftest_module.is_chromium_available() is False
        assert len(calls) == 2
        assert conftest_module._CHROMIUM_LAST_FAILURE == "timeout"

    def test_실패_캐시_사유별_skip_사유가_갈린다(
        self, conftest_module, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(conftest_module, "_CHROMIUM_AVAILABLE", False)

        monkeypatch.setattr(conftest_module, "_CHROMIUM_LAST_FAILURE", "timeout")
        assert "판정이 제한 시간" in conftest_module._skip_reason()

        monkeypatch.setattr(conftest_module, "_CHROMIUM_LAST_FAILURE", "failed")
        assert "판정이 실패" in conftest_module._skip_reason()
