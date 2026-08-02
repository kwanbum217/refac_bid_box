from collections.abc import Generator

from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.app.core.config import settings

# MySQL 8에서는 BIGINT AUTO_INCREMENT 그대로, SQLite(테스트)에서만 INTEGER로 변형해
# AUTOINCREMENT 가 동작하도록 합니다. 운영 DDL은 원본과 동일하게 유지됩니다.
PKBigInteger = BigInteger().with_variant(Integer, "sqlite")

# 원본 Django TextField 는 MySQL/MariaDB 에서 LONGTEXT(4GB)로 생성됩니다.
# SQLAlchemy 기본 Text 는 TEXT(64KB)라 그대로 쓰면 스키마가 원본보다 좁아지고,
# 이 선언으로 autogenerate 를 돌리면 기존 값을 잘라내는 DDL 이 만들어집니다.
LongText = Text().with_variant(mysql.LONGTEXT, "mysql", "mariadb")

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
