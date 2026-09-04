"""
tests/test_model_schema_parity.py

SQLAlchemy 모델 선언이 원본 Django 스키마를 그대로 재현하는지 검증합니다.

DB 접속 없이 컴파일된 DDL 과 컬럼 속성만 확인합니다. 실제 DB 대조는
`make migrate-check` (scripts/check_schema_drift.py) 가 담당합니다.

이 파일이 막는 사고는 하나입니다. 모델이 원본보다 느슨하거나 좁게 선언되면
`alembic revision --autogenerate` 가 운영 스키마를 바꾸는 DDL 을 만들어냅니다.
특히 LONGTEXT -> TEXT 는 64KB 를 넘는 기존 값을 잘라냅니다.
"""

from typing import Any

import pytest
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect

import src.app.models  # noqa: F401
from src.app.core.db import Base
from src.app.core.timeutil import utcnow

MYSQL = mysql.dialect()
SQLITE = sqlite.dialect()

# 원본 Django TextField 로 만들어져 DB 에 LONGTEXT 로 존재하는 컬럼입니다.
LONGTEXT_COLUMNS = [
    ("automation_requests", "requested_text"),
    ("automation_requests", "followup_query"),
    ("automation_requests", "execution_url"),
    ("automation_requests", "result_summary"),
    ("automation_requests", "error_message"),
    ("chat_session_states", "last_query"),
    ("chat_session_states", "last_result_summary"),
    ("knowledge_base_status", "notes"),
    ("pipeline_executions", "logs_summary"),
    ("pipeline_executions", "external_url"),
]

# 원본에서 NOT NULL 인데 이식 과정에서 nullable 로 느슨해졌던 컬럼입니다.
NOT_NULL_COLUMNS = [
    ("automation_requests", "request_id"),
    ("automation_requests", "user_id"),
    ("automation_requests", "intent_type"),
    ("automation_requests", "status"),
    ("automation_requests", "requires_confirmation"),
    ("automation_subscriptions", "user_id"),
    ("automation_subscriptions", "is_active"),
    ("bid_announcements", "bid_ntce_ord"),
    ("bid_announcements", "category"),
    ("bid_dataset_summaries", "total_count"),
    ("bid_dataset_summaries", "total_amount"),
    ("bid_results", "bid_ntce_ord"),
    ("bid_results", "category"),
    ("chat_session_states", "session_key"),
    ("knowledge_base_status", "status"),
    ("knowledge_base_status", "source_bid_count"),
    ("pipeline_executions", "run_mode"),
    ("pipeline_executions", "status"),
    ("pipeline_executions", "source"),
    ("prediction_results", "bid_ntce_ord"),
]

# 원본 Django unique_together 가 만든 실제 인덱스명입니다. 이름이 다르면
# autogenerate 가 제약을 지우고 다시 만드는 DDL 을 제안합니다.
DJANGO_UNIQUE_NAMES = {
    "bid_announcements": "bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq",
    "bid_results": "bid_results_bid_ntce_no_bid_ntce_ord_category_94d04c58_uniq",
}


# 원본 Django Meta.indexes 가 직접 이름 붙인 복합 인덱스입니다. 이식 과정에서
# 통째로 빠져 있었습니다. 조회 성능에 직접 영향을 줍니다.
ORIGINAL_NAMED_INDEXES = {
    "automation_requests": [
        ("ix_auto_req_user_status", ("user_id", "status")),
        ("ix_auto_req_intent_created", ("intent_type", "created_at")),
        ("ix_auto_req_action_created", ("action_key", "created_at")),
    ],
    "automation_subscriptions": [
        ("ix_auto_sub_user_active", ("user_id", "is_active")),
        ("ix_auto_sub_type", ("automation_type",)),
    ],
    "chat_session_states": [
        ("ix_chat_state_user_updated", ("user_id", "updated_at")),
    ],
}

# 원본 FK 제약명. accounts_customuser 를 참조하는 세 테이블입니다.
ORIGINAL_FOREIGN_KEYS = {
    "automation_requests": "automation_requests_user_id_09027998_fk_accounts_customuser_id",
    "automation_subscriptions": "automation_subscript_user_id_65841fc4_fk_accounts_",
    "chat_session_states": "chat_session_states_user_id_47adeb98_fk_accounts_customuser_id",
}

