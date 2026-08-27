from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    SECRET_KEY: str
    # 고비용 자동화는 최근 성공 이력이 있으면 재실행하지 않습니다 (원본 동일 기본값 on).
    AUTOMATION_REUSE_RECENT: bool = True
    # 워커가 앱과 같은 DB 를 보는지 여부. 기본 docker-compose 구성은 공유합니다.
    AUTOMATION_WORKER_SHARES_DB: bool = True
    # 워커를 별도 배포해 DB 를 공유하지 않을 때 결과를 되돌려 보낼 API 주소입니다.
    # 워커가 도달할 수 있는 주소여야 하며, 컨테이너 분리 시 서비스명(http://app:8000)을 씁니다.
    AUTOMATION_CALLBACK_BASE_URL: str = ""
    # 원본 Harness 야간 트리거(매일 02:00) 대체. 개발 장비에서는 꺼둘 수 있습니다.
    AUTOMATION_NIGHTLY_SCHEDULE_ENABLED: bool = True
    # 개발 DB 최신화 전용 크론. 수집·KB·집계만 수행하며 예측 검증과 재학습은 포함하지 않습니다.
    AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED: bool = False
    # 원본 Airflow narabid_weekly_retrain(매주 월요일 03:00) 대체.
    ML_WEEKLY_RETRAIN_ENABLED: bool = True
    # 구간별 지연 구조화 로그는 진단 전용입니다. 정식 레이턴시 게이트에서는
    # 로그 포매팅·출력 오버헤드를 배제하기 위해 기본적으로 끕니다.
    LATENCY_SEGMENT_LOGGING: bool = False
    # RAG 답변에서 검색 컨텍스트의 낙찰금액·낙찰률 누락 여부를 결정론적으로 검출해 로깅합니다.
    NUMERIC_OMISSION_DETECTION: bool = False
    # MLOps 알림 웹훅(Slack/Discord). 비면 알림을 보내지 않습니다.
    # 실제 URL 은 .env 에만 둡니다.
    MLOPS_WEBHOOK_URL: str = ""

    # CORS 허용 오리진. 콤마로 구분한 문자열입니다.
    # list[str] 필드로 두면 pydantic-settings 가 환경변수를 JSON 으로만 해석해
    # .env 에 ["https://a","https://b"] 를 요구합니다. 운영자가 손으로 쓰는 값이라
    # 콤마 구분을 받고 cors_allowed_origins 프로퍼티에서 나눕니다.
    # 개발·스테이징 기본값은 비어 있어도 되며, 그 경우 아래 CORS_DEV_ALLOW_ALL
    # 정책이 적용됩니다. production 에서 비면 validator 가 기동을 거부합니다.
    CORS_ALLOWED_ORIGINS: str = ""
    # 개발·스테이징에서 임의 오리진을 허용할지 여부입니다. 로컬 개발 편의를 위해
    # 기본 활성이며, production 에서는 이 값과 무관하게 항상 목록만 허용합니다.
    CORS_DEV_ALLOW_ALL: bool = True

    # DB 설정
    DATABASE_URL: str = "mysql+pymysql://root:rootpassword@localhost:3306/procurement"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "rootpassword"
    DB_NAME: str = "procurement"

    # Redis 설정
    REDIS_URL: str = "redis://localhost:6379/0"

    # 검색 전용 Meilisearch 인덱스입니다. 원본 MySQL 테이블에는 검색용 DDL을 추가하지
    # 않고 별도 읽기 모델로 복제합니다. 기본값은 기존 개발 환경 호환을 위해 비활성입니다.
    MEILI_ENABLED: bool = False
    MEILI_URL: str = "http://localhost:7700"
    MEILI_MASTER_KEY: str = ""
    MEILI_TIMEOUT_SECONDS: float = 5.0

    # LLM & RAG
    # 생성 LLM 백엔드: "ollama"(기본, 로컬 gemma4:e2b) 또는 "gemini"(원본 경로)
    LLM_PROVIDER: str = "ollama"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_TEMPERATURE: float = 0.2
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma4:e2b"
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
    # 임베딩 제공자. "ollama" 가 기본이며 "default" 는 ChromaDB 내장
    # all-MiniLM-L6-v2 로 되돌립니다. 그 모델은 영어 전용이라 한국어 검색
    # 적중률이 top-5 에서 4% 에 그칩니다 (2026-08-06 실측, bge-m3 는 100%).
    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "bge-m3"
    # 가중치 저장 위치의 정본입니다. src/ml/model_registry.py 와
    # src/ml/promotion.py 가 이 값을 읽습니다. 외부 볼륨이나 다른 디스크로
    # 옮길 때는 이 환경변수만 바꾸면 되며, 코드 수정은 필요하지 않습니다.
    MODEL_FILES_DIR: str = str(PROJECT_ROOT / "data" / "model_files")
    # 승격 시 직전 서빙본을 옮겨 두는 곳입니다. verify_migration.py 가 원본
    # 기준선을 여기서 대조하므로(G1) 서빙 경로와 함께 옮겨야 합니다.
    MODEL_BACKUPS_DIR: str = str(PROJECT_ROOT / "data" / "model_backups")
    # 서빙 모델 실측 지표 사이드카. 승격 게이트가 champion 지표를 여기서
    # 읽으므로 가중치와 한 묶음으로 배포해야 합니다.
    MODEL_METRICS_DIR: str = str(PROJECT_ROOT / "data" / "model_metrics")

    # ML MLOps Directory
    MODEL_REGISTRY_DIR: str = "ml_registry"
    FEATURE_STORE_DIR: str = "data/feature_store"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_allowed_origins(self) -> list[str]:
        """CORS_ALLOWED_ORIGINS 를 오리진 목록으로 변환합니다."""
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def docs_enabled(self) -> bool:
        """OpenAPI 스키마와 문서 UI 노출 여부입니다.

        production 에서는 전체 API 표면이 공개되지 않도록 닫습니다.
        """
        return self.ENVIRONMENT != "production"

    @model_validator(mode="after")
    def validate_security_settings(self):
        secret_key = self.SECRET_KEY.strip()
        if len(secret_key) < 32:
            raise ValueError("SECRET_KEY는 32자 이상의 무작위 값이어야 합니다.")

        if self.ENVIRONMENT != "production":
            return self

        if self.DEBUG:
            raise ValueError("운영 환경에서는 DEBUG를 활성화할 수 없습니다.")

        insecure_secret_keys = {
            "change-this-in-production-to-a-secure-random-key",
            "default-insecure-secret-key-change-me",
        }
        if secret_key in insecure_secret_keys:
            raise ValueError("운영 환경에서는 예제 SECRET_KEY를 사용할 수 없습니다.")

        if self.DB_PASSWORD == "rootpassword" or "rootpassword" in self.DATABASE_URL:  # nosec B105 - 기본 비밀번호 사용을 거부하는 검사 문자열입니다
            raise ValueError("운영 환경에서는 기본 데이터베이스 비밀번호를 사용할 수 없습니다.")

        origins = self.cors_allowed_origins
        if not origins:
            raise ValueError(
                "운영 환경에서는 CORS_ALLOWED_ORIGINS 에 허용 오리진을 명시해야 합니다."
            )
        if "*" in origins:
            raise ValueError(
                "운영 환경에서는 CORS_ALLOWED_ORIGINS 에 와일드카드를 사용할 수 없습니다."
            )

        return self


settings = Settings()
