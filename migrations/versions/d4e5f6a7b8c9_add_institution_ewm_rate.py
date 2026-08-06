"""기관 이력 집계에 지수감쇠 낙찰률 추가

Revision ID: d4e5f6a7b8c9
Revises: 4a991a277bc2
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "4a991a277bc2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_win_rate_stats",
        sa.Column(
            "ewm_rate",
            sa.Numeric(precision=10, scale=4),
            nullable=True,
            comment="지수감쇠 낙찰률 (퍼센트, 반감기 20건)",
        ),
    )


def downgrade() -> None:
    op.drop_column("institution_win_rate_stats", "ewm_rate")
