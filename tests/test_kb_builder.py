"""
tests/test_kb_builder.py

rebuild_knowledge_base 청크 스트리밍 단위 및 회귀 테스트.
실물 Chroma/Ollama 없이 대역(Mock/Fake)으로만 검증합니다.
"""

from __future__ import annotations

import tracemalloc
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.kb_builder import (
    CHUNK_SIZE,
    COLLECTION_NAME,
    DOC_FORMAT_VERSION,
    _document_hash,
    rebuild_knowledge_base,
)


class FakeBidAnnouncement:
    """테스트용 공고 대역."""

    def __init__(self, id_val: int, title: str = "공고"):
        self.id = id_val
        self.bid_ntce_no = f"NTCE_{id_val:06d}"
        self.bid_ntce_ord = "00"
        self.bid_ntce_nm = f"{title}_{id_val}"
        self.category = "용역"
        self.order_agency_nm = "발주처"
        self.dminstt_nm = "수요기관"
        self.bid_ntce_dt = datetime(2026, 1, 1)
        self.openg_dt = datetime(2026, 1, 10)
        self.asign_bdgt_amt = 100_000_000
        self.presmpt_prce = 90_000_000
        self.raw_data: dict[str, Any] = {}


class FakeBidResult:
    """테스트용 낙찰 대역."""

    def __init__(self, id_val: int):
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


class FakeChromaCollection:
    """Chroma 컬렉션 대역."""

    def __init__(
        self, initial_docs: dict[str, str] | None = None, store_documents: bool = False
    ) -> None:
        self.store_documents = store_documents
        self._docs: dict[str, dict[str, Any]] = {}
        self.upsert_batch_sizes: list[int] = []
        self.upsert_batches: list[list[str]] = []
        self.delete_calls: list[list[str]] = []
        if initial_docs:
            for doc_id, doc_hash in initial_docs.items():
                self._docs[doc_id] = {
                    "doc_hash": doc_hash,
                    "fmt": DOC_FORMAT_VERSION,
                }

    def count(self) -> int:
        return len(self._docs)

    def get(
        self,
        include: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
    ) -> dict[str, Any]:
        all_ids = list(self._docs.keys())
        sliced_ids = all_ids[offset : offset + limit]
        metadatas = [
            {
                "type": "bid_info",
                "id": i,
                "doc_hash": self._docs[i]["doc_hash"],
                "fmt": self._docs[i]["fmt"],
            }
            for i in sliced_ids
        ]
        return {"ids": sliced_ids, "metadatas": metadatas}

    def upsert(
        self,
        documents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
    ) -> None:
        self.upsert_batch_sizes.append(len(documents))
        if self.store_documents:
            self.upsert_batches.append(list(documents))
        for doc_id, _doc, meta in zip(ids, documents, metadatas, strict=True):
            self._docs[doc_id] = {
                "doc_hash": meta.get("doc_hash"),
                "fmt": meta.get("fmt", DOC_FORMAT_VERSION),
            }

    def delete(self, ids: list[str]) -> None:
        self.delete_calls.append(list(ids))
        for doc_id in ids:
            self._docs.pop(doc_id, None)


def _setup_mocks(
    announcements: list[FakeBidAnnouncement],
    results: list[FakeBidResult] | None = None,
    initial_collection_docs: dict[str, str] | None = None,
    store_documents: bool = False,
):
    fake_collection = FakeChromaCollection(initial_collection_docs, store_documents=store_documents)
    mock_chroma_client = MagicMock()
    mock_chroma_client.delete_collection = MagicMock()

    mock_db = MagicMock()
    # BidResult 쿼리 반환 대역
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = results or []
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_execute.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_execute

    patch_client = patch("chromadb.PersistentClient", return_value=mock_chroma_client)
    patch_coll = patch("src.app.services.kb_builder.get_collection", return_value=fake_collection)
    patch_ann = patch(
        "src.app.services.kb_builder._resolve_announcements",
        return_value=(announcements, "announcements_with_results"),
    )
    return fake_collection, mock_chroma_client, mock_db, patch_client, patch_coll, patch_ann


