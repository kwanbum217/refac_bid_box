"""Chroma 삭제 요청이 배치 상한(41,666건)을 넘지 않는지 검증합니다."""

from __future__ import annotations

from src.app.services.kb_index_sync import INDEX_LOOKUP_BATCH_SIZE, delete_in_batches

CHROMA_MAX_BATCH = 41_666


class _StrictCollection:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def delete(self, ids: list[str]) -> None:
        if len(ids) > CHROMA_MAX_BATCH:
            raise ValueError(f"Cannot submit more than {CHROMA_MAX_BATCH:,} embeddings at once.")
        self.calls.append(list(ids))


def test_delete_in_batches_splits_large_removal_under_chroma_limit():
    ids = [f"bid_{i}" for i in range(170_001)]
    collection = _StrictCollection()
    delete_in_batches(collection, ids)
    assert [i for call in collection.calls for i in call] == ids
    assert max(len(call) for call in collection.calls) <= INDEX_LOOKUP_BATCH_SIZE < CHROMA_MAX_BATCH


def test_delete_in_batches_skips_empty_list():
    collection = _StrictCollection()
    delete_in_batches(collection, [])
    assert collection.calls == []
