"""tests/test_search_index_parity.py

Meilisearch 읽기 모델 건수 대조 점검 회귀 테스트.

검증 항목:
1. 공고·낙찰이 모두 일치하면 ok.
2. 한쪽만 불일치하면 mismatch 와 db·meili·diff 값.
3. MEILI_ENABLED 가 거짓이면 Meili 도 DB 도 조회하지 않고 skipped.
4. Meili 에 연결하지 못하면 unavailable.
5. 점검 경로가 색인 쓰기나 재구축을 부르지 않는다 (읽기 전용).
6. nightly_schedule_task outcome 에 search_index_parity 가 붙고, 불일치여도
   최종 status 가 바뀌지 않는다.
7. 불일치 시 경고 로그가 남는다.

실제 Meilisearch 나 MySQL 에 접속하지 않는다. 가짜 클라이언트와 DB 로만 검증한다.
"""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import func, select

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import search_index_parity
from src.app.services.bid_queries import latest_announcement_filter
from src.app.services.search_index import (
    INDEX_UID,
    MeiliSearchClient,
    SearchBackendUnavailable,
)
from src.app.services.search_index_parity import check_search_index_parity, count_db_announcements
from src.tasks import scheduled_tasks

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_BASELINE_PATH = PROJECT_ROOT / "data" / "backups" / "schema_signature_baseline.json"

PARITY_PREMISE_BROKEN = (
    "GROUP BY 건수와 row_number 파티션 수의 동치 전제가 깨졌습니다. "
    "bid_announcements 의 파티션 키(bid_ntce_no, category)가 NULL 을 허용하면 "
    "count_db_announcements 와 latest_announcement_filter 가 다른 값을 낼 수 있습니다."
)


def _fake_db(announcement_count: int, result_count: int) -> MagicMock:
    """COUNT 집계 질의 순서(공고, 낙찰)대로 값을 돌려주는 DB 대역."""
    db = MagicMock()
    db.scalar.side_effect = [announcement_count, result_count]
    return db


def _fake_client(announcement_count: int, result_count: int) -> MagicMock:
    """count 호출 순서(announcement, result)대로 값을 돌려주는 Meili 대역."""
    client = MagicMock()
    client.count.side_effect = [announcement_count, result_count]
    return client


# --------------------------------------------------------------------------- #
# MeiliSearchClient.count
# --------------------------------------------------------------------------- #


def test_count_는_page와_hitsPerPage로_정확한_totalHits를_읽는다(monkeypatch) -> None:
    """offset·limit 검색의 추정치가 아니라 page 기반 정확한 총수를 읽어야 합니다."""
    response = MagicMock()
    response.content = b"{}"
    response.json.return_value = {"hits": [], "totalHits": 12345}
    response.raise_for_status.return_value = None
    request = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    total = MeiliSearchClient(base_url="http://search", master_key="test-key").count(
        dataset="announcement"
    )

    assert total == 12345
    assert request.call_args.args[:2] == ("POST", f"http://search/indexes/{INDEX_UID}/search")
    body = request.call_args.kwargs["json"]
    assert body["page"] == 1
    assert body["hitsPerPage"] == 1
    assert "offset" not in body
    assert "limit" not in body
    assert body["filter"] == 'dataset = "announcement"'


def test_count_는_totalHits_가_없으면_unavailable_로_처리한다(monkeypatch) -> None:
    response = MagicMock()
    response.content = b"{}"
    response.json.return_value = {"hits": [], "estimatedTotalHits": 10}
    response.raise_for_status.return_value = None
    monkeypatch.setattr(httpx, "request", MagicMock(return_value=response))

    with pytest.raises(SearchBackendUnavailable):
        MeiliSearchClient(base_url="http://search", master_key="test-key").count(dataset="result")


# --------------------------------------------------------------------------- #
# check_search_index_parity 상태 계약
# --------------------------------------------------------------------------- #


