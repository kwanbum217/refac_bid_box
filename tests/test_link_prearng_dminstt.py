"""link_prearng_dminstt 조인 키 검증. 운영 DB 에 연결하지 않는다."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    name = "link_prearng_dminstt"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "link_prearng_dminstt.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


link = _load_module()


ANNOUNCEMENTS = [
    ("R25BK01250632", "000", "Servc", "조달청"),
    ("R25BK01250632", "001", "Servc", "조달청"),
    ("R25BK01250632", "002", "Servc", None),
    ("R25BK09999999", "000", "Cnstwk", "한국도로공사"),
]


def test_normalize_ord_zero_pads_to_three_digits():
    assert link.normalize_ord("1") == "001"
    assert link.normalize_ord("10") == "010"
    assert link.normalize_ord("001") == "001"
    assert link.normalize_ord("000") == "000"


def test_normalize_ord_handles_blank_and_none():
    assert link.normalize_ord(None) == "000"
    assert link.normalize_ord("") == "000"
    assert link.normalize_ord("   ") == "000"


@pytest.mark.parametrize("raw", [" 002 ", "2", "002"])
def test_match_rows_ignores_ord_padding(raw):
    summary = link.match_rows([("R25BK01250632", raw, "Servc")], ANNOUNCEMENTS)
    assert summary.total == 1
    assert summary.matched == 1


def test_match_rows_requires_notice_number():
    summary = link.match_rows([("R25BK00000000", "000", "Servc")], ANNOUNCEMENTS)
    assert summary.matched == 0
    assert summary.unmatched == 1


def test_match_rows_requires_category():
    summary = link.match_rows([("R25BK01250632", "000", "Thng")], ANNOUNCEMENTS)
    assert summary.matched == 0


def test_match_rows_counts_unmatched_and_rate():
    keys = [
        ("R25BK01250632", "000", "Servc"),
        ("R25BK01250632", "001", "Servc"),
        ("R25BK01250632", "003", "Servc"),
        ("R25BK00000000", "000", "Servc"),
    ]
    summary = link.match_rows(keys, ANNOUNCEMENTS)
    assert summary.total == 4
    assert summary.matched == 2
    assert summary.unmatched == 2
    assert summary.match_rate == pytest.approx(50.0)


def test_match_rows_usable_requires_institution_name():
    summary = link.match_rows([("R25BK01250632", "002", "Servc")], ANNOUNCEMENTS)
    assert summary.matched == 1
    assert summary.usable == 0


def test_match_rows_empty_is_safe():
    summary = link.match_rows([], ANNOUNCEMENTS)
    assert summary.total == 0
    assert summary.unmatched == 0
    assert summary.match_rate == 0.0
