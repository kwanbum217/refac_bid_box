"""
tests/test_classify_band_regime.py

`scripts/classify_band_regime.py` 일괄 판별 계약 검증.

SQLite 인메모리 DB 에 `bid_announcements` 3건(첨부 있음, 첨부 없음, 다른 띠)과
`bid_announcement_regime` 테이블을 만들고 내려받기·추출 함수를 대체합니다.
실제 네트워크·운영 DB·원문 파일은 쓰지 않습니다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import pdfplumber
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from scripts import classify_band_regime as script
from src.app.core.db import Base
from src.app.models.announcement_regime import (
    REGIME_STATUS_CLASSIFIED,
    REGIME_STATUS_FAILED,
    REGIME_STATUS_NO_ATTACHMENT,
    BidAnnouncementRegime,
)
from src.app.models.bids import BidAnnouncement

BID_ATTACHED = "R26BK00000001"
BID_NO_ATTACH = "R26BK00000002"
BID_OTHER_BAND = "R26BK00000003"
BID_EXTRA_ATTACHED = "R26BK00000004"

BAND_METHOD = "적격심사제-추정가격 2억미만 1억이상"
OTHER_BAND_METHOD = "적격심사제-추정가격 1억미만"
BID_DT = datetime(2026, 6, 1, 10, 0, 0)
PERIOD = (date(2026, 5, 1), date(2026, 7, 1))
ATTACHMENT_URL = "https://www.g2b.go.kr/download/1.hwp"
CLASSIFIER_TEXT = "조달청 일반용역 적격심사 세부기준을 적용합니다."
PDF_TEXT = "적격심사 세부기준 PDF 본문입니다."


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[BidAnnouncement.__table__, BidAnnouncementRegime.__table__],
    )
    with Session(engine) as session:
        _seed_announcements(session)
        session.commit()
        yield session
    engine.dispose()


def _announcement(
    bid_ntce_no: str,
    *,
    method: str,
    raw_extra: dict[str, Any] | None = None,
    bid_ntce_ord: str = "000",
) -> BidAnnouncement:
    raw_data: dict[str, Any] = {"sucsfbidMthdNm": method}
    if raw_extra:
        raw_data.update(raw_extra)
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        category="Servc",
        bid_ntce_nm=f"공고 {bid_ntce_no}",
        bid_ntce_dt=BID_DT,
        raw_data=raw_data,
    )


def _seed_announcements(session: Session) -> None:
    session.add(
        _announcement(
            BID_ATTACHED,
            method=BAND_METHOD,
            raw_extra={
                "ntceSpecDocUrl1": ATTACHMENT_URL,
                "ntceSpecFileNm1": "적격심사.hwp",
            },
        )
    )
    session.add(_announcement(BID_NO_ATTACH, method=BAND_METHOD))
    session.add(_announcement(BID_OTHER_BAND, method=OTHER_BAND_METHOD))


def _run(
    session: Session,
    *,
    dry_run: bool,
    max_calls: int = 10,
    calls: list[str] | None = None,
) -> dict[str, Any]:
    recorded = calls if calls is not None else []

    def fake_download(url: str) -> bytes:
        recorded.append(url)
        return b"fake-hwp-bytes:" + url.encode()

    def fake_extract(name: str, data: bytes) -> script.DocumentTexts:
        assert name
        assert data.startswith(b"fake-hwp-bytes:")
        return script.DocumentTexts(texts=(CLASSIFIER_TEXT,))

    return script.run_batch(
        session,
        start=PERIOD[0],
        end=PERIOD[1],
        dry_run=dry_run,
        sleep_seconds=0,
        max_calls=max_calls,
        download_fn=fake_download,
        extract_fn=fake_extract,
    )


def _rows(session: Session) -> dict[tuple[str, str], BidAnnouncementRegime]:
    return {
        (row.bid_ntce_no, row.bid_ntce_ord): row
        for row in session.scalars(select(BidAnnouncementRegime))
    }


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(BidAnnouncementRegime)) or 0


def test_dry_run_writes_nothing(db: Session) -> None:
    calls: list[str] = []

    summary = _run(db, dry_run=True, calls=calls)

    assert calls == []
    assert _count(db) == 0
    assert summary["targets"] == 2
    assert summary["estimated_calls"] == 1


def test_execute_classifies_only_band_announcements(db: Session) -> None:
    calls: list[str] = []

    summary = _run(db, dry_run=False, calls=calls)

    rows = _rows(db)
    assert set(rows) == {
        (BID_ATTACHED, "000"),
        (BID_NO_ATTACH, "000"),
    }
    assert BID_OTHER_BAND not in {row.bid_ntce_no for row in rows.values()}

    attached = rows[(BID_ATTACHED, "000")]
    assert attached.status == REGIME_STATUS_CLASSIFIED
    assert attached.regime == "PPS"
    assert attached.matched_rules == "R6"

    unattached = rows[(BID_NO_ATTACH, "000")]
    assert unattached.status == REGIME_STATUS_NO_ATTACHMENT
    assert unattached.regime == "NO_ATTACH"

    assert calls == [ATTACHMENT_URL]
    assert summary["classified"] == 1
    assert summary["no_attachment"] == 1
    assert summary["failed"] == 0
    assert summary["calls_used"] == 1


def test_rerun_skips_classified_and_retries_failed(db: Session) -> None:
    _run(db, dry_run=False)

    retry_calls: list[str] = []
    _run(db, dry_run=False, calls=retry_calls)
    assert retry_calls == []

    rows = _rows(db)
    rows[(BID_ATTACHED, "000")].status = REGIME_STATUS_FAILED
    rows[(BID_ATTACHED, "000")].regime = "UNSPECIFIED"
    rows[(BID_ATTACHED, "000")].error = "일시 실패"
    db.commit()

    retry_calls = []
    summary = _run(db, dry_run=False, calls=retry_calls)

    assert retry_calls == [ATTACHMENT_URL]
    assert rows[(BID_ATTACHED, "000")].status == REGIME_STATUS_CLASSIFIED
    assert rows[(BID_ATTACHED, "000")].error is None
    assert summary["classified"] == 1


def test_max_calls_stops_remaining_targets(db: Session) -> None:
    db.add(
        _announcement(
            BID_EXTRA_ATTACHED,
            method=BAND_METHOD,
            raw_extra={
                "ntceSpecDocUrl1": "https://www.g2b.go.kr/download/2.hwp",
                "ntceSpecFileNm1": "적격심사2.hwp",
            },
        )
    )
    db.commit()

    calls: list[str] = []
    summary = _run(db, dry_run=False, max_calls=1, calls=calls)

    rows = _rows(db)
    assert calls == [ATTACHMENT_URL]
    assert (BID_EXTRA_ATTACHED, "000") not in rows
    assert rows[(BID_ATTACHED, "000")].status == REGIME_STATUS_CLASSIFIED
    assert rows[(BID_NO_ATTACH, "000")].status == REGIME_STATUS_NO_ATTACHMENT
    assert summary["skipped"] == 1
    assert summary["calls_used"] == 1
    assert summary["status"] == "truncated"


def test_source_files_store_only_name_and_sha256(db: Session) -> None:
    _run(db, dry_run=False)

    row = _rows(db)[(BID_ATTACHED, "000")]
    assert row.source_files is not None
    assert len(row.source_files) == 1
    entry = row.source_files[0]
    assert set(entry) == {"name", "sha256"}
    assert entry["name"] == "적격심사.hwp"
    assert len(entry["sha256"]) == 64
    assert all(char in "0123456789abcdef" for char in entry["sha256"])


def test_pdf_extraction_uses_pdfplumber(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[Any] = []

    class _FakePage:
        def extract_text(self) -> str:
            return PDF_TEXT

    class _FakePdf:
        pages = (_FakePage(),)

        def __enter__(self) -> _FakePdf:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_open(source: Any, *args: Any, **kwargs: Any) -> _FakePdf:
        opened.append(source)
        return _FakePdf()

    monkeypatch.setattr(pdfplumber, "open", fake_open)

    result = script.extract_document_texts("공고문.pdf", b"%PDF-1.4 fake")

    assert len(opened) == 1
    assert result.reason is None
    assert result.texts == (PDF_TEXT,)
