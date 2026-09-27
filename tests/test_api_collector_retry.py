"""
tests/test_api_collector_retry.py

src/app/services/api_collector.py 의 _make_request_with_retry 재시도 로직을 검증합니다.

- 200 즉시 반환, 429/502/503/504 재시도, 그 밖 상태코드 즉시 실패
- RequestError(연결 오류)는 상태코드와 무관하게 재시도
- 마지막 시도 실패 시 마지막 예외 재발생, get 호출 수 == max_retries
- 재시도 로그에 serviceKey 같은 자격 증명 원문 노출 금지

asyncio.sleep 은 monkeypatch 로 대체해 실제 대기 없이 실행하고,
httpx.Response 의 raise_for_status 를 그대로 사용해 상태코드 예외를 재현합니다.
외부 네트워크 및 실제 조달청 API 호출은 일절 수행하지 않습니다.
"""

from __future__ import annotations

import httpx
import pytest

from src.app.services import api_collector
from src.app.services.api_collector import _make_request_with_retry

MOCK_URL = "https://example.invalid/api"


class FakeClient:
    """client.get 을 미리 정한 응답/예외 순서대로 재현하는 가짜 비동기 클라이언트."""

    def __init__(self, outcomes: list[httpx.Response | Exception]):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def get(self, url: str, params=None, timeout=None) -> httpx.Response:
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("미리 준비한 응답을 모두 소진했습니다")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _request() -> httpx.Request:
    return httpx.Request("GET", MOCK_URL)


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


def _connect_timeout(message: str = "connection refused") -> httpx.ConnectTimeout:
    return httpx.ConnectTimeout(message, request=_request())


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """asyncio.sleep 을 즉시 반환하는 가짜로 대체하고 호출 인자를 기록합니다."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(api_collector.asyncio, "sleep", fake_sleep)
    return recorded


async def test_first_response_200_returns_immediately(sleep_calls):
    """(1) 첫 응답 200 이면 재시도 없이 즉시 반환하고 sleep 은 0회다."""
    client = FakeClient([_status_response(200)])

    resp = await _make_request_with_retry(client, MOCK_URL, params={})

    assert resp.status_code == 200
    assert client.calls == 1
    assert sleep_calls == []


async def test_two_503_then_200_returns_on_third_attempt(sleep_calls):
    """(2) 503 두 번 뒤 200 이면 세 번째 시도에서 반환하고 sleep 인자는 3.0, 6.0 이다."""
    client = FakeClient(
        [
            _status_response(503),
            _status_response(503),
            _status_response(200),
        ]
    )

    resp = await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=5)

    assert resp.status_code == 200
    assert client.calls == 3
    assert sleep_calls == [3.0, 6.0]


@pytest.mark.parametrize("status_code", [429, 502, 503, 504])
async def test_retryable_status_codes_retry_then_succeed(sleep_calls, status_code):
    """(3) 429, 502, 503, 504 는 재시도 대상이며 이후 200 을 반환한다."""
    client = FakeClient(
        [
            _status_response(status_code),
            _status_response(200),
        ]
    )

    resp = await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=5)

    assert resp.status_code == 200
    assert client.calls == 2
    assert sleep_calls == [3.0]


@pytest.mark.parametrize("status_code", [400, 404, 500])
async def test_non_retryable_status_codes_raise_immediately(sleep_calls, status_code):
    """(4) 400, 404, 500 은 재시도 없이 HTTPStatusError 를 즉시 던진다."""
    client = FakeClient([_status_response(status_code)])

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=5)

    assert exc_info.value.response.status_code == status_code
    assert client.calls == 1
    assert sleep_calls == []


async def test_request_error_retries_then_succeeds(sleep_calls):
    """(5) RequestError(예: ConnectTimeout) 뒤 성공하면 200 을 반환한다."""
    client = FakeClient([_connect_timeout(), _status_response(200)])

    resp = await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=5)

    assert resp.status_code == 200
    assert client.calls == 2
    assert sleep_calls == [3.0]


async def test_persistent_status_error_raises_last_error_after_max_retries(sleep_calls):
    """(6) 재시도 대상 상태 오류가 max_retries 번 계속되면 마지막 예외를 던지고 get 호출 수는 max_retries 다."""
    client = FakeClient(
        [
            _status_response(503),
            _status_response(503),
            _status_response(503),
        ]
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=3)

    assert exc_info.value.response.status_code == 503
    assert client.calls == 3
    assert sleep_calls == [3.0, 6.0]


async def test_persistent_request_error_raises_after_max_retries(sleep_calls):
    """(6) 연결 오류가 max_retries 번 계속되면 마지막 RequestError 를 던진다."""
    client = FakeClient(
        [
            _connect_timeout(),
            _connect_timeout(),
            _connect_timeout(),
        ]
    )

    with pytest.raises(httpx.ConnectTimeout):
        await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=3)

    assert client.calls == 3
    assert sleep_calls == [3.0, 6.0]


async def test_zero_max_retries_raises_runtime_error_without_any_call(sleep_calls):
    """max_retries 가 0 이면 시도 없이 RuntimeError 로 종료한다."""
    client = FakeClient([])

    with pytest.raises(RuntimeError, match="재시도 한도"):
        await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=0)

    assert client.calls == 0
    assert sleep_calls == []


async def test_retry_log_masks_credentials(sleep_calls, caplog):
    """(7) 재시도 로그에 serviceKey 같은 자격 증명 원문이 나오지 않는다."""
    client = FakeClient([_connect_timeout("?serviceKey=REALSECRET12345678"), _status_response(200)])

    with caplog.at_level("WARNING", logger="src.app.services.api_collector"):
        resp = await _make_request_with_retry(client, MOCK_URL, params={}, max_retries=5)

    assert resp.status_code == 200
    assert "REALSECRET12345678" not in caplog.text
    assert "serviceKey=***" in caplog.text
