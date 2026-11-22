"""챗봇 API 동시 실행 상한과 사용자당 1요청 제한입니다.

전역 슬롯은 프로세스 단위로 세므로, 프로세스가 여러 개면(WEB_CONCURRENCY > 1)
전체 상한은 설정값의 프로세스 수 배가 됩니다. 사용자당 제한은 로그인 사용자의
id, 익명은 클라이언트 IP 를 키로 씁니다. 슬롯은 LLM·DB 를 건드리기 전에
비차단으로 잡고, 넘치면 HTTPException(503/429) 과 Retry-After 로 즉시
거절합니다. 증감은 동기 엔드포인트·시험 스레드에서도 일어날 수 있어
threading.Lock 으로 보호합니다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from src.app.core.config import settings
from src.app.core.security import resolve_client_ip
from src.app.models.accounts import CustomUser

CHAT_BUSY_DETAIL = "지금 상담 요청이 많습니다. 잠시 후 다시 시도해 주세요."
CHAT_DUPLICATE_DETAIL = "이전 답변이 끝난 뒤 다시 질문해 주세요."
CHAT_RETRY_AFTER_SECONDS = 5
DEFAULT_MAX_CONCURRENT_REQUESTS = 2


class ChatConcurrencyLimiter:
    """프로세스 단위 동시 실행 상한과 사용자당 1요청 제한입니다.

    반납 함수는 여러 번 불려도 한 번만 반영하므로 정상 종료·예외·연결 끊김이
    겹쳐도 슬롯이 두 번 반납되지 않습니다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_total = 0
        self._active_users: set[str] = set()

    def acquire(self, user_key: str, limit: int) -> Callable[[], None]:
        with self._lock:
            if user_key in self._active_users:
                raise HTTPException(
                    status_code=429,
                    detail=CHAT_DUPLICATE_DETAIL,
                    headers={"Retry-After": str(CHAT_RETRY_AFTER_SECONDS)},
                )
            if self._active_total >= max(1, limit):
                raise HTTPException(
                    status_code=503,
                    detail=CHAT_BUSY_DETAIL,
                    headers={"Retry-After": str(CHAT_RETRY_AFTER_SECONDS)},
                )
            self._active_total += 1
            self._active_users.add(user_key)

        released = False

        def release() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                self._active_users.discard(user_key)
                if self._active_total > 0:
                    self._active_total -= 1

        return release


chat_limiter = ChatConcurrencyLimiter()


class ChatStreamingResponse(StreamingResponse):
    """동시성 슬롯 반납을 응답 수명 전체에 묶은 StreamingResponse 입니다.

    Starlette 1.3.1 은 ASGI spec_version 2.4 이상에서 응답 시작 send 가 OSError 를
    내면 본문 반복 전에 ClientDisconnect 를 올리고, 2.4 미만에서는
    listen_for_disconnect 가 먼저 끝나면 stream_response 를 취소합니다. 두 경우 모두
    본문 생성기가 한 번도 시작되지 않아 생성기 finally 가 돌지 않으므로 여기서
    반납합니다. 반납 함수는 멱등이라 생성기 finally 와 겹쳐도 한 번만 반영됩니다.
    """

    def __init__(self, *args: Any, release: Callable[[], None], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


def max_concurrent_requests() -> int:
    """설정에서 동시 실행 상한을 읽습니다. 잘못된 값은 기본값으로 되돌립니다."""
    raw = getattr(settings, "CHATBOT_MAX_CONCURRENT_REQUESTS", DEFAULT_MAX_CONCURRENT_REQUESTS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT_REQUESTS


def user_key(request: Request, user: CustomUser | None) -> str:
    """동시 1요청 제한의 키입니다. 로그인 사용자는 id, 익명은 클라이언트 IP 입니다."""
    user_id = getattr(user, "id", None)
    if user_id is not None:
        return f"user:{user_id}"
    peer = request.client.host if request.client and request.client.host else ""
    return f"ip:{resolve_client_ip(peer, request.headers.get('x-forwarded-for'))}"
