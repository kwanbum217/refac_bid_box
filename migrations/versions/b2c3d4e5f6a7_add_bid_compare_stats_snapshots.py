"""비교 통계 사전 집계 스냅샷 테이블 추가

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-11

GET /api/v1/bids/compare-stats 의 두 무거운 집계(기관별 상위 10,
매칭 건수)를 사전 집계로 전환합니다. 기존 테이블과 컬럼은 건드리지 않고
bid_compare_stats_snapshots 하나만 새로 둡니다.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('bid_compare_stats_snapshots',
        sa.Column('snapshot_key', sa.String(length=50), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('window_days', sa.Integer(), nullable=False),
        sa.Column('rebuilt_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('snapshot_key'),
    )


def downgrade() -> None:
    op.drop_table('bid_compare_stats_snapshots')
