import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, JSON, String, Text
from src.app.core.db import Base, PKBigInteger


class AutomationRequest(Base):
    """자동화 요청 테이블 (원래 db_table: automation_requests)"""
    __tablename__ = "automation_requests"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    intent_type = Column(String(64), default="unknown", index=True)
    requested_text = Column(Text, nullable=False, default="")
    action_key = Column(String(64), nullable=False, default="", index=True)
    pipeline_name = Column(String(100), nullable=False, default="")
    status = Column(String(20), default="queued", index=True)
    payload = Column(JSON, nullable=False, default=dict)
    requires_confirmation = Column(Boolean, default=False)
    followup_query = Column(Text, nullable=False, default="")
    harness_execution_id = Column(String(100), nullable=False, default="")
    plan_execution_id = Column(String(100), nullable=False, default="", index=True)
    execution_url = Column(Text, nullable=False, default="")
    result_summary = Column(Text, nullable=False, default="")
    result_payload = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ChatSessionState(Base):
    """채팅 세션 및 내역 테이블 (원래 db_table: chat_session_states)"""
    __tablename__ = "chat_session_states"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    session_key = Column(String(64), unique=True, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    last_query = Column(Text, nullable=False, default="")
    last_plan_json = Column(JSON, nullable=False, default=dict)
    last_filters_json = Column(JSON, nullable=False, default=dict)
    last_result_summary = Column(Text, nullable=False, default="")
    last_chart_payload = Column(JSON, nullable=False, default=dict)
    last_result_payload = Column(JSON, nullable=False, default=dict)
    last_job_id = Column(String(100), nullable=False, default="")
    last_action_key = Column(String(64), nullable=False, default="")
    last_kb_version = Column(String(100), nullable=False, default="")
    last_response_mode = Column(String(20), nullable=False, default="")
    chat_history_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class AutomationSubscription(Base):
    """자동화 구독 테이블 (원본 db_table: automation_subscriptions)"""
    __tablename__ = "automation_subscriptions"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    automation_type = Column(String(64), nullable=False, index=True, comment="자동화 종류")
    filter_json = Column(JSON, nullable=False, default=dict, comment="필터 조건")
    schedule_cron = Column(String(100), nullable=False, default="", comment="스케줄 Cron")
    is_active = Column(Boolean, default=True, index=True, comment="활성 여부")
    last_run_at = Column(DateTime, nullable=True, comment="마지막 실행 시각")
    next_run_at = Column(DateTime, nullable=True, comment="다음 실행 예정 시각")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeBaseStatus(Base):
    """지식베이스 색인 상태 테이블 (원본 db_table: knowledge_base_status)"""
    __tablename__ = "knowledge_base_status"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    kb_version = Column(String(100), unique=True, nullable=False, comment="KB 버전/이름")
    status = Column(String(20), default="unknown", comment="상태")
    source_bid_count = Column(Integer, default=0, comment="원본 공고 수")
    last_embedding_at = Column(DateTime, nullable=True, comment="마지막 임베딩 시각")
    last_pipeline_run_id = Column(String(100), nullable=False, default="", comment="마지막 파이프라인 실행 ID")
    notes = Column(Text, nullable=False, default="", comment="메모")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineExecution(Base):
    """자동화 파이프라인 실행 이력 (원본 apps/pipelines, db_table: pipeline_executions)"""
    __tablename__ = "pipeline_executions"
    __table_args__ = (
        Index("ix_pipe_exec_name_status", "pipeline_name", "status"),
        Index("ix_pipe_exec_created", "created_at"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    execution_id = Column(String(100), unique=True, nullable=False, index=True, comment="실행 ID")
    pipeline_name = Column(String(100), nullable=False, index=True, comment="파이프라인명")
    run_mode = Column(String(50), default="manual_full", comment="실행 모드")
    stage_name = Column(String(100), nullable=False, default="", comment="현재 스테이지명")
    stage_status = Column(String(50), nullable=False, default="", comment="현재 스테이지 상태")
    status = Column(String(20), default="queued", index=True, comment="상태")
    started_at = Column(DateTime, nullable=True, comment="시작 시각")
    ended_at = Column(DateTime, nullable=True, comment="종료 시각")
    metrics_json = Column(JSON, nullable=False, default=dict, comment="실행 지표")
    raw_status_payload = Column(JSON, nullable=False, default=dict, comment="원본 상태 페이로드")
    logs_summary = Column(Text, nullable=False, default="", comment="로그 요약")
    external_url = Column(Text, nullable=False, default="", comment="외부 실행 URL")
    source = Column(String(50), default="chatbot", comment="요청 소스")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
