"""
tests/test_bid_results_institution_date_index.py

낙찰 기관명-개찰일시 복합 인덱스(ix_bid_results_inst_dt) 계약 검증.

공고 상세의 기관 과거 낙찰 5건 조회는 dminstt_nm 등치 조건에 rl_openg_dt 내림차순 정렬을 씁니다.
기관 단일 인덱스(bid_results_dminstt_nm_1b809760)만으로는 해당 기관의 모든 행을 읽고 filesort
하므로 콜드 상태에서 7초를 넘습니다. (dminstt_nm, rl_openg_dt) 복합 인덱스를 둡니다. MySQL 에서는
조회와 수집을 막지 않는 온라인 DDL 이어야 하고 리비전은 멱등이어야 합니다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from src.app.core.db import Base
from src.app.models.bids import BidResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "e4f5a6b7c8d9"
INDEX_NAME = "ix_bid_results_inst_dt"
COLUMNS = ("dminstt_nm", "rl_openg_dt")
MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "versions"
    / "e4f5a6b7c8d9_add_bid_results_institution_date_index.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("results_date_index_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_follows_prearng_prices():
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))

    assert script.get_revision(REVISION).down_revision == "d3e4f5a6b7c8"
    assert len(script.get_heads()) == 1


def test_model_declares_date_index_columns():
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
        "ALTER TABLE bid_results ADD INDEX ix_bid_results_inst_dt "
        "(dminstt_nm, rl_openg_dt), ALGORITHM=INPLACE, LOCK=NONE"
    ]


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
