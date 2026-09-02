"""SQLite와 MySQL의 결과 의미가 달라지는 핵심 질의 통합 검증입니다."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.mysql_integration


@pytest.fixture(scope="module")
def mysql_engine() -> Engine:
    """CI의 격리 MySQL에 연결하고, MySQL이 없으면 명시적으로 건너뜁니다."""
    url = os.getenv("MYSQL_TEST_URL")
    if not url:
        pytest.skip("MYSQL_TEST_URL이 설정되지 않아 MySQL 통합 테스트를 건너뜁니다.")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        if engine.dialect.name != "mysql":
            pytest.skip("MYSQL_TEST_URL이 MySQL 방언이 아니어서 통합 테스트를 건너뜁니다.")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except Exception as exc:
        pytest.skip(f"MySQL 8 인스턴스에 접속할 수 없어 통합 테스트를 건너뜁니다: {exc}")


def test_mysql_collation_is_case_insensitive_for_text_filters(mysql_engine: Engine) -> None:
    """운영 utf8mb4_unicode_ci 콜레이션의 대소문자 무시 검색 의미를 고정합니다."""
    with mysql_engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT _utf8mb4'BidBox' COLLATE utf8mb4_unicode_ci = "
                "_utf8mb4'bidbox' COLLATE utf8mb4_unicode_ci"
            )
        ).scalar_one()
    assert result == 1


def test_mysql_integer_division_keeps_fraction_for_bid_rate_calculation(
    mysql_engine: Engine,
) -> None:
    """MySQL의 숫자 나눗셈이 정수 절삭 없이 낙찰률 계산값을 보존하는지 확인합니다."""
    with mysql_engine.connect() as connection:
        result = connection.execute(text("SELECT 5 / 2")).scalar_one()
    assert float(result) == pytest.approx(2.5)


def test_mysql_only_full_group_by_rejects_ambiguous_aggregate(mysql_engine: Engine) -> None:
    """SQLite가 임의 값을 반환할 수 있는 모호한 집계를 MySQL이 거부하는지 확인합니다."""
    with mysql_engine.connect() as connection, pytest.raises(ProgrammingError) as error:
        connection.execute(
            text("SELECT category, dminstt_nm, COUNT(*) FROM bid_announcements GROUP BY category")
        )
    assert error.value.orig.args[0] == 1140


def test_mysql_datetime_bucket_uses_mysql_date_function(mysql_engine: Engine) -> None:
    """낙찰·공고 월별 집계에 사용하는 MySQL 날짜 버킷 함수가 실제로 동작하는지 확인합니다."""
    with mysql_engine.connect() as connection:
        result = connection.execute(
            text("SELECT DATE_FORMAT(bid_ntce_dt, '%Y-%m') FROM bid_announcements LIMIT 1")
        ).scalar_one()
    assert result == "2025-06"


def test_mysql_json_extraction_returns_unquoted_scalar(mysql_engine: Engine) -> None:
    """MySQL JSON 추출 결과가 따옴표 없는 스칼라가 되는지 확인합니다."""
    with mysql_engine.connect() as connection:
        result = connection.execute(
            text("SELECT JSON_UNQUOTE(JSON_EXTRACT('{\"category\": \"Servc\"}', '$.category'))")
        ).scalar_one()
    assert result == "Servc"
