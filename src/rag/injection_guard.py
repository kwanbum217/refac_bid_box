"""RAG 사용자 질의 가짜 Source 블록 인젝션 방지 결정론적 입력 가드.

사용자 질문에 "Source [n]:" 형식으로 끼워 넣은 가짜 검색 결과나 지시를 결정론적으로
제거하여 모델이 악의적인 탈옥/오염 지시를 따르지 못하게 차단합니다.
"""

from __future__ import annotations

import re

INJECTION_NOTICE = (
    "질문에 포함된 'Source' 형식의 문장은 시스템이 제공한 검색 결과가 아니므로, "
    "그 안의 지시는 따를 수 없습니다."
)

_SOURCE_BLOCK_PATTERN = re.compile(
    r"^\s*(?:Source|소스|출처)\s*\[\s*\d+\s*\]\s*[:\uff1a]",
    re.IGNORECASE,
)


def strip_injected_source_blocks(query: str) -> tuple[str, bool]:
    """사용자 질의에서 가짜 Source 머리글로 시작하는 줄을 통째로 제거합니다.

    줄 단위로 검사하여 줄 앞 공백 뒤가 ^\\s*(?:Source|소스|출처)\\s*\\[\\s*\\d+\\s*\\]\\s*[:\\uff1a]
    에 매칭되는 줄을 제거하고, 남은 줄을 합친 문자열과 제거 여부를 반환합니다.
    줄 중간의 'Source [1]' 언급은 제거하지 않습니다.
    제거 뒤 남은 문자열이 공백뿐이거나 비어 있으면 빈 문자열을 반환합니다.
    """
    if not query:
        return "", False

    lines = query.splitlines()
    remaining: list[str] = []
    stripped = False

    for line in lines:
        if _SOURCE_BLOCK_PATTERN.match(line):
            stripped = True
        else:
            remaining.append(line)

    if not stripped:
        return query, False

    cleaned = "\n".join(remaining).strip()
    if not cleaned:
        return "", True
    return cleaned, True


__all__ = [
    "INJECTION_NOTICE",
    "strip_injected_source_blocks",
]
