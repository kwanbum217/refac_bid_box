"""
tests/test_compare_host_container_db.py

호스트-컨테이너 DB 비교 스크립트의 종료 코드 판정을 검증합니다.

이 스크립트는 G1 검증 도구입니다. 차이를 화면에 출력하면서도 항상 0 을
반환하면 자동화가 DB 불일치를 통과로 읽습니다. 과거에 같은 종류의 무조건
통과가 데이터 유실을 놓친 적이 있습니다.
"""

from __future__ import annotations

import pandas as pd

from scripts.compare_host_container_db import verdict_exit_code


def test_exit_code_zero_only_when_both_empty():
    """행 수와 스키마가 모두 같을 때만 통과입니다."""
    assert verdict_exit_code(pd.DataFrame(), pd.DataFrame()) == 0


def test_row_count_difference_fails():
    """행 수 차이는 데이터 유실 신호이므로 통과가 아닙니다."""
    row_diff = pd.DataFrame(
        {"table": ["bid_results"], "rows_host": [1000], "rows_container": [999]}
    )
    assert verdict_exit_code(row_diff, pd.DataFrame()) == 1


def test_schema_mismatch_fails():
    """스키마 차이는 행 수가 같아도 통과가 아닙니다."""
    schema_mismatch = pd.DataFrame({"COLUMN_NAME": ["base_amount"], "COLUMN_TYPE_host": ["bigint"]})
    assert verdict_exit_code(pd.DataFrame(), schema_mismatch) == 1


def test_both_differences_fail():
    """두 차이가 겹쳐도 1 입니다."""
    frame = pd.DataFrame({"x": [1]})
    assert verdict_exit_code(frame, frame) == 1
