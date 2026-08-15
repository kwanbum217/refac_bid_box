"""
경로 접근 허용 판정과 감사 지표 수치 집계를 수행하는 유틸리티 모듈입니다.
"""

from __future__ import annotations

import re
from typing import Any


def validate_window_size(window: int, min_w: int = 1, max_w: int = 100) -> bool:
    """윈도우 크기가 허용 범위 내에 있는지 검증합니다."""
    return min_w <= window <= max_w


def extract_metric_total(records: list[dict[str, Any]]) -> float:
    """레코드 목록에서 metric_value 필드를 합산합니다."""
    total = 0.0
    for record in records:
        val = record.get("metric_value", 0.0)
        total += float(val)
    return total


def parse_and_accumulate_scores(items: list[Any]) -> float:
    """점수 목록을 누적 합산하며 불리언 값은 제외합니다."""
    total = 0.0
    for item in items:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            total += float(item)
    return total


def match_task_identifier(token: str) -> bool:
    """작업 식별자 형식이 'task_' 접두사와 12자리 16진수인지 정규식으로 검증합니다."""
    return bool(re.match(r"^task_[a-f0-9]{12}$", token))


def truncate_summary_text(summary: str, max_chars: int | None = None) -> str:
    """요약 텍스트가 상한을 초과하면 절단합니다."""
    if max_chars is not None and len(summary) > max_chars:
        return summary[:max_chars]
    return summary


def execute_safely_and_collect(records: list[dict[str, Any]]) -> dict[str, Any]:
    """레코드 처리 중 예외가 발생하면 에러 상태를 안전하게 반환합니다."""
    try:
        if not records:
            raise ValueError("레코드 목록이 비어 있습니다")
        return {"status": "success", "count": len(records)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
