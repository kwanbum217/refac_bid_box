"""
tests/test_bid_ann_institution_covering_index.py

공고 기관명 커버링 인덱스(ix_bid_ann_inst_cat_ntce) 계약 검증.

RAG 정형 검색의 기관명 조건 집계가 공고 본문을 읽지 않도록 (dminstt_nm, category, bid_ntce_nm)
인덱스를 둡니다. MySQL 에서는 조회와 수집을 막지 않는 온라인 DDL 이어야 하고, 리비전은 멱등이어야
합니다(docs/analysis/rag_coldsql_root_cause_20260913.md 8.3 절).
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
from src.app.models.bids import BidAnnouncement

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "afc72b545c6a"
INDEX_NAME = "ix_bid_ann_inst_cat_ntce"
COLUMNS = ("dminstt_nm", "category", "bid_ntce_nm")
MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "versions"
    / "afc72b545c6a_add_bid_announcements_institution_covering_index.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("covering_index_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_names(engine) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes("bid_announcements")}


def test_revision_is_single_head_after_compare_stats_snapshots():
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))

    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == "b2c3d4e5f6a7"


def test_model_declares_covering_index_columns():
    indexes = {index.name: index for index in BidAnnouncement.__table__.indexes}

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
        "ALTER TABLE bid_announcements ADD INDEX ix_bid_ann_inst_cat_ntce "
        "(dminstt_nm, category, bid_ntce_nm), ALGORITHM=INPLACE, LOCK=NONE"
    ]


def test_upgrade_is_idempotent_and_downgrade_removes_index(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.tables["bid_announcements"].create(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        operations.drop_index(INDEX_NAME, table_name="bid_announcements")

        migration.upgrade()
        migration.upgrade()
        assert INDEX_NAME in {
            index["name"] for index in inspect(connection).get_indexes("bid_announcements")
        }

        migration.downgrade()
        assert INDEX_NAME not in {
            index["name"] for index in inspect(connection).get_indexes("bid_announcements")
        }
