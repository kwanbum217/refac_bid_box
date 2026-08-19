"""
src/app/services/tools/automation_status_tool.py

자동화 상태 조회 도구 (원본 apps/chatbot/tools/automation_status_tool.py 1:1 이식).
job_id 미지정 시 활성 상태(running > queued > pending_confirmation) 우선으로
최신 작업을 찾아 단계별 진행도 차트와 함께 반환합니다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from src.app.models.chatbot import AutomationRequest
from src.app.services.automation_orchestrator import (
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_PENDING_CONFIRMATION,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    build_action_response,
    sync_automation_status,
)

ACTIVE_STATUSES = (STATUS_RUNNING, STATUS_QUEUED, STATUS_PENDING_CONFIRMATION)

STEP_ORDER = ("preflight", "collect", "rag", "predict", "inspect", "final")
STEP_STATUS_PROGRESS = {
    "success": 1.0,
    "succeeded": 1.0,
    "complete": 1.0,
    "completed": 1.0,
    "running": 0.5,
    "queued": 0.15,
    "pending": 0.15,
    "pending_confirmation": 0.15,
    "failed": 0.0,
    "failure": 0.0,
    "error": 0.0,
    "canceled": 0.0,
    "cancelled": 0.0,
}
DURATION_FALLBACK_TITLES = ("자동화 실행 소요 시간", "Harness 실행 소요 시간")


def _step_status_visualizations(result_payload: dict | None) -> list[dict[str, Any]]:
    steps = (result_payload or {}).get("steps") or {}
    if not isinstance(steps, dict) or not steps:
        return []

    ordered_names = [name for name in STEP_ORDER if name in steps]
    ordered_names.extend(name for name in steps if name not in ordered_names)

    labels: list[str] = []
    values: list[float] = []
    statuses: list[str] = []
    for name in ordered_names:
        step_payload = steps.get(name) or {}
        if not isinstance(step_payload, dict):
            continue
        status = str(step_payload.get("status") or "-").lower()
        labels.append(name)
        values.append(STEP_STATUS_PROGRESS.get(status, 0.25))
        statuses.append(status)

    if not labels:
        return []

    return [
        {
            "type": "chart",
            "chart_type": "bar",
            "title": "점검 단계 진행 상태",
            "labels": labels,
            "values": values,
            "unit": "",
            "x_label": "점검 단계",
            "y_label": "진행도 (0~1)",
            "statuses": statuses,
        }
    ]


def _is_duration_fallback_visualization(visualization: dict) -> bool:
    return str((visualization or {}).get("title") or "") in DURATION_FALLBACK_TITLES


def _status_label(status: str) -> str:
    labels = {
        STATUS_SUCCESS: "완료",
        STATUS_FAILED: "실패",
        STATUS_CANCELED: "중지",
        STATUS_PENDING_CONFIRMATION: "승인 대기",
        STATUS_RUNNING: "진행 중",
        STATUS_QUEUED: "대기 중",
    }
    return labels.get(status, status or "-")


def _prepend_status_summary(payload: dict, request_obj: AutomationRequest) -> None:
    summary = f"현재 점검 상태: {_status_label(request_obj.status)}(`{request_obj.status}`)"
    if request_obj.status == STATUS_SUCCESS:
        summary += "입니다."
    elif request_obj.status in ACTIVE_STATUSES:
        summary += "입니다. 아래 단계별 진행 상황을 확인해주세요."
    else:
        summary += "로 확인됩니다."

    answer = str(payload.get("answer") or "").strip()
    if answer and not answer.startswith("현재 점검 상태:"):
        payload["answer"] = f"{summary}\n\n{answer}"
    else:
        payload["answer"] = answer or summary


def _adapt_status_payload(
    payload: dict, request_obj: AutomationRequest, *, prefer_visualization: bool = False
) -> dict:
    _prepend_status_summary(payload, request_obj)

    step_visualizations = _step_status_visualizations(request_obj.result_payload)
    if step_visualizations:
        payload["visualizations"] = step_visualizations
    elif prefer_visualization:
        payload["visualizations"] = list(payload.get("visualizations") or [])
    else:
        payload["visualizations"] = [
            item
            for item in payload.get("visualizations") or []
            if not _is_duration_fallback_visualization(item)
        ]
    payload["message"] = "현재 자동화 상태를 확인했습니다."
    return payload


def _find_request(
    db: Session, job_id: str = "", *, user_id: int | None = None
) -> AutomationRequest | None:
    stmt = select(AutomationRequest)
    if user_id is not None:
        stmt = stmt.where(AutomationRequest.user_id == user_id)

    if job_id:
        return db.execute(stmt.where(AutomationRequest.request_id == job_id)).scalar_one_or_none()

    status_rank = case(
        (AutomationRequest.status == STATUS_RUNNING, 0),
        (AutomationRequest.status == STATUS_QUEUED, 1),
        (AutomationRequest.status == STATUS_PENDING_CONFIRMATION, 2),
        else_=3,
    )
    return db.execute(
        stmt.order_by(status_rank, AutomationRequest.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def execute(
    *,
    db: Session,
    job_id: str = "",
    prefer_visualization: bool = False,
    context: dict | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    user_id = (context or {}).get("user_id")
    request_obj = _find_request(db, str(job_id or "").strip(), user_id=user_id)

    if request_obj is None:
        return {
            "mode": "answer",
            "intent": "automation_status",
            "message": "조회 가능한 자동화 작업이 없습니다.",
            "answer": (
                "현재 연결된 점검 작업을 찾지 못했습니다.\n"
                "먼저 `전체 점검해줘`로 점검을 요청하거나, 실행 카드의 상태 보기에서 확인해주세요."
            ),
            "suggestions": ["전체 점검해줘", "실행 상태 보기"],
            "job": None,
            "visualizations": [],
            "result_payload": {},
            # 비밀번호가 아니라 확인 토큰 없음 표시입니다
            "confirmation_token": "",  # nosec B105
            "found": False,
        }

    sync_failed = False
    if request_obj.status in ACTIVE_STATUSES and request_obj.plan_execution_id:
        try:
            request_obj = sync_automation_status(db, request_obj)
        except Exception as exc:
            # 대화를 끊지 않되, 여기 담긴 상태가 최신이 아님을 호출자가 기계로
            # 알 수 있어야 합니다. 문구만 남기면 구분할 방법이 없습니다.
            sync_failed = True
            request_obj.result_summary = request_obj.result_summary or f"상태 동기화 보류: {exc}"

    payload = build_action_response(db, request_obj)
    payload = _adapt_status_payload(
        payload, request_obj, prefer_visualization=bool(prefer_visualization)
    )
    payload["found"] = True
    payload["sync_failed"] = sync_failed
    payload["status_is_stale"] = sync_failed
    if sync_failed:
        # 플래그만 payload 최상위에 두면 API 응답 경계에서 사라집니다.
        # 사용자는 낡은 상태를 현재 상태로 읽고, result_payload 를 보는
        # 호출자도 최신 여부를 알 수 없습니다. 둘 다 실어 보냅니다.
        result_payload = payload.get("result_payload")
        if not isinstance(result_payload, dict):
            result_payload = {}
        result_payload = dict(result_payload)
        result_payload["sync_failed"] = True
        result_payload["status_is_stale"] = True
        payload["result_payload"] = result_payload

        notice = "상태 동기화에 실패해 아래 정보는 최신이 아닐 수 있습니다."
        answer = str(payload.get("answer") or "").strip()
        if notice not in answer:
            payload["answer"] = f"{notice}\n\n{answer}".strip()
    return payload
