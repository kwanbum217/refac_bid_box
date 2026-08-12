import pytest

from src.app.services import collector_service


def test_collect_endpoint_requires_authentication(client):
    response = client.post("/api/v1/bids/collect")

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_collect_bids_reports_failed_when_all_attempts_raise(monkeypatch, isolated_db):
    async def fail(*args, **kwargs):
        raise RuntimeError("수집 실패")

    monkeypatch.setattr(collector_service, "get_service_key", lambda: "test-key")
    monkeypatch.setattr(collector_service, "stream_bid_announcements", fail)
    monkeypatch.setattr(collector_service, "stream_bid_data", fail)

    metrics = await collector_service.collect_bids(
        isolated_db,
        categories=("Thng", "Servc"),
        refresh_aggregates=False,
    )

    assert metrics["status"] == "failed"
    assert metrics["attempted"] == 4
    assert metrics["failed_count"] == 4


@pytest.mark.asyncio
async def test_collect_bids_reports_partial_success_when_some_attempts_raise(
    monkeypatch, isolated_db
):
    async def collect_announcements(*args, category, **kwargs):
        if category == "Thng":
            raise RuntimeError("물품 수집 실패")
        return 2

    monkeypatch.setattr(collector_service, "get_service_key", lambda: "test-key")
    monkeypatch.setattr(
        collector_service,
        "stream_bid_announcements",
        collect_announcements,
    )

    metrics = await collector_service.collect_bids(
        isolated_db,
        categories=("Thng", "Servc"),
        fetch_type="announce",
        refresh_aggregates=False,
    )

    assert metrics["status"] == "partial_success"
    assert metrics["attempted"] == 2
    assert metrics["failed_count"] == 1


@pytest.mark.asyncio
async def test_collect_bids_reports_success_when_all_attempts_finish(monkeypatch, isolated_db):
    async def collect(*args, **kwargs):
        return 1

    monkeypatch.setattr(collector_service, "get_service_key", lambda: "test-key")
    monkeypatch.setattr(collector_service, "stream_bid_announcements", collect)
    monkeypatch.setattr(collector_service, "stream_bid_data", collect)

    metrics = await collector_service.collect_bids(
        isolated_db,
        categories=("Thng", "Servc"),
        refresh_aggregates=False,
    )

    assert metrics["status"] == "success"
    assert metrics["attempted"] == 4
    assert metrics["failed_count"] == 0
