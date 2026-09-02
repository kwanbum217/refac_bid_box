import asyncio
import re

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.api.ui import _verify_ssr_csrf
from src.app.core import security


def csrf_form(client, page_path: str, data: dict | None = None) -> dict:
    """실제 브라우저처럼 폼 화면을 먼저 열고 hidden CSRF 값을 제출합니다."""
    page = client.get(page_path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, f"CSRF token missing from {page_path}"
    return {**(data or {}), security.CSRF_FORM_FIELD: match.group(1)}


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


@pytest.mark.parametrize(
    "path,data",
    [
        ("/accounts/signup/", {}),
        ("/accounts/login/", {"username": "u", "password": "p"}),
        ("/accounts/logout/", {}),
    ],
)
@pytest.mark.parametrize("submitted_token", [None, "forged-token"])
def test_each_ssr_post_rejects_missing_or_forged_token(
    client, path, data, submitted_token, monkeypatch
):
    monkeypatch.setattr(security.settings, "CSRF_PROTECTION_ENABLED", True, raising=False)
    client.cookies.set(security.CSRF_COOKIE_NAME, security.make_csrf_token())
    if submitted_token is not None:
        data = {**data, security.CSRF_FORM_FIELD: submitted_token}
    response = client.post(path, data=data, follow_redirects=False)
    assert response.status_code == 403
