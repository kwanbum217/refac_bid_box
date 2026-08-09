"""
scripts/rebuild_institution_stats.py

기관별 낙찰률 사전 집계를 수동으로 다시 만듭니다.

평소에는 야간 스케줄(`_rebuild_institution_stats`)이 갱신합니다. 데이터를
대량 적재한 직후나 **스케줄이 한동안 돌지 않은 것을 확인했을 때** 씁니다.

이 표가 뒤처지면 조용히 틀립니다. 추론 경로는 `institution_win_rate_stats`
를 유니크 키로 조회하는데, 없는 기관은 이력 없음으로 처리돼 예측이 기본값
쪽으로 끌려갑니다. 오류가 나지 않으므로 화면만 보면 알 수 없습니다.

순위 스냅샷에는 `make rebuild-rankings` 가 있는데 이쪽에는 없어서 추가했습니다.

실행:
    make rebuild-institution-stats
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import InstitutionWinRateStat  # noqa: E402
from src.ml.institution_history import rebuild_institution_stats  # noqa: E402


def _snapshot(session) -> tuple[int, str]:
    rows = session.execute(select(func.count(InstitutionWinRateStat.id))).scalar_one()
    latest = session.execute(select(func.max(InstitutionWinRateStat.rebuilt_at))).scalar()
    return int(rows), str(latest) if latest else "-"


def main() -> int:
    session = SessionLocal()
    try:
        before_rows, before_at = _snapshot(session)
        print(f"이전: {before_rows:,}행 / 갱신 시각 {before_at}")

        started = time.perf_counter()
        outcome = rebuild_institution_stats(session)
        session.commit()

        after_rows, after_at = _snapshot(session)
        print(f"이후: {after_rows:,}행 / 갱신 시각 {after_at}")
        print(f"증감 {after_rows - before_rows:+,}행 / {time.perf_counter() - started:.0f}초")
        print(f"반환: {outcome}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
