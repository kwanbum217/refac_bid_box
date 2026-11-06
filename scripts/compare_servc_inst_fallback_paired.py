#!/usr/bin/env python3
"""
기관 이력 폴백의 서빙 정의와 학습 정의를 **같은 공고·같은 모델**로 쌍대 비교합니다.

서빙은 집계 표(`institution_win_rate_stats`)에 없는 기관에 365일 창·0~100
이상치·표본 수 0 을 쓰는 실시간 집계로 내려갑니다. 학습
(`attach_institution_history`)은 전 이력·50~120 이상치·실제 표본 수를 씁니다.
정의가 다르므로, 정의를 바꾸기 전에 같은 공고에서 두 정의의 예측 오차를
짝지어 실측합니다(A1 가격 기준 비교와 같은 방식).

집계 표에 있는 기관은 두 정의 모두 표 값을 그대로 쓰므로 비교 대상이
아닙니다. 이 스크립트는 폴백을 타는 공고만 골라 특징을 두 번 만들고,
같은 서빙 모델에 넣어 예측 낙찰률의 절대 오차를 짝짓습니다.

`src/ml/features.py` 는 고치지 않습니다. 기관 이력 세 값을 특징 dict 에
직접 덮어쓴 뒤 같은 `build_feature_dict` 를 다시 태워 파생 상호작용까지
같은 단일 공급원에서 다시 계산합니다.

운영 DB 는 읽기만 합니다. 모델 파일이 없는 환경에서는 실행하지 말고
`tests/test_inst_fallback_paired.py` 의 monkeypatch 시험으로 검증하십시오.

사용법:
    uv run python scripts/compare_servc_inst_fallback_paired.py \\
        --samples 300 --year 2025 --output .orca/inst_fallback_paired.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

# paired_stats·_evaluate_scope 를 그대로 재사용합니다. 판정 기준과 표 형식이
# A1 비교와 같아야 결과를 나란히 읽을 수 있습니다.
from scripts.compare_servc_models_paired import _evaluate_scope, paired_stats  # noqa: E402
from src.app.api.v1.predictions import build_serving_features  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import (  # noqa: E402
    BidAnnouncement,
    BidResult,
    InstitutionWinRateStat,
)
from src.app.services.bid_queries import (  # noqa: E402
    DEFAULT_PREDICTION_MODEL,
    DEFAULT_PREDICTION_MODEL_BY_CATEGORY,
)
from src.ml.dataset import MAX_WINNING_RATE, MIN_WINNING_RATE  # noqa: E402
from src.ml.features import build_feature_dict  # noqa: E402
from src.ml.institution_history import (  # noqa: E402
    FALLBACK_DEFINITION_CURRENT,
    FALLBACK_DEFINITION_TRAINING,
    lookup_institution_stats,
)
from src.ml.model_registry import (  # noqa: E402
    predict_interval,
    predict_optimal_price_with_provenance,
)

CURRENT_LABEL = "current(365일)"
TRAINING_LABEL = "training(전 이력)"
DEFINITION_LABELS = {
    "base": CURRENT_LABEL,
    "challenger": TRAINING_LABEL,
}

# features.py 가 기관 이력에서 파생하는 키입니다. 값을 덮어쓸 때 이 키들을
# 지우고 다시 태워야 상호작용 특징이 새 정의를 반영합니다.
DERIVED_INSTITUTION_KEYS = (
    "inst_hist_rate",
    "inst_sample_cnt",
    "inst_ewm_rate",
    "inst_rate_mean_30d",
    "inst_rate_std_90d",
    "inst_part_avg",
    *tuple(f"inst_inter_sem_{idx}" for idx in (10, 12, 13, 17, 30)),
)

# 쌍대 프레임이 _evaluate_scope 에 넘기는 필수 컬럼입니다.
PAIRED_COLUMNS = (
    "actual",
    "base_err",
    "chal_err",
    "base_width",
    "chal_width",
    "base_covered",
    "chal_covered",
)


def is_fallback_target(
    institution_name: str, category: str, stats_keys: set[tuple[str, str]]
) -> bool:
    """집계 표에 (기관, 업무구분) 키가 없어 서빙 폴백을 타는지 판별합니다."""
    return (str(institution_name or ""), str(category or "")) not in stats_keys


def load_stats_keys(session: Any, category: str) -> set[tuple[str, str]]:
    """집계 표에 존재하는 (기관, 업무구분) 키를 읽습니다."""
    stmt = select(InstitutionWinRateStat.institution_name, InstitutionWinRateStat.category)
    if category:
        stmt = stmt.where(InstitutionWinRateStat.category == category)
    return {(str(name), str(cat or "")) for name, cat in session.execute(stmt)}


def select_fallback_targets(frame: pd.DataFrame, stats_keys: set[tuple[str, str]]) -> pd.DataFrame:
    """집계 표에 없는 기관의 행만 남깁니다."""
    if frame.empty:
        return frame
    keep = [
        is_fallback_target(row.dminstt_nm, row.category, stats_keys) for row in frame.itertuples()
    ]
    return frame.loc[keep].copy()


def collect_fallback_samples(
    session: Any,
    year: int,
    samples: int,
    seed: int,
    category: str = "Servc",
) -> pd.DataFrame:
    """낙찰 결과가 있고 기관이 집계 표에 없는 공고를 무작위로 뽑습니다.

    NOT EXISTS 로 폴백 대상만 먼저 좁힙니다. 전체에서 무작위로 뽑은 뒤
    걸러내면 폴백 비중이 낮을 때 표본을 거의 못 채웁니다.
    """
    stats_exists = (
        select(InstitutionWinRateStat.id)
        .where(
            InstitutionWinRateStat.institution_name == BidResult.dminstt_nm,
            InstitutionWinRateStat.category == BidResult.category,
        )
        .exists()
    )
    stmt = (
        select(
            BidAnnouncement.id.label("bid_id"),
            BidAnnouncement.bid_ntce_no,
            BidResult.sucsf_bid_rate.label("actual_rate"),
            BidResult.dminstt_nm,
            BidResult.category,
        )
        .join(BidResult, BidResult.bid_ntce_no == BidAnnouncement.bid_ntce_no)
        .where(
            BidAnnouncement.category == category,
            BidResult.category == category,
            BidResult.sucsf_bid_rate.isnot(None),
            BidResult.sucsf_bid_rate > 0,
            func.year(BidResult.rl_openg_dt) == year,
            ~stats_exists,
        )
        .order_by(func.rand(seed))
        .limit(samples * 2)
    )
    rows = session.execute(stmt).all()
    frame = pd.DataFrame(
        rows,
        columns=["bid_id", "bid_ntce_no", "actual_rate", "dminstt_nm", "category"],
    )
    # SQL 과 같은 규칙을 파이썬에서 한 번 더 적용합니다. 조회 사이에 집계 표가
    # 갱신되어도 폴백 대상이 아닌 행이 비교에 섞이지 않습니다. 공고-결과 조인은
    # 차수 표기가 달라 같은 공고가 여러 번 나올 수 있으므로 공고 단위로 접습니다.
    selected = select_fallback_targets(frame, load_stats_keys(session, category))
    return selected.drop_duplicates("bid_id").head(samples)


def _institution_feature_source(bid: BidAnnouncement) -> dict[str, Any]:
    """기관명·업무구분·기준일을 서빙 특징과 같은 키로 모읍니다."""
    return {
        "dminstt_nm": bid.dminstt_nm or "",
        "category": bid.category or "",
        "openg_dt": bid.openg_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "bid_ntce_dt": bid.bid_ntce_dt,
    }


def apply_institution_definition(
    serving_features: dict[str, Any],
    stats: dict[str, float],
    session: Any = None,
) -> dict[str, Any]:
    """서빙 특징 dict 에 기관 이력 정의를 덮어쓰고 단일 공급원을 다시 태웁니다.

    기관 이력에서 파생된 키를 지운 뒤 `build_feature_dict` 를 호출하므로
    `inst_inter_sem_*` 같은 상호작용도 새 정의 값으로 다시 계산됩니다.
    """
    overridden = {
        key: value for key, value in serving_features.items() if key not in DERIVED_INSTITUTION_KEYS
    }
    overridden.update(stats)
    return build_feature_dict(overridden, session)


def predict_definition(model_id: str, features: dict[str, Any]) -> dict[str, Any]:
    """같은 모델로 한 정의의 점 추정과 예측 구간을 냅니다.

    `predict_optimal_price_with_provenance` 는 낙찰률을 0~1 비율로 돌려주고
    `predict_interval` 은 퍼센트로 돌려줍니다. DB 낙찰률이 퍼센트이므로
    점 추정만 100 을 곱해 단위를 맞춥니다.
    """
    outcome = predict_optimal_price_with_provenance(model_id, features)
    bounds = predict_interval(outcome.actual_model, features)
    low = high = coverage = None
    if bounds is not None:
        low, high, coverage = bounds
    return {
        "pred": float(outcome.predicted_rate) * 100.0,
        "model_id": outcome.actual_model,
        "low": float(low) if low is not None else None,
        "high": float(high) if high is not None else None,
        "coverage": float(coverage) if coverage is not None else None,
    }


def evaluate_bid(
    session: Any,
    bid: BidAnnouncement,
    actual_rate: float,
    model_id: str,
) -> dict[str, Any] | None:
    """공고 한 건을 두 정의로 예측해 짝지을 수 있는 레코드로 만듭니다."""
    reference_amount = float(bid.prediction_reference_amount or 0)
    if reference_amount <= 0:
        return None

    source = _institution_feature_source(bid)
    current_stats = lookup_institution_stats(
        source, session, fallback_definition=FALLBACK_DEFINITION_CURRENT
    )
    training_stats = lookup_institution_stats(
        source, session, fallback_definition=FALLBACK_DEFINITION_TRAINING
    )

    serving = build_serving_features(bid, session, reference_amount)
    current_features = apply_institution_definition(serving, current_stats, session)
    training_features = apply_institution_definition(serving, training_stats, session)

    return {
        "bid_id": int(bid.id),
        "actual": float(actual_rate),
        "current": predict_definition(model_id, current_features),
        "training": predict_definition(model_id, training_features),
        "current_rate": float(current_stats["inst_hist_rate"]),
        "training_rate": float(training_stats["inst_hist_rate"]),
        "current_count": float(current_stats["inst_sample_cnt"]),
        "training_count": float(training_stats["inst_sample_cnt"]),
    }


def _width(arm: dict[str, Any]) -> float:
    if arm["low"] is None or arm["high"] is None:
        return float("nan")
    return float(arm["high"]) - float(arm["low"])


def _covered(arm: dict[str, Any], actual: float) -> bool:
    if arm["low"] is None or arm["high"] is None:
        return False
    return bool(float(arm["low"]) <= actual <= float(arm["high"]))


def build_paired_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    """정의별 예측 레코드를 `_evaluate_scope` 가 읽는 쌍대 프레임으로 바꿉니다."""
    rows = []
    for record in records:
        actual = float(record["actual"])
        current = record["current"]
        training = record["training"]
        rows.append(
            {
                "bid_id": record.get("bid_id"),
                "actual": actual,
                "base_err": abs(float(current["pred"]) - actual),
                "chal_err": abs(float(training["pred"]) - actual),
                "base_width": _width(current),
                "chal_width": _width(training),
                "base_covered": _covered(current, actual),
                "chal_covered": _covered(training, actual),
                "base_rate": float(record["current_rate"]),
                "chal_rate": float(record["training_rate"]),
                "base_count": float(record["current_count"]),
                "chal_count": float(record["training_count"]),
            }
        )
    if not rows:
        return pd.DataFrame({name: pd.Series(dtype="float64") for name in PAIRED_COLUMNS})
    return pd.DataFrame(rows)


def _finite_or_none(value: Any) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _json_value(value: Any) -> Any:
    """JSON 에 실을 수 있도록 numpy 수치와 비유한값을 정리합니다."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _finite_or_none(value)
    return value


