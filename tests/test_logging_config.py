"""tests/test_logging_config.py

루트 로깅 구성, Uvicorn/Arq 호환성, 중복 출력 방지,
Settings.LOG_LEVEL 검증 및 .env.example 동적 대응 검사 테스트.
"""

from __future__ import annotations

import ast
import logging
import logging.config
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import uvicorn.config
from pydantic import ValidationError

from src.app.core.config import Settings, settings
from src.app.core.logging_config import (
    configure_logging,
)
from src.app.main import (
    _enable_latency_segment_logging,
    _enable_warmup_logging,
)
from src.tasks.worker import WorkerSettings

INFRA_ONLY_KEYS = frozenset(
    {
        "MYSQL_ROOT_PASSWORD",
        "WEB_CONCURRENCY",
        "GF_SECURITY_ADMIN_PASSWORD",
        "G2B_SERVICE_KEY",
        "ALERTMANAGER_SLACK_WEBHOOK_URL",
        "WORKER_HEARTBEAT_MAX_AGE_SECONDS",
    }
)


@pytest.fixture(autouse=True)
def restore_logging_state():
    """각 테스트 전후 로거 핸들러와 레벨 상태를 안전하게 복원합니다."""
    root = logging.getLogger()
    original_root_handlers = list(root.handlers)
    original_root_level = root.level

    warmup_logger = logging.getLogger("src.app.main")
    original_warmup_handlers = list(warmup_logger.handlers)
    original_warmup_level = warmup_logger.level
    original_warmup_propagate = warmup_logger.propagate

    segment_logger = logging.getLogger("src.rag.engine")
    original_segment_handlers = list(segment_logger.handlers)
    original_segment_level = segment_logger.level
    original_segment_propagate = segment_logger.propagate

    dashboard_logger = logging.getLogger("src.app.services.dashboard")
    original_dashboard_handlers = list(dashboard_logger.handlers)
    original_dashboard_level = dashboard_logger.level
    original_dashboard_propagate = dashboard_logger.propagate

    yield

    root.handlers = original_root_handlers
    root.setLevel(original_root_level)

    warmup_logger.handlers = original_warmup_handlers
    warmup_logger.setLevel(original_warmup_level)
    warmup_logger.propagate = original_warmup_propagate

    segment_logger.handlers = original_segment_handlers
    segment_logger.setLevel(original_segment_level)
    segment_logger.propagate = original_segment_propagate

    dashboard_logger.handlers = original_dashboard_handlers
    dashboard_logger.setLevel(original_dashboard_level)
    dashboard_logger.propagate = original_dashboard_propagate


def test_no_basic_config_used():
    """logging.basicConfig 가 프로젝트 로깅 구성 코드에서 사용되지 않았는지 검증합니다."""
    source_files = [
        Path("src/app/core/logging_config.py"),
        Path("src/app/main.py"),
        Path("src/tasks/worker.py"),
    ]
    for file_path in source_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "basicConfig"
            ):
                pytest.fail(f"{file_path} 에서 logging.basicConfig 호출이 발견되었습니다.")


def test_configure_logging_does_not_call_basic_config():
    """configure_logging 실행 시 logging.basicConfig 가 호출되지 않고 dictConfig 가 사용되는지 검증합니다."""
    with patch("logging.basicConfig") as mock_basic:
        configure_logging("INFO")
        mock_basic.assert_not_called()


def test_uvicorn_baseline_emit_regression(capsys):
    """uvicorn 기본 로깅 적용 후 임의의 앱 로거가 INFO 로그를 실제로 출력하는지 검증합니다.

    uvicorn.config.LOGGING_CONFIG 는 root 핸들러를 정의하지 않으므로,
    configure_logging 적용 전에는 root 에 핸들러가 없어 info 로그가 유실됩니다.
    configure_logging 적용 후에는 실제 핸들러 출력을 통해 타임스탬프, 레벨, 로거명,
    event= 본문이 완전하게 방출되는지 확인합니다.
    """
    # 1. Uvicorn 기본 로깅 설정 주입 (루트에 핸들러를 정의하지 않음을 확인)
    assert "root" not in uvicorn.config.LOGGING_CONFIG.get("loggers", {})
    assert "root" not in uvicorn.config.LOGGING_CONFIG

    root = logging.getLogger()
    root.handlers.clear()
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    assert len(root.handlers) == 0, "uvicorn 기본 설정에서는 root 핸들러가 없어야 합니다."

    # 2. 우리 애플리케이션의 루트 로거 구성 적용
    configure_logging("INFO")
    assert len(root.handlers) >= 1, "configure_logging 적용 후 root 핸들러가 부착되어야 합니다."

    capsys.readouterr()

    # 3. 임의의 애플리케이션 모듈 로거에서 info 방출
    test_logger = logging.getLogger("src.tasks.scheduled_tasks")
    test_logger.info("event=daily_refresh_start, count=42, status=running")

    captured = capsys.readouterr()
    stdout = captured.out

    # 4. 실제 방출 여부 및 형식 검증
    assert "event=daily_refresh_start, count=42, status=running" in stdout
    assert "[INFO]" in stdout
    assert "src.tasks.scheduled_tasks" in stdout
    # 타임스탬프 형식 검증 (YYYY-MM-DD HH:MM:SS)
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stdout) is not None

    # INFO 레벨이므로 DEBUG 로그는 방출되지 않아야 함
    test_logger.debug("event=daily_refresh_detail, debug_info=secret")
    captured_debug = capsys.readouterr()
    assert "event=daily_refresh_detail" not in captured_debug.out


