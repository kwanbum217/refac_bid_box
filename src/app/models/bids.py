from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship
from src.app.core.db import Base


class BidAnnouncement(Base):
    __tablename__ = "bid_announcement"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bid_notice_no = Column(String(100), unique=True, nullable=False, index=True)
    bid_notice_name = Column(String(255), nullable=False)
    order_institution = Column(String(150), nullable=False, index=True)
    category_code = Column(String(50), nullable=False, index=True)  # Thng, Servc, Cnstwk
    presumed_price = Column(Float, nullable=False, default=0.0)
    base_price = Column(Float, nullable=False, default=0.0)
    notice_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    results = relationship("BidResult", back_populates="announcement", cascade="all, delete-orphan")


class BidResult(Base):
    __tablename__ = "bid_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    announcement_id = Column(BigInteger, ForeignKey("bid_announcement.id"), nullable=False, index=True)
    winning_company = Column(String(150), nullable=False)
    winning_price = Column(Float, nullable=False)
    winning_rate = Column(Float, nullable=False)
    successful_bid_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    announcement = relationship("BidAnnouncement", back_populates="results")


class InstitutionStat(Base):
    __tablename__ = "institution_stat"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    institution_name = Column(String(150), unique=True, nullable=False, index=True)
    category_code = Column(String(50), nullable=False)
    avg_winning_rate = Column(Float, nullable=False, default=0.925)
    total_bids = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
