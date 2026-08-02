import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects import mysql

from src.app.core.db import Base, LongText, PKBigInteger

# 원본 Django PositiveIntegerField 는 MySQL/MariaDB 에서 int unsigned 로 생성됩니다.
PositiveInteger = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql", "mariadb")

# 원본 FK 제약명입니다. Django 가 자동 생성한 이름을 그대로 써야 autogenerate 가
# 제약을 지우고 다시 만드는 DDL 을 제안하지 않습니다. Django 의 on_delete=CASCADE 는
# 파이썬 레벨 동작이라 DB 에는 ON DELETE 절 없이(RESTRICT) 생성되어 있습니다.
FK_AUTOMATION_REQUEST_USER = "automation_requests_user_id_09027998_fk_accounts_customuser_id"
FK_AUTOMATION_SUBSCRIPTION_USER = "automation_subscript_user_id_65841fc4_fk_accounts_"
FK_CHAT_SESSION_USER = "chat_session_states_user_id_47adeb98_fk_accounts_customuser_id"

# 원본 Django UUIDField 를 MySQL 8 에서도 사용할 수 있도록 문자열 기반 UUID 로 매핑합니다.
# as_uuid=False 처럼 애플리케이션은 문자열로 다룹니다.
RequestUuid = String(36)