def test_공고와_낙찰이_모두_일치하면_ok(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    db = _fake_db(100, 200)
    client = _fake_client(100, 200)

    result = check_search_index_parity(db, client=client)

    assert result["status"] == "ok"
    assert result["announcements"] == {"db": 100, "meili": 100, "diff": 0}
    assert result["results"] == {"db": 200, "meili": 200, "diff": 0}


def test_공고가_부족하면_mismatch_와_음수_diff(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    db = _fake_db(100, 200)
    client = _fake_client(97, 200)

    result = check_search_index_parity(db, client=client)

    assert result["status"] == "mismatch"
    assert result["announcements"] == {"db": 100, "meili": 97, "diff": -3}
    assert result["results"]["diff"] == 0


def test_낙찰이_많으면_mismatch_와_양수_diff(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    db = _fake_db(100, 200)
    client = _fake_client(100, 205)

    result = check_search_index_parity(db, client=client)

    assert result["status"] == "mismatch"
    assert result["announcements"]["diff"] == 0
    assert result["results"] == {"db": 200, "meili": 205, "diff": 5}


def test_MEILI_ENABLED_거짓이면_조회없이_skipped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    db = MagicMock()
    client = MagicMock()

    result = check_search_index_parity(db, client=client)

    assert result["status"] == "skipped"
    client.count.assert_not_called()
    db.scalar.assert_not_called()


def test_Meili_연결실패면_db_조회없이_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    db = MagicMock()
    client = MagicMock()
    client.count.side_effect = SearchBackendUnavailable("offline")

    result = check_search_index_parity(db, client=client)

    assert result["status"] == "unavailable"
    db.scalar.assert_not_called()


# --------------------------------------------------------------------------- #
# 읽기 전용 보장
# --------------------------------------------------------------------------- #


def test_점검모듈이_색인쓰기나_재구축을_참조하지_않는다() -> None:
    """호출 그래프 어디에도 쓰기·재구축 진입점이 없어야 합니다."""
    source = inspect.getsource(search_index_parity)

    for forbidden in (
        "sync_search_index(",
        "configure_index(",
        ".upsert(",
        "run_data_reconciliation",
    ):
        assert forbidden not in source, f"읽기 전용 위반 참조 발견: {forbidden}"


def test_점검경로가_색인쓰기와_커밋을_부르지_않는다(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    db = _fake_db(100, 200)
    client = _fake_client(100, 200)

    with (
        patch("src.app.services.search_index.sync_search_index") as sync_index,
        patch.object(MeiliSearchClient, "configure_index") as configure_index,
        patch.object(MeiliSearchClient, "upsert") as upsert,
    ):
        result = check_search_index_parity(db, client=client)

    assert result["status"] == "ok"
    sync_index.assert_not_called()
    configure_index.assert_not_called()
    upsert.assert_not_called()
    client.upsert.assert_not_called()
    client.configure_index.assert_not_called()
    db.commit.assert_not_called()
    db.add.assert_not_called()


# --------------------------------------------------------------------------- #
# 건수 정의 동치
# --------------------------------------------------------------------------- #


def test_group_by_건수가_latest_announcement_filter_파티션수와_같다(isolated_db) -> None:
    """차수가 여러 개인 조합과 카테고리만 다른 같은 공고번호가 섞여도 두 정의가 동치입니다."""
    now = utcnow()
    isolated_db.add_all(
        [
            BidAnnouncement(
                bid_ntce_no="PARITY-A",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="PARITY-A",
                bid_ntce_ord="001",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="PARITY-A",
                bid_ntce_ord="002",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="PARITY-B",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="PARITY-B",
                bid_ntce_ord="000",
                category="Thng",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="PARITY-C",
                bid_ntce_ord="000",
                category="Cnstwk",
                bid_ntce_dt=now,
                collected_at=now,
            ),
        ]
    )
    isolated_db.commit()

    latest = latest_announcement_filter(select(BidAnnouncement.id)).subquery()
    expected = int(isolated_db.scalar(select(func.count()).select_from(latest)) or 0)

    assert expected == 4
    assert count_db_announcements(isolated_db) == expected


def test_공고_파티션_키는_ORM에서_NOT_NULL이다() -> None:
    """두 건수 정의의 동치 전제를 ORM 컬럼 nullable=False 로 고정합니다."""
    columns = BidAnnouncement.__table__.c

    assert columns.bid_ntce_no.nullable is False, PARITY_PREMISE_BROKEN
    assert columns.category.nullable is False, PARITY_PREMISE_BROKEN


def test_공고_파티션_키는_G1_기준선에서_NOT_NULL이다() -> None:
    """운영 MySQL 스키마 서명에서도 같은 전제를 고정합니다."""
    baseline = json.loads(SCHEMA_BASELINE_PATH.read_text(encoding="utf-8"))
    columns = {
        column["name"]: column for column in baseline["tables"]["bid_announcements"]["columns"]
    }

    assert columns["bid_ntce_no"]["nullable"] is False, PARITY_PREMISE_BROKEN
    assert columns["category"]["nullable"] is False, PARITY_PREMISE_BROKEN


# --------------------------------------------------------------------------- #
# 야간 스케줄 통합
# --------------------------------------------------------------------------- #


def test_search_index_parity_는_후속실패집계에_포함되지_않는다() -> None:
    """불일치는 스케줄 실패가 아니라 경고다."""
    assert "search_index_parity" not in scheduled_tasks.FOLLOWUP_KEYS


@pytest.mark.asyncio
async def test_nightly_outcome_에_불일치가_담겨도_status_는_유지된다(monkeypatch) -> None:
    dummy_claim = MagicMock()
    dummy_claim.acquired = True
    dummy_claim.key = "claim_key"
    dummy_claim.token = "claim_token"  # noqa: S105

    mismatch: dict[str, Any] = {
        "status": "mismatch",
        "announcements": {"db": 100, "meili": 97, "diff": -3},
        "results": {"db": 200, "meili": 200, "diff": 0},
    }

    with (
        patch("src.tasks.scheduled_tasks.settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True),
        patch("src.tasks.scheduled_tasks.acquire_schedule_claim", return_value=dummy_claim),
        patch("src.tasks.scheduled_tasks._create_scheduled_execution", return_value="test_exec"),
        patch(
            "src.tasks.scheduled_tasks.run_automation_pipeline",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_ranking_snapshots",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_compare_stats_snapshots",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_institution_stats",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._check_mysql_stats_freshness",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._check_restore_drill_freshness",
            return_value={"status": "success"},
        ),
        patch("src.tasks.scheduled_tasks._check_search_index_parity", return_value=mismatch),
        patch("src.tasks.scheduled_tasks.release_schedule_claim"),
    ):
        outcome = await scheduled_tasks.nightly_schedule_task({})

    assert outcome["status"] == "success"
    assert outcome["search_index_parity"] == mismatch
    assert "failed_followups" not in outcome


# --------------------------------------------------------------------------- #
# 경고 로그
# --------------------------------------------------------------------------- #


def test_불일치시_경고로그에_수치와_수동재구축_안내가_남는다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mismatch: dict[str, Any] = {
        "status": "mismatch",
        "announcements": {"db": 4_000_001, "meili": 3_999_001, "diff": -1000},
        "results": {"db": 2_000_000, "meili": 2_000_500, "diff": 500},
    }

    with (
        patch(
            "src.app.services.search_index_parity.check_search_index_parity",
            return_value=mismatch,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        result = scheduled_tasks._check_search_index_parity()

    assert result == mismatch

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) >= 1
    message = warnings[0].getMessage()
    assert "4000001" in message
    assert "3999001" in message
    assert "-1000" in message
    assert "2000000" in message
    assert "2000500" in message
    assert "500" in message
    assert "scripts/run_data_reconciliation.py" in message


def test_일치시_경고로그가_남지_않는다(caplog: pytest.LogCaptureFixture) -> None:
    ok_payload: dict[str, Any] = {
        "status": "ok",
        "announcements": {"db": 10, "meili": 10, "diff": 0},
        "results": {"db": 20, "meili": 20, "diff": 0},
    }

    with (
        patch(
            "src.app.services.search_index_parity.check_search_index_parity",
            return_value=ok_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        result = scheduled_tasks._check_search_index_parity()

    assert result == ok_payload
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []
    assert any("정상" in record.getMessage() for record in caplog.records)


def test_점검이_예외를_던져도_야간작업이_중단되지_않는다() -> None:
    with patch(
        "src.app.services.search_index_parity.check_search_index_parity",
        side_effect=RuntimeError("DB 연결 시간 초과 모의"),
    ):
        result = scheduled_tasks._check_search_index_parity()

    assert isinstance(result, dict)
    assert result.get("status") == "failed"
    assert "DB 연결 시간 초과 모의" in result.get("error", "")