def _scope_payload(scope: dict[str, Any]) -> dict[str, Any]:
    """`_evaluate_scope` 결과에서 JSON 으로 실을 수 있는 값만 꺼냅니다."""
    summary = scope["summary"].copy()
    summary["모델"] = summary["모델"].map(lambda name: DEFINITION_LABELS.get(name, name))
    stats = scope["stats"].copy()
    return {
        "label": scope["label"],
        "n": int(scope["n"]),
        "summary": [
            {key: _json_value(value) for key, value in row.items()}
            for row in summary.to_dict(orient="records")
        ],
        "stats": [
            {key: _json_value(value) for key, value in row.items()}
            for row in stats.to_dict(orient="records")
        ],
        "better_ratio": _finite_or_none(scope["better_ratio"]),
        "detectable": _finite_or_none(scope["detectable"]),
        "observed": _finite_or_none(scope["observed"]),
        "verdict": scope["verdict"],
    }


def summarize_pairs(frame: pd.DataFrame) -> dict[str, Any]:
    """전량과 판정 표본(학습 낙찰률 범위 70~110)의 쌍대 통계를 냅니다."""
    if frame.empty:
        return {
            "complete_pairs": 0,
            "decision_pairs": 0,
            "outside_count": 0,
            "reporting": None,
            "decision": None,
            "inst_rate_mean_current": None,
            "inst_rate_mean_training": None,
            "inst_rate_mean_diff": None,
            "inst_rate_stats": None,
        }

    actual = pd.to_numeric(frame["actual"], errors="coerce")
    inside = actual.between(MIN_WINNING_RATE, MAX_WINNING_RATE)
    reporting = _evaluate_scope(frame, "보고용(전량)")
    decision = _evaluate_scope(frame.loc[inside], "판정용(학습 범위 내)")
    rate_diff = (frame["chal_rate"] - frame["base_rate"]).dropna()

    return {
        "complete_pairs": len(frame),
        "decision_pairs": int(inside.sum()),
        "outside_count": int((~inside).sum()),
        "reporting": _scope_payload(reporting),
        "decision": _scope_payload(decision),
        "inst_rate_mean_current": _finite_or_none(frame["base_rate"].mean()),
        "inst_rate_mean_training": _finite_or_none(frame["chal_rate"].mean()),
        "inst_rate_mean_diff": _finite_or_none(rate_diff.mean()),
        # 두 정의의 inst_hist_rate 차이도 같은 쌍대 통계로 읽습니다.
        "inst_rate_stats": {
            key: _json_value(value)
            for key, value in paired_stats(rate_diff.to_numpy(), "inst_hist_rate").items()
        },
        "inst_count_mean_current": _finite_or_none(frame["base_count"].mean()),
        "inst_count_mean_training": _finite_or_none(frame["chal_count"].mean()),
    }


