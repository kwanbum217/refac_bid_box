"""add bid_results institution date index

공고 상세의 기관 과거 낙찰 5건 조회는 `dminstt_nm` 등치 조건에 `rl_openg_dt` 내림차순 정렬을
씁니다. 기존 `bid_results_dminstt_nm_1b809760` 는 기관 단일 컬럼 인덱스라 옵티마이저가 해당
기관의 모든 행(경기도 화성시 등 수천 행)을 읽고 filesort 로 상위 5건을 고릅니다. 콜드 상태에서
7초를 넘습니다. (dminstt_nm, rl_openg_dt) 복합 인덱스는 등치 조건 뒤에 정렬 키가 이어져 읽는
범위를 5건으로 줄입니다.

MySQL 에서는 조회와 수집을 막지 않도록 ALGORITHM=INPLACE, LOCK=NONE 으로 만듭니다. 본 리비전은
멱등이며 인덱스가 이미 있으면 건너뜁니다.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-09
"""

from alembic import op
from sqlalchemy import inspect

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None

TABLE_NAME = "bid_results"
INDEX_NAME = "ix_bid_results_inst_dt"
COLUMNS = ("dminstt_nm", "rl_openg_dt")


def _has_index() -> bool:
    bind = op.get_bind()
    return INDEX_NAME in {index["name"] for index in inspect(bind).get_indexes(TABLE_NAME)}


def upgrade() -> None:
    if _has_index():
        return
    if op.get_bind().dialect.name == "mysql":
        op.execute(
            f"ALTER TABLE {TABLE_NAME} ADD INDEX {INDEX_NAME} ({', '.join(COLUMNS)}), "
            "ALGORITHM=INPLACE, LOCK=NONE"
        )
        return
    op.create_index(INDEX_NAME, TABLE_NAME, list(COLUMNS), unique=False)


def downgrade() -> None:
    if _has_index():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
