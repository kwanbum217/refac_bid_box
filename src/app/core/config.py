import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-insecure-secret-key-change-me")
    # 고비용 자동화는 최근 성공 이력이 있으면 재실행하지 않습니다 (원본 동일 기본값 on).
    AUTOMATION_REUSE_RECENT: bool = True

    # DB 설정
    DATABASE_URL: str = "mysql+pymysql://root:rootpassword@localhost:3306/procurement"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "rootpassword"
    DB_NAME: str = "procurement"

    # Redis 설정
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM & RAG
    # 생성 LLM 백엔드: "ollama"(기본, 로컬 gemma4:e4b) 또는 "gemini"(원본 경로)
    LLM_PROVIDER: str = "ollama"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_TEMPERATURE: float = 0.2
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma4:e4b"
    GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
    GEMINI_API_KEY: str = ""
    CHROMA_DB_PATH: str = str(PROJECT_ROOT / "chroma_db")
    MODEL_FILES_DIR: str = str(PROJECT_ROOT / "data" / "model_files")

    # ML MLOps Directory
    MODEL_REGISTRY_DIR: str = "ml_registry"
    FEATURE_STORE_DIR: str = "data/feature_store"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
