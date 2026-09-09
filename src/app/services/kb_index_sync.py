"""src/app/services/kb_index_sync.py - 지식베이스 색인 동기화 및 해시 차분 모듈.

기존 색인의 상태를 읽어 목표 문서 상태와 동기화(upsert/delete)하는 책임을 담당합니다.
문서 해시 비교를 통한 증분 색인, 삭제 상한(G1 데이터 무손실) 검증, 배치 플러시를 수행합니다.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

INDEX_BATCH_SIZE = 100

# 50만 건 메타데이터를 한 응답으로 읽으면 Chroma 응답 객체가 워커 메모리를
# 소진할 수 있습니다. 해시 비교용 조회도 페이지 단위로 제한합니다.
INDEX_LOOKUP_BATCH_SIZE = 10_000

INDEX_LOOKUP_MAX_ATTEMPTS = 2
INDEX_LOOKUP_RETRY_DELAY_SECONDS = 0.25

# 한 번의 증분 색인이 지울 수 있는 비율의 상한입니다. 이를 넘으면 색인을 중단하고
# 실패로 보고합니다. 상한값 설정 실수나 DB 일시 장애로 KB 가 통째로 사라지는 경로를
# 막습니다. 데이터 무손실(G1)은 벡터DB 에도 적용됩니다.
MAX_REMOVAL_RATIO = 0.5

# 문서 본문 포맷 버전.
#
# `_build_announcement_document` 나 `_build_result_document` 의 출력 형식을
# 바꾸면 반드시 이 값을 올리십시오. 증분 색인은 본문 해시로 변경을 판정하므로,
# 포맷을 바꾸고 버전을 그대로 두면 낡은 형식의 문서가 조용히 남습니다.
DOC_FORMAT_VERSION = 1

# 청크 스트리밍 단위 크기 (메모리 상주 방지)
CHUNK_SIZE = 1_000


class KbSyncStats(TypedDict):
    embedded: int
    unchanged: int
    removed: int
    mode: str


__all__ = (
    "CHUNK_SIZE",
    "DOC_FORMAT_VERSION",
    "INDEX_BATCH_SIZE",
    "INDEX_LOOKUP_BATCH_SIZE",
    "INDEX_LOOKUP_MAX_ATTEMPTS",
    "INDEX_LOOKUP_RETRY_DELAY_SECONDS",
    "MAX_REMOVAL_RATIO",
    "KbSyncStats",
    "_diff_index",
    "_document_hash",
    "_flush",
    "_load_existing_index",
    "_read_existing_index_value",
    "_sync",
    "_sync_stream",
)


def _current_doc_format_version() -> int:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "DOC_FORMAT_VERSION", None)
        if builder_val is not None and builder_val != 1:
            return builder_val
    return DOC_FORMAT_VERSION


def _current_lookup_batch_size() -> int:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "INDEX_LOOKUP_BATCH_SIZE", None)
        if builder_val is not None and builder_val != 10_000:
            return builder_val
    return INDEX_LOOKUP_BATCH_SIZE


def _current_retry_delay_seconds() -> float:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "INDEX_LOOKUP_RETRY_DELAY_SECONDS", None)
        if builder_val is not None and builder_val != 0.25:
            return builder_val
    return INDEX_LOOKUP_RETRY_DELAY_SECONDS


def _current_max_attempts() -> int:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "INDEX_LOOKUP_MAX_ATTEMPTS", None)
        if builder_val is not None and builder_val != 2:
            return builder_val
    return INDEX_LOOKUP_MAX_ATTEMPTS


def _current_max_removal_ratio() -> float:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "MAX_REMOVAL_RATIO", None)
        if builder_val is not None and builder_val != 0.5:
            return builder_val
    return MAX_REMOVAL_RATIO


def _current_flush() -> Callable[..., int]:
    mod = sys.modules.get("src.app.services.kb_builder")
    if mod is not None:
        builder_val = getattr(mod, "_flush", None)
        if builder_val is not None and builder_val is not _flush:
            return builder_val
    return _flush


def _document_hash(content: str) -> str:
    """문서 본문의 해시. 증분 색인의 변경 판정 기준입니다.

    DB 시각을 쓰지 않는 이유가 있습니다. `collected_at` 은 `default=utcnow` 라
    INSERT 시각이며, 재수집으로 값이 갱신돼도 시각이 그대로일 수 있습니다.
    본문 해시는 어떤 경로로 값이 바뀌었든 잡아냅니다.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_existing_index_value(operation: Callable[[], Any], operation_name: str) -> Any:
    """기존 색인 조회를 재시도하고, 계속 실패하면 변경 전에 중단합니다."""
    last_error: Exception | None = None
    max_attempts = _current_max_attempts()
    retry_delay = _current_retry_delay_seconds()
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                logger.warning("%s 재시도(%d/%d): %s", operation_name, attempt, max_attempts, exc)
                time.sleep(retry_delay)

    raise RuntimeError(
        f"{operation_name}에 {max_attempts}회 실패했습니다. "
        "기존 색인을 보존한 채 중단합니다. 명시적 full 실행 전에 원인을 확인하십시오."
    ) from last_error


