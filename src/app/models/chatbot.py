import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, JSON, String, Text
from src.app.core.db import Base


class AutomationRequest(Base):
    """자동화 요청 테이블 (원래 db_table: automation_requests)"""
    __tablename__ = "automation_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    intent_type = Column(String(64), default="unknown", index=True)
    requested_text = Column(Text, nullable=True)
    action_key = Column(String(64), nullable=True, index=True)
    pipeline_name = Column(String(100), nullable=True)
    status = Column(String(20), default="queued", index=True)
    payload = Column(JSON, nullable=True)
    requires_confirmation = Column(Boolean, default=False)
    followup_query = Column(Text, nullable=True)
    harness_execution_id = Column(String(100), nullable=True)
    plan_execution_id = Column(String(100), nullable=True, index=True)
    execution_url = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    result_payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ChatSessionState(Base):
    """채팅 세션 및 내역 테이블 (원래 db_table: chat_session_states)"""
    __tablename__ = "chat_session_states"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_key = Column(String(64), unique=True, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    last_query = Column(Text, nullable=True)
    last_plan_json = Column(JSON, nullable=True)
    last_filters_json = Column(JSON, nullable=True)
    last_result_summary = Column(Text, nullable=True)
    last_chart_payload = Column(JSON, nullable=True)
    last_result_payload = Column(JSON, nullable=True)
    last_job_id = Column(String(100), nullable=True)
    last_action_key = Column(String(64), nullable=True)
    last_kb_version = Column(String(100), nullable=True)
    last_response_mode = Column(String(20), nullable=True)
    chat_history_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
