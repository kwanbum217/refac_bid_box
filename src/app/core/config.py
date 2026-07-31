import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-insecure-secret-key-change-me")

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
    GEMINI_API_KEY: str = ""

    # ML MLOps Directory
    MODEL_REGISTRY_DIR: str = "ml_registry"
    FEATURE_STORE_DIR: str = "data/feature_store"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