def _load_existing_index(collection: Any) -> tuple[dict[str, str], bool]:
    """컬렉션에 이미 있는 id -> 본문 해시 맵을 읽습니다.

    두 번째 반환값은 증분을 적용할 수 있는지 여부입니다. 해시가 없거나 포맷
    버전이 다른 문서가 하나라도 있으면 비교 기준이 서지 않으므로 전량
    재구축으로 떨어집니다.
    """
    stored_count = _read_existing_index_value(
        lambda: int(collection.count()), "기존 색인 문서 수 조회"
    )

    if not stored_count:
        return {}, False

    batch_size = _current_lookup_batch_size()
    fmt_version = _current_doc_format_version()
    hashes: dict[str, str] = {}
    for offset in range(0, stored_count, batch_size):

        def read_page(page_offset: int = offset) -> tuple[list[str], list[dict[str, Any] | None]]:
            stored = collection.get(include=["metadatas"], limit=batch_size, offset=page_offset)
            ids, metadatas = stored.get("ids") or [], stored.get("metadatas") or []
            if not ids:
                raise RuntimeError(f"offset {page_offset} 페이지가 비어 있습니다.")
            if len(ids) != len(metadatas):
                raise RuntimeError(
                    f"offset {page_offset} 페이지의 ID {len(ids)}건과 "
                    f"메타데이터 {len(metadatas)}건이 일치하지 않습니다."
                )
            return ids, metadatas

        ids, metadatas = _read_existing_index_value(
            read_page, f"기존 색인 메타데이터 조회(offset={offset})"
        )
        for doc_id, meta in zip(ids, metadatas, strict=True):
            meta = meta or {}
            doc_hash = meta.get("doc_hash")
            if not doc_hash or int(meta.get("fmt", 0)) != fmt_version:
                return {}, False
            hashes[doc_id] = str(doc_hash)

    if len(hashes) != stored_count:
        raise RuntimeError(
            "기존 색인 조회 중 문서 수가 달라졌습니다. "
            f"count={stored_count}, loaded={len(hashes)}. 기존 색인을 보존한 채 중단합니다."
        )

    return hashes, True


def _diff_index(
    existing: dict[str, str], ids: list[str], metadatas: list[dict[str, Any]]
) -> tuple[list[int], list[str]]:
    """[Deprecated] 재색인할 항목의 위치와 삭제할 id 를 계산합니다.

    _sync_stream 에서는 전량 target_ids 생성을 회피하므로 이 함수를 직접 호출하지 않습니다.
    """
    changed_positions = [
        position
        for position, doc_id in enumerate(ids)
        if existing.get(doc_id) != metadatas[position]["doc_hash"]
    ]
    # 집합을 반드시 밖에서 한 번만 만듭니다. 컴프리헨션 안에 두면 기존 문서마다
    # 재구축해 O(기존 x 대상) 이 되고, 10만 x 50만 규모에서는 끝나지 않습니다.
    target_ids = set(ids)
    removed_ids = [doc_id for doc_id in existing if doc_id not in target_ids]
    return changed_positions, removed_ids


def _flush(
    collection: Any, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]
) -> int:
    """배치로 upsert 합니다. 같은 id 가 오면 제자리에서 갱신됩니다."""
    indexed = 0
    for start in range(0, len(documents), INDEX_BATCH_SIZE):
        end = start + INDEX_BATCH_SIZE
        chunk_ids = ids[start:end]
        if chunk_ids:
            collection.upsert(
                documents=documents[start:end], metadatas=metadatas[start:end], ids=chunk_ids
            )
            indexed += len(chunk_ids)
    return indexed


