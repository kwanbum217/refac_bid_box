"""나라장터 수요기관 기준정보 테이블 추가

Revision ID: bd7c2e9a104f
Revises: a2c7e9f1b4d6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bd7c2e9a104f"
down_revision: str | Sequence[str] | None = "a2c7e9f1b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # API 기관명·분류·주소는 표기 길이 편차가 있어 실측 응답을 보존하도록 여유 길이를 둡니다.
    op.create_table('g2b_demand_institutions',
        sa.Column("dminstt_cd", sa.String(20), primary_key=True),
        sa.Column("dminstt_nm", sa.String(500), nullable=True),
        sa.Column("jrsdctn_div_nm", sa.String(100), nullable=True),
        sa.Column("instt_ty_lrgclsfc_nm", sa.String(200), nullable=True),
        sa.Column("instt_ty_midclsfc_nm", sa.String(300), nullable=True),
        sa.Column("instt_ty_smlclsfc_nm", sa.String(300), nullable=True),
        sa.Column("rgn_cd", sa.String(10), nullable=True),
        sa.Column("rgn_nm", sa.String(200), nullable=True),
        sa.Column("toplvl_instt_cd", sa.String(20), nullable=True),
        sa.Column("toplvl_instt_nm", sa.String(500), nullable=True),
        sa.Column("dlt_yn", sa.String(10), nullable=True),
        sa.Column("rgst_dt", sa.String(20), nullable=True),
        sa.Column("chg_dt", sa.DateTime(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("g2b_demand_institutions")
