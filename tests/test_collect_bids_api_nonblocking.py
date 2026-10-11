"""
tests/test_collect_bids_api_nonblocking.py

G2B 수집 엔드포인트가 이벤트 루프를 막지 않는지 검증합니다.

collect_bids 는 동기 Session 으로 DB 를 쓰는 경로를 asyncio.to_thread 로
오프로드하지만, 호출 자체와 실패 분기 롤백은 동기입니다. 엔드포인트를 동기 def 로
두어 FastAPI 가 스레드풀에서 실행해야 요청 루프가 멈추지 않습니다. 이 테스트는
수집이 요청 루프가 아닌 스레드에서 돌고, 그 동안 루프가 계속 tick 하는지
기록으로 확인합니다.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from src.app.api.v1 import bids as bids_api
from src.app.main import app


@pytest.mark.asyncio
async def test_collect_endpoint_runs_collection_off_the_request_loop(isolated_db):
    seen: dict[str, object] = {}

    async def fake_collect(db, **kwargs):
        seen["thread"] = threading.current_thread()
        seen["kwargs"] = kwargs
        time.sleep(0.2)
        return {"status": "success", "total_records": 3}

    app.dependency_overrides[bids_api.require_current_user] = lambda: SimpleNamespace(
        id=1, is_staff=True, is_superuser=True
    )

    ticks = 0
    stop = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    hb_task = asyncio.create_task(heartbeat())
    try:
        with patch("src.app.services.collector_service.collect_bids", fake_collect):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/v1/bids/collect")
    finally:
        stop.set()
        await hb_task
        app.dependency_overrides.pop(bids_api.require_current_user, None)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "total_records": 3}
    assert seen["thread"] is not threading.main_thread()
    assert ticks > 5
