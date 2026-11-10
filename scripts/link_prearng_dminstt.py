"""bid_prearng_prices.dminstt_nm 을 bid_announcements 로 잇는 연결기.

예비가격 API 응답에는 수요기관명이 없어 `bid_prearng_prices.dminstt_nm` 이
비어 있다. 이 스크립트는 공고 원장에서 수요기관명을 찾아 그 컬럼을 채운다.

조인 키와 SQL, 매칭 규칙은 `src/app/services/prearng_dminstt_link.py` 에 있고
일일 증분 태스크와 같은 함수를 쓴다. 이 파일은 CLI 진입점만 제공한다.

기본 실행은 dry-run 이며 매칭 건수·미매칭 건수·전체 건수·매칭률만 출력한다.
운영 DB 쓰기는 `--execute` 를 명시했을 때만 일어난다.

    uv run python scripts/link_prearng_dminstt.py
    uv run python scripts/link_prearng_dminstt.py --execute

측정 결과는 docs/analysis/prearng_dminstt_match_20261007.md 에 기록돼 있다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.prearng_dminstt_link import (  # noqa: E402
    DEFAULT_ORD,
    ORD_WIDTH,
    AnnouncementRow,
    Key,
    MatchSummary,
    link_prearng_dminstt,
    match_rows,
    measure_prearng_dminstt,
    normalize_ord,
)

__all__ = [
    "DEFAULT_ORD",
    "ORD_WIDTH",
    "AnnouncementRow",
    "Key",
    "MatchSummary",
    "format_summary",
    "link_prearng_dminstt",
    "main",
    "match_rows",
    "measure_prearng_dminstt",
    "normalize_ord",
]


def _engine() -> object:
    from sqlalchemy import create_engine

    from src.app.core.config import settings

    return create_engine(settings.DATABASE_URL)


def measure() -> MatchSummary:
    engine = _engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            return measure_prearng_dminstt(conn)
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def apply_link() -> int:
    engine = _engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            return link_prearng_dminstt(conn)
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def format_summary(summary: MatchSummary) -> str:
    return (
        f"전체 {summary.total}건 | 매칭 {summary.matched}건 | 미매칭 {summary.unmatched}건 | "
        f"매칭률 {summary.match_rate:.4f}% | 수요기관명 확보 {summary.usable}건"
        f"({summary.usable_rate:.4f}%)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="예비가격-공고 수요기관명 연결기")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 dminstt_nm 을 갱신한다. 생략하면 dry-run(측정만)",
    )
    args = parser.parse_args(argv)

    try:
        summary = measure()
    except Exception as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1

    print(format_summary(summary))

    if not args.execute:
        print("dry-run: 운영 DB 를 변경하지 않았습니다. 반영하려면 --execute 를 주십시오.")
        return 0

    try:
        updated = apply_link()
    except Exception as exc:
        print(f"갱신 실패: {exc}", file=sys.stderr)
        return 1
    print(f"갱신 완료: dminstt_nm {updated}건을 채웠습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
