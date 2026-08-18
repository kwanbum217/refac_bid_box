"""
scripts/eval_servc_segment_conformal.py

세그먼트별 등각예측 배율 검토.

전역 배율 하나로 10억 이상 구간과 하한율 결측 구간을 감당할 수 있는지
확인합니다. 보정 전 측정에서 두 구간의 피복률이 66.85% / 70.04% 로
낮았기 때문에 세그먼트별 배율이 필요한지가 쟁점이었습니다.

재학습은 하지 않습니다. 이미 승격된 분위 모델로 예측만 다시 뽑아
학습기와 같은 보정 구간에서 세그먼트별 배율을 산정합니다.

결론은 기각입니다. 상세는 docs/design/servc_prediction_interval_20260804.md 7장.

실행: PYTHONPATH=. .venv/bin/python scripts/eval_servc_segment_conformal.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.features import (  # noqa: E402
    apply_categorical_dtypes,
    build_feature_frame,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    CALIBRATION_SPLIT,
    DEFAULT_VALIDATION_SPLIT,
    INTERVAL_TARGET_COVERAGE,
    TRAINING_FEATURES,
    _conformal_scale,
    _time_based_split,
)

d = Path("data/model_files/servc_institution_v1")
meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
q10, q90 = joblib.load(d / "model_q10.bin"), joblib.load(d / "model_q90.bin")
GLOBAL = meta["interval"]["conformal_scale"]

raw = attach_repeat_history(
    attach_institution_history(pd.read_parquet("data/feature_store/dataset_Servc.parquet"))
)
feat = apply_categorical_dtypes(
    pd.DataFrame(build_feature_frame(raw.to_dict(orient="records"))), meta["category_levels"]
)
feat["openg_dt"] = raw["openg_dt"].to_numpy()
y = raw["winning_rate"].to_numpy()
print("특징 생성 완료", flush=True)

tr, va, _, _ = _time_based_split(feat, y, DEFAULT_VALIDATION_SPLIT)
cal_start = int(len(tr) * (1 - CALIBRATION_SPLIT))
cal = tr[cal_start:]


def bounds(idx):
    X = feat[TRAINING_FEATURES].iloc[idx]
    a, b = q10.predict(X), q90.predict(X)
    return np.minimum(a, b), np.maximum(a, b)


lo_c, hi_c = bounds(cal)
lo_v, hi_v = bounds(va)
print("예측 완료", flush=True)


def seg_of(idx):
    f = feat.iloc[idx]
    price = f["real_budget"].to_numpy()
    band = np.select(
        [price < 1e7, price < 5e7, price < 1e8, price < 2.3e8, price < 1e9],
        ["1천만미만", "1천만~5천만", "5천만~1억", "1억~2.3억", "2.3억~10억"],
        "10억이상",
    )
    lw = np.where(f["lwlt_rate_missing"].to_numpy() == 1, "하한율결측", "하한율보유")
    return band, lw


bc, lc = seg_of(cal)
bv, lv = seg_of(va)
yc, yv = y[cal], y[va]


def cover(y_, lo, hi, s):
    c, h = (lo + hi) / 2, (hi - lo) / 2 * s
    return np.mean((y_ >= c - h) & (y_ <= c + h)), np.median(2 * h)


rows = []
for name, keys_c, keys_v in (("금액구간", bc, bv), ("하한율", lc, lv)):
    for key in pd.unique(keys_v):
        mc, mv = keys_c == key, keys_v == key
        if mc.sum() < 500 or mv.sum() < 200:
            continue
        s = _conformal_scale(yc[mc], lo_c[mc], hi_c[mc], INTERVAL_TARGET_COVERAGE)
        g_cov, g_w = cover(yv[mv], lo_v[mv], hi_v[mv], GLOBAL)
        s_cov, s_w = cover(yv[mv], lo_v[mv], hi_v[mv], s)
        rows.append(
            {
                "구분": name,
                "세그먼트": key,
                "검증건수": int(mv.sum()),
                "전역배율": round(GLOBAL, 3),
                "전역피복": round(g_cov, 4),
                "전역폭": round(g_w, 3),
                "세그배율": round(s, 3),
                "세그피복": round(s_cov, 4),
                "세그폭": round(s_w, 3),
            }
        )
out = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(f"\n보정 {len(cal):,}건 / 검증 {len(va):,}건, 목표 {INTERVAL_TARGET_COVERAGE:.0%}\n")
print(out.to_string(index=False))
