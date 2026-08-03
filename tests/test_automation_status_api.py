"""
tests/test_automation_status_api.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 중 상태 조회/콜백 이식.

원본은 Harness 가 콜백을 보내는 구조였고 이식본은 Arq 워커가 같은 계약으로
보고합니다. 검증 대상은 "워커 보고가 누적되어 최종 상태와 결과 화면으로
이어지는가" 이므로 Harness 고유 필드만 제외하고 그대로 옮겼습니다.
"""

from datetime import timedelta
from unittest.mock import patch

from src.app.core.timeutil import utcnow
from src.app.models.chatbot import AutomationRequest, KnowledgeBaseStatus, PipelineExecution
from src.app.services.action_catalog import get_action
from src.app.services.automation_orchestrator import make_callback_token


def _full_validation_pipeline() -> str:
    """재사용 조회는 pipeline_name 이 일치해야 하므로 카탈로그 값을 그대로 씁니다."""
    return get_action("full_validation").pipeline_id


def _plan_execution_id(db, job_id: str) -> str:
    request_obj = db.query(AutomationRequest).filter_by(request_id=job_id).one()
    db.refresh(request_obj)
    return request_obj.plan_execution_id

VALID_SIGNUP = {
    "username": "auto-status-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "auto-status@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _login(client) -> int:
    signup = client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "auto-status-user", "password": "StrongPass123!!"},
    )
    return signup.json()["id"]


def _seed_kb_status(db) -> KnowledgeBaseStatus:
    kb = KnowledgeBaseStatus(
        kb_version="bidding_kb",
        status="ready",
        source_bid_count=321,
        last_pipeline_run_id="exec_002",
        updated_at=utcnow(),
    )
    db.add(kb)
    db.commit()
    return kb


RAG_CALLBACK = {
    "step": "rag",
    "status": "success",
    "summary": "최근 1일 데이터 기준 128건 임베딩을 완료했습니다.",
    "metrics": {
        "source_bid_count": 128,
        "last_embedding_at": "2026-05-04T03:30:00+00:00",
    },
    "artifacts": {},
    "final": False,
}

FINAL_CALLBACK = {
    "step": "final",
    "status": "success",
    "summary": "데이터 갱신과 최종 점검이 완료되었습니다.",
    "metrics": {"completed_steps": ["preflight", "collect", "rag", "inspect"]},
    "artifacts": {
        "steps": {
            "inspect": {
                "status": "success",
                "summary": "Final Inspector PASS",
                "metrics": {
                    "today_rows": 12,
                    "vector_count": 128,
                    "api_check": True,
                    "model_check": True,
                },
                "artifacts": {},
            }
        }
    },
    "final": True,
}


# --------------------------------------------------------------------------- #
# 콜백 인증
# --------------------------------------------------------------------------- #


