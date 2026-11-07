"""규칙 커버리지 원장 취소공고 제외 시험 (DB 없이).

같은 공고번호·업무구분의 최신 차수가 취소공고면 집계에서 빼고, 이전 차수만 취소공고인
공고는 최신 차수를 그대로 집계하며, 제외 건수가 totals.excluded_cancelled 에 남는지
고정 입력으로 검사합니다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import report_rule_coverage as ledger_script


def _row(bid_ntce_no: str, ord_: str, kind: str, category: str = "Servc") -> SimpleNamespace:
    return SimpleNamespace(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=ord_,
        category=category,
        raw_data=json.dumps({"ntceKindNm": kind}, ensure_ascii=False),
    )


def test_is_cancelled_notice_reads_ntce_kind_nm() -> None:
    assert ledger_script.is_cancelled_notice(_row("R1", "000", "취소공고"))
    assert not ledger_script.is_cancelled_notice(_row("R1", "000", "등록공고"))
    assert not ledger_script.is_cancelled_notice(_row("R1", "000", "재공고"))
    assert not ledger_script.is_cancelled_notice(_row("R1", "000", "변경공고"))


def test_latest_cancelled_notice_is_excluded() -> None:
    """(a) 최신 차수가 취소공고면 그 공고번호를 집계에서 뺀다."""
    rows = [
        _row("R1", "000", "등록공고"),
        _row("R1", "001", "취소공고"),
        _row("R2", "000", "등록공고"),
    ]
    latest, excluded = ledger_script.split_by_latest_order(rows)

    assert [row.bid_ntce_no for row in latest] == ["R2"]
    assert [(row.bid_ntce_no, row.bid_ntce_ord) for row in excluded] == [("R1", "001")]


def test_earlier_cancelled_notice_keeps_latest_notice() -> None:
    """(b) 이전 차수만 취소공고고 최신 차수가 정상 공고면 최신 차수를 집계한다."""
    rows = [
        _row("R1", "000", "취소공고"),
        _row("R1", "001", "등록공고"),
    ]
    latest, excluded = ledger_script.split_by_latest_order(rows)

    assert [(row.bid_ntce_no, row.bid_ntce_ord) for row in latest] == [("R1", "001")]
    assert excluded == []


def test_reannouncement_and_change_notice_are_not_excluded() -> None:
    rows = [
        _row("R1", "001", "재공고"),
        _row("R2", "001", "변경공고"),
    ]
    latest, excluded = ledger_script.split_by_latest_order(rows)

    assert [row.bid_ntce_no for row in latest] == ["R1", "R2"]
    assert excluded == []


def test_same_bid_number_in_other_category_is_a_separate_key() -> None:
    rows = [
        _row("R1", "001", "취소공고", category="Servc"),
        _row("R1", "001", "등록공고", category="Cnstwk"),
    ]
    latest, excluded = ledger_script.split_by_latest_order(rows)

    assert [(row.bid_ntce_no, row.category) for row in latest] == [("R1", "Cnstwk")]
    assert [(row.bid_ntce_no, row.category) for row in excluded] == [("R1", "Servc")]


def test_totals_record_excluded_cancelled() -> None:
    """(c) 제외 건수가 totals.excluded_cancelled 에 기록된다."""
    ledger = ledger_script.build_ledger(
        [],
        filter_meta={"months": 12},
        min_announcements=1,
        generated_at="2026-11-07",
        excluded_cancelled=3,
    )

    assert ledger["totals"]["excluded_cancelled"] == 3
    assert ledger["totals"]["announcements"] == 0
    assert sum(item["announcements"] for item in ledger["totals"]["applied_scope"].values()) == 0


def test_totals_default_excluded_cancelled_is_zero() -> None:
    ledger = ledger_script.build_ledger(
        [], filter_meta={}, min_announcements=1, generated_at="2026-11-07"
    )

    assert ledger["totals"]["excluded_cancelled"] == 0
