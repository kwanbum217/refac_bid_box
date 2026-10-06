"""
src/app/models/prearng_prices.py

나라장터 개찰결과 예비가격 상세(용역) 및 발주처별 사정률 분포 ORM 모델.

G1 데이터 무손실 원칙을 준수하여 기존 테이블은 컬럼·타입·인덱스를 바꾸지 않고
신규 테이블 2개만 정의합니다. `bid_prearng_prices` 는 공고(집행)당 1행으로,
API 가 공고당 15행으로 내려주는 복수예비가격을 JSON `items` 로 집약해 저장합니다.
`institution_sajeong_rate_stats` 는 예정가격/기초금액 비율(사정률) 분포를
institution -> region(시·도) -> category 순 대체가 가능하도록 사전 집계합니다.

설계 정본: docs/analysis/prearng_price_collection_feasibility_20261006.md 7장.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow


class BidPrearngPrice(Base):
    """개찰결과 예비가격 상세(용역) 공고당 1행.

    API 는 공고당 15행(복수예비가격 후보)을 내려줍니다. 개별 후보 검색이 목적이
    아니라 표시·검증이 목적이므로 child 테이블(약 1,790만 행)을 만들지 않고
    `items` JSON 으로 압축합니다. 유니크 키는 API 복합키에 `category` 를 더해
    `INSERT IGNORE` 적재 시 멱등성을 보장합니다.
    """

    __tablename__ = "bid_prearng_prices"
    __table_args__ = (
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "bid_clsfc_no",
            "rbid_no",
            "category",
            name="uq_bid_prearng_prices",
        ),
        Index("ix_prearng_inst_dt", "dminstt_nm", "category", "rl_openg_dt"),
        Index("ix_prearng_dt_cat", "rl_openg_dt", "category"),
        Index("ix_prearng_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    bid_clsfc_no: Mapped[str] = mapped_column(
        String(20), nullable=False, default="0", comment="입찰분류번호"
    )
    rbid_no: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="재입찰번호"
    )
    category: Mapped[str] = mapped_column(
        String(10), nullable=False, default="Servc", comment="업무구분"
    )
    bid_ntce_nm: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="공고명")
    dminstt_nm: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="수요기관명(적재 시 공고에서 해석)"
    )
    bssamt: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="기초금액")
    plnprc: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="예정가격")
    sajeong_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="사정률(퍼센트) = plnprc/bssamt*100"
    )
    tot_prce_num: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="총 복수예비가격 수"
    )
    drwt_prce_num: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="추첨 예비가격 수"
    )
    bss_up_num: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="기초금액기준 상위갯수"
    )
    slctn_bss: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="낙찰자선정적용기준내용"
    )
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="예비가격 15개 [{sno,bsis_plnprc,drwt_yn,drwt_num}]"
    )
    rl_openg_dt: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="실제 개찰일시"
    )
    mkng_dt: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="복수예비가격 작성시각"
    )
    inpt_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="입력일시")
    raw_data: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="전체 원본 데이터"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="수집일시"
    )

    def __str__(self) -> str:
        return f"[{self.category}] {self.bid_ntce_no} 사정률 {self.sajeong_rate}%"


class InstitutionSajeongRateStat(Base):
    """발주처별 사정률 분포 사전 집계.

    `institution_win_rate_stats` 와 같은 패턴입니다. 최저가·최상가 조회가
    원장 스캔 없이 PK/유니크 조회로 끝나게 하며, `scope` 로 발주처 -> 시·도 ->
    업종 순 대체를 같은 테이블에서 표현합니다.
    """

    __tablename__ = "institution_sajeong_rate_stats"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "institution_name",
            "category",
            "window_days",
            name="uq_inst_sajeong",
        ),
        Index("ix_inst_sajeong_lookup", "scope", "institution_name", "category"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="institution", comment="institution|region|category"
    )
    institution_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="수요기관명 또는 지역명"
    )
    category: Mapped[str] = mapped_column(
        String(10), nullable=False, default="", comment="업무구분(전체는 빈 문자열)"
    )
    window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1095, comment="집계 창(일)"
    )
    sample_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="표본 건수"
    )
    min_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="사정률 최솟값"
    )
    max_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="사정률 최댓값"
    )
    p10_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    p50_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    p90_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    rebuilt_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        comment="집계 갱신 시각",
    )

    def __str__(self) -> str:
        return (
            f"[{self.scope}/{self.category or '전체'}] {self.institution_name or '전체'} "
            f"{self.min_rate}~{self.max_rate}% ({self.sample_count}건)"
        )