def test_callback_rejects_invalid_signature(client, isolated_db):
    """원본 test_callback_rejects_invalid_signature 대응."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-callback-001",
            user_id=user_id,
            intent_type="data_refresh",
            action_key="data_refresh",
            requested_text="오늘 데이터 갱신해줘",
            pipeline_name="bidbox_staging",
            status="running",
            plan_execution_id="plan-003",
            harness_execution_id="plan-003",
        )
    )
    isolated_db.commit()

    response = client.post(
        "/api/v1/automation/job/job-callback-001/callback",
        json={},
        headers={"X-BIDBOX-CALLBACK-TOKEN": "invalid"},
    )
    assert response.status_code == 403


def test_callback_accepts_valid_signature(client, isolated_db):
    """유효한 토큰은 통과해야 합니다 (거부 테스트의 대조군)."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-callback-002",
            user_id=user_id,
            intent_type="data_refresh",
            action_key="data_refresh",
            requested_text="오늘 데이터 갱신해줘",
            pipeline_name="bidbox_staging",
            status="running",
        )
    )
    isolated_db.commit()

    response = client.post(
        "/api/v1/automation/job/job-callback-002/callback",
        json=RAG_CALLBACK,
        headers={"X-BIDBOX-CALLBACK-TOKEN": make_callback_token("job-callback-002")},
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# 상태 조회
# --------------------------------------------------------------------------- #


def test_status_endpoint_returns_terminal_answer_and_visualizations(client, isolated_db):
    """원본 test_status_endpoint_returns_terminal_answer_and_visualizations 대응.

    워커가 rag/final 두 건을 보고하면 상태 조회가 완료 화면으로 전환되어야 합니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-status-001",
            user_id=user_id,
            intent_type="data_refresh",
            action_key="data_refresh",
            requested_text="오늘 데이터 갱신해서 그래프 보여줘",
            followup_query="오늘 데이터 갱신해서 그래프 보여줘",
            pipeline_name="bidbox_staging",
            payload={"callback_mode": "callback", "callback_configured": True},
            status="running",
            plan_execution_id="plan-004",
            harness_execution_id="plan-004",
        )
    )
    isolated_db.add(
        PipelineExecution(
            execution_id="plan-004",
            pipeline_name="bidbox_staging",
            run_mode="refresh_data",
            status="running",
            source="chatbot",
        )
    )
    isolated_db.commit()

    token = make_callback_token("job-status-001")
    for callback_payload in (RAG_CALLBACK, FINAL_CALLBACK):
        response = client.post(
            "/api/v1/automation/job/job-status-001/callback",
            json=callback_payload,
            headers={"X-BIDBOX-CALLBACK-TOKEN": token},
        )
        assert response.status_code == 200

    response = client.get("/api/v1/automation/job/job-status-001/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "result"
    assert payload["job"]["status"] == "success"
    assert payload["job"]["callback_mode"] == "callback"
    assert "완료" in payload["answer"]
    assert "insights" in payload["result_payload"]
    assert "recommended_actions" in payload["result_payload"]

    # 두 건의 워커 보고가 모두 누적되어야 합니다.
    request_obj = (
        isolated_db.query(AutomationRequest).filter_by(request_id="job-status-001").one()
    )
    isolated_db.refresh(request_obj)
    assert set(request_obj.result_payload["steps"]) == {"rag", "final"}


def test_status_endpoint_includes_failed_job_error_details(client, isolated_db):
    """원본 test_status_endpoint_includes_failed_job_error_details 대응."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-status-002",
            user_id=user_id,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            pipeline_name="bidbox_staging",
            payload={"callback_mode": "polling", "callback_configured": False},
            status="failed",
            result_summary="자동화 실행 요청을 보내지 못했습니다.",
            error_message="CALLBACK_URL 값이 null로 해석되었습니다.",
        )
    )
    isolated_db.commit()

    response = client.get("/api/v1/automation/job/job-status-002/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "error"
    assert payload["job"]["status"] == "failed"
    assert "자동화 실행 요청" in payload["job"]["result_summary"]
    assert "CALLBACK_URL" in payload["job"]["error_message"]
    assert "CALLBACK_URL" in payload["answer"]


def test_status_endpoint_rejects_other_users_job(client, isolated_db):
    """원본은 user 로 조회 범위를 제한합니다. 남의 작업은 볼 수 없어야 합니다."""
    _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-status-003",
            user_id=99999,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            pipeline_name="bidbox_staging",
            status="running",
        )
    )
    isolated_db.commit()

    assert client.get("/api/v1/automation/job/job-status-003/status").status_code == 404


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_sync_status_preserves_step_history(mock_enqueue, client, isolated_db):
    """원본 test_sync_status_preserves_callback_history 대응.

    원본은 Harness 폴링이 raw_status_payload["callbacks"] 를 덮어쓰지 않는지 봤습니다.
    이식본은 워커 보고를 result_payload["steps"] 에 쌓으므로 그쪽이 검증 대상입니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-sync-001",
            user_id=user_id,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            pipeline_name="bidbox_staging",
            payload={"callback_mode": "callback", "callback_configured": True},
            status="running",
            plan_execution_id="plan-005",
            harness_execution_id="plan-005",
            result_payload={
                "steps": {
                    "preflight": {"status": "success", "summary": "사전 점검 완료"},
                    "collect": {"status": "success", "summary": "수집 완료"},
                }
            },
        )
    )
    isolated_db.add(
        PipelineExecution(
            execution_id="plan-005",
            pipeline_name="bidbox_staging",
            run_mode="manual_full",
            status="running",
            source="chatbot",
        )
    )
    isolated_db.commit()

    response = client.get("/api/v1/automation/job/job-sync-001/status")
    assert response.status_code == 200

    request_obj = isolated_db.query(AutomationRequest).filter_by(request_id="job-sync-001").one()
    isolated_db.refresh(request_obj)
    assert set(request_obj.result_payload["steps"]) == {"preflight", "collect"}


# --------------------------------------------------------------------------- #
# 실행 중지 (원본 Harness abort -> Arq abort)
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator.abort_arq_job", return_value=True)
@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_running_automation_request_aborts_worker_job(
    mock_enqueue, mock_abort, client, isolated_db
):
    """원본 test_cancel_running_automation_request_aborts_harness 대응.

    원본은 Harness abort API 를 호출했습니다. 이식본은 같은 자리에서 Arq 작업을
    중단해야 하며, DB 만 바꾸고 워커를 방치하면 안 됩니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    job_id = client.post("/api/v1/automation/run/collect-bids", json={"reason": "수집"}).json()[
        "job"
    ]["job_id"]

    execution_id = _plan_execution_id(isolated_db, job_id)
    arq_job_id = (
        isolated_db.query(PipelineExecution)
        .filter_by(execution_id=execution_id)
        .one()
        .raw_status_payload["arq_job_id"]
    )

    response = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["job"]["status"] == "canceled"
    assert "사용자 요청으로 분석 실행을 중지했습니다" in payload["answer"]
    mock_abort.assert_called_once_with(arq_job_id)

    request_obj = isolated_db.query(AutomationRequest).filter_by(request_id=job_id).one()
    isolated_db.refresh(request_obj)
    assert request_obj.status == "canceled"
    assert request_obj.payload["canceled_by_user"]["worker_abort_requested"] is True

    execution = isolated_db.query(PipelineExecution).filter_by(execution_id=execution_id).one()
    assert execution.status == "failed"
    assert execution.stage_status == "canceled"


