from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Float, JSON, String, Text
from src.app.core.db import Base


class ChatbotLog(Base):
    __tablename__ = "chatbot_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(100), nullable=True, index=True)
    query_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=False)
    retrieved_docs = Column(JSON, nullable=True)
    latency_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class KBDocument(Base):
    __tablename__ = "kb_document"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_title = Column(String(255), nullable=False)
    collection_name = Column(String(100), nullable=False, index=True)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RAGHistory(Base):
    __tablename__ = "rag_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
