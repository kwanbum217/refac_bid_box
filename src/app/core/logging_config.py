"""src/app/core/logging_config.py

애플리케이션 및 워커 통합 루트 로깅 구성 모듈입니다.
logging.basicConfig 대신 logging.config.dictConfig 를 사용하여 Uvicorn 및 Arq
환경에서도 루트 로거 및 하위 모듈 로거의 레벨과 포매터가 일관되게 적용되도록 보장합니다.
"""

from __future__ import annotations

import logging
import logging.config
import re
from typing import Any

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ServiceKeyRedactionFilter(logging.Filter):
    """로그 메시지에서 조달청 API 인증키(serviceKey 쿼리 값)를 가립니다."""

    _SERVICE_KEY_PATTERN = re.compile(r"(?i)(serviceKey=)[^&\s'\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._SERVICE_KEY_PATTERN.sub(r"\1***", message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def get_logging_config(log_level: str = "INFO") -> dict[str, Any]:
    """dictConfig 에 전달할 로깅 설정 딕셔너리를 생성합니다."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": DEFAULT_LOG_FORMAT,
                "datefmt": DEFAULT_DATE_FORMAT,
            },
        },
        "filters": {
            "service_key_redaction": {
                "()": "src.app.core.logging_config.ServiceKeyRedactionFilter",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "standard",
                "filters": ["service_key_redaction"],
            },
        },
        "loggers": {
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            # chromadb 0.6.3 은 텔레메트리를 꺼도 posthog.capture 를 부르고, posthog 7.x 와
            # 인자가 맞지 않아 클라이언트 생성마다 ERROR 를 남깁니다. 전송은 이미 꺼져 있습니다.
            "chromadb.telemetry.product.posthog": {"level": "CRITICAL"},
        },
        "root": {
            "level": str(log_level).upper(),
            "handlers": ["default"],
        },
    }


def configure_logging(log_level: str | None = None) -> None:
    """애플리케이션과 워커 전역의 루트 로거를 dictConfig 로 구성합니다.

    logging.basicConfig 는 루트 로거에 기존 핸들러가 등록되어 있을 경우 조용히 무동작하므로,
    반드시 logging.config.dictConfig 를 사용해 루트 로거의 레벨과 핸들러를 확실하게 설정합니다.
    """
    if log_level is None:
        from src.app.core.config import settings

        log_level = settings.LOG_LEVEL

    config = get_logging_config(log_level)
    logging.config.dictConfig(config)


setup_logging = configure_logging
