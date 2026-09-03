"""
tests/test_drift_monitor_window.py

PSI 드리프트 모니터링 평가 윈도우 쿼리 및 비파괴 관측 검증 테스트.
- build_training_dataset 시그니처 및 기본값 하위 호환성 검증
- persist=False 시 Parquet 캐시 미생성 및 persist=True 시 정상 저장 검증
- [start_at, end_at) 반열림 구간 필터링 및 경계값(start_at 포함, end_at 제외) 검증
- 윈도우 밖 표본 배제 검증
- require_announcement=False 경로에서의 윈도우 필터링 검증
- drift_monitor_task 가 evaluation_window_days 구간 및 persist=False 를 전달하는지 검증
- 표본 부재(0건) 및 표본 부족(<100건) 시 INSUFFICIENT_DATA 기록 및 조용한 통과 방지 검증
- 실제 MySQL 없이 SQLite isolated_db 로 동작 검증
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.app.core.config import settings
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.predictions import RetrainLog
from src.ml.dataset import build_training_dataset
from src.ml.monitoring import save_baseline_distributions
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks.scheduled_tasks import drift_monitor_task


def _insert_sample_bid(
    db,
    notice_no: str,
    openg_dt: datetime,
    category: str = "Servc",
    winning_rate: float = 88.0,
    sucsf_bid_amt: int = 100_000_000,
    presmpt_prce: int = 110_000_000,
    with_announcement: bool = True,
):
    db.add(
        BidResult(
            bid_ntce_no=notice_no,
            bid_ntce_ord="00",
            category=category,
            bid_ntce_nm=f"공고 {notice_no}",
            bidwinnr_nm="낙찰업체",
            dminstt_nm="수요기관",
            sucsf_bid_amt=sucsf_bid_amt,
            sucsf_bid_rate=winning_rate,
            rl_openg_dt=openg_dt,
            collected_at=openg_dt,
        )
    )
    if with_announcement:
        db.add(
            BidAnnouncement(
                bid_ntce_no=notice_no,
                bid_ntce_ord="000",
                category=category,
                bid_ntce_nm=f"공고 {notice_no}",
                ntce_instt_nm="공고기관",
                dminstt_nm="수요기관",
                cntrct_mthd_nm="일반경쟁",
                ntce_kind_nm="실공고",
                bid_methd_nm="전자입찰",
                presmpt_prce=presmpt_prce,
                base_amount=presmpt_prce,
                bid_ntce_dt=openg_dt - timedelta(days=7),
                bid_clse_dt=openg_dt - timedelta(hours=1),
                raw_data={"sucsfbidLwltRate": "87.745", "srvceDivNm": "일반용역"},
                collected_at=openg_dt,
            )
        )
    db.commit()


def test_build_training_dataset_default_arguments_and_persist_true(isolated_db, tmp_path):
    """기본값(start_at=None, end_at=None, persist=True)에서 전체 이력을 읽고 Parquet 캐시를 저장합니다."""
    base_time = datetime(2026, 8, 1, 10, 0, 0)
    for i in range(3):
        _insert_sample_bid(
            isolated_db,
            notice_no=f"N00000{i}",
            openg_dt=base_time + timedelta(days=i),
            category="Servc",
        )

    out_dir = str(tmp_path / "feature_store")
    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=out_dir)

    assert len(df) == 3
    parquet_path = Path(out_dir) / "dataset_Servc.parquet"
    assert parquet_path.exists()

    df_cached = pd.read_parquet(parquet_path)
    assert len(df_cached) == 3


def test_build_training_dataset_persist_false_does_not_create_file(isolated_db, tmp_path):
    """persist=False 시 DataFrame 은 반환하되 Parquet 파일은 생성하지 않습니다."""
    base_time = datetime(2026, 8, 1, 10, 0, 0)
    for i in range(2):
        _insert_sample_bid(
            isolated_db,
            notice_no=f"NP0000{i}",
            openg_dt=base_time + timedelta(days=i),
            category="Servc",
        )

    out_dir = str(tmp_path / "non_persisted_store")
    df = build_training_dataset(
        isolated_db,
        category_code="Servc",
        output_dir=out_dir,
        persist=False,
    )

    assert len(df) == 2
    parquet_path = Path(out_dir) / "dataset_Servc.parquet"
    assert not parquet_path.exists()
    assert not Path(out_dir).exists()


def test_build_training_dataset_half_open_window_filtering(isolated_db, tmp_path):
    """[start_at, end_at) 반열림 구간 필터링 검증:
    - start_at 이상(>=): 시작 경계값 포함
    - end_at 미만(<): 끝 경계값 제외
    - 구간 밖 표본 배제
    """
    # 표본 5건 배치:
    # 1. 2026-08-01 00:00:00 -> 윈도우 이전 (제외)
    # 2. 2026-08-10 00:00:00 -> start_at 과 동일 (포함)
    # 3. 2026-08-15 12:00:00 -> 윈도우 내부 (포함)
    # 4. 2026-08-20 00:00:00 -> end_at 과 동일 (제외)
    # 5. 2026-08-25 00:00:00 -> 윈도우 이후 (제외)
    samples = [
        ("W_BEFORE", datetime(2026, 8, 1, 0, 0, 0)),
        ("W_START_EDGE", datetime(2026, 8, 10, 0, 0, 0)),
        ("W_INSIDE", datetime(2026, 8, 15, 12, 0, 0)),
        ("W_END_EDGE", datetime(2026, 8, 20, 0, 0, 0)),
        ("W_AFTER", datetime(2026, 8, 25, 0, 0, 0)),
    ]

    for notice_no, dt in samples:
        _insert_sample_bid(isolated_db, notice_no=notice_no, openg_dt=dt, category="Servc")

    start_window = datetime(2026, 8, 10, 0, 0, 0)
    end_window = datetime(2026, 8, 20, 0, 0, 0)

    # 1. datetime 객체로 윈도우 필터링
    df_window = build_training_dataset(
        isolated_db,
        category_code="Servc",
        start_at=start_window,
        end_at=end_window,
        persist=False,
    )

    assert len(df_window) == 2
    matched_notices = set(df_window["bid_ntce_no"].tolist())
    assert matched_notices == {"W_START_EDGE", "W_INSIDE"}
    assert "W_BEFORE" not in matched_notices
    assert "W_END_EDGE" not in matched_notices
    assert "W_AFTER" not in matched_notices

    # 2. start_at 만 지정한 경우 (start_at 이상 전체)
    df_start_only = build_training_dataset(
        isolated_db,
        category_code="Servc",
        start_at=start_window,
        persist=False,
    )
    assert len(df_start_only) == 4
    assert set(df_start_only["bid_ntce_no"].tolist()) == {
        "W_START_EDGE",
        "W_INSIDE",
        "W_END_EDGE",
        "W_AFTER",
    }

    # 3. end_at 만 지정한 경우 (end_at 미만 전체)
    df_end_only = build_training_dataset(
        isolated_db,
        category_code="Servc",
        end_at=end_window,
        persist=False,
    )
    assert len(df_end_only) == 3
    assert set(df_end_only["bid_ntce_no"].tolist()) == {
        "W_BEFORE",
        "W_START_EDGE",
        "W_INSIDE",
    }


def test_build_training_dataset_require_announcement_false_with_window(isolated_db):
    """require_announcement=False 경로에서도 개찰일 기준 윈도우 필터가 정상 적용됩니다."""
    samples = [
        ("WO_BEFORE", datetime(2026, 8, 5, 0, 0, 0)),
        ("WO_INSIDE", datetime(2026, 8, 12, 0, 0, 0)),
        ("WO_AFTER", datetime(2026, 8, 25, 0, 0, 0)),
    ]
    for notice_no, dt in samples:
        _insert_sample_bid(
            isolated_db,
            notice_no=notice_no,
            openg_dt=dt,
            category="Servc",
            with_announcement=False,
        )

    df = build_training_dataset(
        isolated_db,
        category_code="Servc",
        require_announcement=False,
        start_at=datetime(2026, 8, 10, 0, 0, 0),
        end_at=datetime(2026, 8, 20, 0, 0, 0),
        persist=False,
    )

    assert len(df) == 1
    assert df.iloc[0]["bid_ntce_no"] == "WO_INSIDE"


@pytest.mark.asyncio
async def test_drift_monitor_task_passes_window_interval_and_persist_false(
    isolated_db, tmp_path, monkeypatch
):
    """drift_monitor_task 가 evaluation_window_days 로 [now - N days, now) 구간을 계산해 persist=False 로 넘깁니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)

    # baseline 생성
    df_train = pd.DataFrame(
        {
            "log_price": [10.0] * 120,
            "srvce_div_nm": ["일반용역"] * 120,
        }
    )
    for _category, model_name in CATEGORY_MODEL_NAMES.items():
        base_dir = tmp_path / model_name / "baseline"
        save_baseline_distributions(
            df_feat=df_train,
            feature_columns=["log_price", "srvce_div_nm"],
            target_dir=base_dir,
            model_name=model_name,
            model_version="v_20260903_001",
        )

    captured_calls = []

    def _spy_build_dataset(db, category_code, **kwargs):
        captured_calls.append({"category": category_code, "kwargs": kwargs})
        return pd.DataFrame(
            [
                {
                    "presumed_price": 100_000_000.0,
                    "base_price": 99_000_000.0,
                    "winning_rate": 88.0,
                    "openg_dt": "2026-08-01",
                    "srvce_div_nm": "일반용역",
                    "log_price": 10.0,
                }
                for _ in range(120)
            ]
        )

    monkeypatch.setattr("src.tasks.scheduled_tasks.build_training_dataset", _spy_build_dataset)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    assert len(captured_calls) == len(CATEGORY_MODEL_NAMES)

    for call in captured_calls:
        kw = call["kwargs"]
        assert kw.get("persist") is False
        start_at = kw.get("start_at")
        end_at = kw.get("end_at")
        assert isinstance(start_at, datetime)
        assert isinstance(end_at, datetime)
        diff = end_at - start_at
        assert abs(diff.total_seconds() - 7 * 86400) < 5


