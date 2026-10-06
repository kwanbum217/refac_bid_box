"""add bid prearng prices and institution sajeong rate stats

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-06 00:00:00.000000

나라장터 개찰결과 예비가격 상세(용역) 적재용 `bid_prearng_prices` 와 발주처별
사정률 분포 사전집계 `institution_sajeong_rate_stats` 를 추가합니다. 기존
테이블의 컬럼·타입·인덱스는 변경하지 않습니다(G1).

테이블·인덱스 이름은 모듈 상수나 f-string 없이 문자열 리터럴로 씁니다. G1
드리프트 게이트가 마이그레이션을 ast 로 읽어 이름을 정적으로 해석합니다.

기존 `test_signup_company_profile` 은 SQLite 에 ORM 메타데이터로 모든 테이블을
만든 뒤 직전 리비전을 스탬프하고 upgrade 를 돌립니다. 신규 테이블이 이미 존재하면
create_table 이 충돌하므로 존재 여부를 확인한 뒤 만듭니다. 운영 DB 에는 신규
테이블이 없어 정상적으로 생성됩니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_tables()
    if "bid_prearng_prices" not in existing:
        op.create_table('bid_prearng_prices',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("bid_ntce_no", sa.String(length=50), nullable=False),
            sa.Column("bid_ntce_ord", sa.String(length=10), nullable=False),
            sa.Column("bid_clsfc_no", sa.String(length=20), nullable=False),
            sa.Column("rbid_no", sa.String(length=10), nullable=False),
            sa.Column("category", sa.String(length=10), nullable=False),
            sa.Column("bid_ntce_nm", sa.String(length=500), nullable=True),
            sa.Column("dminstt_nm", sa.String(length=200), nullable=True),
            sa.Column("bssamt", sa.BigInteger(), nullable=True),
            sa.Column("plnprc", sa.BigInteger(), nullable=True),
            sa.Column("sajeong_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("tot_prce_num", sa.Integer(), nullable=True),
            sa.Column("drwt_prce_num", sa.Integer(), nullable=True),
            sa.Column("bss_up_num", sa.Integer(), nullable=True),
            sa.Column("slctn_bss", sa.String(length=100), nullable=True),
            sa.Column("items", sa.JSON(), nullable=True),
            sa.Column("rl_openg_dt", sa.DateTime(), nullable=True),
            sa.Column("mkng_dt", sa.DateTime(), nullable=True),
            sa.Column("inpt_dt", sa.DateTime(), nullable=True),
            sa.Column("raw_data", sa.JSON(), nullable=True),
            sa.Column("collected_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bid_ntce_no",
                "bid_ntce_ord",
                "bid_clsfc_no",
                "rbid_no",
                "category",
                name="uq_bid_prearng_prices",
            ),
        )
        op.create_index(
            "ix_prearng_inst_dt",
            "bid_prearng_prices",
            ["dminstt_nm", "category", "rl_openg_dt"],
            unique=False,
        )
        op.create_index(
            "ix_prearng_dt_cat",
            "bid_prearng_prices",
            ["rl_openg_dt", "category"],
            unique=False,
        )
        op.create_index(
            "ix_prearng_collected",
            "bid_prearng_prices",
            ["collected_at"],
            unique=False,
        )

    if "institution_sajeong_rate_stats" not in existing:
        op.create_table('institution_sajeong_rate_stats',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("institution_name", sa.String(length=200), nullable=False),
            sa.Column("category", sa.String(length=10), nullable=False),
            sa.Column("window_days", sa.Integer(), nullable=False),
            sa.Column("sample_count", sa.BigInteger(), nullable=False),
            sa.Column("min_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("max_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("p10_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("p50_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("p90_rate", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("rebuilt_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "scope",
                "institution_name",
                "category",
                "window_days",
                name="uq_inst_sajeong",
            ),
        )
        op.create_index(
            "ix_inst_sajeong_lookup",
            "institution_sajeong_rate_stats",
            ["scope", "institution_name", "category"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    existing = _existing_tables()
    if "institution_sajeong_rate_stats" in existing:
        op.drop_index("ix_inst_sajeong_lookup", table_name="institution_sajeong_rate_stats")
        op.drop_table("institution_sajeong_rate_stats")
    if "bid_prearng_prices" in existing:
        op.drop_index("ix_prearng_collected", table_name="bid_prearng_prices")
        op.drop_index("ix_prearng_dt_cat", table_name="bid_prearng_prices")
        op.drop_index("ix_prearng_inst_dt", table_name="bid_prearng_prices")
        op.drop_table("bid_prearng_prices")
