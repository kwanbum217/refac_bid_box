"""
src/app/models/openg_results.py

나라장터 개찰결과(유찰 상태 포함) ORM 모델.

기존 `bid_announcements`·`bid_results` 는 컬럼·타입·인덱스를 바꾸지 않고 신규
테이블 `bid_openg_results` 만 추가합니다(G1). 유찰 판정 원천은
`progrs_div_cd_nm`(개찰결과구분명)이며, 낙찰 성공 정보를 담는 `bid_results` 와
의미가 다르므로 분리합니다.

설계 정본: docs/analysis/fail_bid_collection_design_20261031.md 3장.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

OPENG_STATUS_FAILED = "유찰"
OPENG_STATUS_CLOSED = "개찰완료"
OPENG_STATUS_OTHER = "기타"


def classify_openg_status(value: str | None) -> str:
    """개찰결과구분명을 유찰·개찰완료·기타 3종으로 분류합니다.

    유찰 판정은 `progrs_div_cd_nm == "유찰"` 하나로 합니다. 참가업체 수
    (`prtcpt_cnum`)가 0 이어도 유찰이 아닌 행이 실측되었으므로 보조 지표로만
    씁니다. 재입찰은 유찰의 결과일 뿐 상태 라벨이 아니므로 기타로 둡니다.
    """
    text = (value or "").strip()
    if text == OPENG_STATUS_FAILED:
        return OPENG_STATUS_FAILED
    if text.startswith(OPENG_STATUS_CLOSED):
        return OPENG_STATUS_CLOSED
    return OPENG_STATUS_OTHER


class BidOpengResult(Base):
    """나라장터 개찰결과 1건.

    응답 1건을 `(공고번호, 차수, 재입찰번호, 분류)` 로 유일하다고 보고 멱등
    적재 기준으로 삼습니다. 다만 같은 공고·차수에서 `rbid_no` 가 중복되는
    사례는 아직 실측하지 않았으므로 유니크 키는 확정 전 가정입니다. 적재는
    첫 관측값을 고정하지 않고 upsert 로 상태를 갱신하며, 첫 관측 시각만
    `first_seen_at` 에 남깁니다.

    `opengCorpInfo`(개찰 업체 정보)에는 대표자명 등 개인정보가 포함되므로
    컬럼으로 만들지 않고 `raw_data` 에서도 제외합니다.
    """

    __tablename__ = "bid_openg_results"
    __table_args__ = (
        # 실측 확정 전 가정입니다. rbid_no 중복 사례가 확인되면 키를 조정해야 합니다.
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "rbid_no",
            "category",
            name="uq_bid_openg_results",
        ),
        Index("ix_openg_cat_dt", "category", "openg_dt"),
        Index("ix_openg_status_dt", "progrs_div_cd_nm", "openg_dt"),
        Index("ix_openg_inst_cat_dt", "dminstt_nm", "category", "openg_dt"),
        Index("ix_openg_notice", "bid_ntce_no", "category"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    rbid_no: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="재입찰번호"
    )
    bid_clsfc_no: Mapped[str] = mapped_column(
        String(20), nullable=False, default="0", comment="입찰분류번호"
    )
    category: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="업무구분(Thng|Cnstwk|Servc)"
    )
    progrs_div_cd_nm: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="개찰결과구분명(유찰 판정 원천)"
    )
    prtcpt_cnum: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="참가업체 수(보조 지표)"
    )
    bid_ntce_nm: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="공고명")
    dminstt_nm: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="수요기관명")
    openg_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="개찰일시")
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="응답 원문(opengCorpInfo 제외)"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="처음 관측 시각"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        comment="마지막 관측 시각",
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="적재 시각"
    )

    def __str__(self) -> str:
        return f"[{self.category}] {self.bid_ntce_no}-{self.bid_ntce_ord} {self.progrs_div_cd_nm}"
