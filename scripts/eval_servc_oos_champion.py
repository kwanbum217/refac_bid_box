#!/usr/bin/env python3
"""
scripts/eval_servc_oos_champion.py

Servc 현 Champion 모델을 3,589건 유효 OOS(Out-of-Sample) 표본으로 고정 평가하는 하네스.

[OOS 표본 집합의 정의]
2026-08-03 11:00:00(운영 feature store dataset_Servc.parquet 컷오프) 이후 개찰된
용역(Servc) 개찰 결과 중 (1) 낙찰률이 결측이 아니고(sucsf_bid_rate IS NOT NULL),
(2) 낙찰률이 정상 유효 범위 70.0% ~ 110.0% 에 속하며, (3) 낙찰금액이 존재하고
(sucsf_bid_amt IS NOT NULL), (4) 공고 테이블(bid_announcements)과 3개 키
(공고번호, 3자리 정규화 차수, 업무구분 Servc)로 조인 매칭에 성공하고,
(5) 추정가격이 10만원 이상 1조원 이하(100,000 <= presmpt_prce <= 1,000,000,000,000)인
정본 3,589건의 표본 집합을 대상으로 합니다.

본 하네스는 선택된 행의 기본 키 집합을 정렬하여 SHA-256 해시로 결박함으로써
평가 표본의 재현성을 보장하며, 실측 표본 수가 기대 정본(3,589건)과 다를 경우
조용히 넘어가지 않고 canonical=False 및 건수 차이값을 산출물에 명시합니다.
특징 생성은 train/serve skew 방지 원칙에 따라 src/ml/features.py 및 dataset.py의
단일 정의를 사용하며, Champion 모델의 식별 정보(가중치 SHA-256, 버전, 경로)를 함께 기록합니다.

사용법:
    # 하네스 검증 / dry-run (실제 모델 파일 없이 키/지표 검증)
    .venv/bin/python scripts/eval_servc_oos_champion.py --dry-run

    # 주 저장소 정식 평가 실행 (결과 JSON 저장)
    .venv/bin/python scripts/eval_servc_oos_champion.py --output data/benchmarks/servc_oos_champion_eval.json
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import func, literal, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.requests import Request  # noqa: E402

from src.app.api.v1.predictions import predict_price_api  # noqa: E402
from src.app.core.config import settings  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402
from src.app.schemas.predictions import PredictPriceRequest  # noqa: E402
from src.ml.dataset import (  # noqa: E402
    MAX_PRESMPT_PRCE,
    MAX_WINNING_RATE,
    MIN_PRESMPT_PRCE,
    MIN_WINNING_RATE,
    announcement_feature_payload,
)

logger = logging.getLogger(__name__)

# 정본 상수 정의
OOS_CATEGORY: str = "Servc"
OOS_CUTOFF_TIMESTAMP: str = "2026-08-03 11:00:00"
EXPECTED_OOS_SAMPLE_COUNT: int = 3589
DEFAULT_MODEL_ID: str = "servc_institution_v1"
ERROR_BANDS: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0)
DEFAULT_OUTPUT_FILE: str = "data/benchmarks/servc_oos_champion_eval.json"
OOS_EVAL_SCHEMA: str = "ORCA_SERVC_OOS_EVAL_V1"
OOS_EVAL_SCHEMA_VERSION: str = "1.0.0"


def _script_predict_request() -> Request:
    """FastAPI predict_price_api 호출에 필요한 가상 Request 객체를 생성합니다."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/predictions/predict-price",
            "headers": [],
        }
    )


def _normalized_ord_expr():
    """차수 자리수 정규화 표현식 ('00' -> '000').

    src/ml/dataset.py:141 _normalized_ord 와 동일한 정의입니다.
    """
    return func.substr(literal("000").concat(BidResult.bid_ntce_ord), -3, 3)


