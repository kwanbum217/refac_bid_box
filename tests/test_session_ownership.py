"""
tests/test_session_ownership.py

동기 SQLAlchemy Session 의 소유권, 트랜잭션 경계 복구(pending-rollback 해제),
그리고 수집 오류 로깅 시 서비스 키 및 자격 증명 마스킹 검증 테스트입니다.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.app.models.bids import BidAnnouncement
from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.app.services.api_collector import (
    RangeCollectionError,
    mask_credentials,
)
from src.app.services.collector_service import _bulk_insert, collect_bids
from src.tasks import automation_tasks


@pytest.fixture
def worker_db(isolated_db, monkeypatch):
    """태스크가 여는 SessionLocal 을 isolated_db 엔진에 연결합니다."""
    engine = isolated_db.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(automation_tasks, "SessionLocal", factory)
    return isolated_db


def _add_pipeline_and_request(
    db, execution_id: str, request_id: str, run_mode: str = "manual_full"
) -> tuple[PipelineExecution, AutomationRequest]:
    execution = PipelineExecution(
        execution_id=execution_id,
        pipeline_name="BIDBOX_Personal_Pipeline_Staging",
        run_mode=run_mode,
        status="queued",
        source="chatbot",
    )
    request_obj = AutomationRequest(
        request_id=request_id,
        user_id=1,
        action_key="manual_full",
        status="queued",
    )
    db.add(execution)
    db.add(request_obj)
    db.commit()
    return execution, request_obj


@pytest.mark.asyncio
async def test_automation_pipeline_recovers_from_db_error_and_records_failure(worker_db):
    """DB 오류로 세션이 pending-rollback 상태가 되어도 예외 핸들러가 rollback 후

    PipelineExecution 상태와 AutomationRequest 실패 보고를 성공적으로 기록함을 증명합니다.
    """
    exec_id = "exec-db-err-001"
    req_id = "req-db-err-001"
    _add_pipeline_and_request(worker_db, exec_id, req_id, run_mode="manual_full")

    def failing_runner(db, **kwargs):
        # 의도적으로 잘못된 SQL을 실행해 세션을 에러 / pending-rollback 상태로 만듭니다.
        db.execute(text("SELECT * FROM non_existent_table_triggering_db_error"))
        return "never reached", {}

    runners = {"collect": failing_runner}

    with patch.object(automation_tasks, "STEP_RUNNERS", runners):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=exec_id,
            automation_request_id=req_id,
            run_mode="manual_full",
        )

    # 1. 반환값 검증
    assert result["status"] == "failed"
    assert "non_existent_table_triggering_db_error" in result["error"]

    # 2. PipelineExecution 레코드 상태 검증
    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution).filter(PipelineExecution.execution_id == exec_id).one()
    )
    assert execution.status == "failed"
    assert execution.ended_at is not None
    assert "non_existent_table_triggering_db_error" in (execution.logs_summary or "")

    # 3. AutomationRequest 레코드 상태 검증
    request_obj = (
        worker_db.query(AutomationRequest).filter(AutomationRequest.request_id == req_id).one()
    )
    assert request_obj.status == "failed"
    assert "실행 중 오류가 발생했습니다" in (request_obj.result_summary or "")


@pytest.mark.asyncio
async def test_automation_pipeline_thread_runner_exception_handling(worker_db):
    """동기 스레드 runner에서 일반 예외 발생 시 트랜잭션 rollback 후 상태가 기록된다."""
    exec_id = "exec-thread-err-002"
    req_id = "req-thread-err-002"
    _add_pipeline_and_request(worker_db, exec_id, req_id, run_mode="manual_full")

    def failing_sync_runner(db, **kwargs):
        raise ValueError("simulated synchronous worker error")

    runners = {"collect": failing_sync_runner}

    with patch.object(automation_tasks, "STEP_RUNNERS", runners):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id=exec_id,
            automation_request_id=req_id,
            run_mode="manual_full",
        )

    assert result["status"] == "failed"
    assert "simulated synchronous worker error" in result["error"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution).filter(PipelineExecution.execution_id == exec_id).one()
    )
    assert execution.status == "failed"
    assert "simulated synchronous worker error" in (execution.logs_summary or "")


def test_bulk_insert_rolls_back_on_error(isolated_db):
    """_bulk_insert 실행 중 DB 오류 발생 시 세션이 rollback 됨을 확인합니다."""
    # 정상 데이터 준비
    rows = [{"bid_ntce_no": "20260101001", "bid_ntce_ord": "00"}]

    # db.execute 가 오류를 던지도록 모킹
    with (
        patch.object(isolated_db, "execute", side_effect=RuntimeError("DB write failed")),
        pytest.raises(RuntimeError, match="DB write failed"),
    ):
        _bulk_insert(isolated_db, BidAnnouncement, rows)

    # rollback 이후 세션이 정상 쿼리를 수행할 수 있는지 검증
    assert isolated_db.scalar(text("SELECT 1")) == 1


@pytest.mark.asyncio
async def test_collect_bids_handles_dashboard_failure_cleanly(isolated_db, monkeypatch):
    """대시보드 통계 집계 중 DB 에러가 발생해도 세션이 rollback 되고 metrics 에 반영된다."""
    monkeypatch.setattr("src.app.services.collector_service.get_service_key", lambda: "mock_key")
    monkeypatch.setattr(
        "src.app.services.collector_service.resolve_collection_window",
        lambda *a, **k: ("20260101", "20260102", False),
    )
    monkeypatch.setattr(
        "src.app.services.collector_service.stream_bid_announcements",
        AsyncMock(return_value=10),
    )
    monkeypatch.setattr(
        "src.app.services.collector_service.stream_bid_data",
        AsyncMock(return_value=10),
    )
    monkeypatch.setattr(
        "src.app.services.collector_service.rebuild_bid_dataset_summaries",
        lambda db, datasets: (_ for _ in ()).throw(RuntimeError("Aggregation DB error")),
    )

    metrics = await collect_bids(
        isolated_db, categories=("Thng",), fetch_type="both", refresh_aggregates=True
    )
    assert metrics["cache_warmed"] is False
    assert metrics["announcement_count"] == 10
    assert metrics["result_count"] == 10

    # DB 세션이 pending-rollback 없이 정상 작동하는지 확인
    assert isolated_db.scalar(text("SELECT 1")) == 1


def test_mask_credentials_patterns():
    """자격 증명 관련 파라미터(serviceKey, key, apikey, token 등)가 정상 마스킹되는지 확인합니다."""
    # 1. serviceKey 쿼리 파라미터
    url1 = "https://apis.data.go.kr/1230000/as/ScsbidInfoService?serviceKey=MOCK_SECRET_KEY_123&pageNo=1"
    assert (
        mask_credentials(url1)
        == "https://apis.data.go.kr/1230000/as/ScsbidInfoService?serviceKey=***&pageNo=1"
    )

    # 2. apiKey 및 token 파라미터
    url2 = "https://api.example.com/v1/data?apiKey=SECRET_API_KEY&token=BEARER_XYZ&category=Thng"
    assert (
        mask_credentials(url2)
        == "https://api.example.com/v1/data?apiKey=***&token=***&category=Thng"
    )

    # 3. key 및 secret 파라미터
    url3 = "https://api.example.com/check?key=MOCK_KEY&secret=MOCK_SECRET&numOfRows=999"
    assert (
        mask_credentials(url3) == "https://api.example.com/check?key=***&secret=***&numOfRows=999"
    )

    # 4. httpx.HTTPStatusError 메시지 형태
    request = httpx.Request(
        "GET", "https://apis.data.go.kr/test?serviceKey=MOCK_SECRET_G2B&pageNo=2"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        masked_exc = mask_credentials(exc)
        assert "serviceKey=***" in masked_exc
        assert "MOCK_SECRET_G2B" not in masked_exc

    # 5. 빈 값 및 None 처리
    assert mask_credentials(None) == ""
    assert mask_credentials("일반 메시지입니다.") == "일반 메시지입니다."


@pytest.mark.asyncio
async def test_api_collector_logging_masks_service_key(caplog):
    """수집기 구간 오류 로깅 시 G2B 서비스 키가 로그에 남지 않고 마스킹됨을 증명합니다."""
    from src.app.services.api_collector import _run_ranges

    mock_key = "MOCK_SECRET_SERVICE_KEY_XYZ_123"
    error_url = f"https://apis.data.go.kr/1230000/ad/test?serviceKey={mock_key}&pageNo=1"

    request = httpx.Request("GET", error_url)
    response = httpx.Response(400, request=request)

    async def mock_fetch_paged(*args, **kwargs):
        response.raise_for_status()

    with (
        patch("src.app.services.api_collector._fetch_paged", side_effect=mock_fetch_paged),
        caplog.at_level(logging.ERROR),
        pytest.raises(RangeCollectionError),
    ):
        await _run_ranges(
            error_url,
            "20260101",
            "20260102",
            999,
            lambda item, raw: {},
            "입찰공고",
            lambda rows: None,
        )

    log_output = caplog.text
    assert "serviceKey=***" in log_output
    assert mock_key not in log_output


def test_report_db_error_does_not_raise(isolated_db):
    """_report 실행 중 DB 예외가 발생해도 예외를 삼키고 세션을 rollback 하여 호출부 세션을 보호합니다."""
    from src.tasks.automation_tasks import _report

    with patch(
        "src.tasks.automation_tasks.get_automation_request",
        side_effect=RuntimeError("DB query failed in report"),
    ):
        # 예외를 던지지 않고 정상 반환해야 함
        _report(isolated_db, "req-123", "step1", "success", "summary", {})

    # 세션이 rollback 되어 정상 쿼리가 가능함을 검증
    assert isolated_db.scalar(text("SELECT 1")) == 1


@pytest.mark.asyncio
async def test_collect_bids_handles_partial_failure_with_masked_error(isolated_db, monkeypatch):
    """수집 중 RangeCollectionError 발생 시 metrics 및 로그에 마스킹된 에러가 저장된다."""
    monkeypatch.setattr("src.app.services.collector_service.get_service_key", lambda: "mock_key")
    monkeypatch.setattr(
        "src.app.services.collector_service.resolve_collection_window",
        lambda *a, **k: ("20260101", "20260102", False),
    )

    range_err = RangeCollectionError("입찰공고", 5, [("20260101", "20260102")])
    monkeypatch.setattr(
        "src.app.services.collector_service.stream_bid_announcements",
        AsyncMock(side_effect=range_err),
    )
    monkeypatch.setattr(
        "src.app.services.collector_service.stream_bid_data",
        AsyncMock(return_value=10),
    )

    metrics = await collect_bids(
        isolated_db, categories=("Thng",), fetch_type="both", refresh_aggregates=False
    )
    assert metrics["status"] == "partial_success"
    assert metrics["announcement_count"] == 5
    assert metrics["result_count"] == 10
    assert "announcement_error" in metrics["categories"]["Thng"]
    assert isolated_db.scalar(text("SELECT 1")) == 1
