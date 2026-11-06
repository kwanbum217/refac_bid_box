#!/usr/bin/env python3
"""
scripts/regress_band_regime_classifier.py

첨부 판별기 회귀 측정. `bid_announcement_regime` 의 `CLASSIFIED`·`NO_ATTACHMENT`
전 행(운영 기준 100건)의 첨부를 다시 내려받아 새 판별기로 재판별하고 DB 라벨과
비교합니다.

- 첨부 원본은 `.cache/band_regress/raw/<공고번호>/<차수>_<번호>_<파일명>` 에 두고
  이미 있으면 재사용합니다. 요청 사이 기본 1초를 쉽니다.
- DB 는 `SET SESSION TRANSACTION READ ONLY` 트랜잭션에서 SELECT 만 합니다.
- 외부 호출 상한은 `--max-calls`(기본 400)이며, 넘으면 남은 행을 처리하지 않고
  `truncated` 로 끝냅니다.
- `.cache` 는 커밋하지 않습니다.

실행:
    uv run python scripts/regress_band_regime_classifier.py
    uv run python scripts/regress_band_regime_classifier.py --output .cache/band_regress/result.json
    uv run python scripts/regress_band_regime_classifier.py --bid-no R26BK01506722
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from scripts.classify_band_regime import (  # noqa: E402
    Attachment,
    DocumentTexts,
    extract_document_texts,
    plan_attachments,
)
from src.app.core.config import settings  # noqa: E402
from src.app.services.band_regime_classifier import (  # noqa: E402
    BAND_REGIME_CLASSIFIER_VERSION,
    classify_band_regime,
)

DEFAULT_CACHE_DIR = Path(".cache/band_regress/raw")
DEFAULT_MAX_CALLS = 400
DEFAULT_SLEEP_SECONDS = 1.0
DOWNLOAD_TIMEOUT_SECONDS = 180
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z가-힣._-]+")


@dataclass(frozen=True)
class RegimeRow:
    """비교 대상 1행."""

    bid_ntce_no: str
    bid_ntce_ord: str
    category: str
    db_regime: str
    db_matched_rules: str | None
    raw_data: dict[str, Any]


@dataclass
class RowOutcome:
    """한 행의 재판별 결과."""

    row: RegimeRow
    new_regime: str | None = None
    new_matched_rules: tuple[str, ...] = ()
    evidence: str | None = None
    plan: int = 0
    cache_hits: int = 0
    downloads: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.new_regime is not None and self.new_regime != self.row.db_regime

    def as_dict(self) -> dict[str, Any]:
        return {
            "bid_ntce_no": self.row.bid_ntce_no,
            "bid_ntce_ord": self.row.bid_ntce_ord,
            "category": self.row.category,
            "db_regime": self.row.db_regime,
            "new_regime": self.new_regime,
            "changed": self.changed,
            "matched_rules": list(self.new_matched_rules),
            "db_matched_rules": self.row.db_matched_rules,
            "evidence": self.evidence,
            "attachments": self.plan,
            "cache_hits": self.cache_hits,
            "downloads": self.downloads,
            "errors": self.errors,
        }


class _CallLimitReached(Exception):
    """--max-calls 상한에 걸렸습니다."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="첨부 판별기 재판별 회귀 (DB 쓰기 없음)",
    )
    parser.add_argument(
        "--output",
        help="행별 비교 결과를 JSON 으로 쓸 경로",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help=f"첨부 캐시 디렉터리 (기본 {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help=f"외부 다운로드 호출 상한 (기본 {DEFAULT_MAX_CALLS})",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help=f"다운로드 요청 사이 대기 초 (기본 {DEFAULT_SLEEP_SECONDS})",
    )
    parser.add_argument(
        "--bid-no",
        action="append",
        dest="bid_nos",
        default=None,
        help="지정한 공고번호만 처리합니다. 진단용이며 여러 번 쓸 수 있습니다",
    )
    parser.add_argument(
        "--dump-texts",
        action="store_true",
        help="재판별에 쓴 추출 텍스트를 캐시 디렉터리의 texts.txt 로 남깁니다",
    )
    return parser


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def load_rows(bid_nos: Sequence[str] | None = None) -> list[RegimeRow]:
    """DB 에서 비교 대상 행과 공고 raw_data 를 읽기 전용으로 가져옵니다."""
    statement = text(
        """
        SELECT r.bid_ntce_no, r.bid_ntce_ord, r.category, r.regime, r.matched_rules,
               a.raw_data
        FROM bid_announcement_regime r
        JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = r.bid_ntce_ord
         AND a.category = r.category
        WHERE r.status IN ('CLASSIFIED', 'NO_ATTACHMENT')
        ORDER BY r.bid_ntce_no, r.bid_ntce_ord
        """
    )

    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
            rows = conn.execute(statement).fetchall()
    finally:
        engine.dispose()

    selected = set(bid_nos) if bid_nos else None
    return [
        RegimeRow(
            bid_ntce_no=str(row.bid_ntce_no),
            bid_ntce_ord=str(row.bid_ntce_ord),
            category=str(row.category),
            db_regime=str(row.regime),
            db_matched_rules=row.matched_rules,
            raw_data=_as_dict(row.raw_data),
        )
        for row in rows
        if selected is None or str(row.bid_ntce_no) in selected
    ]


def _cached_path(cache_dir: Path, row: RegimeRow, index: int, attachment: Attachment) -> Path:
    """첨부 1건의 캐시 경로. 번호와 파일명으로 재사용 가능한 이름을 만듭니다."""
    name = _UNSAFE_NAME.sub("_", Path(attachment.name).name).strip("._")[:80]
    return cache_dir / row.bid_ntce_no / f"{row.bid_ntce_ord}_{index:02d}_{name or 'attachment'}"


