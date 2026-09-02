"""
tests/test_callback_delivery.py

워커 실행 결과가 요청 레코드로 되돌아오는 경로(callback delivery) 판정 검증.

원본은 외부 SaaS(Harness)가 호출자였기 때문에 사설 대역을 전부 거부했습니다.
Arq 워커는 같은 네트워크 안에 있으므로 판정 규칙이 반대입니다. 사설 주소는
허용하고 루프백만 거부하며, 콜백 주소가 없어도 DB 를 공유하면 direct 로 봅니다.
"""

from unittest.mock import patch

import pytest

from src.app.services.automation_orchestrator import (
    CALLBACK_PATH_TEMPLATE,
    make_callback_token,
    resolve_callback_delivery,
)
from src.tasks.automation_tasks import _report

JOB_ID = "job-delivery-001"


@pytest.fixture
def automation_settings(monkeypatch):
    """자동화 콜백 관련 설정만 건드리는 헬퍼."""

    def _apply(*, base_url: str = "", shares_db: bool = True):
        from src.app.core.config import settings

        monkeypatch.setattr(settings, "AUTOMATION_CALLBACK_BASE_URL", base_url, raising=False)
        monkeypatch.setattr(settings, "AUTOMATION_WORKER_SHARES_DB", shares_db, raising=False)

    return _apply


# --------------------------------------------------------------------------- #
# 판정 규칙
# --------------------------------------------------------------------------- #


def test_no_base_url_with_shared_db_is_direct(automation_settings):
    """기본 docker-compose 구성. 워커가 DB 에 직접 기록하므로 direct 입니다."""
    automation_settings(base_url="", shares_db=True)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "direct"
    assert delivery.configured is True
    assert delivery.callback_url == ""


def test_no_base_url_without_shared_db_is_polling(automation_settings):
    """DB 도 안 보고 콜백 주소도 없으면 되돌릴 경로가 없습니다."""
    automation_settings(base_url="", shares_db=False)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "polling"
    assert delivery.configured is False
    assert "상태 조회" in delivery.reason


@pytest.mark.parametrize(
    "base_url",
    [
        "http://app:8000",  # 컨테이너 서비스명
        "http://10.0.1.5:8000",  # 사설 대역
        "http://172.18.0.4:8000",  # docker 기본 브릿지 대역
        "https://bidbox.example.com",  # 공개 도메인
    ],
)
def test_private_and_public_hosts_are_accepted(automation_settings, base_url):
    """원본과 반대로 사설 주소를 허용합니다. 워커가 같은 네트워크에 있기 때문입니다."""
    automation_settings(base_url=base_url, shares_db=False)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "callback"
    assert delivery.configured is True
    assert delivery.callback_url == (
        f"{base_url.rstrip('/')}{CALLBACK_PATH_TEMPLATE.format(job_id=JOB_ID)}"
    )


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000", "http://0.0.0.0:8000"],
)
def test_loopback_hosts_are_rejected(automation_settings, base_url):
    """루프백은 별도 프로세스인 워커에서 앱이 아니라 자기 자신을 가리킵니다."""
    automation_settings(base_url=base_url, shares_db=False)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "polling"
    assert delivery.configured is False
    assert "루프백" in delivery.reason


def test_loopback_falls_back_to_direct_when_db_is_shared(automation_settings):
    """콜백 주소가 잘못돼도 DB 를 공유하면 결과는 정상적으로 돌아옵니다."""
    automation_settings(base_url="http://127.0.0.1:8000", shares_db=True)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "direct"
    assert delivery.configured is True
    assert "루프백" in delivery.reason


@pytest.mark.parametrize("base_url", ["not-a-url", "ftp://app:8000", "http://"])
def test_malformed_base_url_is_rejected(automation_settings, base_url):
    automation_settings(base_url=base_url, shares_db=False)
    delivery = resolve_callback_delivery(JOB_ID)
    assert delivery.mode == "polling"
    assert "형식" in delivery.reason


def test_trailing_slash_does_not_duplicate(automation_settings):
    automation_settings(base_url="http://app:8000/", shares_db=False)
    assert "//api" not in resolve_callback_delivery(JOB_ID).callback_url


# --------------------------------------------------------------------------- #
# 요청 레코드 반영
# --------------------------------------------------------------------------- #


