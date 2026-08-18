"""
tests/test_automation_collect_status_propagation.py

수집 스텝(collect) 결과 상태(success, partial_success, failed, error) 전파 및
PipelineExecution, AutomationRequest callback 상태 일치성 회귀 테스트.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.tasks import automation_tasks


@pytest.fixture
def worker_db(isolated_db, monkeypatch):
    """태스크는 SessionLocal 을 직접 열므로 인메모리 엔진에 묶어 줍니다."""
    engine = isolated_db.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(automation_tasks, "SessionLocal", factory)
    return isolated_db


def _add_execution(db, execution_id: str, run_mode: str) -> PipelineExecution:
    row = PipelineExecution(
        execution_id=execution_id,
        pipeline_name="BIDBOX_Personal_Pipeline_Staging",
        run_mode=run_mode,
        status="queued",
        source="chatbot",
    )
    db.add(row)
    db.commit()
    return row


def _add_request(db, request_id: str, action_key: str = "collect_refresh") -> AutomationRequest:
    req = AutomationRequest(
        request_id=request_id,
        user_id=1,
        intent_type="data_collection",
        action_key=action_key,
        requested_text="수집 테스트",
        status="running",
        requires_confirmation=False,
    )
    db.add(req)
    db.commit()
    return req


@pytest.mark.asyncio
async def test_collect_status_success_propagation(worker_db, monkeypatch):
    """수집 결과가 success 일 때 수집 스텝과 최종 상태가 모두 success 로 기록된다."""
    execution_id = "test-exec-success-001"
    request_id = "test-req-success-001"
    _add_execution(worker_db, execution_id, "collect_only")
    _add_request(worker_db, request_id, action_key="collect_refresh")

    mock_collect_metrics = {
        "status": "success",
        "start_date": "20260811",
        "end_date": "20260811",
        "fetch_type": "both",
        "announcement_count": 10,
        "result_count": 5,
        "total_records": 15,
        "attempted": 2,
        "failed_count": 0,
        "categories": {
            "servc": {"announcement_count": 10, "result_count": 5},
        },
    }

    with patch(
        "src.app.services.collector_service.collect_bids", new_callable=AsyncMock
    ) as mock_collect:
        mock_collect.return_value = mock_collect_metrics
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=execution_id,
            run_mode="collect_only",
            automation_request_id=request_id,
        )

    assert result["status"] == "success"
    assert result["completed_steps"] == ["collect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == execution_id)
        .one()
    )
    assert execution.status == "success"
    assert execution.stage_status == "success"

    req = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == request_id).one()
    )
    assert req.status == "success"
    steps = req.result_payload.get("steps", {})
    assert steps["collect"]["status"] == "success"
    assert steps["collect"]["metrics"]["attempted"] == 2
    assert steps["collect"]["metrics"]["failed_count"] == 0
    assert steps["collect"]["metrics"]["announcement_count"] == 10


@pytest.mark.asyncio
async def test_collect_status_partial_success_propagation(worker_db, monkeypatch):
    """수집 결과가 partial_success 일 때 metrics 가 보존되고 최종 status 는 failed 로 기록된다."""
    execution_id = "test-exec-partial-001"
    request_id = "test-req-partial-001"
    _add_execution(worker_db, execution_id, "refresh_data")
    _add_request(worker_db, request_id, action_key="data_refresh")

    mock_collect_metrics = {
        "status": "partial_success",
        "start_date": "20260811",
        "end_date": "20260811",
        "fetch_type": "both",
        "announcement_count": 5,
        "result_count": 0,
        "total_records": 5,
        "attempted": 2,
        "failed_count": 1,
        "categories": {
            "servc": {"announcement_count": 5, "result_count": 0},
            "cnstwk": {"announcement_count": 0, "result_count": 0, "announcement_error": "timeout"},
        },
    }

    def dummy_search(db, **kwargs):
        return ("search step ok", {"announcements": 5})

    def dummy_rag(db, **kwargs):
        return ("rag step ok", {"vector_count": 10})

    def dummy_inspect(db, **kwargs):
        return ("inspect step ok", {})

    with (
        patch(
            "src.app.services.collector_service.collect_bids", new_callable=AsyncMock
        ) as mock_collect,
        patch.dict(
            automation_tasks.STEP_RUNNERS,
            {
                "collect": automation_tasks._step_collect,
                "search": dummy_search,
                "rag": dummy_rag,
                "inspect": dummy_inspect,
            },
        ),
    ):
        mock_collect.return_value = mock_collect_metrics
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=execution_id,
            run_mode="refresh_data",
            automation_request_id=request_id,
        )

    assert result["status"] == "failed"
    assert result["completed_steps"] == ["collect", "search", "rag", "inspect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == execution_id)
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_status == "failed"

    req = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == request_id).one()
    )
    assert req.status == "failed"
    steps = req.result_payload.get("steps", {})
    assert steps["collect"]["status"] == "partial_success"
    assert steps["collect"]["metrics"]["attempted"] == 2
    assert steps["collect"]["metrics"]["failed_count"] == 1
    assert "categories" in steps["collect"]["metrics"]
    assert steps["collect"]["metrics"]["categories"]["cnstwk"]["announcement_error"] == "timeout"


@pytest.mark.asyncio
async def test_collect_status_failed_propagation(worker_db, monkeypatch):
    """수집 결과가 failed 일 때 수집 스텝 후 즉시 중단되고 status 는 failed 로 전파된다."""
    execution_id = "test-exec-failed-001"
    request_id = "test-req-failed-001"
    _add_execution(worker_db, execution_id, "refresh_data")
    _add_request(worker_db, request_id, action_key="data_refresh")

    mock_collect_metrics = {
        "status": "failed",
        "start_date": "20260811",
        "end_date": "20260811",
        "fetch_type": "both",
        "announcement_count": 0,
        "result_count": 0,
        "total_records": 0,
        "attempted": 2,
        "failed_count": 2,
        "categories": {
            "servc": {"announcement_error": "500 Internal Server Error"},
            "cnstwk": {"result_error": "500 Internal Server Error"},
        },
    }

    def dummy_rag(db, **kwargs):
        return ("rag step ok", {})

    with (
        patch(
            "src.app.services.collector_service.collect_bids", new_callable=AsyncMock
        ) as mock_collect,
        patch.dict(
            automation_tasks.STEP_RUNNERS,
            {"collect": automation_tasks._step_collect, "rag": dummy_rag},
        ),
    ):
        mock_collect.return_value = mock_collect_metrics
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=execution_id,
            run_mode="refresh_data",
            automation_request_id=request_id,
        )

    assert result["status"] == "failed"
    assert result["completed_steps"] == ["collect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == execution_id)
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_status == "failed"

    req = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == request_id).one()
    )
    assert req.status == "failed"
    steps = req.result_payload.get("steps", {})
    assert steps["collect"]["status"] == "failed"
    assert steps["collect"]["metrics"]["attempted"] == 2
    assert steps["collect"]["metrics"]["failed_count"] == 2
    assert steps["collect"]["metrics"]["collector_available"] is False


@pytest.mark.asyncio
async def test_collect_status_error_servicekey_compatibility(worker_db, monkeypatch):
    """serviceKey 미설정 error 시 기존 호환성을 유지하며 collector_available=False 및 failed 로 처리된다."""
    execution_id = "test-exec-error-001"
    request_id = "test-req-error-001"
    _add_execution(worker_db, execution_id, "collect_only")
    _add_request(worker_db, request_id, action_key="collect_refresh")

    mock_collect_metrics = {
        "status": "error",
        "message": "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.",
        "announcement_count": 0,
        "result_count": 0,
        "total_records": 0,
        "attempted": 0,
        "failed_count": 0,
    }

    with patch(
        "src.app.services.collector_service.collect_bids", new_callable=AsyncMock
    ) as mock_collect:
        mock_collect.return_value = mock_collect_metrics
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=execution_id,
            run_mode="collect_only",
            automation_request_id=request_id,
        )

    assert result["status"] == "failed"
    assert result["completed_steps"] == ["collect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == execution_id)
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_status == "error"

    req = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == request_id).one()
    )
    assert req.status == "failed"
    steps = req.result_payload.get("steps", {})
    assert steps["collect"]["status"] == "error"
    assert steps["collect"]["metrics"]["collector_available"] is False
    assert "serviceKey" in steps["collect"]["metrics"]["message"]


@pytest.mark.asyncio
async def test_collect_status_unknown_malformed_fail_closed(worker_db, monkeypatch):
    """알 수 없거나 잘못된 collector status 가 반환되면 silent success 가 아닌 fail-closed 처리된다."""
    execution_id = "test-exec-unknown-001"
    request_id = "test-req-unknown-001"
    _add_execution(worker_db, execution_id, "refresh_data")
    _add_request(worker_db, request_id, action_key="data_refresh")

    mock_collect_metrics = {
        "status": "unknown_invalid_status",
        "total_records": 0,
    }

    def dummy_search(db, **kwargs):
        return ("search step ok", {})

    with (
        patch(
            "src.app.services.collector_service.collect_bids", new_callable=AsyncMock
        ) as mock_collect,
        patch.dict(
            automation_tasks.STEP_RUNNERS,
            {
                "collect": automation_tasks._step_collect,
                "search": dummy_search,
            },
        ),
    ):
        mock_collect.return_value = mock_collect_metrics
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=execution_id,
            run_mode="refresh_data",
            automation_request_id=request_id,
        )

    assert result["status"] == "failed"
    assert result["completed_steps"] == ["collect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == execution_id)
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_status == "failed"

    req = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == request_id).one()
    )
    assert req.status == "failed"
    steps = req.result_payload.get("steps", {})
    assert steps["collect"]["status"] == "failed"
    assert steps["collect"]["metrics"]["collector_available"] is False