# 원본 prediction_results 에는 인덱스가 없습니다. 이식본이 임의로 추가했던 것들입니다.
TABLES_WITHOUT_EXTRA_INDEXES = ("prediction_results", "retrain_logs")

# 운영 DB 에 실재하는 인덱스명입니다 (PRIMARY 제외). 2026-08-05 실측.
# 해시가 붙은 이름은 Django 자동 생성, ix_ 로 시작하는 것은 원본 Meta.indexes 가
# 직접 붙인 이름, 컬럼명 그대로인 것은 UNIQUE KEY 입니다.
PRODUCTION_INDEX_NAMES = {
    "accounts_customuser": {"username"},
    "automation_requests": {
        "automation_requests_action_key_72546a52",
        "automation_requests_created_at_1c714821",
        "automation_requests_intent_type_72f08cf2",
        "automation_requests_plan_execution_id_4f401e5d",
        "automation_requests_status_b21ae7da",
        "ix_auto_req_action_created",
        "ix_auto_req_intent_created",
        "ix_auto_req_user_status",
        "request_id",
    },
    "automation_subscriptions": {
        "automation_subscriptions_automation_type_64b4d3d1",
        "automation_subscriptions_is_active_1dd49756",
        "ix_auto_sub_type",
        "ix_auto_sub_user_active",
    },
    "bid_announcements": {
        "bid_announcements_bid_ntce_dt_c42f1afb",
        "bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq",
        "bid_announcements_category_02e9e006",
        "bid_announcements_dminstt_nm_952da702",
        "ix_bid_ann_collected",
        "ix_bid_ann_category_collected_dt",
        "ix_bid_ann_collected_dt",
        "ix_bid_ann_dt_cat",
    },
    "bid_dataset_summaries": {"bid_dataset_summaries_rebuilt_at_8d77f9db"},
    "bid_results": {
        "bid_results_bid_ntce_no_bid_ntce_ord_category_94d04c58_uniq",
        "bid_results_category_981358ae",
        "bid_results_collected_at_25a564b9",
        "bid_results_dminstt_nm_1b809760",
        "bid_results_rl_openg_dt_00b70e7a",
        "ix_bid_results_amt_id",
        "ix_bid_results_bidwinnr_nm",
        # 챗봇 통계 집계 커버링 인덱스. 마이그레이션 a1c4e7b90d21 로 추가했습니다.
        "ix_bid_results_cat_dt_stats",
        "ix_bid_results_dt_cat",
        "ix_bid_results_rate_id",
    },
    "chat_session_states": {
        "chat_session_states_updated_at_44284963",
        "ix_chat_state_user_updated",
        "session_key",
    },
    "knowledge_base_status": {"kb_version"},
    "pipeline_executions": {
        "execution_id",
        "ix_pipe_exec_created",
        "ix_pipe_exec_name_status",
        "pipeline_executions_pipeline_name_010b1479",
        "pipeline_executions_status_e7ec4919",
    },
    "prediction_results": set(),
    "retrain_logs": set(),
    # 원본에 없는 신규 테이블. 리비전 23cb59f0e3fe 가 만듭니다.
    "bid_ranking_snapshots": {"uq_bid_ranking_slot", "ix_bid_ranking_lookup"},
    # 원본에 없는 신규 테이블. 리비전 88dd431cb285 가 만듭니다.
    "institution_win_rate_stats": {"uq_inst_win_rate_scope"},
}


def _column(table: str, column: str):
    return Base.metadata.tables[table].c[column]


def _index_map(table: str) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(c.name for c in index.columns)
        for index in Base.metadata.tables[table].indexes
    }


@pytest.mark.parametrize(("table", "column"), LONGTEXT_COLUMNS)
def test_text_columns_compile_to_longtext_on_mysql(table, column):
    assert _column(table, column).type.compile(MYSQL) == "LONGTEXT"


@pytest.mark.parametrize(("table", "column"), LONGTEXT_COLUMNS)
def test_text_columns_stay_text_on_sqlite(table, column):
    """테스트는 SQLite 를 쓰므로 MySQL 전용 타입이 새어 나오면 안 됩니다."""
    assert _column(table, column).type.compile(SQLITE) == "TEXT"


@pytest.mark.parametrize(("table", "column"), NOT_NULL_COLUMNS)
def test_columns_are_not_nullable(table, column):
    assert _column(table, column).nullable is False