def _fmt(value: Any, spec: str) -> str:
    return format(value, spec) if value is not None else "측정 불가"


def print_summary(result: dict[str, Any]) -> None:
    print(
        f"{result['year']}년 {result['category']} 폴백 대상 "
        f"{result['fallback_targets']:,}건 / 요청 {result['requested_samples']:,}건"
    )
    print(f"사용 모델: {result['model_id']}")
    print(
        f"평가 쌍 {result['complete_pairs']:,}건 "
        f"(금액 없음 {result['skipped_amount']:,}건, API 오류 {result['api_error_count']:,}건, "
        f"모델 불일치 {result['model_mismatch_count']:,}건 제외)"
    )

    for key in ("reporting", "decision"):
        scope = result.get(key)
        if not scope:
            continue
        print(f"\n{'=' * 92}\n{scope['label']} {scope['n']:,}건\n{'=' * 92}")
        if scope["n"] == 0:
            print("  표본이 없어 쌍대 통계를 계산하지 않습니다.")
            continue
        for row in scope["summary"]:
            print(
                f"  {row['모델']:<16} MAE {_fmt(row['MAE'], '.4f')}  "
                f"RMSE {_fmt(row['RMSE'], '.4f')}  "
                f"0.5%p 적중 {_fmt(row['0.5%p 적중'], '.2%')}  "
                f"구간 폭 {_fmt(row['구간 폭'], '.4f')}  "
                f"피복률 {_fmt(row['피복률'], '.2%')}"
            )
        for row in scope["stats"]:
            print(
                f"  {row['지표']:<8} 평균 차이 {_fmt(row['평균 차이'], '+.5f')}  "
                f"표준오차 {_fmt(row['표준오차'], '.5f')}  "
                f"t {_fmt(row['t'], '+.2f')}  {row['판정']}"
            )
        print(f"  training 이 더 정확한 공고 비율: {_fmt(scope['better_ratio'], '.2%')}")
        print(f"  이 표본이 잡아낼 수 있는 최소 MAE 차이: {_fmt(scope['detectable'], '.5f')}")

    decision = result.get("decision") or {}
    print(f"\n최종 판정(학습 범위 내): {decision.get('verdict', '측정 불가')}")
    print(
        "inst_hist_rate 평균: "
        f"{CURRENT_LABEL} {result['inst_rate_mean_current']}, "
        f"{TRAINING_LABEL} {result['inst_rate_mean_training']}, "
        f"차이 {result['inst_rate_mean_diff']:+}"
        if result["inst_rate_mean_diff"] is not None
        else "inst_hist_rate 평균: 측정 불가"
    )
    print(
        "inst_sample_cnt 평균: "
        f"{CURRENT_LABEL} {result['inst_count_mean_current']}, "
        f"{TRAINING_LABEL} {result['inst_count_mean_training']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=300, help="폴백 대상 표본 상한")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--category", default="Servc", help="업무구분 코드")
    parser.add_argument("--model", default=None, help="서빙 모델 ID. 기본값은 카테고리 기본 모델")
    parser.add_argument("--output", default=None, help="결과 JSON 경로")
    args = parser.parse_args()

    if args.samples <= 0:
        print("--samples 는 1 이상이어야 합니다.")
        return 1

    model_id = args.model or DEFAULT_PREDICTION_MODEL_BY_CATEGORY.get(
        args.category, DEFAULT_PREDICTION_MODEL
    )

    session = SessionLocal()
    records: list[dict[str, Any]] = []
    skipped_amount = api_error_count = model_mismatch_count = 0
    try:
        frame = collect_fallback_samples(session, args.year, args.samples, args.seed, args.category)
        if frame.empty:
            print("폴백 대상 표본이 없습니다. 연도·카테고리·집계 표를 확인하십시오.")
            return 1

        for row in frame.itertuples():
            bid = session.get(BidAnnouncement, int(row.bid_id))
            if bid is None:
                api_error_count += 1
                continue
            try:
                record = evaluate_bid(session, bid, row.actual_rate, model_id)
            except Exception as exc:
                api_error_count += 1
                print(f"  bid_id={row.bid_id} 예측 실패: {type(exc).__name__}")
                continue
            if record is None:
                skipped_amount += 1
                continue
            if record["current"]["model_id"] != record["training"]["model_id"]:
                # 같은 모델로 비교해야 쌍대 차이가 정의 차이만 담습니다.
                model_mismatch_count += 1
                continue
            records.append(record)
    finally:
        session.close()

    paired = build_paired_frame(records)
    summary = summarize_pairs(paired)
    result = {
        "year": args.year,
        "category": args.category,
        "model_id": model_id,
        "requested_samples": args.samples,
        "fallback_targets": len(frame),
        "complete_pairs": summary["complete_pairs"],
        "skipped_amount": skipped_amount,
        "api_error_count": api_error_count,
        "model_mismatch_count": model_mismatch_count,
        "definition_labels": {
            "base": CURRENT_LABEL,
            "challenger": TRAINING_LABEL,
        },
        **summary,
    }

    print_summary(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        print(f"\n결과 JSON: {output_path}")

    if summary["complete_pairs"] == 0:
        return 1
    if not result.get("decision") or result["decision"]["n"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
