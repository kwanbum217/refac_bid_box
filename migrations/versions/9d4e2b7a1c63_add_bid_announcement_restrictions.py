"""입찰공고 면허제한정보 및 참가가능지역 신규 테이블 추가

Revision ID: 9d4e2b7a1c63
Revises: c38ebe417cf3
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4e2b7a1c63"
down_revision: str | Sequence[str] | None = "c38ebe417cf3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. bid_announcement_license_limits 테이블 생성
    op.create_table('bid_announcement_license_limits',
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("bid_ntce_no", sa.String(length=50), nullable=False),
        sa.Column(
            "bid_ntce_ord",
            sa.String(length=10),
            server_default="000",
            nullable=False,
        ),
        sa.Column(
            "lmt_grp_no",
            sa.String(length=20),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "lmt_sno",
            sa.String(length=20),
            server_default="1",
            nullable=False,
        ),
        sa.Column("lcns_lmt_nm", sa.String(length=500), nullable=True),
        sa.Column("permsn_indstryty_list", sa.Text(), nullable=True),
        sa.Column("indstryty_mfrc_fld_list", sa.Text(), nullable=True),
        sa.Column("rgst_dt", sa.DateTime(), nullable=True),
        sa.Column("bsns_div_nm", sa.String(length=50), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "lmt_grp_no",
            "lmt_sno",
            name="uq_bid_ann_lic_limits_ntce_grp_sno",
        ),
    )
    op.create_index(
        "ix_bid_ann_lic_limits_ntce",
        "bid_announcement_license_limits",
        ["bid_ntce_no", "bid_ntce_ord"],
        unique=False,
    )
    op.create_index(
        "ix_bid_ann_lic_limits_collected",
        "bid_announcement_license_limits",
        ["collected_at"],
        unique=False,
    )

    # 2. bid_announcement_participation_regions 테이블 생성
    op.create_table('bid_announcement_participation_regions',
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("bid_ntce_no", sa.String(length=50), nullable=False),
        sa.Column(
            "bid_ntce_ord",
            sa.String(length=10),
            server_default="000",
            nullable=False,
        ),
        sa.Column(
            "lmt_sno",
            sa.String(length=20),
            server_default="1",
            nullable=False,
        ),
        sa.Column("prtcpt_psbl_rgn_nm", sa.String(length=200), nullable=True),
        sa.Column("rgst_dt", sa.DateTime(), nullable=True),
        sa.Column("bsns_div_nm", sa.String(length=50), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "lmt_sno",
            name="uq_bid_ann_prtcpt_rgn_ntce_sno",
        ),
    )
    op.create_index(
        "ix_bid_ann_prtcpt_rgn_ntce",
        "bid_announcement_participation_regions",
        ["bid_ntce_no", "bid_ntce_ord"],
        unique=False,
    )
    op.create_index(
        "ix_bid_ann_prtcpt_rgn_collected",
        "bid_announcement_participation_regions",
        ["collected_at"],
        unique=False,
    )


def downgrade() -> None:
    # 2. bid_announcement_participation_regions 역순 삭제
    op.drop_index(
        "ix_bid_ann_prtcpt_rgn_collected",
        table_name="bid_announcement_participation_regions",
    )
    op.drop_index(
        "ix_bid_ann_prtcpt_rgn_ntce",
        table_name="bid_announcement_participation_regions",
    )
    op.drop_table("bid_announcement_participation_regions")

    # 1. bid_announcement_license_limits 역순 삭제
    op.drop_index(
        "ix_bid_ann_lic_limits_collected",
        table_name="bid_announcement_license_limits",
    )
    op.drop_index(
        "ix_bid_ann_lic_limits_ntce",
        table_name="bid_announcement_license_limits",
    )
    op.drop_table("bid_announcement_license_limits")
