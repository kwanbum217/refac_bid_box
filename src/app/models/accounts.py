"""
src/app/models/accounts.py

사용자 계정 ORM (원본 apps/accounts/models.py CustomUser 1:1 이식).
테이블은 원본 그대로 accounts_customuser 이며, Django AbstractUser 컬럼과
프로젝트 커스텀 컬럼(nickname, birth_y/m/d, gender)을 모두 보존합니다.
accounts_session_generation 은 원본에 없는 신규 테이블로, 전체 로그아웃 세대의
정본을 보관합니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

GENDER_CHOICES = {
    "M": "남성",
    "F": "여성",
}


class CustomUser(Base):
    """조달 분석 플랫폼 사용자 (원본 db_table: accounts_customuser)"""

    __tablename__ = "accounts_customuser"

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # unique=True 만으로 DB 의 UNIQUE KEY `username` 과 일치합니다.
    # index=True 를 더하면 원본에 없는 ix_accounts_customuser_username 이 생깁니다.
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    date_joined: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    birth_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birth_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birth_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str] = mapped_column(String(1), nullable=False, default="M")

    def __str__(self) -> str:
        return f"{self.username} ({self.nickname})"


class SessionGeneration(Base):
    """사용자별 세션 세대 정본 (원본에 없는 신규 테이블).

    전체 로그아웃은 이 행의 generation 을 1 올려 그 사용자의 모든 세션을
    무효화합니다. Redis 키 auth:user_epoch:<user_id> 는 이 값의 캐시일 뿐이라
    Redis 데이터가 지워져도 세대가 되돌아가지 않습니다. 행이 없는 사용자는
    세대 0 과 같습니다.
    """

    __tablename__ = "accounts_session_generation"

    user_id: Mapped[int] = mapped_column(
        PKBigInteger,
        ForeignKey(
            "accounts_customuser.id",
            name="fk_accounts_session_generation_user_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


# 이전 리팩토링본이 임의로 도입한 이름과의 호환 별칭
UserAccount = CustomUser
