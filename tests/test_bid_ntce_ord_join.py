"""
tests/test_bid_ntce_ord_join.py

공고와 낙찰을 잇는 차수 키 정규화를 검증합니다.

G2B 는 같은 차수를 공고 API 에서 3자리(`000`), 낙찰 API 에서 2자리(`00`) 로
내려줍니다. 정규화 없이 문자열로 이으면 조인이 거의 전부 실패합니다.
2026-08-03 운영 DB 실측에서 물품 조인율이 3.40% 였고, 차수를 맞추자
99.91% 가 되었습니다. 조인 실패는 예외를 내지 않고 표본만 조용히 사라집니다.
"""

import pytest

from src.app.models.bids import normalize_bid_ntce_ord
from src.app.services.kb_builder import _join_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00", "000"),
        ("000", "000"),
        ("01", "001"),
        ("001", "001"),
        ("10", "010"),
        ("100", "100"),
        (" 02 ", "002"),
        (0, "000"),
        (None, "000"),
        ("", "000"),
        # 4자리 이상은 뒤 3자리를 남깁니다. 원본 컬럼이 3자리 기준입니다.
        ("0012", "012"),
    ],
)
def test_normalize_bid_ntce_ord(raw, expected):
    assert normalize_bid_ntce_ord(raw) == expected


class _Row:
    def __init__(self, no, ord_, category):
        self.bid_ntce_no = no
        self.bid_ntce_ord = ord_
        self.category = category


@pytest.mark.parametrize("result_ord", ["00", "000"])
def test_join_key_matches_across_ord_widths(result_ord):
    """낙찰 차수가 2자리로 오든 3자리로 오든 공고와 같은 키가 나와야 합니다."""
    announcement = _Row("R26BK01633457", "000", "Thng")
    result = _Row("R26BK01633457", result_ord, "Thng")
    assert _join_key(announcement) == _join_key(result)


def test_join_key_separates_categories():
    """같은 공고번호라도 카테고리가 다르면 다른 건입니다."""
    assert _join_key(_Row("R26BK01633457", "000", "Thng")) != _join_key(
        _Row("R26BK01633457", "000", "Cnstwk")
    )


def test_join_key_separates_orders():
    """차수가 실제로 다르면 이어지면 안 됩니다."""
    assert _join_key(_Row("R26BK01633457", "000", "Thng")) != _join_key(
        _Row("R26BK01633457", "001", "Thng")
    )
