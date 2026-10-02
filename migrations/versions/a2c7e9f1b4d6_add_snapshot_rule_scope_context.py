"""스냅샷 판정 문맥 컬럼 추가

Revision ID: a2c7e9f1b4d6
Revises: 9d4e2b7a1c63
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c7e9f1b4d6"
down_revision: str | Sequence[str] | None = "9d4e2b7a1c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bid_evaluation_snapshots", sa.Column("contract_regime", sa.String(20), nullable=True)
    )
    op.add_column(
        "bid_evaluation_snapshots", sa.Column("institution_code", sa.String(100), nullable=True)
    )
    op.add_column(
        "bid_evaluation_snapshots", sa.Column("institution_name", sa.String(255), nullable=True)
    )
    op.add_column(
        "bid_evaluation_snapshots", sa.Column("region_code", sa.String(100), nullable=True)
    )
    op.add_column(
        "bid_evaluation_snapshots", sa.Column("region_name", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("bid_evaluation_snapshots", "region_name")
    op.drop_column("bid_evaluation_snapshots", "region_code")
    op.drop_column("bid_evaluation_snapshots", "institution_name")
    op.drop_column("bid_evaluation_snapshots", "institution_code")
    op.drop_column("bid_evaluation_snapshots", "contract_regime")
