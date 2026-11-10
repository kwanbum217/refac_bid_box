"""bid_prearng_prices 의 수요기관명을 bid_announcements 로 잇는 연결 로직.

예비가격 API 응답에는 수요기관명이 없어 `bid_prearng_prices.dminstt_nm` 이
비어 있습니다. 이 모듈은 공고 원장에서 수요기관명을 찾아 그 컬럼을 채우는
조회·갱신 SQL 과 매칭 규칙을 제공합니다. CLI(`scripts/link_prearng_dminstt.py`)
와 일일 증분 태스크(`src/tasks/scheduled_tasks.py`)가 같은 함수를 씁니다.

조인 키는 (공고번호, 정규화한 차수, category) 세 가지입니다. 차수는 원장마다
표기가 흔들릴 수 있어 숫자만 남겨 0 을 채운 3자리로 맞춥니다(`000`, `001`).

갱신 함수는 커밋하지 않습니다. 트랜잭션은 호출자가 소유합니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

ORD_WIDTH = 3
DEFAULT_ORD = "000"

Key = tuple[str, str, str]
AnnouncementRow = tuple[str, str | None, str, str | None]


def normalize_ord(value: str | None) -> str:
    """차수를 숫자만 남긴 3자리 문자열로 정규화합니다.

    None·빈 값·비숫자는 기본 차수 `000` 으로 떨어뜨립니다.
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
    """매칭 집계. usable 은 매칭된 공고에서 수요기관명까지 건진 건수입니다."""

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
    파이썬으로 재현합니다. 조회 SQL(`COUNT_SQL`)의 판정과 일치해야 합니다.
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


def measure_prearng_dminstt(conn: Any) -> MatchSummary:
    """연결 현황을 읽기 전용으로 집계합니다."""
    row = conn.execute(text(COUNT_SQL)).one()
    return MatchSummary(total=int(row[0]), matched=int(row[1]), usable=int(row[2]))


def link_prearng_dminstt(conn: Any) -> int:
    """비어 있는 `dminstt_nm` 을 공고 원장 값으로 채우고 갱신 행 수를 돌려줍니다.

    이미 값이 있는 행은 건드리지 않으므로 반복 실행해도 결과가 같습니다.
    커밋하지 않으므로 Session 이면 호출자가 commit/rollback 합니다.
    """
    result = conn.execute(text(UPDATE_SQL))
    return int(result.rowcount or 0)
