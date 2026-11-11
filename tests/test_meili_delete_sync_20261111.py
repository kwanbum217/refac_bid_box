"""tests/test_meili_delete_sync_20261111.py

Meilisearch 색인 잔존 문서 정리와 야간 건수 대조 알림 승격 회귀 테스트.

검증 항목:
1. iter_document_ids 가 documents API 를 페이지로 끝까지 순회한다.
2. 원본에 없는 색인 문서만 삭제 후보가 된다 (공고·낙찰 각각).
3. 기본 dry-run 은 delete_documents 를 부르지 않는다.
4. 후보가 데이터셋 건수의 1% 를 넘으면 종료 코드 2 로 거부하고,
   --max-ratio 로 상한을 올리면 진행한다.
5. 야간 대조가 불일치·대조 불가일 때 notify 를 한 번 부르고,
   정상일 때는 부르지 않는다.

실제 Meilisearch 나 MySQL 에 접속하지 않는다. 가짜 클라이언트와 SQLite 로만 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from scripts import sync_search_index_deletions as script
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.search_index import INDEX_UID, MeiliSearchClient
from src.tasks import scheduled_tasks


class _NonClosingSession:
    """스크립트가 세션을 닫아도 시험 픽스처 세션을 살려 둡니다."""

    def __init__(self, session):
        self._session = session

    def execute(self, statement):
        return self._session.execute(statement)

    def close(self) -> None:
        pass


class _FakeIndex:
    """색인 문서 id 를 데이터셋별로 들고 있는 Meilisearch 대역."""

    def __init__(self, documents: dict[str, list[str]]):
        self._documents = documents
        self.deleted: list[list[str]] = []

    def iter_document_ids(self, dataset: str, *, batch_size: int = 10_000):
        documents = self._documents.get(dataset, [])
        for start in range(0, len(documents), batch_size):
            yield from documents[start : start + batch_size]

    def delete_documents(self, ids) -> int:
        self.deleted.append(list(ids))
        return 42


def _run_script(monkeypatch, db, index: _FakeIndex, argv: list[str]) -> int:
    monkeypatch.setattr(script, "SessionLocal", lambda: _NonClosingSession(db))
    monkeypatch.setattr(script, "MeiliSearchClient", lambda: index)
    return script.main(argv)


# --------------------------------------------------------------------------- #
# 1. 문서 id 순회
# --------------------------------------------------------------------------- #


def test_iter_document_ids_는_끝까지_순회한다(monkeypatch) -> None:
    """limit·offset 을 넘기며 모든 페이지를 읽고 dataset 이 다른 행은 거른다."""
    pages = [
        {
            "results": [
                {"id": "result_1", "dataset": "result"},
                {"id": "result_2", "dataset": "result"},
            ],
            "total": 5,
        },
        {
            "results": [
                {"id": "announcement_Servc_A", "dataset": "announcement"},
                {"id": "result_3", "dataset": "result"},
            ],
            "total": 5,
        },
        {"results": [{"id": "result_4", "dataset": "result"}], "total": 5},
    ]
    calls: list[dict] = []

    def fake_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return pages[len(calls) - 1]

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    monkeypatch.setattr(client, "_request", fake_request)

    ids = list(client.iter_document_ids("result", batch_size=2))

    assert ids == ["result_1", "result_2", "result_3", "result_4"]
    assert len(calls) == 3
    assert all(call["path"] == f"/indexes/{INDEX_UID}/documents" for call in calls)
    assert [call["params"]["offset"] for call in calls] == [0, 2, 4]
    assert all(call["params"]["fields"] == "id,dataset" for call in calls)


def test_iter_document_ids_는_문서목록이_없으면_unavailable(monkeypatch) -> None:
    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {})

    with pytest.raises(Exception, match="문서 목록"):
        list(client.iter_document_ids("result"))


def test_delete_documents_는_delete_batch로_보낸다(monkeypatch) -> None:
    seen: dict = {}

    def fake_request(method, path, **kwargs):
        seen.update({"method": method, "path": path, "json": kwargs.get("json")})
        return {"taskUid": 7}

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    monkeypatch.setattr(client, "_request", fake_request)

    assert client.delete_documents(["result_1", "result_2"]) == 7
    assert seen["method"] == "POST"
    assert seen["path"] == f"/indexes/{INDEX_UID}/documents/delete-batch"
    assert seen["json"] == ["result_1", "result_2"]


def test_delete_documents_는_빈목록이면_요청하지_않는다(monkeypatch) -> None:
    request = MagicMock()
    monkeypatch.setattr(httpx, "request", request)

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")

    assert client.delete_documents([]) is None
    request.assert_not_called()


# --------------------------------------------------------------------------- #
# 2. 후보 판정
# --------------------------------------------------------------------------- #


def test_공고는_원본에_없는_조합만_후보가_된다(isolated_db) -> None:
    now = utcnow()
    isolated_db.add_all(
        [
            # 같은 공고번호가 차수만 다르게 있으면 색인 문서는 하나다.
            BidAnnouncement(
                bid_ntce_no="DEL-A",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="DEL-A",
                bid_ntce_ord="001",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            ),
            BidAnnouncement(
                bid_ntce_no="DEL-B",
                bid_ntce_ord="000",
                category="Thng",
                bid_ntce_dt=now,
                collected_at=now,
            ),
        ]
    )
    isolated_db.commit()

    candidates = script.stale_ids_in_batch(
        isolated_db,
        script.DATASET_ANNOUNCEMENT,
        [
            "announcement_Servc_DEL-A",
            "announcement_Thng_DEL-B",
            "announcement_Servc_DEL-GONE",
            "announcement_Thng_DEL-GONE",
            "announcement_",
        ],
    )

    assert candidates == [
        "announcement_Servc_DEL-GONE",
        "announcement_Thng_DEL-GONE",
        "announcement_",
    ]


def test_낙찰은_원본에_없는_id만_후보가_된다(isolated_db) -> None:
    now = utcnow()
    added = BidResult(
        bid_ntce_no="DEL-R",
        bid_ntce_ord="00",
        category="Servc",
        rl_openg_dt=now,
        collected_at=now,
    )
    isolated_db.add(added)
    isolated_db.commit()
    surviving_id = added.id

    candidates = script.stale_ids_in_batch(
        isolated_db,
        script.DATASET_RESULT,
        [f"result_{surviving_id}", "result_999999", "announcement_1", "result_x"],
    )

    assert candidates == ["result_999999", "announcement_1", "result_x"]


# --------------------------------------------------------------------------- #
# 3. dry-run
# --------------------------------------------------------------------------- #


def test_기본값은_dry_run이라_삭제하지_않는다(monkeypatch, isolated_db, capsys) -> None:
    # 색인 200건 중 1건만 원본에 없어 상한(1%) 이내다.
    _seed_results(isolated_db, 199)
    index = _FakeIndex(
        {
            "announcement": [],
            "result": [f"result_{value}" for value in range(1, 200)] + ["result_999999"],
        }
    )

    exit_code = _run_script(monkeypatch, isolated_db, index, [])

    assert exit_code == script.EXIT_OK
    assert index.deleted == []
    output = capsys.readouterr().out
    assert "dry-run" in output
    assert "result_999999" in output


def test_상한을_넘으면_dry_run도_거부한다(monkeypatch, isolated_db, capsys) -> None:
    """상한 초과는 dry-run 에서도 같은 종료 코드로 드러나야 한다."""
    index = _FakeIndex({"announcement": [], "result": ["result_999999"]})

    exit_code = _run_script(monkeypatch, isolated_db, index, [])

    assert exit_code == script.EXIT_RATIO_EXCEEDED
    assert index.deleted == []
    assert "거부" in capsys.readouterr().err


def test_도움말이_깨지지_않는다(capsys) -> None:
    """help 문자열의 퍼센트 표기가 argparse 포맷을 깨뜨리지 않게 고정한다."""
    with pytest.raises(SystemExit) as excinfo:
        script.main(["--help"])

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "--max-ratio" in output
    assert "1%" in output


# --------------------------------------------------------------------------- #
# 4. 삭제 비율 상한
# --------------------------------------------------------------------------- #


def _seed_results(isolated_db, count: int) -> None:
    now = utcnow()
    isolated_db.add_all(
        BidResult(
            bid_ntce_no=f"DEL-RATIO-{index}",
            bid_ntce_ord="00",
            category="Servc",
            rl_openg_dt=now,
            collected_at=now,
        )
        for index in range(count)
    )
    isolated_db.commit()


def test_상한_1퍼센트를_넘으면_거부하고_아무것도_지우지_않는다(
    monkeypatch, isolated_db, capsys
) -> None:
    _seed_results(isolated_db, 197)
    index = _FakeIndex(
        {
            "announcement": [],
            # 색인 200건 중 3건이 원본에 없다 -> 1.5% 로 1% 상한 초과
            "result": [f"result_{value}" for value in range(1, 198)]
            + ["result_900001", "result_900002", "result_900003"],
        }
    )

    exit_code = _run_script(monkeypatch, isolated_db, index, ["--execute"])

    assert exit_code == script.EXIT_RATIO_EXCEEDED
    assert exit_code == 2
    assert index.deleted == []
    assert "거부" in capsys.readouterr().err


def test_상한을_명시_상향하면_진행한다(monkeypatch, isolated_db) -> None:
    _seed_results(isolated_db, 197)
    index = _FakeIndex(
        {
            "announcement": [],
            "result": [f"result_{value}" for value in range(1, 198)]
            + ["result_900001", "result_900002", "result_900003"],
        }
    )

    exit_code = _run_script(monkeypatch, isolated_db, index, ["--execute", "--max-ratio", "0.05"])

    assert exit_code == script.EXIT_OK
    assert index.deleted == [["result_900001", "result_900002", "result_900003"]]


# --------------------------------------------------------------------------- #
# 5. 야간 대조 알림 승격
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_불일치면_notify를_한번_부른다(monkeypatch) -> None:
    notify = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify", notify)
    mismatch = {
        "status": "mismatch",
        "announcements": {"db": 4_000_001, "meili": 3_999_001, "diff": -1000},
        "results": {"db": 2_000_000, "meili": 2_000_500, "diff": 500},
    }

    await scheduled_tasks._notify_search_index_parity(mismatch)

    notify.assert_awaited_once()
    title = notify.await_args.args[0]
    lines = notify.await_args.args[1]
    assert notify.await_args.kwargs["level"] == "warning"
    assert "불일치" in title
    body = "\n".join(lines)
    assert "4000001" in body
    assert "3999001" in body
    assert "-1000" in body
    assert "2000000" in body
    assert "2000500" in body
    assert "scripts/sync_search_index.py" in body
    assert "scripts/sync_search_index_deletions.py" in body


@pytest.mark.asyncio
async def test_대조_불가면_notify를_한번_부른다(monkeypatch) -> None:
    notify = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify", notify)

    await scheduled_tasks._notify_search_index_parity(
        {
            "status": "unavailable",
            "announcements": {"db": None, "meili": None, "diff": None},
            "results": {"db": None, "meili": None, "diff": None},
        }
    )

    notify.assert_awaited_once()
    assert notify.await_args.kwargs["level"] == "warning"
    assert "대조 불가" in notify.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ok", "skipped", "failed"])
async def test_정상이거나_점검밖이면_notify를_부르지_않는다(monkeypatch, status: str) -> None:
    notify = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify", notify)

    await scheduled_tasks._notify_search_index_parity(
        {
            "status": status,
            "announcements": {"db": 10, "meili": 10, "diff": 0},
            "results": {"db": 20, "meili": 20, "diff": 0},
        }
    )

    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_알림_실패가_야간결과를_바꾸지_않는다(monkeypatch) -> None:
    notify = AsyncMock(side_effect=RuntimeError("웹훅 장애 모의"))
    monkeypatch.setattr(scheduled_tasks, "notify", notify)

    await scheduled_tasks._notify_search_index_parity({"status": "mismatch"})

    notify.assert_awaited_once()


def test_자동_삭제_경로가_앱과_스케줄에_없다() -> None:
    """삭제는 수동 스크립트 전용이다. 앱·스케줄 코드에서 호출하지 않는다."""
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (project_root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "delete_documents(" in text or "delete-batch" in text:
            hits.append(str(path.relative_to(project_root)))

    assert hits == ["src/app/services/search_index.py"]
