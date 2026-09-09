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
    2. items 리스트 생성을 포함한 측정 구간에서 피크 메모리가 문서 수에 선형 비례하여 폭증하지 않음을 엄격히 검증합니다.
    """
    chunk_size = 50

    # 모듈 임포트 오버헤드를 배제하기 위한 사전 워밍업
    ann_warm = [FakeBidAnnouncement(0)]
    _coll_w, _c_w, _db_w, pw_c, pw_co, pw_a = _setup_mocks(ann_warm, initial_collection_docs={})
    with pw_c, pw_co, pw_a:
        rebuild_knowledge_base(_db_w, chunk_size=chunk_size, full=True)

    # 1. 200건 실행 (items 생성을 tracemalloc 측정 구간에 포함)
    tracemalloc.start()
    ann_200 = [FakeBidAnnouncement(i) for i in range(200)]
    fake_coll_200, _mock_client_200, mock_db_200, p_c1, p_co1, p_a1 = _setup_mocks(
        ann_200, initial_collection_docs={}
    )
    fake_coll_200.upsert = lambda documents, metadatas, ids: (
        fake_coll_200.upsert_batch_sizes.append(len(documents))
    )
    with p_c1, p_co1, p_a1:
        res_200 = rebuild_knowledge_base(mock_db_200, chunk_size=chunk_size, full=True)
    _, peak_200 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_200["status"] == "success"
    assert res_200["metrics"]["embedded_count"] == 200
    for batch_size in fake_coll_200.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 2. 10배인 2,000건 실행 (items 생성을 tracemalloc 측정 구간에 포함)
    tracemalloc.start()
    ann_2000 = [FakeBidAnnouncement(i) for i in range(2000)]
    fake_coll_2000, _mock_client_2000, mock_db_2000, p_c2, p_co2, p_a2 = _setup_mocks(
        ann_2000, initial_collection_docs={}
    )
    fake_coll_2000.upsert = lambda documents, metadatas, ids: (
        fake_coll_2000.upsert_batch_sizes.append(len(documents))
    )
    with p_c2, p_co2, p_a2:
        res_2000 = rebuild_knowledge_base(mock_db_2000, chunk_size=chunk_size, full=True)
    _, peak_2000 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_2000["status"] == "success"
    assert res_2000["metrics"]["embedded_count"] == 2000
    for batch_size in fake_coll_2000.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 3. 문서 수가 10배 늘어도 items 생성을 포함한 피크 메모리가 5.0배 미만으로 엄격히 억제됨을 단언 (6.0배보다 엄격)
    growth_ratio = peak_2000 / max(peak_200, 1)
    assert growth_ratio < 5.0, (
        f"피크 메모리가 문서 수 증가에 비례하여 증가했습니다 (비율: {growth_ratio:.2f}x). "
        "청크 단위 해제가 정상 작동하지 않고 있습니다."
    )


def test_memory_bound_incremental_with_large_existing_hashes() -> None:
    """운영 기본 경로 full=False, incremental=True 에서 수만 건 existing_hashes 가 상주하더라도
    청크 스트리밍과 target_ids 전량 집합 생성 회피로 피크 메모리가 안정적으로 유지됨을 검증.
    """
    chunk_size = 500
    # 수만 건(20,000건) 기존 색인 해시 주입
    initial_docs = {f"bid_{i}": f"hash_{i:064x}" for i in range(20_000)}

    # 사전 워밍업
    ann_warm = [FakeBidAnnouncement(0)]
    _cw, _, _dbw, pw_c, pw_co, pw_a = _setup_mocks(
        ann_warm, initial_collection_docs={"bid_0": "hash_0"}
    )
    with pw_c, pw_co, pw_a:
        rebuild_knowledge_base(_dbw, chunk_size=chunk_size, full=False)

    # 19,000건 공고 (1,000건 삭제 -> removal_ratio = 5% <= 50%)
    tracemalloc.start()
    announcements = [FakeBidAnnouncement(i) for i in range(19_000)]
    fake_coll, mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(
        announcements, initial_collection_docs=initial_docs
    )
    fake_coll.upsert = lambda documents, metadatas, ids: fake_coll.upsert_batch_sizes.append(
        len(documents)
    )
    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, chunk_size=chunk_size, full=False)
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result["status"] == "success"
    metrics = result["metrics"]
    assert metrics["index_mode"] == "incremental"
    assert metrics["source_bid_count"] == 19_000
    assert metrics["removed_count"] == 1_000
    # full=False 이므로 delete_collection 은 절대 호출되지 않아야 함
    mock_client.delete_collection.assert_not_called()
    for batch_size in fake_coll.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 수만 건 existing_hashes 와 items 적재를 포함해도 피크 메모리가 50MB 미만으로 제어됨을 단언
    assert peak_memory < 50 * 1024 * 1024, (
        f"피크 메모리가 너무 높습니다: {peak_memory / 1024 / 1024:.2f} MB"
    )


def test_full_path_consistency_and_fallback_values() -> None:
    """비증분 full 경로에서 len(items)와 embedded 가 일치하고 source_bid_count 와 fallback 분기가 일관됨을 검증."""
    # 1. 일반 full 경로: len(items) == embedded == source_bid_count
    announcements = [FakeBidAnnouncement(i) for i in range(15)]
    fake_coll, _mock_client, mock_db, p_client, p_coll, p_ann = _setup_mocks(
        announcements, initial_collection_docs={}
    )
    with p_client, p_coll, p_ann:
        result = rebuild_knowledge_base(mock_db, chunk_size=5, full=True)

    assert result["status"] == "success"
    assert result["metrics"]["index_mode"] == "full"
    assert result["metrics"]["embedded_count"] == len(announcements)
    assert result["metrics"]["source_bid_count"] == len(announcements)
    assert result["metrics"]["unchanged_count"] == 0
    assert result["metrics"]["removed_count"] == 0

    # 2. 공고가 없을 때 fallback 경로: source_bid_count == fallback_results 길이와 일치
    mock_chroma_client = MagicMock()
    fallback_results = [FakeBidResult(i) for i in range(7)]
    mock_scalars = MagicMock()
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
        fb_result = rebuild_knowledge_base(mock_db, chunk_size=3, full=True)

    assert fb_result["status"] == "success"
    assert fb_result["metrics"]["source_mode"] == "results_only"
    assert fb_result["metrics"]["embedded_count"] == len(fallback_results)
    assert fb_result["metrics"]["source_bid_count"] == len(fallback_results)


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


class StreamingFakeDb:
    """페이지 단위 조회를 시뮬레이션하는 DB 세션 대역."""

    def __init__(self, notice_count: int, collected_count: int = 0) -> None:
        self.notice_count = notice_count
        self.collected_count = collected_count

    def scalar(self, stmt: Any) -> Any:
        sql_text = str(stmt)
        if "WHERE bid_announcements.collected_at" in sql_text:
            return self.collected_count
        return self.notice_count

    def execute(self, stmt: Any) -> Any:
        mock_result = MagicMock()
        sql_text = str(stmt)
        if "bid_announcements" in sql_text:
            offset = getattr(stmt, "_offset", 0) or 0
            limit = getattr(stmt, "_limit", None)
            total = (
                self.collected_count
                if "WHERE bid_announcements.collected_at" in sql_text
                else self.notice_count
            )
            end = total if limit is None else min(total, offset + limit)
            page = [FakeBidAnnouncement(i) for i in range(offset, end)]
            mock_result.scalars.return_value.all.return_value = page
        elif "bid_results" in sql_text:
            mock_result.scalars.return_value.all.return_value = []
        elif "knowledge_base_status" in sql_text:
            mock_result.scalar_one_or_none.return_value = None
        else:
            mock_result.scalars.return_value.all.return_value = []
            mock_result.scalar_one_or_none.return_value = None
        return mock_result

    def commit(self) -> None:
        pass

    def add(self, obj: Any) -> None:
        pass


def test_resolve_announcements_fallback_rules_and_paged_sequence() -> None:
    """_resolve_announcements 의 공고일 우선 -> 수집일 폴백 규칙과 PagedQuerySequence 동작 검증."""
    from src.app.services.kb_builder import _resolve_announcements
    from src.app.services.kb_document_builder import PagedQuerySequence

    dt = datetime(2026, 1, 1)

    # 1. 공고일 기준 데이터가 있을 때
    db_notice = StreamingFakeDb(notice_count=15, collected_count=5)
    seq_notice, mode_notice = _resolve_announcements(cast(Any, db_notice), dt)
    assert mode_notice == "announcements_by_notice_date"
    assert isinstance(seq_notice, PagedQuerySequence)
    assert len(seq_notice) == 15
    assert bool(seq_notice) is True
    # 슬라이스 및 단일 인덱스 검증
    slice_items = seq_notice[0:5]
    assert len(slice_items) == 5
    assert slice_items[0].id == 0
    assert seq_notice[3].id == 3

    # 2. 공고일 기준이 0건이고 수집일 기준이 있을 때 폴백
    db_collected = StreamingFakeDb(notice_count=0, collected_count=8)
    seq_collected, mode_collected = _resolve_announcements(cast(Any, db_collected), dt)
    assert mode_collected == "announcements_by_collected_at"
    assert isinstance(seq_collected, PagedQuerySequence)
    assert len(seq_collected) == 8
    assert len(list(seq_collected)) == 8

    # 3. 둘 다 0건일 때
    db_empty = StreamingFakeDb(notice_count=0, collected_count=0)
    seq_empty, mode_empty = _resolve_announcements(cast(Any, db_empty), dt)
    assert mode_empty == "announcements_unavailable"
    assert seq_empty == []


def test_resolve_delta_announcements_paged_sequence() -> None:
    """_resolve_delta_announcements 가 PagedQuerySequence 로 페이지 단위 지연 조회를 수행함을 검증."""
    from src.app.services.kb_builder import _resolve_delta_announcements
    from src.app.services.kb_document_builder import PagedQuerySequence

    mock_db = MagicMock()
    mock_scalars_distinct = MagicMock()
    mock_scalars_distinct.all.return_value = ["NTCE_000001", "NTCE_000002"]
    mock_db.scalars.return_value = mock_scalars_distinct
    mock_db.scalar.return_value = 10

    mock_execute = MagicMock()
    mock_execute.scalars.return_value.all.return_value = [FakeBidAnnouncement(i) for i in range(5)]
    mock_db.execute.return_value = mock_execute

    seq, mode = _resolve_delta_announcements(mock_db, datetime(2026, 9, 1))
    assert mode == "announcements_by_collected_delta"
    assert isinstance(seq, PagedQuerySequence)
    assert len(seq) == 10
    chunk = seq[0:5]
    assert len(chunk) == 5

    # 0건일 때 빈 리스트 반환
    mock_db_empty = MagicMock()
    mock_db_empty.scalars.return_value.all.return_value = []
    mock_db_empty.scalar.return_value = 0
    seq_empty, mode_empty = _resolve_delta_announcements(mock_db_empty, datetime(2026, 9, 1))
    assert mode_empty == "announcements_by_collected_delta"
    assert seq_empty == []


def test_memory_bound_announcements_query_streaming() -> None:
    """_resolve_announcements 조회를 측정 구간에 포함하여, 문서 수가 10배(200건 -> 2,000건)
    증가하더라도 PagedQuerySequence 의 페이지 단위 지연 조회로 인해 피크 메모리가
    문서 수에 비례하여 증가하지 않음을 단언하는 회귀 테스트.
    """
    chunk_size = 50

    # 사전 워밍업
    db_warm = StreamingFakeDb(notice_count=1)
    coll_w = FakeChromaCollection()
    client_w = MagicMock()
    with (
        patch("chromadb.PersistentClient", return_value=client_w),
        patch("src.app.services.kb_builder.get_collection", return_value=coll_w),
    ):
        rebuild_knowledge_base(cast(Any, db_warm), chunk_size=chunk_size, full=True)

    # 1. 200건 실행 (_resolve_announcements DB 조회를 tracemalloc 측정 구간에 포함)
    db_200 = StreamingFakeDb(notice_count=200)
    coll_200 = FakeChromaCollection()
    coll_200.upsert = lambda documents, metadatas, ids: coll_200.upsert_batch_sizes.append(
        len(documents)
    )
    client_200 = MagicMock()

    tracemalloc.start()
    with (
        patch("chromadb.PersistentClient", return_value=client_200),
        patch("src.app.services.kb_builder.get_collection", return_value=coll_200),
    ):
        res_200 = rebuild_knowledge_base(cast(Any, db_200), chunk_size=chunk_size, full=True)
    _, peak_200 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_200["status"] == "success"
    assert res_200["metrics"]["source_mode"] == "announcements_by_notice_date"
    assert res_200["metrics"]["embedded_count"] == 200
    for batch_size in coll_200.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 2. 10배인 2,000건 실행 (_resolve_announcements DB 조회를 tracemalloc 측정 구간에 포함)
    db_2000 = StreamingFakeDb(notice_count=2000)
    coll_2000 = FakeChromaCollection()
    coll_2000.upsert = lambda documents, metadatas, ids: coll_2000.upsert_batch_sizes.append(
        len(documents)
    )
    client_2000 = MagicMock()

    tracemalloc.start()
    with (
        patch("chromadb.PersistentClient", return_value=client_2000),
        patch("src.app.services.kb_builder.get_collection", return_value=coll_2000),
    ):
        res_2000 = rebuild_knowledge_base(cast(Any, db_2000), chunk_size=chunk_size, full=True)
    _, peak_2000 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res_2000["status"] == "success"
    assert res_2000["metrics"]["source_mode"] == "announcements_by_notice_date"
    assert res_2000["metrics"]["embedded_count"] == 2000
    for batch_size in coll_2000.upsert_batch_sizes:
        assert batch_size <= chunk_size

    # 3. announcements 조회를 포함해도 10배 문서 수에서 피크 메모리 증가비율이 5.0배 미만으로 엄격히 억제됨을 단언
    growth_ratio = peak_2000 / max(peak_200, 1)
    assert growth_ratio < 5.0, (
        f"announcements 조회 포함 피크 메모리가 문서 수에 비례하여 증가했습니다 (비율: {growth_ratio:.2f}x). "
        "페이지 단위 지연 조회가 정상 작동하지 않고 있습니다."
    )
