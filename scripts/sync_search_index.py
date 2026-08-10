"""Meilisearch 검색 읽기 모델의 초기 전체/증분 동기화 CLI."""

from __future__ import annotations

import argparse
from datetime import timedelta

from src.app.core.db import SessionLocal
from src.app.core.timeutil import utcnow
from src.app.services.search_index import sync_search_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Meilisearch 검색 인덱스를 동기화합니다.")
    parser.add_argument(
        "--since-hours", type=int, help="최근 N시간 적재분만 동기화합니다. 미지정 시 전체입니다."
    )
    args = parser.parse_args()
    collected_since = utcnow() - timedelta(hours=args.since_hours) if args.since_hours else None
    db = SessionLocal()
    try:
        counts = sync_search_index(db, collected_since=collected_since)
    finally:
        db.close()
    print(f"검색 인덱스 동기화 완료: 공고 {counts['announcements']}건, 낙찰 {counts['results']}건")


if __name__ == "__main__":
    main()
