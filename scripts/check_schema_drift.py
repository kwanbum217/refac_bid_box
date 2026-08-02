"""
scripts/check_schema_drift.py

SQLAlchemy 모델과 실제 DB 스키마의 차이를 읽기 전용으로 보고합니다.

DDL 을 실행하지 않습니다. `alembic revision --autogenerate` 를 돌리기 전에 무엇이
바뀌려 하는지 먼저 확인하는 용도이며, 원본 Django 스키마 대비 이식 누락을 찾는
데도 씁니다.

실행:
    make migrate-check
"""

import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from src.app.core.config import settings  # noqa: E402
from src.app.core.db import Base  # noqa: E402
import src.app.models  # noqa: E402,F401

# 주석은 Django 가 DB 에 기록하지 않으므로 항상 차이로 잡힙니다. 스키마 의미에
# 영향이 없어 기본 보고에서 제외합니다.
COSMETIC_KINDS = {"modify_comment"}

# 인덱스는 Django 자동 명명(`bid_results_category_981358ae`)과 SQLAlchemy 명명
# (`ix_bid_results_category`)이 달라 이름만 다른 동일 인덱스가 대량으로 잡힙니다.
NAMING_KINDS = {"add_index", "remove_index"}


def _table_of(item) -> str:
    kind = item[0]
    if kind in ("add_table", "remove_table"):
        return item[1].name
    if kind in ("add_column", "remove_column"):
        return item[2]
    if kind in ("add_index", "remove_index"):
        return item[1].table.name
    if kind in ("add_constraint", "remove_constraint", "add_fk", "remove_fk"):
        return getattr(item[1].table, "name", "?")
    if kind.startswith("modify_"):
        return item[2]
    return "?"


def _describe(item) -> str:
    kind = item[0]
    if kind in ("add_column", "remove_column"):
        return f"{kind}: {item[3].name} ({item[3].type})"
    if kind.startswith("modify_"):
        return f"{kind}: {item[3]}  DB={item[5]!r} -> MODEL={item[6]!r}"
    if kind in (
        "add_index",
        "remove_index",
        "add_constraint",
        "remove_constraint",
        "add_fk",
        "remove_fk",
    ):
        return f"{kind}: {getattr(item[1], 'name', '?')}"
    if kind in ("add_table", "remove_table"):
        return kind
    return str(kind)


def main() -> int:
    managed = frozenset(Base.metadata.tables)
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, type_, reflected, compare_to: (
                    name in managed if type_ == "table" else True
                ),
            },
        )
        raw = compare_metadata(context, Base.metadata)

    items = []
    for entry in raw:
        items.extend(entry if isinstance(entry, list) else [entry])
    items = [it for it in items if _table_of(it) in managed]

    substantive = [it for it in items if it[0] not in COSMETIC_KINDS | NAMING_KINDS]
    naming = [it for it in items if it[0] in NAMING_KINDS]
    cosmetic = [it for it in items if it[0] in COSMETIC_KINDS]

    # DB_HOST/DB_PORT 는 DATABASE_URL 과 어긋날 수 있으므로 실제 접속에 쓰인 값을 씁니다.
    url = engine.url
    print(f"대상 DB: {url.host}:{url.port}/{url.database} ({engine.dialect.name})")
    print(f"관리 테이블: {len(managed)}개")
    print()
    print(f"실질 차이   : {len(substantive)}건")
    print(f"인덱스 명명 : {len(naming)}건 (기능 동일, 이름만 다름)")
    print(f"주석        : {len(cosmetic)}건 (스키마 의미 없음)")

    if not substantive:
        print()
        print("모델과 실제 스키마가 일치합니다.")
        return 0

    grouped = defaultdict(list)
    for it in substantive:
        grouped[_table_of(it)].append(it)

    print()
    print("--- 실질 차이 상세 ---")
    for table in sorted(grouped):
        print(f"[{table}]")
        for it in grouped[table]:
            print(f"    {_describe(it)}")

    print()
    print("주의: 위 차이를 autogenerate 로 그대로 적용하면 운영 스키마가 바뀝니다.")
    print("      LONGTEXT -> TEXT 변경은 기존 데이터를 잘라낼 수 있습니다.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