def test_chunk_size_constant_and_injection() -> None:
    """CHUNK_SIZE 상수가 노출되고 rebuild_knowledge_base 인자로 주입 가능한지 검증."""
    assert isinstance(CHUNK_SIZE, int)
    assert CHUNK_SIZE > 0
    assert CHUNK_SIZE == 1_000

    mock_db = MagicMock()
    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        rebuild_knowledge_base(mock_db, chunk_size=0)

    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        rebuild_knowledge_base(mock_db, chunk_size=-5)


def test_chunk_streaming_batches() -> None:
    """전체 문서를 한 번에 upsert하지 않고 chunk_size 단위로 나누어 _flush함을 검증."""
    announcements = [FakeBidAnnouncement(i) for i in range(25)]
    fake_coll, _mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(
        announcements, initial_collection_docs={}, store_documents=True
    )

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, chunk_size=10, full=True)

    assert result["status"] == "success"
    assert result["metrics"]["source_bid_count"] == 25
    assert result["metrics"]["embedded_count"] == 25
    assert result["metrics"]["index_mode"] == "full"

    # chunk_size=10 이므로 25건은 [10, 10, 5] 세 배치로 나뉘어 upsert되어야 함
    assert len(fake_coll.upsert_batches) == 3
    assert len(fake_coll.upsert_batches[0]) == 10
    assert len(fake_coll.upsert_batches[1]) == 10
    assert len(fake_coll.upsert_batches[2]) == 5


def test_incremental_semantics_unchanged_changed_and_removed() -> None:
    """증분 색인 시 유지/갱신/삭제 판정 의미가 유지됨을 검증."""
    from src.app.services.kb_builder import _build_announcement_document

    ann_0 = FakeBidAnnouncement(0, "공고0")
    ann_1 = FakeBidAnnouncement(1, "공고1-변경후")
    ann_2 = FakeBidAnnouncement(2, "신규공고2")
    announcements = [ann_0, ann_1, ann_2]

    # ann_0 은 기존과 동일한 해시
    hash_0 = _document_hash(_build_announcement_document(cast(Any, ann_0), None))
    # ann_1 은 기존과 다른 해시 (이전 해시 지정)
    hash_1_old = "old_hash_111111111111111111111111111111111111111111111111111111111111"
    # ann_deleted 는 기존에 있었으나 announcements 에는 없음 (삭제 대상)
    # 단 MAX_REMOVAL_RATIO (0.5) 이하를 위해 1건만 삭제
    hash_del = "del_hash_999999999999999999999999999999999999999999999999999999999999"

    initial_docs = {
        "bid_0": hash_0,
        "bid_1": hash_1_old,
        "bid_deleted": hash_del,
    }

    fake_coll, mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(
        announcements, initial_collection_docs=initial_docs
    )

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, chunk_size=2, full=False)

    assert result["status"] == "success"
    metrics = result["metrics"]
    assert metrics["index_mode"] == "incremental"
    assert metrics["source_bid_count"] == 3  # 목표 건수 (bid_0, bid_1, bid_2)
    assert metrics["unchanged_count"] == 1  # bid_0 유지
    assert metrics["embedded_count"] == 2  # bid_1 갱신 + bid_2 신규
    assert metrics["removed_count"] == 1  # bid_deleted 삭제

    # 삭제가 정상 호출되었는지 검증
    assert fake_coll.delete_calls == [["bid_deleted"]]

    # full=False 이므로 delete_collection 은 호출되지 않아야 함
    mock_client.delete_collection.assert_not_called()


def test_incremental_does_not_delete_collection() -> None:
    """full=False 일 때 delete_collection 을 절대 호출하지 않음을 검증."""
    announcements = [FakeBidAnnouncement(1)]
    _fake_coll, mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(announcements)

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, full=False)

    assert result["status"] == "success"
    mock_client.delete_collection.assert_not_called()


