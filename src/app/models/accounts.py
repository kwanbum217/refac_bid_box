from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, String
from src.app.core.db import Base, PKBigInteger


class UserAccount(Base):
    __tablename__ = "user_account"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
