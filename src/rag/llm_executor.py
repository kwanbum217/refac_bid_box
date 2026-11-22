"""
src/rag/llm_executor.py

챗봇 LLM 호출 전용 스레드 실행기.

`asyncio.to_thread` 는 이벤트 루프 기본 실행기(ThreadPoolExecutor)를 씁니다.
LLM 스트리밍은 토큰 하나를 기다리는 동안 그 스레드를 붙잡고 있으므로, 같은
실행기를 쓰는 로그인·가입 제한기, 챗봇 쿼터, OCR 오프로드가 함께 밀립니다.
여기서는 챗봇 LLM 경로만 쓰는 실행기를 따로 두어 기본 실행기의 고갈과
분리합니다. 기본 실행기를 교체(`set_default_executor`)하지는 않습니다.

토큰 생성기는 `next` 와 `close` 를 같은 잠금으로 직렬화합니다. 소비자가
취소되면 진행 중인 `next` 는 실행기 스레드에서 계속 돌고 있으므로, 곧바로
`close` 를 부르면 `ValueError: generator already executing` 가 납니다.
`TokenGeneratorGuard.close` 는 진행 중인 `next` 가 끝난 뒤에 닫습니다.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

LLM_EXECUTOR_MAX_WORKERS = 8
LLM_EXECUTOR_THREAD_PREFIX = "rag-llm"

T = TypeVar("T")

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def get_llm_executor() -> ThreadPoolExecutor:
    """챗봇 LLM 전용 실행기를 지연 생성해 반환합니다."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=LLM_EXECUTOR_MAX_WORKERS,
                thread_name_prefix=LLM_EXECUTOR_THREAD_PREFIX,
            )
        return _executor


def shutdown_llm_executor(wait: bool = False) -> None:
    """전용 실행기를 정리합니다. 다음 접근에서 새로 만들어집니다.

    앱 종료 훅(main.py)에는 아직 연결하지 않았습니다. 프로세스가 끝나면
    실행기 스레드도 함께 정리되므로 필수 경로는 아닙니다.
    """
    global _executor
    with _executor_lock:
        executor = _executor
        _executor = None
    if executor is not None:
        executor.shutdown(wait=wait)


async def run_in_llm_executor(func: Callable[..., T], *args: Any) -> T:
    """`func` 를 전용 실행기에서 실행하고 결과를 기다립니다.

    `asyncio.to_thread` 와 같이 호출 시점의 contextvars 문맥을 복사해
    넘깁니다. 로그 상관관계(trace_id 등)가 스레드에서도 유지됩니다.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(get_llm_executor(), functools.partial(ctx.run, func, *args))


def _close_in_background(guard: TokenGeneratorGuard) -> None:
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(get_llm_executor(), guard.close)
    future.add_done_callback(_log_close_failure)


def _log_close_failure(future: asyncio.Future[None]) -> None:
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        logger.debug("LLM 토큰 생성기 종료 중 예외 (무시됨): %s", exc)


async def close_token_generator(guard: TokenGeneratorGuard) -> None:
    """토큰 생성기를 닫습니다. 취소 중에도 닫기를 포기하지 않습니다."""
    if guard.closed:
        return
    try:
        await run_in_llm_executor(guard.close)
    except asyncio.CancelledError:
        # 취소가 다시 전달되면 기다릴 수 없습니다. 실행기에 맡기고 빠져나갑니다.
        guard.close_nowait()
        raise
    except Exception as exc:
        logger.debug("LLM 토큰 생성기 종료 중 예외 (무시됨): %s", exc)


class TokenGeneratorGuard:
    """토큰 생성기의 `next` 와 `close` 를 잠금으로 직렬화합니다."""

    def __init__(self, generator: Iterator[str]) -> None:
        self._generator = generator
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def next_token(self) -> str | None:
        """실행기 스레드에서 다음 토큰을 꺼냅니다. 끝이면 None 입니다."""
        with self._lock:
            if self._closed:
                return None
            return next(self._generator, None)

    def close(self) -> None:
        """진행 중인 `next` 가 끝난 뒤 생성기를 닫습니다. 여러 번 불러도 안전합니다."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            close = getattr(self._generator, "close", None)
            if close is None:
                return
            close()

    def close_nowait(self) -> None:
        """취소로 `close` 를 기다릴 수 없을 때 실행기에 맡기고 빠져나갑니다."""
        with _executor_lock:
            executor = _executor
        if executor is None:
            # 정리된 실행기에는 맡길 수 없습니다. 이벤트 루프를 막지 않도록
            # 짧은 스레드에서 닫습니다.
            threading.Thread(
                target=self.close,
                name=f"{LLM_EXECUTOR_THREAD_PREFIX}-close",
                daemon=True,
            ).start()
            return
        _close_in_background(self)


__all__ = [
    "LLM_EXECUTOR_MAX_WORKERS",
    "LLM_EXECUTOR_THREAD_PREFIX",
    "TokenGeneratorGuard",
    "close_token_generator",
    "get_llm_executor",
    "run_in_llm_executor",
    "shutdown_llm_executor",
]
