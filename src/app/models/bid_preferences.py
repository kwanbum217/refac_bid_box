"""
src/app/models/bid_preferences.py

회원별 관심 업종(면허)·지역 저장 ORM 모델.

새 메인 화면의 '사용자에 해당되는 입찰 건수' 를 세려면 회원이 관심 있는
업종(면허) 코드와 지역 코드가 필요합니다. 기존 계정 테이블은 건드리지 않고
신규 테이블 `account_bid_preferences` 만 추가합니다(G1).

업종·지역 코드 정의는 공고 탐색 필터와 같은 정본을 씁니다
(src/app/services/bid_queries.py). 저장 전에 그 정규화 함수로 좁힙니다.

시각 컬럼은 앱 공통 규약대로 UTC naive 입니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

FK_ACCOUNT_BID_PREFERENCE_USER = "fk_account_bid_preferences_user_id"


class AccountBidPreference(Base):
    """회원 관심 업종·지역 (사용자당 1행)."""

    __tablename__ = "account_bid_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_account_bid_preferences_user_id",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PKBigInteger,
        ForeignKey(
            "accounts_customuser.id",
            name=FK_ACCOUNT_BID_PREFERENCE_USER,
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    license_codes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="관심 업종(면허) 코드 목록. 공고 탐색 업종 필터와 같은 코드 정의",
    )
    region_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="",
        server_default="",
        comment="관심 지역 코드. 공고 탐색 지역 필터와 같은 코드 정의",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
