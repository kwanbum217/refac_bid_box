"""
src/app/models/announcement_regime.py

공고별 첨부 원문 적용 기준 갈래 ORM 모델.

기존 `bid_announcements`·`bid_results` 는 컬럼·타입·인덱스를 바꾸지 않고 신규
테이블 `bid_announcement_regime` 만 추가합니다(G1). 갈래 판별 자체는
`src/app/services/band_regime_classifier.py` 가 맡고, 이 테이블은 결과만
보관합니다. 원문 파일·바이너리는 저장하지 않고 파일명·SHA-256 메타데이터만
`source_files` 에 둡니다.

설계 정본: `.orca/ref/band_2to1_attachment_classifier_design_20261106.md` 4.2절.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

REGIME_STATUS_CLASSIFIED = "CLASSIFIED"
REGIME_STATUS_FAILED = "FAILED"
REGIME_STATUS_NO_ATTACHMENT = "NO_ATTACHMENT"


class BidAnnouncementRegime(Base):
    """공고·차수·업무구분 단위의 첨부 원문 판별 결과 1건.

    같은 공고라도 업무구분이 다르면 갈래가 달라질 수 있어 `category` 를
    유니크 키에 포함합니다. 판별에 실패한 경우에도 행을 남겨 재시도 대상과
    실패 사유를 추적합니다.
    """

    __tablename__ = "bid_announcement_regime"
    __table_args__ = (
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "category",
            name="uq_bid_announcement_regime",
        ),
        Index("ix_bid_announcement_regime_regime", "regime"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_no: Mapped[str] = mapped_column(String(40), nullable=False, comment="입찰공고번호")
    bid_ntce_ord: Mapped[str] = mapped_column(
        String(10), nullable=False, default="000", comment="입찰공고차수"
    )
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="업무구분(Thng|Cnstwk|Servc)"
    )
    regime: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="적용 기준 갈래(MOIS_ACADEMIC|MOIS_OTHER|PPS|LOCAL|MOIS4|UNSPECIFIED|NO_ATTACH)",
    )
    evidence: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="근거 문장(80자 이내)"
    )
    matched_rules: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="매치 규칙 ID 쉼표 결합(R1,R12)"
    )
    source_files: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="첨부 파일명·sha256 목록"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="판별 상태(CLASSIFIED|FAILED|NO_ATTACHMENT)",
    )
    error: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="판별 실패 사유")
    classifier_version: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="판별기 버전"
    )
    classified_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="판별 시각"
    )

    def __str__(self) -> str:
        return f"[{self.category}] {self.bid_ntce_no}-{self.bid_ntce_ord} {self.regime}"
