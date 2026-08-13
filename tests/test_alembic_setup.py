"""
tests/test_alembic_setup.py

Alembic 구성 안전장치 검증.

운영 DB 에는 원본 Django 가 만든 테이블이 그대로 남아 있습니다. autogenerate 가
이들을 DROP 대상으로 잡으면 데이터 무손실 원칙(G1)이 깨집니다. 필터가 사라지거나
기준선 리비전이 흔들리는 것을 막는 것이 이 파일의 목적입니다.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

import src.app.models  # noqa: F401  모든 테이블을 Base.metadata 에 등록
from src.app.core.db import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE = "0001_django_baseline"

# 운영 DB 에 남아 있는 원본 Django 테이블. 하나라도 관리 대상에 들어오면
# autogenerate 가 DROP 을 제안하게 됩니다.
# 원본 Django 19개 마이그레이션이 만든 테이블. 기준선 리비전의 범위입니다.
DJANGO_BASELINE_TABLES = (
    "accounts_customuser",
    "automation_requests",
    "automation_subscriptions",
    "bid_announcements",
    "bid_dataset_summaries",
    "bid_results",
    "chat_session_states",
    "knowledge_base_status",
    "pipeline_executions",
    "prediction_results",
    "retrain_logs",
)

DJANGO_LEGACY_TABLES = (
    "django_migrations",
    "django_session",
    "django_admin_log",
    "django_content_type",
    "django_site",
    "auth_group",
    "auth_permission",
    "auth_group_permissions",
    "accounts_customuser_groups",
    "accounts_customuser_user_permissions",
    "account_emailaddress",
    "account_emailconfirmation",
    "socialaccount_socialaccount",
    "socialaccount_socialapp",
    "socialaccount_socialapp_sites",
    "socialaccount_socialtoken",
)


@pytest.fixture(scope="module")
def script_directory():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config)


def _load_env_filters():
    """env.py 를 alembic 컨텍스트 없이 불러오기 위해 필터 함수만 재구성합니다."""
    source = (PROJECT_ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    start = source.index("MANAGED_TABLES = ")
    end = source.index("def run_migrations_offline")
    namespace: dict = {"Base": Base, "frozenset": frozenset}
    exec(compile(source[start:end], "env_filters", "exec"), namespace)
    return namespace


# --------------------------------------------------------------------------- #
# 기준선 리비전
# --------------------------------------------------------------------------- #


def test_baseline_is_the_root_revision(script_directory):
    """기준선은 항상 이력의 뿌리여야 합니다. head 는 리비전이 쌓이며 앞으로 갑니다."""
    assert list(script_directory.get_bases()) == [BASELINE]


def test_revision_history_is_linear(script_directory):
    """분기가 생기면 어느 것이 진짜 스키마인지 알 수 없게 됩니다."""
    assert len(script_directory.get_heads()) == 1


def test_baseline_has_no_parent(script_directory):
    revision = script_directory.get_revision(BASELINE)
    assert revision.down_revision is None


def test_baseline_creates_every_django_table():
    """원본 Django 19개 마이그레이션이 만든 테이블은 전부 기준선에 있어야 합니다.

    이후 추가된 테이블(`bid_ranking_snapshots` 등)은 후속 리비전 소관이므로
    기준선에 없는 것이 정상입니다.
    """
    source = (PROJECT_ROOT / "migrations" / "versions" / f"{BASELINE}.py").read_text(
        encoding="utf-8"
    )
    for table in sorted(DJANGO_BASELINE_TABLES):
        assert f"op.create_table('{table}'" in source, f"{table} 이 기준선에 없습니다."


def test_baseline_uses_mysql_compatible_request_id_type():
    """MySQL 8 은 UUID DDL 타입을 지원하지 않으므로 빈 DB 생성이 가능해야 합니다."""
    source = (PROJECT_ROOT / "migrations" / "versions" / f"{BASELINE}.py").read_text(
        encoding="utf-8"
    )
    assert "sa.Column('request_id', sa.String(length=36)" in source


def test_every_modeled_table_is_created_by_some_revision():
    """모델에 있는데 어느 리비전도 만들지 않으면 신규 환경이 깨집니다."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "migrations" / "versions").glob("*.py")
    )
    for table in sorted(Base.metadata.tables):
        assert f"op.create_table('{table}'" in sources, f"{table} 을 만드는 리비전이 없습니다."


def test_baseline_does_not_touch_django_legacy_tables():
    """기준선이 Django 인프라 테이블을 만들거나 지우면 안 됩니다."""
    source = (PROJECT_ROOT / "migrations" / "versions" / f"{BASELINE}.py").read_text(
        encoding="utf-8"
    )
    for table in DJANGO_LEGACY_TABLES:
        assert f"'{table}'" not in source, f"{table} 이 기준선에 등장합니다."


# --------------------------------------------------------------------------- #
# autogenerate 필터
# --------------------------------------------------------------------------- #


def test_managed_tables_match_models():
    namespace = _load_env_filters()
    assert namespace["MANAGED_TABLES"] == frozenset(Base.metadata.tables)


@pytest.mark.parametrize("table", DJANGO_LEGACY_TABLES)
def test_django_legacy_tables_are_excluded(table):
    namespace = _load_env_filters()
    assert namespace["include_name"](table, "table", {}) is False
    assert namespace["include_object"](None, table, "table", True, None) is False


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_modeled_tables_are_included(table):
    namespace = _load_env_filters()
    assert namespace["include_name"](table, "table", {}) is True
    assert namespace["include_object"](None, table, "table", True, None) is True


def test_alembic_version_table_is_not_managed():
    """alembic 자체 버전 테이블은 모델에 없으므로 관리 대상 밖이어야 합니다."""
    namespace = _load_env_filters()
    assert namespace["include_object"](None, "alembic_version", "table", True, None) is False


def test_env_reads_url_from_application_settings():
    """alembic.ini 자리표시자를 그대로 쓰면 엉뚱한 DB 에 붙습니다."""
    source = (PROJECT_ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    assert 'config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)' in source
