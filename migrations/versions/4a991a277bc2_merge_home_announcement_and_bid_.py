"""merge home announcement and bid announcement indexes

병렬 세션이 같은 부모(`a1c4e7b90d21`)에서 각각 인덱스 리비전을 만들어 head 가
둘이 됐습니다. 둘 다 인덱스 추가라 서로 충돌하지 않으므로 계보만 합칩니다.

| 리비전 | 내용 |
| --- | --- |
| `b7c3d4e5f601` | 홈 화면 공고 조회 인덱스 |
| `c2d5f8a10b34` | RAG 정형 검색용 `ix_bid_ann_cat_dt (category, bid_ntce_dt)` |

스키마 변경은 없습니다. 두 갈래를 하나로 모으는 것이 전부입니다.

Revision ID: 4a991a277bc2
Revises: b7c3d4e5f601, c2d5f8a10b34
Create Date: 2026-08-05
"""

revision = "4a991a277bc2"
down_revision = ("b7c3d4e5f601", "c2d5f8a10b34")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """계보 병합 전용. 적용할 스키마 변경이 없습니다."""


def downgrade() -> None:
    """계보 병합 전용. 되돌릴 스키마 변경이 없습니다."""
