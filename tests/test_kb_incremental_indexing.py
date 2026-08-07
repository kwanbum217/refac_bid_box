"""지식베이스 증분 색인 회귀 테스트.

여기서 고정하는 것은 세 가지입니다.

1. 변하지 않은 문서를 다시 임베딩하지 않는가 (증분의 목적)
2. 어떤 경우에도 컬렉션 내용이 목표 상태와 어긋나지 않는가 (정확성이 우선)
3. 재구축 도중 기존 KB 가 비지 않는가 (챗봇이 근거 없이 답하는 것을 막습니다)
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import kb_builder


@pytest.fixture
def chroma_path(tmp_path, monkeypatch):
    path = tmp_path / "chroma"
    monkeypatch.setattr(kb_builder.settings, "CHROMA_DB_PATH", str(path))
    monkeypatch.setenv("KB_MAX_DOCUMENTS", "50")
    return path


def _add_announcement(db, *, notice_no: str, name: str, institution: str = "테스트기관"):
    row = BidAnnouncement(
        bid_ntce_no=notice_no,
        bid_ntce_ord="00",
        bid_ntce_nm=name,
        dminstt_nm=institution,
        category="Servc",
        bid_ntce_dt=utcnow() - timedelta(days=1),
        collected_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _collection(path):
    import chromadb

    client = chromadb.PersistentClient(path=str(path))
    return client.get_collection(kb_builder.COLLECTION_NAME)


def test_first_run_indexes_everything(isolated_db, chroma_path):
    for index in range(3):
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")

    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["status"] == "success"
    assert outcome["metrics"]["source_bid_count"] == 3
    assert outcome["metrics"]["embedded_count"] == 3
    assert _collection(chroma_path).count() == 3


def test_unchanged_documents_are_not_reembedded(isolated_db, chroma_path):
    """증분의 목적입니다. 변경이 없으면 임베딩이 0건이어야 합니다."""
    for index in range(3):
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
    kb_builder.rebuild_knowledge_base(isolated_db)

    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["metrics"]["index_mode"] == "incremental"
    assert outcome["metrics"]["embedded_count"] == 0
    assert outcome["metrics"]["unchanged_count"] == 3
    # 건수는 KB 규모를 뜻하므로 변경분이 아니라 전체를 보고해야 합니다.
    assert outcome["metrics"]["source_bid_count"] == 3


def test_only_changed_document_is_reembedded(isolated_db, chroma_path):
    rows = [
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
        for index in range(3)
    ]
    kb_builder.rebuild_knowledge_base(isolated_db)

    rows[1].dminstt_nm = "변경된기관"
    isolated_db.commit()

    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["metrics"]["embedded_count"] == 1
    assert outcome["metrics"]["unchanged_count"] == 2

    stored = _collection(chroma_path).get(ids=[f"bid_{rows[1].id}"], include=["documents"])
    assert "변경된기관" in stored["documents"][0]


def test_removed_document_is_deleted_from_collection(isolated_db, chroma_path):
    rows = [
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
        for index in range(3)
    ]
    kb_builder.rebuild_knowledge_base(isolated_db)

    removed_id = f"bid_{rows[2].id}"
    isolated_db.delete(rows[2])
    isolated_db.commit()

    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["metrics"]["removed_count"] == 1
    collection = _collection(chroma_path)
    assert collection.count() == 2
    assert removed_id not in collection.get()["ids"]


def test_format_version_bump_forces_full_reindex(isolated_db, chroma_path, monkeypatch):
    """본문 포맷을 바꾸고 버전을 올리면 낡은 문서가 남으면 안 됩니다."""
    for index in range(2):
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
    kb_builder.rebuild_knowledge_base(isolated_db)

    monkeypatch.setattr(kb_builder, "DOC_FORMAT_VERSION", kb_builder.DOC_FORMAT_VERSION + 1)
    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["metrics"]["index_mode"] == "full"
    assert outcome["metrics"]["embedded_count"] == 2


def test_legacy_documents_without_hash_fall_back_to_full(isolated_db, chroma_path):
    """해시 없는 기존 색인은 비교 기준이 없으므로 전량으로 가야 합니다."""
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(kb_builder.COLLECTION_NAME)
    collection.add(documents=["옛 문서"], ids=["bid_legacy"], metadatas=[{"type": "bid_info"}])

    _add_announcement(isolated_db, notice_no="20260000", name="새 공고")
    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["metrics"]["index_mode"] == "full"


def test_full_flag_rebuilds_from_scratch(isolated_db, chroma_path):
    rows = [
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
        for index in range(2)
    ]
    kb_builder.rebuild_knowledge_base(isolated_db)

    outcome = kb_builder.rebuild_knowledge_base(isolated_db, full=True)

    assert outcome["metrics"]["index_mode"] == "full"
    assert outcome["metrics"]["embedded_count"] == 2
    assert _collection(chroma_path).count() == len(rows)


def test_incremental_run_never_empties_collection(isolated_db, chroma_path, monkeypatch):
    """색인이 실패해도 기존 KB 는 살아 있어야 합니다.

    예전 구조는 delete_collection 을 먼저 했기 때문에, 실패하면 KB 가 빈 채로
    남고 챗봇이 근거 없이 답했습니다.
    """
    _add_announcement(isolated_db, notice_no="20260000", name="공고 0")
    kb_builder.rebuild_knowledge_base(isolated_db)
    assert _collection(chroma_path).count() == 1

    _add_announcement(isolated_db, notice_no="20260001", name="공고 1")

    def boom(*_args, **_kwargs):
        raise RuntimeError("임베딩 실패")

    monkeypatch.setattr(kb_builder, "_flush", boom)
    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["status"] == "failed"
    assert _collection(chroma_path).count() == 1


def test_document_hash_detects_content_change():
    """DB 시각이 아니라 본문으로 판정하는지 확인합니다."""
    first = kb_builder._document_hash("[공고명] A\n")
    second = kb_builder._document_hash("[공고명] B\n")
    assert first != second
    assert first == kb_builder._document_hash("[공고명] A\n")


def test_diff_index_classifies_correctly():
    existing = {"a": "h1", "b": "h2", "gone": "h3"}
    ids = ["a", "b", "new"]
    metadatas = [{"doc_hash": "h1"}, {"doc_hash": "changed"}, {"doc_hash": "h4"}]

    changed, removed = kb_builder._diff_index(existing, ids, metadatas)

    assert changed == [1, 2]
    assert removed == ["gone"]


def test_diff_index_scales_to_large_collections():
    """삭제 대상 계산이 기존 문서 수에 선형인지 고정합니다.

    2026-08-07 에 `set(ids)` 가 컴프리헨션 안에 있어 기존 문서마다 대상 집합을
    재구축했고, 10만 x 50만 규모에서 색인이 진행되지 않았습니다. 아래 규모는
    수정 전이면 분 단위로 걸리고 수정 후에는 1초 안에 끝납니다.
    """
    ids = [f"bid_{index}" for index in range(100_000)]
    metadatas = [{"doc_hash": f"h{index}"} for index in range(100_000)]
    existing = {f"bid_{index}": f"h{index}" for index in range(5_000)}

    started = time.perf_counter()
    changed, removed = kb_builder._diff_index(existing, ids, metadatas)
    elapsed = time.perf_counter() - started

    assert changed == list(range(5_000, 100_000))
    assert removed == []
    assert elapsed < 5.0
