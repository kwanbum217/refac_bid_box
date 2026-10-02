"""나라장터 수요기관 기준정보 전체 또는 증분 수집."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from src.app.core.config import settings  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.services.demand_institutions import collect_and_upsert  # noqa: E402


async def run(mode: str, dry_run: bool) -> dict:
    if not settings.G2B_USRINFO_SERVICE_KEY:
        raise RuntimeError("G2B_USRINFO_SERVICE_KEY 가 설정되지 않았습니다.")
    with SessionLocal() as db:
        return await collect_and_upsert(db, settings.G2B_USRINFO_SERVICE_KEY, mode, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="나라장터 수요기관 기준정보 수집")
    parser.add_argument("--mode", choices=("full", "incremental"), required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="결과 집계만 출력하고 DB 는 쓰지 않습니다."
    )
    args = parser.parse_args()
    result = asyncio.run(run(args.mode, args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
