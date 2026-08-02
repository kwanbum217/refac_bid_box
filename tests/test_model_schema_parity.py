"""
tests/test_model_schema_parity.py

SQLAlchemy 모델 선언이 원본 Django 스키마를 그대로 재현하는지 검증합니다.

DB 접속 없이 컴파일된 DDL 과 컬럼 속성만 확인합니다. 실제 DB 대조는
`make migrate-check` (scripts/check_schema_drift.py) 가 담당합니다.

이 파일이 막는 사고는 하나입니다. 모델이 원본보다 느슨하거나 좁게 선언되면
`alembic revision --autogenerate` 가 운영 스키마를 바꾸는 DDL 을 만들어냅니다.
특히 LONGTEXT -> TEXT 는 64KB 를 넘는 기존 값을 잘라냅니다.
"""

import pytest
from sqlalchemy.dialects import mysql, sqlite

import src.app.models  # noqa: F401
from src.app.core.db import Base

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

# 운영 DB 에 실재하는 인덱스명입니다 (PRIMARY 제외). 2026-08-02 실측.
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


def test_request_id_uses_native_uuid_on_mariadb():
    """운영 DB(MariaDB 12.3) 의 request_id 는 네이티브 uuid 컬럼입니다.

    일반 Uuid 는 CHAR(32), String(36) 은 VARCHAR(36) 으로 컴파일되어 둘 다
    원본과 어긋납니다. 어긋난 채로 autogenerate 를 돌리면 운영 테이블에
    ALTER COLUMN 이 걸립니다.
    """
    column = _column("automation_requests", "request_id")
    mariadb = mysql.dialect()
    mariadb.supports_native_uuid = True
    assert column.type.compile(mariadb) == "UUID"


def test_request_id_stays_varchar_on_sqlite():
    """테스트는 SQLite 를 쓰므로 MariaDB 전용 타입이 새어 나오면 안 됩니다."""
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
    names = {
        fk.constraint.name
        for fk in Base.metadata.tables[table].foreign_keys
    }
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
