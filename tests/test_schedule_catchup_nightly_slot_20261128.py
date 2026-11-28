"""
tests/test_schedule_catchup_nightly_slot_20261128.py

기동 따라잡기의 야간 02:00 슬롯 누락 판정 보강 검증.

PC 를 매일 02:00 전에 끄면 야간 스케줄이 매일 빠진다. 기존 판정은 낮 수집이
`collected_at` 을 최신으로 올리면 임계(24시간)에 걸리지 않아 야간 누락을 잡지
못했다. 이 시험은 `schedule_run_log` 의 최신 성공 시작 시각을 기준으로
오늘(KST) 02:00 슬롯이 채워졌는지 판정하는 경로를 고정한다.

검증 항목:
1. 오늘 02:00 이후 + 마지막 성공이 어제 + collected_at 13시간 전이면 발화
2. 오늘 02:00 이후 성공 기록이 있으면 이 조건으로는 미발화
3. 현재가 오늘 02:00 이전이면 이 조건으로는 미발화
4. 쿨다운 중이면 기존대로 미발화
5. 성공 행이 하나도 없으면 발화
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

# 2026-11-28 09:00 UTC = 18:00 KST. 오늘(KST) 02:00 슬롯은 2026-11-27 17:00 UTC 다.
NOW_AFTER_SLOT = datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
# 13시간 전 수집 = 2026-11-28 05:00 KST 로 슬롯 이후다(기존 슬롯 판정은 미발화).
COLLECTED_13H_AGO = NOW_AFTER_SLOT - timedelta(hours=13)
# 2026-11-27 19:00 KST. 오늘 02:00 슬롯 이전의 마지막 성공이다.
SUCCESS_BEFORE_SLOT = datetime(2026, 11, 27, 10, 0, 0)
# 2026-11-28 03:00 KST. 오늘 슬롯 이후의 성공이다.
SUCCESS_AFTER_SLOT = datetime(2026, 11, 27, 18, 0, 0)


def _configure_catchup(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS", 6)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)


def _add_success_run(
    db: Any,
    started_at: datetime,
    *,
    success: bool = True,
    status: str | None = None,
) -> None:
    from src.app.models.schedule_run_log import ScheduleRunLog

    db.add(
        ScheduleRunLog(
            schedule_name="development_data_refresh",
            started_at=started_at,
            finished_at=started_at,
            success=success,
            status=status,
        )
    )
    db.commit()


def _judge(
    monkeypatch: pytest.MonkeyPatch,
    db: Any,
    *,
    now: datetime,
    collected_at: datetime | None,
    in_cooldown: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    from zoneinfo import ZoneInfo

    from src.tasks import scheduled_tasks

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=collected_at),
        patch.object(
            scheduled_tasks,
            "is_catchup_in_cooldown",
            return_value=(in_cooldown, "2026-11-28T08:00:00+00:00" if in_cooldown else None),
        ),
    ):
        return scheduled_tasks.check_schedule_catchup_needed(db=db, tz=ZoneInfo("Asia/Seoul"))


def test_nightly_slot_missed_when_last_success_before_today_slot(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) 낮 수집으로 collected_at 이 최신이어도 야간 성공이 없으면 발화합니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_BEFORE_SLOT)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is True
    assert reason == "nightly_slot_missed"
    assert details["last_success_at"] == SUCCESS_BEFORE_SLOT.isoformat()
    assert details["nightly_slot_at"] == "2026-11-27T17:00:00+00:00"
    assert details["target_task"] == "development_data_refresh"


def test_nightly_slot_not_missed_when_today_success_exists(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) 오늘 02:00 이후 성공 기록이 있으면 이 조건으로는 발화하지 않습니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_AFTER_SLOT)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is False
    assert reason == "threshold_not_exceeded"
    assert details["last_success_at"] == SUCCESS_AFTER_SLOT.isoformat()


def test_nightly_slot_not_missed_before_today_0200_kst(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) 현재가 오늘(KST) 02:00 이전이면 이 조건으로는 발화하지 않습니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_BEFORE_SLOT)

    now = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)  # 2026-11-28 01:00 KST
    collected_at = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)  # 2026-11-28 00:00 KST

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=now,
        collected_at=collected_at,
    )

    assert needed is False
    assert reason == "threshold_not_exceeded"
    assert "last_success_at" not in details


def test_nightly_slot_not_missed_in_cooldown(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(d) 쿨다운 중이면 야간 성공 이력과 무관하게 기존대로 건너뜁니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_BEFORE_SLOT)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
        in_cooldown=True,
    )

    assert needed is False
    assert reason == "in_cooldown"
    assert details["cooldown_hours"] == 6


def test_nightly_slot_missed_when_no_success_row(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(e) 대상 스케줄의 성공 행이 하나도 없으면 놓친 야간 작업으로 봅니다."""
    _configure_catchup(monkeypatch)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is True
    assert reason == "nightly_slot_missed"
    assert details["last_success_at"] is None


def test_nightly_slot_ignores_failed_runs(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실패 행은 성공 이력으로 세지 않으므로 마지막 성공 이전 시각으로 판정합니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_BEFORE_SLOT)
    _add_success_run(isolated_db, SUCCESS_AFTER_SLOT, success=False)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is True
    assert reason == "nightly_slot_missed"
    assert details["last_success_at"] == SUCCESS_BEFORE_SLOT.isoformat()


def test_nightly_slot_missed_when_today_only_skipped_success(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(f) 오늘 슬롯 이후 행이 success=True, status='skipped' 뿐이면 성공으로 보지 않습니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_BEFORE_SLOT)
    _add_success_run(isolated_db, SUCCESS_AFTER_SLOT, status="skipped")

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is True
    assert reason == "nightly_slot_missed"
    assert details["last_success_at"] == SUCCESS_BEFORE_SLOT.isoformat()


def test_nightly_slot_success_with_null_status_still_counts(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(g) status 를 채우지 않은 기존 성공 행은 지금처럼 슬롯 성공으로 봅니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_AFTER_SLOT, status=None)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is False
    assert reason == "threshold_not_exceeded"
    assert details["last_success_at"] == SUCCESS_AFTER_SLOT.isoformat()


def test_nightly_slot_success_after_skipped_row_counts(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(h) 슬롯 이후 skipped 행과 그 뒤 실제 성공 행이 함께 있으면 후자를 씁니다."""
    _configure_catchup(monkeypatch)
    _add_success_run(isolated_db, SUCCESS_AFTER_SLOT, status="skipped")
    later_success = SUCCESS_AFTER_SLOT + timedelta(hours=1)
    _add_success_run(isolated_db, later_success)

    needed, reason, details = _judge(
        monkeypatch,
        isolated_db,
        now=NOW_AFTER_SLOT,
        collected_at=COLLECTED_13H_AGO,
    )

    assert needed is False
    assert reason == "threshold_not_exceeded"
    assert details["last_success_at"] == later_success.isoformat()
