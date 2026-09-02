"""
tests/test_automation_api.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 중 automation API 핵심 검증 이식.
 - 데이터 갱신 실행 → 자동화 요청 생성
 - 전체 점검 → 확인 필요 (high_cost)
 - 실행 취소
 - 상태 조회
 - 미인증 차단
"""

from unittest.mock import patch

VALID_SIGNUP = {
    "username": "automation-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "auto@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _login(client, isolated_db):
    client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "automation-user", "password": "StrongPass123!!"},
    )
    import sqlalchemy

    from src.app.models.accounts import CustomUser

    user = isolated_db.execute(
        sqlalchemy.select(CustomUser).where(CustomUser.username == "automation-user")
    ).scalar_one()
    user.is_staff = True
    isolated_db.commit()


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_collect_bids_creates_automation_request(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["action_key"] == "collect_refresh"
    assert payload["job"]["run_mode"] == "collect_only"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_manual_full_requires_confirmation(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    response = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "confirmation"
    assert payload["confirmation_token"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_manual_retrain_requires_confirmation(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    response = client.post("/api/v1/automation/run/retrain", json={"reason": "운영자 검토"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "confirmation"
    assert payload["job"]["action_key"] == "model_retrain"
    assert payload["job"]["run_mode"] == "retrain_only"
    assert payload["confirmation_token"]
    mock_enqueue.assert_not_called()

    confirm_response = client.post(
        f"/api/v1/automation/job/{payload['job']['job_id']}/confirm",
        json={"confirmation_token": payload["confirmation_token"]},
    )
    assert confirm_response.status_code == 200
    assert mock_enqueue.call_args.args[0] == "manual_retrain_task"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_pending_confirmation(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    cancel_resp = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["job"]["status"] == "canceled"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_status_query_returns_job_details(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    create_resp = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    job_id = create_resp.json()["job"]["job_id"]

    status_resp = client.get(f"/api/v1/automation/job/{job_id}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["job_id"] == job_id
    assert data["action_key"] == "collect_refresh"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_executes_pending_request(mock_enqueue, client, isolated_db):
    _login(client, isolated_db)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": token},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["job"]["status"] in ("running", "queued", "success")


@patch("src.app.services.automation_orchestrator.abort_arq_job", return_value=False)
@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_pending_confirmation_request_marks_canceled_without_harness_abort(
    mock_enqueue, mock_abort, client, isolated_db
):
    """확인 대기 중인 요청은 취소만 하고 워커 중단 신호는 보내지 않는다.

    아직 큐에 들어가지 않았으므로 보낼 대상이 없습니다. 그래도 보내면 엉뚱한
    작업 ID 로 중단 신호가 나갈 수 있습니다.

    원본은 Harness abort API 호출 여부를 봤고, 이식본은 같은 자리의
    abort_arq_job 호출 여부를 봅니다.
    """
    _login(client, isolated_db)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    response = client.post(f"/api/v1/automation/job/{job_id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["job"]["status"] == "canceled"
    assert "요청을 중지했습니다" in payload["answer"]
    mock_abort.assert_not_called()


@patch("src.app.services.automation_orchestrator.abort_arq_job", return_value=True)
def test_cancel_running_automation_request_aborts_harness_and_stops_polling_state(
    mock_abort, client, isolated_db
):
    """실행 중인 요청은 워커에 중단 신호를 보내고 실행 이력도 함께 닫는다.

    요청만 canceled 로 바꾸고 pipeline_executions 를 running 으로 두면,
    상태 폴링이 끝나지 않아 화면이 계속 진행 중으로 남습니다.
    """
    from src.app.models.chatbot import AutomationRequest, PipelineExecution
    from src.app.services.automation_orchestrator import make_callback_token  # noqa: F401

    _login(client, isolated_db)
    me = client.get("/api/v1/accounts/me").json()

    isolated_db.add_all(
        [
            AutomationRequest(
                request_id="plan-cancel-001",
                user_id=me["id"],
                intent_type="data_refresh",
                action_key="data_refresh",
                requested_text="오늘 데이터 갱신해서 그래프 보여줘",
                pipeline_name="BIDBOX_Personal_Pipeline_Staging",
                status="running",
                plan_execution_id="plan-cancel-001",
                harness_execution_id="plan-cancel-001",
                execution_url="https://example.invalid/pipeline/plan-cancel-001",
            ),
            PipelineExecution(
                execution_id="plan-cancel-001",
                pipeline_name="BIDBOX_Personal_Pipeline_Staging",
                run_mode="refresh_data",
                status="running",
                source="chatbot",
                # 중단 신호를 보낼 대상 작업 ID 입니다. 없으면 신호를 보내지 않습니다.
                raw_status_payload={"arq_job_id": "arq-cancel-001"},
            ),
        ]
    )
    isolated_db.commit()

    response = client.post("/api/v1/automation/job/plan-cancel-001/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["mode"] == "error"
    assert payload["job"]["status"] == "canceled"
    assert "사용자 요청으로 분석 실행을 중지했습니다" in payload["answer"]
    mock_abort.assert_called_once_with("arq-cancel-001")

    isolated_db.expire_all()
    request_obj = (
        isolated_db.query(AutomationRequest)
        .filter(AutomationRequest.request_id == "plan-cancel-001")
        .one()
    )
    assert request_obj.status == "canceled"
    assert request_obj.payload["canceled_by_user"]["worker_abort_requested"] is True

    execution = (
        isolated_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == "plan-cancel-001")
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_status == "canceled"


def test_automation_requires_authentication(client, isolated_db):
    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    assert response.status_code == 401


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_callback_updates_step_status(mock_enqueue, client, isolated_db):
    from src.app.services.automation_orchestrator import make_callback_token

    _login(client, isolated_db)
    create_resp = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    job_id = create_resp.json()["job"]["job_id"]
    token = make_callback_token(job_id)

    callback_resp = client.post(
        f"/api/v1/automation/job/{job_id}/callback",
        json={"step": "collect", "status": "success", "summary": "수집 완료", "final": True},
        headers={"X-BIDBOX-CALLBACK-TOKEN": token},
    )
    assert callback_resp.status_code == 200
    assert callback_resp.json()["status"] == "success"
