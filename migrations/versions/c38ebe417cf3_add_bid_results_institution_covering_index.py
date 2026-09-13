"""add bid_results institution covering index

RAG 정형 검색의 기관명 조건 낙찰 집계를 인덱스만으로 끝냅니다.

기관명 부분 일치(`dminstt_nm LIKE '%...%'`)로 거른 낙찰 금액 COUNT/AVG/SUM 은 테이블 전체
스캔(1.46GB)이고, 낙찰업체별 GROUP BY 는 그룹 인덱스를 배제한 뒤에도 테이블을 읽습니다.
category 가 붙으면 옵티마이저가 category 인덱스로 행마다 본문을 읽습니다("광주"+Servc 11.8초).
(dminstt_nm, category, bidwinnr_nm, sucsf_bid_rate, sucsf_bid_amt) 는 두 집계가 쓰는 컬럼을 모두
담으며 id 는 InnoDB 보조 인덱스에 기본키로 붙습니다(docs/analysis/rag_coldsql_root_cause_20260913.md 14장).

bid_results 데이터 사전에는 파일 없는 FULLTEXT 보조 테이블 항목이 남아 있으나 복제본에서 테이블
전체 재구축이 오류 없이 끝나 이 DDL 을 막지 않습니다(같은 문서 11.1.1 절).

MySQL 에서는 조회와 수집을 막지 않도록 ALGORITHM=INPLACE, LOCK=NONE 으로 만듭니다. 본 리비전은
멱등이며 인덱스가 이미 있으면 건너뜁니다. G1 스키마 서명 기준선을 같은 변경에서 갱신합니다.

Revision ID: c38ebe417cf3
Revises: afc72b545c6a
Create Date: 2026-09-13
"""

from alembic import op
from sqlalchemy import inspect

revision = "c38ebe417cf3"
down_revision = "afc72b545c6a"
branch_labels = None
depends_on = None

TABLE_NAME = "bid_results"
INDEX_NAME = "ix_bid_results_inst_cat_stats"
COLUMNS = ("dminstt_nm", "category", "bidwinnr_nm", "sucsf_bid_rate", "sucsf_bid_amt")


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
