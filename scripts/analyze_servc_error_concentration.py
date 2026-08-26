#!/usr/bin/env python3
"""
용역 모델의 오차가 어디에 몰려 있는지 분해합니다.

`diagnose_servc_lwlt_residuals.py --dump-dir` 가 남긴 잔차 parquet 을 읽습니다.
재학습하지 않으므로 초 단위로 끝납니다.

**MAE 가 아니라 오차 총량 기여도로 봅니다.** 어떤 집단의 MAE 가 높아도 건수가
적으면 그 집단을 완벽하게 고쳐도 전체는 거의 안 움직입니다. 어제 최근 구간
가중 실험이 8개 모집단 중 4개에서 우세하고도 기각된 이유가 이것입니다
([`servc_recency_weighting_20260806.md`](../docs/design/servc_recency_weighting_20260806.md)).

그래서 집단마다 세 값을 함께 냅니다.

    건수 비중        그 집단이 전체 표본에서 차지하는 몫
    오차 기여도      그 집단의 절대오차 합계가 전체 절대오차 합계에서 차지하는 몫
    집중 배수        오차 기여도 / 건수 비중. 1 보다 크면 몫보다 많이 틀립니다

여기에 **개선 상한**을 덧붙입니다. 그 집단의 MAE 를 전체 중앙 수준까지 낮춘다고
가정했을 때 전체 MAE 가 얼마나 줄어드는지입니다. 가정이므로 달성 가능한 값이
아니라 **그 집단을 겨냥할 가치가 있는지 판단하는 상한**으로만 씁니다.

사용법:
    .venv/bin/python scripts/analyze_servc_error_concentration.py --dir <잔차 디렉터리>
    .venv/bin/python scripts/analyze_servc_error_concentration.py --dir <경로> --year 2026
"""

from __future__ import annotations

import argparse
import glob
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# 집단 표가 읽히려면 이만큼은 있어야 합니다.
MIN_GROUP_ROWS = 200

# 추정가격 구간. 발주 담당자가 쓰는 임계값(고시금액 2.3억 등)에 맞춥니다.
PRICE_BANDS = [
    ("1천만 미만", 0, 10_000_000),
    ("1천만~5천만", 10_000_000, 50_000_000),
    ("5천만~1억", 50_000_000, 100_000_000),
    ("1억~2.3억", 100_000_000, 230_000_000),
    ("2.3억~10억", 230_000_000, 1_000_000_000),
    ("10억 이상", 1_000_000_000, np.inf),
]

SAMPLE_BANDS = [
    ("0건", 0.0, 1.0),
    ("1~9건", 1.0, 10.0),
    ("10~49건", 10.0, 50.0),
    ("50~199건", 50.0, 200.0),
    ("200건 이상", 200.0, np.inf),
]


def load(dump_dir: Path, year: int | None) -> dict[int, pd.DataFrame]:
    frames: dict[int, pd.DataFrame] = {}
    for path in sorted(glob.glob(str(dump_dir / "servc_residuals_*.parquet"))):
        found = int(Path(path).stem.split("_")[-1])
        if year is not None and found != year:
            continue
        df = pd.read_parquet(path)
        # 금액대는 학습 특징에 없습니다. log_price 로 되돌립니다.
        df["presmpt_prce"] = np.expm1(df["log_price"])
        frames[found] = df
    return frames


def banded(series: pd.Series, bands: Sequence[tuple[str, float, float]]) -> pd.Series:
    """구간 라벨을 붙입니다. 정렬이 유지되도록 범주형 순서를 고정합니다."""
    labels = pd.Series("기타", index=series.index, dtype=object)
    for name, low, high in bands:
        labels[(series >= low) & (series < high)] = name
    order = [name for name, _, _ in bands] + ["기타"]
    return pd.Categorical(labels, categories=order, ordered=True)