def _login(client, isolated_db=None) -> int:
    signup = client.post(
        "/api/v1/accounts/signup",
        json={
            "username": "delivery-user",
            "password1": "StrongPass123!!",
            "password2": "StrongPass123!!",
            "nickname": "테스터",
            "email": "delivery@example.com",
            "birth_date": "1999-05-17",
            "gender": "F",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    client.post(
        "/api/v1/accounts/login",
        json={"username": "delivery-user", "password": "StrongPass123!!"},
    )
    if isolated_db is not None:
        import sqlalchemy

        from src.app.models.accounts import CustomUser

        user = isolated_db.execute(
            sqlalchemy.select(CustomUser).where(CustomUser.username == "delivery-user")
        ).scalar_one()
        user.is_staff = True
        isolated_db.commit()
    return signup.json()["id"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_request_records_resolved_delivery(mock_enqueue, client, isolated_db, automation_settings):
    """판정 결과가 요청 페이로드와 응답 job 계약에 그대로 실려야 합니다."""
    automation_settings(base_url="http://app:8000", shares_db=False)
    _login(client, isolated_db)

    payload = client.post("/api/v1/automation/run/collect-bids", json={"reason": "수집"}).json()
    assert payload["job"]["callback_mode"] == "callback"
    assert payload["job"]["callback_configured"] is True
    assert "결과 수신 방식: `callback`" in payload["answer"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_direct_mode_is_reported_in_answer(mock_enqueue, client, isolated_db, automation_settings):
    """기본 구성은 polling 이 아니라 direct 로 안내되어야 합니다."""
    automation_settings(base_url="", shares_db=True)
    _login(client, isolated_db)

    payload = client.post("/api/v1/automation/run/collect-bids", json={"reason": "수집"}).json()
    assert payload["job"]["callback_mode"] == "direct"
    assert "결과 수신 방식: `direct`" in payload["answer"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_callback_credentials_are_passed_to_worker_only_in_callback_mode(
    mock_enqueue, client, isolated_db, automation_settings
):
    """direct 모드에서는 워커에 콜백 자격을 넘기지 않아야 합니다."""
    automation_settings(base_url="", shares_db=True)
    _login(client, isolated_db)
    client.post("/api/v1/automation/run/collect-bids", json={"reason": "수집"})
    assert mock_enqueue.call_args.kwargs["callback_url"] == ""
    assert mock_enqueue.call_args.kwargs["callback_token"] == ""

    mock_enqueue.reset_mock()
    automation_settings(base_url="http://app:8000", shares_db=False)
    client.post("/api/v1/automation/run/update-kb", json={"reason": "갱신"})
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["callback_url"].endswith("/callback")
    assert kwargs["callback_token"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_api_falls_back_to_polling_for_loopback_callback_base_url(
    mock_enqueue, client, isolated_db, automation_settings
):
    """챗봇에서 만든 작업도 루프백 콜백 주소면 polling 으로 내려간다.

    자동화 실행 엔드포인트만 판정이 걸려 있고 챗봇 경로가 새면, 워커가
    도달할 수 없는 127.0.0.1 로 결과를 보내다 통째로 유실됩니다. 자격을
    비워 보내는 것까지 확인해야 워커가 헛된 HTTP 시도를 하지 않습니다.
    """
    automation_settings(base_url="http://127.0.0.1:8800", shares_db=False)
    _login(client)

    payload = client.post(
        "/api/v1/chatbot/chat", json={"message": "오늘 데이터 갱신해서 그래프 보여줘"}
    ).json()

    assert payload["job"]["callback_mode"] == "polling"
    assert payload["job"]["callback_configured"] is False
    assert mock_enqueue.call_args.kwargs["callback_url"] == ""
    assert mock_enqueue.call_args.kwargs["callback_token"] == ""


# --------------------------------------------------------------------------- #
# 워커 보고 경로
# --------------------------------------------------------------------------- #


@patch("src.tasks.automation_tasks.apply_callback_payload")
@patch("src.tasks.automation_tasks._post_callback", return_value=True)
def test_worker_uses_http_when_callback_url_given(mock_post, mock_apply):
    _report(
        None,
        JOB_ID,
        "rag",
        "success",
        "요약",
        {"source_bid_count": 12},
        callback_url="http://app:8000/api/v1/automation/job/x/callback",
        callback_token=make_callback_token(JOB_ID),
    )
    mock_post.assert_called_once()
    mock_apply.assert_not_called()


@patch("src.tasks.automation_tasks.get_automation_request", return_value=object())
@patch("src.tasks.automation_tasks.apply_callback_payload")
@patch("src.tasks.automation_tasks._post_callback", return_value=False)
def test_worker_falls_back_to_db_when_http_fails(mock_post, mock_apply, mock_get):
    """콜백 전송이 실패해도 같은 페이로드를 DB 에 남겨 보고가 유실되지 않아야 합니다."""
    _report(
        None,
        JOB_ID,
        "rag",
        "success",
        "요약",
        {"source_bid_count": 12},
        callback_url="http://app:8000/api/v1/automation/job/x/callback",
        callback_token="t",
    )
    mock_post.assert_called_once()
    mock_apply.assert_called_once()


@patch("src.tasks.automation_tasks.get_automation_request", return_value=object())
@patch("src.tasks.automation_tasks.apply_callback_payload")
@patch("src.tasks.automation_tasks._post_callback")
def test_worker_writes_db_directly_without_callback_url(mock_post, mock_apply, mock_get):
    _report(None, JOB_ID, "rag", "success", "요약", {})
    mock_post.assert_not_called()
    mock_apply.assert_called_once()
