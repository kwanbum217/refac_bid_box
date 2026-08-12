#!/usr/bin/env python3
"""
두 모델을 운영 API 경로에서 **쌍대 비교**합니다.

기존 `eval_servc_api_path.py` 는 모델을 하나씩 따로 돌려 요약값만 비교했습니다.
그 방식으로는 판정이 불가능하다는 것이 2026-08-05 에 드러났습니다. 용역 낙찰률
오차는 산포가 커서(RMSE 3.12) 1,000건 표본의 MAE 표준오차가 약 0.099 인데,
리프 63 대 127 의 관측 차이는 0.0015 였습니다. **표준오차의 1.5% 를 읽고 우열을
단정한 것입니다.**

같은 공고에 두 모델을 돌리면 공고별 오차 차이를 직접 볼 수 있습니다. 두 모델은
같은 특징을 같은 공고에서 보므로 오차가 강하게 상관되고, 차이의 분산은 오차
자체의 분산보다 훨씬 작습니다. 그래서 같은 표본으로도 훨씬 작은 효과를 잡아냅니다.

전제: 비교할 두 모델이 **서빙 루트(`data/model_files/`)에 각각 다른 ID 로**
올라가 있어야 합니다. 승격본과 백업을 겨룰 때는 백업을 임시 ID 로 복제하십시오.

사용법:
    .venv/bin/python scripts/compare_servc_models_paired.py \\
        --base servc_prev_63leaf --challenger servc_institution_v1
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

from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.api.v1.predictions import predict_price_api  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.schemas.predictions import PredictPriceRequest  # noqa: E402
from src.ml.dataset import (  # noqa: E402
    MAX_WINNING_RATE,
    MIN_WINNING_RATE,
    announcement_feature_payload,
)
from src.ml.model_registry import ModelRegistry  # noqa: E402

# 유의 판정 기준. 쌍대 t 통계량의 절댓값이 이보다 커야 방향을 말합니다.
T_THRESHOLD = 2.0


def predict_one(session, bid_id: int, model_id: str) -> dict | None:
    try:
        response = predict_price_api(
            PredictPriceRequest(bid_id=int(bid_id), user_price="0", selected_model=model_id),
            session,
        )
    except Exception:
        return None
    if response.prediction_rate is None:
        return None
    act_model_id = getattr(response, "model_id", None)
    req_model = getattr(response, "requested_model", None)
    fb_used = getattr(response, "fallback_used", None)

    missing_prov = not act_model_id or not req_model or fb_used is None

    return {
        "pred": float(response.prediction_rate),
        "model": response.model_name,
        "low": response.rate_low,
        "high": response.rate_high,
        "model_id": act_model_id or "",
        "requested_model": req_model or "",
        "fallback_used": bool(fb_used),
        "missing_provenance": missing_prov,
    }


def paired_stats(diff: np.ndarray, label: str, lower_is_better: bool = True) -> dict:
    """쌍대 차이의 평균과 표준오차를 냅니다. diff = challenger - base 입니다."""
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    if n == 0:
        return {
            "지표": label,
            "평균 차이": np.nan,
            "표준오차": np.nan,
            "t": np.nan,
            "판정": "측정 불가",
        }
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0
    if abs(t) < T_THRESHOLD:
        verdict = "판별 불가"
    elif (mean < 0) == lower_is_better:
        verdict = "challenger 우세"
    else:
        verdict = "base 우세"
    return {
        "지표": label,
        "평균 차이": round(mean, 5),
        "표준오차": round(se, 5),
        "t": round(t, 2),
        "판정": verdict,
    }


def evaluate_paired_samples(
    frame: pd.DataFrame, requested_pairs: int = 0, api_error_count: int = 0
) -> dict:
    """전량 보고와 학습 범위 내 판정을 함께 계산합니다."""
    required = {
        "actual",
        "base_err",
        "chal_err",
        "base_width",
        "chal_width",
        "base_covered",
        "chal_covered",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"쌍대 평가 컬럼이 없습니다: {missing}")

    df = frame.copy()
    if "missing_provenance" not in df.columns:
        df["missing_provenance"] = False
    if "base_fallback" not in df.columns:
        df["base_fallback"] = True
    if "chal_fallback" not in df.columns:
        df["chal_fallback"] = True
    if "same_actual_model" not in df.columns:
        df["same_actual_model"] = True

    invalid_prov = (
        df["missing_provenance"]
        | df["base_fallback"]
        | df["chal_fallback"]
        | df["same_actual_model"]
    )
    df["provenance_valid"] = ~invalid_prov

    invalid_provenance_count = int(invalid_prov.sum())
    total_complete_pairs = len(df)

    if requested_pairs == 0:
        requested_pairs = total_complete_pairs + api_error_count

    valid_frame = df.loc[df["provenance_valid"]]
    valid_count = len(valid_frame)

    actual = pd.to_numeric(valid_frame["actual"], errors="coerce")
    inside = actual.between(MIN_WINNING_RATE, MAX_WINNING_RATE)
    outside_count = int((~inside).sum())
    reporting = _evaluate_scope(valid_frame, "보고용(전량)")
    decision = _evaluate_scope(valid_frame.loc[inside], "판정용(학습 범위 내)")

    fail_closed = invalid_provenance_count > 0 or api_error_count > 0
    if fail_closed:
        decision["verdict"] = "판정 불가 (대체 모델 발생)"
        reporting["verdict"] = "판정 불가 (대체 모델 발생)"

    return {
        "requested_pairs": requested_pairs,
        "complete_pairs": total_complete_pairs,
        "valid_pairs": valid_count,
        "api_error_count": api_error_count,
        "missing_provenance_count": int(df["missing_provenance"].sum()),
        "invalid_provenance_count": invalid_provenance_count,
        "base_fallback_count": int(df["base_fallback"].sum()),
        "chal_fallback_count": int(df["chal_fallback"].sum()),
        "same_actual_model_count": int(df["same_actual_model"].sum()),
        "fail_closed": fail_closed,
        "outside_count": outside_count,
        "outside_ratio": outside_count / valid_count if valid_count > 0 else 0.0,
        "reporting": reporting,
        "decision": decision,
        "verdict_mismatch": reporting["verdict"] != decision["verdict"],
    }


def _evaluate_scope(frame: pd.DataFrame, label: str) -> dict:
    summary = pd.DataFrame(
        [
            _model_summary(frame, "base", "base"),
            _model_summary(frame, "challenger", "chal"),
        ]
    )
    stats = pd.DataFrame(
        [
            paired_stats((frame["chal_err"] - frame["base_err"]).to_numpy(), "절대오차"),
            paired_stats(
                (frame["chal_err"] ** 2 - frame["base_err"] ** 2).to_numpy(),
                "제곱오차",
            ),
            paired_stats(
                (frame["chal_width"] - frame["base_width"]).dropna().to_numpy(),
                "구간 폭",
            ),
            paired_stats(
                (
                    frame["chal_covered"].astype(float) - frame["base_covered"].astype(float)
                ).to_numpy(),
                "피복률",
                lower_is_better=False,
            ),
        ]
    )
    mae_diff = frame["chal_err"] - frame["base_err"]
    n = len(mae_diff)
    detectable = T_THRESHOLD * float(mae_diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {
        "label": label,
        "n": n,
        "summary": summary,
        "stats": stats,
        "better_ratio": float((frame["chal_err"] < frame["base_err"]).mean()),
        "detectable": detectable,
        "observed": abs(float(mae_diff.mean())),
        "verdict": stats.iloc[0]["판정"],
    }


def _model_summary(frame: pd.DataFrame, model: str, prefix: str) -> dict:
    errors = frame[f"{prefix}_err"]
    return {
        "모델": model,
        "MAE": round(float(errors.mean()), 4),
        "RMSE": round(float(np.sqrt((errors**2).mean())), 4),
        "0.5%p 적중": round(float((errors <= 0.5).mean()), 4),
        "구간 폭": round(float(frame[f"{prefix}_width"].median()), 4),
        "피복률": round(float(frame[f"{prefix}_covered"].mean()), 4),
    }


def print_paired_evaluation(evaluation: dict) -> None:
    req = evaluation["requested_pairs"]
    comp = evaluation["complete_pairs"]
    val = evaluation["valid_pairs"]

    print(f"요청 쌍: {req:,}건")
    if req > 0:
        print(f"완전 쌍(Complete): {comp:,}건 ({comp / req:.1%})")
        print(f"유효 쌍(Valid): {val:,}건 ({val / req:.1%})")
    print()

    api_err = evaluation["api_error_count"]
    if api_err > 0:
        print(f"API 응답 실패/미반환 (API 오류): {api_err:,}건")

    invalid_prov_count = evaluation.get("invalid_provenance_count", 0)
    if invalid_prov_count > 0 or api_err > 0:
        base_fb = evaluation.get("base_fallback_count", 0)
        chal_fb = evaluation.get("chal_fallback_count", 0)
        same_m = evaluation.get("same_actual_model_count", 0)
        missing_p = evaluation.get("missing_provenance_count", 0)

        print("대체 모델/동일 모델/출처 누락 등 오류 표본을 정상 비교에서 제외합니다.")
        print(f"  - 출처 정보 누락(missing_provenance): {missing_p:,}건")
        print(f"  - base 모델 fallback: {base_fb:,}건")
        print(f"  - challenger 모델 fallback: {chal_fb:,}건")
        print(f"  - 양 팔 동일 actual model: {same_m:,}건")

    outside_count = evaluation["outside_count"]
    outside_ratio = evaluation["outside_ratio"]
    print(
        f"학습 범위 밖 {outside_count:,}건({outside_ratio:.3%})은 판정에서 제외하고 "
        "보고에는 유지합니다."
    )
    for key in ("reporting", "decision"):
        scope = evaluation[key]
        print(f"\n{'=' * 92}\n{scope['label']} {scope['n']:,}건\n{'=' * 92}")
        print(scope["summary"].to_string(index=False))
        print("\n쌍대 비교 (challenger - base)")
        print(scope["stats"].to_string(index=False))
        print(f"challenger 가 더 정확한 공고 비율: {scope['better_ratio']:.2%}")
        print(f"이 표본이 잡아낼 수 있는 최소 MAE 차이: {scope['detectable']:.5f}")
        print(f"관측된 차이: {scope['observed']:.5f}")

    reporting_verdict = evaluation["reporting"]["verdict"]
    decision_verdict = evaluation["decision"]["verdict"]
    print(f"\n최종 판정(학습 범위 내): {decision_verdict}")
    if evaluation.get("fail_closed", False):
        print("주의: 대체 모델(fallback) 발생으로 인해 승격 판정이 차단(fail-closed)되었습니다.")
    if evaluation["verdict_mismatch"]:
        print(
            f"주의: 판정이 어긋납니다: 전량 '{reporting_verdict}' -> 범위 내 '{decision_verdict}'"
        )
    else:
        print(f"전량과 범위 내 판정이 같습니다: {decision_verdict}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="기준 모델 ID (서빙 루트 디렉터리명)")
    parser.add_argument("--challenger", required=True, help="비교 모델 ID")
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--category", default="Servc", help="업무구분 코드")
    parser.add_argument("--require-lwlt", action="store_true", help="하한율 보유 건만 채점")
    parser.add_argument(
        "--model-root",
        default=None,
        help="비교용 모델 디렉터리 루트. 지정하면 이 프로세스에서만 사용",
    )
    args = parser.parse_args()

    if args.require_lwlt and args.category != "Servc":
        print("--require-lwlt는 Servc 평가에서만 지원합니다.")
        return 1

    if args.model_root:
        model_root = Path(args.model_root).resolve()
        if not model_root.is_dir():
            print(f"비교용 모델 루트가 없습니다: {model_root}")
            return 1
        ModelRegistry._get_model_root = classmethod(lambda cls: str(model_root))
        ModelRegistry.load_all_models()

    session = SessionLocal()
    try:
        pool = args.samples * 4 if args.require_lwlt else args.samples
        frame = collect(session, args.year, pool, args.seed, args.category)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1

        if args.require_lwlt:
            keep = []
            for row in frame.itertuples():
                bid = session.get(BidAnnouncement, int(row.bid_id))
                if bid and announcement_feature_payload(bid).get("lwlt_rate"):
                    keep.append(row.bid_id)
                if len(keep) >= args.samples:
                    break
            frame = frame[frame["bid_id"].isin(keep)]
            print(f"하한율 보유 건만 사용합니다 ({len(frame):,}건).")

        print(f"{args.year}년 {args.category} {len(frame):,}건에 두 모델을 같은 순서로 호출합니다.")
        print(f"  base       {args.base}")
        print(f"  challenger {args.challenger}\n")

        requested_pairs = len(frame)
        records = []
        api_error_count = 0
        for row in frame.itertuples():
            a = predict_one(session, row.bid_id, args.base)
            b = predict_one(session, row.bid_id, args.challenger)
            if a is None or b is None:
                api_error_count += 1
                continue

            base_miss = a.get("missing_provenance", False)
            chal_miss = b.get("missing_provenance", False)
            base_fb = a.get("fallback_used", False) or (
                a.get("model_id") != a.get("requested_model")
            )
            chal_fb = b.get("fallback_used", False) or (
                b.get("model_id") != b.get("requested_model")
            )
            same_m = a.get("model_id") == b.get("model_id")
            is_valid = not (base_miss or chal_miss or base_fb or chal_fb or same_m)

            actual = float(row.actual_rate)
            records.append(
                {
                    "actual": actual,
                    "base_err": abs(a["pred"] - actual),
                    "chal_err": abs(b["pred"] - actual),
                    "base_width": (a["high"] - a["low"]) if a["low"] is not None else np.nan,
                    "chal_width": (b["high"] - b["low"]) if b["low"] is not None else np.nan,
                    "base_covered": _covered(a, actual),
                    "chal_covered": _covered(b, actual),
                    "provenance_valid": is_valid,
                    "missing_provenance": base_miss or chal_miss,
                    "base_fallback": base_fb,
                    "chal_fallback": chal_fb,
                    "same_actual_model": same_m,
                    "base_model_id": a.get("model_id", ""),
                    "chal_model_id": b.get("model_id", ""),
                }
            )
    finally:
        session.close()

    if not records:
        print("채점 가능한 표본이 없습니다.")
        return 1

    df = pd.DataFrame(records)

    try:
        eval_result = evaluate_paired_samples(
            df, requested_pairs=requested_pairs, api_error_count=api_error_count
        )
    except ValueError as e:
        print(f"오류: {e}")
        return 1

    print_paired_evaluation(eval_result)
    if eval_result.get("valid_pairs", 0) == 0:
        return 1
    if eval_result.get("decision", {}).get("n", 0) == 0:
        return 1
    return 0


def _covered(result: dict, actual: float) -> bool:
    if result["low"] is None or result["high"] is None:
        return False
    return result["low"] <= actual <= result["high"]


if __name__ == "__main__":
    raise SystemExit(main())
