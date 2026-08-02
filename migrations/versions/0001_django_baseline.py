"""django schema baseline

원본 bid_box 의 Django 마이그레이션 19개를 모두 적용한 뒤의 스키마 상태입니다.
운영 DB 를 그대로 반영(reflect)해 생성했으므로, 이미 Django 로 구축된 DB 에는
upgrade 를 실행하지 말고 `alembic stamp 0001_django_baseline` 로 버전만 기록하십시오.
새로 구축하는 환경에서만 upgrade 로 스키마를 만듭니다.

원본 마이그레이션 목록은 docs/migration/django_migration_history.md 에 기록되어 있습니다.

Revision ID: 0001_django_baseline
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0001_django_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('accounts_customuser',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('password', mysql.VARCHAR(length=128), nullable=False),
    sa.Column('last_login', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('is_superuser', mysql.TINYINT(display_width=1), autoincrement=False, nullable=False),
    sa.Column('username', mysql.VARCHAR(length=150), nullable=False),
    sa.Column('first_name', mysql.VARCHAR(length=150), nullable=False),
    sa.Column('last_name', mysql.VARCHAR(length=150), nullable=False),
    sa.Column('email', mysql.VARCHAR(length=254), nullable=False),
    sa.Column('is_staff', mysql.TINYINT(display_width=1), autoincrement=False, nullable=False),
    sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=False),
    sa.Column('date_joined', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('nickname', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('birth_y', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.Column('birth_m', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.Column('birth_d', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.Column('gender', mysql.VARCHAR(length=1), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('username', 'accounts_customuser', ['username'], unique=True)
    op.create_table('bid_announcements',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('bid_ntce_nm', mysql.VARCHAR(length=500), nullable=True),
    sa.Column('bid_ntce_no', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('bid_ntce_ord', mysql.VARCHAR(length=10), nullable=False),
    sa.Column('ntce_instt_nm', mysql.VARCHAR(length=200), nullable=True),
    sa.Column('dminstt_nm', mysql.VARCHAR(length=200), nullable=True),
    sa.Column('presmpt_prce', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('bid_ntce_dt', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('bid_clse_dt', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('openg_dt', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('ntce_kind_nm', mysql.VARCHAR(length=100), nullable=True),
    sa.Column('bid_methd_nm', mysql.VARCHAR(length=100), nullable=True),
    sa.Column('cntrct_mthd_nm', mysql.VARCHAR(length=100), nullable=True),
    sa.Column('category', mysql.VARCHAR(length=10), nullable=False),
    sa.Column('raw_data', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=True),
    sa.Column('collected_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('base_amount', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('bid_announcements_bid_ntce_dt_c42f1afb', 'bid_announcements', ['bid_ntce_dt'], unique=False)
    op.create_index('bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq', 'bid_announcements', ['bid_ntce_no', 'bid_ntce_ord', 'category'], unique=True)
    op.create_index('bid_announcements_category_02e9e006', 'bid_announcements', ['category'], unique=False)
    op.create_index('bid_announcements_dminstt_nm_952da702', 'bid_announcements', ['dminstt_nm'], unique=False)
    op.create_index('ix_bid_ann_collected', 'bid_announcements', ['collected_at'], unique=False)
    op.create_index('ix_bid_ann_dt_cat', 'bid_announcements', ['bid_ntce_dt', 'category'], unique=False)
    op.create_table('bid_dataset_summaries',
    sa.Column('dataset', mysql.VARCHAR(length=20), nullable=False),
    sa.Column('total_count', mysql.BIGINT(display_width=20), autoincrement=False, nullable=False),
    sa.Column('total_amount', mysql.DECIMAL(precision=30, scale=0), nullable=False),
    sa.Column('avg_rate', mysql.DECIMAL(precision=10, scale=4), nullable=True),
    sa.Column('source_latest_collected_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('rebuilt_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('dataset'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('bid_dataset_summaries_rebuilt_at_8d77f9db', 'bid_dataset_summaries', ['rebuilt_at'], unique=False)
    op.create_table('bid_results',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('bid_ntce_nm', mysql.VARCHAR(length=500), nullable=True),
    sa.Column('bid_ntce_no', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('bid_ntce_ord', mysql.VARCHAR(length=10), nullable=False),
    sa.Column('bidwinnr_nm', mysql.VARCHAR(length=200), nullable=True),
    sa.Column('sucsf_bid_amt', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('sucsf_bid_rate', mysql.DECIMAL(precision=10, scale=4), nullable=True),
    sa.Column('rl_openg_dt', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('dminstt_nm', mysql.VARCHAR(length=200), nullable=True),
    sa.Column('category', mysql.VARCHAR(length=10), nullable=False),
    sa.Column('raw_data', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=True),
    sa.Column('collected_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('bid_results_bid_ntce_no_bid_ntce_ord_category_94d04c58_uniq', 'bid_results', ['bid_ntce_no', 'bid_ntce_ord', 'category'], unique=True)
    op.create_index('bid_results_category_981358ae', 'bid_results', ['category'], unique=False)
    op.create_index('bid_results_collected_at_25a564b9', 'bid_results', ['collected_at'], unique=False)
    op.create_index('bid_results_dminstt_nm_1b809760', 'bid_results', ['dminstt_nm'], unique=False)
    op.create_index('bid_results_rl_openg_dt_00b70e7a', 'bid_results', ['rl_openg_dt'], unique=False)
    op.create_index('ix_bid_results_amt_id', 'bid_results', ['sucsf_bid_amt', 'id'], unique=False)
    op.create_index('ix_bid_results_bidwinnr_nm', 'bid_results', ['bidwinnr_nm'], unique=False)
    op.create_index('ix_bid_results_dt_cat', 'bid_results', ['rl_openg_dt', 'category'], unique=False)
    op.create_index('ix_bid_results_rate_id', 'bid_results', ['sucsf_bid_rate', 'id'], unique=False)
    op.create_table('knowledge_base_status',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('kb_version', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('status', mysql.VARCHAR(length=20), nullable=False),
    sa.Column('source_bid_count', mysql.INTEGER(display_width=10, unsigned=True), autoincrement=False, nullable=False),
    sa.Column('last_embedding_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('last_pipeline_run_id', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('notes', mysql.LONGTEXT(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('kb_version', 'knowledge_base_status', ['kb_version'], unique=True)
    op.create_table('pipeline_executions',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('execution_id', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('pipeline_name', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('run_mode', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('status', mysql.VARCHAR(length=20), nullable=False),
    sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('ended_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('metrics_json', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('logs_summary', mysql.LONGTEXT(), nullable=False),
    sa.Column('source', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('external_url', mysql.LONGTEXT(), nullable=False),
    sa.Column('raw_status_payload', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('stage_name', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('stage_status', mysql.VARCHAR(length=50), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('execution_id', 'pipeline_executions', ['execution_id'], unique=True)
    op.create_index('ix_pipe_exec_created', 'pipeline_executions', ['created_at'], unique=False)
    op.create_index('ix_pipe_exec_name_status', 'pipeline_executions', ['pipeline_name', 'status'], unique=False)
    op.create_index('pipeline_executions_pipeline_name_010b1479', 'pipeline_executions', ['pipeline_name'], unique=False)
    op.create_index('pipeline_executions_status_e7ec4919', 'pipeline_executions', ['status'], unique=False)
    op.create_table('prediction_results',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('bid_ntce_no', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('bid_ntce_ord', mysql.VARCHAR(length=10), nullable=False),
    sa.Column('user_input_price', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('model_version', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('predicted_lower_bound', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('predicted_upper_bound', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('predicted_optimal_price', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('confidence_score', mysql.DECIMAL(precision=5, scale=4), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_table('retrain_logs',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('trigger_source', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('champion_version', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('challenger_version', mysql.VARCHAR(length=50), nullable=False),
    sa.Column('status', mysql.VARCHAR(length=30), nullable=False),
    sa.Column('metrics_summary', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=True),
    sa.Column('created_at', mysql.DATETIME(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_table('automation_requests',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('request_id', sa.String(36), nullable=False),
    sa.Column('intent_type', mysql.VARCHAR(length=64), nullable=False),
    sa.Column('requested_text', mysql.LONGTEXT(), nullable=False),
    sa.Column('pipeline_name', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('status', mysql.VARCHAR(length=20), nullable=False),
    sa.Column('payload', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('harness_execution_id', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('result_summary', mysql.LONGTEXT(), nullable=False),
    sa.Column('error_message', mysql.LONGTEXT(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('user_id', mysql.BIGINT(display_width=20), autoincrement=False, nullable=False),
    sa.Column('action_key', mysql.VARCHAR(length=64), nullable=False),
    sa.Column('confirmed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('execution_url', mysql.LONGTEXT(), nullable=False),
    sa.Column('followup_query', mysql.LONGTEXT(), nullable=False),
    sa.Column('plan_execution_id', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('requires_confirmation', mysql.TINYINT(display_width=1), autoincrement=False, nullable=False),
    sa.Column('result_payload', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'], name='automation_requests_user_id_09027998_fk_accounts_customuser_id'),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('automation_requests_action_key_72546a52', 'automation_requests', ['action_key'], unique=False)
    op.create_index('automation_requests_created_at_1c714821', 'automation_requests', ['created_at'], unique=False)
    op.create_index('automation_requests_intent_type_72f08cf2', 'automation_requests', ['intent_type'], unique=False)
    op.create_index('automation_requests_plan_execution_id_4f401e5d', 'automation_requests', ['plan_execution_id'], unique=False)
    op.create_index('automation_requests_status_b21ae7da', 'automation_requests', ['status'], unique=False)
    op.create_index('ix_auto_req_action_created', 'automation_requests', ['action_key', 'created_at'], unique=False)
    op.create_index('ix_auto_req_intent_created', 'automation_requests', ['intent_type', 'created_at'], unique=False)
    op.create_index('ix_auto_req_user_status', 'automation_requests', ['user_id', 'status'], unique=False)
    op.create_index('request_id', 'automation_requests', ['request_id'], unique=True)
    op.create_table('automation_subscriptions',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('automation_type', mysql.VARCHAR(length=64), nullable=False),
    sa.Column('filter_json', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('schedule_cron', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=False),
    sa.Column('last_run_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('next_run_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('user_id', mysql.BIGINT(display_width=20), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'], name='automation_subscript_user_id_65841fc4_fk_accounts_'),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('automation_subscriptions_automation_type_64b4d3d1', 'automation_subscriptions', ['automation_type'], unique=False)
    op.create_index('automation_subscriptions_is_active_1dd49756', 'automation_subscriptions', ['is_active'], unique=False)
    op.create_index('ix_auto_sub_type', 'automation_subscriptions', ['automation_type'], unique=False)
    op.create_index('ix_auto_sub_user_active', 'automation_subscriptions', ['user_id', 'is_active'], unique=False)
    op.create_table('chat_session_states',
    sa.Column('id', mysql.BIGINT(display_width=20), autoincrement=True, nullable=False),
    sa.Column('session_key', mysql.VARCHAR(length=64), nullable=False),
    sa.Column('last_query', mysql.LONGTEXT(), nullable=False),
    sa.Column('last_plan_json', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('last_filters_json', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('last_result_summary', mysql.LONGTEXT(), nullable=False),
    sa.Column('last_chart_payload', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('last_result_payload', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('user_id', mysql.BIGINT(display_width=20), autoincrement=False, nullable=True),
    sa.Column('last_action_key', mysql.VARCHAR(length=64), nullable=False),
    sa.Column('last_job_id', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('last_kb_version', mysql.VARCHAR(length=100), nullable=False),
    sa.Column('last_response_mode', mysql.VARCHAR(length=20), nullable=False),
    sa.Column('chat_history_json', mysql.LONGTEXT(charset='utf8mb4', collation='utf8mb4_bin'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts_customuser.id'], name='chat_session_states_user_id_47adeb98_fk_accounts_customuser_id'),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_unicode_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('chat_session_states_updated_at_44284963', 'chat_session_states', ['updated_at'], unique=False)
    op.create_index('ix_chat_state_user_updated', 'chat_session_states', ['user_id', 'updated_at'], unique=False)
    op.create_index('session_key', 'chat_session_states', ['session_key'], unique=True)


def downgrade() -> None:
    op.drop_table('chat_session_states')
    op.drop_table('automation_subscriptions')
    op.drop_table('automation_requests')
    op.drop_table('retrain_logs')
    op.drop_table('prediction_results')
    op.drop_table('pipeline_executions')
    op.drop_table('knowledge_base_status')
    op.drop_table('bid_results')
    op.drop_table('bid_dataset_summaries')
    op.drop_table('bid_announcements')
    op.drop_table('accounts_customuser')
