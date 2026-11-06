#!/usr/bin/env python3
"""
scripts/classify_band_regime.py

낙찰방법명이 `2억미만 1억이상` 인 용역 공고의 첨부를 내려받아 적용 기준 갈래를
판별하고 `bid_announcement_regime` 에 upsert 하는 일괄 스크립트.

기본은 dry-run 입니다. `--execute` 를 명시할 때만 외부 호출과 DB 쓰기를 합니다.
대상은 공고일 범위(`--start`/`--end`, 기본 최근 12개월)로 먼저 좁힌 뒤
`raw_data.sucsfbidMthdNm` 을 파이썬에서 거르고, 공고번호·업무구분별 최신 차수만
남깁니다. 이미 `CLASSIFIED`·`NO_ATTACHMENT` 로 저장된 행은 건너뛰고 `FAILED` 행만
재시도합니다.

첨부 원문 바이너리는 저장하지 않고 파일명과 SHA-256 만 `source_files` 에 남깁니다.
판별 자체는 `src/app/services/band_regime_classifier.py` 의 `classify_band_regime`
결과를 불투명 값으로 다룹니다.

실행:
    uv run python scripts/classify_band_regime.py --max-calls 400
    uv run python scripts/classify_band_regime.py --start 20251106 --end 20261106 --max-calls 400
    uv run python scripts/classify_band_regime.py --start 20251106 --end 20261106 --max-calls 400 --execute

설계 정본: `.orca/ref/band_2to1_attachment_classifier_design_20261106.md` 4절.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.mysql import insert as mysql_insert  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts.extract_score_params import extract_document_text  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.timeutil import utcnow  # noqa: E402
from src.app.models.announcement_regime import (  # noqa: E402
    REGIME_STATUS_CLASSIFIED,
    REGIME_STATUS_FAILED,
    REGIME_STATUS_NO_ATTACHMENT,
    BidAnnouncementRegime,
)
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.services.announcement_attachments import _allowed_url  # noqa: E402
from src.app.services.band_regime_classifier import (  # noqa: E402
    BAND_REGIME_CLASSIFIER_VERSION,
    NO_ATTACH,
    UNSPECIFIED,
    classify_band_regime,
)

TARGET_CATEGORY = "Servc"
BAND_METHOD_MARKERS = ("2억미만", "1억이상")
DEFAULT_SLEEP_SECONDS = 1.0
ERROR_LIMIT = 255
ATTACHMENT_SLOTS = 10
DOWNLOAD_TIMEOUT_SECONDS = 180
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_UPSERT_COLUMNS = (
    "regime",
    "evidence",
    "matched_rules",
    "source_files",
    "status",
    "error",
    "classifier_version",
    "classified_at",
)

# 압축·이미지는 원문 판별 대상이 아니므로 내려받기 전에 거릅니다. HWPX 는 zip
# 컨테이너지만 확장자가 hwpx 이므로 여기에 넣지 않습니다.
_SKIP_EXTENSIONS = frozenset(
    {
        ".zip",
        ".7z",
        ".rar",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".alz",
        ".egg",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
        ".heic",
    }
)

_IMAGE_MAGIC = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a",
    b"GIF89a",
    b"II*\x00",
    b"MM\x00*",
)


@dataclass(frozen=True)
class Attachment:
    """내려받기 후보 첨부 1건."""

    name: str
    url: str


@dataclass(frozen=True)
class Target:
    """판별 대상 공고 1건."""

    bid_ntce_no: str
    bid_ntce_ord: str
    category: str
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class DocumentTexts:
    """첨부 1건에서 뽑은 판별용 텍스트 묶음. 추출 실패면 reason 이 채워집니다."""

    texts: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class TargetOutcome:
    """대상 1건 처리 결과."""

    status: str
    regime: str
    evidence: str | None = None
    matched_rules: tuple[str, ...] = ()
    source_files: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    calls: int = 0


class _Pacer:
    """외부 요청 사이 예절 대기. 첫 요청 전에는 기다리지 않습니다."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._requested = False

    def wait(self) -> None:
        if self._seconds > 0 and self._requested:
            time.sleep(self._seconds)
        self._requested = True


