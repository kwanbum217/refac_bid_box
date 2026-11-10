"""tests/test_manual_retrain_fanout_20261109.py

I-ai 검토 F-03 회귀 시험: 수동 재학습의 카테고리 누락 결함.

관리자 재학습 버튼과 챗봇 model_retrain 이 쓰는 retrain_only 자동화가
run_retrain_pipeline_task 를 category_code 없이 불러 항상 ValueError 로
끝났습니다. 수동·주간 두 경로가 같은 fan-out 함수를 쓰는지, 카테고리 하나의
예외가 나머지를 막지 않는지, 이미 도는 재학습과 겹치지 않는지, 주간 재학습의
반환 형식이 그대로인지 확인합니다.

실제 학습·DB·Redis 서버는 호출하지 않고 경계만 대역으로 바꿉니다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.app.models.chatbot import PipelineExecution
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks import automation_tasks, scheduled_tasks
from src.tasks.automation_steps import _step_retrain
from src.tasks.scheduled_tasks import (
    WEEKLY_RETRAIN_CLAIM_KEY,
    set_schedule_redis_conn,
    weekly_retrain_task,
)
from tests.fake_redis import FakeRedisClient, FakeRedisConnection


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """실제 Redis 대신 테스트마다 비워지는 대역 연결을 씁니다."""
    conn = FakeRedisConnection(FakeRedisClient(), label="test_manual_retrain")
    set_schedule_redis_conn(conn)
    yield conn
    set_schedule_redis_conn(None)


@pytest.fixture(autouse=True)
def all_categories(monkeypatch):
    """설정 파일과 무관하게 CATEGORY_MODEL_NAMES 전체를 대상으로 봅니다."""
    monkeypatch.setattr(scheduled_tasks.settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "")


def _fake_retrain_success(calls: list[tuple[str, str | None]]):
    async def fake_retrain(
        ctx: dict[str, Any],
        *,
        trigger_source: str,
        category_code: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append((trigger_source, category_code))
        return {
            "status": "success",
            "category": category_code,
            "version": f"v_test_{category_code}",
            "samples": 1,
            "recommendation": "REJECT_CHALLENGER",
        }

    return fake_retrain


async def test_step_retrain_passes_category_code_for_every_category(monkeypatch):
    """수동 재학습이 카테고리마다 category_code 를 넘겨 호출한다."""
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        scheduled_tasks,
        "run_retrain_pipeline_task",
        _fake_retrain_success(calls),
    )

    summary, outcome = await _step_retrain(None)

    assert [category for _source, category in calls] == sorted(CATEGORY_MODEL_NAMES)
    assert {source for source, _category in calls} == {"manual_api"}
    assert outcome["status"] == "success"
    for category in CATEGORY_MODEL_NAMES:
        assert f"{category}: 성공 (버전 v_test_{category}" in summary


async def test_step_retrain_isolates_category_failure(monkeypatch):
    """한 카테고리 예외가 다른 카테고리 실행을 막지 않는다."""
    calls: list[str | None] = []

    async def fake_retrain(
        ctx: dict[str, Any],
        *,
        trigger_source: str,
        category_code: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(category_code)
        if category_code == "Servc":
            raise RuntimeError("Servc 학습 모의 실패")
        return {"status": "success", "category": category_code, "version": "v1"}

    monkeypatch.setattr(scheduled_tasks, "run_retrain_pipeline_task", fake_retrain)

    summary, outcome = await _step_retrain(None)

    assert sorted(calls) == sorted(CATEGORY_MODEL_NAMES)
    assert outcome["status"] == "partial_failure"
    assert "Servc: 실패 (Servc 학습 모의 실패)" in summary
    assert "Thng: 성공" in summary
    assert "Cnstwk: 성공" in summary


async def test_step_retrain_skips_when_claim_already_held(isolate_schedule_redis, monkeypatch):
    """주간 재학습이 같은 선점을 잡고 있으면 학습 없이 already_running 으로 끝난다."""
    isolate_schedule_redis.client().set(WEEKLY_RETRAIN_CLAIM_KEY, "held", nx=True)
    retrain = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "run_retrain_pipeline_task", retrain)

    summary, outcome = await _step_retrain(None)

    assert outcome == {"status": "skipped", "reason": "already_running"}
    assert "이미 실행 중" in summary
    retrain.assert_not_awaited()
    assert isolate_schedule_redis.client().get(WEEKLY_RETRAIN_CLAIM_KEY) == "held"


async def test_weekly_retrain_task_return_shape_unchanged(monkeypatch):
    """주간 재학습은 기존과 같은 status·trigger_source·categories 형식을 돌려준다."""
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        scheduled_tasks,
        "run_retrain_pipeline_task",
        _fake_retrain_success(calls),
    )

    outcome = await weekly_retrain_task({})

    assert set(outcome) == {"status", "trigger_source", "categories"}
    assert outcome["status"] == "success"
    assert outcome["trigger_source"] == "weekly_schedule"
    assert list(outcome["categories"]) == sorted(CATEGORY_MODEL_NAMES)
    assert {source for source, _category in calls} == {"weekly_schedule"}
    for category in CATEGORY_MODEL_NAMES:
        assert outcome["categories"][category]["status"] == "success"


@pytest.fixture
def worker_db(isolated_db, monkeypatch):
    """retrain_only 자동화가 여는 세션을 인메모리 엔진에 묶습니다."""
    engine = isolated_db.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(automation_tasks, "SessionLocal", factory)
    return isolated_db


async def test_retrain_only_automation_runs_real_step_retrain(worker_db, monkeypatch):
    """retrain_only 실행이 STEP_RUNNERS 교체 없이 실제 _step_retrain 을 통과한다."""
    worker_db.add(
        PipelineExecution(
            execution_id="manual-retrain-f03",
            pipeline_name="refac_bid_box_pipeline",
            run_mode="retrain_only",
            status="queued",
            source="admin",
        )
    )
    worker_db.commit()

    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        scheduled_tasks,
        "run_retrain_pipeline_task",
        _fake_retrain_success(calls),
    )

    result = await automation_tasks.run_automation_pipeline(
        {},
        execution_id="manual-retrain-f03",
        run_mode="retrain_only",
    )

    assert result["status"] == "success"
    assert result["completed_steps"] == ["retrain"]
    assert [category for _source, category in calls] == sorted(CATEGORY_MODEL_NAMES)

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == "manual-retrain-f03")
        .one()
    )
    assert execution.status == "success"
    assert execution.stage_name == "retrain"
    assert execution.metrics_json["completed_steps"] == ["retrain"]
