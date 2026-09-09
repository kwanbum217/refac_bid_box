"""적격심사 정량평가 프로필, 스냅샷, 증빙 메타데이터 신규 테이블 추가

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. bid_evaluation_profiles 테이블 생성
    op.create_table('bid_evaluation_profiles',
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "framework",
            sa.String(length=50),
            nullable=False,
            server_default="servc_qualification",
        ),
        sa.Column(
            "input_schema_version",
            sa.String(length=20),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["accounts_customuser.id"],
            name="fk_bid_eval_profiles_user_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_bid_eval_profiles_user_name"),
    )
    op.create_index(
        "ix_bid_eval_profiles_user_id",
        "bid_evaluation_profiles",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_profiles_user_created",
        "bid_evaluation_profiles",
        ["user_id", "created_at"],
        unique=False,
    )

    # 2. bid_evaluation_snapshots 테이블 생성
    op.create_table('bid_evaluation_snapshots',
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("bid_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bid_id"],
            ["bid_announcements.id"],
            name="fk_bid_eval_snapshots_bid_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["accounts_customuser.id"],
            name="fk_bid_eval_snapshots_user_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bid_eval_snapshots_user_id",
        "bid_evaluation_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_snapshots_bid_id",
        "bid_evaluation_snapshots",
        ["bid_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_snapshots_user_bid",
        "bid_evaluation_snapshots",
        ["user_id", "bid_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_snapshots_rule_id",
        "bid_evaluation_snapshots",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_snapshots_created_at",
        "bid_evaluation_snapshots",
        ["created_at"],
        unique=False,
    )

    # 3. bid_evaluation_evidence 테이블 생성
    op.create_table('bid_evaluation_evidence',
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "item_code",
            sa.String(length=50),
            nullable=False,
            comment="평가 항목 코드 (performance/management/labor_plan/credibility)",
        ),
        sa.Column(
            "issuer",
            sa.String(length=100),
            nullable=False,
            comment="발급기관명",
        ),
        sa.Column(
            "reference_no",
            sa.String(length=100),
            nullable=False,
            comment="문서/증빙 일련번호",
        ),
        sa.Column(
            "valid_from",
            sa.Date(),
            nullable=True,
            comment="유효기간 시작일",
        ),
        sa.Column(
            "valid_to",
            sa.Date(),
            nullable=True,
            comment="유효기간 만료일",
        ),
        sa.Column(
            "note",
            sa.String(length=500),
            nullable=True,
            comment="비고 및 메모",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["bid_evaluation_snapshots.id"],
            name="fk_bid_eval_evidence_snapshot_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bid_eval_evidence_snapshot_id",
        "bid_evaluation_evidence",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_evidence_item_code",
        "bid_evaluation_evidence",
        ["item_code"],
        unique=False,
    )
    op.create_index(
        "ix_bid_eval_evidence_snap_item",
        "bid_evaluation_evidence",
        ["snapshot_id", "item_code"],
        unique=False,
    )


def downgrade() -> None:
    # 3. bid_evaluation_evidence 역순 삭제
    op.drop_index("ix_bid_eval_evidence_snap_item", table_name="bid_evaluation_evidence")
    op.drop_index("ix_bid_eval_evidence_item_code", table_name="bid_evaluation_evidence")
    op.drop_index("ix_bid_eval_evidence_snapshot_id", table_name="bid_evaluation_evidence")
    op.drop_table("bid_evaluation_evidence")

    # 2. bid_evaluation_snapshots 역순 삭제
    op.drop_index("ix_bid_eval_snapshots_created_at", table_name="bid_evaluation_snapshots")
    op.drop_index("ix_bid_eval_snapshots_rule_id", table_name="bid_evaluation_snapshots")
    op.drop_index("ix_bid_eval_snapshots_user_bid", table_name="bid_evaluation_snapshots")
    op.drop_index("ix_bid_eval_snapshots_bid_id", table_name="bid_evaluation_snapshots")
    op.drop_index("ix_bid_eval_snapshots_user_id", table_name="bid_evaluation_snapshots")
    op.drop_table("bid_evaluation_snapshots")

    # 1. bid_evaluation_profiles 역순 삭제
    op.drop_index("ix_bid_eval_profiles_user_created", table_name="bid_evaluation_profiles")
    op.drop_index("ix_bid_eval_profiles_user_id", table_name="bid_evaluation_profiles")
    op.drop_table("bid_evaluation_profiles")
