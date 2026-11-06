"""
tests/test_announcement_regime_model.py

`bid_announcement_regime` ORM 모델과 Alembic 마이그레이션 계약 검증.

SQLite 인메모리에서만 돌며 운영 DB·MySQL·Docker 를 쓰지 않습니다. 마이그레이션은
파일을 직접 읽어 리비전과 `utf8mb4_unicode_ci` 옵션을 확인하고, 기존 테이블은
건드리지 않는지 upgrade/downgrade 본문으로 확인합니다.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.core.db import Base
from src.app.models.announcement_regime import (
    REGIME_STATUS_CLASSIFIED,
    REGIME_STATUS_FAILED,
    REGIME_STATUS_NO_ATTACHMENT,
    BidAnnouncementRegime,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "b4e5f6a7c8d9"
PREVIOUS_REVISION = "a9b8c7d6e5f4"
TABLE_NAME = "bid_announcement_regime"
INDEX_NAME = "ix_bid_announcement_regime_regime"
UNIQUE_NAME = "uq_bid_announcement_regime"
MIGRATION_PATH = (
    PROJECT_ROOT / "migrations" / "versions" / f"{REVISION}_add_bid_announcement_regime.py"
)


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("announcement_regime_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[BidAnnouncementRegime.__table__])
    try:
        yield engine
    finally:
        engine.dispose()


def _regime_row(**overrides: Any) -> BidAnnouncementRegime:
    values: dict[str, Any] = {
        "bid_ntce_no": "R26BK01506722",
        "bid_ntce_ord": "000",
        "category": "Servc",
        "regime": "MOIS_OTHER",
        "evidence": "사업수행능력평가(P.Q)를 하지 않는 기술용역 4. 추정가격 2억원 미만 1억원 이상인 평가기준",
        "matched_rules": "R12",
        "source_files": [{"name": "공고문.hwp", "sha256": "a" * 64}],
        "status": "CLASSIFIED",
        "error": None,
        "classifier_version": "1.0.0",
        "classified_at": datetime(2026, 11, 6, 0, 0, 0),
    }
    values.update(overrides)
    return BidAnnouncementRegime(**values)


def test_status_constants() -> None:
    assert (
        REGIME_STATUS_CLASSIFIED,
        REGIME_STATUS_FAILED,
        REGIME_STATUS_NO_ATTACHMENT,
    ) == ("CLASSIFIED", "FAILED", "NO_ATTACHMENT")


def test_model_columns_and_keys() -> None:
    columns = {column.name: column for column in BidAnnouncementRegime.__table__.columns}

    assert set(columns) == {
        "id",
        "bid_ntce_no",
        "bid_ntce_ord",
        "category",
        "regime",
        "evidence",
        "matched_rules",
        "source_files",
        "status",
        "error",
        "classifier_version",
        "classified_at",
    }
    assert columns["bid_ntce_no"].type.length == 40
    assert columns["bid_ntce_ord"].type.length == 10
    assert columns["category"].type.length == 20
    assert columns["regime"].type.length == 30
    assert columns["evidence"].type.length == 255
    assert columns["matched_rules"].type.length == 255
    assert columns["status"].type.length == 20
    assert columns["classifier_version"].type.length == 20
    assert columns["evidence"].nullable is True
    assert columns["matched_rules"].nullable is True
    assert columns["source_files"].nullable is True
    assert columns["error"].nullable is True

    unique = next(
        constraint
        for constraint in BidAnnouncementRegime.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint) and constraint.name == UNIQUE_NAME
    )
    assert tuple(column.name for column in unique.columns) == (
        "bid_ntce_no",
        "bid_ntce_ord",
        "category",
    )

    indexes = {index.name: index for index in BidAnnouncementRegime.__table__.indexes}
    assert tuple(column.name for column in indexes[INDEX_NAME].columns) == ("regime",)


def test_insert_and_query(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(_regime_row())
        session.commit()

    with Session(engine) as session:
        row = session.scalars(select(BidAnnouncementRegime)).one()

    assert row.bid_ntce_no == "R26BK01506722"
    assert row.bid_ntce_ord == "000"
    assert row.category == "Servc"
    assert row.regime == "MOIS_OTHER"
    assert row.matched_rules == "R12"
    assert row.source_files == [{"name": "공고문.hwp", "sha256": "a" * 64}]
    assert row.status == REGIME_STATUS_CLASSIFIED
    assert row.classified_at == datetime(2026, 11, 6, 0, 0, 0)


def test_unique_key_rejects_duplicate(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(_regime_row())
        session.commit()
        session.add(_regime_row())
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_unique_key_allows_other_category(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(_regime_row())
        session.add(_regime_row(category="Thng", status=REGIME_STATUS_FAILED, error="원문 없음"))
        session.commit()

        assert len(session.scalars(select(BidAnnouncementRegime)).all()) == 2


def test_migration_revision_follows_current_head() -> None:
    migration = _load_migration()

    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION

    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    assert len(script.get_heads()) == 1
    head = script.get_current_head()
    assert head is not None
    assert REVISION in {rev.revision for rev in script.iterate_revisions(head, "base")}


def test_migration_declares_utf8mb4_unicode_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    captured: dict[str, Any] = {}
    created_indexes: list[tuple[str, str, list[str]]] = []

    def fake_create_table(name: str, *columns: Any, **options: Any) -> None:
        captured["name"] = name
        captured["options"] = options

    def fake_create_index(
        name: str, table_name: str, columns: list[str], unique: bool = False
    ) -> None:
        created_indexes.append((name, table_name, list(columns)))

    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(create_table=fake_create_table, create_index=fake_create_index),
    )
    monkeypatch.setattr(migration, "_existing_tables", lambda: set())

    migration.upgrade()

    assert captured["name"] == TABLE_NAME
    assert captured["options"]["mysql_charset"] == "utf8mb4"
    assert captured["options"]["mysql_collate"] == "utf8mb4_unicode_ci"
    assert created_indexes == [(INDEX_NAME, TABLE_NAME, ["regime"])]


def test_upgrade_and_downgrade_are_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            monkeypatch.setattr(migration, "op", operations)

            migration.upgrade()
            migration.upgrade()
            assert TABLE_NAME in set(inspect(connection).get_table_names())
            index_names = {index["name"] for index in inspect(connection).get_indexes(TABLE_NAME)}
            assert INDEX_NAME in index_names
            unique = next(
                constraint
                for constraint in inspect(connection).get_unique_constraints(TABLE_NAME)
                if constraint["name"] == UNIQUE_NAME
            )
            assert unique["column_names"] == ["bid_ntce_no", "bid_ntce_ord", "category"]

            migration.downgrade()
            assert TABLE_NAME not in set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
