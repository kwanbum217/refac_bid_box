"""add bid_results stats covering index

챗봇 통계 질의가 340만 행을 풀스캔하던 것을 커버링 인덱스로 없앱니다.

실측 (bid_results 3,390,117행, MySQL 8 Docker):

| 질의 | 이전 | 이후 |
| --- | --- | --- |
| category 단독 집계 | 5,347ms | 236ms |
| category + 1년 기간 집계 | 4,825ms | 23ms |

기존 category 단일 인덱스만으로는 집계 컬럼을 읽으려 테이블로 되돌아가야 해
옵티마이저가 풀스캔(type=ALL)을 택했습니다. 집계에 쓰는 두 컬럼까지 넣어
인덱스만으로 끝나게(Using index) 합니다.

컬럼 순서는 category 등치 조건이 먼저, rl_openg_dt 범위 조건이 다음입니다.
반대로 두면 등치 조건을 인덱스 선두에서 못 써 범위 스캔 폭이 넓어집니다.

Revision ID: a1c4e7b90d21
Revises: 88dd431cb285
Create Date: 2026-08-04
"""

from alembic import op

revision = "a1c4e7b90d21"
down_revision = "88dd431cb285"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_bid_results_cat_dt_stats"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "bid_results",
        ["category", "rl_openg_dt", "sucsf_bid_rate", "sucsf_bid_amt"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="bid_results")