def build_oos_sample_query(
    category: str = OOS_CATEGORY,
    cutoff_openg_dt: str = OOS_CUTOFF_TIMESTAMP,
):
    """S0~S5 필터 조건이 적용된 OOS 표본 집합 SQL 쿼리를 구성합니다.

    [필터 단계 정의]
    - S0: Servc 업무구분 및 컷오프 이후 개찰 (rl_openg_dt > '2026-08-03 11:00:00')
    - S1: 낙찰률 비결측 (sucsf_bid_rate IS NOT NULL)
    - S2: 낙찰률 유효 범위 (70.0 <= sucsf_bid_rate <= 110.0)
    - S3: 낙찰금액 비결측 (sucsf_bid_amt IS NOT NULL)
    - S4: 공고 테이블 3-key 매칭 (bid_ntce_no, bid_ntce_ord 정규화, category)
    - S5: 추정가격 정상 범위 (100,000 <= presmpt_prce <= 1,000,000,000,000)
    """
    stmt = (
        select(
            BidAnnouncement.id.label("bid_id"),
            BidAnnouncement.bid_ntce_no,
            BidAnnouncement.bid_ntce_ord,
            BidAnnouncement.category,
            BidAnnouncement.presmpt_prce,
            BidAnnouncement.base_amount,
            BidResult.rl_openg_dt.label("openg_dt"),
            BidResult.sucsf_bid_amt,
            BidResult.sucsf_bid_rate.label("actual_rate"),
        )
        .join(
            BidResult,
            (BidResult.bid_ntce_no == BidAnnouncement.bid_ntce_no)
            & (_normalized_ord_expr() == BidAnnouncement.bid_ntce_ord)
            & (BidResult.category == BidAnnouncement.category),
        )
        .where(
            BidAnnouncement.category == category,
            BidResult.rl_openg_dt > cutoff_openg_dt,
            BidResult.sucsf_bid_rate.is_not(None),
            BidResult.sucsf_bid_rate.between(MIN_WINNING_RATE, MAX_WINNING_RATE),
            BidResult.sucsf_bid_amt.is_not(None),
            BidAnnouncement.presmpt_prce.between(MIN_PRESMPT_PRCE, MAX_PRESMPT_PRCE),
        )
        .order_by(
            BidResult.rl_openg_dt.asc(),
            BidAnnouncement.bid_ntce_no.asc(),
            BidAnnouncement.bid_ntce_ord.asc(),
        )
    )
    return stmt


def collect_oos_samples(
    db_session: Session,
    category: str = OOS_CATEGORY,
    cutoff_openg_dt: str = OOS_CUTOFF_TIMESTAMP,
) -> pd.DataFrame:
    """DB에서 3,589건 유효 OOS 표본 집합을 쿼리하여 DataFrame으로 수집합니다."""
    stmt = build_oos_sample_query(category=category, cutoff_openg_dt=cutoff_openg_dt)
    rows = db_session.execute(stmt).mappings().all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(row) for row in rows])


def compute_sample_keys_sha256(sample_keys: list[str]) -> str:
    """표본 행 키 집합을 사전순으로 정렬하여 SHA-256 체크섬으로 결박합니다.

    입력 리스트의 순서와 무관하게 동일한 행 키 집합이면 항상 동일한 해시가 생성됩니다.
    행 키 형식: f"{bid_ntce_no}:{bid_ntce_ord}:{category}"
    """
    sorted_keys = sorted(str(k).strip() for k in sample_keys if str(k).strip())
    digest = hashlib.sha256()
    for key in sorted_keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def compute_frame_keys_sha256(df: pd.DataFrame) -> str:
    """DataFrame의 각 행에서 표준 키를 추출하여 SHA-256 해시를 계산합니다."""
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    keys = [
        f"{row.bid_ntce_no}:{str(row.bid_ntce_ord).zfill(3)}:{row.category}"
        for row in df.itertuples()
    ]
    return compute_sample_keys_sha256(keys)