@patch("src.app.services.automation_orchestrator.abort_arq_job", return_value=True)
@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_pending_confirmation_does_not_abort_worker_job(
    mock_enqueue, mock_abort, client, isolated_db
):
    """확인 대기 건은 아직 큐에 없으므로 abort 를 부르면 안 됩니다 (원본 동일)."""
    _login(client)
    _seed_kb_status(isolated_db)
    job_id = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"}).json()[
        "job"
    ]["job_id"]

    assert client.post(f"/api/v1/automation/job/{job_id}/cancel").status_code == 200
    mock_abort.assert_not_called()


# --------------------------------------------------------------------------- #
# 최근 성공 실행 재사용
# --------------------------------------------------------------------------- #


def _seed_successful_execution(db, *, age: timedelta, run_mode: str, execution_id: str):
    started_at = utcnow() - age
    execution = PipelineExecution(
        execution_id=execution_id,
        pipeline_name=_full_validation_pipeline(),
        run_mode=run_mode,
        status="success",
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        raw_status_payload={"status": "success"},
        source="chatbot",
    )
    db.add(execution)
    db.commit()
    return execution


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_reuses_recent_success_without_new_run(mock_enqueue, client, isolated_db):
    """원본 test_confirm_reuses_recent_staging_success_without_new_run 대응.

    최근 성공 이력이 있으면 고비용 전체 점검을 새로 돌리지 않습니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    _seed_successful_execution(
        isolated_db,
        age=timedelta(minutes=40),
        run_mode="manual_full",
        execution_id="recent-manual-full-001",
    )

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]
    mock_enqueue.reset_mock()

    response = client.post(
        f"/api/v1/automation/job/{job_id}/confirm", json={"confirmation_token": token}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "result"
    assert payload["job"]["status"] == "success"
    assert payload["job"]["plan_execution_id"] == "recent-manual-full-001"
    assert "최근 성공한 자동화 실행" in payload["answer"]
    assert "requested_run_mode" in payload["result_payload"]["reused_execution"]
    mock_enqueue.assert_not_called()

    request_obj = isolated_db.query(AutomationRequest).filter_by(request_id=job_id).one()
    isolated_db.refresh(request_obj)
    assert request_obj.status == "success"
    assert request_obj.payload["reuse_mode"] == "recent_execution"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_ignores_stale_success_and_executes_new_run(mock_enqueue, client, isolated_db):
    """원본 test_confirm_ignores_stale_staging_success_and_executes_new_run 대응.

    신선도 창(72시간)을 벗어난 이력은 재사용하지 않고 새로 실행합니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    _seed_successful_execution(
        isolated_db,
        age=timedelta(days=7),
        run_mode="manual_full",
        execution_id="stale-manual-full-001",
    )

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]
    mock_enqueue.reset_mock()

    response = client.post(
        f"/api/v1/automation/job/{job_id}/confirm", json={"confirmation_token": token}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "action"
    assert payload["job"]["plan_execution_id"] != "stale-manual-full-001"
    mock_enqueue.assert_called_once()


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_collect_bids_is_not_reused(mock_enqueue, client, isolated_db):
    """재사용은 고비용 작업(full_validation)에만 적용됩니다 (원본 동일)."""
    _login(client)
    _seed_kb_status(isolated_db)
    _seed_successful_execution(
        isolated_db,
        age=timedelta(minutes=10),
        run_mode="collect_only",
        execution_id="recent-collect-001",
    )

    payload = client.post("/api/v1/automation/run/collect-bids", json={"reason": "수집"}).json()
    assert payload["job"]["plan_execution_id"] != "recent-collect-001"
    mock_enqueue.assert_called_once()


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_endpoint_executes_after_confirmation(mock_enqueue, client, isolated_db):
    """원본 test_confirm_endpoint_executes_after_confirmation 대응.

    확인 토큰으로 승인하면 confirmed_at 이 기록되고 실행 큐로 넘어가야 합니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]

    response = client.post(
        f"/api/v1/automation/job/{job_id}/confirm", json={"confirmation_token": token}
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "action"

    request_obj = isolated_db.query(AutomationRequest).filter_by(request_id=job_id).one()
    isolated_db.refresh(request_obj)
    assert request_obj.confirmed_at is not None
    assert request_obj.status in ("queued", "running")
    mock_enqueue.assert_called_once()
