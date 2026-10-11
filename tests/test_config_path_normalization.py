"""tests/test_config_path_normalization.py

경로 설정 정규화 검증.

실행 위치(CWD)와 무관하게 경로 설정이 프로젝트 루트 기준으로 해석되는지 확인합니다.
.env 의 간섭을 배제하기 위해 `Settings(_env_file=None)` 으로 새로 만듭니다.
"""

from __future__ import annotations

from pathlib import Path

from src.app.core.config import PROJECT_ROOT, Settings

# 프로젝트 루트 기준으로 정규화되는 경로 설정 필드입니다.
_PATH_FIELDS = (
    "CHROMA_DB_PATH",
    "MODEL_FILES_DIR",
    "MODEL_BACKUPS_DIR",
    "MODEL_METRICS_DIR",
    "MODEL_REGISTRY_DIR",
    "FEATURE_STORE_DIR",
)

_RELATIVE_ENV_VALUES = {
    "CHROMA_DB_PATH": "chroma_db",
    "MODEL_FILES_DIR": "data/model_files",
    "MODEL_BACKUPS_DIR": "data/model_backups",
    "MODEL_METRICS_DIR": "data/model_metrics",
    "MODEL_REGISTRY_DIR": "ml_registry",
    "FEATURE_STORE_DIR": "data/feature_store",
}


def _settings_without_env_file(monkeypatch, **overrides) -> Settings:
    """경로 설정 env 를 비우고 .env 를 건너뛴 Settings 를 만듭니다."""
    for field in _PATH_FIELDS:
        monkeypatch.delenv(field, raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-key-at-least-32-characters")
    return Settings(_env_file=None, **overrides)


def test_relative_env_paths_resolve_to_project_root(tmp_path, monkeypatch):
    """상대 경로 환경변수 값은 CWD 가 아니라 프로젝트 루트 기준이어야 합니다."""
    monkeypatch.chdir(tmp_path)
    for field, value in _RELATIVE_ENV_VALUES.items():
        monkeypatch.setenv(field, value)

    settings = Settings(_env_file=None)

    for field, value in _RELATIVE_ENV_VALUES.items():
        resolved = Path(getattr(settings, field))
        assert resolved == PROJECT_ROOT / value
        assert resolved.is_absolute()
        assert not str(resolved).startswith(str(tmp_path))


def test_default_paths_are_project_root_absolute(tmp_path, monkeypatch):
    """기본값도 CWD 와 무관하게 프로젝트 루트 기준 절대 경로여야 합니다."""
    monkeypatch.chdir(tmp_path)
    settings = _settings_without_env_file(monkeypatch)

    assert Path(settings.CHROMA_DB_PATH) == PROJECT_ROOT / "chroma_db"
    assert Path(settings.MODEL_FILES_DIR) == PROJECT_ROOT / "data" / "model_files"
    assert Path(settings.MODEL_BACKUPS_DIR) == PROJECT_ROOT / "data" / "model_backups"
    assert Path(settings.MODEL_METRICS_DIR) == PROJECT_ROOT / "data" / "model_metrics"
    assert Path(settings.MODEL_REGISTRY_DIR) == PROJECT_ROOT / "ml_registry"
    assert Path(settings.FEATURE_STORE_DIR) == PROJECT_ROOT / "data" / "feature_store"
    for field in _PATH_FIELDS:
        assert Path(getattr(settings, field)).is_absolute()


def test_absolute_env_paths_are_preserved(tmp_path, monkeypatch):
    """절대 경로 값은 그대로 유지되어야 합니다 (Docker 의 /app 경로 등)."""
    monkeypatch.chdir(tmp_path)
    settings = _settings_without_env_file(
        monkeypatch,
        CHROMA_DB_PATH="/app/chroma_db",
        MODEL_FILES_DIR="/app/data/model_files",
    )

    assert settings.CHROMA_DB_PATH == "/app/chroma_db"
    assert settings.MODEL_FILES_DIR == "/app/data/model_files"


def test_trainer_defaults_to_settings_registry_dir(tmp_path, monkeypatch):
    """하드코딩을 설정값으로 바꾼 함수가 기본값으로 설정 경로를 쓰는지 확인합니다."""
    from src.app.core.config import settings
    from src.ml.trainer import ModelTrainer

    monkeypatch.chdir(tmp_path)

    default_trainer = ModelTrainer.for_category("Servc")
    assert default_trainer.registry_dir == Path(settings.MODEL_REGISTRY_DIR)
    assert default_trainer.registry_dir.is_absolute()

    explicit = tmp_path / "custom_registry"
    explicit_trainer = ModelTrainer.for_category("Servc", registry_dir=str(explicit))
    assert explicit_trainer.registry_dir == explicit
