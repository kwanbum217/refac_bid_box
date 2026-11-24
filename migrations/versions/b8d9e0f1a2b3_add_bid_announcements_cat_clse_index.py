"""add bid_announcements category+deadline index

메인 화면의 '내 조건 입찰 중' 건수·목록이 캐시가 빈 상태에서 49~60초 걸리던
것을 줄입니다. 조건은 `category='Servc'` 등치 + `bid_clse_dt >= now` 범위이고
정렬도 `bid_clse_dt` 입니다. 그런데 기존 인덱스는 `(category, bid_ntce_dt)`
(`ix_bid_ann_cat_dt`) 와 `(bid_ntce_dt)` 계열뿐이라 마감일로 먼저 좁힐 수
없었습니다.

입찰 중 용역 공고는 7,068건인데 performance_schema 실측 검사 행은 평균
1,022,268행이었습니다. (category, bid_clse_dt) 를 선두로 두면 등치 + 범위
조건을 인덱스 한 번에 좁힌 뒤 마감 임박 순서를 그대로 읽을 수 있습니다.

본 리비전은 멱등입니다. 인덱스가 이미 있으면 건너뜁니다. 운영 DB 적용은
별도 승인 절차를 따르며, 신규 DB 는 이 리비전이 만듭니다. 둘 중 어느 경로로
왔든 결과가 같아야 합니다.

Revision ID: b8d9e0f1a2b3
Revises: d6e7f8a9b0c1
Create Date: 2026-11-24
"""

from alembic import op
from sqlalchemy import inspect

# Capsule 초안이 지정한 b7c8d9e0f1a2 는 이미 accounts_session_generation 리비전이
# 쓰고 있어 같은 ID 로 두면 이력이 갈라집니다. 코디네이터 승인으로 리비전 ID 와
# 파일 이름을 b8d9e0f1a2b3 으로 맞췄습니다.
revision = "b8d9e0f1a2b3"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_bid_ann_cat_clse"
TABLE_NAME = "bid_announcements"


def _has_index() -> bool:
    bind = op.get_bind()
    names = {index["name"] for index in inspect(bind).get_indexes(TABLE_NAME)}
    return INDEX_NAME in names


def upgrade() -> None:
    if _has_index():
        return
    op.create_index(INDEX_NAME, TABLE_NAME, ["category", "bid_clse_dt"], unique=False)


def downgrade() -> None:
    if _has_index():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
