"""add account bid preferences

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-11 00:00:00.000000

회원별 관심 업종(면허)·지역을 보관할 `account_bid_preferences` 를 추가합니다.
기존 테이블의 컬럼·인덱스·콜레이션은 변경하지 않고 신규 테이블 1개만 만듭니다(G1).

테이블·제약 이름은 문자열 리터럴로 씁니다. G1 드리프트 게이트가 마이그레이션을
ast 로 읽어 이름을 정적으로 해석합니다.

운영 스키마 기본 콜레이션이 `utf8mb4_0900_ai_ci` 라 `utf8mb4_unicode_ci` 를
명시합니다. ORM 메타데이터로 테이블을 먼저 만든 뒤 upgrade 를 도는 시험이
있으므로 존재 여부를 확인한 뒤 만듭니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Upgrade schema."""
    if "account_bid_preferences" not in _existing_tables():
        op.create_table('account_bid_preferences',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("user_id", PK, nullable=False),
            sa.Column("license_codes", sa.JSON(), nullable=False),
            sa.Column("region_code", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["accounts_customuser.id"],
                name="fk_account_bid_preferences_user_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_account_bid_preferences_user_id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "account_bid_preferences" in _existing_tables():
        op.drop_table("account_bid_preferences")
