"""
src/tasks/coverage_tasks.py

낙찰결과 매칭률 감시 주간 크론 태스크.

개찰 완료 지 28일이 지난 최근 주와 직전 주의 대형 보정 매칭률이 5주 합산 전년
동기 기저보다 10%p 이상 2주 연속 낮으면 MLOps 웹훅 경고를 보낸다. 계산은 읽기
전용 src/app/services/result_coverage.py 에 위임하고, 여기서는 실행 순서와
알림 발신만 담당한다.

RESULT_COVERAGE_ALERT_SUPPRESS 로 지정한 원인 확인 경고는 만료일까지 알림 본문에서
빼고, 억제된 경고만 남으면 알림을 보내지 않는다. 억제 여부와 무관하게 판정 목록
전체는 반환 dict 의 alerts 에 그대로 담는다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.core.observability import traced_worker_task
from src.app.services.result_coverage import (
    compute_result_match_rates,
    evaluate_match_rate_alerts,
    parse_alert_suppressions,
)
from src.tasks.notifier import notify
from src.tasks.scheduled_tasks import (
    RESULT_COVERAGE_CLAIM_KEY,
    RESULT_COVERAGE_CLAIM_TTL_SECONDS,
    ScheduleClaimResult,
    ScheduleClaimStatus,
    _record_schedule,
    acquire_schedule_claim,
    release_schedule_claim,
)

logger = logging.getLogger(__name__)


def _format_rate(rate: float | None) -> str:
    return f"{rate * 100:.1f}%" if rate is not None else "측정 불가"


def _band_label(band: Any) -> str:
    """규모 표기입니다. 경고 판정은 대형 행에서만 나오므로 미표기는 대형으로 봅니다."""
    return "소형" if band == "small" else "대형"


def _format_suppressed_summary(suppressed: list[dict[str, Any]]) -> str:
    """억제 중인 경고를 알림 마지막 줄로 요약합니다. 예: 억제 중: Servc 대형(~2026-11-30)"""
    entries = ", ".join(
        f"{alert['category']} {_band_label(alert.get('band'))}(~{alert.get('suppressed_until')})"
        for alert in suppressed
    )
    return f"억제 중: {entries}"


def _collect_snapshot() -> dict[str, Any]:
    db = SessionLocal()
    try:
        as_of = date.today()
        rows = compute_result_match_rates(db, as_of=as_of)
        suppressions = parse_alert_suppressions(settings.RESULT_COVERAGE_ALERT_SUPPRESS)
        alerts = evaluate_match_rate_alerts(rows, suppressions=suppressions, today=as_of)
        return {
            "status": "ok",
            "as_of": as_of.isoformat(),
            "alerts": alerts,
            "rows": len(rows),
        }
    finally:
        db.close()


def _acquire_result_coverage_claim() -> ScheduleClaimResult:
    """커버리지 크론과 기동 따라잡기가 공유하는 선점을 원자적으로 획득합니다.

    TTL 은 잡 타임아웃 이상으로 잡습니다. Redis 에 접근할 수 없으면 호출부가
    경고를 남기고 선점 없이 진행하도록 결과를 그대로 돌려줍니다.
    """
    from src.tasks.worker import MONITOR_CATCHUP_JOB_TIMEOUT_SECONDS

    ttl = max(int(MONITOR_CATCHUP_JOB_TIMEOUT_SECONDS), RESULT_COVERAGE_CLAIM_TTL_SECONDS)
    return acquire_schedule_claim(
        "result_coverage_monitor",
        key=RESULT_COVERAGE_CLAIM_KEY,
        ttl_seconds=ttl,
    )


async def _run_result_coverage_monitor() -> dict[str, Any]:
    """선점을 획득한 뒤 실행되는 매칭률 감시 본문입니다."""
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
    active_alerts = [alert for alert in alerts if not alert.get("suppressed")]
    suppressed_alerts = [alert for alert in alerts if alert.get("suppressed")]
    if active_alerts:
        lines = []
        for alert in active_alerts:
            lines.append(
                f"{alert['category']} {alert['week_start']} 주 대형: "
                f"보정 {_format_rate(alert['adjusted_rate'])} / "
                f"다주 기저 {_format_rate(alert['baseline_multi_rate'])}, 2주 연속 "
                f"(실측 {_format_rate(alert['rate'])} / 전년 {_format_rate(alert['baseline_rate'])}, "
                f"공고 {alert['announcements']:,}건)"
            )
        lines.append("")
        lines.append("상세: uv run python scripts/result_match_rate_report.py")
        if suppressed_alerts:
            lines.append(_format_suppressed_summary(suppressed_alerts))
        await notify("낙찰결과 매칭률 경고", lines, level="warning")
    elif suppressed_alerts:
        logger.info(
            "억제된 낙찰결과 매칭률 경고 %d건만 있어 알림을 보내지 않습니다: %s",
            len(suppressed_alerts),
            _format_suppressed_summary(suppressed_alerts),
        )
    return result


@traced_worker_task
@_record_schedule("result_coverage_monitor", success_statuses=frozenset({"ok"}))
async def result_coverage_monitor_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매칭률 스냅샷을 계산하고 경고 대상이 있을 때만 한 번 알린다.

    DB 오류는 로그만 남기고 status error 로 반환한다. 예외를 올리면 워커의
    재시도 카운트를 소진하고 다른 감시 태스크를 방해하므로 삼킨다.
    크론과 기동 따라잡기가 같은 선점 키를 공유해 같은 슬롯 감시가 겹치지 않는다.
    """
    claim = _acquire_result_coverage_claim()
    if claim.status == ScheduleClaimStatus.ALREADY_CLAIMED:
        logger.info("낙찰결과 매칭률 감시가 이미 실행 중이어서 건너뜁니다.")
        return {"status": "skipped", "reason": "already_running"}
    if not claim.acquired:
        logger.warning(
            "Redis 접근 불가로 낙찰결과 매칭률 감시 선점 없이 진행합니다 (key=%s, status=%s)",
            RESULT_COVERAGE_CLAIM_KEY,
            claim.status.value,
        )

    try:
        return await _run_result_coverage_monitor()
    finally:
        # 성공, 실패, 예외, 취소 어느 경로로 끝나도 자기 토큰일 때만 해제합니다.
        if claim.acquired and claim.token:
            release_schedule_claim(key=RESULT_COVERAGE_CLAIM_KEY, token=claim.token)