def _sync_stream(
    collection: Any,
    items: Sequence[Any],
    make_id: Callable[[int, Any], str],
    make_doc: Callable[[int, Any], tuple[str, str, dict[str, Any]]],
    existing_hashes: dict[str, str],
    *,
    incremental: bool,
    delta_mode: bool,
    chunk_size: int,
    prepare_chunk: Callable[[Sequence[Any]], None] | None = None,
) -> tuple[int, KbSyncStats]:
    """컬렉션을 목표 상태에 맞춥니다.

    반환하는 건수는 **컬렉션에 있어야 할 전체 문서 수**입니다. 이번에 임베딩한
    수가 아닙니다. `knowledge_base_status.source_bid_count` 가 KB 규모를 뜻하는
    값이라, 증분 실행에서 변경분만 기록하면 KB 가 줄어든 것처럼 보입니다.

    [설계 근거: 2회 순회와 페이지 지연 조회]
    _sync_stream 은 2회 순회합니다 (Pass 1: removed_ids 소거, Pass 2: 임베딩/upsert).
    단순 제너레이터는 1회 순회 후 소진되므로 반복 순회 및 슬라이싱이 가능한 Sequence
    (PagedQuerySequence/list)를 유지하고, 슬라이스마다 페이지를 지연 조회하여 O(N) 메모리 상주를 방지합니다.
    """
    if not items:
        mode = "delta" if delta_mode else "full"
        empty_stats: KbSyncStats = {"mode": mode, "embedded": 0, "unchanged": 0, "removed": 0}
        return (collection.count() if delta_mode else 0), empty_stats

    removed_ids: list[str] = []
    if incremental and existing_hashes:
        # target_ids 전량 집합({make_id(...) for it in items})을 생성하면
        # 수십만 건의 문자열 객체가 existing_hashes 와 동시 상주하여 메모리가 폭증합니다.
        # 기존 색인의 키 집합(기존 문자열 재사용)에서 목표 ID 를 청크 단위로 소거(discard)하여
        # O(N) 추가 메모리 점유 없이 삭제 대상(removed_ids)을 계산합니다.
        unseen_ids = set(existing_hashes.keys())
        for start in range(0, len(items), chunk_size):
            chunk = items[start : start + chunk_size]
            for offset, item in enumerate(chunk):
                unseen_ids.discard(make_id(start + offset, item))
        removed_ids = list(unseen_ids)
        del unseen_ids

        # 임베딩을 시작하기 전에 막습니다. 이 비율을 넘는 삭제는 데이터가 실제로
        # 사라진 것이 아니라 상한값이나 DB 조회가 잘못된 경우입니다. 그대로 두면
        # 야간 재색인 한 번에 KB 가 통째로 비고, 챗봇은 근거 없이 답하게 됩니다.
        max_ratio = _current_max_removal_ratio()
        removal_ratio = len(removed_ids) / len(existing_hashes)
        if removal_ratio > max_ratio:
            raise RuntimeError(
                f"삭제 대상이 기존 색인의 {removal_ratio:.1%} 입니다"
                f" (기존 {len(existing_hashes)}건, 삭제 {len(removed_ids)}건, 목표 {len(items)}건)."
                f" 상한 {max_ratio:.0%} 를 넘어 중단합니다."
                " KB_MAX_DOCUMENTS 설정과 DB 조회 결과를 확인하십시오."
            )

    embedded_count = 0
    unchanged_count = 0
    # [설계 근거: G1 데이터 무손실 - Pass 2 upsert 문서 삭제 방지]
    # Pass 1 과 Pass 2 사이 집합 변경이 발생하더라도, Pass 2 에서 upsert/유지된 문서가
    # removed_ids 로 잘못 삭제되는 위험(G1 데이터 손실)을 원천 차단하기 위해 소거합니다.
    removed_ids_set = set(removed_ids) if incremental and removed_ids else set()
    flush_fn = _current_flush()

    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        if prepare_chunk is not None:
            prepare_chunk(chunk)
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        ids: list[str] = []
        for offset, item in enumerate(chunk):
            doc_id, content, meta = make_doc(start + offset, item)
            if removed_ids_set:
                removed_ids_set.discard(doc_id)
            if incremental and existing_hashes.get(doc_id) == meta.get("doc_hash"):
                unchanged_count += 1
            else:
                docs.append(content)
                metas.append(meta)
                ids.append(doc_id)
        if docs:
            embedded_count += flush_fn(collection, docs, metas, ids)

    # 삭제는 재색인 뒤에 합니다. 먼저 지우면 색인이 실패했을 때 문서만 사라집니다.
    final_removed_count = 0
    if incremental and removed_ids_set:
        final_removed = list(removed_ids_set)
        final_removed_count = len(final_removed)
        collection.delete(ids=final_removed)

    mode = "delta" if delta_mode else ("incremental" if incremental else "full")
    stats: KbSyncStats = {
        "mode": mode,
        "embedded": embedded_count,
        "unchanged": unchanged_count if incremental and not delta_mode else 0,
        "removed": final_removed_count if incremental and not delta_mode else 0,
    }
    return (collection.count() if delta_mode else len(items)), stats


def _sync(
    collection: Any,
    documents: list[str],
    metadatas: list[dict[str, Any]],
    ids: list[str],
    existing_hashes: dict[str, str],
    incremental: bool,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> tuple[int, KbSyncStats]:
    """[Deprecated] 하위 호환을 위해 유지되는 동기식 래퍼입니다."""
    if not documents:
        return 0, {"embedded": 0, "unchanged": 0, "removed": 0, "mode": "full"}
    return _sync_stream(
        collection,
        ids,
        lambda index, _: ids[index],
        lambda index, _: (ids[index], documents[index], metadatas[index]),
        existing_hashes,
        incremental=incremental,
        delta_mode=False,
        chunk_size=chunk_size,
    )
