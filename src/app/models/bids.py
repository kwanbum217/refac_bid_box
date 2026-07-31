from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship
from src.app.core.db import Base



class BidResult(Base):
    """조달청 낙찰 결과 테이블 (원래 db_table: bid_results)"""
    __tablename__ = "bid_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bid_ntce_nm = Column(String(500), nullable=True, comment="입찰공고명")
    bid_ntce_no = Column(String(50), nullable=False, index=True, comment="입찰공고번호")
    bid_ntce_ord = Column(String(10), default="00", comment="입찰공고차수")
    bidwinnr_nm = Column(String(200), nullable=True, index=True, comment="낙찰업체명")
    sucsf_bid_amt = Column(BigInteger, nullable=True, comment="낙찰금액")
    sucsf_bid_rate = Column(Numeric(10, 4), nullable=True, comment="낙찰률")

    rl_openg_dt = Column(DateTime, nullable=True, index=True, comment="개찰일시")
    dminstt_nm = Column(String(200), nullable=True, index=True, comment="수요기관명")
    category = Column(String(10), default="Thng", index=True, comment="업무구분(Thng/Cnstwk/Servc/Frgcpt)")
    raw_data = Column(JSON, nullable=True, comment="전체 원본 데이터")
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True, comment="수집일시")


class BidAnnouncement(Base):
    """조달청 입찰공고 테이블 (원래 db_table: bid_announcements)"""
    __tablename__ = "bid_announcements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bid_ntce_nm = Column(String(500), nullable=True, comment="입찰공고명")
    bid_ntce_no = Column(String(50), nullable=False, index=True, comment="입찰공고번호")
    bid_ntce_ord = Column(String(10), default="000", comment="입찰공고차수")
    ntce_instt_nm = Column(String(200), nullable=True, comment="공고기관명")
    dminstt_nm = Column(String(200), nullable=True, index=True, comment="수요기관명")
    base_amount = Column(BigInteger, nullable=True, comment="기초금액(사업예산)")
    presmpt_prce = Column(BigInteger, nullable=True, comment="원본 참고금액")
    bid_ntce_dt = Column(DateTime, nullable=True, index=True, comment="입찰공고일시")
    bid_clse_dt = Column(DateTime, nullable=True, comment="입찰마감일시")
    openg_dt = Column(DateTime, nullable=True, comment="개찰일시")
    ntce_kind_nm = Column(String(100), nullable=True, comment="공고종류명")
    bid_methd_nm = Column(String(100), nullable=True, comment="입찰방식명")
    cntrct_mthd_nm = Column(String(100), nullable=True, comment="계약방법명")
    category = Column(String(10), default="Thng", index=True, comment="업무구분(Thng/Cnstwk/Servc/Frgcpt)")
    raw_data = Column(JSON, nullable=True, comment="전체 원본 데이터")
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="수집일시")


class BidDatasetSummary(Base):
    """대시보드용 전용 집계 요약 (원래 db_table: bid_dataset_summaries)"""
    __tablename__ = "bid_dataset_summaries"

    dataset = Column(String(20), primary_key=True, comment="집계 대상 (announcement/result)")
    total_count = Column(BigInteger, default=0, comment="전체 건수")
    total_amount = Column(Numeric(30, 0), default=0, comment="전체 금액 합계")
    avg_rate = Column(Numeric(10, 4), nullable=True, comment="평균 낙찰률")
    source_latest_collected_at = Column(DateTime, nullable=True, comment="원본 최신 수집 시각")
    rebuilt_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True, comment="집계 갱신 시각")

