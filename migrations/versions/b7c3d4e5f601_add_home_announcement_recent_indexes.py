"""add home announcement recent-query indexes

홈 화면의 카테고리별 최근 공고 표본 조회가 category 단일 인덱스와
collected_at 단일 인덱스를 각각 사용하면서 대량 행 filesort를 수행하던 문제를
해결합니다. 기존 컬럼·행·제약조건은 변경하지 않고 조회용 인덱스만 추가합니다.

Revision ID: b7c3d4e5f601
Revises: a1c4e7b90d21
Create Date: 2026-08-05
"""

from alembic import op

revision = "b7c3d4e5f601"
down_revision = "a1c4e7b90d21"
branch_labels = None
depends_on = None

INDEXES = (
    (
        "ix_bid_ann_category_collected_dt",
        ["category", "collected_at", "bid_ntce_dt", "id"],
    ),
    ("ix_bid_ann_collected_dt", ["collected_at", "bid_ntce_dt", "id"]),
)


def upgrade() -> None:
    for name, columns in INDEXES:
        op.create_index(name, "bid_announcements", columns, unique=False)


def downgrade() -> None:
    for name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name="bid_announcements")
