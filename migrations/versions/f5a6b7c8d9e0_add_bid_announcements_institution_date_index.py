"""add bid_announcements institution date index

공고 상세의 기관·분야별 유사 공고 5건 조회는 `category`·`dminstt_nm` 등치 조건에
`bid_ntce_dt` 내림차순 정렬을 씁니다. 기존 `ix_bid_ann_inst_cat_ntce`(dminstt_nm, category,
bid_ntce_nm) 는 정렬 키가 아니라 공고명 순이라 인덱스 순서 그대로 오래된 공고가 먼저 나옵니다.
정렬을 붙이면 옵티마이저가 기관 전체를 `bid_announcements_bid_ntce_dt_c42f1afb` 로 역방향 스캔해
김해시에서 4,655행을 읽습니다(0.2초). (dminstt_nm, category, bid_ntce_dt) 복합 인덱스는 등치
조건 뒤에 정렬 키가 이어져 읽는 범위를 5건으로 줄입니다.

MySQL 에서는 조회와 수집을 막지 않도록 ALGORITHM=INPLACE, LOCK=NONE 으로 만듭니다. 본 리비전은
멱등이며 인덱스가 이미 있으면 건너뜁니다.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-10-09
"""

from alembic import op
from sqlalchemy import inspect

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None

TABLE_NAME = "bid_announcements"
INDEX_NAME = "ix_bid_ann_inst_cat_dt"
COLUMNS = ("dminstt_nm", "category", "bid_ntce_dt")


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
