"""bid_dataset_summaries에 집계 알고리즘 버전 컬럼 추가

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bid_dataset_summaries",
        sa.Column(
            "aggregation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="집계 알고리즘 버전",
        ),
    )


def downgrade() -> None:
    op.drop_column("bid_dataset_summaries", "aggregation_version")