def _download(url: str) -> bytes:
    with httpx.Client(follow_redirects=True) as client:
        response = client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content


def _extract_or_error(name: str, data: bytes) -> tuple[DocumentTexts, str | None]:
    try:
        return extract_document_texts(name, data), None
    except Exception as exc:  # 손상 첨부는 사유만 남깁니다
        return DocumentTexts(), f"추출 예외: {name}: {type(exc).__name__}"


def _process_row(
    row: RegimeRow,
    *,
    cache_dir: Path,
    download_fn: Any,
    extract_fn: Any,
    calls_left: int,
    dump_texts: bool,
) -> RowOutcome:
    """첨부를 캐시에서 읽거나 내려받아 재판별합니다."""
    attachments = plan_attachments(row.raw_data)
    outcome = RowOutcome(row=row, plan=len(attachments))
    if not attachments:
        outcome.new_regime = classify_band_regime([]).regime
        return outcome

    texts: list[str] = []
    for index, attachment in enumerate(attachments, start=1):
        path = _cached_path(cache_dir, row, index, attachment)
        if path.exists() and path.stat().st_size > 0:
            data = path.read_bytes()
            outcome.cache_hits += 1
        else:
            if calls_left <= 0:
                raise _CallLimitReached
            data = download_fn(attachment.url)
            calls_left -= 1
            outcome.downloads += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        extracted, error = extract_fn(attachment.name, data)
        if error is not None:
            outcome.errors.append(error)
            continue
        if extracted.reason is not None:
            outcome.errors.append(f"추출 실패: {attachment.name}: {extracted.reason}")
            continue
        texts.extend(extracted.texts)

    if dump_texts:
        dump_path = cache_dir / row.bid_ntce_no / "texts.txt"
        dump_path.write_text("\n\n".join(texts), encoding="utf-8")

    result = classify_band_regime(texts)
    outcome.new_regime = result.regime
    outcome.new_matched_rules = result.matched_rules
    outcome.evidence = result.evidence
    return outcome


def _print_table(outcomes: Sequence[RowOutcome]) -> None:
    header = (
        f"{'공고번호':<15} {'차수':<4} {'DB regime':<22} {'새 regime':<22} "
        f"{'변경':<4} matched_rules"
    )
    print(header)
    print("-" * len(header))
    for outcome in outcomes:
        rules = ",".join(outcome.new_matched_rules) or "-"
        print(
            f"{outcome.row.bid_ntce_no:<15} {outcome.row.bid_ntce_ord:<4} "
            f"{outcome.row.db_regime:<22} {outcome.new_regime or 'EXTRACT_FAIL':<22} "
            f"{'예' if outcome.changed else '아니오':<4} {rules}"
        )


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_calls < 1:
        print("입력 오류: --max-calls 는 1 이상이어야 합니다", file=sys.stderr)
        return 2
    if args.sleep < 0:
        print("입력 오류: --sleep 은 0 이상이어야 합니다", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir)
    rows = load_rows(args.bid_nos)
    print(f"대상: {len(rows)}건, 판별기 버전 {BAND_REGIME_CLASSIFIER_VERSION}")

    outcomes: list[RowOutcome] = []
    calls_used = 0
    truncated = False
    pacer = _Pacer(args.sleep)

    def _download_paced(url: str) -> bytes:
        pacer.wait()
        return _download(url)

    for index, row in enumerate(rows):
        try:
            outcome = _process_row(
                row,
                cache_dir=cache_dir,
                download_fn=_download_paced,
                extract_fn=_extract_or_error,
                calls_left=args.max_calls - calls_used,
                dump_texts=args.dump_texts,
            )
        except _CallLimitReached:
            truncated = True
            print(
                f"--max-calls 상한({args.max_calls})에 걸려 남은 {len(rows) - index}건을 "
                "처리하지 않습니다.",
                file=sys.stderr,
            )
            break
        calls_used += outcome.downloads
        outcomes.append(outcome)

    _print_table(outcomes)
    changed = [outcome for outcome in outcomes if outcome.changed]
    summary = {
        "targets": len(rows),
        "processed": len(outcomes),
        "changed": len(changed),
        "unchanged": len(outcomes) - len(changed),
        "calls_used": calls_used,
        "truncated": truncated,
        "new_regimes": _regime_counts(outcomes),
    }
    print(
        f"\n처리 {summary['processed']}/{summary['targets']}건, 변경 {summary['changed']}건, "
        f"외부 호출 {calls_used}회"
    )
    if changed:
        print("변경 행:")
        for outcome in changed:
            print(
                f"  - {outcome.row.bid_ntce_no}-{outcome.row.bid_ntce_ord}: "
                f"{outcome.row.db_regime} -> {outcome.new_regime} "
                f"({','.join(outcome.new_matched_rules) or '-'})"
            )

    if args.output:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "classifier_version": BAND_REGIME_CLASSIFIER_VERSION,
            "summary": summary,
            "rows": [outcome.as_dict() for outcome in outcomes],
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 JSON: {output_path}")

    return 1 if truncated else 0


def _regime_counts(outcomes: Sequence[RowOutcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        key = outcome.new_regime or "EXTRACT_FAIL"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


class _Pacer:
    """외부 요청 사이 예절 대기. 첫 요청 전에는 기다리지 않습니다."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._requested = False

    def wait(self) -> None:
        if self._seconds > 0 and self._requested:
            time.sleep(self._seconds)
        self._requested = True


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
