#!/usr/bin/env python3
"""
두 모델을 운영 API 경로에서 쌍대 비교하되 **집단별로 분해**합니다.

`compare_servc_models_paired.py` 는 전체 한 덩어리로만 판정합니다. 그것만으로는
전체가 우세해도 특정 집단에서 회귀하는 경우를 놓칩니다. 실제로 huber alpha=0.5
후보는 전체에서 우세했지만 기관 이력이 얕은 12,339건에서 t=2.69 로 악화해
기각됐습니다.

**판정은 우세 집단의 개수가 아니라 비중으로 합니다.** 최근 구간 가중 실험에서
반감기 730일은 8개 모집단 중 4개에서 우세했지만 우세 구간의 합계 비중이 21.9%
였고 열세인 단일 구간이 61.8% 였습니다. 승률이 아니라 가중 합계가 판정입니다.

여러 집단을 동시에 검정하므로 t 임계값을 본페로니 보정으로 올립니다. 보정 없이
개별 2.0 을 쓰면 집단 수만큼 위양성이 늘어납니다.

예측 결과는 parquet 으로 남겨 재분석에 예측을 다시 돌리지 않게 합니다.

사용법:
    .venv/bin/python scripts/compare_servc_models_by_group.py \\
        --base servc_base_huber --challenger servc_quantile_v2 \\
        --model-root /tmp/model_root_ab --samples 9000
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from statistics import NormalDist

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.compare_servc_models_paired import predict_one  # noqa: E402
from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.ml.dataset import announcement_feature_payload  # noqa: E402
from src.ml.features import _coerce_float, build_default_feature_map  # noqa: E402
from src.ml.model_registry import ModelRegistry  # noqa: E402

# 기관 이력이 얕다고 보는 표본 수. analyze_servc_error_concentration.py 와 같은 값을
# 씁니다. 두 스크립트가 다른 경계를 쓰면 셀 판정이 서로 어긋납니다.
SHALLOW_HISTORY_MAX = 50

# 집단을 판정 대상으로 삼는 최소 표본. 이보다 적으면 표준오차가 커서 어떤 차이도
# 잡지 못하므로 판정 대신 참고로만 출력합니다.
MIN_GROUP_ROWS = 200


def group_labels(session, bid_id: int) -> dict[str, str]:
    """공고 한 건의 집단 라벨입니다. 특징 생성은 운영과 같은 함수를 씁니다.

    `inst_sample_cnt` 는 원시 payload 에 없고 기관 이력을 조회해 만드는 파생
    특징이라 `build_default_feature_map` 을 거쳐야 합니다. 여기서 직접 집계하면
    운영 경로와 값이 갈릴 수 있습니다.
    """
    bid = session.get(BidAnnouncement, int(bid_id))
    if bid is None:
        return {}
    payload = announcement_feature_payload(bid)
    feature_map = build_default_feature_map(payload, session)
    sample_cnt = _coerce_float(feature_map.get("inst_sample_cnt"), 0.0)
    return {
        # lwlt_rate 0.0 은 결측으로 봅니다. 하한율이 존재하는 제도라면 0 이 나올 수
        # 없고, compare_servc_models_paired.py 의 --require-lwlt 와 같은 기준입니다.
        "하한율": "보유" if payload.get("lwlt_rate") else "결측",
        "용역구분": str(payload.get("srvce_div_nm") or "미상"),
        "기관이력": "얕음" if sample_cnt < SHALLOW_HISTORY_MAX else "두꺼움",
    }


def _sign_test_pvalue(wins: int, decided: int) -> float:
    """부호 검정의 양측 p 값입니다. 연속성 보정을 넣은 정규근사를 씁니다.

    이항분포 정확검정을 쓰려면 scipy 가 필요한데 이 프로젝트의 선언된 의존성이
    아닙니다(sklearn 의 전이 의존일 뿐입니다). 집단당 표본이 최소 수백 건이라
    근사 오차가 판정을 바꾸지 않습니다.
    """
    if decided <= 0:
        return float("nan")
    deviation = max(abs(wins - decided / 2) - 0.5, 0.0)
    z = deviation / np.sqrt(decided / 4)
    return 2 * (1 - NormalDist().cdf(z))


def paired_verdict(part: pd.DataFrame, t_threshold: float) -> dict:
    """쌍대 절대오차 차이의 통계량입니다. diff = challenger - base 입니다."""
    diff = (part["chal_err"] - part["base_err"]).to_numpy(dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    mean = float(diff.mean()) if n else np.nan
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0

    if n < MIN_GROUP_ROWS:
        verdict = "표본 부족"
    elif abs(t) < t_threshold:
        verdict = "판별 불가"
    elif mean < 0:
        verdict = "challenger 우세"
    else:
        verdict = "base 우세"

    # 부호 검정입니다. 평균은 소수의 큰 오차에 끌려가지만 승률은 그렇지 않아,
    # L1 최적화처럼 다수를 조금씩 개선하는 변경을 따로 볼 수 있습니다.
    wins = int((part["chal_err"] < part["base_err"]).sum())
    ties = int((part["chal_err"] == part["base_err"]).sum())
    decided = len(part) - ties
    win_rate = wins / decided if decided else np.nan
    sign_p = _sign_test_pvalue(wins, decided)

    return {
        "n": n,
        "base MAE": round(float(part["base_err"].mean()), 4),
        "chal MAE": round(float(part["chal_err"].mean()), 4),
        "차이": round(mean, 5),
        "t": round(t, 2),
        "승률": round(win_rate, 4),
        "부호 p": f"{sign_p:.2e}" if np.isfinite(sign_p) else "-",
        "판정": verdict,
    }


def axis_report(df: pd.DataFrame, axis: str, t_threshold: float) -> pd.DataFrame:
    rows = []
    total = len(df)
    for value, part in df.groupby(axis, observed=True):
        row = {"집단": f"{axis}={value}", "비중": round(len(part) / total, 4)}
        row.update(paired_verdict(part, t_threshold))
        rows.append(row)
    return pd.DataFrame(rows).sort_values("비중", ascending=False)


def weighted_summary(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """축별로 우세·열세 비중을 합산합니다. 개수가 아니라 이것이 판정입니다."""
    rows = []
    for table in tables:
        axis = table["집단"].iloc[0].split("=")[0]
        by_verdict = table.groupby("판정")["비중"].sum()
        rows.append(
            {
                "축": axis,
                "challenger 우세 비중": round(float(by_verdict.get("challenger 우세", 0.0)), 4),
                "base 우세 비중": round(float(by_verdict.get("base 우세", 0.0)), 4),
                "판별 불가 비중": round(float(by_verdict.get("판별 불가", 0.0)), 4),
                "표본 부족 비중": round(float(by_verdict.get("표본 부족", 0.0)), 4),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--samples", type=int, default=9000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--category", default="Servc")
    parser.add_argument("--model-root", default=None)
    parser.add_argument(
        "--out",
        default=None,
        help="예측 결과 parquet 경로. 지정하면 저장해 재분석에 씁니다",
    )
    parser.add_argument(
        "--from-parquet",
        default=None,
        help="저장된 예측 결과로 집계만 다시 합니다. 예측을 돌리지 않습니다",
    )
    args = parser.parse_args()

    if args.from_parquet:
        df = pd.read_parquet(args.from_parquet)
        print(f"저장된 예측 {len(df):,}건으로 집계합니다: {args.from_parquet}\n")
    else:
        if args.model_root:
            model_root = Path(args.model_root).resolve()
            if not model_root.is_dir():
                print(f"비교용 모델 루트가 없습니다: {model_root}")
                return 1
            ModelRegistry._get_model_root = classmethod(lambda cls: str(model_root))
            ModelRegistry.load_all_models()

        session = SessionLocal()
        try:
            frame = collect(session, args.year, args.samples, args.seed, args.category)
            if frame.empty:
                print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
                return 1
            print(
                f"{args.year}년 {args.category} {len(frame):,}건에 "
                f"두 모델을 같은 순서로 호출합니다.\n"
                f"  base       {args.base}\n"
                f"  challenger {args.challenger}\n"
            )

            records = []
            for row in frame.itertuples():
                a = predict_one(session, row.bid_id, args.base)
                b = predict_one(session, row.bid_id, args.challenger)
                if a is None or b is None:
                    continue
                labels = group_labels(session, row.bid_id)
                if not labels:
                    continue
                actual = float(row.actual_rate)
                records.append(
                    {
                        "actual": actual,
                        "base_err": abs(a["pred"] - actual),
                        "chal_err": abs(b["pred"] - actual),
                        **labels,
                    }
                )
        finally:
            session.close()

        if not records:
            print("채점 가능한 표본이 없습니다.")
            return 1
        df = pd.DataFrame(records)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(args.out, index=False)
            print(f"예측 결과를 저장했습니다: {args.out}")

    axes = ["하한율", "용역구분", "기관이력"]
    tables = []
    group_count = 0
    for axis in axes:
        group_count += df[axis].nunique()

    # 본페로니 보정입니다. 검정하는 집단 수만큼 개별 유의수준을 나눕니다.
    t_threshold = NormalDist().inv_cdf(1 - 0.05 / (2 * max(group_count, 1)))
    print(f"채점 {len(df):,}건 / 검정 집단 {group_count}개")
    print(f"본페로니 보정 t 임계값: {t_threshold:.2f} (개별 2.0 대신 이 값을 씁니다)\n")

    print(f"{'=' * 100}\n전체\n{'=' * 100}")
    overall = pd.DataFrame([{"집단": "전체=전체", "비중": 1.0, **paired_verdict(df, 2.0)}])
    print(overall.to_string(index=False))
    print("\n주의: 전체 판정에는 보정 없는 t=2.0 을 씁니다. 검정이 하나뿐이기 때문입니다.")

    for axis in axes:
        table = axis_report(df, axis, t_threshold)
        tables.append(table)
        print(f"\n{'=' * 100}\n{axis}별\n{'=' * 100}")
        print(table.to_string(index=False))

    print(f"\n{'=' * 100}\n비중 가중 합산 (개수가 아니라 이것이 판정입니다)\n{'=' * 100}")
    print(weighted_summary(tables).to_string(index=False))

    regressed = [
        row["집단"]
        for table in tables
        for _, row in table.iterrows()
        if row["판정"] == "base 우세"
    ]
    print()
    if regressed:
        print(f"회귀 집단이 있습니다: {', '.join(regressed)}")
    else:
        print("보정 임계값을 넘겨 악화한 집단은 없습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
