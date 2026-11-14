"""
tests/test_home_accuracy_redis_race_20261114.py

메인 '모델 정확도' 의 실측값 우선순위와 RedisConnection 동시 호출 경쟁을 고정합니다.

1. 사이드카 실측값이 서빙 버전과 일치하면 그 rmse 를 화면에 쓴다.
2. 사이드카 version 불일치·파일 없음·JSON 오류면 metadata.json 의 source_metrics 를 쓴다.
3. 둘 다 없으면 available=False 이다.
4. 연결 시도 중 동시 호출자는 None 이 아니라 같은 클라이언트를 받는다.
5. 연결 실패 뒤 backoff 안의 호출은 여전히 None 이다.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from src.app.core.cache import RedisConnection
from src.app.services import home_summary

MODEL_NAME = "servc_institution_v1"
PROMOTED_AT = "2026-01-02T03:04:05"


def _write_serving(root: Path, *, version: str, rmse: float) -> None:
    slot = root / MODEL_NAME
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "metadata.json").write_text(
        json.dumps(
            {
                "version": version,
                "source_metrics": {"rmse": rmse},
                "promoted_at": PROMOTED_AT,
            }
        ),
        encoding="utf-8",
    )


def _write_sidecar(root: Path, *, version: str, rmse: float) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{MODEL_NAME}.json").write_text(
        json.dumps({"version": version, "metrics": {"rmse": rmse}}),
        encoding="utf-8",
    )


def test_accuracy_prefers_matching_sidecar(tmp_path):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_serving(serving, version="v_same", rmse=2.7003)
    _write_sidecar(metrics, version="v_same", rmse=2.5635886886913912)

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)

    assert accuracy["available"] is True
    assert accuracy["rmse_display"] == "2.56"
    assert accuracy["promoted_date"] == "2026-01-02"


@pytest.mark.parametrize("case", ["version_mismatch", "missing", "broken_json"])
def test_accuracy_falls_back_to_source_metrics(tmp_path, case):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_serving(serving, version="v_serving", rmse=2.7003)

    if case == "version_mismatch":
        _write_sidecar(metrics, version="v_stale", rmse=1.0)
    elif case == "broken_json":
        metrics.mkdir(parents=True, exist_ok=True)
        (metrics / f"{MODEL_NAME}.json").write_text("{not json", encoding="utf-8")

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)

    assert accuracy["available"] is True
    assert accuracy["rmse_display"] == "2.70"


def test_accuracy_unavailable_without_any_metrics(tmp_path):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_serving_root = serving / MODEL_NAME
    _write_serving_root.mkdir(parents=True, exist_ok=True)
    (_write_serving_root / "metadata.json").write_text(
        json.dumps({"version": "v_serving", "promoted_at": PROMOTED_AT}),
        encoding="utf-8",
    )

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)

    assert accuracy["available"] is False
    assert accuracy["rmse_display"] is None


class SlowPingClient:
    def __init__(self, entered: threading.Event, release: threading.Event):
        self._entered = entered
        self._release = release

    def ping(self):
        self._entered.set()
        assert self._release.wait(5)
        return True


def _install_redis(monkeypatch, connector) -> None:
    class FakeRedisModule:
        class Redis:
            from_url = staticmethod(connector)

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)


def test_concurrent_client_calls_share_one_connection(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    fake_client = SlowPingClient(entered, release)
    attempts: list[int] = []

    def connector(*_args, **_kwargs):
        attempts.append(1)
        return fake_client

    _install_redis(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=5.0, label="test")

    first_result: list[object] = []
    first = threading.Thread(target=lambda: first_result.append(conn.client()))
    first.start()
    assert entered.wait(5)

    second_result: list[object] = []
    second = threading.Thread(target=lambda: second_result.append(conn.client()))
    second.start()
    # 두 번째 호출자가 잠금에서 대기하는 구간을 확보한 뒤 첫 연결을 완료합니다.
    time.sleep(0.05)
    release.set()

    first.join(5)
    second.join(5)

    assert first_result == [fake_client]
    assert second_result == [fake_client]
    assert attempts == [1]


def test_failed_connection_still_backs_off(monkeypatch):
    attempts: list[int] = []

    def connector(*_args, **_kwargs):
        attempts.append(1)
        raise ConnectionError("Redis 연결 거부")

    _install_redis(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=60.0, label="test")

    assert conn.client() is None
    assert conn.client() is None
    assert attempts == [1]
