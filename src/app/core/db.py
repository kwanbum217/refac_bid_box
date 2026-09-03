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


def open_thread_session() -> tuple[Session, bool]:
    """asyncio.to_thread 로 도는 동기 작업이 쓸 세션을 엽니다.

    두 번째 값은 호출자가 close 를 책임져야 하는지 여부입니다.

    스레드 경로는 FastAPI 의존성 주입을 거치지 않으므로 그대로 두면
    ``app.dependency_overrides[get_db]`` 로 건 격리 DB 를 무시하고 실제 DB 에
    붙습니다. E2E 가 개발 DB 를 오염시키는 경로가 정확히 여기입니다.
    그래서 오버라이드가 걸려 있으면 그것을 따릅니다.

    오버라이드가 제너레이터를 돌려주면 그 정리는 오버라이드 소유이므로
    호출자가 닫지 않습니다.
    """
    from src.app.main import app

    override = app.dependency_overrides.get(get_db)
    if override is not None:
        produced = override()
        if hasattr(produced, "__next__"):
            return next(produced), False
        return produced, True
    return SessionLocal(), True