def test_full_rebuild_deletes_collection() -> None:
    """full=True 일 때 delete_collection 을 호출하고 모드가 full 인지 검증."""
    announcements = [FakeBidAnnouncement(1)]
    _fake_coll, mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(announcements)

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, full=True)

    assert result["status"] == "success"
    mock_client.delete_collection.assert_called_once_with(COLLECTION_NAME)
    assert result["metrics"]["index_mode"] == "full"


def test_removal_ratio_guard_blocks_excessive_deletion() -> None:
    """삭제 비율이 MAX_REMOVAL_RATIO 를 초과하면 임베딩 전에 차단되는지 검증."""
    # 기존 색인 10건 중 6건이 삭제 대상 (60% > 50%)
    initial_docs = {f"bid_{i}": f"hash_{i}" for i in range(10)}
    announcements = [
        FakeBidAnnouncement(0),
        FakeBidAnnouncement(1),
        FakeBidAnnouncement(2),
        FakeBidAnnouncement(3),
    ]

    fake_coll, _mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(
        announcements, initial_collection_docs=initial_docs
    )

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, full=False)

    assert result["status"] == "failed"
    assert "삭제 대상이 기존 색인의 60.0% 입니다" in result["summary"]
    # 삭제 및 업서트가 전혀 실행되지 않아야 함
    assert len(fake_coll.upsert_batches) == 0
    assert len(fake_coll.delete_calls) == 0


def test_return_shape_and_metrics_integrity() -> None:
    """반환 형식과 metrics 키가 규약과 100% 일치하는지 검증."""
    announcements = [FakeBidAnnouncement(1)]
    _fake_coll, _mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(announcements)

    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, pipeline_run_id="run_123", full=True)

    assert set(result.keys()) == {"status", "summary", "metrics"}
    metrics = result["metrics"]
    expected_keys = {
        "source_bid_count",
        "collection_name",
        "source_mode",
        "max_documents",
        "last_pipeline_run_id",
        "last_embedding_at",
        "index_mode",
        "embedded_count",
        "unchanged_count",
        "removed_count",
    }
    assert set(metrics.keys()) == expected_keys
    assert metrics["collection_name"] == COLLECTION_NAME
    assert metrics["last_pipeline_run_id"] == "run_123"
    assert metrics["source_bid_count"] == 1
    assert metrics["embedded_count"] == 1
    assert metrics["unchanged_count"] == 0
    assert metrics["removed_count"] == 0


def test_delta_mode() -> None:
    """collected_since 인자가 주어진 delta_mode 정상 동작 검증."""
    announcements = [FakeBidAnnouncement(10)]
    fake_coll = FakeChromaCollection()
    mock_chroma_client = MagicMock()
    mock_db = MagicMock()
    mock_execute = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_execute.scalars.return_value = mock_scalars
    mock_execute.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_execute

    since_dt = datetime(2026, 9, 1, 12, 0, 0)
    with (
        patch("chromadb.PersistentClient", return_value=mock_chroma_client),
        patch("src.app.services.kb_builder.get_collection", return_value=fake_coll),
        patch(
            "src.app.services.kb_builder._resolve_delta_announcements",
            return_value=(announcements, "delta_announcements"),
        ) as mock_delta_res,
    ):
        result = rebuild_knowledge_base(mock_db, collected_since=since_dt)

    assert result["status"] == "success"
    assert result["metrics"]["index_mode"] == "delta"
    assert result["metrics"]["embedded_count"] == 1
    mock_delta_res.assert_called_once_with(mock_db, since_dt)


