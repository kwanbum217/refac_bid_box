"""SQLite와 MySQL의 결과 의미가 달라지는 핵심 질의 통합 검증입니다."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

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
    # MySQL 8 은 only_full_group_by 위반을 OperationalError 1055 로 돌려줍니다.
    # 1140 은 집계 함수와 비집계 컬럼을 GROUP BY 없이 섞었을 때의 코드라
    # 이 질의에는 해당하지 않습니다. 2026-09-02 에 실제 MySQL 8 로 확인했습니다.
    with mysql_engine.connect() as connection, pytest.raises(OperationalError) as error:
        connection.execute(
            text("SELECT category, dminstt_nm, COUNT(*) FROM bid_announcements GROUP BY category")
        )
    assert error.value.orig.args[0] == 1055


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


def test_mysql_amount_column_aggregation_and_cast_dialects(mysql_engine: Engine) -> None:
    """MySQL 8 방언에서 base_amount 집계 표현식과 금액 파싱(20자리, 소수점, 콤마, 상한초과, NULL)을 검증합니다.

    SQLite 와 MySQL 간의 CAST(DECIMAL(30,0)) 및 BIGINT 범위 처리 차이를 방어합니다:
    1. 20자리 값: DECIMAL(30,0) 캐스팅 시 오버플로우 없이 100조 상한 필터에 걸려 NULL 처리
    2. 소수점 표기: MySQL CAST(DECIMAL(30,0)) 동작 확인 및 절단 적재 컬럼값과의 차이 검증
    3. 콤마 포함 표기: REPLACE 후 DECIMAL 캐스팅 정상 동작 확인
    4. 상한 초과(100조 초과): CASE WHEN 문으로 정확히 NULL 제외 확인
    5. NULL: SUM 집계 시 오류 없이 무시됨 확인
    """
    with mysql_engine.connect() as connection:
        # (1) MySQL CAST 방언 및 문자열 파싱 동작 검증
        row = (
            connection.execute(
                text(
                    """
                SELECT
                    -- 20자리 값 DECIMAL 캐스팅
                    CAST('12240000012240000011' AS DECIMAL(30, 0)) AS val_20digit,
                    -- 소수점 표기 DECIMAL 캐스팅
                    CAST('3469575370.8' AS DECIMAL(30, 0)) AS val_fraction,
                    -- 콤마 포함 표기
                    CAST(REPLACE('1,234,567', ',', '') AS DECIMAL(30, 0)) AS val_comma
                """
                )
            )
            .mappings()
            .one()
        )

        assert int(row["val_20digit"]) == 12240000012240000011
        assert int(row["val_fraction"]) == 3469575371
        assert int(row["val_comma"]) == 1234567

        # (2) base_amount 컬럼 기반 집계 표현식 검증 (20자리 포화, 상한초과, 정상, 절단, NULL)
        agg_result = (
            connection.execute(
                text(
                    """
                WITH test_cases AS (
                    -- 정상 공고 (150만)
                    SELECT 1500000 AS base_amount, '정상' AS label
                    UNION ALL
                    -- 20자리 원본으로 인한 BIGINT 포화값 (922경 -> 100조 초과로 제외)
                    SELECT 9223372036854775807 AS base_amount, '포화건' AS label
                    UNION ALL
                    -- 100조 초과 자릿수 반복 이상치 (137경 -> 100조 초과로 제외)
                    SELECT 137150000137150000 AS base_amount, '상한초과' AS label
                    UNION ALL
                    -- 소수점 절단 적재값 (34억)
                    SELECT 3469575370 AS base_amount, '소수점절단' AS label
                    UNION ALL
                    -- 콤마 제거 적재값 (123만)
                    SELECT 1234567 AS base_amount, '콤마정제' AS label
                    UNION ALL
                    -- raw 0.0 또는 결측으로 인한 NULL
                    SELECT NULL AS base_amount, 'NULL' AS label
                )
                SELECT
                    SUM(
                        CASE
                            WHEN CAST(base_amount AS DECIMAL(30, 0)) > 100000000000000 THEN NULL
                            ELSE CAST(base_amount AS DECIMAL(30, 0))
                        END
                    ) AS total_amount,
                    COUNT(*) AS total_rows,
                    COUNT(base_amount) AS non_null_rows
                FROM test_cases
                """
                )
            )
            .mappings()
            .one()
        )

        # 총 6행 중 NULL 1행 제외 5행 non-null
        assert agg_result["total_rows"] == 6
        assert agg_result["non_null_rows"] == 5

        # 집계 기대치: 1500000 + 3469575370 + 1234567 = 3472309937
        # (포화건 9223372036854775807 및 상한초과건 137150000137150000 은 제외되어야 함)
        expected_total = 1500000 + 3469575370 + 1234567
        assert int(agg_result["total_amount"]) == expected_total
