"""KB 원천 최신 차수·취소 제외와 이전 차수 문서 삭제 회귀 테스트.

문서 원천 세 경로(공고일, 수집일, 수집 델타)가 같은 공고의 최신 차수 한 행만
문서로 만들고, 최신 차수가 취소공고면 제외하는지 고정합니다. 증분·델타 색인이
컬렉션에 남은 이전 차수·취소 문서를 지우되 낙찰 결과 문서는 건드리지 않는지도
가짜 컬렉션으로 확인합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import kb_builder
from src.app.services.kb_document_builder import (
    _resolve_announcements,
    _resolve_delta_announcements,
)


class FakeCollection:
    """Chroma 컬렉션 대역. 문서 본문과 해시를 메모리에 보관합니다."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.docs: dict[str, dict[str, str]] = {
            doc_id: {"doc_hash": doc_hash, "document": ""}
            for doc_id, doc_hash in (initial or {}).items()
        }
        self.delete_calls: list[list[str]] = []

    def count(self) -> int:
        return len(self.docs)

    def get(
        self,
        include: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
        ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if ids is None:
            selected = list(self.docs)[offset : offset + limit]
        else:
            selected = [doc_id for doc_id in ids if doc_id in self.docs]
        return {
            "ids": selected,
            "metadatas": [
                {"type": "bid_info", "doc_hash": self.docs[doc_id]["doc_hash"], "fmt": 1}
                for doc_id in selected
            ],
            "documents": [self.docs[doc_id]["document"] for doc_id in selected],
        }

    def upsert(self, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        for document, meta, doc_id in zip(documents, metadatas, ids, strict=True):
            self.docs[doc_id] = {"doc_hash": meta["doc_hash"], "document": document}

    def delete(self, ids: list[str]) -> None:
        self.delete_calls.append(list(ids))
        for doc_id in ids:
            self.docs.pop(doc_id, None)


@pytest.fixture
def fake_index(tmp_path, monkeypatch):
    """Chroma 클라이언트와 컬렉션을 가짜로 바꾸고 색인 경로를 임시 경로로 둡니다."""
    collection = FakeCollection()
    monkeypatch.setattr(kb_builder.settings, "CHROMA_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setattr("chromadb.PersistentClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(kb_builder, "get_collection", lambda *args, **kwargs: collection)
    monkeypatch.setenv("KB_MAX_DOCUMENTS", "500")
    return collection


def _add(
    db,
    *,
    no: str,
    ord_: str,
    category: str = "Servc",
    notice_dt: datetime | None = None,
    collected_at: datetime | None = None,
    kind: str | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord=ord_,
        bid_ntce_nm=f"공고 {no}-{ord_}",
        dminstt_nm="수요기관",
        category=category,
        bid_ntce_dt=notice_dt if notice_dt is not None else utcnow() - timedelta(days=1),
        collected_at=collected_at if collected_at is not None else utcnow(),
        ntce_kind_nm=kind,
        raw_data={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _ids(sequence) -> list[int]:
    return [row.id for row in sequence]


def test_notice_date_source_keeps_only_latest_ord(isolated_db):
    """공고일 기준 원천은 같은 공고의 000·001 차수 중 001 만 문서화합니다."""
    now = utcnow()
    _add(isolated_db, no="2026A", ord_="000", notice_dt=now - timedelta(days=2))
    latest = _add(isolated_db, no="2026A", ord_="001", notice_dt=now - timedelta(days=1))

    sequence, mode = _resolve_announcements(isolated_db, now - timedelta(days=365))

    assert mode == "announcements_by_notice_date"
    assert _ids(sequence) == [latest.id]
    assert len(sequence) == 1


def test_collected_at_source_keeps_only_latest_ord(isolated_db):
    """수집일 기준 폴백 원천도 최신 차수 한 행만 문서화합니다."""
    now = utcnow()
    _add(
        isolated_db,
        no="2026B",
        ord_="000",
        notice_dt=now - timedelta(days=400),
        collected_at=now - timedelta(hours=2),
    )
    latest = _add(
        isolated_db,
        no="2026B",
        ord_="001",
        notice_dt=now - timedelta(days=400),
        collected_at=now - timedelta(hours=1),
    )

    sequence, mode = _resolve_announcements(
        isolated_db, now - timedelta(days=365), now - timedelta(days=365)
    )

    assert mode == "announcements_by_collected_at"
    assert _ids(sequence) == [latest.id]


def test_delta_source_keeps_only_latest_ord(isolated_db):
    """수집 델타 원천도 같은 공고의 이전 차수를 문서로 만들지 않습니다."""
    now = utcnow()
    _add(isolated_db, no="2026C", ord_="000", collected_at=now - timedelta(hours=2))
    latest = _add(isolated_db, no="2026C", ord_="001", collected_at=now - timedelta(hours=1))

    sequence, mode = _resolve_delta_announcements(isolated_db, now - timedelta(hours=6))

    assert mode == "announcements_by_collected_delta"
    assert _ids(sequence) == [latest.id]


def test_latest_cancelled_is_excluded_but_reannounced_is_kept(isolated_db):
    """최신 차수가 취소공고면 제외하고, 재공고·변경공고·NULL 은 유지합니다."""
    now = utcnow()
    _add(isolated_db, no="2026D", ord_="000", notice_dt=now - timedelta(days=2))
    _add(
        isolated_db,
        no="2026D",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        kind="취소공고",
    )
    _add(isolated_db, no="2026E", ord_="000", notice_dt=now - timedelta(days=2))
    reannounced = _add(
        isolated_db,
        no="2026E",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        kind="재공고",
    )
    changed = _add(
        isolated_db,
        no="2026F",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        kind="변경공고",
    )
    no_kind = _add(isolated_db, no="2026G", ord_="001", notice_dt=now - timedelta(days=1))

    sequence, _mode = _resolve_announcements(isolated_db, now - timedelta(days=365))

    assert set(_ids(sequence)) == {reannounced.id, changed.id, no_kind.id}


def test_count_and_pages_use_the_same_conditions(isolated_db):
    """PagedQuerySequence 총계와 실제 페이지 결과가 같은 조건을 씁니다."""
    now = utcnow()
    expected: set[int] = set()
    for index in range(6):
        no = f"2026P{index}"
        _add(isolated_db, no=no, ord_="000", notice_dt=now - timedelta(days=3))
        if index < 2:
            _add(
                isolated_db,
                no=no,
                ord_="001",
                notice_dt=now - timedelta(days=2),
                kind="취소공고",
            )
        else:
            expected.add(
                _add(
                    isolated_db,
                    no=no,
                    ord_="001",
                    notice_dt=now - timedelta(days=1),
                ).id
            )

    sequence, _mode = _resolve_announcements(isolated_db, now - timedelta(days=365))

    assert len(sequence) == len(expected) == 4
    assert len(list(sequence)) == 4
    assert set(_ids(sequence)) == expected
    assert set(_ids(sequence[0:2]) + _ids(sequence[2:4])) == expected


def test_incremental_index_removes_previous_ord_and_cancelled_docs(isolated_db, fake_index):
    """증분 색인은 이전 차수·취소 문서를 지우고 res 문서는 유지합니다."""
    now = utcnow()
    a_old = _add(isolated_db, no="2026R", ord_="000", notice_dt=now - timedelta(days=2))
    a_latest = _add(isolated_db, no="2026R", ord_="001", notice_dt=now - timedelta(days=1))
    c_old = _add(isolated_db, no="2026S", ord_="000", notice_dt=now - timedelta(days=3))
    c_cancelled = _add(
        isolated_db,
        no="2026S",
        ord_="001",
        notice_dt=now - timedelta(days=2),
        kind="취소공고",
    )
    fillers = [
        _add(isolated_db, no=f"2026T{index}", ord_="001", notice_dt=now - timedelta(days=1))
        for index in range(4)
    ]

    initial = {
        f"bid_{a_old.id}": "old_a",
        f"bid_{a_latest.id}": "old_latest",
        f"bid_{c_old.id}": "old_c",
        f"bid_{c_cancelled.id}": "old_cancel",
        "res_2026R_001": "res_hash",
    }
    for filler in fillers:
        document = kb_builder._build_announcement_document(filler, None)
        initial[f"bid_{filler.id}"] = kb_builder._document_hash(document)
    fake_index.docs = {
        doc_id: {"doc_hash": doc_hash, "document": ""} for doc_id, doc_hash in initial.items()
    }

    outcome = kb_builder.rebuild_knowledge_base(isolated_db, chunk_size=10)

    assert outcome["status"] == "success"
    assert outcome["metrics"]["index_mode"] == "incremental"
    assert outcome["metrics"]["removed_count"] == 3
    remaining = set(fake_index.docs)
    assert f"bid_{a_latest.id}" in remaining
    assert {f"bid_{filler.id}" for filler in fillers} <= remaining
    assert "res_2026R_001" in remaining
    assert f"bid_{a_old.id}" not in remaining
    assert f"bid_{c_old.id}" not in remaining
    assert f"bid_{c_cancelled.id}" not in remaining
    deleted = {doc_id for batch in fake_index.delete_calls for doc_id in batch}
    assert deleted == {f"bid_{a_old.id}", f"bid_{c_old.id}", f"bid_{c_cancelled.id}"}


def test_delta_index_removes_previous_ord_and_cancelled_docs(isolated_db, fake_index):
    """델타 색인도 새 차수 유입 시 이전 차수 문서와 취소 문서를 지웁니다."""
    now = utcnow()
    a_old = _add(
        isolated_db,
        no="2026U",
        ord_="000",
        notice_dt=now - timedelta(days=3),
        collected_at=now - timedelta(days=2),
    )
    a_latest = _add(
        isolated_db,
        no="2026U",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        collected_at=now - timedelta(minutes=30),
    )
    b_old = _add(
        isolated_db,
        no="2026V",
        ord_="000",
        notice_dt=now - timedelta(days=3),
        collected_at=now - timedelta(days=2),
    )
    b_cancelled = _add(
        isolated_db,
        no="2026V",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        collected_at=now - timedelta(minutes=20),
        kind="취소공고",
    )
    c_new = _add(
        isolated_db,
        no="2026W",
        ord_="001",
        notice_dt=now - timedelta(days=1),
        collected_at=now - timedelta(minutes=10),
    )

    initial = {
        f"bid_{a_old.id}": "old_a",
        f"bid_{b_old.id}": "old_b",
        f"bid_{b_cancelled.id}": "old_cancel",
        "res_2026V_001": "res_hash",
    }
    fake_index.docs = {
        doc_id: {"doc_hash": doc_hash, "document": ""} for doc_id, doc_hash in initial.items()
    }

    outcome = kb_builder.rebuild_knowledge_base(
        isolated_db, collected_since=now - timedelta(hours=1), chunk_size=10
    )

    assert outcome["status"] == "success"
    assert outcome["metrics"]["index_mode"] == "delta"
    remaining = set(fake_index.docs)
    assert f"bid_{a_latest.id}" in remaining
    assert f"bid_{c_new.id}" in remaining
    assert "res_2026V_001" in remaining
    assert f"bid_{a_old.id}" not in remaining
    assert f"bid_{b_old.id}" not in remaining
    assert f"bid_{b_cancelled.id}" not in remaining
