#!/usr/bin/env python3
"""
학습 프레임과 서빙 경로가 같은 공고에서 **같은 값**을 만드는지 특징별로 잽니다.

`tests/test_serving_feature_parity.py` 는 서빙 가능 여부(키가 있는가)를 봅니다.
이 스크립트는 한 걸음 더 들어가 **값이 일치하는가**를 봅니다. 키가 있어도 값이
다르면 모델은 학습 때와 다른 입력을 받습니다.

이 대조가 필요한 이유입니다. 2026-08-04~05 에 하이퍼파라미터 두 건과 특징 한
건이 모두 홀드아웃에서 개선되고 운영에서 뒤집혔습니다. 세 번 연속이라 우연으로
보기 어렵고, 홀드아웃 MAE 0.76 과 운영 MAE 0.99 의 30% 격차도 설명되지 않습니다.
`inst_hist_rate` 는 대조해 정합함을 확인했으나(실값 상관 0.986) 나머지는
확인한 적이 없습니다.

주의: 이력 계열 특징은 **전량에 붙인 뒤 잘라내야** 합니다. `attach_*` 함수는
`shift(1).expanding()` 이라 프레임을 연도로 자르면 각 기관의 연초 건이 최소
표본에 걸려 기본값 폴백이 폭증합니다. 이 함정으로 한 번 오진단했습니다
(`servc_rolling_institution_20260805.md` 6.2).

사용법:
    .venv/bin/python scripts/audit_feature_parity_values.py
    .venv/bin/python scripts/audit_feature_parity_values.py --samples 500 --year 2025
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.ml.dataset import announcement_feature_payload  # noqa: E402
from src.ml.features import CATEGORICAL_FEATURES, build_feature_frame  # noqa: E402
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import training_features_for_category  # noqa: E402

# 이 값 미만이면 두 경로가 사실상 다른 특징을 쓰고 있다고 봅니다.
CORRELATION_FLOOR = 0.95
AUDITED_FEATURES = tuple(training_features_for_category("Servc"))
KNOWN_TIMING_LIMITS = {
    "inst_hist_rate": (0.90, 0.01),
    "inst_sample_cnt": (0.85, 250.0),
    "inst_ewm_rate": (0.85, 0.02),
    "is_repeat": (0.90, 0.04),
    "repeat_hist_rate": (0.92, 0.003),
    "repeat_prev_rate": (0.92, 0.003),
    "repeat_hist_std": (0.85, 0.001),
    "repeat_days_since": (0.80, 25.0),
    "ntce_kind_nm": (0.92, None),
}


def build_training_side(parquet: Path, year: int) -> pd.DataFrame:
    """학습기와 같은 순서로 이력을 붙인 뒤 대상 연도를 잘라 냅니다."""
    df = pd.read_parquet(parquet)
    df["category"] = "Servc"
    df = attach_institution_history(df)
    df = attach_repeat_history(df)
    picked = df[pd.to_datetime(df["openg_dt"]).dt.year == year]
    return picked.drop_duplicates("bid_ntce_no", keep="last")


def serving_row(session, bid_ntce_no: str) -> dict | None:
    bid = (
        session.query(BidAnnouncement)
        .filter(
            BidAnnouncement.bid_ntce_no == bid_ntce_no,
            BidAnnouncement.category == "Servc",
        )
        .first()
    )
    if bid is None:
        return None
    payload = announcement_feature_payload(bid)
    # 레코드 리스트를 받아 특징 맵 리스트를 돌려줍니다. dict 를 그대로 넘기면
    # 키 문자열을 순회하다 뒤늦게 터집니다.
    maps = build_feature_frame([payload], session=session)
    return dict(maps[0])


def compare(train_row: pd.Series, serve_row: dict) -> dict[str, tuple]:
    """특징별로 (학습값, 서빙값) 쌍을 돌려줍니다. 없는 키는 건너뜁니다."""
    pairs = {}
    for name in AUDITED_FEATURES:
        if name not in train_row or name not in serve_row:
            continue
        pairs[name] = (train_row[name], serve_row[name])
    return pairs


def summarize(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    rows = []
    for name in AUDITED_FEATURES:
        t_col, s_col = f"{name}__t", f"{name}__s"
        if t_col not in frame.columns:
            continue
        t, s = frame[t_col], frame[s_col]

        if name in CATEGORICAL_FEATURES:
            match = (t.astype("string").fillna("") == s.astype("string").fillna("")).mean()
            rows.append(
                {
                    "특징": name,
                    "종류": "범주",
                    "일치율": round(float(match), 4),
                    "상관": np.nan,
                    "평균절대차": np.nan,
                }
            )
            continue

        t_num = pd.to_numeric(t, errors="coerce")
        s_num = pd.to_numeric(s, errors="coerce")
        both = t_num.notna() & s_num.notna()
        if both.sum() < 2:
            rows.append(
                {
                    "특징": name,
                    "종류": "수치",
                    "일치율": np.nan,
                    "상관": np.nan,
                    "평균절대차": np.nan,
                }
            )
            continue
        corr = t_num[both].corr(s_num[both])
        rows.append(
            {
                "특징": name,
                "종류": "수치",
                "일치율": round(float((t_num[both] - s_num[both]).abs().lt(1e-6).mean()), 4),
                "상관": round(float(corr), 4) if pd.notna(corr) else np.nan,
                "평균절대차": round(float((s_num[both] - t_num[both]).abs().mean()), 5),
            }
        )
    return pd.DataFrame(rows)


def split_differences(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """임계값 미달 특징을 기지 시점 차이와 예상 밖 차이로 나눕니다."""
    numeric_low = (
        (table["종류"] == "수치") & table["상관"].notna() & (table["상관"] < CORRELATION_FLOOR)
    )
    categorical_low = (table["종류"] == "범주") & (table["일치율"] < CORRELATION_FLOOR)
    low = table[numeric_low | categorical_low]
    known_mask = []
    for row in low.itertuples(index=False):
        limits = KNOWN_TIMING_LIMITS.get(row.특징)
        if limits is None:
            known_mask.append(False)
            continue
        min_score, max_difference = limits
        score = row.상관 if row.종류 == "수치" else row.일치율
        score_ok = pd.notna(score) and score >= min_score
        difference_ok = max_difference is None or (
            pd.notna(row.평균절대차) and row.평균절대차 <= max_difference
        )
        known_mask.append(bool(score_ok and difference_ok))
    known = low[known_mask]
    unexpected = low[[not value for value in known_mask]]
    return known, unexpected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    print("학습 프레임 구성 중 (전량에 이력을 붙인 뒤 연도를 자릅니다)")
    train = build_training_side(path, args.year)
    print(f"  {args.year}년 {len(train):,}건")
    train = train.sample(n=min(args.samples * 2, len(train)), random_state=args.seed)

    session = SessionLocal()
    records = []
    try:
        for row in train.itertuples():
            serve = serving_row(session, row.bid_ntce_no)
            if serve is None:
                continue
            train_row = train.loc[row.Index]
            record = {}
            for name, (t_value, s_value) in compare(train_row, serve).items():
                record[f"{name}__t"] = t_value
                record[f"{name}__s"] = s_value
            records.append(record)
            if len(records) >= args.samples:
                break
    finally:
        session.close()

    if not records:
        print("대조 가능한 표본이 없습니다.")
        return 1

    print(f"  대조 {len(records):,}건\n")
    table = summarize(records)
    print(f"{'=' * 96}\n특징별 학습·서빙 값 일치\n{'=' * 96}")
    print(table.to_string(index=False))

    known, unexpected = split_differences(table)

    print(f"\n{'=' * 96}\n판정\n{'=' * 96}")
    if known.empty and unexpected.empty:
        print(
            f"모든 특징이 상관/일치율 {CORRELATION_FLOOR} 이상입니다. 값 불일치는 원인이 아닙니다."
        )
        return 0

    if not known.empty:
        print(f"알려진 시점 차이 {len(known)}개:")
        print(known.to_string(index=False))
        print(
            "\n학습값은 각 과거 공고 직전의 값이고 서빙값은 현재 집계 또는 현재 "
            "공고 원본입니다. 과거 공고를 현재 경로로 재평가할 때 생기는 기지 차이입니다."
        )
    if not unexpected.empty:
        print(f"\n예상 밖 차이 {len(unexpected)}개:")
        print(unexpected.to_string(index=False))
        print("\n새 배관 결함 가능성이 있으므로 원인을 확인해야 합니다.")
    else:
        print("\n예상 밖 차이는 없습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
