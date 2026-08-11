"""용역 raw_data 필드의 월별 구성 변화를 추적해 체제 전환을 찾습니다.

특징으로 넣기 전에 값의 의미가 시점에 따라 달라지는지 확인합니다.
prdctClsfcLmtYn 과 rbidPermsnYn 은 2025-01 계단식 전환이 확인됐습니다.

사용법:
    uv run python scripts/audit_servc_flag_regime.py [필드명 ...]

읽기 전용입니다. 결과 해석은
docs/design/servc_unused_rawdata_field_audit_20260811.md 4.3 을 보십시오.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SINCE = "2023-01-01"
JUMP_THRESHOLD = 15.0
DEFAULT_FIELDS = ("prdctClsfcLmtYn", "rbidPermsnYn", "indstrytyLmtYn", "dsgntCmptYn")


def monthly_ratio(engine, field: str) -> list[tuple[str, int, int, int]]:
    # 필드명은 JSON 경로 리터럴이라 바인딩할 수 없습니다. main 에서 영숫자만
    # 허용하도록 검사한 뒤 전달합니다.
    sql = (
        "SELECT LEFT(bid_ntce_dt,7) AS ym, COUNT(*) AS n, "  # noqa: S608
        f"SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.{field}'))='Y') AS hit, "
        f"SUM(JSON_EXTRACT(raw_data,'$.{field}') IS NULL) AS missing "
        "FROM bid_announcements "
        "WHERE category='Servc' AND raw_data IS NOT NULL AND bid_ntce_dt >= :since "
        "GROUP BY ym ORDER BY ym"
    )
    query = text(sql)
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(query, {"since": SINCE})]


def report(field: str, rows: list[tuple[str, int, int, int]]) -> None:
    print(f"\n[{field}]  (Y 비율)")
    previous: float | None = None
    jumps: list[str] = []
    for ym, total, hit, _missing in rows:
        ratio = 100 * int(hit) / total if total else 0.0
        if previous is not None and abs(ratio - previous) > JUMP_THRESHOLD:
            jumps.append(f"{ym} {previous:.1f}%->{ratio:.1f}%")
        previous = ratio
    first, last = rows[0], rows[-1]
    missing_total = sum(int(row[3]) for row in rows)
    print(
        f"   {first[0]} {100 * int(first[2]) / first[1]:.1f}%"
        f"  ->  {last[0]} {100 * int(last[2]) / last[1]:.1f}%"
        f"   키 없음 합 {missing_total:,}"
    )
    print("   급변: " + (", ".join(jumps) if jumps else "없음"))


def main() -> None:
    fields = tuple(sys.argv[1:]) or DEFAULT_FIELDS
    for field in fields:
        if not field.isalnum():
            raise SystemExit(f"필드명에 영숫자만 허용합니다: {field}")

    load_dotenv(PROJECT_ROOT / ".env")
    engine = create_engine(os.environ["DATABASE_URL"])
    for field in fields:
        rows = monthly_ratio(engine, field)
        if rows:
            report(field, rows)


if __name__ == "__main__":
    main()