def test_log_level_debug_emits_debug_logs(capsys):
    """LOG_LEVEL=DEBUG 일 때 debug 로그가 실제로 출력되는지 검증합니다."""
    configure_logging("DEBUG")
    capsys.readouterr()

    test_logger = logging.getLogger("src.ml.trainer")
    test_logger.debug("event=epoch_debug, step=10, loss=0.123")

    captured = capsys.readouterr()
    assert "[DEBUG]" in captured.out
    assert "src.ml.trainer" in captured.out
    assert "event=epoch_debug, step=10, loss=0.123" in captured.out


def test_settings_log_level_validation():
    """Settings 의 LOG_LEVEL 필드 기본값과 유효성 검증을 확인합니다."""
    # 기본값은 INFO
    s_default = Settings(SECRET_KEY="a" * 32)
    assert s_default.LOG_LEVEL == "INFO"

    # 대소문자 허용 및 정규화
    s_debug = Settings(SECRET_KEY="a" * 32, LOG_LEVEL="debug")
    assert s_debug.LOG_LEVEL == "DEBUG"

    s_warn = Settings(SECRET_KEY="a" * 32, LOG_LEVEL="warning")
    assert s_warn.LOG_LEVEL == "WARNING"

    s_err = Settings(SECRET_KEY="a" * 32, LOG_LEVEL="error")
    assert s_err.LOG_LEVEL == "ERROR"

    s_crit = Settings(SECRET_KEY="a" * 32, LOG_LEVEL="CRITICAL")
    assert s_crit.LOG_LEVEL == "CRITICAL"

    # 잘못된 값은 검증에서 에러 발생
    invalid_levels = ["INVALID", "VERBOSE", "TRACE", "100", ""]
    for level in invalid_levels:
        with pytest.raises(ValidationError):
            Settings(SECRET_KEY="a" * 32, LOG_LEVEL=level)


def test_warmup_logging_no_duplicate_output(capsys):
    """루트 로거 구성 후 _enable_warmup_logging 이 중복 출력을 유발하지 않는지 검증합니다."""
    configure_logging("INFO")
    _enable_warmup_logging()

    capsys.readouterr()

    app_logger = logging.getLogger("src.app.main")
    app_logger.info("event=predictor_warmup, status=success, elapsed_ms=12.34")

    captured = capsys.readouterr()
    # 정확히 한 번만 출력되어야 함
    count = captured.out.count("event=predictor_warmup, status=success, elapsed_ms=12.34")
    assert count == 1, f"예열 로그가 {count}회 출력되었습니다 (1회여야 함)."
    assert "[INFO]" in captured.out
    assert "src.app.main" in captured.out


def test_latency_segment_logging_no_duplicate_output(capsys):
    """LATENCY_SEGMENT_LOGGING 활성화 시 세그먼트 로그가 중복 출력되지 않는지 검증합니다."""
    segment_logger = logging.getLogger("src.rag.engine")
    segment_logger.handlers.clear()
    configure_logging("INFO")
    with patch.object(settings, "LATENCY_SEGMENT_LOGGING", True):
        _enable_latency_segment_logging()

        capsys.readouterr()

        segment_logger = logging.getLogger("src.rag.engine")
        segment_logger.info("event=rag_segment, sql_ms=2.5, vector_ms=4.1")

        captured = capsys.readouterr()
        count = captured.out.count("event=rag_segment, sql_ms=2.5, vector_ms=4.1")
        assert count == 1, f"세그먼트 로그가 {count}회 출력되었습니다 (1회여야 함)."
        assert "[INFO]" in captured.out
        assert "src.rag.engine" in captured.out