@pytest.mark.asyncio
async def test_drift_monitor_task_insufficient_samples_when_empty_records(
    isolated_db, tmp_path, monkeypatch
):
    """최근 윈도우 내 데이터가 0건일 때 조용히 통과하지 않고 INSUFFICIENT_DATA 를 retrain_logs 에 기록합니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)

    # baseline 생성
    df_train = pd.DataFrame(
        {
            "log_price": [10.0] * 120,
            "srvce_div_nm": ["일반용역"] * 120,
        }
    )
    for _category, model_name in CATEGORY_MODEL_NAMES.items():
        base_dir = tmp_path / model_name / "baseline"
        save_baseline_distributions(
            df_feat=df_train,
            feature_columns=["log_price", "srvce_div_nm"],
            target_dir=base_dir,
            model_name=model_name,
            model_version="v_20260903_001",
        )

    # DB 에 오래된 데이터만 삽입 (현재 윈도우 [now-7d, now) 에 포함되지 않음)
    old_date = datetime(2020, 1, 1, 0, 0, 0)
    _insert_sample_bid(isolated_db, notice_no="OLD_001", openg_dt=old_date, category="Servc")

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    categories = outcome["categories"]
    assert "Servc" in categories
    assert categories["Servc"]["status"] == "INSUFFICIENT_DATA"
    assert categories["Servc"]["samples"] == 0

    # retrain_logs 확인
    logs = isolated_db.query(RetrainLog).filter(RetrainLog.trigger_source == "drift_monitor").all()
    assert len(logs) >= 1
    servc_logs = [
        log_item for log_item in logs if log_item.champion_version == CATEGORY_MODEL_NAMES["Servc"]
    ]
    assert len(servc_logs) == 1
    assert servc_logs[0].status == "INSUFFICIENT_DATA"
    summary = servc_logs[0].metrics_summary
    assert "evaluation_window_days" in summary
    assert summary["recent_samples"] == 0
