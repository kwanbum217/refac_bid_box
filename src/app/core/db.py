from collections.abc import Generator

from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.app.core.config import settings

# MySQL 8에서는 BIGINT AUTO_INCREMENT 그대로, SQLite(테스트)에서만 INTEGER로 변형해
# AUTOINCREMENT 가 동작하도록 합니다. 운영 DDL은 원본과 동일하게 유지됩니다.
PKBigInteger = BigInteger().with_variant(Integer, "sqlite")

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