def test_memory_bound_proportional_to_chunk_size() -> None:
    """문서 수를 늘려도 한 번에 메모리에 상주하는 문서 배치가 chunk_size 이하로 제한됨을 단언하는 회귀 테스트.

    문서 수가 10배(200건 -> 2,000건) 증가하더라도
    1. collection.upsert 에 전달되는 문서 배치 크기는 chunk_size 를 초과하지 않으며
    2. 청크 스트리밍으로 인해 문서 생성 중 피크 메모리가 문서 수에 선형 비례하여 폭증하지 않음을 검증합니다.
    """
    chunk_size = 50

    # 1. 200건 실행
    ann_200 = [FakeBidAnnouncement(i) for i in range(200)]
    fake_coll_200, _mock_client_200, mock_db_200, p_c1, p_co1, p_a1 = _setup_mocks(
        ann_200, initial_collection_docs={}
    )

    tracemalloc.start()
    with p_c1, p_co1, p_a1:
        res_200 = rebuild_knowledge_base(mock_db_200, chunk_size=chunk_size, full=True)
    _, peak_200 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_200["status"] == "success"
    assert res_200["metrics"]["embedded_count"] == 200
    # 모든 upsert 배치가 chunk_size 이하인지 단언
    for batch_size in fake_coll_200.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 2. 10배인 2,000건 실행
    ann_2000 = [FakeBidAnnouncement(i) for i in range(2000)]
    fake_coll_2000, _mock_client_2000, mock_db_2000, p_c2, p_co2, p_a2 = _setup_mocks(
        ann_2000, initial_collection_docs={}
    )

    tracemalloc.start()
    with p_c2, p_co2, p_a2:
        res_2000 = rebuild_knowledge_base(mock_db_2000, chunk_size=chunk_size, full=True)
    _, peak_2000 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_2000["status"] == "success"
    assert res_2000["metrics"]["embedded_count"] == 2000
    # 모든 upsert 배치가 chunk_size 이하인지 단언
    for batch_size in fake_coll_2000.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 3. 문서 수가 10배 늘어도 청크 스트리밍 덕분에 피크 메모리는 문서 수에 비례(10배)하여 증가하지 않고
    #    청크 크기(50건) 수준의 상한 내로 제한됨을 단언합니다.
    #    (전량 적재 시 10배에 가깝게 증가하지만, 스트리밍 시 배율이 매우 낮게 유지됨)
    growth_ratio = peak_2000 / max(peak_200, 1)
    assert growth_ratio < 6.0, (
        f"피크 메모리가 문서 수 증가에 비례하여 증가했습니다 (비율: {growth_ratio:.2f}x). "
        "청크 단위 해제가 정상 작동하지 않고 있습니다."
    )


def test_fallback_results_when_announcements_empty() -> None:
    """공고가 없을 때 낙찰 단독(results_only)으로 폴백하여 청크 스트리밍되는지 검증."""
    fake_coll = FakeChromaCollection()
    mock_chroma_client = MagicMock()
    mock_db = MagicMock()

    # announcements 는 빈 리스트, fallback_results 는 5건
    fallback_results = [FakeBidResult(i) for i in range(5)]
    mock_scalars = MagicMock()
    # 첫 execute: BidResult 쿼리 (announcements 비어있음 -> execute 안 불림)
    # 두 번째 execute: fallback_results
    mock_scalars.all.return_value = fallback_results
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_execute.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_execute

    with (
        patch("chromadb.PersistentClient", return_value=mock_chroma_client),
        patch("src.app.services.kb_builder.get_collection", return_value=fake_coll),
        patch(
            "src.app.services.kb_builder._resolve_announcements",
            return_value=([], "no_announcements"),
        ),
    ):
        result = rebuild_knowledge_base(mock_db, chunk_size=2, full=True)

    assert result["status"] == "success"
    assert result["metrics"]["source_mode"] == "results_only"
    assert result["metrics"]["source_bid_count"] == 5
    assert result["metrics"]["embedded_count"] == 5


def test_empty_dataset_raises_runtime_error() -> None:
    """공고도 없고 낙찰 결과도 없을 때 실패 처리 검증."""
    fake_coll = FakeChromaCollection()
    mock_chroma_client = MagicMock()
    mock_db = MagicMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_execute.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_execute

    with (
        patch("chromadb.PersistentClient", return_value=mock_chroma_client),
        patch("src.app.services.kb_builder.get_collection", return_value=fake_coll),
        patch(
            "src.app.services.kb_builder._resolve_announcements",
            return_value=([], "no_announcements"),
        ),
    ):
        result = rebuild_knowledge_base(mock_db)

    assert result["status"] == "failed"
    assert "인덱싱할 공고/낙찰 데이터가 없습니다" in result["summary"]
