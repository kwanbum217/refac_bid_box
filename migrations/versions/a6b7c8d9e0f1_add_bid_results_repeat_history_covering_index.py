"""add bid_results repeat history covering index

predict-price 첫 요청의 재발주 이력 조회(src/ml/repeat_history.py lookup_repeat_history)는
dminstt_nm·category 등치 조건에 rl_openg_dt 내림차순 정렬과 LIMIT 5000 을 쓰고 SELECT 열로
bid_ntce_nm, sucsf_bid_rate, rl_openg_dt 를 읽습니다. 기존 ix_bid_results_inst_cat_stats 는
bid_ntce_nm 이 없어 조건에 맞는 행마다 테이블 본문을 랜덤 조회합니다(EXPLAIN key=
ix_bid_results_inst_cat_stats, rows 5442, Using index condition; Using where; Using filesort).
(dminstt_nm, category, rl_openg_dt, sucsf_bid_rate, bid_ntce_nm) 커버링 인덱스는 등치 두 열
뒤에 정렬 키가 이어져 역스캔으로 filesort 를 없애고 SELECT 열을 모두 담아 본문 조회도 없앱니다.

MySQL 에서는 조회와 수집을 막지 않도록 ALGORITHM=INPLACE, LOCK=NONE 으로 만듭니다. 본 리비전은
멱등이며 인덱스가 이미 있으면 건너뜁니다.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-10-11
"""

from alembic import op
from sqlalchemy import inspect

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None

TABLE_NAME = "bid_results"
INDEX_NAME = "ix_bid_results_repeat_hist"
COLUMNS = ("dminstt_nm", "category", "rl_openg_dt", "sucsf_bid_rate", "bid_ntce_nm")


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
