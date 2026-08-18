#!/usr/bin/env python3
"""
호스트 MariaDB(3307) 와 컨테이너 MySQL 8(3306) 의 내용을 대조합니다.

`AGENTS.md` 는 MySQL 8 Docker 통일과 이중화 제거를 규정합니다. 그런데 호스트
`.env` 는 로컬 MariaDB 를, 컨테이너는 Docker MySQL 을 봅니다. **호스트에서 잰
값이 운영 경로와 다른 DB 를 본다는 뜻이라** 측정이 조용히 어긋납니다. KB
커버리지 작업에서 `source_bid_count` 가 499,195 대 500 으로 갈린 것이 그
사례입니다.

이중화를 없애려면 **먼저 무엇이 다른지 확정해야 합니다.** 한쪽에만 있는 행이
있는데 전환하면 데이터 무손실(G1)이 깨집니다. 이 스크립트는 읽기만 합니다.

대조 항목입니다.

    테이블 목록      한쪽에만 있는 테이블
    행 수            테이블별 COUNT(*)
    최신 시각        시간 컬럼이 있는 테이블의 MAX
    스키마           컬럼 이름·타입 (기본 대상 테이블)

사용법:
    .venv/bin/python scripts/compare_host_container_db.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

# 시간 컬럼이 있는 테이블입니다. 최신 시각이 갈리면 한쪽만 갱신되고 있다는
# 뜻이라 행 수가 같아도 내용이 다릅니다.
TIME_COLUMNS = {
    "bid_announcements": "bid_ntce_dt",
    "bid_results": "rl_openg_dt",
    "retrain_logs": "created_at",
    "model_registry": "created_at",
}

# 스키마까지 보는 테이블입니다. 전량을 보면 출력이 길어 판정이 흐려집니다.
SCHEMA_TABLES = ("bid_announcements", "bid_results", "model_registry")

# 컨테이너 MySQL 은 호스트 MariaDB 와 계정이 다릅니다. 포트만 바꾸면 인증에서
# 막힙니다. 이 값은 `docker-compose.yml` 의 db 서비스 설정 그대로이고 로컬
# 개발용이라 저장소에 이미 평문으로 있습니다.
CONTAINER_URL_DEFAULT = "mysql+pymysql://root:rootpassword@127.0.0.1:3306/procurement"


def make_engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def table_rows(engine) -> pd.Series:
    names = pd.read_sql(text("SHOW TABLES"), engine).iloc[:, 0].tolist()
    counts = {}
    for name in names:
        # 테이블명은 SHOW TABLES 결과라 외부 입력이 아닙니다.
        counts[name] = int(
            pd.read_sql(text(f"SELECT COUNT(*) AS n FROM `{name}`"), engine).iloc[0, 0]  # noqa: S608  # nosec B608 - 사용자 입력이 아니라 내부 테이블 및 컬럼명으로 조립합니다
        )
    return pd.Series(counts, name="rows")


def latest_times(engine) -> dict[str, str]:
    result = {}
    for table, column in TIME_COLUMNS.items():
        try:
            value = pd.read_sql(
                text(f"SELECT MAX(`{column}`) AS m FROM `{table}`"),  # noqa: S608  # nosec B608 - 사용자 입력이 아니라 내부 테이블 및 컬럼명으로 조립합니다
                engine,
            ).iloc[0, 0]
        except Exception:
            value = None
        result[table] = str(value) if value is not None else "-"
    return result


def schema_of(engine, database: str) -> pd.DataFrame:
    sql = """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = :db AND TABLE_NAME IN :tables
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    return pd.read_sql(text(sql).bindparams(tables=SCHEMA_TABLES), engine, params={"db": database})


def verdict_exit_code(row_diff: pd.DataFrame, schema_mismatch: pd.DataFrame) -> int:
    """차이가 하나라도 있으면 1 을 돌려줍니다.

    종전에는 차이를 화면에 출력하면서도 항상 0 을 반환했습니다. 자동화가 이
    스크립트를 호출하면 DB 불일치가 통과로 승격되어 G1 을 위반합니다.
    """
    if row_diff.empty and schema_mismatch.empty:
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--container-url",
        default=CONTAINER_URL_DEFAULT,
        help="컨테이너 MySQL 접속 URL. 기본값은 docker-compose.yml 의 db 서비스 설정",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    host_url = os.environ["DATABASE_URL"]
    container_url = args.container_url
    if host_url == container_url:
        print("호스트 DATABASE_URL 이 이미 컨테이너 DB 를 가리킵니다. 이중화가 해소된 상태입니다.")
        return 0

    host, container = make_engine(host_url), make_engine(container_url)

    host_rows, container_rows = table_rows(host), table_rows(container)
    frame = (
        pd.concat([host_rows.rename("호스트 3307"), container_rows.rename("컨테이너 3306")], axis=1)
        .fillna(-1)
        .astype(int)
    )
    frame["차이"] = frame["컨테이너 3306"] - frame["호스트 3307"]

    print("=" * 78)
    print("테이블별 행 수 (-1 은 그쪽에 테이블 없음)")
    print("=" * 78)
    print(frame.to_string())

    diff = frame[frame["차이"] != 0]
    print(f"\n다른 테이블 {len(diff)}개 / 전체 {len(frame)}개")

    print("\n" + "=" * 78)
    print("최신 시각")
    print("=" * 78)
    times = pd.DataFrame(
        {"호스트 3307": latest_times(host), "컨테이너 3306": latest_times(container)}
    )
    print(times.to_string())

    database = host_url.rsplit("/", 1)[-1].split("?")[0]
    host_schema, container_schema = schema_of(host, database), schema_of(container, database)
    merged = host_schema.merge(
        container_schema,
        on=["TABLE_NAME", "COLUMN_NAME"],
        how="outer",
        suffixes=("_호스트", "_컨테이너"),
        indicator=True,
    )
    mismatch = merged[
        (merged["_merge"] != "both")
        | (merged["COLUMN_TYPE_호스트"] != merged["COLUMN_TYPE_컨테이너"])
    ]

    print("\n" + "=" * 78)
    print(f"스키마 차이 ({', '.join(SCHEMA_TABLES)})")
    print("=" * 78)
    print(mismatch.to_string(index=False) if not mismatch.empty else "(없음)")

    print("\n" + "=" * 78)
    if diff.empty and mismatch.empty:
        print("두 DB 가 동일합니다. 호스트 DATABASE_URL 을 3306 으로 옮겨도 손실이 없습니다.")
    else:
        print("차이가 있습니다. 전환 전에 위 항목을 해소해야 합니다 (G1).")
    return verdict_exit_code(diff, mismatch)


if __name__ == "__main__":
    raise SystemExit(main())
