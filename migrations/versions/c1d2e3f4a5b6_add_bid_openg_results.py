"""add bid openg results

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-10-31 00:00:00.000000

나라장터 개찰결과(유찰 상태 포함) 적재용 `bid_openg_results` 를 추가합니다.
기존 `bid_announcements`·`bid_results` 의 컬럼·타입·인덱스는 변경하지 않고
신규 테이블 1개만 만듭니다(G1).

테이블·인덱스 이름은 모듈 상수나 f-string 없이 문자열 리터럴로 씁니다. G1
드리프트 게이트가 마이그레이션을 ast 로 읽어 이름을 정적으로 해석합니다.

`test_signup_company_profile` 처럼 ORM 메타데이터로 기존 테이블을 먼저 만든
뒤 직전 리비전을 스탬프하고 upgrade 를 도는 시험이 있습니다. 신규 테이블이
이미 존재하면 create_table 이 충돌하므로 존재 여부를 확인한 뒤 만듭니다.
운영 DB 에는 신규 테이블이 없어 정상적으로 생성됩니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Upgrade schema."""
    if "bid_openg_results" not in _existing_tables():
        op.create_table('bid_openg_results',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("bid_ntce_no", sa.String(length=50), nullable=False),
            sa.Column("bid_ntce_ord", sa.String(length=10), nullable=False),
            sa.Column("rbid_no", sa.String(length=10), nullable=False),
            sa.Column("bid_clsfc_no", sa.String(length=20), nullable=False),
            sa.Column("category", sa.String(length=10), nullable=False),
            sa.Column("progrs_div_cd_nm", sa.String(length=30), nullable=False),
            sa.Column("prtcpt_cnum", sa.Integer(), nullable=True),
            sa.Column("bid_ntce_nm", sa.String(length=500), nullable=True),
            sa.Column("dminstt_nm", sa.String(length=200), nullable=True),
            sa.Column("openg_dt", sa.DateTime(), nullable=True),
            sa.Column("raw_data", sa.JSON(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("collected_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bid_ntce_no",
                "bid_ntce_ord",
                "rbid_no",
                "category",
                name="uq_bid_openg_results",
            ),
        )
        op.create_index(
            "ix_openg_cat_dt",
            "bid_openg_results",
            ["category", "openg_dt"],
            unique=False,
        )
        op.create_index(
            "ix_openg_status_dt",
            "bid_openg_results",
            ["progrs_div_cd_nm", "openg_dt"],
            unique=False,
        )
        op.create_index(
            "ix_openg_inst_cat_dt",
            "bid_openg_results",
            ["dminstt_nm", "category", "openg_dt"],
            unique=False,
        )
        op.create_index(
            "ix_openg_notice",
            "bid_openg_results",
            ["bid_ntce_no", "category"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "bid_openg_results" in _existing_tables():
        op.drop_index("ix_openg_notice", table_name="bid_openg_results")
        op.drop_index("ix_openg_inst_cat_dt", table_name="bid_openg_results")
        op.drop_index("ix_openg_status_dt", table_name="bid_openg_results")
        op.drop_index("ix_openg_cat_dt", table_name="bid_openg_results")
        op.drop_table("bid_openg_results")
