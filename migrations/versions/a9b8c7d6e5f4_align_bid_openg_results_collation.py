"""align bid openg results collation

Revision ID: a9b8c7d6e5f4
Revises: c1d2e3f4a5b6
Create Date: 2026-11-03 00:00:00.000000

`bid_openg_results` 는 콜레이션을 명시하지 않고 만들어져 운영 스키마 기본값
`utf8mb4_0900_ai_ci` 를 따랐습니다. 나머지 테이블은 `utf8mb4_unicode_ci` 라
공고·낙찰 테이블과 공고번호로 비교하면 콜레이션 혼합 오류가 나고, 빈 DB 에
마이그레이션을 올리는 CI 의 G1 스키마 서명과도 어긋납니다.

테이블이 이미 `utf8mb4_unicode_ci` 이면 아무것도 하지 않습니다. 컬럼 이름·
길이·NULL 여부·인덱스는 바꾸지 않고 문자 집합과 콜레이션만 맞춥니다.
downgrade 는 불일치 상태로 되돌리지 않도록 비워 둡니다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b8c7d6e5f4"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    current = bind.execute(
        sa.text(
            "SELECT TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'bid_openg_results'"
        )
    ).scalar()
    if current is None or current == "utf8mb4_unicode_ci":
        return
    op.execute(
        "ALTER TABLE bid_openg_results "
        "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )


def downgrade() -> None:
    """Downgrade schema."""