@pytest.mark.asyncio
async def test_worker_logging_uses_same_configuration(capsys):
    """Arq 워커 진입점(WorkerSettings.on_startup)이 앱과 동일한 로깅 구성을 적용하는지 검증합니다."""
    import arq.logs

    # 1. Arq 기본 로깅 설정 주입
    logging.config.dictConfig(arq.logs.default_log_config(True))

    # 2. Worker on_startup 실행
    ctx: dict[str, Any] = {}
    with (
        patch("src.tasks.worker.record_worker_heartbeat"),
        patch("src.tasks.worker._heartbeat_loop"),
    ):
        await WorkerSettings.on_startup(ctx)

    capsys.readouterr()

    # 3. 워커 내부 태스크 로거 출력 검증
    worker_task_logger = logging.getLogger("src.tasks.automation_tasks")
    worker_task_logger.info("event=collect_bids_start, target=g2b")

    captured = capsys.readouterr()
    assert "event=collect_bids_start, target=g2b" in captured.out
    assert "[INFO]" in captured.out
    assert "src.tasks.automation_tasks" in captured.out
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", captured.out) is not None


def test_settings_and_env_example_parity():
    """Settings 모델 필드와 .env.example 키 대응을 동적으로 전수 검증합니다.

    새로운 필드가 Settings 에 추가되었는데 .env.example 에 반영되지 않으면 이 테스트는 즉시 실패합니다.
    컨테이너 전용 인프라 키(INFRA_ONLY_KEYS) 6개는 명시적 예외로 허용됩니다.
    """
    env_path = Path(".env.example")
    assert env_path.exists(), ".env.example 파일이 존재해야 합니다."

    env_content = env_path.read_text(encoding="utf-8")
    env_lines = env_content.splitlines()

    env_keys: set[str] = set()
    for line in env_lines:
        line_str = line.strip()
        if line_str and not line_str.startswith("#") and "=" in line_str:
            key = line_str.split("=", 1)[0].strip()
            env_keys.add(key)

    # Settings 필드 동적 읽기
    settings_fields: set[str] = set(Settings.model_fields.keys())

    # 1. Settings 에 존재하는 모든 필드가 .env.example 에 포함되어 있는지 검증
    missing_in_env = settings_fields - env_keys
    assert not missing_in_env, (
        f"Settings 에 정의되었으나 .env.example 에 누락된 필드가 있습니다: {sorted(missing_in_env)}"
    )

    # 2. .env.example 에 존재하는 키 중 Settings 또는 INFRA_ONLY_KEYS 에 없는 불명 키가 없는지 검증
    extra_in_env = env_keys - (settings_fields | INFRA_ONLY_KEYS)
    assert not extra_in_env, (
        f".env.example 에 정의되었으나 Settings 및 INFRA_ONLY_KEYS 에 존재하지 않는 키가 있습니다: {sorted(extra_in_env)}"
    )

    # 3. 인프라 전용 키 6개가 .env.example 에 모두 존재하는지 검증
    missing_infra = INFRA_ONLY_KEYS - env_keys
    assert not missing_infra, (
        f"컨테이너 인프라 전용 필수 키가 .env.example 에 누락되었습니다: {sorted(missing_infra)}"
    )

    # 4. .env.example 이 애플리케이션 설정 절과 컨테이너 인프라 설정 절 두 개로 명확히 나뉘어 있는지 검증
    assert "1. 애플리케이션 설정 (Application Settings)" in env_content
    assert "2. 컨테이너 인프라 설정 (Container Infrastructure Settings)" in env_content

    # 5. 각 인프라 키가 컨테이너 인프라 설정 절 이후에 위치하는지 검증
    infra_section_pos = env_content.find(
        "2. 컨테이너 인프라 설정 (Container Infrastructure Settings)"
    )
    for key in INFRA_ONLY_KEYS:
        key_pos = env_content.find(f"{key}=")
        assert key_pos > infra_section_pos, (
            f"인프라 키 {key} 는 컨테이너 인프라 설정 절 아래에 배치되어야 합니다."
        )


def test_env_example_has_no_secrets():
    """.env.example 에 실제 비밀값(하드코딩된 시크릿, API 키 등)이 누출되지 않았는지 검증합니다."""
    env_content = Path(".env.example").read_text(encoding="utf-8")

    # 민감한 키의 값이 비어 있거나 안전한 예시 값이어야 함
    sensitive_keys = [
        "GEMINI_API_KEY",
        "GF_SECURITY_ADMIN_PASSWORD",
        "G2B_SERVICE_KEY",
        "ALERTMANAGER_SLACK_WEBHOOK_URL",
        "MEILI_MASTER_KEY",
        "MLOPS_WEBHOOK_URL",
    ]
    for line in env_content.splitlines():
        line_str = line.strip()
        if not line_str or line_str.startswith("#") or "=" not in line_str:
            continue
        key, val = line_str.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key in sensitive_keys:
            assert val == "", f"{key} 에 실제 비밀값이 들어가면 안 됩니다: {val}"
        if key == "SECRET_KEY":
            assert val.startswith("change-this"), "SECRET_KEY는 안전한 플레이스홀더여야 합니다."