def contribution_table(
    valid: pd.DataFrame,
    key: str,
    min_rows: int = MIN_GROUP_ROWS,
) -> pd.DataFrame:
    """집단별 오차 총량 기여도입니다.

    개선 상한은 그 집단의 MAE 를 **전체 중앙값 수준**으로 낮췄다고 가정했을 때
    전체 MAE 가 얼마나 내려가는지입니다. 이미 중앙값보다 잘 맞히는 집단은
    0 이 됩니다. 달성 가능한 값이 아니라 겨냥할 가치의 상한입니다.
    """
    total_rows = len(valid)
    total_abs = float(valid["abs_err"].sum())
    target_mae = float(valid["abs_err"].median())

    rows = []
    for name, part in valid.groupby(key, observed=True):
        if len(part) < min_rows:
            continue
        part_abs = float(part["abs_err"].sum())
        share_rows = len(part) / total_rows
        share_err = part_abs / total_abs
        mae = float(part["abs_err"].mean())
        gain = max(mae - target_mae, 0.0) * len(part) / total_rows
        rows.append(
            {
                key: str(name),
                "건수": len(part),
                "건수 비중": round(share_rows, 4),
                "MAE": round(mae, 4),
                "실제 표준편차": round(float(part["actual"].std()), 3),
                "오차 기여도": round(share_err, 4),
                "집중 배수": round(share_err / share_rows, 2) if share_rows else np.nan,
                "개선 상한": round(gain, 4),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("오차 기여도", ascending=False)


def concentration_curve(valid: pd.DataFrame) -> pd.DataFrame:
    """절대오차 상위 몇 %가 오차 총량의 몇 %를 차지하는지입니다.

    오차가 소수 건에 몰려 있으면 평균을 겨냥한 개선은 효과가 없습니다.
    그 경우 다뤄야 하는 것은 중심이 아니라 꼬리입니다.
    """
    ordered = np.sort(valid["abs_err"].to_numpy())[::-1]
    total = ordered.sum()
    rows = []
    for pct in (1, 5, 10, 20, 50):
        cut = max(int(len(ordered) * pct / 100), 1)
        rows.append(
            {
                "상위": f"{pct}%",
                "건수": cut,
                "오차 총량 비중": round(float(ordered[:cut].sum() / total), 4),
                "이 구간 MAE": round(float(ordered[:cut].mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def cross_table(valid: pd.DataFrame, row_key: str, col_key: str) -> pd.DataFrame:
    """두 축의 교차 셀별 MAE 와 건수입니다.

    한 축만 보면 교란된 관계를 구조로 착각합니다. 예를 들어 하한율 결측 집단이
    어려운 것이 결측 때문인지 그 집단에 고액 건이 몰려서인지는 교차해야 갈립니다.
    """
    pivot_mae = valid.pivot_table(
        index=row_key, columns=col_key, values="abs_err", aggfunc="mean", observed=True
    ).round(3)
    pivot_n = valid.pivot_table(
        index=row_key, columns=col_key, values="abs_err", aggfunc="size", observed=True
    )
    out = pivot_mae.astype(object)
    for r in out.index:
        for c in out.columns:
            n = pivot_n.loc[r, c] if (r in pivot_n.index and c in pivot_n.columns) else 0
            n = 0 if pd.isna(n) else int(n)
            out.loc[r, c] = f"{pivot_mae.loc[r, c]:.3f} (n={n:,})" if n >= 50 else "-"
    return out


def skill_of(part: pd.DataFrame) -> tuple[float, float, float]:
    """셀의 난이도로 정규화한 설명력입니다.

    기준선은 **그 셀 안 실제값의 중앙값으로 예측**했을 때의 MAE 입니다. 셀마다
    본질적 산포가 다르므로 MAE 를 그대로 비교하면 어려운 셀이 항상 나빠 보입니다.
    설명력은 그 난이도를 나눠 없앱니다.

        설명력 = 1 - 모델 MAE / 기준 MAE

    기준선이 셀의 중앙값을 알고 있는 오라클이라 모델에 불리한 엄격한 잣대입니다.
    셀이 작을수록 오라클 이점이 커지므로 작은 셀의 설명력은 낮게 나옵니다.
    """
    naive = float((part["actual"] - part["actual"].median()).abs().mean())
    mae = float(part["abs_err"].mean())
    return naive, mae, (1 - mae / naive) if naive > 0 else np.nan


def cell_skill_table(valid: pd.DataFrame, min_rows: int = MIN_GROUP_ROWS) -> pd.DataFrame:
    """용역구분 x 하한율 x 이력 깊이 셀별 설명력입니다.

    MAE 순위와 설명력 순위는 다릅니다. MAE 만 보고 겨냥하면 본질적으로 어려운
    셀을 고르게 되고, 그 셀은 이미 난이도 대비로는 잘 맞히고 있을 수 있습니다.
    """
    valid = valid.copy()
    valid["이력"] = np.where(valid["inst_sample_cnt"] < 50, "얕음", "두꺼움")
    rows = []
    for keys, part in valid.groupby(["srvce_div_nm", "lwlt_group", "이력"], observed=True):
        if len(part) < min_rows:
            continue
        naive, mae, skill = skill_of(part)
        rows.append(
            {
                "셀": "/".join(map(str, keys)),
                "건수": len(part),
                "건수 비중": round(len(part) / len(valid), 4),
                "기준 MAE": round(naive, 3),
                "모델 MAE": round(mae, 3),
                "설명력": round(skill, 3),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("설명력")


def shallow_history_upper_bound(valid: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """얕은 이력 셀을 같은 조건 두꺼운 셀의 설명력까지 올렸다고 가정한 상한입니다.

    **달성 가능한 값이 아닙니다.** 이력이 얕다는 것은 정보가 적다는 뜻이므로
    두꺼운 셀과 같은 설명력이 원리상 불가능할 수 있습니다. 이 표는 그 방향을
    겨냥할 가치가 있는지 판단하는 상한으로만 씁니다.
    """
    table = cell_skill_table(valid).set_index("셀")
    total = len(valid)
    gain = 0.0
    rows = []
    for div in valid["srvce_div_nm"].dropna().unique():
        for lwlt in ("보유", "결측"):
            shallow, deep = f"{div}/{lwlt}/얕음", f"{div}/{lwlt}/두꺼움"
            if shallow not in table.index or deep not in table.index:
                continue
            # 두꺼운 셀이 오히려 못 맞히면 목표를 현 수준으로 둡니다. 음의 개선을
            # 상한이라고 부를 수는 없습니다.
            target = max(table.loc[deep, "설명력"], table.loc[shallow, "설명력"])
            new_mae = table.loc[shallow, "기준 MAE"] * (1 - target)
            contribution = (
                (table.loc[shallow, "모델 MAE"] - new_mae) * table.loc[shallow, "건수"] / total
            )
            gain += contribution
            rows.append(
                {
                    "셀": shallow,
                    "건수": int(table.loc[shallow, "건수"]),
                    "현 MAE": round(table.loc[shallow, "모델 MAE"], 3),
                    "목표 MAE": round(new_mae, 3),
                    "전체 기여": round(contribution, 4),
                }
            )
    return pd.DataFrame(rows).sort_values("전체 기여", ascending=False), gain


def report(title: str, frame: pd.DataFrame | str, index: bool = False) -> None:
    print(f"\n{'=' * 108}\n{title}\n{'=' * 108}")
    if isinstance(frame, str):
        print(frame)
    elif frame.empty:
        print("표본이 부족해 표를 만들지 않았습니다.")
    else:
        print(frame.to_string(index=index))


def analyze(valid: pd.DataFrame, year: int) -> None:
    valid = valid.copy()
    valid["금액대"] = banded(valid["presmpt_prce"], PRICE_BANDS)
    valid["기관 이력"] = banded(valid["inst_sample_cnt"], SAMPLE_BANDS)
    valid["재발주"] = np.where(valid["is_repeat"] > 0, "재발주", "신규")

    total_mae = float(valid["abs_err"].mean())
    report(
        f"[{year}] 0. 전체",
        f"{len(valid):,}건 / MAE {total_mae:.4f} / "
        f"절대오차 중앙값 {float(valid['abs_err'].median()):.4f}\n"
        f"하한율 결측 {int((valid['lwlt_group'] == '결측').sum()):,}건 "
        f"({(valid['lwlt_group'] == '결측').mean():.1%})",
    )

    report(f"[{year}] 1. 오차 집중도", concentration_curve(valid))
    report(f"[{year}] 2. 하한율 집단별 기여도", contribution_table(valid, "lwlt_group"))
    report(f"[{year}] 3. 금액대별 기여도", contribution_table(valid, "금액대"))
    report(f"[{year}] 4. 기관 이력 깊이별 기여도", contribution_table(valid, "기관 이력"))
    report(f"[{year}] 5. 재발주 여부별 기여도", contribution_table(valid, "재발주"))
    report(f"[{year}] 6. 용역구분별 기여도", contribution_table(valid, "srvce_div_nm"))
    report(f"[{year}] 7. 계약방법별 기여도", contribution_table(valid, "cntrct_mthd_nm"))

    missing = valid[valid["lwlt_group"] == "결측"]
    report(
        f"[{year}] 8. 하한율 결측 집단 안의 금액대별 기여도 ({len(missing):,}건 기준)",
        contribution_table(missing, "금액대", min_rows=100),
    )
    report(
        f"[{year}] 9. 하한율 결측 집단 안의 기관 이력별 기여도",
        contribution_table(missing, "기관 이력", min_rows=100),
    )

    report(
        f"[{year}] 10. 교차: 하한율 x 금액대 (MAE)",
        cross_table(valid, "lwlt_group", "금액대"),
        index=True,
    )
    report(
        f"[{year}] 11. 교차: 하한율 x 기관 이력 깊이 (MAE)",
        cross_table(valid, "lwlt_group", "기관 이력"),
        index=True,
    )
    report(
        f"[{year}] 12. 교차: 금액대 x 기관 이력 깊이 (MAE, 결측 집단만)",
        cross_table(missing, "금액대", "기관 이력"),
        index=True,
    )

    report(f"[{year}] 13. 셀별 설명력 (난이도로 정규화)", cell_skill_table(valid))
    bound_table, gain = shallow_history_upper_bound(valid)
    report(
        f"[{year}] 14. 얕은 이력 개선 상한 "
        f"(MAE {total_mae:.4f} -> {total_mae - gain:.4f}, {gain / total_mae:.1%})",
        bound_table,
    )


def stability(frames: dict[int, pd.DataFrame], key: str) -> pd.DataFrame:
    """연도별 기여도를 나란히 놓습니다. 흔들리면 구조가 아닙니다."""
    parts = []
    for year, valid in sorted(frames.items()):
        valid = valid.copy()
        valid["금액대"] = banded(valid["presmpt_prce"], PRICE_BANDS)
        valid["기관 이력"] = banded(valid["inst_sample_cnt"], SAMPLE_BANDS)
        valid["재발주"] = np.where(valid["is_repeat"] > 0, "재발주", "신규")
        table = contribution_table(valid, key)
        if table.empty:
            continue
        parts.append(
            table.set_index(key)[["오차 기여도", "집중 배수"]].rename(
                columns=lambda c, y=year: f"{y} {c}"
            )
        )
    return pd.concat(parts, axis=1).reset_index() if parts else pd.DataFrame()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="잔차 parquet 디렉터리")
    parser.add_argument("--year", type=int, default=None, help="한 해만 볼 때 지정")
    args = parser.parse_args()

    frames = load(Path(args.dir), args.year)
    if not frames:
        print(f"잔차 parquet 이 없습니다: {args.dir}")
        print("먼저 diagnose_servc_lwlt_residuals.py --dump-dir 를 돌리십시오.")
        return 1

    for year in sorted(frames):
        analyze(frames[year], year)

    if len(frames) > 1:
        for key in ("lwlt_group", "금액대", "기관 이력", "재발주"):
            report(f"A. {key} 기여도의 연도 안정성", stability(frames, key))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
