from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow


class PredictionResult(Base):
    """예측 결과 이력 테이블 (원래 db_table: prediction_results)"""

    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    user_input_price: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="사용자 투찰 금액"
    )
    model_version: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="사용한 모델 버전"
    )
    predicted_lower_bound: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="예측 하한가"
    )
    predicted_upper_bound: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="예측 상한가"
    )
    predicted_optimal_price: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="최적 투찰 추천가"
    )
    confidence_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True, comment="신뢰도 점수"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="예측 일시"
    )


class RetrainLog(Base):
    """재학습 이력 로그 테이블"""

    __tablename__ = "retrain_logs"

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)
    champion_version: Mapped[str] = mapped_column(String(50), nullable=False)
    challenger_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    metrics_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