class _CallLimitReached(Exception):
    """--max-calls 상한에 걸려 대상 처리를 시작하지 못했습니다."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="2억미만 1억이상 띠 용역 공고 첨부 판별 일괄 실행 (기본 dry-run)",
    )
    parser.add_argument("--start", help="공고일 시작 YYYYMMDD. 기본 오늘 기준 1년 전")
    parser.add_argument("--end", help="공고일 종료 YYYYMMDD. 기본 오늘")
    parser.add_argument(
        "--max-calls",
        type=int,
        required=True,
        help="외부 첨부 다운로드 호출 상한. 초과하면 남은 대상을 처리하지 않고 중단합니다",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help=f"첨부 요청 사이 대기 초. 기본 {DEFAULT_SLEEP_SECONDS}",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="대상 목록과 예상 호출 수만 출력합니다. 기본값",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="첨부 내려받기·판별·저장을 수행합니다",
    )
    return parser


def _resolve_period(start_value: str | None, end_value: str | None) -> tuple[date, date]:
    today = utcnow().date()
    try:
        start = (
            datetime.strptime(start_value, "%Y%m%d").date()
            if start_value
            else today - timedelta(days=365)
        )
        end = datetime.strptime(end_value, "%Y%m%d").date() if end_value else today
    except ValueError as exc:
        raise ValueError(f"날짜는 YYYYMMDD 형식이어야 합니다: {exc}") from exc
    if start > end:
        raise ValueError(f"시작일 {start} 이 종료일 {end} 보다 늦습니다")
    return start, end


def _as_dict(value: Any) -> dict[str, Any]:
    """raw_data JSON 컬럼 값을 dict 로 맞춥니다."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _ord_key(value: Any) -> int:
    """공고 차수를 최신 비교용 정수로 만듭니다. 숫자가 아니면 가장 낮게 둡니다."""
    text_value = str(value or "").strip()
    return int(text_value) if text_value.isdigit() else -1


def _is_band_method(raw_data: dict[str, Any]) -> bool:
    method = raw_data.get("sucsfbidMthdNm")
    if not isinstance(method, str):
        return False
    return all(marker in method for marker in BAND_METHOD_MARKERS)


