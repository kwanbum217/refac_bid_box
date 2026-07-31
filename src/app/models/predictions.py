from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, JSON, String
from src.app.core.db import Base


class PredictionResult(Base):
    __tablename__ = "prediction_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bid_notice_no = Column(String(100), nullable=False, index=True)
    model_version = Column(String(50), nullable=False, index=True)
    predicted_price = Column(Float, nullable=False)
    predicted_rate = Column(Float, nullable=False)
    features_used = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RetrainLog(Base):
    __tablename__ = "retrain_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trigger_source = Column(String(50), nullable=False)  # manual, scheduled, drift_psi
    champion_version = Column(String(50), nullable=False)
    challenger_version = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False)  # promoted, archived, failed
    metrics_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