def compute_oos_metrics(scored_df: pd.DataFrame) -> dict[str, Any]:
    """채점된 예측 결과 DataFrame으로부터 정본 평가 지표를 산출합니다.

    [계산 정의 출처]
    - MAE, RMSE, 편향, 절대오차 중앙값: scripts/eval_servc_api_path.py:166-172
    - 오차 밴드 비율 (0.5%p ~ 5.0%p): scripts/eval_servc_api_path.py:174-184
    - 예측구간 피복률 및 구간 폭 중앙값: scripts/eval_servc_api_path.py:186-202 및
      scripts/eval_servc_interval_by_group.py:71-92
    """
    if scored_df.empty:
        return {
            "sample_count": 0,
            "mae": None,
            "rmse": None,
            "bias": None,
            "median_abs_err": None,
            "hit_rate_05": None,
            "accuracy_bands": {},
            "coverage": None,
            "coverage_gap": None,
            "median_interval_width": None,
        }

    actual = pd.to_numeric(scored_df["actual"], errors="coerce")
    pred = pd.to_numeric(scored_df["pred"], errors="coerce")
    err = pred - actual
    abs_err = err.abs()
    n = len(scored_df)

    # 기본 오차 지표 (eval_servc_api_path.py 정의)
    mae = float(abs_err.mean())
    rmse = float(np.sqrt((err**2).mean()))
    bias = float(err.mean())
    median_abs_err = float(abs_err.median())
    hit_rate_05 = float((abs_err <= 0.5).mean())

    # 오차 밴드 비율 (eval_servc_api_path.py ERROR_BANDS 정의)
    accuracy_bands: dict[str, Any] = {}
    for band in ERROR_BANDS:
        count_within = int((abs_err <= band).sum())
        accuracy_bands[f"within_{band}_pct"] = {
            "count": count_within,
            "ratio": round(float(count_within / n), 4),
        }

    # 예측구간 지표 (eval_servc_interval_by_group.py 정의)
    coverage = None
    coverage_gap = None
    median_width = None
    if "low" in scored_df.columns and "high" in scored_df.columns:
        low = pd.to_numeric(scored_df["low"], errors="coerce")
        high = pd.to_numeric(scored_df["high"], errors="coerce")
        valid_intervals = low.notna() & high.notna()
        if valid_intervals.any():
            inside = (actual[valid_intervals] >= low[valid_intervals]) & (
                actual[valid_intervals] <= high[valid_intervals]
            )
            cov_val = float(inside.mean())
            coverage = round(cov_val, 4)
            coverage_gap = round(cov_val - 0.90, 4)
            width = high[valid_intervals] - low[valid_intervals]
            median_width = round(float(width.median()), 4)

    return {
        "sample_count": n,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "bias": round(bias, 4),
        "median_abs_err": round(median_abs_err, 4),
        "hit_rate_05": round(hit_rate_05, 4),
        "accuracy_bands": accuracy_bands,
        "coverage": coverage,
        "coverage_gap": coverage_gap,
        "median_interval_width": median_width,
    }


def compute_group_metrics(scored_df: pd.DataFrame) -> dict[str, Any]:
    """하한율 보유/결측 집단별 세부 지표를 산출합니다.

    출처: scripts/eval_servc_interval_by_group.py:71-92
    """
    if scored_df.empty or "is_lwlt_missing" not in scored_df.columns:
        return {}

    groups = {}
    with_lwlt = scored_df[~scored_df["is_lwlt_missing"]]
    missing_lwlt = scored_df[scored_df["is_lwlt_missing"]]

    groups["with_lwlt"] = compute_oos_metrics(with_lwlt)
    groups["missing_lwlt"] = compute_oos_metrics(missing_lwlt)
    return groups


def get_model_provenance(model_id: str = DEFAULT_MODEL_ID) -> dict[str, Any]:
    """Champion 서빙 모델의 식별 정보와 가중치 파일 SHA-256을 조회합니다."""
    model_dir = Path(settings.MODEL_FILES_DIR) / model_id
    weights_path = model_dir / "model.bin"
    meta_path = model_dir / "metadata.json"

    weights_sha256 = None
    if weights_path.exists():
        try:
            weights_sha256 = hashlib.sha256(weights_path.read_bytes()).hexdigest()
        except OSError:
            weights_sha256 = "read_error"
    else:
        weights_sha256 = "file_not_found"

    metadata: dict[str, Any] = {}
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {"error": "invalid_metadata"}

    return {
        "model_id": model_id,
        "model_dir": str(model_dir),
        "weights_path": str(weights_path),
        "weights_sha256": weights_sha256,
        "weights_exist": weights_path.exists(),
        "model_version": metadata.get("version") or metadata.get("timestamp") or "unknown",
        "objective": metadata.get("objective") or "quantile(0.5)",
    }


