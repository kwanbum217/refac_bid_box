from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, JSON, Numeric, String
from src.app.core.db import Base, PKBigInteger


class PredictionResult(Base):
    """예측 결과 이력 테이블 (원래 db_table: prediction_results)"""
    __tablename__ = "prediction_results"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no = Column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord = Column(String(10), nullable=False, default="000", comment="입찰공고차수")
    user_input_price = Column(BigInteger, nullable=True, comment="사용자 투찰 금액")
    model_version = Column(String(100), nullable=False, comment="사용한 모델 버전")
    predicted_lower_bound = Column(BigInteger, nullable=True, comment="예측 하한가")
    predicted_upper_bound = Column(BigInteger, nullable=True, comment="예측 상한가")
    predicted_optimal_price = Column(BigInteger, nullable=True, comment="최적 투찰 추천가")
    confidence_score = Column(Numeric(5, 4), nullable=True, comment="신뢰도 점수")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="예측 일시")



class RetrainLog(Base):
    """재학습 이력 로그 테이블"""
    __tablename__ = "retrain_logs"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    trigger_source = Column(String(50), nullable=False)
    champion_version = Column(String(50), nullable=False)
    challenger_version = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False)
    metrics_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
