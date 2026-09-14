"""RAG 시스템 프롬프트 유출 방지 결정론적 출력 가드.

LLM 생성 답변 또는 스트리밍 토큰 누적 텍스트에서 SYSTEM_PROMPT 원문 특징 조각이
포착되면 사용자 노출 전에 결정론적으로 차단하고 표준 거절 문구로 교체합니다.
"""

from __future__ import annotations

import re

LEAK_REFUSAL_MESSAGE = (
    "시스템 설정이나 내부 지침은 제공할 수 없습니다. 입찰 공고나 낙찰 정보에 대해 질문해 주십시오."
)

_CACHED_FRAGMENTS: list[str] = []


def extract_system_prompt_fragments(prompt: str, min_len: int = 20) -> list[str]:
    """SYSTEM_PROMPT 에서 유출 판정에 사용할 특징 문장 조각 목록을 추출합니다.

    문장(마침표·줄바꿈)과 절(쉼표) 단위로 분리하며, 공백을 단일 공백으로 정규화하고
    min_len(기본 20자) 이상의 조각만 중복 없이 수집합니다.
    """
    fragments: list[str] = []
    for sentence in re.split(r"[.\n]", prompt):
        cleaned = re.sub(r"\s+", " ", sentence).strip().strip("'\"")
        if len(cleaned) >= min_len and cleaned not in fragments:
            fragments.append(cleaned)
        for clause in re.split(r"[,]", sentence):
            cleaned_clause = re.sub(r"\s+", " ", clause).strip().strip("'\"")
            if len(cleaned_clause) >= min_len and cleaned_clause not in fragments:
                fragments.append(cleaned_clause)
    return fragments


def init_leak_guard(prompt: str, min_len: int = 20) -> list[str]:
    """engine.py 의 SYSTEM_PROMPT 로 조각 목록을 초기화하고 캐시합니다."""
    global _CACHED_FRAGMENTS
    _CACHED_FRAGMENTS = extract_system_prompt_fragments(prompt, min_len=min_len)
    return _CACHED_FRAGMENTS


def get_system_prompt_fragments() -> list[str]:
    """캐시된 SYSTEM_PROMPT 조각 목록을 반환합니다.

    아직 초기화되지 않은 경우 지연 로딩을 시도합니다.
    """
    global _CACHED_FRAGMENTS
    if not _CACHED_FRAGMENTS:
        try:
            from src.rag.engine import SYSTEM_PROMPT

            _CACHED_FRAGMENTS = extract_system_prompt_fragments(SYSTEM_PROMPT)
        except ImportError:
            pass
    return _CACHED_FRAGMENTS


def reset_leak_guard() -> None:
    """테스트 격리용: 캐시된 조각 목록을 초기화합니다."""
    global _CACHED_FRAGMENTS
    _CACHED_FRAGMENTS = []


def contains_system_prompt_leak(text: str, fragments: list[str] | None = None) -> bool:
    """답변 텍스트에 SYSTEM_PROMPT 원문 특징 조각이 포함되어 있는지 판정합니다."""
    if not text or not text.strip():
        return False
    frags = fragments if fragments is not None else get_system_prompt_fragments()
    if not frags:
        return False
    normalized_text = re.sub(r"\s+", " ", text)
    return any(frag in text or frag in normalized_text for frag in frags)


__all__ = [
    "LEAK_REFUSAL_MESSAGE",
    "contains_system_prompt_leak",
    "extract_system_prompt_fragments",
    "get_system_prompt_fragments",
    "init_leak_guard",
    "reset_leak_guard",
]
