"""
scripts/rebuild_ranking_snapshots.py

상위 N 집계 스냅샷을 수동으로 다시 만듭니다.

평소에는 야간 스케줄(`nightly_schedule_task`)이 자동으로 갱신합니다. 최초 도입
시점이나 데이터를 대량 적재한 직후처럼 즉시 반영이 필요할 때 씁니다.

주간 차원(`WEEKLY_DIMENSIONS`)은 기본적으로 7일이 지났을 때만 다시 집계합니다.
집계 정의가 바뀌어 주기를 기다리지 않고 새로 만들어야 할 때는 `--force-weekly`
를 붙입니다.

스냅샷이 없으면 조회가 실시간 집계로 넘어가 동작은 하되 느려집니다.

실행:
    make rebuild-rankings
    uv run python scripts/rebuild_ranking_snapshots.py --force-weekly
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.services.ranking_snapshots import (  # noqa: E402
    rebuild_ranking_snapshots,
    snapshot_age,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="상위 N 집계 스냅샷 재집계")
    parser.add_argument(
        "--force-weekly",
        action="store_true",
        help="주간 차원도 주기와 무관하게 다시 집계합니다.",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        previous = snapshot_age(db)
        print(f"직전 갱신: {previous or '없음'}")
        print("재집계 중입니다. 300만 행 집계라 1~2분 걸립니다.")

        started = time.perf_counter()
        outcome = rebuild_ranking_snapshots(db, force_weekly=args.force_weekly)
        elapsed = time.perf_counter() - started

        print(f"완료: {outcome['rows']}행, {elapsed:.1f}초")
        if outcome["deferred_dimensions"]:
            print(f"주기 미도래로 건너뜀: {', '.join(outcome['deferred_dimensions'])}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
