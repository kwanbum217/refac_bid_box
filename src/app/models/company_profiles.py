"""
src/app/models/company_profiles.py

회원가입 시 받는 회사·담당자 정보와 정량평가 원자료 저장 계층 ORM 모델.

기존 계정 테이블(accounts_customuser)은 건드리지 않고 신규 테이블 3개만 추가합니다.

| 테이블 | 카디널리티 | 내용 |
| --- | --- | --- |
| `account_company_profiles` | 사용자당 1행 | 회사명·대표자·주소·전화·팩스·회사 이메일, 담당자 성명·직책·부서·전화·이메일 |
| `account_qualification_facts` | 사용자당 1행 | 신용평가등급·평가일, 신인도 해당 항목 목록, 비가격 정량점수 기본값, 스키마 버전 |
| `account_consent_events` | 가입 시 2행 | 약관 동의 구분·약관 버전·동의 시각 |

정량평가 점수는 가입 때 계산하지 않습니다. 원자료만 저장하고, 공고 조회 시
정량평가 엔진이 환산합니다(D-W4).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

# 외래키 제약명 상수. MySQL 은 제약명을 요구하므로 명시합니다.
FK_ACCOUNT_COMPANY_PROFILE_USER = "fk_account_company_profiles_user_id"
FK_ACCOUNT_QUALIFICATION_FACTS_USER = "fk_account_qualification_facts_user_id"
FK_ACCOUNT_CONSENT_EVENTS_USER = "fk_account_consent_events_user_id"

# 동의 구분과 약관 버전. 가입 화면의 필수 동의 2종에 대응합니다.
CONSENT_KIND_TERMS = "terms"
CONSENT_KIND_PRIVACY = "privacy"
CONSENT_TERMS_VERSION = "1.0"
CONSENT_PRIVACY_VERSION = "1.0"

# 정량 원자료 스키마 버전. 입력 항목 구성이 바뀌면 올립니다.
QUALIFICATION_FACTS_VERSION = "1.0"


class AccountCompanyProfile(Base):
    """회원 회사·담당자 정보 (사용자당 1행)."""

    __tablename__ = "account_company_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_account_company_profiles_user_id"),)

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PKBigInteger,
        ForeignKey(
            "accounts_customuser.id",
            name=FK_ACCOUNT_COMPANY_PROFILE_USER,
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="회사명")
    representative_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="대표자 성명"
    )
    address: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="회사 주소")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="회사 전화")
    fax: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="회사 팩스")
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, comment="회사 이메일")
    contact_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="담당자 성명"
    )
    contact_position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="담당자 직책"
    )
    contact_department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="담당자 부서"
    )
    contact_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="담당자 전화"
    )
    contact_email: Mapped[str | None] = mapped_column(
        String(254), nullable=True, comment="담당자 이메일"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AccountQualificationFact(Base):
    """회원 정량평가 원자료 (사용자당 1행).

    가입 때 점수를 계산하지 않고 원자료만 저장합니다. 값이 비어 있어도 가입은
    성립하며(선택 항목), 공고 조회 시 정량평가 엔진이 환산합니다.
    """

    __tablename__ = "account_qualification_facts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_account_qualification_facts_user_id"),)

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PKBigInteger,
        ForeignKey(
            "accounts_customuser.id",
            name=FK_ACCOUNT_QUALIFICATION_FACTS_USER,
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    credit_grade: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="경영상태 신용평가등급 표기"
    )
    credit_evaluated_on: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="신용평가등급 평가일"
    )
    reputation_items: Mapped[dict[str, float] | list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="신인도 항목 코드 목록(list) 또는 항목별 선택 평점(dict). 구형 list 도 그대로 읽습니다",
    )
    non_price_quant_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="기관 원문 미반영 공고용 비가격 정량점수 기본값"
    )
    version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=QUALIFICATION_FACTS_VERSION,
        comment="원자료 스키마 버전",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AccountConsentEvent(Base):
    """약관 동의 이력 (가입 시 동의 구분별 1행)."""

    __tablename__ = "account_consent_events"
    __table_args__ = (Index("ix_account_consent_events_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PKBigInteger,
        ForeignKey(
            "accounts_customuser.id",
            name=FK_ACCOUNT_CONSENT_EVENTS_USER,
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    consent_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="동의 구분 (terms/privacy)"
    )
    terms_version: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="동의한 약관 버전"
    )
    consented_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, comment="동의 시각"
    )
