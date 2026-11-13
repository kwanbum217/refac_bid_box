"""RATE_LIMIT_EXEMPT_USERNAMES 면제 판정 시험.

로그인 사용자 API 한도 한 곳에서만 면제가 적용되는지, 기본값과 production 에서
동작이 바뀌지 않는지 확인합니다.
"""

from types import SimpleNamespace

import pytest

from src.app.core import security
from src.app.core.config import settings


@pytest.fixture
def limiter_calls(monkeypatch):
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        security.authenticated_api_rate_limiter,
        "check_rate_limit",
        lambda user_id: calls.append(("check", user_id)),
    )
    monkeypatch.setattr(
        security.authenticated_api_rate_limiter,
        "record_request",
        lambda user_id: calls.append(("record", user_id)),
    )
    return calls


@pytest.fixture
def request_stub():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})


def test_default_setting_keeps_limit(monkeypatch, limiter_calls, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", "")
    user = SimpleNamespace(id=7, username="some_user")

    security.enforce_anonymous_api_quota(request_stub, user)

    assert limiter_calls == [("check", 7), ("record", 7)]


def test_exempt_user_skips_check_and_record(monkeypatch, limiter_calls, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", "bench_measure")
    user = SimpleNamespace(id=7, username="bench_measure")

    security.enforce_anonymous_api_quota(request_stub, user)

    assert limiter_calls == []


def test_user_not_in_list_is_limited(monkeypatch, limiter_calls, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", "bench_measure")
    user = SimpleNamespace(id=7, username="other_user")

    security.enforce_anonymous_api_quota(request_stub, user)

    assert limiter_calls == [("check", 7), ("record", 7)]


def test_production_ignores_exempt_list(monkeypatch, limiter_calls, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", "bench_measure")
    monkeypatch.setattr(security, "_rate_limit_exempt_production_warned", False)
    user = SimpleNamespace(id=7, username="bench_measure")

    security.enforce_anonymous_api_quota(request_stub, user)

    assert limiter_calls == [("check", 7), ("record", 7)]


def test_exempt_list_parsing_trims_and_drops_empty(monkeypatch, limiter_calls, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", " a , ,b ")

    security.enforce_anonymous_api_quota(request_stub, SimpleNamespace(id=1, username="a"))
    security.enforce_anonymous_api_quota(request_stub, SimpleNamespace(id=2, username="b"))

    assert limiter_calls == []


def test_anonymous_path_unchanged(monkeypatch, request_stub):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_EXEMPT_USERNAMES", "bench_measure")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        security.anonymous_api_rate_limiter,
        "check_rate_limit",
        lambda ip: calls.append(("check", ip)),
    )
    monkeypatch.setattr(
        security.anonymous_api_rate_limiter,
        "record_request",
        lambda ip: calls.append(("record", ip)),
    )

    security.enforce_anonymous_api_quota(request_stub, None)

    assert calls == [("check", "127.0.0.1"), ("record", "127.0.0.1")]
