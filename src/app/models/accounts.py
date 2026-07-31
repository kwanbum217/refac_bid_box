"""
src/app/models/accounts.py

사용자 계정 ORM (원본 apps/accounts/models.py CustomUser 1:1 이식).
테이블은 원본 그대로 accounts_customuser 이며, Django AbstractUser 컬럼과
프로젝트 커스텀 컬럼(nickname, birth_y/m/d, gender)을 모두 보존합니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from src.app.core.db import Base, PKBigInteger

GENDER_CHOICES = {
    "M": "남성",
    "F": "여성",
}


class CustomUser(Base):
    """조달 분석 플랫폼 사용자 (원본 db_table: accounts_customuser)"""

    __tablename__ = "accounts_customuser"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    password = Column(String(128), nullable=False)
    last_login = Column(DateTime, nullable=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    username = Column(String(150), nullable=False, unique=True, index=True)
    first_name = Column(String(150), nullable=False, default="")
    last_name = Column(String(150), nullable=False, default="")
    email = Column(String(254), nullable=False, default="")
    is_staff = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    date_joined = Column(DateTime, nullable=False, default=datetime.utcnow)
    nickname = Column(String(50), nullable=False, default="")
    birth_y = Column(Integer, nullable=True)
    birth_m = Column(Integer, nullable=True)
    birth_d = Column(Integer, nullable=True)
    gender = Column(String(1), nullable=False, default="M")

    def __str__(self) -> str:
        return f"{self.username} ({self.nickname})"


# 이전 리팩토링본이 임의로 도입한 이름과의 호환 별칭
UserAccount = CustomUser