def evaluate_oos_sample_row(
    session: Session,
    row: Any,
    predict_fn: Callable[[int, Session], Any] | None = None,
) -> dict[str, Any]:
    """OOS 표본 1건에 대해 운영 API 경로(predict_price_api)를 통해 예측을 수행합니다.

    특징 생성은 train/serve 단일 공급원인 src/ml/features.py 및 dataset.py를 통합니다.
    """
    bid_id = int(row.bid_id)
    actual_rate = float(row.actual_rate)

    # 하한율 결측 여부 판정 (dataset.announcement_feature_payload 활용)
    bid = session.get(BidAnnouncement, bid_id)
    payload = announcement_feature_payload(bid) if bid else {}
    raw_lwlt = payload.get("lwlt_rate")
    is_missing = raw_lwlt in (None, "", 0, "0")

    if predict_fn is not None:
        pred_res = predict_fn(bid_id, session)
        pred_rate = pred_res.get("prediction_rate")
        rate_low = pred_res.get("rate_low")
        rate_high = pred_res.get("rate_high")
        model_name = pred_res.get("model_name", DEFAULT_MODEL_ID)
    else:
        response = predict_price_api(
            PredictPriceRequest(bid_id=bid_id, user_price="0"),
            _script_predict_request(),
            db=session,
        )
        pred_rate = (
            float(response.prediction_rate) if response.prediction_rate is not None else None
        )
        rate_low = float(response.rate_low) if response.rate_low is not None else None
        rate_high = float(response.rate_high) if response.rate_high is not None else None
        model_name = response.model_name

    return {
        "bid_id": bid_id,
        "bid_ntce_no": str(row.bid_ntce_no),
        "bid_ntce_ord": str(row.bid_ntce_ord),
        "category": str(row.category),
        "actual": actual_rate,
        "pred": pred_rate,
        "low": rate_low,
        "high": rate_high,
        "model": model_name,
        "is_lwlt_missing": is_missing,
    }


