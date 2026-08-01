"""
tests/test_chatbot_integration.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 이식 (세션/자동화 대화 흐름).

이 파일은 자동화 API 를 직접 호출하는 대신 반드시 챗봇 대화 API(/chatbot/chat)를
거칩니다. 원본 테스트의 목적이 "자연어 요청이 계획 수립을 거쳐 자동화 요청으로
연결되는가" 이기 때문이며, 엔드포인트 단독 동작은 tests/test_automation_api.py 가
이미 담당합니다.

예측/답변 계약은 tests/test_chatbot_prediction.py, 상태 조회와 콜백은
tests/test_automation_status_api.py 에 있습니다.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from src.app.models.chatbot import (
    AutomationRequest,
    ChatSessionState,
    KnowledgeBaseStatus,
)

VALID_SIGNUP = {
    "username": "chat-int-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "chat-int@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _login(client) -> int:
    """원본 setUp 의 force_login 대응. 생성된 사용자 id 를 돌려줍니다."""
    signup = client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "chat-int-user", "password": "StrongPass123!!"},
    )
    return signup.json()["id"]


def _seed_kb_status(db, **overrides) -> KnowledgeBaseStatus:
    """원본 setUp 의 KnowledgeBaseStatus 픽스처 대응."""
    payload = {
        "kb_version": "bidding_kb",
        "status": "ready",
        "source_bid_count": 321,
        "last_pipeline_run_id": "exec_002",
        "updated_at": datetime.utcnow(),
    }
    payload.update(overrides)
    kb = KnowledgeBaseStatus(**payload)
    db.add(kb)
    db.commit()
    return kb


def _chat(client, message: str, **extra):
    return client.post("/api/v1/chatbot/chat", json={"message": message, **extra})


# --------------------------------------------------------------------------- #
# 세션 전환
# --------------------------------------------------------------------------- #


def test_new_chat_session_returns_fresh_key(client, isolated_db):
    """원본 test_new_chat_session_api_cycles_only_chat_session 대응.

    원본은 Django 세션을 갈아끼우므로 로그인 유지까지 확인했습니다. 이식본은
    세션 키를 응답으로만 돌려주는 무상태 방식이라, 직전 키와 달라지는지와
    이전 세션 상태가 보존되는지를 확인합니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    old_key = _chat(client, "최근 공고 보여줘").json()["session_key"]

    response = client.post("/api/v1/chatbot/session/new")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["session_key"] != old_key

    # 새 세션을 만들어도 이전 세션 레코드는 남아 있어야 합니다.
    preserved = isolated_db.query(ChatSessionState).filter_by(session_key=old_key).one()
    assert preserved.last_query == "최근 공고 보여줘"


def test_chat_switches_to_persisted_session_history(client, isolated_db):
    """원본 test_chat_api_switches_to_persisted_session_history 대응."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        ChatSessionState(
            session_key="session-history-001",
            user_id=user_id,
            last_query="최근 서비스 공고 요약",
            last_result_summary="요약 답변",
            chat_history_json=[
                {"role": "user", "text": "최근 서비스 공고 요약"},
                {"role": "model", "text": "요약 답변"},
            ],
        )
    )
    isolated_db.commit()

    payload = _chat(client, "", session_key="session-history-001").json()
    assert payload["status"] == "success"
    assert payload["mode"] == "switch"
    assert payload["session_key"] == "session-history-001"
    assert payload["last_query"] == "최근 서비스 공고 요약"
    assert payload["history"][0]["text"] == "최근 서비스 공고 요약"
    assert payload["history"][1]["text"] == "요약 답변"


def test_chat_switch_repairs_stale_history_mapped_to_other_query(client, isolated_db):
    """원본 test_chat_api_switch_repairs_stale_history_mapped_to_other_query 대응.

    last_query 만 갱신되고 chat_history_json 이 낡아 있는 행은 전환 시
    last_query 기준으로 복구되어야 합니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        ChatSessionState(
            session_key="session-history-stale",
            user_id=user_id,
            last_query="최근 서비스 공고 요약",
            last_result_summary="최신 요약 답변",
            chat_history_json=[
                {"role": "user", "text": "예전 서울 서비스 흐름"},
                {"role": "model", "text": "예전 답변"},
            ],
        )
    )
    isolated_db.commit()

    payload = _chat(client, "", session_key="session-history-stale").json()
    assert payload["mode"] == "switch"
    assert payload["last_query"] == "최근 서비스 공고 요약"
    assert payload["history"][0]["text"] == "최근 서비스 공고 요약"
    assert payload["history"][1]["text"] == "최신 요약 답변"
    assert payload["history"][0]["text"] != "예전 서울 서비스 흐름"


def test_chat_without_message_and_without_session_returns_error(client, isolated_db):
    """빈 요청은 전환이 아니라 오류로 처리되어야 합니다 (원본 동일)."""
    _login(client)
    _seed_kb_status(isolated_db)
    assert _chat(client, "").json()["status"] == "error"


