"""최근 데이터 추가 학습의 이득을 쌍대로 잰다.

같은 평가 구간 [eval_start, eval_end] 에 대해
  stale: eval_start 보다 gap 만큼 앞선 컷까지만 학습
  fresh: eval_start 직전까지 학습
두 모델의 공고별 절대오차 차이로 쌍대 t 를 낸다. 1년 전 동기간 대조군을 함께 낸다.
학습은 eval_servc_regime_lwlt_levels.fit_operational 의 운영 3단계(시간순 분할,
조기 종료, 전량 재적합)를 그대로 쓴다. DB 없이 parquet 만 읽으며 약 15분 걸린다.

사용법:
    uv run python scripts/eval_servc_freshness.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.eval_servc_regime_lwlt_levels import build_frame, fit_operational  # noqa: E402
from src.ml.trainer import TRAINING_FEATURES  # noqa: E402

PARQUET = Path("data/feature_store/servc_rebuild_20260915/dataset_Servc.parquet")
SPLITS = [
    ("신제도 (stale=2026-05-26, fresh=2026-07-20)", "2026-05-26", "2026-07-20", "2026-09-14 23:59"),
    (
        "대조군 1년 전 (stale=2025-05-26, fresh=2025-07-20)",
        "2025-05-26",
        "2025-07-20",
        "2025-09-14 23:59",
    ),
    (
        "신제도 짧은 간격 (stale=2026-06-23, fresh=2026-07-20)",
        "2026-06-23",
        "2026-07-20",
        "2026-09-14 23:59",
    ),
]


def paired(err_a: np.ndarray, err_b: np.ndarray) -> tuple[float, float]:
    d = np.abs(err_b) - np.abs(err_a)
    se = d.std(ddof=1) / np.sqrt(len(d))
    return float(d.mean()), float(d.mean() / se)


def main() -> int:
    t0 = time.perf_counter()
    frame = build_frame(PARQUET)
    print(f"프레임 {len(frame):,}행 {time.perf_counter() - t0:.0f}초")
    features = list(TRAINING_FEATURES)
    for title, stale_cut, fresh_cut, end in SPLITS:
        stale_cut, fresh_cut, end = map(pd.Timestamp, (stale_cut, fresh_cut, end))
        valid = frame[(frame.openg_dt >= fresh_cut) & (frame.openg_dt <= end)]
        y = valid.winning_rate.to_numpy(float)
        preds = {}
        for name, cut in (("stale", stale_cut), ("fresh", fresh_cut)):
            model = fit_operational(frame[frame.openg_dt < cut], features)
            preds[name] = np.asarray(model.predict(valid[features]), float) - y
        lw = valid.raw_lwlt.notna().to_numpy()
        print(f"\n=== {title} / 평가 {len(valid):,}행 ===")
        for label, mask in (
            ("전체", np.ones(len(y), bool)),
            ("하한율 보유", lw),
            ("하한율 결측", ~lw),
        ):
            a, b = preds["stale"][mask], preds["fresh"][mask]
            diff, t = paired(a, b)
            print(
                f"{label:8s} n={mask.sum():6d} MAE stale {np.abs(a).mean():.4f} fresh {np.abs(b).mean():.4f} "
                f"차이 {diff:+.4f} t={t:+.2f} 적중0.5 stale {(np.abs(a) <= 0.5).mean() * 100:.2f} fresh {(np.abs(b) <= 0.5).mean() * 100:.2f} "
                f"편향 stale {a.mean():+.4f} fresh {b.mean():+.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