def run_servc_oos_evaluation(
    session: Session | None = None,
    samples_df: pd.DataFrame | None = None,
    predict_fn: Callable[[int, Session], Any] | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Servc Champion 3,589건 유효 OOS 고정 평가 파이프라인을 실행합니다."""
    start_time = datetime.datetime.now(datetime.UTC).isoformat()

    # 1. 표본 수집 (주입된 DataFrame이 없으면 DB에서 수집)
    if samples_df is None:
        if session is None:
            raise ValueError("session 또는 samples_df 중 하나는 필수입니다.")
        df_samples = collect_oos_samples(session)
    else:
        df_samples = samples_df.copy()

    actual_sample_count = len(df_samples)
    sample_diff = actual_sample_count - EXPECTED_OOS_SAMPLE_COUNT
    canonical = actual_sample_count == EXPECTED_OOS_SAMPLE_COUNT

    # 2. 행 키 집합 SHA-256 결박
    keys_sha256 = compute_frame_keys_sha256(df_samples)

    # 3. 모델 Provenance 식별
    model_provenance = get_model_provenance(model_id=model_id)

    # 4. Dry-run 모드이거나 표본이 없는 경우 즉시 스키마 반환
    if dry_run or df_samples.empty:
        return {
            "schema": OOS_EVAL_SCHEMA,
            "version": OOS_EVAL_SCHEMA_VERSION,
            "evaluated_at": start_time,
            "dry_run": dry_run,
            "canonical": canonical,
            "expected_sample_count": EXPECTED_OOS_SAMPLE_COUNT,
            "actual_sample_count": actual_sample_count,
            "sample_count_diff": sample_diff,
            "sample_keys_sha256": keys_sha256,
            "model_provenance": model_provenance,
            "overall_metrics": compute_oos_metrics(pd.DataFrame()),
            "group_metrics": {},
            "skipped_count": 0,
            "sample_definition": (
                f"Servc bids with openg_dt > '{OOS_CUTOFF_TIMESTAMP}', winning_rate in [70, 110], "
                f"presmpt_prce in [100k, 1T], matched to bid_announcements"
            ),
        }

    # 5. 표본별 운영 예측 평가 수행
    scored_records: list[dict[str, Any]] = []
    skipped_count = 0

    if session is not None:
        for row in df_samples.itertuples():
            try:
                rec = evaluate_oos_sample_row(session, row, predict_fn=predict_fn)
                if rec.get("pred") is not None:
                    scored_records.append(rec)
                else:
                    skipped_count += 1
            except Exception as exc:
                logger.debug("OOS 평가 행 제외 (bid_id=%s): %s", getattr(row, "bid_id", None), exc)
                skipped_count += 1

    scored_df = pd.DataFrame(scored_records)

    # 6. 지표 산출
    overall_metrics = compute_oos_metrics(scored_df)
    group_metrics = compute_group_metrics(scored_df)

    return {
        "schema": OOS_EVAL_SCHEMA,
        "version": OOS_EVAL_SCHEMA_VERSION,
        "evaluated_at": start_time,
        "dry_run": False,
        "canonical": canonical,
        "expected_sample_count": EXPECTED_OOS_SAMPLE_COUNT,
        "actual_sample_count": actual_sample_count,
        "sample_count_diff": sample_diff,
        "sample_keys_sha256": keys_sha256,
        "model_provenance": model_provenance,
        "overall_metrics": overall_metrics,
        "group_metrics": group_metrics,
        "skipped_count": skipped_count,
        "sample_definition": (
            f"Servc bids with openg_dt > '{OOS_CUTOFF_TIMESTAMP}', winning_rate in [70, 110], "
            f"presmpt_prce in [100k, 1T], matched to bid_announcements"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Servc Champion 3,589건 유효 OOS 고정 평가 하네스")
    parser.add_argument(
        "--output", default=None, help="결과 JSON 저장 경로 (미지정 시 stdout 출력)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="모델 로드 없이 표본 수집 및 키 결박 해시만 검증"
    )
    parser.add_argument(
        "--model-id", default=DEFAULT_MODEL_ID, help="평가 대상 Champion 모델 식별자"
    )
    args = parser.parse_args()

    from src.app.core.db import SessionLocal

    session = SessionLocal()
    try:
        print("=== Servc 현 Champion 유효 OOS 고정 평가 하네스 ===")
        print(f"기준 컷오프: {OOS_CUTOFF_TIMESTAMP} 이후 개찰")
        print(f"기대 정본 표본 수: {EXPECTED_OOS_SAMPLE_COUNT:,}건")
        print(f"평가 대상 모델: {args.model_id}")

        result = run_servc_oos_evaluation(
            session=session,
            model_id=args.model_id,
            dry_run=args.dry_run,
        )

        print("\n--- 평가 실행 메타데이터 ---")
        print(f"실측 표본 수      : {result['actual_sample_count']:,}건")
        print(f"기대 표본 수      : {result['expected_sample_count']:,}건")
        print(f"표본 수 차이      : {result['sample_count_diff']:+d}건")
        print(f"정본 판정(canonical): {result['canonical']}")
        print(f"행 키 SHA-256     : {result['sample_keys_sha256']}")
        print(f"가중치 SHA-256    : {result['model_provenance']['weights_sha256']}")

        if not args.dry_run and result["overall_metrics"].get("mae") is not None:
            metrics = result["overall_metrics"]
            print("\n--- 전체 성능 지표 (Overall) ---")
            print(
                f"채점 건수         : {metrics['sample_count']:,}건 (제외 {result['skipped_count']}건)"
            )
            print(f"MAE               : {metrics['mae']:.4f}%p")
            print(f"RMSE              : {metrics['rmse']:.4f}%p")
            print(f"편향 (Bias)       : {metrics['bias']:+.4f}%p")
            print(f"0.5%p 적중률      : {metrics['hit_rate_05']:.2%}")
            if metrics.get("coverage") is not None:
                print(
                    f"예측구간 피복률   : {metrics['coverage']:.2%} (명목 90% 대비 {metrics['coverage_gap']:+.2%})"
                )
                print(f"구간 폭 중앙값    : {metrics['median_interval_width']:.4f}%p")

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"\n평가 결과가 성공적으로 저장되었습니다: {out_path}")
        else:
            print("\n결과 JSON 요약:")
            print(json.dumps(result, ensure_ascii=False, indent=2))

        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
