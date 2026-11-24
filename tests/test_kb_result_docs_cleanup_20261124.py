"""tests/test_kb_result_docs_cleanup_20261124.py

공고 원천 색인 성공 뒤 잔존 result_ 문서 정리 동작 회귀 테스트.
실물 Chroma/Ollama/DB 없이 대역(Mock/Fake)으로만 검증합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from src.app.services.kb_builder import (
    DOC_FORMAT_VERSION,
    rebuild_knowledge_base,
)

_TODAY = datetime(2026, 6, 2, 12, 0, 0)


class FakeBidAnnouncement:
    """테스트용 공고 대역."""

    def __init__(self, id_val: int) -> None:
        self.id = id_val
        self.bid_ntce_no = f"NTCE_{id_val:06d}"
        self.bid_ntce_ord = "00"
        self.bid_ntce_nm = f"공고_{id_val}"
        self.category = "용역"
        self.order_agency_nm = "발주처"
        self.dminstt_nm = "수요기관"
        self.bid_ntce_dt = datetime(2026, 1, 1)
        self.openg_dt = datetime(2026, 1, 10)
        self.collected_at = datetime(2026, 1, 1)
        self.asign_bdgt_amt = 100_000_000
        self.presmpt_prce = 90_000_000
        self.raw_data: dict[str, Any] = {}


class FakeBidResult:
    """테스트용 낙찰 대역."""

    def __init__(self, id_val: int) -> None:
        self.bid_ntce_no = f"NTCE_{id_val:06d}"
        self.bid_ntce_ord = "00"
        self.bid_ntce_nm = f"낙찰건명_{id_val}"
        self.order_agency_nm = "발주처"
        self.dminstt_nm = "수요기관"
        self.rl_openg_dt = datetime(2026, 1, 10)
        self.openg_dt = datetime(2026, 1, 10)
        self.category = "용역"
        self.sucsf_corp_nm = "낙찰업체"
        self.bidwinnr_nm = "낙찰업체"
        self.sucsf_amt = 85_000_000
        self.bidwinnr_amt = 85_000_000
        self.sucsf_bid_amt = 85_000_000
        self.sucsf_rate = 88.5
        self.sucsf_bid_rate = 88.5
        self.plnd_prce = 95_000_000
        self.bsis_prce = 95_000_000


def _doc(doc_hash: str, doc_type: str) -> dict[str, Any]:
    return {"doc_hash": doc_hash, "fmt": DOC_FORMAT_VERSION, "type": doc_type}


class FakeChromaCollection:
    """Chroma 컬렉션 대역. where 필터와 include=[] 조회를 지원합니다."""

    def __init__(
        self,
        initial_docs: dict[str, dict[str, Any]] | None = None,
        *,
        fail_upsert: bool = False,
    ) -> None:
        self._docs = dict(initial_docs or {})
        self.fail_upsert = fail_upsert
        self.delete_calls: list[list[str]] = []
        self.where_calls: list[dict[str, Any]] = []

    def count(self) -> int:
        return len(self._docs)

    def get(
        self,
        include: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ids = list(self._docs.keys())
        if where is not None:
            self.where_calls.append(dict(where))
            field, value = next(iter(where.items()))
            ids = [doc_id for doc_id in ids if self._docs[doc_id].get(field) == value]
        sliced_ids = ids[offset : offset + limit]
        if not include:
            return {"ids": sliced_ids}
        return {"ids": sliced_ids, "metadatas": [dict(self._docs[i]) for i in sliced_ids]}

    def upsert(
        self,
        documents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
    ) -> None:
        if self.fail_upsert:
            raise RuntimeError("임베딩 저장 실패")
        for doc_id, meta in zip(ids, metadatas, strict=True):
            self._docs[doc_id] = {
                "doc_hash": meta.get("doc_hash"),
                "fmt": meta.get("fmt", DOC_FORMAT_VERSION),
                "type": meta.get("type", "bid_info"),
            }

    def delete(self, ids: list[str]) -> None:
        self.delete_calls.append(list(ids))
        for doc_id in ids:
            self._docs.pop(doc_id, None)

    def deleted_ids(self) -> set[str]:
        return {doc_id for batch in self.delete_calls for doc_id in batch}


def _mock_db(results: list[FakeBidResult] | None = None) -> MagicMock:
    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = results or []
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_execute.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_execute
    return mock_db


def _run(
    *,
    collection: FakeChromaCollection,
    announcements: list[FakeBidAnnouncement],
    source_mode: str,
    results: list[FakeBidResult] | None = None,
    full: bool = False,
    delete_collection_error: Exception | None = None,
) -> dict[str, Any]:
    mock_client = MagicMock()
    if delete_collection_error is not None:
        mock_client.delete_collection.side_effect = delete_collection_error
    else:
        mock_client.delete_collection.side_effect = lambda name: collection._docs.clear()

    with (
        patch("chromadb.PersistentClient", return_value=mock_client),
        patch("src.app.services.kb_builder.get_collection", return_value=collection),
        patch(
            "src.app.services.kb_builder._resolve_announcements",
            return_value=(announcements, source_mode),
        ),
        patch("src.app.services.kb_builder.utcnow", return_value=_TODAY),
    ):
        return rebuild_knowledge_base(_mock_db(results), full=full)


def test_incremental_cleanup_removes_stale_result_documents() -> None:
    """증분 색인이 공고 원천으로 성공하면 과거 result_ 문서를 지운다."""
    result_doc_id = "result_NTCE_000009_00_0"
    collection = FakeChromaCollection(
        {
            "bid_1": _doc("stale_hash", "bid_info"),
            result_doc_id: _doc("result_hash", "bid_result"),
        }
    )

    result = _run(
        collection=collection,
        announcements=[FakeBidAnnouncement(1)],
        source_mode="announcements_with_results",
    )

    assert result["status"] == "success"
    assert result["metrics"]["index_mode"] == "incremental"
    assert result_doc_id not in collection._docs
    assert result_doc_id in collection.deleted_ids()
    assert collection._docs["bid_1"]["type"] == "bid_info"
    # 정리 건수가 삭제 건수에 더해지고, KB 규모는 실제 문서 수와 일치한다.
    assert result["metrics"]["removed_count"] == 1
    assert result["metrics"]["source_bid_count"] == collection.count() == 1
    assert "삭제 1건" in result["summary"]


def test_results_only_keeps_result_documents() -> None:
    """공고 원천 0건(results_only)이면 결과 문서를 지우지 않는다."""
    result_doc_id = "result_OLD_00_0"
    collection = FakeChromaCollection({result_doc_id: _doc("result_hash", "bid_result")})

    result = _run(
        collection=collection,
        announcements=[],
        source_mode="announcements_unavailable",
        results=[FakeBidResult(i) for i in range(2)],
    )

    assert result["status"] == "success"
    assert result["metrics"]["source_mode"] == "results_only"
    assert result_doc_id in collection._docs
    assert collection.delete_calls == []


def test_index_failure_keeps_result_documents() -> None:
    """색인이 예외로 실패하면 결과 문서를 지우지 않는다."""
    result_doc_id = "result_NTCE_000009_00_0"
    collection = FakeChromaCollection(
        {
            "bid_1": _doc("stale_hash", "bid_info"),
            result_doc_id: _doc("result_hash", "bid_result"),
        },
        fail_upsert=True,
    )

    result = _run(
        collection=collection,
        announcements=[FakeBidAnnouncement(1)],
        source_mode="announcements_with_results",
    )

    assert result["status"] == "failed"
    assert result_doc_id in collection._docs
    assert collection.delete_calls == []


def test_full_rebuild_recreates_collection_without_result_documents() -> None:
    """full 모드는 컬렉션을 새로 만들어 result_ 문서가 남지 않는다."""
    result_doc_id = "result_OLD_00_0"
    collection = FakeChromaCollection({result_doc_id: _doc("result_hash", "bid_result")})

    result = _run(
        collection=collection,
        announcements=[FakeBidAnnouncement(1)],
        source_mode="announcements_with_results",
        full=True,
    )

    assert result["status"] == "success"
    assert result["metrics"]["index_mode"] == "full"
    assert result_doc_id not in collection._docs
    # 컬렉션 자체를 새로 만들었으므로 개별 삭제 호출은 없다.
    assert collection.delete_calls == []
    assert collection.where_calls == []


def test_full_rebuild_cleans_result_documents_when_delete_fails() -> None:
    """컬렉션 삭제가 실패해 기존 문서가 남으면 full 모드에서도 결과 문서를 정리한다."""
    result_doc_id = "result_OLD_00_0"
    collection = FakeChromaCollection(
        {
            result_doc_id: _doc("result_hash", "bid_result"),
        }
    )

    result = _run(
        collection=collection,
        announcements=[FakeBidAnnouncement(1)],
        source_mode="announcements_with_results",
        full=True,
        delete_collection_error=RuntimeError("삭제 실패"),
    )

    assert result["status"] == "success"
    assert result["metrics"]["index_mode"] == "full"
    assert collection.where_calls == [{"type": "bid_result"}]
    assert result_doc_id not in collection._docs
    assert result["metrics"]["removed_count"] == 1
    assert result["metrics"]["source_bid_count"] == collection.count() == 1
    assert "잔존 결과 문서 1건 정리" in result["summary"]
