"""2026-11-11 재현 보고서 소규모 결함 시험.

정본: .orca/capsules/task_small_fixes_data_20261111/capsule.yaml.
  - F-06: 관리자 수집 API 가 end_date 단독·역순 창을 422 로 거부한다.
  - F-07: 대시보드 화면은 삭제되었고 옛 주소는 홈으로 리다이렉트된다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.app.api.v1 import bids as bids_api
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser

COLLECT_URL = "/api/v1/bids/collect"


@pytest.fixture
def admin_client(client):
    app.dependency_overrides[bids_api.require_current_user] = lambda: SimpleNamespace(
        id=1, is_staff=True, is_superuser=True
    )
    yield client
    app.dependency_overrides.pop(bids_api.require_current_user, None)


@pytest.fixture
def collect_spy(monkeypatch):
    """수집 본체 호출을 기록하는 대역. 외부 G2B API 호출을 막습니다."""
    calls: list[dict] = []

    async def fake_collect(db, **kwargs):
        calls.append(kwargs)
        return {"status": "success"}

    monkeypatch.setattr("src.app.services.collector_service.collect_bids", fake_collect)
    return calls


def test_collect_rejects_end_date_without_start_date(admin_client, collect_spy):
    response = admin_client.post(COLLECT_URL, params={"end_date": "20260812"})

    assert response.status_code == 422
    assert "end_date" in response.json()["detail"]
    assert collect_spy == [], "검증 실패 요청이 수집 본체까지 도달했습니다"


def test_collect_rejects_reversed_date_range(admin_client, collect_spy):
    response = admin_client.post(
        COLLECT_URL, params={"start_date": "20260812", "end_date": "20260810"}
    )

    assert response.status_code == 422
    assert collect_spy == [], "검증 실패 요청이 수집 본체까지 도달했습니다"


def test_collect_accepts_start_and_end_date_together(admin_client, collect_spy):
    response = admin_client.post(
        COLLECT_URL, params={"start_date": "20260810", "end_date": "20260812"}
    )

    assert response.status_code == 200
    assert collect_spy == [{"start_date": "20260810", "end_date": "20260812", "fetch_type": "both"}]


def test_removed_dashboard_redirects_to_home(isolated_db):
    user = CustomUser(
        username="small_fixes_dashboard",
        password=make_password("pw-test-1234"),
        email="small-fixes@example.com",
        nickname="대시보드 제거 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)

    token = create_session(user.id, user.username)
    client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})

    for path in ("/bids/dashboard/", "/dashboard/"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"
