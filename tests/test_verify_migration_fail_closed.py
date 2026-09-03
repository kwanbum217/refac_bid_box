"""G1 기준선 fail-closed 및 ORM 테이블 집합 검증 테스트."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from scripts import verify_migration as verifier


@pytest.fixture
def sample_engine(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "test_users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String(50), nullable=False),
    )
    Table(
        "test_posts",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer, nullable=False),
    )
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_schema_baseline_missing_does_not_write(tmp_path, sample_engine):
    baseline_path = tmp_path / "schema.json"

    ok, message = verifier.verify_schema_signature(
        engine=sample_engine,
        baseline_path=baseline_path,
        auto_save_baseline=True,
        tables=("test_users", "test_posts"),
    )

    assert ok is False
    assert "기준 서명 파일 없음" in message
    assert not baseline_path.exists()


def test_schema_baseline_without_metadata_is_rejected(tmp_path, sample_engine):
    baseline_path = tmp_path / "schema.json"
    signature = verifier.generate_schema_signature(
        sample_engine,
        tables=("test_users", "test_posts"),
    )
    signature.pop("metadata")
    baseline_path.write_text(json.dumps(signature), encoding="utf-8")

    ok, message = verifier.verify_schema_signature(
        engine=sample_engine,
        baseline_path=baseline_path,
        tables=("test_users", "test_posts"),
    )

    assert ok is False
    assert "메타데이터 누락" in message


def test_schema_signature_uses_orm_and_db_table_union(monkeypatch):
    class FakeInspector:
        def get_table_names(self):
            return ["bid_results", "db_only_table"]

        def get_columns(self, table_name):
            return [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                }
            ]

        def get_pk_constraint(self, table_name):
            return {"constrained_columns": ["id"]}

        def get_foreign_keys(self, table_name):
            return []

        def get_indexes(self, table_name):
            return []

    monkeypatch.setattr(
        verifier,
        "get_orm_table_names",
        lambda: {"bid_results", "bid_ranking_snapshots", "institution_win_rate_stats"},
    )
    signature = verifier.generate_schema_signature(FakeInspector())

    assert set(signature["orm_tables"]) == {
        "bid_results",
        "bid_ranking_snapshots",
        "institution_win_rate_stats",
    }
    assert signature["database_tables"] == ["bid_results", "db_only_table"]
    assert signature["tables"]["bid_ranking_snapshots"] is None
    assert signature["tables"]["institution_win_rate_stats"] is None
    assert "db_only_table" in signature["tables"]
    assert set(signature["metadata"]) == {
        "generated_at",
        "database_identifier",
        "generated_by",
        "tool_version",
        "git_head",
    }


def test_default_orm_table_set_contains_all_known_tables():
    orm_tables = verifier.get_orm_table_names()

    assert "bid_ranking_snapshots" in orm_tables
    assert "institution_win_rate_stats" in orm_tables


def test_reconciliation_baseline_missing_is_fail_closed(tmp_path):
    baseline_path = tmp_path / "reconciliation.json"

    def should_not_open_session():
        raise AssertionError("기준선 부재 시 DB 세션을 열면 안 됩니다")

    ok, message = verifier.verify_reconciliation(
        session_factory=should_not_open_session,
        baseline_path=baseline_path,
        auto_save_baseline=True,
    )

    assert ok is False
    assert "기준선 파일 없음" in message
    assert not baseline_path.exists()


def test_reconciliation_baseline_without_metadata_is_rejected(tmp_path):
    baseline_path = tmp_path / "reconciliation.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "tables": {
                    "bid_announcements": 1,
                    "bid_results": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    def should_not_open_session():
        raise AssertionError("메타데이터 오류 시 DB 세션을 열면 안 됩니다")

    ok, message = verifier.verify_reconciliation(
        session_factory=should_not_open_session,
        baseline_path=baseline_path,
    )

    assert ok is False
    assert "메타데이터 누락" in message
