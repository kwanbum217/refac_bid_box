"""
tests/test_backtest_qualification_rules.py

scripts/backtest_qualification_rules.py 의 순수 계산부(A1~A4)와 DB 조회부 계약을 검증한다.
DB 조회부는 SQLite 인메모리 픽스처로 공고·결과 차수 정규화 조인을 확인한다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from scripts.backtest_qualification_rules import (
    AnalyzedBid,
    build_analyzed_bids,
    compute_metrics,
    load_representative_announcements,
    load_results,
    select_representatives,
)
from src.app.models.bids import BidAnnouncement, BidResult


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _bid(
    *,
    rule_id: str = "R",
    rule_lwlt: str | None = "90",
    ann_lwlt: str | None = "90",
    effective: str | None = "90",
    matched: bool = True,
    winning_rate: str | None = None,
) -> AnalyzedBid:
    return AnalyzedBid(
        rule_id=rule_id,
        rule_lwlt_rate=_dec(rule_lwlt),
        announcement_lwlt_rate=_dec(ann_lwlt),
        effective_lwlt_rate=_dec(effective),
        matched=matched,
        winning_rate=_dec(winning_rate),
    )


def _announcement(
    *,
    bid_ntce_no: str,
    bid_ntce_ord: str,
    ntce_kind_nm: str | None = None,
) -> Any:
    return SimpleNamespace(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        ntce_kind_nm=ntce_kind_nm,
    )


def test_blocked_reason_codes_are_aggregated() -> None:
    metrics = compute_metrics(["MANUAL_EVALUATION", "MANUAL_EVALUATION", "RULE_NOT_FOUND"], [])

    a1 = metrics["a1_distribution"]
    assert a1["blocked_by_code"] == {"MANUAL_EVALUATION": 2, "RULE_NOT_FOUND": 1}
    assert a1["blocked"] == 3
    assert a1["analyzable"] == 0
    assert a1["checked"] == 3
    assert a1["blocked_rate_pct"] == Decimal("100.0000")


def test_a2_equal_not_equal_and_missing() -> None:
    bids = [
        _bid(ann_lwlt="90"),
        _bid(ann_lwlt="89"),
        _bid(ann_lwlt=None),
    ]

    a2 = compute_metrics([], bids)["a2_lwlt_match"]["matched"]
    assert a2["compared"] == 2
    assert a2["equal"] == 1
    assert a2["not_equal"] == 1
    assert a2["missing_announcement_rate"] == 1
    assert a2["equal_rate_pct"] == Decimal("50.0000")


def test_a2_rule_default_zero_is_excluded() -> None:
    bids = [_bid(rule_lwlt="0", ann_lwlt="90")]

    a2 = compute_metrics([], bids)["a2_lwlt_match"]["matched"]
    assert a2["rule_default_zero"] == 1
    assert a2["compared"] == 0
    assert a2["equal_rate_pct"] is None


def test_a3_boundary_equal_counts_as_above() -> None:
    bids = [
        _bid(effective="90", winning_rate="90"),
        _bid(effective="90", winning_rate="89.9999"),
    ]

    a3 = compute_metrics([], bids)["a3_rate_above_lwlt"]
    assert a3["denominator"] == 2
    assert a3["above"] == 1
    assert a3["below"] == 1
    assert a3["above_rate_pct"] == Decimal("50.0000")


def test_unmatched_bids_are_excluded_from_a3_and_a4() -> None:
    bids = [
        _bid(effective="90", winning_rate="90.1"),
        _bid(matched=False, winning_rate=None),
    ]

    metrics = compute_metrics([], bids)
    assert metrics["a3_rate_above_lwlt"]["denominator"] == 1
    assert metrics["a4_rate_gap"]["count"] == 1


def test_a4_reports_median_and_quantiles() -> None:
    bids = [
        _bid(effective="90", winning_rate="90.0"),
        _bid(effective="90", winning_rate="91.0"),
        _bid(effective="90", winning_rate="92.0"),
    ]

    a4 = compute_metrics([], bids)["a4_rate_gap"]
    assert a4["count"] == 3
    assert a4["min"] == Decimal("0.0000")
    assert a4["max"] == Decimal("2.0000")
    assert a4["median"] == Decimal("1.0000")


def test_by_rule_splits_metrics_by_rule_id() -> None:
    bids = [
        _bid(rule_id="A", ann_lwlt="90", effective="90", winning_rate="90"),
        _bid(rule_id="A", ann_lwlt="89", effective="90", winning_rate="90"),
        _bid(rule_id="B", rule_lwlt="80", ann_lwlt="80", effective="80", winning_rate="80"),
    ]

    by_rule = compute_metrics([], bids)["by_rule"]
    assert set(by_rule) == {"A", "B"}
    assert by_rule["A"]["a2_lwlt_match"]["matched"]["equal_rate_pct"] == Decimal("50.0000")
    assert by_rule["B"]["a2_lwlt_match"]["matched"]["equal_rate_pct"] == Decimal("100.0000")
    assert by_rule["A"]["counts"]["matched"] == 2


def test_select_representatives_picks_max_normalized_ord() -> None:
    rows = [
        _announcement(bid_ntce_no="A", bid_ntce_ord="000"),
        _announcement(bid_ntce_no="A", bid_ntce_ord="2"),
        _announcement(bid_ntce_no="B", bid_ntce_ord="01"),
        _announcement(bid_ntce_no="C", bid_ntce_ord="000", ntce_kind_nm="취소공고"),
    ]

    selected = select_representatives(rows)
    assert [(row.bid_ntce_no, row.bid_ntce_ord) for row in selected] == [("A", "2"), ("B", "01")]


def test_db_join_uses_normalized_ord(isolated_db: Session) -> None:
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="A1",
            bid_ntce_ord="000",
            category="Servc",
            bid_ntce_dt=datetime(2026, 6, 1, 10, 0),
            raw_data={
                "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
                "sucsfbidLwltRate": "87.745",
                "asignBdgtAmt": "100000000",
            },
        )
    )
    isolated_db.add(
        BidResult(
            bid_ntce_no="A1",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_rate=Decimal("88.0000"),
            rl_openg_dt=datetime(2026, 6, 10, 10, 0),
            raw_data={},
        )
    )
    isolated_db.commit()

    selection = load_representative_announcements(
        isolated_db,
        window_from=date(2026, 5, 26),
        window_to=date(2026, 9, 29),
        category="Servc",
    )
    assert len(selection.representatives) == 1

    results = load_results(isolated_db, category="Servc", notice_numbers=["A1"])
    assert results[("A1", "000")] == Decimal("88.0000")

    blocked, analyzed, pred_non_positive = build_analyzed_bids(
        selection.representatives, results, category="Servc"
    )
    assert blocked == []
    assert pred_non_positive == 0
    assert len(analyzed) == 1
    assert analyzed[0].matched is True
    assert analyzed[0].winning_rate == Decimal("88.0000")