# --------------------------------------------------------------------------- #
# 자동화 실행 요청
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_creates_automation_request_for_data_refresh(mock_enqueue, client, isolated_db):
    """원본 test_chat_api_creates_running_automation_request_for_data_refresh 대응.

    자연어 요청이 action 모드로 분류되어 AutomationRequest 레코드까지 생성되는지
    확인합니다. 원본의 Harness 단언(plan_execution_id, callback_mode)은 Harness 를
    제거한 이식본에 대응 개념이 없어 제외했습니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    payload = _chat(client, "오늘 데이터 갱신해서 그래프 보여줘").json()
    assert payload["mode"] == "action"
    assert payload["intent"] == "data_refresh"
    assert payload["job"]["run_mode"] == "refresh_data"

    request_obj = isolated_db.query(AutomationRequest).one()
    assert request_obj.action_key == "data_refresh"
    assert request_obj.payload["source"] == "chat_api"


def test_chat_requires_login_for_automation(client, isolated_db):
    """원본은 로그인 사용자만 자동화를 실행합니다. 비로그인은 오류여야 합니다."""
    _seed_kb_status(isolated_db)
    payload = _chat(client, "오늘 데이터 갱신해줘").json()
    assert payload["status"] == "error"
    assert payload["intent"] == "data_refresh"


def test_chat_requires_confirmation_for_full_validation(client, isolated_db):
    """원본 test_chat_api_requires_confirmation_for_full_validation 대응."""
    _login(client)
    _seed_kb_status(isolated_db)
    payload = _chat(client, "전체 점검해줘").json()
    assert payload["mode"] == "confirmation"
    assert payload["job"]["requires_confirmation"] is True
    assert payload["confirmation_token"]

    request_obj = isolated_db.query(AutomationRequest).one()
    assert request_obj.action_key == "full_validation"
    assert request_obj.status == "pending_confirmation"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_cancel_pending_confirmation_marks_canceled(mock_enqueue, client, isolated_db):
    """원본 test_cancel_pending_confirmation_request_marks_canceled 대응.

    확인 대기 상태의 요청은 워커에 넣지 않은 채 취소되어야 합니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    job_id = _chat(client, "전체 점검해줘").json()["job"]["job_id"]

    cancel_resp = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["job"]["status"] == "canceled"
    mock_enqueue.assert_not_called()


# --------------------------------------------------------------------------- #
# 텍스트 승인
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_text_confirmation_executes_pending_request(mock_enqueue, client, isolated_db):
    """원본 test_chat_api_text_confirmation_executes_pending_request 대응.

    확인 대기 요청이 있을 때 "승인 후 실행해줘" 는 그 요청을 실행으로 전환합니다.
    """
    _login(client)
    _seed_kb_status(isolated_db)
    job_id = _chat(client, "전체 점검해줘").json()["job"]["job_id"]

    payload = _chat(client, "승인 후 실행해줘").json()
    assert payload["mode"] == "action"
    assert payload["job"]["job_id"] == job_id
    assert payload["job"]["action_key"] == "full_validation"

    request_obj = isolated_db.query(AutomationRequest).one()
    isolated_db.refresh(request_obj)
    assert request_obj.confirmed_at is not None
    assert request_obj.status in ("queued", "running")
    mock_enqueue.assert_called_once()


def test_chat_text_confirmation_without_pending_request_returns_guidance(client, isolated_db):
    """원본 test_chat_api_text_confirmation_without_pending_request_returns_guidance 대응."""
    _login(client)
    _seed_kb_status(isolated_db)

    payload = _chat(client, "승인 후 실행해줘").json()
    assert payload["mode"] == "answer"
    assert payload["intent"] == "automation_confirmation"
    assert "승인 대기 중인 자동화 요청이 없습니다" in payload["answer"]
    assert isolated_db.query(AutomationRequest).count() == 0


# --------------------------------------------------------------------------- #
# 진행 상황 조회
# --------------------------------------------------------------------------- #


def test_chat_progress_status_request_uses_latest_automation_job(client, isolated_db):
    """원본 test_chat_api_progress_status_request_uses_latest_automation_job 대응."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    request_obj = AutomationRequest(
        request_id="job-progress-001",
        user_id=user_id,
        intent_type="full_validation",
        action_key="full_validation",
        requested_text="전체 점검해줘",
        pipeline_name="bidbox_staging",
        payload={"callback_mode": "callback", "callback_configured": True},
        status="running",
        result_payload={
            "steps": {
                "preflight": {"status": "success", "summary": "사전 점검 완료"},
                "collect": {"status": "running", "summary": "공고 수집 진행 중"},
            }
        },
    )
    isolated_db.add(request_obj)
    isolated_db.commit()

    payload = _chat(client, "현재 점검 진행 상황 알려줘").json()
    assert payload["mode"] == "action"
    assert payload["intent"] == "full_validation"
    assert payload["job"]["job_id"] == "job-progress-001"
    assert "Step 진행 상황" in payload["answer"]
    assert "preflight" in payload["answer"]
    assert "collect" in payload["answer"]
    assert payload["visualizations"][0]["labels"] == ["preflight", "collect"]
    assert payload["plan_steps"][0]["tool"] == "automation_status_tool"


def test_chat_completed_status_request_suppresses_duration_only_chart(client, isolated_db):
    """원본 test_chat_api_completed_status_request_suppresses_duration_only_chart 대응.

    완료 상태의 단순 진행 질의는 소요 시간만 있는 차트를 노출하지 않습니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-done-001",
            user_id=user_id,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            pipeline_name="bidbox_staging",
            status="success",
            result_summary="최근 성공한 자동화 실행 결과를 재사용했습니다.",
            result_payload={
                "reused_execution": {
                    "started_at": "2026-04-29T01:00:00+00:00",
                    "ended_at": "2026-04-29T01:07:00+00:00",
                },
                "health_status": "stable",
                "insights": [],
                "recommended_actions": [],
            },
        )
    )
    isolated_db.commit()

    payload = _chat(client, "현재 점검 진행 상황 알려줘").json()
    assert payload["mode"] == "result"
    assert "완료" in payload["answer"]
    assert payload["visualizations"] == []
    assert "자동화 실행 소요 시간" not in payload["answer"]


