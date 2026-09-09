"""
src/app/models/evaluations.py

일반용역 적격심사 정량평가 저장 계층 ORM 모델.
사용자 평가 프로필, 분석 스냅샷, 증빙 메타데이터 테이블을 정의합니다.
G1 데이터 무손실 원칙을 준수하여 기존 테이블 변경 없이 신규 테이블만 정의합니다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

# 외래키 제약명 상수
FK_BID_EVAL_PROFILES_USER = "fk_bid_eval_profiles_user_id"
FK_BID_EVAL_SNAPSHOTS_USER = "fk_bid_eval_snapshots_user_id"
FK_BID_EVAL_SNAPSHOTS_BID = "fk_bid_eval_snapshots_bid_id"
FK_BID_EVAL_EVIDENCE_SNAPSHOT = "fk_bid_eval_evidence_snapshot_id"


class BidEvaluationProfile(Base):
    """사용자 적격심사 정량평가 기본 프로필.

    사용자가 자주 사용하는 수행능력 점수, 경영상태 점수, 근로조건 이행계획 점수 등을
    템플릿처럼 저장하여 재사용할 수 있도록 지원합니다.
    """

    __tablename__ = "bid_evaluation_profiles"
    __table_args__ = (
        Index("ix_bid_eval_profiles_user_id", "user_id"),
        Index("ix_bid_eval_profiles_user_created", "user_id", "created_at"),
        UniqueConstraint("user_id", "name", name="uq_bid_eval_profiles_user_name"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts_customuser.id", name=FK_BID_EVAL_PROFILES_USER),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    framework: Mapped[str] = mapped_column(
        String(50), nullable=False, default="servc_qualification"
    )
    input_schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class BidEvaluationSnapshot(Base):
    """적격심사 정량평가 분석 스냅샷.

    분석 시점의 입력값(input_json)과 산출 결과(result_json), 적용된 적격심사 규칙 ID(rule_id),
    사용된 예측 모델 정보(model_id, model_version)를 불변으로 보존하여
    향후 규칙 개정이나 시스템 변경과 무관하게 과거 분석을 완전하게 재현할 수 있도록 합니다.
    """

    __tablename__ = "bid_evaluation_snapshots"
    __table_args__ = (
        Index("ix_bid_eval_snapshots_user_id", "user_id"),
        Index("ix_bid_eval_snapshots_bid_id", "bid_id"),
        Index("ix_bid_eval_snapshots_user_bid", "user_id", "bid_id"),
        Index("ix_bid_eval_snapshots_rule_id", "rule_id"),
        Index("ix_bid_eval_snapshots_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bid_announcements.id", name=FK_BID_EVAL_SNAPSHOTS_BID),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts_customuser.id", name=FK_BID_EVAL_SNAPSHOTS_USER),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    # 관계: 스냅샷에 연결된 증빙 메타데이터 목록 (캐스케이드 삭제 지원)
    evidence_items: Mapped[list[BidEvaluationEvidence]] = relationship(
        "BidEvaluationEvidence",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BidEvaluationEvidence(Base):
    """적격심사 증빙 서류 메타데이터.

    보안, 암호화, 보존기간 정책이 수립되기 전이므로 원문 파일이나 바이너리는 일절 저장하지 않으며,
    발급기관, 문서번호, 유효기간, 비고 등 메타데이터만 안전하게 관리합니다.
    """

    __tablename__ = "bid_evaluation_evidence"
    __table_args__ = (
        Index("ix_bid_eval_evidence_snapshot_id", "snapshot_id"),
        Index("ix_bid_eval_evidence_item_code", "item_code"),
        Index("ix_bid_eval_evidence_snap_item", "snapshot_id", "item_code"),
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "bid_evaluation_snapshots.id",
            ondelete="CASCADE",
            name=FK_BID_EVAL_EVIDENCE_SNAPSHOT,
        ),
        nullable=False,
    )
    item_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="평가 항목 코드 (performance/management/labor_plan/credibility)",
    )
    issuer: Mapped[str] = mapped_column(String(100), nullable=False, comment="발급기관명")
    reference_no: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="문서/증빙 일련번호"
    )
    valid_from: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=None, comment="유효기간 시작일"
    )
    valid_to: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=None, comment="유효기간 만료일"
    )
    note: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None, comment="비고 및 메모"
    )

    # 역방향 관계
    snapshot: Mapped[BidEvaluationSnapshot] = relationship(
        "BidEvaluationSnapshot",
        back_populates="evidence_items",
    )
