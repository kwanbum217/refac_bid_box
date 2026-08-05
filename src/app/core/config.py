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
    # 워커가 앱과 같은 DB 를 보는지 여부. 기본 docker-compose 구성은 공유합니다.
    AUTOMATION_WORKER_SHARES_DB: bool = True
    # 워커를 별도 배포해 DB 를 공유하지 않을 때 결과를 되돌려 보낼 API 주소입니다.
    # 워커가 도달할 수 있는 주소여야 하며, 컨테이너 분리 시 서비스명(http://app:8000)을 씁니다.
    AUTOMATION_CALLBACK_BASE_URL: str = ""
    # 원본 Harness 야간 트리거(매일 02:00) 대체. 개발 장비에서는 꺼둘 수 있습니다.
    AUTOMATION_NIGHTLY_SCHEDULE_ENABLED: bool = True
    # 원본 Airflow narabid_weekly_retrain(매주 월요일 03:00) 대체.
    ML_WEEKLY_RETRAIN_ENABLED: bool = True
    # MLOps 알림 웹훅(Slack/Discord). 비면 알림을 보내지 않습니다.
    # 실제 URL 은 .env 에만 둡니다.
    MLOPS_WEBHOOK_URL: str = ""

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
    # 모델을 메모리에 붙잡아 두는 시간. 내려가면 다음 질의가 로드 비용을 전부
    # 냅니다(실측 11.78초). "-1" 은 무기한, "30m" 은 30분입니다.
    OLLAMA_KEEP_ALIVE: str = "-1"
    # 기동 시 모델을 미리 올려 첫 질의가 로드 비용을 내지 않게 합니다.
    LLM_WARMUP_ON_STARTUP: bool = True
    # 사고(thinking) 단계 사용 여부. gemma4 는 사고를 끝낸 뒤에야 답변 본문을
    # 내보내므로, 켜 두면 첫 토큰이 9.73초, 끄면 0.41초입니다 (2026-08-05 실측).
    LLM_THINKING: bool = False
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
