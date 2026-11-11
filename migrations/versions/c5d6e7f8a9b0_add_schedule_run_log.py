"""add schedule run log

Revision ID: c5d6e7f8a9b0
Revises: b4e5f6a7c8d9
Create Date: 2026-11-11 00:00:00.000000

스케줄 태스크 실행 이력을 영구 보관할 `schedule_run_log` 를 추가합니다. 기존
테이블의 컬럼·인덱스·콜레이션은 변경하지 않고 신규 테이블 1개만 만듭니다(G1).

테이블·인덱스 이름은 모듈 상수나 f-string 없이 문자열 리터럴로 씁니다. G1
드리프트 게이트가 마이그레이션을 ast 로 읽어 이름을 정적으로 해석합니다.

운영 스키마 기본 콜레이션이 `utf8mb4_0900_ai_ci` 라 `utf8mb4_unicode_ci` 를
명시합니다. ORM 메타데이터로 테이블을 먼저 만든 뒤 upgrade 를 도는 시험이
있으므로 존재 여부를 확인한 뒤 만듭니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4e5f6a7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Upgrade schema."""
    if "schedule_run_log" not in _existing_tables():
        op.create_table('schedule_run_log',
            sa.Column("id", PK, autoincrement=True, nullable=False),
            sa.Column("schedule_name", sa.String(length=64), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("error_type", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.String(length=1000), nullable=True),
            sa.Column("worker_id", sa.String(length=128), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index(
            "ix_schedule_run_log_name_started",
            "schedule_run_log",
            ["schedule_name", "started_at"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "schedule_run_log" in _existing_tables():
        op.drop_index(
            "ix_schedule_run_log_name_started",
            table_name="schedule_run_log",
        )
        op.drop_table("schedule_run_log")
