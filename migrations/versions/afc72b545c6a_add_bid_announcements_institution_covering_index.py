"""add bid_announcements institution covering index

RAG 정형 검색의 기관명 조건 집계를 인덱스만으로 끝냅니다.

기관명 부분 일치(`dminstt_nm LIKE '%...%'`)는 날짜 범위가 없으면 후보 행의 공고 본문을
읽어야 합니다. 공고 데이터는 31.6GB 로 버퍼풀 2GB 밖에 있어 콜드에서 문장당 16~28초가
걸렸고, 넓은 기관명("서울", 442,955행)의 공고명별 집계는 23~42초였습니다. 기관명 2단계
해석은 일치 행이 15만~22만 행을 넘으면 오히려 느려져 이 구간을 줄이지 못했습니다
(docs/analysis/rag_coldsql_root_cause_20260913.md 8장).

(dminstt_nm, category, bid_ntce_nm) 는 느린 공고 문장이 쓰는 컬럼을 모두 담습니다. id 는
InnoDB 보조 인덱스에 기본키로 붙으므로 COUNT(id), category 조건, 기관별·공고명별 GROUP BY 가
본문을 읽지 않습니다. 크기는 기존 기관명 인덱스 359MB 의 약 2.1배(약 760MB)로 추정했습니다.

MySQL 에서는 조회와 수집을 막지 않도록 ALGORITHM=INPLACE, LOCK=NONE 으로 만듭니다. 본
리비전은 멱등이며 인덱스가 이미 있으면 건너뜁니다. 인덱스는 테이블·컬럼을 바꾸지 않지만
G1 스키마 서명이 인덱스 목록을 포함하므로 기준선(data/backups/schema_signature_baseline.json)을
같은 변경에서 갱신합니다.

Revision ID: afc72b545c6a
Revises: b2c3d4e5f6a7
Create Date: 2026-09-13
"""

from alembic import op
from sqlalchemy import inspect

revision = "afc72b545c6a"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

TABLE_NAME = "bid_announcements"
INDEX_NAME = "ix_bid_ann_inst_cat_ntce"
COLUMNS = ("dminstt_nm", "category", "bid_ntce_nm")


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
