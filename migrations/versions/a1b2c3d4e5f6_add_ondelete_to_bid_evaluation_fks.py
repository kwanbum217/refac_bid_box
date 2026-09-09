"""적격심사 평가 테이블 외래키에 ON DELETE CASCADE 추가

Revision ID: a1b2c3d4e5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-09-09

공고나 사용자가 삭제될 때 참조하는 프로필과 스냅샷이 남아 외래키 제약을
위반하는 문제를 막습니다. 증빙 테이블은 이미 CASCADE 였으나 프로필의
user_id 와 스냅샷의 bid_id 및 user_id 는 빠져 있었습니다.
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None

FKS = (
    ("bid_evaluation_profiles", "fk_bid_eval_profiles_user_id", "user_id", "accounts_customuser"),
    ("bid_evaluation_snapshots", "fk_bid_eval_snapshots_bid_id", "bid_id", "bid_announcements"),
    ("bid_evaluation_snapshots", "fk_bid_eval_snapshots_user_id", "user_id", "accounts_customuser"),
)


def upgrade() -> None:
    for table, name, column, referent in FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referent, [column], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    for table, name, column, referent in FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referent, [column], ["id"])
