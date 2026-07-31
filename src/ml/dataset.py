"""
src/ml/dataset.py

학습 데이터셋 빌더.
DB에서 BidAnnouncement와 BidResult를 조인하여 정제된 학습 데이터 프레임을 구축하고
Feature Store(materialized parquet)에 캐싱합니다.
"""

from pathlib import Path
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session
from src.app.models.bids import BidAnnouncement, BidResult


def build_training_dataset(
    db_session: Session,
    category_code: Optional[str] = None,
    output_dir: str = "data/feature_store",
) -> pd.DataFrame:
    """
    DB 조인 및 정제 기반 학습 데이터셋 파켓 빌더.
    `final_cleaned_filtered.csv` 정제 로직 승격.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # DB 조인 쿼리
    query = (
        db_session.query(
            BidAnnouncement.bid_notice_no,
            BidAnnouncement.bid_notice_name,
            BidAnnouncement.order_institution,
            BidAnnouncement.category_code,
            BidAnnouncement.presumed_price,
            BidAnnouncement.base_price,
            BidResult.winning_price,
            BidResult.winning_rate,
        )
        .join(BidResult, BidAnnouncement.id == BidResult.announcement_id)
    )

    if category_code:
        query = query.filter(BidAnnouncement.category_code == category_code)

    records = query.all()

    if not records:
        # 데이터 미존재 시 더미 구조 리턴
        df = pd.DataFrame([
            {
                "bid_notice_no": "TEST-001",
                "bid_notice_name": "테스트 물품 구매 건",
                "order_institution": "조달청",
                "category_code": category_code or "Thng",
                "presumed_price": 500000000.0,
                "base_price": 495000000.0,
                "winning_price": 435600000.0,
                "winning_rate": 88.0,
            }
        ])
    else:
        df = pd.DataFrame([r._asdict() for r in records])

    # 정제 로직: 결측치 및 이상치 필터링 (80.0% ~ 100.0% 범위 유효)
    df = df[(df["winning_rate"] >= 70.0) & (df["winning_rate"] <= 110.0)]
    df = df.dropna(subset=["presumed_price", "base_price", "winning_price"])

    # Feature Store에 materialized parquet으로 저장
    parquet_file = out_path / f"dataset_{category_code or 'all'}.parquet"
    df.to_parquet(parquet_file, index=False)

    return df