def _skip_by_name(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return bool(suffix) and suffix in _SKIP_EXTENSIONS


def _looks_like_image(data: bytes) -> bool:
    return any(data.startswith(magic) for magic in _IMAGE_MAGIC)


def plan_attachments(raw_data: Any) -> list[Attachment]:
    """raw_data 에서 내려받을 첨부 목록을 만듭니다.

    URL 허용 판정은 `announcement_attachments._allowed_url` 을 그대로 씁니다.
    압축·이미지 확장자는 제외하고, 같은 URL 은 한 번만 남깁니다.
    """
    data = _as_dict(raw_data)
    attachments: list[Attachment] = []
    seen: set[str] = set()

    def add(url_value: Any, name_value: Any, fallback: str) -> None:
        url = _allowed_url(url_value)
        if url is None or url in seen:
            return
        name = name_value.strip() if isinstance(name_value, str) else ""
        if name and _skip_by_name(name):
            return
        seen.add(url)
        attachments.append(Attachment(name=name or fallback, url=url))

    for number in range(1, ATTACHMENT_SLOTS + 1):
        add(
            data.get(f"ntceSpecDocUrl{number}"),
            data.get(f"ntceSpecFileNm{number}"),
            f"첨부파일 {number}",
        )
    add(data.get("stdNtceDocUrl"), data.get("ntceSpecFileNm1"), "표준공고문")
    return attachments


def download_attachment(url: str) -> bytes:
    """첨부 URL 하나를 내려받습니다. 원문은 메모리에서만 씁니다."""
    with httpx.Client(follow_redirects=True) as client:
        response = client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content


def _pdf_texts(data: bytes) -> DocumentTexts:
    """PDF 첨부의 텍스트 레이어를 pdfplumber 로 읽습니다."""
    try:
        import pdfplumber
    except ImportError:
        return DocumentTexts(reason="pdfplumber 미설치")

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts = tuple(
                text.strip() for page in pdf.pages if (text := page.extract_text()) and text.strip()
            )
    except Exception as exc:  # 손상 PDF 는 사유만 남기고 실패로 처리합니다
        return DocumentTexts(reason=f"PDF 파싱 실패: {type(exc).__name__}")
    if not texts:
        return DocumentTexts(reason="텍스트 레이어 없음")
    return DocumentTexts(texts=texts)


def extract_document_texts(name: str, data: bytes) -> DocumentTexts:
    """첨부 바이트에서 판별용 텍스트를 뽑습니다.

    HWP·HWPX·HWPML 은 `extract_score_params.extract_document_text` 를 쓰고 PDF 만
    pdfplumber 로 읽습니다. 표 행도 문단과 함께 판별 입력으로 넘깁니다.
    """
    if data[:5] == b"%PDF-":
        return _pdf_texts(data)

    document = extract_document_text(data)
    texts: list[str] = []
    if document.flat:
        texts.append(document.flat)
    for row in document.rows:
        joined = " ".join(cell for cell in row if cell).strip()
        if joined:
            texts.append(joined)
    if not texts:
        return DocumentTexts(reason=document.reason or "본문 텍스트 없음")

    unique = tuple(dict.fromkeys(texts))
    return DocumentTexts(texts=unique)


def _classify_target(
    target: Target,
    *,
    pacer: _Pacer,
    calls_left: int,
    download_fn: Callable[[str], bytes],
    extract_fn: Callable[[str, bytes], DocumentTexts],
) -> TargetOutcome:
    """대상 1건을 내려받아 판별합니다. 호출 상한을 넘으면 _CallLimitReached."""
    attachments = plan_attachments(target.raw_data)
    if not attachments:
        return TargetOutcome(status=REGIME_STATUS_NO_ATTACHMENT, regime=NO_ATTACH)

    if len(attachments) > calls_left:
        raise _CallLimitReached

    texts: list[str] = []
    source_files: list[dict[str, str]] = []
    errors: list[str] = []
    calls = 0
    for attachment in attachments:
        pacer.wait()
        calls += 1
        try:
            data = download_fn(attachment.url)
        except Exception as exc:
            errors.append(f"내려받기 실패: {attachment.name}: {type(exc).__name__}")
            continue

        source_files.append(
            {
                "name": attachment.name,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        if _looks_like_image(data):
            continue

        extracted = extract_fn(attachment.name, data)
        if extracted.reason is not None:
            errors.append(f"추출 실패: {attachment.name}: {extracted.reason}")
            continue
        texts.extend(extracted.texts)

    # 첨부 하나가 판독 불가여도 다른 첨부에서 텍스트를 얻었으면 판별합니다. 판독
    # 가능한 첨부가 하나도 없을 때만 FAILED 로 남겨 재시도 대상으로 삼습니다.
    if not texts:
        reason = "; ".join(errors) if errors else "판별할 본문 텍스트 없음"
        return TargetOutcome(
            status=REGIME_STATUS_FAILED,
            regime=UNSPECIFIED,
            source_files=source_files,
            error=_short_error(reason),
            calls=calls,
        )

    result = classify_band_regime(texts)
    status = REGIME_STATUS_NO_ATTACHMENT if result.regime == NO_ATTACH else REGIME_STATUS_CLASSIFIED
    return TargetOutcome(
        status=status,
        regime=result.regime,
        evidence=result.evidence,
        matched_rules=result.matched_rules,
        source_files=source_files,
        calls=calls,
    )


def _short_error(message: str) -> str:
    return message[:ERROR_LIMIT]


def collect_targets(
    db: Session,
    *,
    start: date,
    end: date,
) -> list[Target]:
    """판별 대상 공고를 고릅니다.

    공고일 범위로 먼저 좁힌 뒤 `sucsfbidMthdNm` 을 파이썬에서 걸러 운영 DB 에
    raw_data LIKE 전체 스캔을 걸지 않습니다. 공고번호·업무구분별 최신 차수만
    남기고, 이미 CLASSIFIED·NO_ATTACHMENT 로 저장된 행은 제외합니다.
    """
    window_from = datetime.combine(start, day_time.min)
    window_end = datetime.combine(end + timedelta(days=1), day_time.min)
    stmt = (
        select(
            BidAnnouncement.bid_ntce_no,
            BidAnnouncement.bid_ntce_ord,
            BidAnnouncement.category,
            BidAnnouncement.raw_data,
        )
        .where(
            BidAnnouncement.category == TARGET_CATEGORY,
            BidAnnouncement.bid_ntce_dt >= window_from,
            BidAnnouncement.bid_ntce_dt < window_end,
        )
        .order_by(BidAnnouncement.bid_ntce_no, BidAnnouncement.bid_ntce_ord)
    )

    latest: dict[tuple[str, str], Target] = {}
    latest_ord: dict[tuple[str, str], int] = {}
    result = db.execute(stmt.execution_options(stream_results=True))
    for row in result:
        raw_data = _as_dict(row.raw_data)
        if not _is_band_method(raw_data):
            continue
        key = (row.bid_ntce_no, row.category)
        ord_key = _ord_key(row.bid_ntce_ord)
        if key in latest and ord_key <= latest_ord[key]:
            continue
        latest[key] = Target(
            bid_ntce_no=row.bid_ntce_no,
            bid_ntce_ord=str(row.bid_ntce_ord or ""),
            category=row.category,
            raw_data=raw_data,
        )
        latest_ord[key] = ord_key

    if not latest:
        return []

    numbers = sorted({target.bid_ntce_no for target in latest.values()})
    existing: dict[tuple[str, str, str], str] = {}
    regime_stmt = select(
        BidAnnouncementRegime.bid_ntce_no,
        BidAnnouncementRegime.bid_ntce_ord,
        BidAnnouncementRegime.category,
        BidAnnouncementRegime.status,
    ).where(
        BidAnnouncementRegime.category == TARGET_CATEGORY,
        BidAnnouncementRegime.bid_ntce_no.in_(numbers),
    )
    for row in db.execute(regime_stmt):
        existing[(row.bid_ntce_no, row.bid_ntce_ord, row.category)] = row.status

    targets: list[Target] = []
    for target in latest.values():
        key = (target.bid_ntce_no, target.bid_ntce_ord, target.category)
        if existing.get(key) in (REGIME_STATUS_CLASSIFIED, REGIME_STATUS_NO_ATTACHMENT):
            continue
        targets.append(target)
    return targets


def _upsert_regime(db: Session, rows: list[dict[str, Any]]) -> None:
    """판별 결과를 유니크 키 기준 upsert 로 저장합니다.

    MySQL·SQLite 방언을 모두 지원하며, 충돌 시 판별 결과·상태·시각을 갱신합니다.
    """
    if not rows:
        return
    # 다중 행 INSERT 는 첫 행의 키로 컬럼 목록을 만듭니다. 갱신 절은 _UPSERT_COLUMNS
    # 전체를 참조하므로 행마다 같은 컬럼을 채우지 않으면 MySQL 이 new.<컬럼> 을 찾지
    # 못합니다(2026-11-06 운영 실행에서 error 키 누락으로 1054 오류). ORM 모델로 만든
    # INSERT 는 ORM 일괄 경로를 타 None 값 컬럼을 빼므로 Core 테이블로 만듭니다.
    columns = ("bid_ntce_no", "bid_ntce_ord", "category", *_UPSERT_COLUMNS)
    rows = [{name: row.get(name) for name in columns} for row in rows]
    if db.get_bind().dialect.name in ("mysql", "mariadb"):
        mysql_stmt = mysql_insert(BidAnnouncementRegime.__table__)
        stmt = mysql_stmt.on_duplicate_key_update(
            **{name: mysql_stmt.inserted[name] for name in _UPSERT_COLUMNS}
        )
    else:
        sqlite_stmt = sqlite_insert(BidAnnouncementRegime.__table__)
        stmt = sqlite_stmt.on_conflict_do_update(
            index_elements=["bid_ntce_no", "bid_ntce_ord", "category"],
            set_={name: sqlite_stmt.excluded[name] for name in _UPSERT_COLUMNS},
        )
    db.execute(stmt, rows)
    db.commit()


def _outcome_row(target: Target, outcome: TargetOutcome) -> dict[str, Any]:
    matched_rules = ",".join(outcome.matched_rules)
    return {
        "bid_ntce_no": target.bid_ntce_no,
        "bid_ntce_ord": target.bid_ntce_ord,
        "category": target.category,
        "regime": outcome.regime,
        "evidence": outcome.evidence[:255] if outcome.evidence else None,
        "matched_rules": matched_rules[:255] if matched_rules else None,
        "source_files": outcome.source_files or None,
        "status": outcome.status,
        "error": _short_error(outcome.error) if outcome.error else None,
        "classifier_version": BAND_REGIME_CLASSIFIER_VERSION,
        "classified_at": utcnow(),
    }


def run_batch(
    db: Session,
    *,
    start: date,
    end: date,
    dry_run: bool = True,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_calls: int,
    download_fn: Callable[[str], bytes] | None = None,
    extract_fn: Callable[[str, bytes], DocumentTexts] | None = None,
) -> dict[str, Any]:
    """대상 공고를 골라 판별하고 상태·regime 별 집계를 돌려줍니다."""
    if max_calls < 1:
        raise ValueError("--max-calls 는 1 이상이어야 합니다")
    if sleep_seconds < 0:
        raise ValueError("--sleep 은 0 이상이어야 합니다")

    fetch = download_fn or download_attachment
    extract = extract_fn or extract_document_texts

    targets = collect_targets(db, start=start, end=end)
    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "start": f"{start:%Y%m%d}",
        "end": f"{end:%Y%m%d}",
        "targets": len(targets),
        "estimated_calls": sum(len(plan_attachments(target.raw_data)) for target in targets),
        "calls_used": 0,
        "classified": 0,
        "no_attachment": 0,
        "failed": 0,
        "skipped": 0,
        "regimes": {},
    }

    span_days = (end - start).days + 1
    print(
        f"대상 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({span_days}일), 업무구분 {TARGET_CATEGORY}"
    )
    print(f"대상 공고: {len(targets)}건")

    if dry_run:
        for target in targets:
            attachments = plan_attachments(target.raw_data)
            print(f"  - {target.bid_ntce_no}-{target.bid_ntce_ord} 첨부 {len(attachments)}개")
        print(f"예상 외부 호출 수: {summary['estimated_calls']}회")
        if summary["estimated_calls"] > max_calls:
            print(
                f"주의: 예상 호출 수가 --max-calls {max_calls} 를 넘습니다. "
                "--execute 시 상한에서 중단되고 남은 대상은 건너뜁니다."
            )
        print("dry-run 입니다. 외부 호출과 DB 저장은 --execute 를 명시해야 수행합니다.")
        return summary

    pacer = _Pacer(sleep_seconds)
    calls_used = 0
    regimes: dict[str, int] = {}
    for index, target in enumerate(targets):
        outcome = None
        try:
            outcome = _classify_target(
                target,
                pacer=pacer,
                calls_left=max_calls - calls_used,
                download_fn=fetch,
                extract_fn=extract,
            )
        except _CallLimitReached:
            summary["skipped"] = len(targets) - index
            print(
                f"--max-calls 상한({max_calls})에 걸려 남은 "
                f"{summary['skipped']}건을 처리하지 않습니다."
            )
            break

        calls_used += outcome.calls
        _upsert_regime(db, [_outcome_row(target, outcome)])
        summary[outcome.status.lower()] += 1
        regimes[outcome.regime] = regimes.get(outcome.regime, 0) + 1
        label = f"{target.bid_ntce_no}-{target.bid_ntce_ord}"
        if outcome.status == REGIME_STATUS_FAILED:
            print(f"  {label}: {outcome.status} ({outcome.error})", file=sys.stderr)
        else:
            print(f"  {label}: {outcome.status} {outcome.regime}")

    summary["calls_used"] = calls_used
    summary["regimes"] = regimes
    if summary["skipped"]:
        summary["status"] = "truncated"

    print("-" * 60)
    print(f"외부 호출: {calls_used}회 (상한 {max_calls}회)")
    print(
        f"상태: {REGIME_STATUS_CLASSIFIED} {summary['classified']} / "
        f"{REGIME_STATUS_NO_ATTACHMENT} {summary['no_attachment']} / "
        f"{REGIME_STATUS_FAILED} {summary['failed']} / 건너뜀 {summary['skipped']}"
    )
    if regimes:
        print("regime 분포:")
        for regime, count in sorted(regimes.items()):
            print(f"  - {regime}: {count}건")
    else:
        print("regime 분포: 저장된 결과 없음")
    return summary


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        start, end = _resolve_period(args.start, args.end)
        if args.max_calls < 1:
            raise ValueError("--max-calls 는 1 이상이어야 합니다")
        if args.sleep < 0:
            raise ValueError("--sleep 은 0 이상이어야 합니다")
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    session = SessionLocal()
    try:
        summary = run_batch(
            session,
            start=start,
            end=end,
            dry_run=args.dry_run,
            sleep_seconds=args.sleep,
            max_calls=args.max_calls,
        )
    finally:
        session.close()

    return 1 if summary["status"] in ("error", "truncated") else 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
