"""
tests/test_prefs_save_warm_20261125.py

마이페이지 관심 조건 저장 직후 그 조건 하나만 예열하는 계약을 고정합니다.

막으려는 사고:
  - 저장 직후 최대 10분 동안 메인 화면 '내 조건 입찰 중' 이 '집계 중' 으로 남는 것
  - 예열 등록 실패(Redis 장애, 예외)가 관심 조건 저장을 실패시키는 것
  - async 저장 라우트가 블로킹 등록 호출로 이벤트 루프를 막는 것
  - 예열 작업이 세션을 닫지 않거나 실패를 예외로 올려 worker 재시도를 유발하는 것
  - 검증 오류로 저장하지 않은 요청이 예열을 넣는 것

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 시험 대역을 씁니다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.services.bid_preferences import (
    BidPreferenceView,
    get_bid_preferences,
    save_bid_preferences,
)
from tests.test_csrf import csrf_form

EDIT_URL = "/accounts/mypage/edit/"
MYPAGE_URL = "/accounts/mypage/"
LICENSE_CODE = "1162"
REGION_CODE = "seoul"


def _create_user(db, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-pref-1234"),
        email=f"{username}@example.com",
        nickname="관심 회원",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _payload(user: CustomUser, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "nickname": "관심 회원",
        "email": f"{user.username}@example.com",
        "bid_license_codes": [LICENSE_CODE],
        "bid_region_code": REGION_CODE,
    }
    data.update(overrides)
    return data


class _NonClosingSession:
    """스레드 작업의 close() 를 기록하되 픽스처 세션은 살려 두는 대역."""

    def __init__(self, session: Any, closes: list[bool]) -> None:
        self._session = session
        self._closes = closes

    def close(self) -> None:
        self._closes.append(True)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def _install_thread_session(monkeypatch, isolated_db, closes: list[bool]) -> None:
    from src.tasks import scheduled_tasks

    monkeypatch.setattr(
        scheduled_tasks,
        "SessionLocal",
        lambda: _NonClosingSession(isolated_db, closes),
    )


# --------------------------------------------------------------------------- #
# (a) 저장 라우트가 그 사용자 하나만 예열 작업으로 넣는다
# --------------------------------------------------------------------------- #


def test_save_enqueues_warm_once_for_saved_user(client, isolated_db, monkeypatch):
    from src.app.api import ui as ui_module

    recorded: list[tuple[str, dict[str, Any]]] = []

    def fake_enqueue(task_name: str, **kwargs: Any) -> bool:
        recorded.append((task_name, kwargs))
        return True

    monkeypatch.setattr(ui_module, "_enqueue_arq_job", fake_enqueue)
    user = _create_user(isolated_db, "prefs_warm_enqueue")
    auth_client = _auth_client(user)

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, _payload(user)),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == MYPAGE_URL
    assert recorded == [("warm_bid_preference_task", {"user_id": user.id})]


# --------------------------------------------------------------------------- #
# (b) 등록 실패는 저장을 실패시키지 않는다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("enqueue_result", [False, RuntimeError("redis down")])
def test_enqueue_failure_does_not_fail_save(client, isolated_db, monkeypatch, enqueue_result):
    from src.app.api import ui as ui_module

    def fake_enqueue(*args: Any, **kwargs: Any) -> bool:
        if isinstance(enqueue_result, Exception):
            raise enqueue_result
        return enqueue_result

    monkeypatch.setattr(ui_module, "_enqueue_arq_job", fake_enqueue)
    user = _create_user(isolated_db, f"prefs_warm_fail_{type(enqueue_result).__name__}")
    auth_client = _auth_client(user)

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, _payload(user)),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == MYPAGE_URL
    isolated_db.expire_all()
    stored = get_bid_preferences(isolated_db, user.id)
    assert stored is not None
    assert stored.license_codes == [LICENSE_CODE]
    assert stored.region_code == REGION_CODE


# --------------------------------------------------------------------------- #
# (c) 검증 오류로 저장하지 않은 요청은 예열을 넣지 않는다
# --------------------------------------------------------------------------- #


def test_validation_error_does_not_enqueue(client, isolated_db, monkeypatch):
    from src.app.api import ui as ui_module

    recorded: list[Any] = []
    monkeypatch.setattr(
        ui_module, "_enqueue_arq_job", lambda *args, **kwargs: recorded.append(args)
    )
    user = _create_user(isolated_db, "prefs_warm_invalid")
    auth_client = _auth_client(user)

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, _payload(user, email="not-an-email")),
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert recorded == []


# --------------------------------------------------------------------------- #
# (d) 예열 작업은 빈 조건을 건너뛰고, 실패를 예외로 올리지 않으며, 세션을 닫는다
# --------------------------------------------------------------------------- #


def test_task_skips_empty_preferences(isolated_db, monkeypatch):
    from src.tasks.scheduled_tasks import warm_bid_preference_task

    closes: list[bool] = []
    _install_thread_session(monkeypatch, isolated_db, closes)
    user = _create_user(isolated_db, "prefs_warm_empty")
    save_bid_preferences(isolated_db, user.id, [], "")
    isolated_db.commit()

    warmed: list[Any] = []
    monkeypatch.setattr(
        "src.app.services.bid_preferences.warm_open_servc_matching",
        lambda *args, **kwargs: warmed.append(args),
    )

    result = asyncio.run(warm_bid_preference_task({}, user.id))

    assert result == {"status": "skipped", "reason": "empty"}
    assert warmed == []
    assert closes == [True]


def test_task_warms_only_the_saved_users_condition(isolated_db, monkeypatch):
    from src.tasks.scheduled_tasks import warm_bid_preference_task

    closes: list[bool] = []
    _install_thread_session(monkeypatch, isolated_db, closes)
    user = _create_user(isolated_db, "prefs_warm_one")
    save_bid_preferences(isolated_db, user.id, [LICENSE_CODE], REGION_CODE)
    isolated_db.commit()

    seen: list[BidPreferenceView] = []
    monkeypatch.setattr(
        "src.app.services.bid_preferences.warm_open_servc_matching",
        lambda db, prefs, *args, **kwargs: seen.append(prefs),
    )

    result = asyncio.run(warm_bid_preference_task({}, user.id))

    assert result["status"] == "success"
    assert seen == [BidPreferenceView([LICENSE_CODE], REGION_CODE)]
    assert closes == [True]


def test_task_returns_failed_instead_of_raising(isolated_db, monkeypatch):
    from src.tasks.scheduled_tasks import warm_bid_preference_task

    closes: list[bool] = []
    _install_thread_session(monkeypatch, isolated_db, closes)
    user = _create_user(isolated_db, "prefs_warm_boom")
    save_bid_preferences(isolated_db, user.id, [LICENSE_CODE], REGION_CODE)
    isolated_db.commit()

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("집계 실패")

    monkeypatch.setattr("src.app.services.bid_preferences.warm_open_servc_matching", boom)

    result = asyncio.run(warm_bid_preference_task({}, user.id))

    assert result["status"] == "failed"
    assert closes == [True]


# --------------------------------------------------------------------------- #
# (e) 새 작업은 worker 함수 목록에만 등록하고 cron 은 만들지 않는다
# --------------------------------------------------------------------------- #


def test_worker_settings_register_warm_bid_preference_task():
    from src.tasks.scheduled_tasks import warm_bid_preference_task
    from src.tasks.worker import WorkerSettings

    assert warm_bid_preference_task in WorkerSettings.functions
    assert all(
        getattr(job, "coroutine", None) is not warm_bid_preference_task
        for job in WorkerSettings.cron_jobs
    )
