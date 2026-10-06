"""add account company profiles and qualification facts

Revision ID: c2d3e4f5a6b7
Revises: bd7c2e9a104f
Create Date: 2026-10-06 00:00:00.000000

회원가입 시 받는 회사·담당자 정보, 정량평가 원자료, 약관 동의 이력 테이블을
추가합니다. 기존 accounts_customuser 는 컬럼·타입을 바꾸지 않습니다(G1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: str | Sequence[str] | None = 'bd7c2e9a104f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('account_company_profiles',
    sa.Column('id', PK, autoincrement=True, nullable=False),
    sa.Column('user_id', PK, nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=True),
    sa.Column('representative_name', sa.String(length=100), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('fax', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('contact_name', sa.String(length=100), nullable=True),
    sa.Column('contact_position', sa.String(length=100), nullable=True),
    sa.Column('contact_department', sa.String(length=100), nullable=True),
    sa.Column('contact_phone', sa.String(length=50), nullable=True),
    sa.Column('contact_email', sa.String(length=254), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'],
        name='fk_account_company_profiles_user_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', name='uq_account_company_profiles_user_id')
    )

    op.create_table('account_qualification_facts',
    sa.Column('id', PK, autoincrement=True, nullable=False),
    sa.Column('user_id', PK, nullable=False),
    sa.Column('credit_grade', sa.String(length=50), nullable=True),
    sa.Column('credit_evaluated_on', sa.Date(), nullable=True),
    sa.Column('reputation_items', sa.JSON(), nullable=True),
    sa.Column('non_price_quant_score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'],
        name='fk_account_qualification_facts_user_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', name='uq_account_qualification_facts_user_id')
    )

    op.create_table('account_consent_events',
    sa.Column('id', PK, autoincrement=True, nullable=False),
    sa.Column('user_id', PK, nullable=False),
    sa.Column('consent_kind', sa.String(length=30), nullable=False),
    sa.Column('terms_version', sa.String(length=20), nullable=False),
    sa.Column('consented_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'],
        name='fk_account_consent_events_user_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_account_consent_events_user_id', 'account_consent_events', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_account_consent_events_user_id', table_name='account_consent_events')
    op.drop_table('account_consent_events')
    op.drop_table('account_qualification_facts')
    op.drop_table('account_company_profiles')
