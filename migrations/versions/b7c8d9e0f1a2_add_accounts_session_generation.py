"""add accounts_session_generation

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-10-11

전체 로그아웃(모든 기기에서 로그아웃)의 사용자별 세대 번호를 Redis 키
auth:user_epoch:<user_id> 에만 두면 Redis 데이터가 지워질 때 세대가 0 으로
돌아가 이미 무효화한 세션이 되살아납니다. 이 테이블이 세대의 정본이 되고
Redis 는 TTL 을 가진 캐시로만 씁니다. user_id 는 accounts_customuser.id 를
참조하며 ON DELETE CASCADE 로, 사용자가 삭제되면 세대 행도 함께 사라집니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: str | Sequence[str] | None = 'a6b7c8d9e0f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('accounts_session_generation',
    sa.Column('user_id', PK, nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False, server_default=sa.text('0')),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'],
        name='fk_accounts_session_generation_user_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('accounts_session_generation')
