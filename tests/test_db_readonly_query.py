"""읽기 전용 질의 실행기의 안전 계약을 고정합니다.

2026-09-01 에 조사 워커가 DB 질의마다 사람 승인을 기다리며 멈췄습니다. 손으로
조립한 `docker exec ... mysql` 은 형태가 조금만 달라져도 자동 승인 화이트리스트를
벗어나고, 쓰기를 막을 보장도 없습니다. 이 실행기가 그 두 문제를 닫습니다.

**검사는 문자열 분석이라 완전하지 않습니다.** 그래서 실행 경로는 READ ONLY
트랜잭션을 함께 씁니다. 이 파일은 파서 계층의 계약만 검증합니다.
"""

from __future__ import annotations

import pytest

from scripts.db_readonly_query import UnsafeQueryError, assert_read_only, strip_sql_noise


class TestReadOnlyAccepts:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "select count(*) from bid_results",
            "SHOW TABLES",
            "EXPLAIN SELECT id FROM bid_results",
            "DESC bid_results",
            "DESCRIBE bid_results",
            "WITH t AS (SELECT 1 AS a) SELECT a FROM t",
        ],
    )
    def test_read_only_statements_pass(self, sql):
        assert assert_read_only(sql)

    def test_trailing_semicolon_is_stripped(self):
        assert assert_read_only("SELECT 1;") == "SELECT 1"

    def test_literal_containing_forbidden_word_is_allowed(self):
        """문자열 리터럴 안의 금지어로 정상 질의를 막으면 안 됩니다."""
        assert assert_read_only("SELECT id FROM t WHERE name = 'update log'")

    def test_comment_containing_forbidden_word_is_allowed(self):
        assert assert_read_only("SELECT 1 -- drop table 주의")


class TestReadOnlyRejects:
    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE bid_results SET id=1",
            "DELETE FROM bid_results",
            "INSERT INTO t VALUES (1)",
            "DROP TABLE t",
            "ALTER TABLE t ADD COLUMN c INT",
            "TRUNCATE TABLE t",
            "GRANT ALL ON *.* TO 'x'",
        ],
    )
    def test_write_statements_are_rejected(self, sql):
        with pytest.raises(UnsafeQueryError):
            assert_read_only(sql)

    def test_multi_statement_is_rejected(self):
        """세미콜론으로 이어 붙인 우회를 막아야 합니다."""
        with pytest.raises(UnsafeQueryError) as exc:
            assert_read_only("SELECT 1; DROP TABLE t")
        assert "한 번에 한 문장" in str(exc.value)

    def test_select_into_outfile_is_rejected(self):
        """SELECT 로 시작해도 파일 쓰기는 막아야 합니다."""
        with pytest.raises(UnsafeQueryError) as exc:
            assert_read_only("SELECT * INTO OUTFILE '/tmp/x' FROM t")
        assert "INTO" in str(exc.value).upper()

    def test_comment_hidden_write_is_rejected(self):
        """주석으로 시작 토큰을 가린 뒤 쓰기를 넣는 우회를 막아야 합니다."""
        with pytest.raises(UnsafeQueryError):
            assert_read_only("SELECT 1 /* ok */ UNION SELECT 1 INTO OUTFILE '/tmp/x'")

    def test_empty_statement_is_rejected(self):
        with pytest.raises(UnsafeQueryError):
            assert_read_only("   ;  ")

    def test_set_session_is_rejected(self):
        """세션 설정 변경도 읽기 전용이 아닙니다."""
        with pytest.raises(UnsafeQueryError):
            assert_read_only("SET SESSION sql_mode=''")


class TestStripSqlNoise:
    def test_block_comment_removed(self):
        assert "drop" not in strip_sql_noise("SELECT 1 /* drop */").lower()

    def test_line_comment_removed(self):
        assert "delete" not in strip_sql_noise("SELECT 1 -- delete\nFROM t").lower()

    def test_hash_comment_removed(self):
        assert "insert" not in strip_sql_noise("SELECT 1 # insert").lower()

    def test_single_quoted_literal_removed(self):
        assert "update" not in strip_sql_noise("SELECT 'update'").lower()

    def test_double_quoted_literal_removed(self):
        assert "alter" not in strip_sql_noise('SELECT "alter"').lower()


class TestReadOnlyFunctionTokens:
    """문장 키워드와 이름이 겹치는 읽기 전용 함수는 함수 형태일 때만 통과합니다."""

    def test_replace_function_is_allowed(self):
        sql = "SELECT REPLACE(bid_ntce_nm, ',', '') FROM bid_announcements"
        assert assert_read_only(sql) == sql

    def test_replace_function_with_space_before_paren_is_allowed(self):
        sql = "SELECT REPLACE (bid_ntce_nm, ',', '') FROM bid_announcements"
        assert assert_read_only(sql) == sql

    def test_nested_replace_in_cast_is_allowed(self):
        sql = (
            "SELECT CAST(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.bdgtAmt')), ',', '') "
            "AS DECIMAL(30,0)) FROM bid_announcements"
        )
        assert assert_read_only(sql) == sql

    def test_replace_statement_is_still_rejected(self):
        with pytest.raises(UnsafeQueryError):
            assert_read_only("REPLACE INTO bid_announcements (id) VALUES (1)")

    def test_replace_without_paren_is_still_rejected(self):
        with pytest.raises(UnsafeQueryError):
            assert_read_only("SELECT 1 FROM t WHERE 1=1 REPLACE bid_announcements SET id = 1")

    def test_other_write_keywords_are_not_exempted_by_paren(self):
        with pytest.raises(UnsafeQueryError):
            assert_read_only("SELECT 1 FROM t WHERE id IN (SELECT 1) DELETE (x)")
