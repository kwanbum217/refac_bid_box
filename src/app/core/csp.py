"""요청마다 nonce 를 발급하는 Content-Security-Policy 미들웨어.

인라인 <script> 를 허용하면서도 임의 스크립트 주입을 막기 위해 nonce 방식을
씁니다. 요청마다 새 nonce 를 만들어 요청 상태에 실어 두고, 템플릿은 그 값을
script 태그의 nonce 속성에 씁니다. 브라우저는 헤더의 nonce 와 일치하는
스크립트만 실행하므로, 공격자가 주입한 태그는 nonce 를 모르는 한 실행되지
않습니다.

정책은 HTML 응답에만 답니다. JSON API 와 정적 파일에는 쓰이지 않으며,
Swagger UI(/docs)와 ReDoc(/redoc)은 자체 CDN 스크립트를 쓰므로 제외합니다.

nonce 는 secrets.token_urlsafe(16) 이라 요청마다 달라지고 예측할 수 없습니다.
"""

from __future__ import annotations

import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP_HEADER_NAME = b"content-security-policy"
NONCE_ATTRIBUTE = "csp_nonce"
DOCS_PATHS = ("/docs", "/redoc")

POLICY_TEMPLATE = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://upload.wikimedia.org; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'; "
    "form-action 'self'"
)


def build_policy(nonce: str) -> str:
    """nonce 를 끼운 CSP 정책 문자열을 만듭니다."""
    return POLICY_TEMPLATE.format(nonce=nonce)


def is_docs_path(path: str) -> bool:
    """FastAPI 문서 UI 경로인지 판정합니다.

    Swagger UI 와 ReDoc 은 자체 CDN 스크립트·스타일을 불러오므로 앱 CSP 를
    걸면 문서 화면이 동작하지 않습니다. 하위 경로(/docs/oauth2-redirect)까지
    포함합니다.
    """
    return any(path == prefix or path.startswith(prefix + "/") for prefix in DOCS_PATHS)


def _is_html_response(headers: list[tuple[bytes, bytes]]) -> bool:
    for key, value in headers:
        if key.lower() == b"content-type":
            return value.split(b";", 1)[0].strip().lower() == b"text/html"
    return False


class ContentSecurityPolicyMiddleware:
    """nonce 를 발급하고 HTML 응답에 CSP 헤더를 다는 순수 ASGI 미들웨어.

    본문을 읽거나 바꾸지 않고 응답 시작 메시지의 헤더만 손대므로 SSE 스트리밍과
    충돌하지 않습니다. 설정은 요청 시점에 읽어 테스트에서 바꿔 끼울 수 있습니다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})[NONCE_ATTRIBUTE] = nonce

        if is_docs_path(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        policy = build_policy(nonce).encode("latin1")

        async def send_with_csp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                if _is_html_response(headers):
                    headers.append((CSP_HEADER_NAME, policy))
            await send(message)

        await self.app(scope, receive, send_with_csp)
