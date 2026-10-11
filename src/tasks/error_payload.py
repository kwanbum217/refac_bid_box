"""
src/tasks/error_payload.py

작업 결과 payload 에 담을 예외 요약을 만듭니다.

예외 원문(str(exc))을 그대로 결과에 넣으면 serviceKey 가 든 URL, 파일 경로,
호스트명, 여러 줄 SQL 이 automation_requests 결과·콜백·API 응답으로 새어
나갑니다. 결과에는 예외 분류 코드(error_type)와 마스킹된 한 줄 요약(error)만
담고, 원문은 호출부의 logger.exception 으로만 남깁니다.
"""

from __future__ import annotations

import re

from src.app.services.api_collector import mask_credentials

MAX_ERROR_SUMMARY_LENGTH = 200

# 절대 경로(Windows/POSIX)와 점 확장자를 가진 상대 경로를 지웁니다. URL 의
# 스킴 구분자(://)는 건드리지 않도록 앞 문자를 좁게 봅니다.
_PATH_RE = re.compile(
    r"[A-Za-z]:\\[^\s'\"<>|]+"
    r"|(?<![\w:])/(?:[\w.\-]+/)+[\w.\-]*"
    r"|(?<![\w./-])(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]+"
)


def summarize_error(exc: BaseException) -> str:
    """예외를 결과 payload 용 마스킹된 한 줄 요약으로 바꿉니다.

    첫 줄만 쓰고 자격 증명과 경로를 지운 뒤 200자로 줄입니다. 원문 전체는
    호출부의 logger.exception 이 담당합니다.
    """
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    summary = lines[0] if lines else type(exc).__name__
    summary = mask_credentials(summary)
    summary = _PATH_RE.sub("<path>", summary)
    if len(summary) > MAX_ERROR_SUMMARY_LENGTH:
        summary = summary[: MAX_ERROR_SUMMARY_LENGTH - 3] + "..."
    return summary


def safe_error(exc: BaseException) -> dict[str, str]:
    """결과 dict 에 병합할 예외 분류 코드와 마스킹된 요약을 만듭니다."""
    return {"error_type": type(exc).__name__, "error": summarize_error(exc)}