class AutomationRequest(Base):
    """자동화 요청 테이블 (원래 db_table: automation_requests)"""
    __tablename__ = "automation_requests"
    # 인덱스명은 원본 Django 가 만든 실제 이름입니다. 해시가 붙은 것은 Django 자동 생성,
    # ix_ 로 시작하는 셋은 원본 Meta.indexes 가 직접 이름 붙인 복합 인덱스입니다.
    __table_args__ = (
        Index("automation_requests_intent_type_72f08cf2", "intent_type"),
        Index("automation_requests_action_key_72546a52", "action_key"),
        Index("automation_requests_status_b21ae7da", "status"),
        Index("automation_requests_plan_execution_id_4f401e5d", "plan_execution_id"),
        Index("automation_requests_created_at_1c714821", "created_at"),
        Index("ix_auto_req_user_status", "user_id", "status"),
        Index("ix_auto_req_intent_created", "intent_type", "created_at"),
        Index("ix_auto_req_action_created", "action_key", "created_at"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    request_id = Column(
        RequestUuid, nullable=False, default=lambda: str(uuid.uuid4()), unique=True
    )
    user_id = Column(
        BigInteger,
        ForeignKey("accounts_customuser.id", name=FK_AUTOMATION_REQUEST_USER),
        nullable=False,
    )
    intent_type = Column(String(64), nullable=False, default="unknown")
    requested_text = Column(LongText, nullable=False, default="")
    action_key = Column(String(64), nullable=False, default="")
    pipeline_name = Column(String(100), nullable=False, default="")
    status = Column(String(20), nullable=False, default="queued")
    payload = Column(JSON, nullable=False, default=dict)
    requires_confirmation = Column(Boolean, nullable=False, default=False)
    followup_query = Column(LongText, nullable=False, default="")
    harness_execution_id = Column(String(100), nullable=False, default="")
    plan_execution_id = Column(String(100), nullable=False, default="")
    execution_url = Column(LongText, nullable=False, default="")
    result_summary = Column(LongText, nullable=False, default="")
    result_payload = Column(JSON, nullable=False, default=dict)
    error_message = Column(LongText, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ChatSessionState(Base):
    """채팅 세션 및 내역 테이블 (원래 db_table: chat_session_states)"""
    __tablename__ = "chat_session_states"
    __table_args__ = (
        Index("chat_session_states_updated_at_44284963", "updated_at"),
        Index("ix_chat_state_user_updated", "user_id", "updated_at"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    session_key = Column(String(64), nullable=False, unique=True)
    user_id = Column(
        BigInteger,
        ForeignKey("accounts_customuser.id", name=FK_CHAT_SESSION_USER),
        nullable=True,
    )
    last_query = Column(LongText, nullable=False, default="")
    last_plan_json = Column(JSON, nullable=False, default=dict)
    last_filters_json = Column(JSON, nullable=False, default=dict)
    last_result_summary = Column(LongText, nullable=False, default="")
    last_chart_payload = Column(JSON, nullable=False, default=dict)
    last_result_payload = Column(JSON, nullable=False, default=dict)
    last_job_id = Column(String(100), nullable=False, default="")
    last_action_key = Column(String(64), nullable=False, default="")
    last_kb_version = Column(String(100), nullable=False, default="")
    last_response_mode = Column(String(20), nullable=False, default="")
    chat_history_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AutomationSubscription(Base):
    """자동화 구독 테이블 (원본 db_table: automation_subscriptions)"""
    __tablename__ = "automation_subscriptions"
    __table_args__ = (
        Index("automation_subscriptions_automation_type_64b4d3d1", "automation_type"),
        Index("automation_subscriptions_is_active_1dd49756", "is_active"),
        Index("ix_auto_sub_type", "automation_type"),
        Index("ix_auto_sub_user_active", "user_id", "is_active"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("accounts_customuser.id", name=FK_AUTOMATION_SUBSCRIPTION_USER),
        nullable=False,
    )
    automation_type = Column(String(64), nullable=False, comment="자동화 종류")
    filter_json = Column(JSON, nullable=False, default=dict, comment="필터 조건")
    schedule_cron = Column(String(100), nullable=False, default="", comment="스케줄 Cron")
    is_active = Column(Boolean, nullable=False, default=True, comment="활성 여부")
    last_run_at = Column(DateTime, nullable=True, comment="마지막 실행 시각")
    next_run_at = Column(DateTime, nullable=True, comment="다음 실행 예정 시각")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeBaseStatus(Base):
    """지식베이스 색인 상태 테이블 (원본 db_table: knowledge_base_status)"""
    __tablename__ = "knowledge_base_status"

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    kb_version = Column(String(100), unique=True, nullable=False, comment="KB 버전/이름")
    status = Column(String(20), nullable=False, default="unknown", comment="상태")
    source_bid_count = Column(PositiveInteger, nullable=False, default=0, comment="원본 공고 수")
    last_embedding_at = Column(DateTime, nullable=True, comment="마지막 임베딩 시각")
    last_pipeline_run_id = Column(String(100), nullable=False, default="", comment="마지막 파이프라인 실행 ID")
    notes = Column(LongText, nullable=False, default="", comment="메모")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineExecution(Base):
    """자동화 파이프라인 실행 이력 (원본 apps/pipelines, db_table: pipeline_executions)"""
    __tablename__ = "pipeline_executions"
    __table_args__ = (
        Index("ix_pipe_exec_name_status", "pipeline_name", "status"),
        Index("ix_pipe_exec_created", "created_at"),
        Index("pipeline_executions_pipeline_name_010b1479", "pipeline_name"),
        Index("pipeline_executions_status_e7ec4919", "status"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    execution_id = Column(String(100), unique=True, nullable=False, comment="실행 ID")
    pipeline_name = Column(String(100), nullable=False, comment="파이프라인명")
    run_mode = Column(String(50), nullable=False, default="manual_full", comment="실행 모드")
    stage_name = Column(String(100), nullable=False, default="", comment="현재 스테이지명")
    stage_status = Column(String(50), nullable=False, default="", comment="현재 스테이지 상태")
    status = Column(String(20), nullable=False, default="queued", comment="상태")
    started_at = Column(DateTime, nullable=True, comment="시작 시각")
    ended_at = Column(DateTime, nullable=True, comment="종료 시각")
    metrics_json = Column(JSON, nullable=False, default=dict, comment="실행 지표")
    raw_status_payload = Column(JSON, nullable=False, default=dict, comment="원본 상태 페이로드")
    logs_summary = Column(LongText, nullable=False, default="", comment="로그 요약")
    external_url = Column(LongText, nullable=False, default="", comment="외부 실행 URL")
    source = Column(String(50), nullable=False, default="chatbot", comment="요청 소스")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
