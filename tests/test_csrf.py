import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.api.ui import _verify_ssr_csrf
from src.app.core import security


def test_csrf_token_is_signed_and_matches(monkeypatch):
    token = security.make_csrf_token()
    assert security.csrf_tokens_match(token, token)
    assert not security.csrf_tokens_match(token, token + "tampered")


def test_csrf_token_rejects_different_cookie_token():
    token = security.make_csrf_token()
    assert not security.csrf_tokens_match(security.make_csrf_token(), token)


def test_csrf_token_can_be_disabled(monkeypatch):
    monkeypatch.setattr(security.settings, "CSRF_PROTECTION_ENABLED", False, raising=False)
    request = Request(
        {"type": "http", "headers": [(b"cookie", b"bidbox_csrf=not-used")]},
        receive=lambda: None,
    )
    asyncio.run(_verify_ssr_csrf(request))


def test_csrf_enabled_rejects_missing_form_token(monkeypatch):
    monkeypatch.setattr(security.settings, "CSRF_PROTECTION_ENABLED", True, raising=False)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {"type": "http", "headers": [(b"cookie", b"bidbox_csrf=expected")]},
        receive=receive,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_verify_ssr_csrf(request))
    assert exc_info.value.status_code == 403
