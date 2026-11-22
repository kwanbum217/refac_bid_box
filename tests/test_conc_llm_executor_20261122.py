"""
tests/test_conc_llm_executor_20261122.py

챗봇 LLM 전용 실행기 분리와 스트림 이탈 시 토큰 생성기 종료를 검증합니다.

(a) 스트림의 `next` 호출이 기본 실행기가 아닌 전용 실행기 스레드에서 실행됨
(b) 기본 실행기를 1개 스레드로 묶어 둔 상태에서도 스트림 토큰이 계속 흐름
(c) 소비자가 도중에 aclose() 하거나 작업을 취소하면 토큰 생성기 close 가 호출됨
(d) 정상 종료 시 이벤트 순서(docs, token..., done)와 최종 답변이 불변

LLM 백엔드는 전부 가짜입니다. 운영 DB, Redis, Ollama, Meilisearch 에
기대지 않도록 tool_context 로 검색 근거를 미리 채웁니다.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from src.rag.engine import HybridRAGEngine
from src.rag.llm_executor import (
    LLM_EXECUTOR_THREAD_PREFIX,
    get_llm_executor,
    shutdown_llm_executor,
)

_TOOL_CONTEXT: dict[str, Any] = {
    "tool_results": {
        "semantic_search": {
            "documents": [{"document": "테스트 근거 문서", "metadata": {"doc_id": "test-1"}}]
        },
    },
}


async def _wait_until(predicate, timeout: float = 10.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


@pytest.fixture(autouse=True)
def _fresh_llm_executor():
    """테스트마다 전용 실행기를 새로 만듭니다. 지연 생성 경로도 함께 검증됩니다."""
    yield
    shutdown_llm_executor(wait=True)


class _RecordingStreamBackend:
    """토큰을 내보내며 next 스레드 이름과 close 호출을 기록합니다."""

    name = "fake"

    def __init__(self, tokens: tuple[str, ...] = ("안녕", "하세요", "입니다")) -> None:
        self._tokens = tokens
        self.thread_names: list[str] = []
        self.closed = threading.Event()

    def available(self) -> bool:
        return True

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        self.thread_names.append(threading.current_thread().name)
        return "동기 답변입니다"

    def stream_generate(self, system_prompt: str, messages: list[dict[str, str]]) -> Iterator[str]:
        try:
            for token in self._tokens:
                self.thread_names.append(threading.current_thread().name)
                yield token
        finally:
            self.closed.set()


class _BlockingStreamBackend(_RecordingStreamBackend):
    """두 번째 토큰을 붙잡아 next 가 실행 중인 상태를 만듭니다."""

    def __init__(self) -> None:
        super().__init__(("첫", "둘"))
        self.in_flight = threading.Event()
        self.release = threading.Event()
        self.overlap_error: BaseException | None = None

    def stream_generate(self, system_prompt: str, messages: list[dict[str, str]]) -> Iterator[str]:
        try:
            self.thread_names.append(threading.current_thread().name)
            yield "첫"
            self.in_flight.set()
            if not self.release.wait(15):
                raise TimeoutError("테스트가 next 를 풀어주지 않았습니다")
            yield "둘"
        except Exception as exc:
            if isinstance(exc, ValueError):
                self.overlap_error = exc
            raise
        finally:
            self.closed.set()


def _engine(backend: Any) -> HybridRAGEngine:
    engine = HybridRAGEngine()
    engine._backend = backend
    engine._backend_resolved = True
    return engine


async def _collect(engine: HybridRAGEngine, query: str = "테스트 질문") -> list[dict[str, Any]]:
    return [event async for event in engine.stream_tokens(query, tool_context=_TOOL_CONTEXT)]


async def test_stream_token_next_runs_on_llm_executor():
    """(a) 토큰 대기가 기본 실행기가 아닌 전용 실행기에서 일어납니다."""
    backend = _RecordingStreamBackend()
    engine = _engine(backend)

    await _collect(engine)

    assert backend.thread_names, "토큰 생성기가 실행되지 않았습니다"
    for name in backend.thread_names:
        assert name.startswith(LLM_EXECUTOR_THREAD_PREFIX), (
            f"토큰 next 가 전용 실행기가 아닌 스레드에서 실행되었습니다: {name}"
        )
    assert get_llm_executor() is not None


async def test_context_prepare_and_non_streaming_answer_use_llm_executor():
    """스트리밍·비스트리밍 LLM 경로 모두 전용 실행기를 씁니다."""
    backend = _RecordingStreamBackend()
    engine = _engine(backend)

    prepare_threads: list[str] = []
    original_prepare = engine._prepare_context

    def _spy_prepare(*args, **kwargs):
        prepare_threads.append(threading.current_thread().name)
        return original_prepare(*args, **kwargs)

    engine._prepare_context = _spy_prepare  # type: ignore[method-assign]

    await _collect(engine)
    await engine.get_answer("테스트 질문", tool_context=_TOOL_CONTEXT)

    assert prepare_threads, "컨텍스트 조회가 실행되지 않았습니다"
    for name in prepare_threads:
        assert name.startswith(LLM_EXECUTOR_THREAD_PREFIX), (
            f"컨텍스트 조회가 전용 실행기가 아닌 스레드에서 실행되었습니다: {name}"
        )
    for name in backend.thread_names:
        assert name.startswith(LLM_EXECUTOR_THREAD_PREFIX), (
            f"비스트리밍 LLM 호출이 전용 실행기가 아닌 스레드에서 실행되었습니다: {name}"
        )


async def test_stream_tokens_progress_while_default_executor_is_saturated():
    """(b) 기본 실행기가 고갈돼도 스트림 토큰은 계속 흐릅니다."""
    loop = asyncio.get_running_loop()
    single_worker_pool = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(single_worker_pool)

    occupied = threading.Event()
    release = threading.Event()

    def _occupy_default_executor() -> None:
        occupied.set()
        release.wait(15)

    blocker = loop.run_in_executor(None, _occupy_default_executor)
    try:
        assert await _wait_until(occupied.is_set), "기본 실행기를 점유하지 못했습니다"
        assert not blocker.done()

        backend = _RecordingStreamBackend()
        events = await _collect(_engine(backend))

        tokens = [event["text"] for event in events if event["type"] == "token"]
        assert tokens == ["안녕", "하세요", "입니다"]
        assert events[-1]["type"] == "done"
    finally:
        release.set()
        await blocker
        loop.set_default_executor(ThreadPoolExecutor(max_workers=4))
        single_worker_pool.shutdown(wait=False)


async def test_aclose_mid_stream_closes_token_generator():
    """(c) 소비자가 도중에 그만두면 토큰 생성기를 즉시 닫습니다."""
    backend = _RecordingStreamBackend()
    engine = _engine(backend)

    stream = engine.stream_tokens("테스트 질문", tool_context=_TOOL_CONTEXT)
    async for event in stream:
        if event["type"] == "token":
            break

    assert not backend.closed.is_set(), "스트림 도중에 생성기가 먼저 닫혔습니다"
    await stream.aclose()

    assert backend.closed.is_set(), "aclose 이후에도 토큰 생성기가 닫히지 않았습니다"


async def test_cancel_mid_stream_closes_token_generator_after_in_flight_next():
    """(c) 취소 시 진행 중인 next 와 겹치지 않게 기다렸다가 닫습니다."""
    backend = _BlockingStreamBackend()
    engine = _engine(backend)

    async def _drain() -> None:
        async for _event in engine.stream_tokens("테스트 질문", tool_context=_TOOL_CONTEXT):
            pass

    task = asyncio.create_task(_drain())
    assert await _wait_until(backend.in_flight.is_set), "next 가 실행 중이 되지 않았습니다"

    task.cancel()
    await asyncio.sleep(0.05)
    assert not backend.closed.is_set(), "next 실행 중에 생성기를 닫아 겹쳤습니다"

    backend.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _wait_until(backend.closed.is_set), "취소 뒤 토큰 생성기가 닫히지 않았습니다"
    assert backend.overlap_error is None, (
        f"next 와 close 가 겹쳐 ValueError 가 발생했습니다: {backend.overlap_error}"
    )


async def test_leak_blocked_stream_closes_token_generator():
    """유출 차단으로 루프를 빠져나갈 때도 생성기를 닫습니다."""

    class _LeakBackend(_RecordingStreamBackend):
        def stream_generate(self, system_prompt, messages):
            self.thread_names.append(threading.current_thread().name)
            try:
                yield system_prompt[:40]
            finally:
                self.closed.set()

    backend = _LeakBackend()
    events = await _collect(_engine(backend))

    done = events[-1]
    assert done["type"] == "done"
    assert done.get("leak_blocked") is True
    assert backend.closed.is_set(), "유출 차단 뒤 토큰 생성기가 닫히지 않았습니다"


async def test_normal_stream_event_order_and_final_answer_unchanged():
    """(d) 정상 흐름의 이벤트 순서와 최종 답변이 그대로입니다."""
    backend = _RecordingStreamBackend()
    events = await _collect(_engine(backend))

    assert events[0]["type"] == "docs"
    assert [event["type"] for event in events[1:-1]] == ["token", "token", "token"]
    assert [event["text"] for event in events[1:-1]] == ["안녕", "하세요", "입니다"]
    assert events[-1]["type"] == "done"
    assert events[-1]["final_answer"].startswith("안녕하세요입니다")
    assert "corrected_answer" not in events[-1]
    assert events[-1]["trace_id"]
