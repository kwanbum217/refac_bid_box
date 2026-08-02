"""
migrations/env.py

Alembic 실행 환경. 접속 주소는 alembic.ini 가 아니라 애플리케이션 설정
(src/app/core/config.settings.DATABASE_URL)에서 가져옵니다. 앱과 마이그레이션이
서로 다른 DB 를 보는 사고를 막기 위해서입니다.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.config import settings  # noqa: E402
from src.app.core.db import Base  # noqa: E402
import src.app.models  # noqa: E402,F401  모든 테이블을 Base.metadata 에 등록

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 운영 DB 에는 원본 Django 가 만든 테이블(auth_*, django_*, socialaccount_*,
# account_*, accounts_customuser_groups 등)이 그대로 남아 있습니다. 이식본은 이들을
# ORM 모델로 옮기지 않았으므로, 필터가 없으면 autogenerate 가 전부 DROP 대상으로
# 잡습니다. 데이터 무손실 원칙(G1)을 지키기 위해 모델에 있는 테이블만 추적합니다.
MANAGED_TABLES = frozenset(Base.metadata.tables)


def include_name(name, type_, parent_names) -> bool:
    if type_ == "table":
        return name is None or name in MANAGED_TABLES
    return True


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return name in MANAGED_TABLES
    if reflected and getattr(obj, "table", None) is not None:
        return obj.table.name in MANAGED_TABLES
    return True


def _strip_comment_only_changes(context_, revision, directives) -> None:
    """주석만 다른 변경은 마이그레이션에서 제외합니다.

    원본 Django 는 컬럼 주석을 DB 에 기록하지 않지만, 이식본 모델은 한국어 주석을
    문서로 달고 있습니다. 그대로 두면 autogenerate 가 매번 컬럼 67개의 주석 변경을
    제안하고, 그 소음에 진짜 스키마 변경이 묻힙니다.
    """
    if not directives:
        return

    upgrade_ops = directives[0].upgrade_ops
    if upgrade_ops is None:
        return

    # 미변경 표시는 필드마다 다릅니다 (modify_type/modify_nullable 은 None,
    # modify_server_default 는 False). 주석 자체는 upgrade 에서 문자열, downgrade 에서
    # None 이 되므로 modify_comment 값으로는 판별할 수 없습니다. alembic 은 차이가
    # 있을 때만 op 를 만들므로, 나머지가 모두 미변경이면 주석 변경뿐입니다.
    UNCHANGED = (None, False)

    def _is_comment_only(op) -> bool:
        if type(op).__name__ != "AlterColumnOp":
            return False
        return not any(
            getattr(op, key, None) not in UNCHANGED
            for key in ("modify_type", "modify_nullable", "modify_server_default", "modify_name")
        )

    for ops_container in (directives[0].upgrade_ops, directives[0].downgrade_ops):
        if ops_container is None:
            continue
        for modify in ops_container.ops:
            inner = getattr(modify, "ops", None)
            if inner is not None:
                modify.ops = [op for op in inner if not _is_comment_only(op)]
        ops_container.ops = [
            op
            for op in ops_container.ops
            if not _is_comment_only(op) and getattr(op, "ops", None) != []
        ]

    # 걸러내고 나서 남은 변경이 없으면 빈 리비전 파일을 만들지 않습니다.
    if directives[0].upgrade_ops.is_empty():
        directives[:] = []


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_name=include_name,
        include_object=include_object,
        process_revision_directives=_strip_comment_only_changes,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_name=include_name,
            include_object=include_object,
            process_revision_directives=_strip_comment_only_changes,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
