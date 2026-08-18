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


def test_delta_run_indexes_only_recently_collected_announcements(isolated_db, chroma_path):
    old = _add_announcement(isolated_db, notice_no="20260000", name="기존 공고")
    old.collected_at = utcnow() - timedelta(days=2)
    isolated_db.commit()
    kb_builder.rebuild_knowledge_base(isolated_db)

    _add_announcement(isolated_db, notice_no="20260001", name="새 공고")
    outcome = kb_builder.rebuild_knowledge_base(
        isolated_db, collected_since=utcnow() - timedelta(hours=1)
    )

    assert outcome["status"] == "success"
    assert outcome["metrics"]["index_mode"] == "delta"
    assert outcome["metrics"]["embedded_count"] == 1
    assert outcome["metrics"]["source_bid_count"] == 2


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


def test_low_document_limit_cannot_wipe_the_collection(isolated_db, chroma_path, monkeypatch):
    """상한이 낮아도 기존 KB 가 지워지면 안 됩니다.

    `_step_rag` 는 `rebuild_knowledge_base(db)` 를 인자 없이 부르므로 기본
    상한이 그대로 적용됩니다. 2026-08-07 이전 기본값 10 이었다면 50만 건 KB 가
    야간 재색인 한 번에 10건으로 붕괴합니다.
    """
    for index in range(10):
        _add_announcement(isolated_db, notice_no=f"2026{index:06d}", name=f"공고 {index}")
    kb_builder.rebuild_knowledge_base(isolated_db)
    assert _collection(chroma_path).count() == 10

    monkeypatch.setenv("KB_MAX_DOCUMENTS", "2")
    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["status"] == "failed"
    assert _collection(chroma_path).count() == 10


def test_default_document_limit_matches_operating_scale():
    """기본 상한이 운영 KB 규모(약 50만 건)와 어긋나면 안 됩니다."""
    assert kb_builder.DEFAULT_MAX_DOCUMENTS >= 500_000


def test_existing_index_metadata_is_loaded_in_pages(monkeypatch):
    """대규모 KB 메타데이터를 단일 Chroma 응답으로 읽으면 워커가 OOM 납니다."""

    class _Collection:
        def __init__(self):
            self.rows = [
                (f"bid_{index}", {"doc_hash": f"hash_{index}", "fmt": 1}) for index in range(5)
            ]
            self.calls: list[tuple[int, int]] = []

        def count(self):
            return len(self.rows)

        def get(self, *, include, limit, offset):
            assert include == ["metadatas"]
            self.calls.append((limit, offset))
            rows = self.rows[offset : offset + limit]
            return {"ids": [row[0] for row in rows], "metadatas": [row[1] for row in rows]}

    collection = _Collection()
    monkeypatch.setattr(kb_builder, "INDEX_LOOKUP_BATCH_SIZE", 2)

    hashes, incremental = kb_builder._load_existing_index(collection)

    assert incremental is True
    assert hashes == {f"bid_{index}": f"hash_{index}" for index in range(5)}
    assert collection.calls == [(2, 0), (2, 2), (2, 4)]


def test_existing_index_count_failure_retries_without_falling_back(monkeypatch):
    """일시적 count 실패는 전량 재구축이 아니라 같은 조회를 재시도합니다."""

    class _Collection:
        def __init__(self):
            self.count_calls = 0

        def count(self):
            self.count_calls += 1
            if self.count_calls == 1:
                raise RuntimeError("일시적 count 실패")
            return 1

        def get(self, *, include, limit, offset):
            return {
                "ids": ["bid_1"],
                "metadatas": [{"doc_hash": "hash_1", "fmt": 1}],
            }

    collection = _Collection()
    monkeypatch.setattr(kb_builder, "INDEX_LOOKUP_RETRY_DELAY_SECONDS", 0)

    hashes, incremental = kb_builder._load_existing_index(collection)

    assert incremental is True
    assert hashes == {"bid_1": "hash_1"}
    assert collection.count_calls == 2


def test_existing_index_page_failure_retries_without_falling_back(monkeypatch):
    """일시적 페이지 실패도 비교 기준을 버리지 않고 재시도합니다."""

    class _Collection:
        def __init__(self):
            self.get_calls = 0

        def count(self):
            return 1

        def get(self, *, include, limit, offset):
            self.get_calls += 1
            if self.get_calls == 1:
                raise RuntimeError("일시적 get 실패")
            return {
                "ids": ["bid_1"],
                "metadatas": [{"doc_hash": "hash_1", "fmt": 1}],
            }

    collection = _Collection()
    monkeypatch.setattr(kb_builder, "INDEX_LOOKUP_RETRY_DELAY_SECONDS", 0)

    hashes, incremental = kb_builder._load_existing_index(collection)

    assert incremental is True
    assert hashes == {"bid_1": "hash_1"}
    assert collection.get_calls == 2


def test_repeated_existing_index_count_failure_stops_after_retry(monkeypatch):
    """계속되는 운영 오류는 전량 모드가 아니라 명시적 실패가 됩니다."""

    class _Collection:
        def __init__(self):
            self.count_calls = 0

        def count(self):
            self.count_calls += 1
            raise RuntimeError("지속적인 count 실패")

    collection = _Collection()
    monkeypatch.setattr(kb_builder, "INDEX_LOOKUP_RETRY_DELAY_SECONDS", 0)

    with pytest.raises(RuntimeError, match="기존 색인을 보존한 채 중단"):
        kb_builder._load_existing_index(collection)

    assert collection.count_calls == 2


def test_repeated_existing_index_failure_preserves_collection(
    isolated_db, chroma_path, monkeypatch
):
    """조회가 계속 실패하면 전량 임베딩하지 않고 기존 KB를 그대로 둡니다."""
    _add_announcement(isolated_db, notice_no="20260000", name="기존 공고")
    kb_builder.rebuild_knowledge_base(isolated_db)
    collection = _collection(chroma_path)
    original_ids = set(collection.get()["ids"])

    _add_announcement(isolated_db, notice_no="20260001", name="새 공고")

    def fail_existing_index(_collection):
        raise RuntimeError("기존 색인 문서 수 조회에 2회 실패했습니다.")

    monkeypatch.setattr(kb_builder, "_load_existing_index", fail_existing_index)
    outcome = kb_builder.rebuild_knowledge_base(isolated_db)

    assert outcome["status"] == "failed"
    assert "2회 실패" in outcome["summary"]
    assert set(collection.get()["ids"]) == original_ids


def test_sync_rejects_mass_removal(monkeypatch):
    existing = {f"bid_{index}": f"h{index}" for index in range(100)}
    ids = ["bid_0", "bid_1"]
    metadatas = [{"doc_hash": "h0"}, {"doc_hash": "h1"}]

    class _Collection:
        def __init__(self):
            self.deleted = []

        def delete(self, ids):
            self.deleted.extend(ids)

    collection = _Collection()
    with pytest.raises(RuntimeError, match="상한"):
        kb_builder._sync(collection, ["a", "b"], metadatas, ids, existing, True)
    assert collection.deleted == []


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
