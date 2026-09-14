"""
src/app/models/bid_restrictions.py

조달청 입찰공고 면허제한정보 및 참가가능지역 ORM 모델.
G1 데이터 무손실 원칙을 준수하여 기존 테이블 변경 없이 신규 테이블만 정의합니다.
외래 키 제약 없이 독립적으로 적재됩니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow


class BidAnnouncementLicenseLimit(Base):
    """입찰공고 면허제한정보 테이블"""

    __tablename__ = "bid_announcement_license_limits"
    __table_args__ = (
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "lmt_grp_no",
            "lmt_sno",
            name="uq_bid_ann_lic_limits_ntce_grp_sno",
        ),
        Index("ix_bid_ann_lic_limits_ntce", "bid_ntce_no", "bid_ntce_ord"),
        Index("ix_bid_ann_lic_limits_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    lmt_grp_no: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1", comment="제한그룹번호"
    )
    lmt_sno: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1", comment="제한순번"
    )
    lcns_lmt_nm: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="면허제한명"
    )
    permsn_indstryty_list: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="허가업종목록"
    )
    indstryty_mfrc_fld_list: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="업종제조분야목록"
    )
    rgst_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="등록일시")
    bsns_div_nm: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="업무구분명")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="수집일시"
    )


class BidAnnouncementParticipationRegion(Base):
    """입찰공고 참가가능지역 테이블"""

    __tablename__ = "bid_announcement_participation_regions"
    __table_args__ = (
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "lmt_sno",
            name="uq_bid_ann_prtcpt_rgn_ntce_sno",
        ),
        Index("ix_bid_ann_prtcpt_rgn_ntce", "bid_ntce_no", "bid_ntce_ord"),
        Index("ix_bid_ann_prtcpt_rgn_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    lmt_sno: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1", comment="제한순번"
    )
    prtcpt_psbl_rgn_nm: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="참가가능지역명"
    )
    rgst_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="등록일시")
    bsns_div_nm: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="업무구분명")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="수집일시"
    )
