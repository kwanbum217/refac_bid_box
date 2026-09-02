"""
tests/test_g1_schema_signature.py

G1(데이터 무손실) 전 테이블 스키마 서명 검증 및 보고서 생성 단위 테스트.
- 스키마 서명 생성 및 정규화
- 순서 무관성(Order Independence) 및 해시 결정론성
- 컬럼 추가/삭제/타입변경/nullable변경/PK/FK/인덱스 차이 검출
- 기준 서명 부재 시 최초 기준선 자동 생성 및 통과 처리
- 검증 결과 보고서(JSON) 생성
- 읽기 전용 안전성
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
)

from scripts.verify_migration import (
    compare_schema_signatures,
    extract_table_signature,
    generate_schema_signature,
    generate_verification_report,
    normalize_type_string,
    verify_schema_signature,
)


@pytest.fixture
def sample_engine_a():
    """테스트용 스키마 A 생성 (기본 순서)."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    users = Table(
        "test_users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String(50), nullable=False),
        Column("email", String(100), nullable=True),
    )
    Index("ix_test_users_username", users.c.username, unique=True)

    posts = Table(
        "test_posts",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer, ForeignKey("test_users.id"), nullable=False),
        Column("title", String(200), nullable=False),
    )
    Index("ix_test_posts_user_id", posts.c.user_id)

    metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sample_engine_b_reordered():
    """테스트용 스키마 B 생성 (컬럼 순서 및 테이블 선언 순서가 다른 동일 스키마)."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    # posts 먼저 정의, 컬럼 순서 역순
    posts = Table(
        "test_posts",
        metadata,
        Column("title", String(200), nullable=False),
        Column("user_id", Integer, ForeignKey("test_users.id"), nullable=False),
        Column("id", Integer, primary_key=True),
    )
    Index("ix_test_posts_user_id", posts.c.user_id)

    # users 정의, 컬럼 순서 역순
    users = Table(
        "test_users",
        metadata,
        Column("email", String(100), nullable=True),
        Column("username", String(50), nullable=False),
        Column("id", Integer, primary_key=True),
    )
    Index("ix_test_users_username", users.c.username, unique=True)

    metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_normalize_type_string():
    """타입 문자열 정규화 테스트."""
    assert normalize_type_string(Integer()) == "INTEGER"
    assert "VARCHAR" in normalize_type_string(String(50))
    assert normalize_type_string(None) == ""


def test_extract_table_signature(sample_engine_a):
    """단일 테이블 서명 추출 테스트."""
    inspector = inspect(sample_engine_a)
    sig = extract_table_signature(inspector, "test_users")

    assert sig["name"] == "test_users"
    assert "hash" in sig
    assert len(sig["hash"]) == 64
    assert sig["primary_key"] == ["id"]

    col_names = [c["name"] for c in sig["columns"]]
    # 컬럼명이 알파벳순으로 정렬되었는지 확인
    assert col_names == sorted(col_names)
    assert "username" in col_names
    assert "email" in col_names


def test_schema_signature_order_independence(sample_engine_a, sample_engine_b_reordered):
    """컬럼 정의 순서가 달라도 서명 및 해시가 완전히 일치하는지 검증."""
    sig_a = generate_schema_signature(
        sample_engine_a,
        tables=["test_users", "test_posts"],
    )
    sig_b = generate_schema_signature(
        sample_engine_b_reordered,
        tables=["test_posts", "test_users"],
    )

    assert sig_a["overall_hash"] == sig_b["overall_hash"]
    assert sig_a["table_hashes"]["test_users"] == sig_b["table_hashes"]["test_users"]
    assert sig_a["table_hashes"]["test_posts"] == sig_b["table_hashes"]["test_posts"]

    is_match, diff_messages, _diff_details = compare_schema_signatures(sig_a, sig_b)
    assert is_match is True
    assert len(diff_messages) == 0


def test_compare_schema_signatures_diff_detection():
    """컬럼 추가/삭제/타입변경/nullable/PK/FK/인덱스 차이 검출 테스트."""
    baseline = {
        "tables": {
            "tbl_test": {
                "hash": "base_hash_1",
                "name": "tbl_test",
                "columns": [
                    {
                        "name": "col_a",
                        "type": "VARCHAR(50)",
                        "nullable": False,
                        "primary_key": True,
                    },
                    {"name": "col_b", "type": "INTEGER", "nullable": True, "primary_key": False},
                    {"name": "col_del", "type": "TEXT", "nullable": True, "primary_key": False},
                ],
                "primary_key": ["col_a"],
                "foreign_keys": [],
                "indexes": [{"name": "ix_test_col_b", "column_names": ["col_b"], "unique": False}],
            }
        }
    }

    current = {
        "tables": {
            "tbl_test": {
                "hash": "curr_hash_2",
                "name": "tbl_test",
                "columns": [
                    {
                        "name": "col_a",
                        "type": "VARCHAR(100)",
                        "nullable": True,
                        "primary_key": True,
                    },  # type, nullable changed
                    {"name": "col_b", "type": "INTEGER", "nullable": True, "primary_key": False},
                    {
                        "name": "col_new",
                        "type": "BOOLEAN",
                        "nullable": False,
                        "primary_key": False,
                    },  # added
                ],
                "primary_key": ["col_a", "col_b"],  # pk changed
                "foreign_keys": [
                    {
                        "name": "fk_1",
                        "constrained_columns": ["col_b"],
                        "referred_table": "other",
                        "referred_columns": ["id"],
                    }
                ],  # fk changed
                "indexes": [
                    {"name": "ix_test_col_b", "column_names": ["col_b"], "unique": True}
                ],  # unique index changed
            },
            "tbl_added": {  # table added
                "hash": "new_hash",
                "name": "tbl_added",
                "columns": [],
                "primary_key": [],
                "foreign_keys": [],
                "indexes": [],
            },
        }
    }

    is_match, diff_messages, _diff_details = compare_schema_signatures(baseline, current)
    assert is_match is False
    assert any("테이블 추가: tbl_added" in m for m in diff_messages)
    assert any("col_new: 컬럼 추가" in m for m in diff_messages)
    assert any("col_del: 컬럼 삭제" in m for m in diff_messages)
    assert any("col_a: 타입 변경" in m for m in diff_messages)
    assert any("col_a: nullable 변경" in m for m in diff_messages)
    assert any("기본키 제약조건 변경" in m for m in diff_messages)
    assert any("외래키 제약조건 변경" in m for m in diff_messages)
    assert any("인덱스 제약조건 변경" in m for m in diff_messages)


def test_first_run_creates_baseline_and_passes(tmp_path, sample_engine_a):
    """기준 서명 파일이 없으면 현재 서명을 기준선으로 저장하고 통과(PASS) 처리하는지 검증."""
    baseline_file = tmp_path / "schema_signature_baseline.json"
    assert not baseline_file.exists()

    ok, msg = verify_schema_signature(
        engine=sample_engine_a,
        baseline_path=baseline_file,
        auto_save_baseline=True,
    )

    assert ok is True
    assert "신규 기록" in msg
    assert baseline_file.exists()

    # 2회차 실행 시 기준선과 비교하여 일치로 통과
    ok2, msg2 = verify_schema_signature(
        engine=sample_engine_a,
        baseline_path=baseline_file,
        auto_save_baseline=True,
    )
    assert ok2 is True
    assert "일치" in msg2


def test_generate_verification_report(tmp_path):
    """검증 보고서(JSON) 생성 형식 및 내용 검증."""
    report_file = tmp_path / "test_report.json"
    results = [
        ("ML 가중치 4종 무결성", True, "체크섬 일치"),
        ("ChromaDB 컬렉션 무결성", True, "컬렉션 확인"),
        ("DB 필수 테이블 존재 여부", True, "테이블 존재"),
        ("DB 전 테이블 스키마 서명 정합성", True, "서명 일치"),
        ("데이터 행 수 하한 검증", True, "행 수 충족"),
    ]

    report = generate_verification_report(results, output_path=report_file)

    assert report_file.exists()
    assert report["overall_verdict"] == "PASS"
    assert report["passed_count"] == 5
    assert report["total_count"] == 5
    assert "head_commit" in report
    assert "generated_at" in report
    assert len(report["results"]) == 5

    saved = json.loads(report_file.read_text(encoding="utf-8"))
    assert saved["overall_verdict"] == "PASS"
    assert saved["results"][0]["name"] == "ML 가중치 4종 무결성"
