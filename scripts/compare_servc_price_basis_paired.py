#!/usr/bin/env python3
"""
같은 공고·같은 서빙 모델에서 두 금액 기준을 **쌍대 비교**합니다.

`/predict-price` 는 금액 특징(log_price, notice_amt_ratio, is_over_notice_amt 등)을
`prediction_reference_amount`(기초금액 우선, 없으면 추정가격)로 만듭니다. 학습
데이터셋은 공고의 `presmpt_prce`(추정가격)를 쓰므로, 두 금액이 다른 공고에서는
같은 모델이 학습 때와 다른 금액을 보게 됩니다.

고치기 전에 그 차이가 실제 예측 오차를 얼마나 바꾸는지 재려면 두 기준을 같은
공고에 나란히 넣어야 합니다. 공고별 오차 차이를 직접 보면 두 팔의 오차가 강하게
상관되므로, 따로 돌려 요약값을 비교하는 방식보다 훨씬 작은 차이를 잡아냅니다.

- base       reference : `prediction_reference_amount` (현행 API)
- challenger presmpt   : `bid.presmpt_prce` (학습 기준, 없으면 기준금액 대체)

판정 표본(실제 낙찰률 70~110)과 전량 지표를 함께 냅니다. 운영 DB 는 읽기만 합니다.

사용법:
    .venv/bin/python scripts/compare_servc_price_basis_paired.py \\
        --year 2025 --samples 1000 --seed 42 --category Servc \\
        --output data/analysis/servc_price_basis_paired.json
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from scripts.compare_servc_models_paired import _evaluate_scope, paired_stats  # noqa: E402
from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.api.v1.predictions import (  # noqa: E402
    _default_model_for_bid,
    build_serving_features,
)
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.ml.dataset import MAX_WINNING_RATE, MIN_WINNING_RATE  # noqa: E402
from src.ml.model_registry import (  # noqa: E402
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_interval,
    predict_optimal_price_with_provenance,
)

REFERENCE_ARM = "reference"
PRESMPT_ARM = "presmpt"

# 0.5%p 이내 적중률. 낙찰률 오차의 실무 허용 폭으로 씁니다.
HIT_THRESHOLD = 0.5

PAIRED_COLUMNS = (
    "actual",
    "base_err",
    "chal_err",
    "base_width",
    "chal_width",
    "base_covered",
    "chal_covered",
)

EXTRA_COLUMNS = ("feature_amount_fallback", "boundary_crossed")


def split_decision_sample(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """전량(보고용)과 학습 범위 내(판정용) 표본을 나눕니다.

    실제 낙찰률이 학습 범위(70~110)를 벗어난 표본은 판정을 흔듭니다. 판정에서만
    빼고 전량 보고에는 그대로 남겨, 두 수치가 섞이지 않게 합니다.
    """
    actual = pd.to_numeric(frame["actual"], errors="coerce")
    inside = actual.between(MIN_WINNING_RATE, MAX_WINNING_RATE)
    return frame, frame.loc[inside]


def build_pair_record(
    actual_rate: float,
    reference: dict[str, Any],
    presmpt: dict[str, Any],
    *,
    feature_amount_fallback: bool,
    boundary_crossed: bool,
) -> dict[str, Any]:
    """같은 공고의 두 기준 예측을 하나의 쌍으로 묶습니다."""
    actual = float(actual_rate)
    return {
        "actual": actual,
        "reference_rate": float(reference["rate_percent"]),
        "presmpt_rate": float(presmpt["rate_percent"]),
        "base_err": abs(float(reference["rate_percent"]) - actual),
        "chal_err": abs(float(presmpt["rate_percent"]) - actual),
        "base_width": _interval_width(reference),
        "chal_width": _interval_width(presmpt),
        "base_covered": _covered(reference, actual),
        "chal_covered": _covered(presmpt, actual),
        "feature_amount_fallback": bool(feature_amount_fallback),
        "boundary_crossed": bool(boundary_crossed),
    }


def boundary_crossed(reference: dict[str, Any], presmpt: dict[str, Any]) -> bool:
    """고시금액 경계 판정(is_over_notice_amt)이 두 기준에서 갈렸는지 봅니다."""
    return reference["is_over_notice_amt"] != presmpt["is_over_notice_amt"]


def evaluate_basis_paired(frame: pd.DataFrame) -> dict[str, Any]:
    """두 금액 기준의 쌍대 지표를 전량과 판정 표본으로 나눠 계산합니다."""
    missing = sorted(set(PAIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"쌍대 평가 컬럼이 없습니다: {missing}")

    frame = frame.copy()
    for column in EXTRA_COLUMNS:
        if column not in frame.columns:
            frame[column] = False

    reporting_frame, decision_frame = split_decision_sample(frame)
    reporting = _scope_payload(_evaluate_scope(reporting_frame, "보고용(전량)"), reporting_frame)
    decision = _scope_payload(
        _evaluate_scope(decision_frame, "판정용(학습 범위 내)"), decision_frame
    )
    outside_count = len(frame) - len(decision_frame)

    return {
        "requested_pairs": len(frame),
        "outside_count": outside_count,
        "outside_ratio": _ratio(outside_count, len(frame)),
        "feature_amount_fallback_count": int(frame["feature_amount_fallback"].sum()),
        "boundary_crossed_count": int(frame["boundary_crossed"].sum()),
        "arms": {"base": REFERENCE_ARM, "challenger": PRESMPT_ARM},
        "reporting": reporting,
        "decision": decision,
        "verdict_mismatch": reporting["verdict"] != decision["verdict"],
    }


def predict_basis(
    session: Any,
    bid: BidAnnouncement,
    reference_amount: float,
    basis: str,
    model_id: str,
) -> dict[str, Any]:
    """한 금액 기준으로 특징을 만들고 같은 서빙 모델에 넣습니다."""
    features = build_serving_features(bid, session, reference_amount, feature_amount_basis=basis)
    outcome = predict_optimal_price_with_provenance(model_id, features)
    bounds = predict_interval(outcome.actual_model, features)
    if bounds is None:
        low = high = None
    else:
        low = round(float(bounds[0]), 4)
        high = round(float(bounds[1]), 4)
    return {
        "rate_percent": round(outcome.predicted_rate * 100.0, 4),
        "low": low,
        "high": high,
        "requested_model": outcome.requested_model,
        "actual_model": outcome.actual_model,
        "fallback_used": outcome.fallback_used,
        "feature_amount_fallback": features.get("_feature_amount_fallback") is True,
        "is_over_notice_amt": float(features.get("is_over_notice_amt", 0.0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42, help="표본 재현용 시드")
    parser.add_argument("--category", default="Servc", help="업무구분 코드")
    parser.add_argument("--output", default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args()

    session = SessionLocal()
    skipped: Counter[str] = Counter()
    model_fallback_count = 0
    requested_pairs = 0
    records: list[dict[str, Any]] = []
    try:
        frame = collect(session, args.year, args.samples, args.seed, args.category)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1

        requested_pairs = len(frame)
        print(
            f"{args.year}년 {args.category} {requested_pairs:,}건을 같은 공고·같은 "
            "서빙 모델로 두 금액 기준에 넣습니다."
        )
        print("  base       reference  prediction_reference_amount")
        print("  challenger presmpt    bid.presmpt_prce\n")

        for row in frame.itertuples():
            bid = session.get(BidAnnouncement, int(row.bid_id))
            if bid is None:
                skipped["공고 없음"] += 1
                continue
            reference_amount = float(bid.prediction_reference_amount or 0)
            if reference_amount <= 0:
                skipped["금액 미공개"] += 1
                continue
            raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
            if (
                bid.category == "Servc"
                and classify_price_decision_method(raw) == PriceDecisionMethod.NON_PREARNG
            ):
                skipped["비예가"] += 1
                continue

            model_id = _default_model_for_bid(bid)
            try:
                reference_arm = predict_basis(
                    session, bid, reference_amount, REFERENCE_ARM, model_id
                )
                presmpt_arm = predict_basis(session, bid, reference_amount, PRESMPT_ARM, model_id)
            except Exception:
                skipped["예측 실패"] += 1
                continue

            if reference_arm["actual_model"] != presmpt_arm["actual_model"]:
                skipped["서빙 모델 불일치"] += 1
                continue
            if reference_arm["fallback_used"] or presmpt_arm["fallback_used"]:
                model_fallback_count += 1

            records.append(
                build_pair_record(
                    float(row.actual_rate),
                    reference_arm,
                    presmpt_arm,
                    feature_amount_fallback=bool(presmpt_arm["feature_amount_fallback"]),
                    boundary_crossed=boundary_crossed(reference_arm, presmpt_arm),
                )
            )
    finally:
        session.close()

    paired = pd.DataFrame(records) if records else _empty_paired_frame()
    evaluation = evaluate_basis_paired(paired)
    evaluation["requested_pairs"] = requested_pairs
    evaluation["model_fallback_count"] = model_fallback_count
    evaluation["skipped_counts"] = dict(skipped)
    evaluation["run"] = {
        "year": args.year,
        "category": args.category,
        "samples": args.samples,
        "seed": args.seed,
    }

    print_evaluation(evaluation)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(_jsonable(evaluation), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n결과 JSON: {output_path}")

    if evaluation["requested_pairs"] == 0:
        return 1
    if evaluation["decision"]["n"] == 0:
        return 1
    return 0


def print_evaluation(evaluation: dict[str, Any]) -> None:
    print(f"요청 쌍: {evaluation['requested_pairs']:,}건")
    print(
        f"학습 범위 밖 {evaluation['outside_count']:,}건"
        f"({evaluation['outside_ratio']:.3%})은 판정에서 제외하고 보고에는 유지합니다."
    )
    print(
        "추정가격 대체(_feature_amount_fallback): "
        f"{evaluation['feature_amount_fallback_count']:,}건"
    )
    print(f"고시금액 경계 판정이 갈린 공고: {evaluation['boundary_crossed_count']:,}건")
    if evaluation.get("model_fallback_count"):
        print(
            f"모델 대체가 발생한 쌍: {evaluation['model_fallback_count']:,}건 "
            "(양쪽 실제 모델은 동일)"
        )
    skipped = evaluation.get("skipped_counts") or {}
    if skipped:
        print("표본 제외: " + ", ".join(f"{name} {count:,}건" for name, count in skipped.items()))

    for key in ("reporting", "decision"):
        scope = evaluation[key]
        print(f"\n{'=' * 92}\n{scope['label']} {scope['n']:,}건\n{'=' * 92}")
        summary = scope["summary"].copy()
        summary["모델"] = summary["모델"].map({"base": REFERENCE_ARM, "challenger": PRESMPT_ARM})
        print(summary.to_string(index=False))
        print("\n쌍대 비교 (presmpt - reference)")
        print(scope["stats"].to_string(index=False))
        hit = scope["hit_0_5"]
        print(
            "0.5%p 이내 적중률: "
            f"reference {_format_rate(hit[REFERENCE_ARM])} / "
            f"presmpt {_format_rate(hit[PRESMPT_ARM])}"
        )
        coverage = scope["coverage"]
        print(
            "예측 구간 피복률: "
            f"reference {_format_rate(coverage[REFERENCE_ARM])} / "
            f"presmpt {_format_rate(coverage[PRESMPT_ARM])}"
        )
        paired = scope["hit_0_5_paired"]
        print(
            "0.5%p 적중률 쌍대 차이(presmpt - reference): "
            f"{paired['평균 차이']:+.4f} (t={paired['t']}, {paired['판정']})"
        )
        print(f"presmpt 가 더 정확한 공고 비율: {scope['better_ratio']:.2%}")
        print(f"이 표본이 잡아낼 수 있는 최소 MAE 차이: {scope['detectable']:.5f}")
        print(f"관측된 MAE 차이: {scope['observed']:.5f}")

    print(f"\n최종 판정(학습 범위 내): {evaluation['decision']['verdict']}")
    if evaluation["verdict_mismatch"]:
        print(
            "주의: 판정이 어긋납니다: "
            f"전량 '{evaluation['reporting']['verdict']}' -> "
            f"범위 내 '{evaluation['decision']['verdict']}'"
        )


def _scope_payload(scope: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """_evaluate_scope 결과에 0.5%p 적중·피복 지표를 덧붙입니다."""
    reference_errors = frame["base_err"]
    presmpt_errors = frame["chal_err"]
    hit_diff = (presmpt_errors <= HIT_THRESHOLD).astype(float) - (
        reference_errors <= HIT_THRESHOLD
    ).astype(float)
    return {
        **scope,
        "hit_0_5": {
            REFERENCE_ARM: _rate((reference_errors <= HIT_THRESHOLD).mean()),
            PRESMPT_ARM: _rate((presmpt_errors <= HIT_THRESHOLD).mean()),
        },
        "coverage": {
            REFERENCE_ARM: _rate(frame["base_covered"].astype(float).mean()),
            PRESMPT_ARM: _rate(frame["chal_covered"].astype(float).mean()),
        },
        "hit_0_5_paired": paired_stats(hit_diff.to_numpy(), "0.5%p 적중률", lower_is_better=False),
    }


def _interval_width(arm: dict[str, Any]) -> float:
    low, high = arm.get("low"), arm.get("high")
    if low is None or high is None:
        return float("nan")
    return float(high) - float(low)


def _covered(arm: dict[str, Any], actual_rate: float) -> bool:
    low, high = arm.get("low"), arm.get("high")
    if low is None or high is None:
        return False
    return float(low) <= actual_rate <= float(high)


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _rate(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _format_rate(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value:.2%}"


def _empty_paired_frame() -> pd.DataFrame:
    """표본이 하나도 남지 않아도 같은 출력 경로를 타도록 빈 프레임을 만듭니다."""
    columns: dict[str, pd.Series] = {name: pd.Series(dtype="float64") for name in PAIRED_COLUMNS}
    columns.update(
        {
            "reference_rate": pd.Series(dtype="float64"),
            "presmpt_rate": pd.Series(dtype="float64"),
        }
    )
    columns.update({name: pd.Series(dtype="bool") for name in EXTRA_COLUMNS})
    return pd.DataFrame(columns)


def _jsonable(value: Any) -> Any:
    """numpy/pandas 값을 표준 JSON 값으로 바꿉니다. NaN 은 null 입니다."""
    if isinstance(value, pd.DataFrame):
        return [_jsonable(record) for record in value.to_dict(orient="records")]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


if __name__ == "__main__":
    raise SystemExit(main())
