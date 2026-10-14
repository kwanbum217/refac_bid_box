"""공고 첨부파일과 원문 링크를 화면용으로 정리합니다.

공고 원본 `raw_data`(JSON)의 첨부파일 1~10번(`ntceSpecDocUrlN`·`ntceSpecFileNmN`),
표준공고문(`stdNtceDocUrl`), 나라장터 공고 원문(`bidNtceDtlUrl`)을 링크 목록으로 바꿉니다.
서버가 파일을 대신 내려받지 않고, 사용자가 나라장터에서 직접 내려받도록 URL 만 넘깁니다.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# 나라장터 원문만 통과시킵니다. 접두어 비교가 아니라 파싱한 scheme·hostname 을
# 정확히 비교해 `https://www.g2b.go.kr.evil.com` 같은 우회를 막습니다.
_ALLOWED_SCHEME = "https"
_ALLOWED_HOST = "www.g2b.go.kr"
_ATTACHMENT_COUNT = 10


def _allowed_url(value: Any) -> str | None:
    """허용된 나라장터 https URL 이면 정리한 문자열을, 아니면 None 을 돌려줍니다."""
    if not isinstance(value, str):
        return None
    if not value or value != value.strip():
        return None
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    try:
        parsed = urlparse(value)
        scheme = parsed.scheme
        host = parsed.hostname
        has_userinfo = parsed.username is not None or parsed.password is not None
    except ValueError:
        return None
    if scheme != _ALLOWED_SCHEME or host != _ALLOWED_HOST or has_userinfo:
        return None
    return value


def describe_announcement_links(raw_data: Any) -> dict[str, Any]:
    """첨부파일·표준공고문·나라장터 원문 링크를 번호 순서로 정리합니다.

    raw_data 가 dict 가 아니거나 값이 문자열이 아니어도 예외 없이 빈 결과를 돌려줍니다.
    허용되지 않은 URL 과 빈 값은 건너뛰고, 같은 URL 이 두 번 나오면 첫 번째만 남깁니다.
    이름이 비면 `첨부파일 <번호>` 로 채웁니다.
    """
    data = raw_data if isinstance(raw_data, dict) else {}
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for number in range(1, _ATTACHMENT_COUNT + 1):
        url = _allowed_url(data.get(f"ntceSpecDocUrl{number}"))
        if url is None or url in seen:
            continue
        name_value = data.get(f"ntceSpecFileNm{number}")
        name = name_value.strip() if isinstance(name_value, str) else ""
        files.append({"name": name or f"첨부파일 {number}", "url": url})
        seen.add(url)
    return {
        "files": files,
        "standard_notice_url": _allowed_url(data.get("stdNtceDocUrl")),
        "detail_url": _allowed_url(data.get("bidNtceDtlUrl")),
    }
