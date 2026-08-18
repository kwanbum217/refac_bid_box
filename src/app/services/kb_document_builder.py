"""
src/app/services/kb_document_builder.py

지식베이스 문서 생성 및 공고/낙찰 해석 모듈.
"""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models.bids import (
    CATEGORY_LABELS,
    BidAnnouncement,
    BidResult,
    extract_business_budget,
    normalize_bid_ntce_ord,
)

DEFAULT_MAX_DOCUMENTS = 500_000


def _max_documents() -> int:
    raw = os.getenv("KB_MAX_DOCUMENTS", "").strip()
    if not raw:
        return DEFAULT_MAX_DOCUMENTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DOCUMENTS
    return value if value > 0 else DEFAULT_MAX_DOCUMENTS


def _resolve_announcements(
    db: Session, one_year_ago: datetime
) -> tuple[list[BidAnnouncement], str]:
    """공고일 기준 → 수집일 기준 순으로 폴백합니다 (원본 _resolve_announcement_queryset)."""
    limit = _max_documents()

    by_notice = (
        db.execute(
            select(BidAnnouncement)
            .where(BidAnnouncement.bid_ntce_dt >= one_year_ago)
            .order_by(BidAnnouncement.bid_ntce_dt.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if by_notice:
        return list(by_notice), "announcements_by_notice_date"

    by_collected = (
        db.execute(
            select(BidAnnouncement)
            .where(BidAnnouncement.collected_at >= one_year_ago)
            .order_by(BidAnnouncement.collected_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if by_collected:
        return list(by_collected), "announcements_by_collected_at"

    return [], "announcements_unavailable"


def _resolve_delta_announcements(
    db: Session, collected_since: datetime
) -> tuple[list[BidAnnouncement], str]:
    """이번 수집분과 새 낙찰 결과가 참조하는 공고만 KB에 반영합니다."""
    announcements = list(
        db.execute(
            select(BidAnnouncement)
            .where(BidAnnouncement.collected_at >= collected_since)
            .order_by(BidAnnouncement.collected_at.desc())
        )
        .scalars()
        .all()
    )
    result_notice_numbers = list(
        db.scalars(
            select(BidResult.bid_ntce_no)
            .where(BidResult.collected_at >= collected_since)
            .distinct()
        ).all()
    )
    if result_notice_numbers:
        related_announcements = db.execute(
            select(BidAnnouncement).where(BidAnnouncement.bid_ntce_no.in_(result_notice_numbers))
        ).scalars()
        known_ids = {announcement.id for announcement in announcements}
        announcements.extend(
            announcement
            for announcement in related_announcements
            if announcement.id not in known_ids
        )
    return announcements, "announcements_by_collected_delta"


def _join_key(row: BidAnnouncement | BidResult) -> str:
    """공고와 낙찰을 잇는 키. 차수 자리수를 맞추지 않으면 거의 이어지지 않습니다."""
    return f"{row.bid_ntce_no}-{normalize_bid_ntce_ord(row.bid_ntce_ord)}-{row.category}"


def _build_announcement_document(ann: BidAnnouncement, result: BidResult | None) -> str:
    resolved_base_amount = extract_business_budget(ann.raw_data)
    if resolved_base_amount is None and ann.raw_data is None:
        resolved_base_amount = ann.base_amount

    content = f"[공고명] {ann.bid_ntce_nm}\n"
    content += f"[공고번호] {ann.bid_ntce_no}-{ann.bid_ntce_ord}\n"
    content += f"[수요기관] {ann.dminstt_nm}\n"
    if resolved_base_amount is not None:
        content += f"[기초금액] {resolved_base_amount}원\n"
    if ann.presmpt_prce is not None:
        content += f"[추정가격] {ann.presmpt_prce}원\n"
    content += f"[분류] {CATEGORY_LABELS.get(ann.category, ann.category)}\n"
    content += f"[공고일시] {ann.bid_ntce_dt}\n"

    if result is not None:
        content += f"[낙찰업체] {result.bidwinnr_nm}\n"
        content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
        content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
        content += f"[개찰일시] {result.rl_openg_dt}\n"
    else:
        content += "[낙찰상태] 진행 중 또는 결과 미수집\n"
    return content


def _build_result_document(result: BidResult) -> str:
    content = f"[낙찰공고번호] {result.bid_ntce_no}-{result.bid_ntce_ord}\n"
    content += f"[수요기관] {result.dminstt_nm}\n"
    content += f"[분류] {CATEGORY_LABELS.get(result.category, result.category)}\n"
    content += f"[낙찰업체] {result.bidwinnr_nm}\n"
    content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
    content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
    content += f"[개찰일시] {result.rl_openg_dt}\n"
    return content
