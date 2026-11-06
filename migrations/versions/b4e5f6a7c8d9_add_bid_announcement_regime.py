"""add bid announcement regime

Revision ID: b4e5f6a7c8d9
Revises: a9b8c7d6e5f4
Create Date: 2026-11-06 00:00:00.000000

첨부 원문 적용 기준 갈래 판별 결과를 저장할 `bid_announcement_regime` 을
추가합니다. 기존 테이블의 컬럼·인덱스·콜레이션은 변경하지 않고 신규 테이블
1개만 만듭니다(G1).

테이블·인덱스 이름은 모듈 상수나 f-string 없이 문자열 리터럴로 씁니다. G1
드리프트 게이트가 마이그레이션을 ast 로 읽어 이름을 정적으로 해석합니다.

운영 스키마 기본 콜레이션이 `utf8mb4_0900_ai_ci` 라 `utf8mb4_unicode_ci` 를
명시합니다. ORM 메타데이터로 테이블을 먼저 만든 뒤 upgrade 를 도는 시험이
있으므로 존재 여부를 확인한 뒤 만듭니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e5f6a7c8d9"
down_revision: str | Sequence[str] | None = "a9b8c7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Upgrade schema."""
    if "bid_announcement_regime" not in _existing_tables():
        op.create_table('bid_announcement_regime',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("bid_ntce_no", sa.String(length=40), nullable=False),
            sa.Column("bid_ntce_ord", sa.String(length=10), nullable=False),
            sa.Column("category", sa.String(length=20), nullable=False),
            sa.Column("regime", sa.String(length=30), nullable=False),
            sa.Column("evidence", sa.String(length=255), nullable=True),
            sa.Column("matched_rules", sa.String(length=255), nullable=True),
            sa.Column("source_files", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error", sa.String(length=255), nullable=True),
            sa.Column("classifier_version", sa.String(length=20), nullable=False),
            sa.Column("classified_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bid_ntce_no",
                "bid_ntce_ord",
                "category",
                name="uq_bid_announcement_regime",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index(
            "ix_bid_announcement_regime_regime",
            "bid_announcement_regime",
            ["regime"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "bid_announcement_regime" in _existing_tables():
        op.drop_index(
            "ix_bid_announcement_regime_regime",
            table_name="bid_announcement_regime",
        )
        op.drop_table("bid_announcement_regime")
