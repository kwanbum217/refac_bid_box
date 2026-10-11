"""쿠키 인증 /api/v1 상태 변경 요청의 출처 검사 계약을 검증합니다.

같은 사이트가 아닌 출처의 상태 변경은 403 으로 막고, 같은 출처·허용 목록·
출처 부재·GET·세션 쿠키 없는 요청은 막지 않습니다. 워커 콜백은 쿠키가 없어
검사 대상에서 자연히 빠지는지도 함께 확인합니다.
"""

from __future__ import annotations

import pytest

from src.app.core.config import settings
from src.app.core.origin_guard import (
    ORIGIN_REJECTED_DETAIL,
    has_session_cookie,
    is_origin_allowed,
    origin_of,
    resolve_request_origin,
)

WRITE_PATH = "/api/v1/automation/run/collect-bids"
EXTERNAL_ORIGIN = "https://evil.example"


def _headers(**extra: str) -> dict[str, str]:
    """세션 쿠키를 항상 실은 헤더를 만듭니다."""
    return {"Cookie": "bidbox_session=test-session", **extra}


def _blocked_by_guard(response) -> bool:
    try:
        detail = response.json().get("detail")
    except Exception:
        return False
    return response.status_code == 403 and detail == ORIGIN_REJECTED_DETAIL


@pytest.fixture
def guard_active(monkeypatch):
    """개발 모드라도 임의 출처 허용을 끄고 명시 목록을 비워 검사를 켭니다."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CORS_DEV_ALLOW_ALL", False)
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "")
    return settings


# --------------------------------------------------------------------------- #
# 순수 헬퍼
# --------------------------------------------------------------------------- #


def test_origin_of_extracts_scheme_and_host():
    assert origin_of("https://app.example.com/path?q=1") == "https://app.example.com"
    assert origin_of("http://localhost:8000/anything") == "http://localhost:8000"


def test_origin_of_rejects_unparseable():
    assert origin_of("not-a-url") is None
    assert origin_of("/relative/path") is None


def test_resolve_request_origin_prefers_origin_header():
    assert resolve_request_origin("https://a.example", "https://b.example/x") == "https://a.example"


def test_resolve_request_origin_falls_back_to_referer():
    assert resolve_request_origin("", "https://b.example/x") == "https://b.example"


def test_resolve_request_origin_absent_is_none():
    assert resolve_request_origin("", "") is None


def test_resolve_request_origin_malformed_referer_is_empty():
    assert resolve_request_origin("", "not-a-url") == ""


def test_has_session_cookie_detects_named_cookie():
    assert has_session_cookie("bidbox_session=abc; other=1")
    assert not has_session_cookie("other=1")
    assert not has_session_cookie("")


def test_is_origin_allowed_same_host_and_allowlist():
    assert is_origin_allowed("https://app.example.com", "app.example.com", [])
    assert is_origin_allowed("http://localhost:8000", "localhost:8000", [])
    assert is_origin_allowed(
        "https://allowed.example", "app.example.com", ["https://allowed.example"]
    )
    assert not is_origin_allowed("https://evil.example", "app.example.com", [])
    assert not is_origin_allowed("null", "app.example.com", [])


# --------------------------------------------------------------------------- #
# HTTP 계약
# --------------------------------------------------------------------------- #


def test_external_origin_blocks_state_change_with_session_cookie(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin=EXTERNAL_ORIGIN))
    assert _blocked_by_guard(response)


def test_external_referer_blocks_state_change_with_session_cookie(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers=_headers(Referer=f"{EXTERNAL_ORIGIN}/page"))
    assert _blocked_by_guard(response)


def test_null_origin_is_blocked(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin="null"))
    assert _blocked_by_guard(response)


def test_same_origin_header_passes(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin="http://testserver"))
    assert not _blocked_by_guard(response)


def test_same_origin_referer_passes(client, guard_active):
    response = client.post(
        WRITE_PATH, json={}, headers=_headers(Referer="http://testserver/some/page")
    )
    assert not _blocked_by_guard(response)


def test_allowed_cors_origin_passes(client, guard_active):
    guard_active.CORS_ALLOWED_ORIGINS = "https://app.example.com"
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin="https://app.example.com"))
    assert not _blocked_by_guard(response)


def test_allowed_cors_origin_from_referer_passes(client, guard_active):
    guard_active.CORS_ALLOWED_ORIGINS = "https://app.example.com"
    response = client.post(
        WRITE_PATH, json={}, headers=_headers(Referer="https://app.example.com/dashboard")
    )
    assert not _blocked_by_guard(response)


def test_missing_origin_and_referer_passes(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers=_headers())
    assert not _blocked_by_guard(response)


def test_request_without_session_cookie_is_not_checked(client, guard_active):
    response = client.post(WRITE_PATH, json={}, headers={"Origin": EXTERNAL_ORIGIN})
    assert not _blocked_by_guard(response)


def test_get_is_not_checked(client, guard_active):
    response = client.get(
        "/api/v1/automation/job/any-job/status", headers=_headers(Origin=EXTERNAL_ORIGIN)
    )
    assert not _blocked_by_guard(response)


def test_non_api_path_is_not_checked(client, guard_active):
    response = client.post("/does-not-exist", headers=_headers(Origin=EXTERNAL_ORIGIN))
    assert response.status_code == 404


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_put_patch_delete_are_checked(client, guard_active, method):
    response = getattr(client, method)(WRITE_PATH, headers=_headers(Origin=EXTERNAL_ORIGIN))
    assert _blocked_by_guard(response)


def test_dev_allow_all_skips_check(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CORS_DEV_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "")
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin=EXTERNAL_ORIGIN))
    assert not _blocked_by_guard(response)


def test_dev_with_configured_origins_still_checks(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CORS_DEV_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    response = client.post(WRITE_PATH, json={}, headers=_headers(Origin=EXTERNAL_ORIGIN))
    assert _blocked_by_guard(response)


def test_worker_callback_without_cookie_is_exempt(client, guard_active):
    """워커 콜백은 쿠키가 없어 출처 검사 대상이 아닙니다.

    외부 Origin 이 실려도 출처 검사가 아니라 토큰 검사에서 403 이 나와야 합니다.
    """
    response = client.post(
        "/api/v1/automation/job/no-such-job/callback",
        json={},
        headers={"Origin": EXTERNAL_ORIGIN, "X-BIDBOX-CALLBACK-TOKEN": "invalid"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "유효하지 않은 callback 토큰입니다."
