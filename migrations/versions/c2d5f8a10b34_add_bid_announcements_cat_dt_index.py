"""add bid_announcements category+date index

낙찰결과 AI 분석이 공고 테이블을 훑던 것을 줄입니다.

RAG 정형 검색은 요청 한 번에 공고 테이블을 여섯 번 봅니다. 조건은 모두
`category` 등치 + `dminstt_nm LIKE '%...%'` 이고 정렬은 `bid_ntce_dt DESC`
입니다. 앞 와일드카드라 기관명 인덱스는 쓸 수 없으므로, 카테고리로 좁힌 뒤
날짜 순으로 걸어가는 것이 최선입니다.

기존 `ix_bid_ann_dt_cat` 는 컬럼 순서가 (bid_ntce_dt, category) 라 이 조건에
맞지 않습니다. 등치 조건이 선두에 와야 인덱스 선두에서 좁힐 수 있습니다.

실측 (bid_announcements 5,461,079행, MySQL 8 Docker):

| 조건 | 소요 |
| --- | --- |
| 현행 (옵티마이저가 bid_ntce_dt 인덱스 선택) | 537ms |
| category 단일 인덱스 강제 | 149ms |
| dminstt_nm 인덱스 강제 | 46,915ms |

마지막 줄이 이 인덱스를 만드는 이유입니다. 옵티마이저가 기관명 인덱스를
고르는 순간 47초가 되며, 통계가 흔들리면 실제로 그럴 수 있습니다.

본 리비전은 멱등입니다. 인덱스가 이미 있으면 건너뜁니다. 운영 DB 에는
성능 확인을 위해 DDL 로 먼저 만들었고, 신규 DB 는 이 리비전이 만듭니다.
둘 중 어느 경로로 왔든 결과가 같아야 합니다.

Revision ID: c2d5f8a10b34
Revises: a1c4e7b90d21
Create Date: 2026-08-05
"""

from alembic import op
from sqlalchemy import inspect

revision = "c2d5f8a10b34"
down_revision = "a1c4e7b90d21"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_bid_ann_cat_dt"
TABLE_NAME = "bid_announcements"


def _has_index() -> bool:
    bind = op.get_bind()
    names = {index["name"] for index in inspect(bind).get_indexes(TABLE_NAME)}
    return INDEX_NAME in names


def upgrade() -> None:
    if _has_index():
        return
    op.create_index(INDEX_NAME, TABLE_NAME, ["category", "bid_ntce_dt"], unique=False)


def downgrade() -> None:
    if _has_index():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
