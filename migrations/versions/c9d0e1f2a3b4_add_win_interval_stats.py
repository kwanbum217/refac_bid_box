"""add win interval stats

Revision ID: c9d0e1f2a3b4
Revises: b8d9e0f1a2b3
Create Date: 2026-11-25 00:00:00.000000

용역 적격 낙찰의 공고별 승리 구간 중앙값 분포를 하한율별로 사전 집계하는
`win_interval_stats` 를 추가합니다. 기존 테이블·컬럼은 변경하지 않고 신규
테이블 1개만 만듭니다(G1).

본 리비전은 멱등입니다. 테이블이 이미 있으면 건너뛰며, downgrade 는 테이블이
있을 때만 지웁니다. 운영 DB 적용은 별도 승인 절차를 따르며, 신규 DB 는 이
리비전이 테이블을 만듭니다. 두 경로의 결과가 같아야 합니다.

문자열 컬럼은 테이블 수준 `utf8mb4_unicode_ci` 로 명시합니다. 운영 스키마
기본 콜레이션이 `utf8mb4_0900_ai_ci` 라 생략하면 다른 테이블과 조인할 때
콜레이션 충돌이 납니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "win_interval_stats"
INDEX_NAME = "ix_win_interval_lookup"
UNIQUE_NAME = "uq_win_interval_stats"

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)}


def upgrade() -> None:
    if TABLE_NAME in _existing_tables():
        return
    op.create_table('win_interval_stats',
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("institution_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column("lwlt_rate", sa.Numeric(precision=7, scale=3), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.BigInteger(), nullable=False),
        sa.Column("p05", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p10", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p15", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p20", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p25", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p30", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p35", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p40", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p45", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p50", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p55", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p60", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p65", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p70", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p75", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p80", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p85", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p90", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("p95", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("rebuilt_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "institution_name",
            "category",
            "lwlt_rate",
            "window_days",
            name=UNIQUE_NAME,
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_win_interval_lookup",
        "win_interval_stats",
        ["scope", "institution_name", "category", "lwlt_rate"],
        unique=False,
    )


def downgrade() -> None:
    if TABLE_NAME not in _existing_tables():
        return
    if INDEX_NAME in _existing_indexes():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
