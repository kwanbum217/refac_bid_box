"""2026-11-11 재현 보고서 소규모 결함 시험.

정본: .orca/capsules/task_small_fixes_data_20261111/capsule.yaml.
  - F-06: 관리자 수집 API 가 end_date 단독·역순 창을 422 로 거부한다.
  - F-07: 대시보드 시스템 상태 카드가 readiness 결과를 따르고, 핸들러 없는
    보고서 내보내기 버튼이 제거되었다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.api.v1 import bids as bids_api
from src.app.main import app

COLLECT_URL = "/api/v1/bids/collect"
DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "src" / "app" / "templates" / "bids" / "dashboard.html"
)


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


def test_dashboard_status_card_follows_readiness():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")

    assert "/api/v1/health/ready" in source
    assert 'id="systemStatusBadge"' in source
    assert 'id="systemStatusText"' in source
    assert "systemStatusBadge.innerHTML" not in source
    assert "systemStatusText.innerHTML" not in source


def test_dashboard_export_button_is_removed():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")

    assert "보고서 내보내기" not in source
