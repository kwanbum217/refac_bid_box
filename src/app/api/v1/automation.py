"""
src/app/api/v1/automation.py

자동화 실행 API (원본 apps/chatbot/urls.py 자동화 8개 라우트 1:1 대응).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `chatbot:run_collect_bids` | `POST /api/v1/automation/run/collect-bids` |
| `chatbot:run_update_kb` | `POST /api/v1/automation/run/update-kb` |
| `chatbot:run_prediction` | `POST /api/v1/automation/run/predict` |
| `chatbot:run_manual_full` | `POST /api/v1/automation/run/manual-full` |
| 신규 재학습 실행 | `POST /api/v1/automation/run/retrain` |
| `chatbot:automation_job_confirm` | `POST /api/v1/automation/job/{job_id}/confirm` |
| `chatbot:automation_job_status` | `GET /api/v1/automation/job/{job_id}/status` |
| `chatbot:automation_job_cancel` | `POST /api/v1/automation/job/{job_id}/cancel` |
| `chatbot:automation_job_callback` | `POST /api/v1/automation/job/{job_id}/callback` |
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import require_current_user
from src.app.core.db import get_db
from src.app.models.accounts import CustomUser
from src.app.models.chatbot import AutomationRequest
from src.app.services.automation_orchestrator import (
    AutomationError,
    apply_callback_payload,
    build_action_response,
    cancel_automation_request,
    confirm_automation_request,
    create_action_request,
    get_automation_request,
    resolve_confirmation_token,
    sync_automation_status,
    verify_callback_token,
)
from src.app.services.tools.kb_status_tool import (
    build_kb_status_summary,
    get_latest_kb_status_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation", tags=["Automation"])


def _append_kb_status(answer_text: str, kb_status: dict | None) -> str:
    summary = build_kb_status_summary(kb_status)
    return f"{answer_text}\n\n{summary}" if summary else answer_text


def _require_request(db: Session, job_id: str, user: CustomUser | None = None) -> AutomationRequest:
    request_obj = get_automation_request(db, job_id)
    if request_obj is None:
        raise HTTPException(status_code=404, detail="자동화 요청을 찾을 수 없습니다.")
    # 원본은 user=request.user 로 조회 범위를 제한한다.
    if user is not None and request_obj.user_id not in (None, user.id):
        raise HTTPException(status_code=404, detail="자동화 요청을 찾을 수 없습니다.")
    return request_obj


def _envelope(db: Session, request_obj: AutomationRequest) -> dict[str, Any]:
    action_payload = build_action_response(db, request_obj)
    kb_status = get_latest_kb_status_payload(db)
    return {
        "status": "success",
        "mode": action_payload["mode"],
        "intent": action_payload["intent"],
        "answer": _append_kb_status(action_payload["answer"], kb_status),
        "message": action_payload["message"],
        "job": action_payload["job"],
        "suggestions": action_payload["suggestions"],
        "advisory_signals": [],
        "visualizations": action_payload["visualizations"],
        "result_payload": action_payload["result_payload"],
        "confirmation_token": action_payload["confirmation_token"],
        "kb_status": kb_status,
    }


def _run_automation_by_action(
    db: Session, action_key: str, reason: str, user: CustomUser
) -> dict[str, Any]:
    try:
        request_obj = create_action_request(
            db,
            action_key=action_key,
            message=reason or action_key,
            user_id=user.id,
            payload={"source": "automation_api", "reason": reason},
        )
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _envelope(db, request_obj)


@router.post("/run/collect-bids", summary="입찰 수집 실행")
def run_collect_bids_api(
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    return _run_automation_by_action(db, "collect_refresh", reason, user)


@router.post("/run/update-kb", summary="지식베이스 갱신 실행")
def run_update_kb_api(
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    return _run_automation_by_action(db, "kb_refresh", reason, user)


@router.post("/run/predict", summary="예측 모델 검증 실행")
def run_prediction_api(
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    return _run_automation_by_action(db, "prediction_validate", reason, user)


@router.post("/run/manual-full", summary="전체 검증 실행")
def run_manual_full_api(
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    return _run_automation_by_action(db, "full_validation", reason, user)


@router.post("/run/retrain", summary="예측 모델 재학습 실행")
def run_model_retrain_api(
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """재학습은 고비용 작업이므로 확인 API 호출 전에는 큐에 넣지 않습니다."""
    return _run_automation_by_action(db, "model_retrain", reason, user)


@router.post("/job/{job_id}/confirm", summary="고비용 실행 확인")
def automation_job_confirm_api(
    job_id: str,
    confirmation_token: str = Body("", embed=True),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    request_obj = _require_request(db, job_id, user)
    if confirmation_token:
        try:
            resolved_job_id = resolve_confirmation_token(confirmation_token)
        except AutomationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if resolved_job_id != str(job_id):
            raise HTTPException(status_code=403, detail="확인 토큰이 일치하지 않습니다.")
    return _envelope(db, confirm_automation_request(db, request_obj))


@router.get("/job/{job_id}/status", summary="자동화 실행 상태 조회")
def automation_job_status_api(
    job_id: str,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    request_obj = sync_automation_status(db, _require_request(db, job_id, user))
    envelope = _envelope(db, request_obj)
    envelope["data"] = {
        "job_id": str(request_obj.request_id),
        "intent": request_obj.intent_type,
        "pipeline": request_obj.pipeline_name,
        "action_key": request_obj.action_key,
        "status": request_obj.status,
        "plan_execution_id": request_obj.plan_execution_id,
        "execution_url": request_obj.execution_url,
        "requires_confirmation": request_obj.requires_confirmation,
        "created_at": request_obj.created_at.isoformat() if request_obj.created_at else None,
        "confirmed_at": request_obj.confirmed_at.isoformat() if request_obj.confirmed_at else None,
        "started_at": request_obj.started_at.isoformat() if request_obj.started_at else None,
        "completed_at": request_obj.completed_at.isoformat() if request_obj.completed_at else None,
        "result_summary": request_obj.result_summary,
        "result_payload": request_obj.result_payload,
        "error_message": request_obj.error_message,
    }
    return envelope


@router.post("/job/{job_id}/cancel", summary="자동화 실행 중지")
def automation_job_cancel_api(
    job_id: str,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    request_obj = _require_request(db, job_id, user)
    return _envelope(db, cancel_automation_request(db, request_obj))


@router.post("/job/{job_id}/callback", summary="워커 단계별 결과 콜백")
def automation_job_callback_api(
    job_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    x_bidbox_callback_token: str = Header("", alias="X-BIDBOX-CALLBACK-TOKEN"),
    db: Session = Depends(get_db),
):
    request_obj = _require_request(db, job_id)
    if not verify_callback_token(str(job_id), x_bidbox_callback_token.strip()):
        raise HTTPException(status_code=403, detail="유효하지 않은 callback 토큰입니다.")
    apply_callback_payload(db, request_obj, payload)
    return {"status": "success"}