def test_request_id_keeps_uuid_on_mariadb_legacy_compat():
    """레거시 MariaDB 경로에서 request_id 가 UUID 타입을 유지하는지 확인합니다.

    운영 DB 는 MySQL 8 이며 request_id 는 VARCHAR(36) 으로 저장됩니다.
    MariaDB 방언('mariadb')은 'mysql' 변형 대상이 아니므로 UUID 타입이 그대로 사용됩니다.
    이 테스트는 레거시 호환성 보장 목적이며 운영 동작을 기술하지 않습니다.
    """
    column = _column("automation_requests", "request_id")
    mariadb = MariaDBDialect()
    assert column.type.compile(mariadb) == "UUID"


def test_request_id_uses_varchar_on_mysql():
    """MySQL 8 에는 UUID DDL 타입이 없어 빈 검증 DB도 생성 가능해야 합니다."""
    assert _column("automation_requests", "request_id").type.compile(MYSQL) == "VARCHAR(36)"


def test_request_id_stays_varchar_on_sqlite():
    """테스트는 SQLite 를 쓰므로 MySQL/MariaDB 전용 타입이 새어 나오면 안 됩니다."""
    assert _column("automation_requests", "request_id").type.compile(SQLITE) == "VARCHAR(36)"


def test_request_id_stays_string_in_python():
    """as_uuid=True 로 바뀌면 문자열 비교를 하는 기존 코드가 전부 깨집니다."""
    assert _column("automation_requests", "request_id").type.python_type is str


@pytest.mark.parametrize(("table", "expected"), sorted(DJANGO_UNIQUE_NAMES.items()))
def test_unique_constraint_names_match_django(table, expected):
    names = {c.name for c in Base.metadata.tables[table].constraints}
    assert expected in names


@pytest.mark.parametrize(
    ("table", "index_name", "columns"),
    [(t, n, c) for t, entries in ORIGINAL_NAMED_INDEXES.items() for n, c in entries],
)
def test_original_named_indexes_exist(table, index_name, columns):
    assert _index_map(table).get(index_name) == columns


@pytest.mark.parametrize(("table", "constraint_name"), sorted(ORIGINAL_FOREIGN_KEYS.items()))
def test_user_foreign_keys_are_declared(table, constraint_name):
    """원본은 accounts_customuser 를 FK 로 참조합니다. 이식본에는 빠져 있었습니다."""
    names = {fk.constraint.name for fk in Base.metadata.tables[table].foreign_keys}
    assert constraint_name in names


@pytest.mark.parametrize("table", TABLES_WITHOUT_EXTRA_INDEXES)
def test_tables_without_original_indexes_declare_none(table):
    """원본에 없는 인덱스를 더하면 autogenerate 가 생성 DDL 을 제안합니다."""
    assert _index_map(table) == {}


@pytest.mark.parametrize("table", sorted(PRODUCTION_INDEX_NAMES))
def test_declared_index_names_exist_in_production(table):
    """모델이 만드는 인덱스 이름은 전부 운영 DB 에 실재해야 합니다.

    index=True 는 ix_<table>_<column> 이라는 원본에 없는 이름을 만듭니다.
    그 상태로 autogenerate 를 돌리면 인덱스를 지우고 다시 만드는 DDL 이 나오고,
    수백만 행 테이블에서는 그 자체가 사고입니다.
    """
    declared = set(_index_map(table))
    unknown = sorted(declared - PRODUCTION_INDEX_NAMES[table])
    assert unknown == [], f"운영 DB 에 없는 인덱스명: {unknown}"


# ==============================================================================
# Bids 도메인 모델 메타데이터 불변성 회귀 테스트
# (BidResult, BidAnnouncement, BidDatasetSummary, BidRankingSnapshot, InstitutionWinRateStat)
# Mapped[] 타입 어노테이션 전환 시 테이블명, 컬럼명, 타입, nullable, PK,
# default, onupdate, unique constraint, index, FK 가 100% 보존됨을 보장합니다.
# ==============================================================================

