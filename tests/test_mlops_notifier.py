"""
tests/test_mlops_notifier.py

MLOps 알림 발신 검증. 설계는 `docs/design/mlops_notification_20260805.md`.

두 가지를 고정합니다.

1. **알림 실패가 본 작업을 되돌리지 않을 것.** 웹훅이 죽었다고 재학습 결과가
   날아가면 본말전도입니다.
2. **기각은 보내지 않을 것.** 대부분의 재학습이 기각으로 끝나므로 그것까지
   보내면 알림이 소음이 되고, 정작 중요한 승격 권고를 사람이 읽지 않게 됩니다.

실제 네트워크는 태우지 않습니다. 태우면 테스트가 외부 상태에 묶입니다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.config import settings
from src.tasks import notifier

CHAMPION_METRICS = {"r2": 0.6824, "rmse": 2.6998, "mape": 3.1}
CHALLENGER_METRICS = {"r2": 0.6901, "rmse": 2.6670, "mape": 3.0}


@pytest.fixture(autouse=True)
def mock_schedule_claim(monkeypatch):
    """스케줄 태스크 실패 알림 테스트 시 Redis claim 이 기본적으로 통과하도록 모의합니다."""
    from src.tasks import scheduled_tasks

    monkeypatch.setattr(
        scheduled_tasks,
        "acquire_schedule_claim",
        lambda owner, **kwargs: scheduled_tasks.ScheduleClaimResult(
            status=scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
            key=scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY,
            owner=owner,
            ttl=21600,
            detail="test claim granted",
        ),
    )


@pytest.fixture
def webhook_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MLOPS_WEBHOOK_URL", "http://webhook.test/hook", raising=False)
    return settings.MLOPS_WEBHOOK_URL


@pytest.fixture
def sent(monkeypatch):
    """notify 가 실제로 보낸 메시지를 모읍니다."""
    messages: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        messages.append((title, lines, level))

    monkeypatch.setattr(notifier, "notify", fake_notify)
    return messages


# --------------------------------------------------------------------------- #
# 발신 자체
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_notify_does_nothing_without_url(monkeypatch):
    """URL 미설정이 기본값입니다. 개발 장비에서 조용해야 합니다."""
    monkeypatch.setattr(settings, "MLOPS_WEBHOOK_URL", "", raising=False)
    with patch("httpx.AsyncClient") as client:
        await notifier.notify("제목", ["본문"])
    client.assert_not_called()


@pytest.mark.asyncio
async def test_notify_posts_formatted_text(webhook_enabled, monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    await notifier.notify("승격 권고", ["champion v1", "challenger v2"], level="action")

    assert captured["url"] == webhook_enabled
    assert captured["timeout"] == notifier.WEBHOOK_TIMEOUT_SECONDS
    text = captured["json"]["text"]
    assert text.startswith("[조치 필요] 승격 권고")
    assert "challenger v2" in text


@pytest.mark.asyncio
async def test_notify_swallows_http_error(webhook_enabled, monkeypatch):
    """웹훅이 500 을 내도 호출부로 예외가 새지 않아야 합니다."""

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            raise RuntimeError("500 Internal Server Error")

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    await notifier.notify("제목", ["본문"])


@pytest.mark.asyncio
async def test_notify_swallows_timeout(webhook_enabled, monkeypatch):
    """타임아웃이 나도 본 작업이 계속되어야 합니다."""
    import httpx

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    await notifier.notify("제목", ["본문"])


# --------------------------------------------------------------------------- #
# 무엇을 알리고 무엇을 알리지 않는가
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reject_challenger_is_not_sent(sent):
    """정상 기각은 알림 대상이 아닙니다."""
    await notifier.notify_retrain_result(
        trigger_source="weekly_schedule",
        recommendation="REJECT_CHALLENGER",
        champion_version="v_a",
        challenger_version="v_b",
        champion_metrics=CHAMPION_METRICS,
        challenger_metrics=CHALLENGER_METRICS,
        samples=917_629,
        category="Servc",
    )
    assert sent == []


@pytest.mark.asyncio
async def test_promote_challenger_carries_both_versions(sent):
    await notifier.notify_retrain_result(
        trigger_source="weekly_schedule",
        recommendation="PROMOTE_CHALLENGER",
        champion_version="v_20260805_052203_525",
        challenger_version="v_20260812_030512_118",
        champion_metrics=CHAMPION_METRICS,
        challenger_metrics=CHALLENGER_METRICS,
        samples=917_629,
        category="Servc",
    )

    assert len(sent) == 1
    _, lines, level = sent[0]
    assert level == "action"
    body = "\n".join(lines)
    assert "v_20260805_052203_525" in body
    assert "v_20260812_030512_118" in body
    assert "R2 0.6824" in body
    assert "R2 0.6901" in body
    assert "917,629" in body
    # 홀드아웃 개선이 운영에서 재현되지 않은 전력이 있어, 곧바로 승격을 권하면 안 됩니다.
    assert "compare_servc_models_paired.py" in body


@pytest.mark.asyncio
async def test_holdout_overfit_is_warned_even_though_rejected(sent):
    """표본 부족 기각은 정상 기각이 아니라 지표를 믿을 수 없다는 신호입니다."""
    await notifier.notify_retrain_result(
        trigger_source="weekly_schedule",
        recommendation="REJECT_CHALLENGER",
        champion_version="v_a",
        challenger_version="v_b",
        champion_metrics=CHAMPION_METRICS,
        challenger_metrics=CHALLENGER_METRICS,
        samples=42,
        category="Servc",
        holdout_is_overfit=True,
    )

    assert len(sent) == 1
    _, lines, level = sent[0]
    assert level == "warning"
    assert "홀드아웃" in "\n".join(lines)


@pytest.mark.asyncio
async def test_empty_training_data_is_warned(sent):
    await notifier.notify_empty_training_data("weekly_schedule", "Servc")
    assert len(sent) == 1
    assert sent[0][2] == "warning"


# --------------------------------------------------------------------------- #
# 배선 지점
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_weekly_retrain_failure_notifies():
    from src.tasks import scheduled_tasks

    with (
        patch.object(
            scheduled_tasks,
            "run_retrain_pipeline_task",
            new=AsyncMock(side_effect=RuntimeError("학습 데이터 부족")),
        ),
        patch.object(scheduled_tasks, "notify_task_failure", new=AsyncMock()) as notify_failure,
    ):
        result = await scheduled_tasks.weekly_retrain_task({})

    assert result["status"] == "failed"
    notify_failure.assert_awaited_once()
    assert "학습 데이터 부족" in notify_failure.await_args.args[1]


@pytest.mark.asyncio
async def test_nightly_schedule_failure_notifies(monkeypatch, isolated_db):
    """02:00 수집이 실패하면 03:00 재학습이 옛 데이터로 돕니다."""
    from src.tasks import scheduled_tasks

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True, raising=False)
    session_factory = lambda: isolated_db  # noqa: E731
    isolated_db.close = lambda: None

    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(
            scheduled_tasks,
            "run_automation_pipeline",
            new=AsyncMock(side_effect=RuntimeError("수집 API 응답 없음")),
        ),
        patch.object(scheduled_tasks, "notify_task_failure", new=AsyncMock()) as notify_failure,
        pytest.raises(RuntimeError),
    ):
        await scheduled_tasks.nightly_schedule_task({})

    notify_failure.assert_awaited_once()
    assert "수집 API 응답 없음" in notify_failure.await_args.args[1]


@pytest.mark.asyncio
async def test_tests_never_send_to_a_real_webhook():
    """테스트 실행이 운영 채널로 나가면 안 됩니다.

    2026-08-06 에 .env 에 실제 Slack URL 이 들어오자 재학습 실패/빈 데이터셋
    테스트가 경고 6건을 실제 발신했습니다. conftest 의 차단이 살아 있는지
    고정합니다.
    """
    assert not settings.MLOPS_WEBHOOK_URL
