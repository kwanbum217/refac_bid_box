"""
tests/test_automation_bundle_parity.py

원본 apps/pipelines/tests.py LocalAutomationBundleTests 이식입니다.

대응하는 원본 테스트:

- test_run_local_automation_bundle_records_successful_nightly_run
- test_run_local_automation_bundle_short_circuits_preflight_only
- test_run_local_automation_bundle_marks_failure

원본은 Django 관리 명령을 순서대로 부르는 동기 함수(run_local_automation_bundle)
였고, 이식본은 같은 자리를 Arq 태스크(run_automation_pipeline)가 대신합니다.
원본이 command_runner 를 주입받아 호출 순서를 봤듯 여기서는 STEP_RUNNERS 를
바꿔 끼워 같은 것을 봅니다.

원본과 다른 점이 둘 있습니다.

| 항목 | 원본 | 이식본 |
| --- | --- | --- |
| 실패 전파 | RuntimeError 를 그대로 올림 | status="failed" 를 반환 |
| preflight 스테이지명 | "preflight" 로 표기 | 실행할 스텝이 없어 비움 |

실패를 올리지 않는 것은 Arq 워커가 예외를 재시도 대상으로 보기 때문입니다.
스텝 없이 실패시킬 일이 아니라 결과로 돌려주고 실행 이력에 남깁니다.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from src.app.models.chatbot import PipelineExecution
from src.tasks import automation_tasks


@pytest.fixture
def worker_db(isolated_db, monkeypatch):
    """태스크는 SessionLocal 을 직접 열므로 같은 인메모리 엔진에 묶어 줍니다."""
    engine = isolated_db.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(automation_tasks, "SessionLocal", factory)
    return isolated_db


def _add_execution(db, execution_id: str, run_mode: str) -> PipelineExecution:
    row = PipelineExecution(
        execution_id=execution_id,
        pipeline_name="BIDBOX_Personal_Pipeline_Staging",
        run_mode=run_mode,
        status="queued",
        source="chatbot",
    )
    db.add(row)
    db.commit()
    return row


def _recording_runners(calls: list[str], failing_step: str = ""):
    """STEP_RUNNERS 를 호출만 기록하는 것으로 바꿉니다."""

    def make(step: str):
        def runner(db, **kwargs):
            calls.append(step)
            if step == failing_step:
                raise RuntimeError("validation failed")
            return f"{step} done", {}

        return runner

    return {step: make(step) for step in ("collect", "rag", "predict", "retrain", "inspect")}


@pytest.mark.asyncio
async def test_run_local_automation_bundle_records_successful_nightly_run(worker_db):
    """야간 배치는 collect-rag-predict-inspect 를 순서대로 돌고 성공으로 닫힌다.

    순서가 뒤집히면 아직 수집되지 않은 데이터로 KB 를 만들거나 모델을
    검증하게 됩니다. 스텝 집합만이 아니라 순서까지 계약입니다.
    """
    _add_execution(worker_db, "local-nightly-001", "nightly_schedule")
    calls: list[str] = []

    with patch.object(automation_tasks, "STEP_RUNNERS", _recording_runners(calls)):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="local-nightly-001",
            run_mode="nightly_schedule",
        )

    assert calls == ["collect", "rag", "predict", "inspect"]
    assert result["status"] == "success"
    assert result["completed_steps"] == ["collect", "rag", "predict", "inspect"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == "local-nightly-001")
        .one()
    )
    assert execution.status == "success"
    assert execution.stage_name == "inspect"
    assert execution.stage_status == "success"
    assert execution.metrics_json["completed_steps"] == [
        "collect",
        "rag",
        "predict",
        "inspect",
    ]


@pytest.mark.asyncio
async def test_run_local_automation_bundle_short_circuits_preflight_only(worker_db):
    """preflight_only 는 어떤 스텝도 실행하지 않고 바로 성공으로 끝난다.

    사전 점검은 실행 가능 여부만 보는 모드입니다. 여기서 수집이나 학습이
    돌면 "가볍게 확인만" 하려던 요청이 전체 배치가 됩니다.
    """
    _add_execution(worker_db, "local-preflight-001", "preflight_only")
    calls: list[str] = []

    with patch.object(automation_tasks, "STEP_RUNNERS", _recording_runners(calls)):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="local-preflight-001",
            run_mode="preflight_only",
        )

    assert calls == []
    assert result["status"] == "success"
    assert result["completed_steps"] == []

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == "local-preflight-001")
        .one()
    )
    assert execution.status == "success"
    assert execution.stage_status == "success"


@pytest.mark.asyncio
async def test_manual_retrain_runs_only_retrain_step(worker_db):
    """수동 재학습은 수집·KB 갱신을 섞지 않고 기존 재학습 태스크만 실행한다."""
    _add_execution(worker_db, "manual-retrain-001", "retrain_only")
    calls: list[str] = []

    with patch.object(automation_tasks, "STEP_RUNNERS", _recording_runners(calls)):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="manual-retrain-001",
            run_mode="retrain_only",
        )

    assert calls == ["retrain"]
    assert result == {
        "status": "success",
        "run_mode": "retrain_only",
        "completed_steps": ["retrain"],
    }


@pytest.mark.asyncio
async def test_development_refresh_skips_dashboard_full_scan(worker_db):
    """개발 정기 수집은 신규분만 반영하고 대시보드 전수 집계를 건너뜁니다."""
    _add_execution(worker_db, "development-refresh-001", "refresh_data")
    collect_kwargs: dict = {}

    def collect_runner(db, **kwargs):
        collect_kwargs.update(kwargs)
        return "collect done", {}

    runners = _recording_runners([])
    runners["collect"] = collect_runner
    with patch.object(automation_tasks, "STEP_RUNNERS", runners):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="development-refresh-001",
            run_mode="refresh_data",
        )

    assert result["status"] == "success"
    assert collect_kwargs["refresh_aggregates"] is False


@pytest.mark.asyncio
async def test_development_refresh_uses_delta_kb_window(worker_db):
    """개발 정기 수집은 전체 KB 재구축 대신 최근 적재분만 upsert합니다."""
    _add_execution(worker_db, "development-refresh-002", "refresh_data")
    rag_kwargs: dict = {}

    def rag_runner(db, **kwargs):
        rag_kwargs.update(kwargs)
        return "rag done", {}

    runners = _recording_runners([])
    runners["rag"] = rag_runner
    with patch.object(automation_tasks, "STEP_RUNNERS", runners):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="development-refresh-002",
            run_mode="refresh_data",
        )

    assert result["status"] == "success"
    assert rag_kwargs["collected_since"] is not None


@pytest.mark.asyncio
async def test_run_local_automation_bundle_marks_failure(worker_db):
    """중간 스텝이 실패하면 그 자리에서 멈추고 실행 이력에 실패를 남긴다.

    실패한 스텝 이름과 사유가 남지 않으면 화면에는 "실패" 만 뜨고 어디서
    끊겼는지 알 수 없습니다. 이후 스텝을 계속 도는 것도 막아야 합니다.
    """
    _add_execution(worker_db, "local-nightly-002", "nightly_schedule")
    calls: list[str] = []

    with patch.object(
        automation_tasks,
        "STEP_RUNNERS",
        _recording_runners(calls, failing_step="predict"),
    ):
        result = await automation_tasks.run_automation_pipeline(
            {},
            execution_id="local-nightly-002",
            run_mode="nightly_schedule",
        )

    # predict 에서 끊겼으므로 inspect 는 돌지 않아야 합니다.
    assert calls == ["collect", "rag", "predict"]
    assert result["status"] == "failed"
    assert "validation failed" in result["error"]

    worker_db.expire_all()
    execution = (
        worker_db.query(PipelineExecution)
        .filter(PipelineExecution.execution_id == "local-nightly-002")
        .one()
    )
    assert execution.status == "failed"
    assert execution.stage_name == "predict"
    assert "validation failed" in execution.logs_summary