BIDS_TABLE_SCHEMAS: dict[str, dict[str, Any]] = {
    "bid_results": {
        "primary_key": ("id",),
        "foreign_keys": set(),
        "unique_constraints": {
            "bid_results_bid_ntce_no_bid_ntce_ord_category_94d04c58_uniq": (
                "bid_ntce_no",
                "bid_ntce_ord",
                "category",
            ),
        },
        "indexes": {
            "ix_bid_results_bidwinnr_nm": ("bidwinnr_nm",),
            "ix_bid_results_dt_cat": ("rl_openg_dt", "category"),
            "ix_bid_results_amt_id": ("sucsf_bid_amt", "id"),
            "ix_bid_results_rate_id": ("sucsf_bid_rate", "id"),
            "bid_results_dminstt_nm_1b809760": ("dminstt_nm",),
            "bid_results_category_981358ae": ("category",),
            "bid_results_collected_at_25a564b9": ("collected_at",),
            "bid_results_rl_openg_dt_00b70e7a": ("rl_openg_dt",),
            "ix_bid_results_cat_dt_stats": (
                "category",
                "rl_openg_dt",
                "sucsf_bid_rate",
                "sucsf_bid_amt",
            ),
        },
        "columns": {
            "id": {
                "mysql_type": "BIGINT",
                "sqlite_type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_nm": {
                "mysql_type": "VARCHAR(500)",
                "sqlite_type": "VARCHAR(500)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_no": {
                "mysql_type": "VARCHAR(50)",
                "sqlite_type": "VARCHAR(50)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_ord": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "00",
                "onupdate": None,
            },
            "bidwinnr_nm": {
                "mysql_type": "VARCHAR(200)",
                "sqlite_type": "VARCHAR(200)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "sucsf_bid_amt": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "sucsf_bid_rate": {
                "mysql_type": "NUMERIC(10, 4)",
                "sqlite_type": "NUMERIC(10, 4)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "rl_openg_dt": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "dminstt_nm": {
                "mysql_type": "VARCHAR(200)",
                "sqlite_type": "VARCHAR(200)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "category": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "Thng",
                "onupdate": None,
            },
            "raw_data": {
                "mysql_type": "JSON",
                "sqlite_type": "JSON",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "collected_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": False,
                "primary_key": False,
                "default": utcnow,
                "onupdate": None,
            },
        },
    },
    "bid_announcements": {
        "primary_key": ("id",),
        "foreign_keys": set(),
        "unique_constraints": {
            "bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq": (
                "bid_ntce_no",
                "bid_ntce_ord",
                "category",
            ),
        },
        "indexes": {
            "ix_bid_ann_dt_cat": ("bid_ntce_dt", "category"),
            "bid_announcements_dminstt_nm_952da702": ("dminstt_nm",),
            "bid_announcements_bid_ntce_dt_c42f1afb": ("bid_ntce_dt",),
            "bid_announcements_category_02e9e006": ("category",),
            "ix_bid_ann_collected": ("collected_at",),
            "ix_bid_ann_category_collected_dt": ("category", "collected_at", "bid_ntce_dt", "id"),
            "ix_bid_ann_collected_dt": ("collected_at", "bid_ntce_dt", "id"),
        },
        "columns": {
            "id": {
                "mysql_type": "BIGINT",
                "sqlite_type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_nm": {
                "mysql_type": "VARCHAR(500)",
                "sqlite_type": "VARCHAR(500)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_no": {
                "mysql_type": "VARCHAR(50)",
                "sqlite_type": "VARCHAR(50)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_ord": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "000",
                "onupdate": None,
            },
            "ntce_instt_nm": {
                "mysql_type": "VARCHAR(200)",
                "sqlite_type": "VARCHAR(200)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "dminstt_nm": {
                "mysql_type": "VARCHAR(200)",
                "sqlite_type": "VARCHAR(200)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "base_amount": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "presmpt_prce": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_ntce_dt": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_clse_dt": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "openg_dt": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "ntce_kind_nm": {
                "mysql_type": "VARCHAR(100)",
                "sqlite_type": "VARCHAR(100)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "bid_methd_nm": {
                "mysql_type": "VARCHAR(100)",
                "sqlite_type": "VARCHAR(100)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "cntrct_mthd_nm": {
                "mysql_type": "VARCHAR(100)",
                "sqlite_type": "VARCHAR(100)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "category": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "Thng",
                "onupdate": None,
            },
            "raw_data": {
                "mysql_type": "JSON",
                "sqlite_type": "JSON",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "collected_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": False,
                "primary_key": False,
                "default": utcnow,
                "onupdate": None,
            },
        },
    },
    "bid_dataset_summaries": {
        "primary_key": ("dataset",),
        "foreign_keys": set(),
        "unique_constraints": {},
        "indexes": {
            "bid_dataset_summaries_rebuilt_at_8d77f9db": ("rebuilt_at",),
        },
        "columns": {
            "dataset": {
                "mysql_type": "VARCHAR(20)",
                "sqlite_type": "VARCHAR(20)",
                "nullable": False,
                "primary_key": True,
                "default": None,
                "onupdate": None,
            },
            "total_count": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": False,
                "primary_key": False,
                "default": 0,
                "onupdate": None,
            },
            "total_amount": {
                "mysql_type": "NUMERIC(30, 0)",
                "sqlite_type": "NUMERIC(30, 0)",
                "nullable": False,
                "primary_key": False,
                "default": 0,
                "onupdate": None,
            },
            "avg_rate": {
                "mysql_type": "NUMERIC(10, 4)",
                "sqlite_type": "NUMERIC(10, 4)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "source_latest_collected_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "rebuilt_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": False,
                "primary_key": False,
                "default": utcnow,
                "onupdate": utcnow,
            },
            "aggregation_version": {
                "mysql_type": "INTEGER",
                "sqlite_type": "INTEGER",
                "nullable": False,
                "primary_key": False,
                "default": 1,
                "onupdate": None,
            },
        },
    },
    "bid_ranking_snapshots": {
        "primary_key": ("id",),
        "foreign_keys": set(),
        "unique_constraints": {
            "uq_bid_ranking_slot": ("dataset", "dimension", "category", "rank"),
        },
        "indexes": {
            "ix_bid_ranking_lookup": ("dataset", "dimension", "category", "rank"),
        },
        "columns": {
            "id": {
                "mysql_type": "BIGINT",
                "sqlite_type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "default": None,
                "onupdate": None,
            },
            "dataset": {
                "mysql_type": "VARCHAR(20)",
                "sqlite_type": "VARCHAR(20)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "dimension": {
                "mysql_type": "VARCHAR(30)",
                "sqlite_type": "VARCHAR(30)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "category": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "",
                "onupdate": None,
            },
            "rank": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "label": {
                "mysql_type": "VARCHAR(500)",
                "sqlite_type": "VARCHAR(500)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "metric_count": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": False,
                "primary_key": False,
                "default": 0,
                "onupdate": None,
            },
            "rebuilt_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": False,
                "primary_key": False,
                "default": utcnow,
                "onupdate": utcnow,
            },
        },
    },
    "institution_win_rate_stats": {
        "primary_key": ("id",),
        "foreign_keys": set(),
        "unique_constraints": {
            "uq_inst_win_rate_scope": ("institution_name", "category"),
        },
        "indexes": {},
        "columns": {
            "id": {
                "mysql_type": "BIGINT",
                "sqlite_type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "default": None,
                "onupdate": None,
            },
            "institution_name": {
                "mysql_type": "VARCHAR(200)",
                "sqlite_type": "VARCHAR(200)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "category": {
                "mysql_type": "VARCHAR(10)",
                "sqlite_type": "VARCHAR(10)",
                "nullable": False,
                "primary_key": False,
                "default": "",
                "onupdate": None,
            },
            "sample_count": {
                "mysql_type": "BIGINT",
                "sqlite_type": "BIGINT",
                "nullable": False,
                "primary_key": False,
                "default": 0,
                "onupdate": None,
            },
            "avg_rate": {
                "mysql_type": "NUMERIC(10, 4)",
                "sqlite_type": "NUMERIC(10, 4)",
                "nullable": False,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "ewm_rate": {
                "mysql_type": "NUMERIC(10, 4)",
                "sqlite_type": "NUMERIC(10, 4)",
                "nullable": True,
                "primary_key": False,
                "default": None,
                "onupdate": None,
            },
            "rebuilt_at": {
                "mysql_type": "DATETIME",
                "sqlite_type": "DATETIME",
                "nullable": False,
                "primary_key": False,
                "default": utcnow,
                "onupdate": utcnow,
            },
        },
    },
}

BIDS_COLUMN_PARAMS = [
    (table, col_name, spec)
    for table, schema in BIDS_TABLE_SCHEMAS.items()
    for col_name, spec in schema["columns"].items()
]


def _check_default(col_default, expected_default):
    if expected_default is None:
        assert col_default is None
    elif callable(expected_default):
        assert col_default is not None
        assert (
            col_default.arg == expected_default
            or col_default.arg is expected_default
            or (
                callable(col_default.arg)
                and getattr(col_default.arg, "__name__", None) == expected_default.__name__
                and getattr(col_default.arg, "__module__", None) == expected_default.__module__
            )
        )
    else:
        assert col_default is not None
        assert col_default.arg == expected_default


def _check_onupdate(col_onupdate, expected_onupdate):
    if expected_onupdate is None:
        assert col_onupdate is None
    elif callable(expected_onupdate):
        assert col_onupdate is not None
        assert (
            col_onupdate.arg == expected_onupdate
            or col_onupdate.arg is expected_onupdate
            or (
                callable(col_onupdate.arg)
                and getattr(col_onupdate.arg, "__name__", None) == expected_onupdate.__name__
                and getattr(col_onupdate.arg, "__module__", None) == expected_onupdate.__module__
            )
        )
    else:
        assert col_onupdate is not None
        assert col_onupdate.arg == expected_onupdate


def _unique_constraint_map(table: str) -> dict[str, tuple[str, ...]]:
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in Base.metadata.tables[table].constraints
        if type(c).__name__ == "UniqueConstraint" and c.name is not None
    }


def _foreign_key_targets(table: str) -> set[str]:
    return {fk.target_fullname for fk in Base.metadata.tables[table].foreign_keys}


def _pk_columns(table: str) -> tuple[str, ...]:
    return tuple(c.name for c in Base.metadata.tables[table].primary_key.columns)


@pytest.mark.parametrize("table", sorted(BIDS_TABLE_SCHEMAS.keys()))
def test_bids_table_column_names_exact(table):
    """bids 도메인 테이블의 모든 컬럼 이름과 순서가 정본과 일치해야 합니다."""
    declared_cols = tuple(Base.metadata.tables[table].columns.keys())
    expected_cols = tuple(BIDS_TABLE_SCHEMAS[table]["columns"].keys())
    assert declared_cols == expected_cols


@pytest.mark.parametrize(("table", "col_name", "spec"), BIDS_COLUMN_PARAMS)
def test_bids_column_metadata_invariance(table, col_name, spec):
    """bids 도메인 컬럼의 MySQL/SQLite 방언 타입, nullable, PK, 기본값, 갱신 기본값을 검증합니다."""
    col = _column(table, col_name)
    assert col.type.compile(MYSQL) == spec["mysql_type"], f"{table}.{col_name} MySQL 타입 불일치"
    assert col.type.compile(SQLITE) == spec["sqlite_type"], f"{table}.{col_name} SQLite 타입 불일치"
    assert col.nullable is spec["nullable"], f"{table}.{col_name} nullable 불일치"
    assert col.primary_key is spec["primary_key"], f"{table}.{col_name} primary_key 불일치"
    _check_default(col.default, spec["default"])
    _check_onupdate(col.onupdate, spec["onupdate"])


@pytest.mark.parametrize("table", sorted(BIDS_TABLE_SCHEMAS.keys()))
def test_bids_table_primary_key(table):
    """bids 도메인 테이블의 기본키(PK) 구성이 불변이어야 합니다."""
    assert _pk_columns(table) == BIDS_TABLE_SCHEMAS[table]["primary_key"]


@pytest.mark.parametrize("table", sorted(BIDS_TABLE_SCHEMAS.keys()))
def test_bids_table_foreign_keys(table):
    """bids 도메인 테이블의 외래키(FK) 구성이 정본과 일치해야 합니다."""
    assert _foreign_key_targets(table) == BIDS_TABLE_SCHEMAS[table]["foreign_keys"]


@pytest.mark.parametrize("table", sorted(BIDS_TABLE_SCHEMAS.keys()))
def test_bids_table_unique_constraints(table):
    """bids 도메인 테이블의 UniqueConstraint 명칭 및 대상 컬럼이 불변이어야 합니다."""
    assert _unique_constraint_map(table) == BIDS_TABLE_SCHEMAS[table]["unique_constraints"]


@pytest.mark.parametrize("table", sorted(BIDS_TABLE_SCHEMAS.keys()))
def test_bids_table_named_indexes(table):
    """bids 도메인 테이블의 Named Index 명칭 및 대상 컬럼이 불변이어야 합니다."""
    assert _index_map(table) == BIDS_TABLE_SCHEMAS[table]["indexes"]
