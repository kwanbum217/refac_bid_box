"""쿠키 인증 JSON API 의 상태 변경 요청에 출처(Origin/Referer) 검사를 겁니다.

세션 쿠키가 SameSite=Lax 이므로 크로스 사이트 폼 전송이나 최상위 이동에는
쿠키가 실리지 않지만, SameSite 는 브라우저 구현과 예외 경로(예: 일부 리다이렉트)
에 기대는 방어입니다. 서버가 출처를 직접 확인하면 그 우연한 방어에 기대지 않고
같은 사이트에서 오지 않은 상태 변경을 거부할 수 있습니다.

검사 범위는 다음 조건을 모두 만족할 때로 좁힙니다.
  - 경로가 `/api/v1/` 로 시작한다.
  - 메서드가 POST·PUT·PATCH·DELETE 다.
  - 요청에 세션 쿠키가 있다.

세션 쿠키가 없으면 쿠키 인증 요청이 아니므로(예: 워커 콜백) 검사하지 않습니다.
브라우저는 상태 변경 요청에 Origin 을 싣고, Origin 이 없으면 Referer 의 출처를
씁니다. 둘 다 없으면 비브라우저 클라이언트로 보고 통과시킵니다.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1/"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ORIGIN_REJECTED_DETAIL = "허용되지 않은 출처의 요청입니다."


def has_session_cookie(cookie_header: str) -> bool:
    """Cookie 헤더에 세션 쿠키가 있는지 확인합니다."""
    for part in cookie_header.split(";"):
        name, _, _ = part.strip().partition("=")
        if name == SESSION_COOKIE_NAME:
            return True
    return False


def origin_of(url: str) -> str | None:
    """URL 에서 출처(scheme://host[:port]) 를 뽑습니다. 해석 불가면 None 입니다."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def resolve_request_origin(origin_header: str, referer_header: str) -> str | None:
    """요청의 출처 표지를 해석합니다.

    반환값 None 은 출처 표지가 아예 없음(비브라우저 클라이언트)을 뜻합니다.
    빈 문자열은 표지는 있으나 출처를 해석할 수 없음(거부 대상)을 뜻합니다.
    Origin 이 있으면 그 값을, 없고 Referer 가 있으면 그 출처를 씁니다.
    """
    if origin_header:
        return origin_header.strip()
    if referer_header:
        return origin_of(referer_header) or ""
    return None


def is_origin_allowed(origin: str, host: str, allowed_origins: list[str]) -> bool:
    """출처가 같은 출처이거나 허용 목록에 있으면 True 입니다.

    같은 출처 판정은 요청 Host 와 출처의 netloc 을 비교합니다. 리버스 프록시 뒤에서
    앱이 보는 스킴(http)과 브라우저 출처의 스킴(https)이 어긋날 수 있어 스킴은
    비교하지 않습니다.
    """
    normalized = origin.strip().rstrip("/").lower()
    if not normalized:
        return False
    if normalized in {o.strip().rstrip("/").lower() for o in allowed_origins if o.strip()}:
        return True
    request_host = host.strip().lower()
    if not request_host:
        return False
    origin_netloc = urlsplit(normalized).netloc
    return bool(origin_netloc) and origin_netloc == request_host


def _dev_skip_enabled() -> bool:
    """개발 모드에서 임의 출처를 허용할지 판정합니다.

    config.py 의 CORS 정책과 같은 의미입니다. development 이고
    CORS_DEV_ALLOW_ALL 이 참이며 명시 목록이 비어 있을 때만 검사를 건너뜁니다.
    """
    return (
        settings.ENVIRONMENT == "development"
        and bool(settings.CORS_DEV_ALLOW_ALL)
        and not settings.cors_allowed_origins
    )


class OriginGuardMiddleware:
    """출처 검사를 수행하는 순수 ASGI 미들웨어.

    헤더와 메서드만 보므로 본문을 읽지 않고, 거부 시 403 을 즉시 반환합니다.
    설정은 요청 시점에 읽어 테스트에서 monkeypatch 할 수 있습니다.
    """

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _header(scope, name: bytes) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value.decode("latin1").strip()
        return ""

    def _should_check(self, scope) -> bool:
        if scope.get("method", "") not in STATE_CHANGING_METHODS:
            return False
        if not str(scope.get("path", "")).startswith(API_PREFIX):
            return False
        if not has_session_cookie(self._header(scope, b"cookie")):
            return False
        return not _dev_skip_enabled()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self._should_check(scope):
            await self.app(scope, receive, send)
            return

        origin = resolve_request_origin(
            self._header(scope, b"origin"), self._header(scope, b"referer")
        )
        if origin is None:
            await self.app(scope, receive, send)
            return

        host = self._header(scope, b"host")
        if is_origin_allowed(origin, host, settings.cors_allowed_origins):
            await self.app(scope, receive, send)
            return

        logger.warning(
            "출처 검사 거부: method=%s path=%s origin=%s host=%s",
            scope.get("method"),
            scope.get("path"),
            origin,
            host,
        )
        response = JSONResponse(status_code=403, content={"detail": ORIGIN_REJECTED_DETAIL})
        await response(scope, receive, send)
