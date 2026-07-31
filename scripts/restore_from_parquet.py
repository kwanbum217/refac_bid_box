#!/usr/bin/env python3
"""
data/exports parquet 덤프로부터 입찰공고/낙찰결과 테이블을 복원합니다.

원본 bid_box DB(bid_announcements 1,698,014행 / bid_results 2,996,476행)가 유실된 상황에서,
동일 스키마로 남아 있는 parquet 덤프를 무손실 기준으로 재적재합니다.

- 원본 `id`를 그대로 보존합니다 (G1 데이터 무손실).
- (bid_ntce_no, bid_ntce_ord, category) 유니크 제약으로 중복은 자동 무시됩니다.
- G2B 원시 API 컬럼이 함께 저장된 덤프는 `raw_data` JSON으로 복원해
  `resolved_base_amount` / `prediction_reference_amount` 산출이 원본과 동일해지도록 합니다.

사용법:
    DATABASE_URL=mysql+pymysql://... python scripts/restore_from_parquet.py
    python scripts/restore_from_parquet.py --dry-run
    python scripts/restore_from_parquet.py --only bid_results_thng
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyarrow.parquet as pq  # noqa: E402
from sqlalchemy import insert  # noqa: E402

from src.app.core.db import Base, SessionLocal, engine  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402

DEFAULT_EXPORT_DIR = PROJECT_ROOT.parent / "bid_box" / "data" / "exports"
BATCH_ROWS = 20_000

ANNOUNCEMENT_COLUMNS = (
    "id",
    "bid_ntce_nm",
    "bid_ntce_no",
    "bid_ntce_ord",
    "ntce_instt_nm",
    "dminstt_nm",
    "presmpt_prce",
    "bid_ntce_dt",
    "bid_clse_dt",
    "openg_dt",
    "ntce_kind_nm",
    "bid_methd_nm",
    "cntrct_mthd_nm",
    "collected_at",
    "category",
)
RESULT_COLUMNS = (
    "id",
    "bid_ntce_nm",
    "bid_ntce_no",
    "bid_ntce_ord",
    "bidwinnr_nm",
    "sucsf_bid_amt",
    "sucsf_bid_rate",
    "rl_openg_dt",
    "dminstt_nm",
    "collected_at",
    "category",
)
ANNOUNCEMENT_DATETIME_COLUMNS = ("bid_ntce_dt", "bid_clse_dt", "openg_dt", "collected_at")
RESULT_DATETIME_COLUMNS = ("rl_openg_dt", "collected_at")

# raw_data 로 보존할 G2B 원시 예산 필드 (extract_business_budget 가 참조)
RAW_DATA_PRIORITY_KEYS = ("asignBdgtAmt", "bdgtAmt", "presmptPrce", "govsplyAmt")

DATASETS = {
    "bid_announcements_thng": (BidAnnouncement, "Thng"),
    "bid_announcements_cnstwk": (BidAnnouncement, "Cnstwk"),
    "bid_announcements_servc": (BidAnnouncement, "Servc"),
    "bid_results_thng": (BidResult, "Thng"),
    "bid_results_cnstwk": (BidResult, "Cnstwk"),
    "bid_results_servc": (BidResult, "Servc"),
}


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _to_datetime(value: Any) -> datetime | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 8], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.split("+")[0].strip())
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(numeric) else numeric


def _to_text(value: Any, max_length: int) -> str | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] if text else None


def _format_ord(value: Any, width: int) -> str:
    numeric = _to_int(value)
    if numeric is not None:
        return f"{numeric:0{width}d}"
    text = _to_text(value, 10)
    return text if text else "0" * width


def _build_raw_data(record: dict[str, Any], extra_keys: tuple[str, ...]) -> dict[str, Any] | None:
    """G2B 원시 컬럼을 raw_data JSON 으로 복원합니다 (기초금액 해석에 필요)."""
    if not extra_keys:
        return None
    payload = {}
    for key in extra_keys:
        cleaned = _clean_scalar(record.get(key))
        if cleaned is not None:
            payload[key] = cleaned if not isinstance(cleaned, float) else cleaned
    if not payload:
        return None
    if not any(key in payload for key in RAW_DATA_PRIORITY_KEYS):
        # 예산 필드가 전혀 없으면 raw_data 를 만들지 않습니다.
        # (원본 resolved_base_amount 는 raw_data 가 있으면 base_amount 폴백을 하지 않기 때문)
        return None
    return payload


def _map_announcement(record: dict[str, Any], category: str, extra_keys: tuple[str, ...]) -> dict:
    return {
        "id": _to_int(record.get("id")),
        "bid_ntce_nm": _to_text(record.get("bid_ntce_nm"), 500),
        "bid_ntce_no": _to_text(record.get("bid_ntce_no"), 50) or "",
        "bid_ntce_ord": _format_ord(record.get("bid_ntce_ord"), 3),
        "ntce_instt_nm": _to_text(record.get("ntce_instt_nm"), 200),
        "dminstt_nm": _to_text(record.get("dminstt_nm"), 200),
        "base_amount": _to_int(record.get("bdgtAmt") or record.get("asignBdgtAmt")),
        "presmpt_prce": _to_int(record.get("presmpt_prce")),
        "bid_ntce_dt": _to_datetime(record.get("bid_ntce_dt")),
        "bid_clse_dt": _to_datetime(record.get("bid_clse_dt")),
        "openg_dt": _to_datetime(record.get("openg_dt")),
        "ntce_kind_nm": _to_text(record.get("ntce_kind_nm"), 100),
        "bid_methd_nm": _to_text(record.get("bid_methd_nm"), 100),
        "cntrct_mthd_nm": _to_text(record.get("cntrct_mthd_nm"), 100),
        "category": _to_text(record.get("category"), 10) or category,
        "raw_data": _build_raw_data(record, extra_keys),
        "collected_at": _to_datetime(record.get("collected_at")) or datetime.utcnow(),
    }


def _map_result(record: dict[str, Any], category: str, extra_keys: tuple[str, ...]) -> dict:
    return {
        "id": _to_int(record.get("id")),
        "bid_ntce_nm": _to_text(record.get("bid_ntce_nm"), 500),
        "bid_ntce_no": _to_text(record.get("bid_ntce_no"), 50) or "",
        "bid_ntce_ord": _format_ord(record.get("bid_ntce_ord"), 2),
        "bidwinnr_nm": _to_text(record.get("bidwinnr_nm"), 200),
        "sucsf_bid_amt": _to_int(record.get("sucsf_bid_amt")),
        "sucsf_bid_rate": _to_float(record.get("sucsf_bid_rate")),
        "rl_openg_dt": _to_datetime(record.get("rl_openg_dt")),
        "dminstt_nm": _to_text(record.get("dminstt_nm"), 200),
        "category": _to_text(record.get("category"), 10) or category,
        "raw_data": _build_raw_data(record, extra_keys),
        "collected_at": _to_datetime(record.get("collected_at")) or datetime.utcnow(),
    }


def _ignore_prefix() -> str:
    return "OR IGNORE" if engine.dialect.name == "sqlite" else "IGNORE"


def _load_dataset(name: str, path: Path, *, dry_run: bool) -> tuple[int, int]:
    model, category = DATASETS[name]
    is_announcement = model is BidAnnouncement
    base_columns = ANNOUNCEMENT_COLUMNS if is_announcement else RESULT_COLUMNS
    mapper = _map_announcement if is_announcement else _map_result

    parquet_file = pq.ParquetFile(path)
    available = set(parquet_file.schema.names)
    read_columns = [c for c in base_columns if c in available]
    extra_keys = tuple(sorted(available - set(base_columns)))
    # raw_data 재구성에 필요한 원시 컬럼만 함께 읽습니다.
    raw_columns = [k for k in extra_keys if k in available]
    read_columns.extend(raw_columns)

    total = parquet_file.metadata.num_rows
    inserted = 0
    print(f"\n[{name}] {total:,}행 / 원시컬럼 {len(raw_columns)}개")

    if dry_run:
        sample = next(parquet_file.iter_batches(batch_size=1, columns=read_columns))
        record = {k: v[0] for k, v in sample.to_pydict().items()}
        print("  샘플 매핑:", mapper(record, category, tuple(raw_columns)))
        return total, 0

    stmt = insert(model.__table__).prefix_with(_ignore_prefix())
    session = SessionLocal()
    try:
        for batch in parquet_file.iter_batches(batch_size=BATCH_ROWS, columns=read_columns):
            columns = batch.to_pydict()
            rows = [
                mapper(
                    {key: columns[key][i] for key in columns},
                    category,
                    tuple(raw_columns),
                )
                for i in range(batch.num_rows)
            ]
            rows = [row for row in rows if row["bid_ntce_no"]]
            if not rows:
                continue
            session.execute(stmt, rows)
            session.commit()
            inserted += len(rows)
            print(f"  적재 {inserted:,}/{total:,}", end="\r", flush=True)
    finally:
        session.close()

    print(f"  적재 완료 {inserted:,}/{total:,}      ")
    return total, inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="parquet 덤프에서 입찰 데이터 복원")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--only", action="append", help="특정 데이터셋만 적재")
    parser.add_argument("--dry-run", action="store_true", help="적재 없이 매핑만 검증")
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    if not export_dir.exists():
        print(f"FAIL: export 디렉토리 없음: {export_dir}")
        return 1

    targets = args.only or list(DATASETS)
    print("=" * 66)
    print("parquet 기반 입찰 데이터 복원")
    print(f"  대상 DB : {engine.url.render_as_string(hide_password=True)}")
    print(f"  소스    : {export_dir}")
    print("=" * 66)

    if not args.dry_run:
        Base.metadata.create_all(engine, tables=[BidAnnouncement.__table__, BidResult.__table__])

    summary = []
    for name in targets:
        if name not in DATASETS:
            print(f"SKIP: 알 수 없는 데이터셋 {name}")
            continue
        path = export_dir / f"{name}.parquet"
        if not path.exists():
            print(f"SKIP: 파일 없음 {path.name}")
            continue
        summary.append((name, *_load_dataset(name, path, dry_run=args.dry_run)))

    print("\n" + "-" * 66)
    for name, total, inserted in summary:
        print(f"  {name:34s} 원본 {total:>10,}  적재 {inserted:>10,}")

    if not args.dry_run:
        from sqlalchemy import func, select

        session = SessionLocal()
        try:
            ann = session.scalar(select(func.count(BidAnnouncement.id)))
            res = session.scalar(select(func.count(BidResult.id)))
        finally:
            session.close()
        print("-" * 66)
        print(f"  bid_announcements 최종 : {ann:,}행")
        print(f"  bid_results       최종 : {res:,}행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
