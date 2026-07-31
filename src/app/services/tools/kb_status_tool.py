"""
src/app/services/tools/kb_status_tool.py

KB 상태 조회 도구 (원본 apps/chatbot/tools/kb_status_tool.py + services/kb_status.py 이식).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models.chatbot import KnowledgeBaseStatus


def get_latest_kb_status_payload(db: Session) -> dict[str, Any] | None:
    latest = db.execute(
        select(KnowledgeBaseStatus).order_by(KnowledgeBaseStatus.updated_at.desc()).limit(1)
    ).scalar_one_or_none()
    if not latest:
        return None

    return {
        "kb_version": latest.kb_version,
        "status": latest.status,
        "source_bid_count": latest.source_bid_count,
        "last_embedding_at": (
            latest.last_embedding_at.isoformat() if latest.last_embedding_at else None
        ),
        "last_pipeline_run_id": latest.last_pipeline_run_id,
        "updated_at": latest.updated_at.isoformat() if latest.updated_at else None,
        "notes": latest.notes,
    }


def build_kb_status_summary(kb_status: dict[str, Any] | None) -> str:
    if not kb_status:
        return ""

    lines = [
        "KB 색인 상태:",
        f"- 상태: `{kb_status.get('status') or 'unknown'}`",
        f"- 버전: `{kb_status.get('kb_version') or '-'}`",
        f"- 색인된 원본 문서 수: `{kb_status.get('source_bid_count', 0)}`건",
        "- 참고: 이 값은 답변에서 분석한 공고 수가 아니라 벡터 검색용 KB에 마지막으로 저장된 문서 수입니다.",
    ]

    if kb_status.get("last_embedding_at"):
        lines.append(f"- 마지막 임베딩: `{kb_status['last_embedding_at']}`")
    if kb_status.get("last_pipeline_run_id"):
        lines.append(f"- 마지막 파이프라인 실행 ID: `{kb_status['last_pipeline_run_id']}`")

    return "\n".join(lines)


def execute(*, db: Session, **_ignored: Any) -> dict[str, Any]:
    kb_status = get_latest_kb_status_payload(db)
    return {
        "kb_status": kb_status,
        "summary": build_kb_status_summary(kb_status),
    }