def test_chat_completed_result_graph_request_keeps_duration_chart(client, isolated_db):
    """원본 test_chat_api_completed_result_graph_request_keeps_duration_chart 대응.

    같은 완료 건이라도 명시적으로 그래프를 요청하면 소요 시간 차트를 유지합니다.
    원본은 Harness 전용 문구였으나 이식본은 "자동화 실행 소요 시간" 입니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        AutomationRequest(
            request_id="job-done-002",
            user_id=user_id,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            pipeline_name="bidbox_staging",
            status="success",
            result_summary="최근 성공한 자동화 실행 결과를 재사용했습니다.",
            result_payload={
                "reused_execution": {
                    "started_at": "2026-04-29T01:00:00+00:00",
                    "ended_at": "2026-04-29T01:07:00+00:00",
                },
                "health_status": "stable",
                "insights": [],
                "recommended_actions": [],
            },
        )
    )
    # 원본은 remember_chat_interaction 으로 직전 대화에 job_id 를 남깁니다.
    isolated_db.add(
        ChatSessionState(
            session_key="session-graph-001",
            user_id=user_id,
            last_query="전체 점검해줘",
            last_job_id="job-done-002",
            last_action_key="full_validation",
        )
    )
    isolated_db.commit()

    payload = _chat(
        client, "방금 결과를 그래프로 보여줘", session_key="session-graph-001"
    ).json()
    assert payload["mode"] == "result"
    assert payload["plan_steps"][0]["tool"] == "automation_status_tool"
    assert payload["visualizations"]
    assert payload["visualizations"][0]["title"] == "자동화 실행 소요 시간"
    assert payload["visualizations"][0]["unit"] == "분"


# --------------------------------------------------------------------------- #
# 챗봇 화면 렌더링
# --------------------------------------------------------------------------- #


def test_chat_page_renders_session_sidebar_and_chat_binding(client, isolated_db):
    """원본 test_chat_page_renders_session_sidebar_and_chat_binding 대응.

    원본이 확인하던 프런트 바인딩 지점이 Jinja2 이식 후에도 남아 있는지 봅니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    isolated_db.add(
        ChatSessionState(
            session_key="session-sidebar-001",
            user_id=user_id,
            last_query="파이프라인 감시",
            updated_at=datetime.utcnow() - timedelta(minutes=1),
        )
    )
    isolated_db.commit()

    response = client.get("/chat/")
    assert response.status_code == 200
    body = response.text
    for marker in (
        "data-chat-url",
        "data-new-session-url",
        "btn-stop",
        "요청 중지",
        "cancelUrlTemplate",
        "cancel-automation-btn",
        "stopActiveChatRequest",
        "confirm-automation-btn",
        "app_settings_modal",
        "settings-show-sources",
        "normalizePlainBotMarkdown",
        "chat-chart-card",
        "chat-chart-summary",
        "chatChartValueLabelPlugin",
        "CHAT_CHART_BAR_PALETTE",
        "createBarGradient",
        "resizeChartCard",
        "observeChartResize",
        "setChartExpanded",
        "chart-zoom-in",
        "chart-zoom-reset",
        "chart-zoom-expand",
        "chart-expanded-open",
        "formatSourceTag",
        "source-tag-index",
        "data-unit",
        "inferYAxisLabel",
        "AI가 요청을 분석 중입니다",
        "user-msg-content",
        "scrollChatToMessageStart",
        "새 분석",
        "파이프라인 감시",
    ):
        assert marker in body, f"챗봇 화면에 {marker!r} 가 없습니다."

    assert "New Analysis" not in body


def test_chat_page_new_session_url_matches_real_route(client, isolated_db):
    """chat.html 의 새 대화 버튼이 실제 라우트를 가리켜야 합니다."""
    _login(client)
    _seed_kb_status(isolated_db)
    body = client.get("/chat/").text
    assert 'data-new-session-url="/api/v1/chatbot/session/new"' in body
    assert client.post("/api/v1/chatbot/session/new").status_code == 200
