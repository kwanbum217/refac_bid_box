"""
src/app/models/schedule_run_log.py

스케줄 태스크 실행 이력 ORM 모델.

Redis 의 `bidbox:worker:schedules` 는 최근 상태만 7일 TTL 로 보관하므로, 실행
이력이 사라져 실패 원인을 사후에 확정할 수 없었습니다. 이 테이블은 스케줄
태스크가 끝날 때마다 한 행을 영구 보관합니다. 기존 테이블은 바꾸지 않고 신규
테이블 `schedule_run_log` 만 추가합니다(G1).

시각 컬럼은 앱 공통 규약대로 UTC naive 입니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base, PKBigInteger


class ScheduleRunLog(Base):
    """스케줄 태스크 실행 1건의 영구 기록."""

    __tablename__ = "schedule_run_log"
    __table_args__ = (
        Index("ix_schedule_run_log_name_started", "schedule_name", "started_at"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    schedule_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="스케줄 이름(_record_schedule 인자)"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="시작 시각(UTC naive)"
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="종료 시각(UTC naive)"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="실행 시간(밀리초)"
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="성공 여부")
    status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="태스크가 반환한 status"
    )
    error_type: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="예외 타입 이름"
    )
    error_message: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="예외 메시지(1000자에서 자름)"
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="기록한 워커 식별자"
    )

    def __str__(self) -> str:
        return f"[{self.schedule_name}] {self.started_at} success={self.success}"
