"""
src/rag/llm.py

RAG 생성 LLM 백엔드 추상화.

원본 bid_box 는 Google Gemini API 를 직접 호출했습니다. 리팩토링본은 발표 환경에서
네트워크와 API 키 의존을 없애기 위해 기본 백엔드를 로컬 Ollama(gemma4:e4b)로 두되,
`LLM_PROVIDER=gemini` 로 원본 경로를 즉시 복원할 수 있게 유지합니다.

주의: 본 모듈은 생성(generation) LLM 만 교체합니다. ChromaDB 임베딩 모델은
기존 19개 컬렉션과의 정합성 때문에 절대 교체하지 않습니다 (G1 데이터 무손실).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any, Protocol

import httpx

from src.app.core.config import settings

logger = logging.getLogger(__name__)


class LLMBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str: ...

    def stream_generate(
        self, system_prompt: str, messages: list[dict[str, str]]
    ) -> Iterator[str]: ...


class OllamaBackend:
    """로컬 Ollama /api/chat 호출 (httpx 사용, 신규 의존성 없음)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS

    def available(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Ollama 미응답 (%s): %s", self.base_url, exc)
            return False
        return True

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": False,
            "options": {"temperature": settings.LLM_TEMPERATURE},
        }
        response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        return str((body.get("message") or {}).get("content") or "")

    def stream_generate(
        self, system_prompt: str, messages: list[dict[str, str]]
    ) -> Iterator[str]:
        """Ollama /api/chat stream=True 를 사용해 실시간 토큰을 반환합니다."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": True,
            "options": {"temperature": settings.LLM_TEMPERATURE},
        }
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("done"):
                    break
                content = (chunk.get("message") or {}).get("content")
                if content:
                    yield str(content)


class GeminiBackend:
    """원본 bid_box 와 동일한 Google Gemini 경로."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self._client = None
        if self.api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                logger.warning("google-genai 미설치 - Gemini 백엔드를 사용할 수 없습니다.")

    def available(self) -> bool:
        return self._client is not None

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        from google.genai import types

        contents = [
            types.Content(
                role="model" if item.get("role") == "assistant" else "user",
                parts=[types.Part.from_text(text=item.get("content") or "")],
            )
            for item in messages
        ]
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
        return response.text or ""

    def stream_generate(
        self, system_prompt: str, messages: list[dict[str, str]]
    ) -> Iterator[str]:
        """Gemini 스트리밍 API 를 사용해 실시간 토큰을 반환합니다."""
        from google.genai import types

        contents = [
            types.Content(
                role="model" if item.get("role") == "assistant" else "user",
                parts=[types.Part.from_text(text=item.get("content") or "")],
            )
            for item in messages
        ]
        for chunk in self._client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        ):
            text = chunk.text or ""
            if text:
                yield text


def build_backend(provider: str | None = None) -> LLMBackend | None:
    """설정된 provider 백엔드를 반환합니다. 사용 불가면 None (호출부가 fallback 답변 생성)."""
    resolved = (provider or settings.LLM_PROVIDER or "ollama").strip().lower()

    if resolved == "gemini":
        backend = GeminiBackend()
        return backend if backend.available() else None

    backend = OllamaBackend()
    if backend.available():
        return backend

    # Ollama 가 꺼져 있고 Gemini 키가 있으면 원본 경로로 자동 폴백합니다.
    gemini = GeminiBackend()
    if gemini.available():
        logger.warning("Ollama 사용 불가로 Gemini 백엔드로 폴백합니다.")
        return gemini
    return None
