#!/usr/bin/env python3
"""
bid_announcements.cntrct_mthd_nm 결손을 raw_data 에서 복구합니다.

수집기가 응답에 없는 태그명(cntrctMthdNm)을 읽고 있어 이 컬럼이 통째로
비어 있었습니다. 실제 필드명은 cntrctCnclsMthdNm 이며, 원본 응답은
raw_data 에 그대로 보존되어 있으므로 API 재수집 없이 복구할 수 있습니다.

이미 값이 있는 행은 건드리지 않습니다. 중간에 끊겨도 다시 실행하면
남은 행부터 이어서 채웁니다.

사용법:
    python scripts/repair_contract_method.py --dry-run
    python scripts/repair_contract_method.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import CursorResult  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402

# id 구간으로 잘라 갱신합니다. 300만 행을 한 트랜잭션으로 묶으면
# 락이 오래 잡혀 수집이 막힙니다.
BATCH_ROWS = 20_000

COUNT_SQL = text(
    """
    SELECT COUNT(*), MIN(id), MAX(id)
    FROM bid_announcements
    WHERE cntrct_mthd_nm IS NULL AND raw_data IS NOT NULL
    """
)

UPDATE_SQL = text(
    """
    UPDATE bid_announcements
    SET cntrct_mthd_nm = NULLIF(LEFT(JSON_VALUE(raw_data, '$.cntrctCnclsMthdNm'), 100), '')
    WHERE id BETWEEN :lo AND :hi
      AND cntrct_mthd_nm IS NULL
      AND raw_data IS NOT NULL
    """
)

FILLED_SQL = text("SELECT COUNT(*) FROM bid_announcements WHERE cntrct_mthd_nm IS NOT NULL")


def main() -> int:
    parser = argparse.ArgumentParser(description="계약체결방법 결손 복구")
    parser.add_argument("--dry-run", action="store_true", help="대상 건수만 출력")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        pending, lo, hi = session.execute(COUNT_SQL).one()
        before = session.scalar(FILLED_SQL)
        print(f"대상 {pending:,}건 (id {lo} ~ {hi}), 현재 채워진 행 {before:,}건")
        if args.dry_run or not pending:
            return 0

        started = time.monotonic()
        touched = 0
        cursor = lo
        while cursor <= hi:
            end = cursor + BATCH_ROWS - 1
            update_result = cast(
                CursorResult[Any],
                session.execute(UPDATE_SQL, {"lo": cursor, "hi": end}),
            )
            touched += update_result.rowcount or 0
            session.commit()
            cursor = end + 1
            done = min(cursor - lo, hi - lo + 1)
            print(
                f"  id {lo}~{min(end, hi)} 진행 {done:,}/{hi - lo + 1:,} "
                f"갱신 {touched:,}건 ({time.monotonic() - started:.0f}초)",
                flush=True,
            )

        after = session.scalar(FILLED_SQL)
        print("-" * 60)
        print(f"복구 완료: {touched:,}건 갱신, 채워진 행 {before:,} -> {after:,}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
