"""
src/rag/llm.py

RAG 생성 LLM 백엔드 추상화.

원본 bid_box 는 Google Gemini API 를 직접 호출했습니다. 리팩토링본은 발표 환경에서
네트워크와 API 키 의존을 없애기 위해 기본 백엔드를 로컬 Ollama(gemma4:e4b)로 두되,
`LLM_PROVIDER=gemini` 로 원본 경로를 즉시 복원할 수 있게 유지합니다.

주의: 본 모듈은 생성(generation) LLM 만 교체합니다. ChromaDB 임베딩 모델은
보존된 bidding_kb 임베딩과의 정합성 때문에 절대 교체하지 않습니다 (G1 데이터 무손실).
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

    def warmup(self) -> bool: ...

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str: ...

    def stream_generate(
        self, system_prompt: str, messages: list[dict[str, str]]
    ) -> Iterator[str]: ...


def _coerce_keep_alive(value: str | int | float) -> str | int:
    """Ollama 가 받는 형태로 맞춥니다.

    숫자는 초 단위 정수로, 그 외는 지속시간 문자열("30m")로 보냅니다. 무기한을
    뜻하는 -1 을 문자열로 보내면 Ollama 가 `missing unit in duration` 으로
    400 을 냅니다. 값이 조용히 무시되는 것이 아니라 요청 자체가 실패합니다.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return str(value).strip()


class OllamaBackend:
    """로컬 Ollama /api/chat 호출 (httpx 사용, 신규 의존성 없음).

    **첫 토큰 지연의 정체는 프리필이 아니라 모델 로드입니다.** 2026-08-05 실측에서
    콜드 11.78초, 웜 0.51초로 23배 차이가 났고, 같은 조건에서 프리필은 2,168토큰에
    3.13초(1.4ms/토큰), 실제 운영 프롬프트(약 1,200자)로는 1초 미만이었습니다.

    따라서 `keep_alive` 를 요청마다 명시합니다. 서버 기본값(5분)에 맡기면 질의가
    뜸한 시간대의 첫 사용자가 매번 12초를 냅니다. 서버 환경변수로 거는 방법도
    있으나 Windows 장비까지 같은 설정을 보장하기 어렵습니다 (G2 크로스 플랫폼).
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        keep_alive: str | None = None,
        thinking: bool | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self.keep_alive = _coerce_keep_alive(keep_alive or settings.OLLAMA_KEEP_ALIVE)
        self.thinking = settings.LLM_THINKING if thinking is None else thinking

    def _payload(self, system_prompt: str, messages: list[dict[str, str]], *, stream: bool) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": {"temperature": settings.LLM_TEMPERATURE},
        }
        if not self.thinking:
            # 사고를 끄지 않으면 첫 토큰이 사고가 끝난 뒤에야 나옵니다. 사고를
            # 지원하지 않는 모델은 이 필드를 무시하므로 그대로 보내도 안전합니다.
            payload["think"] = False
        return payload

    def available(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Ollama 미응답 (%s): %s", self.base_url, exc)
            return False
        return True

    def warmup(self) -> bool:
        """모델을 메모리에 올려 둡니다. 실패해도 서비스는 계속됩니다.

        빈 messages 로 부르면 Ollama 는 생성 없이 로드만 수행합니다.
        """
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": [], "keep_alive": self.keep_alive},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Ollama 예열 실패 (%s): %s", self.model, exc)
            return False
        logger.info("Ollama 예열 완료 (%s, keep_alive=%s)", self.model, self.keep_alive)
        return True

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        payload = self._payload(system_prompt, messages, stream=False)
        response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        return str((body.get("message") or {}).get("content") or "")

    def stream_generate(self, system_prompt: str, messages: list[dict[str, str]]) -> Iterator[str]:
        """Ollama /api/chat stream=True 를 사용해 실시간 토큰을 반환합니다."""
        payload = self._payload(system_prompt, messages, stream=True)
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

    def warmup(self) -> bool:
        """원격 API 라 예열할 상태가 없습니다."""
        return True

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        if self._client is None:
            raise RuntimeError("Gemini 클라이언트가 초기화되지 않았습니다. API 키를 확인하세요.")
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

    def stream_generate(self, system_prompt: str, messages: list[dict[str, str]]) -> Iterator[str]:
        """Gemini 스트리밍 API 를 사용해 실시간 토큰을 반환합니다."""
        if self._client is None:
            raise RuntimeError("Gemini 클라이언트가 초기화되지 않았습니다. API 키를 확인하세요.")
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
        gemini_backend = GeminiBackend()
        return gemini_backend if gemini_backend.available() else None

    ollama_backend = OllamaBackend()
    if ollama_backend.available():
        return ollama_backend

    # Ollama 가 꺼져 있고 Gemini 키가 있으면 원본 경로로 자동 폴백합니다.
    gemini = GeminiBackend()
    if gemini.available():
        logger.warning("Ollama 사용 불가로 Gemini 백엔드로 폴백합니다.")
        return gemini
    return None
