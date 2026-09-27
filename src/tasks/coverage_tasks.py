"""
src/tasks/coverage_tasks.py

낙찰결과 매칭률 감시 주간 크론 태스크.

개찰 완료 지 28일이 지난 최근 주의 대형 매칭률이 전년 동기보다 10%p 이상
낮으면 MLOps 웹훅 경고를 보낸다. 계산은 읽기 전용
src/app/services/result_coverage.py 에 위임하고, 여기서는 실행 순서와
알림 발신만 담당한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from src.app.core.db import SessionLocal
from src.app.core.observability import traced_worker_task
from src.app.services.result_coverage import (
    compute_result_match_rates,
    evaluate_match_rate_alerts,
)
from src.tasks.notifier import notify

logger = logging.getLogger(__name__)


def _format_rate(rate: float | None) -> str:
    return f"{rate * 100:.1f}%" if rate is not None else "측정 불가"


def _collect_snapshot() -> dict[str, Any]:
    db = SessionLocal()
    try:
        as_of = date.today()
        rows = compute_result_match_rates(db, as_of=as_of)
        alerts = evaluate_match_rate_alerts(rows)
        return {
            "status": "ok",
            "as_of": as_of.isoformat(),
            "alerts": alerts,
            "rows": len(rows),
        }
    finally:
        db.close()


@traced_worker_task
async def result_coverage_monitor_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매칭률 스냅샷을 계산하고 경고 대상이 있을 때만 한 번 알린다.

    DB 오류는 로그만 남기고 status error 로 반환한다. 예외를 올리면 워커의
    재시도 카운트를 소진하고 다른 감시 태스크를 방해하므로 삼킨다.
    """
    try:
        result = await asyncio.to_thread(_collect_snapshot)
    except Exception as exc:
        logger.exception("낙찰결과 매칭률 감시 실패")
        return {
            "status": "error",
            "as_of": date.today().isoformat(),
            "alerts": [],
            "rows": 0,
            "error": str(exc),
        }

    alerts = result["alerts"]
    if alerts:
        lines = []
        for alert in alerts:
            lines.append(
                f"{alert['category']} {alert['week_start']} 주 대형: "
                f"실측 {_format_rate(alert['rate'])} / 전년 {_format_rate(alert['baseline_rate'])} "
                f"(공고 {alert['announcements']:,}건)"
            )
        lines.append("")
        lines.append("상세: uv run python scripts/result_match_rate_report.py")
        await notify("낙찰결과 매칭률 경고", lines, level="warning")
    return result
