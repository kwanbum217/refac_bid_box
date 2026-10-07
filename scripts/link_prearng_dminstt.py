"""bid_prearng_prices.dminstt_nm 을 bid_announcements 로 잇는 연결기.

예비가격 API 응답에는 수요기관명이 없어 `bid_prearng_prices.dminstt_nm` 이
비어 있다. 이 스크립트는 공고 원장에서 수요기관명을 찾아 그 컬럼을 채운다.

조인 키는 (공고번호, 정규화한 차수, category) 세 가지다. 차수는 원장마다
표기가 흔들릴 수 있어 숫자만 남겨 0 을 채운 3자리로 맞춘다(`000`, `001`).

기본 실행은 dry-run 이며 매칭 건수·미매칭 건수·전체 건수·매칭률만 출력한다.
운영 DB 쓰기는 `--execute` 를 명시했을 때만 일어난다.

    uv run python scripts/link_prearng_dminstt.py
    uv run python scripts/link_prearng_dminstt.py --execute

측정 결과는 docs/analysis/prearng_dminstt_match_20261007.md 에 기록돼 있다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ORD_WIDTH = 3
DEFAULT_ORD = "000"

Key = tuple[str, str, str]
AnnouncementRow = tuple[str, str | None, str, str | None]


def normalize_ord(value: str | None) -> str:
    """차수를 숫자만 남긴 3자리 문자열로 정규화한다.

    None·빈 값·비숫자는 기본 차수 `000` 으로 떨어뜨린다.
    """
    if value is None:
        return DEFAULT_ORD
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if not digits:
        return DEFAULT_ORD
    return digits.lstrip("0").rjust(ORD_WIDTH, "0")


# 차수 정규화 SQL 식. MySQL CAST 는 앞자리 숫자만 읽어 normalize_ord() 규칙과 같다.
# SQL 은 보간 없는 리터럴로 둔다(사용자 입력이 닿지 않는다).
COUNT_SQL = """
SELECT
    COUNT(*) AS total,
    COALESCE(SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END), 0) AS matched,
    COALESCE(
        SUM(CASE WHEN a.dminstt_nm IS NOT NULL AND a.dminstt_nm <> '' THEN 1 ELSE 0 END), 0
    ) AS usable
FROM bid_prearng_prices p
LEFT JOIN bid_announcements a
    ON a.bid_ntce_no = p.bid_ntce_no
   AND LPAD(COALESCE(CAST(CAST(NULLIF(TRIM(a.bid_ntce_ord), '') AS UNSIGNED) AS CHAR), '0'), 3, '0')
     = LPAD(COALESCE(CAST(CAST(NULLIF(TRIM(p.bid_ntce_ord), '') AS UNSIGNED) AS CHAR), '0'), 3, '0')
   AND a.category = p.category
"""

UPDATE_SQL = """
UPDATE bid_prearng_prices p
JOIN bid_announcements a
    ON a.bid_ntce_no = p.bid_ntce_no
   AND LPAD(COALESCE(CAST(CAST(NULLIF(TRIM(a.bid_ntce_ord), '') AS UNSIGNED) AS CHAR), '0'), 3, '0')
     = LPAD(COALESCE(CAST(CAST(NULLIF(TRIM(p.bid_ntce_ord), '') AS UNSIGNED) AS CHAR), '0'), 3, '0')
   AND a.category = p.category
SET p.dminstt_nm = a.dminstt_nm
WHERE (p.dminstt_nm IS NULL OR p.dminstt_nm = '')
  AND a.dminstt_nm IS NOT NULL AND a.dminstt_nm <> ''
"""


@dataclass(frozen=True)
class MatchSummary:
    """매칭 집계. usable 은 매칭된 공고에서 수요기관명까지 건진 건수다."""

    total: int
    matched: int
    usable: int

    @property
    def unmatched(self) -> int:
        return self.total - self.matched

    @property
    def match_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.matched / self.total * 100.0

    @property
    def usable_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.usable / self.total * 100.0


def match_rows(
    prearng_keys: Iterable[Key],
    announcements: Iterable[AnnouncementRow],
) -> MatchSummary:
    """조인 키로 매칭률을 계산하는 순수 함수.

    운영 DB 없이 픽스처만으로 키 규칙을 검증할 수 있도록 SQL 과 같은 규칙을
    파이썬으로 재현한다. 조회 SQL(`COUNT_SQL`)의 판정과 일치해야 한다.
    """
    index: dict[Key, str | None] = {}
    for no, ord_value, category, dminstt_nm in announcements:
        index[(no, normalize_ord(ord_value), category)] = dminstt_nm

    total = 0
    matched = 0
    usable = 0
    for no, ord_value, category in prearng_keys:
        total += 1
        key = (no, normalize_ord(ord_value), category)
        if key not in index:
            continue
        matched += 1
        if index[key]:
            usable += 1
    return MatchSummary(total=total, matched=matched, usable=usable)


def _engine() -> object:
    from sqlalchemy import create_engine

    from src.app.core.config import settings

    return create_engine(settings.DATABASE_URL)


def measure() -> MatchSummary:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(text(COUNT_SQL)).one()
    finally:
        engine.dispose()  # type: ignore[attr-defined]
    return MatchSummary(total=int(row[0]), matched=int(row[1]), usable=int(row[2]))


def apply_link() -> int:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            result = conn.execute(text(UPDATE_SQL))
            return int(result.rowcount or 0)
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
