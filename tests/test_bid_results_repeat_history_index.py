"""
tests/test_bid_results_repeat_history_index.py

낙찰 재발주 이력 커버링 인덱스(ix_bid_results_repeat_hist) 계약 검증.

predict-price 첫 요청의 재발주 이력 조회(src/ml/repeat_history.py lookup_repeat_history)는
dminstt_nm·category 등치 조건에 rl_openg_dt 내림차순 정렬과 LIMIT 5000 을 쓰고 SELECT 열로
bid_ntce_nm, sucsf_bid_rate, rl_openg_dt 를 읽습니다. 기존 ix_bid_results_inst_cat_stats 는
bid_ntce_nm 이 없어 행마다 본문을 랜덤 조회하고 filesort 합니다. (dminstt_nm, category,
rl_openg_dt, sucsf_bid_rate, bid_ntce_nm) 커버링 인덱스를 둡니다. MySQL 에서는 조회와 수집을
막지 않는 온라인 DDL 이어야 하고 리비전은 멱등이어야 합니다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql

from src.app.core.db import Base
from src.app.models.bids import BidResult
from src.ml.repeat_history import lookup_repeat_history

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "a6b7c8d9e0f1"
INDEX_NAME = "ix_bid_results_repeat_hist"
COLUMNS = ("dminstt_nm", "category", "rl_openg_dt", "sucsf_bid_rate", "bid_ntce_nm")
MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "versions"
    / "a6b7c8d9e0f1_add_bid_results_repeat_history_covering_index.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("repeat_hist_index_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_columns() -> tuple[str, ...]:
    indexes = {index.name: index for index in BidResult.__table__.indexes}
    return tuple(column.name for column in indexes[INDEX_NAME].columns)


class _RecordingSession:
    """lookup_repeat_history 가 실제로 내보낸 SELECT 문과 파라미터를 붙잡습니다."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def execute(self, statement: Any):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])


def _recorded_lookup_statement():
    session = _RecordingSession()
    features = {
        "dminstt_nm": "경기도 용인시",
        "bid_ntce_nm": "2026학년도 창남초등학교 통학버스 임차 용역 입찰 공고",
        "category": "Servc",
        "openg_dt": "2026-06-01T10:00:00",
    }
    # 이력이 없으면 None 을 돌려주는 계약은 그대로이고, 그 전에 SELECT 를 한 번 내보냅니다.
    assert lookup_repeat_history(features, session) is None
    assert len(session.statements) == 1
    return session.statements[0]


def _compiled_lookup_sql() -> str:
    statement = _recorded_lookup_statement()
    return str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))


def test_revision_follows_bid_announcements_institution_date_index():
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))

    assert script.get_revision(REVISION).down_revision == "f5a6b7c8d9e0"
    assert len(script.get_heads()) == 1
    assert script.get_current_head() == REVISION


def test_model_declares_repeat_history_index_columns():
    indexes = {index.name: index for index in BidResult.__table__.indexes}

    assert tuple(column.name for column in indexes[INDEX_NAME].columns) == COLUMNS


def test_mysql_upgrade_uses_online_ddl(monkeypatch):
    migration = _load_migration()
    executed: list[str] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")),
        execute=executed.append,
        create_index=lambda *args, **kwargs: pytest.fail("MySQL 에서는 온라인 DDL 을 써야 합니다"),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "_has_index", lambda: False)

    migration.upgrade()

    assert executed == [
        "ALTER TABLE bid_results ADD INDEX ix_bid_results_repeat_hist "
        "(dminstt_nm, category, rl_openg_dt, sucsf_bid_rate, bid_ntce_nm), "
        "ALGORITHM=INPLACE, LOCK=NONE"
    ]


def test_index_covers_lookup_repeat_history_query_columns():
    """WHERE 등치·ORDER BY·SELECT 열이 전부 인덱스에 있어야 본문을 읽지 않습니다."""
    compiled = _compiled_lookup_sql()
    index_columns = _index_columns()

    for column in COLUMNS:
        assert column in index_columns, f"{column} 이 커버링 인덱스 열에 없습니다"
        assert f"bid_results.{column}" in compiled, f"{column} 이 조회 쿼리에 없습니다"

    # 등치 두 열 뒤에 정렬 키가 이어져야 역스캔이 filesort 를 대체합니다.
    assert index_columns[:3] == ("dminstt_nm", "category", "rl_openg_dt")
    assert re.search(r"ORDER BY\s+bid_results\.rl_openg_dt\s+DESC", compiled)


def test_lookup_repeat_history_where_clause_is_unchanged():
    """커버링 인덱스는 조회 조건을 바꾸지 않습니다. WHERE·LIMIT 계약을 고정합니다."""
    compiled = _compiled_lookup_sql()

    assert "bid_results.dminstt_nm = " in compiled
    assert "bid_results.category = " in compiled
    assert "bid_results.sucsf_bid_rate IS NOT NULL" in compiled
    assert "bid_results.sucsf_bid_rate > " in compiled
    assert "bid_results.sucsf_bid_rate < " in compiled
    assert "LIMIT 5000" in compiled


def test_upgrade_is_idempotent_and_downgrade_removes_index(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.tables["bid_results"].create(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        operations.drop_index(INDEX_NAME, table_name="bid_results")

        migration.upgrade()
        migration.upgrade()
        assert INDEX_NAME in {
            index["name"] for index in inspect(connection).get_indexes("bid_results")
        }

        migration.downgrade()
        assert INDEX_NAME not in {
            index["name"] for index in inspect(connection).get_indexes("bid_results")
        }
