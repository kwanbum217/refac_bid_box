#!/usr/bin/env python3
"""
scripts/backtest_qualification_rules.py

일반용역 적격심사 정량평가 규칙 백테스트 CLI (읽기 전용).

공고일 구간([from, to) 반열림)을 받아 규칙 판별 결과와 실제 낙찰 결과를 대조해
G3 보고서 docs/analysis/servc_qualification_backtest_baseline_20260929.md 4장의
A1~A4 지표를 전체와 rule_id(별표) 별로 산출한다.

- A1 판별 분포: 규칙 판별 차단 코드별 건수와 정량평가 가능 비율
- A2 하한율 일치: 별표 기본 하한율과 공고 하한율의 일치율
- A3 하한 실효성: 결과가 매칭된 공고 중 낙찰률이 실효 하한율 이상인 비율
- A4 프리미엄: 낙찰률 - 실효 하한율 차이의 분포(중앙, 사분위, p10, p90)

표본은 구간 안 적격심사 공고(sucsfbidMthdNm 이 '적격심사%', 취소공고 제외)에서
공고번호별 최대 정규화 차수 행 하나를 대표로 삼는다. 공고와 결과 매칭 키는
(공고번호, category, 정규화 차수)이며 정규화는 result_coverage.normalize_ord 다.

지표 집계는 DB 없이 입력 목록만 받는 compute_metrics 로 분리해 단위 테스트한다.
DB 조회부는 src.app.core.db.SessionLocal 로 읽기만 하며 어떤 행도 쓰지 않는다.

실행:
    uv run python scripts/backtest_qualification_rules.py \
        --from 2026-05-26 --to 2026-09-29 --format json
    uv run python scripts/backtest_qualification_rules.py \
        --from 2025-01-01 --to 2026-01-01 --category Servc --limit 500
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402
from src.app.services.bid_queries import is_qualification_analyzable  # noqa: E402
from src.app.services.evaluation_rules import (  # noqa: E402
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.result_coverage import (  # noqa: E402
    CANCELLED_NTCE_KIND,
    normalize_ord,
)

DEFAULT_CATEGORY = "Servc"
QUALIFICATION_METHOD_PREFIX = "적격심사"
RULE_UNKNOWN = "UNKNOWN"
BLOCK_UNKNOWN = "UNKNOWN"
RESULT_QUERY_CHUNK = 500
PERCENT_QUANTUM = Decimal("0.0001")
GAP_QUANTUM = Decimal("0.0001")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal(100)).quantize(PERCENT_QUANTUM)


def is_qualification_method(raw_data: Any) -> bool:
    """공고 낙찰방법이 적격심사 계열인지 판정한다 (sucsfbidMthdNm LIKE '적격심사%')."""
    if not isinstance(raw_data, dict):
        return False
    method = str(raw_data.get("sucsfbidMthdNm") or "").strip()
    return method.startswith(QUALIFICATION_METHOD_PREFIX)


def is_cancelled_kind(ntce_kind_nm: Any) -> bool:
    """공고종류명이 취소공고인지 판정한다."""
    return str(ntce_kind_nm or "").strip() == CANCELLED_NTCE_KIND


def _ord_key(announcement: BidAnnouncement) -> str:
    return normalize_ord(announcement.bid_ntce_ord)


def select_representatives(
    announcements: Sequence[BidAnnouncement],
) -> list[BidAnnouncement]:
    """적격심사 공고 행에서 공고번호별 최대 정규화 차수 행 하나를 대표로 고른다.

    취소공고 행은 먼저 제외한다. 취소 차수가 최대여도 원 공고 행이 남아야 하기
    때문이다. 반환 순서는 (공고번호, 정규화 차수) 오름차순으로 고정해 표본 상한과
    텍스트 출력이 실행마다 같은 순서를 유지하게 한다.
    """
    best: dict[str, BidAnnouncement] = {}
    for announcement in announcements:
        if is_cancelled_kind(announcement.ntce_kind_nm):
            continue
        current = best.get(announcement.bid_ntce_no)
        if current is None or _ord_key(announcement) > _ord_key(current):
            best[announcement.bid_ntce_no] = announcement
    return sorted(best.values(), key=lambda item: (item.bid_ntce_no, _ord_key(item)))


@dataclass(frozen=True)
class AnnouncementSelection:
    """대표 공고 선정 결과와 선정 과정의 집계."""

    representatives: list[BidAnnouncement]
    announcement_rows: int
    cancelled_excluded_rows: int
    notices: int


@dataclass(frozen=True)
class AnalyzedBid:
    """지표 집계에 쓰는 정량평가 가능 공고 한 건의 계산 입력."""

    rule_id: str
    rule_lwlt_rate: Decimal | None
    announcement_lwlt_rate: Decimal | None
    effective_lwlt_rate: Decimal | None
    matched: bool
    winning_rate: Decimal | None


def _count_block(bids: Sequence[AnalyzedBid]) -> dict[str, int]:
    return {
        "analyzed": len(bids),
        "matched": sum(1 for bid in bids if bid.matched),
        "matched_with_rate": sum(1 for bid in bids if bid.matched and bid.winning_rate is not None),
    }


def _a2_block(bids: Sequence[AnalyzedBid]) -> dict[str, Any]:
    """하한율 일치 지표 한 묶음. 별표 기본값이 없거나 0 이면 비교 불가로 뺀다."""
    compared = 0
    equal = 0
    not_equal = 0
    missing_announcement_rate = 0
    rule_default_zero = 0
    for bid in bids:
        if bid.rule_lwlt_rate is None or bid.rule_lwlt_rate <= 0:
            rule_default_zero += 1
            continue
        if bid.announcement_lwlt_rate is None:
            missing_announcement_rate += 1
            continue
        compared += 1
        if bid.announcement_lwlt_rate == bid.rule_lwlt_rate:
            equal += 1
        else:
            not_equal += 1
    return {
        "compared": compared,
        "equal": equal,
        "not_equal": not_equal,
        "missing_announcement_rate": missing_announcement_rate,
        "rule_default_zero": rule_default_zero,
        "equal_rate_pct": _pct(equal, compared),
    }


def _a2_dual_block(bids: Sequence[AnalyzedBid]) -> dict[str, Any]:
    """A2 를 분석가능 전체와 결과매칭 부분집합 두 기준으로 함께 낸다.

    G3 4장 정의는 모집단 전체 비율이지만 5장 실측값(95.34%)은 결과가 매칭된
    행에서 잰 값이다. 두 기준을 함께 실어 어느 쪽과도 대조할 수 있게 한다.
    """
    return {
        "unit": "percent",
        "matched": _a2_block([bid for bid in bids if bid.matched]),
        "analyzed": _a2_block(bids),
    }


def _a3_block(bids: Sequence[AnalyzedBid]) -> dict[str, Any]:
    """낙찰률이 실효 하한율 이상인 비율. 미매칭 공고는 분모에서 뺀다."""
    denominator = 0
    above = 0
    below = 0
    for bid in bids:
        if not bid.matched or bid.winning_rate is None or bid.effective_lwlt_rate is None:
            continue
        denominator += 1
        if bid.winning_rate >= bid.effective_lwlt_rate:
            above += 1
        else:
            below += 1
    return {
        "denominator": denominator,
        "above": above,
        "below": below,
        "above_rate_pct": _pct(above, denominator),
    }


def _quantile(values: Sequence[Decimal], p: float) -> Decimal:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(p * (len(ordered) - 1)))
    return ordered[index]


def _a4_block(bids: Sequence[AnalyzedBid]) -> dict[str, Any]:
    """낙찰률 - 실효 하한율 차이의 분포. 미매칭 공고는 분모에서 뺀다."""
    gaps: list[Decimal] = []
    for bid in bids:
        if not bid.matched or bid.winning_rate is None or bid.effective_lwlt_rate is None:
            continue
        gaps.append((bid.winning_rate - bid.effective_lwlt_rate).quantize(GAP_QUANTUM))
    if not gaps:
        return {
            "count": 0,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(gaps),
        "median": _quantile(gaps, 0.5),
        "p10": _quantile(gaps, 0.1),
        "p25": _quantile(gaps, 0.25),
        "p75": _quantile(gaps, 0.75),
        "p90": _quantile(gaps, 0.9),
        "min": min(gaps),
        "max": max(gaps),
    }


def compute_metrics(
    blocked_reason_codes: Sequence[str],
    analyzed_bids: Sequence[AnalyzedBid],
) -> dict[str, Any]:
    """차단 코드 목록과 정량평가 가능 목록만으로 A1~A4 지표를 집계한다 (DB 불필요).

    A1 은 판별 대상(대표) 대비 차단 코드별 건수와 정량평가 가능 비율이다.
    A2 는 별표 기본 하한율과 공고 하한율의 일치율로, 매칭 부분집합과 분석가능
    전체 두 기준을 함께 낸다. A3·A4 는 결과가 매칭된 공고만 분모로 쓴다.
    """
    blocked_count = len(blocked_reason_codes)
    analyzable = len(analyzed_bids)
    checked = blocked_count + analyzable
    by_code = Counter(blocked_reason_codes)

    grouped: dict[str, list[AnalyzedBid]] = defaultdict(list)
    for bid in analyzed_bids:
        grouped[bid.rule_id].append(bid)
    by_rule = {
        rule_id: {
            "counts": _count_block(grouped[rule_id]),
            "a2_lwlt_match": _a2_dual_block(grouped[rule_id]),
            "a3_rate_above_lwlt": _a3_block(grouped[rule_id]),
            "a4_rate_gap": _a4_block(grouped[rule_id]),
        }
        for rule_id in sorted(grouped)
    }

    return {
        "a1_distribution": {
            "blocked_by_code": dict(sorted(by_code.items())),
            "blocked": blocked_count,
            "analyzable": analyzable,
            "checked": checked,
            "blocked_rate_pct": _pct(blocked_count, checked),
            "analyzable_rate_pct": _pct(analyzable, checked),
        },
        "a2_lwlt_match": _a2_dual_block(analyzed_bids),
        "a3_rate_above_lwlt": _a3_block(analyzed_bids),
        "a4_rate_gap": _a4_block(analyzed_bids),
        "by_rule": by_rule,
        "counts": _count_block(analyzed_bids),
    }


def _announcement_stmt(window_from: date, window_to: date, category: str):
    return (
        select(BidAnnouncement)
        .where(
            BidAnnouncement.category == category,
            BidAnnouncement.bid_ntce_dt.is_not(None),
            BidAnnouncement.bid_ntce_dt
            >= datetime(window_from.year, window_from.month, window_from.day),
            BidAnnouncement.bid_ntce_dt < datetime(window_to.year, window_to.month, window_to.day),
        )
        .order_by(BidAnnouncement.bid_ntce_no, BidAnnouncement.bid_ntce_ord)
    )


def load_representative_announcements(
    db: Session,
    *,
    window_from: date,
    window_to: date,
    category: str,
    limit: int | None = None,
) -> AnnouncementSelection:
    """구간 안 적격심사 공고에서 공고번호별 최대 차수 대표를 읽는다 (읽기 전용)."""
    rows = list(db.execute(_announcement_stmt(window_from, window_to, category)).scalars().all())
    qualified = [row for row in rows if is_qualification_method(row.raw_data)]
    cancelled_excluded = sum(1 for row in qualified if is_cancelled_kind(row.ntce_kind_nm))
    representatives = select_representatives(qualified)
    if limit is not None:
        representatives = representatives[:limit]
    notices = len({row.bid_ntce_no for row in qualified if not is_cancelled_kind(row.ntce_kind_nm)})
    return AnnouncementSelection(
        representatives=representatives,
        announcement_rows=len(qualified),
        cancelled_excluded_rows=cancelled_excluded,
        notices=notices,
    )


def _chunked(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def load_results(
    db: Session,
    *,
    category: str,
    notice_numbers: Sequence[str],
) -> dict[tuple[str, str], Decimal | None]:
    """공고번호 집합의 낙찰결과를 (공고번호, 정규화 차수) 키로 읽는다 (읽기 전용).

    결과 차수는 2자리로 내려오므로 normalize_ord 로 3자리로 맞춰 공고 차수와
    같은 키 공간에서 만난다.
    """
    results: dict[tuple[str, str], Decimal | None] = {}
    for chunk in _chunked(sorted(set(notice_numbers)), RESULT_QUERY_CHUNK):
        stmt = select(
            BidResult.bid_ntce_no,
            BidResult.bid_ntce_ord,
            BidResult.sucsf_bid_rate,
        ).where(
            BidResult.category == category,
            BidResult.bid_ntce_no.in_(chunk),
        )
        for bid_ntce_no, bid_ntce_ord, rate in db.execute(stmt).all():
            results[(bid_ntce_no, normalize_ord(bid_ntce_ord))] = _to_decimal(rate)
    return results


def build_analyzed_bids(
    representatives: Sequence[BidAnnouncement],
    results: dict[tuple[str, str], Decimal | None],
    *,
    category: str,
) -> tuple[list[str], list[AnalyzedBid], int]:
    """대표 공고를 규칙 판별해 차단 코드 목록과 정량평가 가능 입력을 만든다.

    반환은 (차단 코드 목록, 정량평가 가능 목록, 예정가격 기준액 미보유 건수)다.
    판정은 규칙 판별(resolve_evaluation_rule_from_raw_data)과 정량평가 가능
    판정(is_qualification_analyzable) 두 정본 함수에만 위임한다.
    """
    blocked: list[str] = []
    analyzed: list[AnalyzedBid] = []
    pred_non_positive = 0
    for announcement in representatives:
        raw_data = announcement.raw_data if isinstance(announcement.raw_data, dict) else {}
        resolution = resolve_evaluation_rule_from_raw_data(category=category, raw_data=raw_data)
        if resolution.is_blocked:
            blocked.append(resolution.block_reason_code or BLOCK_UNKNOWN)
            continue
        if not is_qualification_analyzable(announcement):
            pred_non_positive += 1
            continue
        rule = resolution.rule
        key = (announcement.bid_ntce_no, normalize_ord(announcement.bid_ntce_ord))
        matched = key in results
        analyzed.append(
            AnalyzedBid(
                rule_id=rule.rule_id if rule is not None else RULE_UNKNOWN,
                rule_lwlt_rate=rule.lwlt_rate if rule is not None else None,
                announcement_lwlt_rate=_to_decimal(raw_data.get("sucsfbidLwltRate")),
                effective_lwlt_rate=resolution.effective_lwlt_rate,
                matched=matched,
                winning_rate=results[key] if matched else None,
            )
        )
    return blocked, analyzed, pred_non_positive


def _to_primitive(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_primitive(item) for item in value]
    return value


def _fmt(value: Any, signed: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:+.4f}" if signed else f"{value:.4f}"
    return str(value)


def _render_a1(a1: dict[str, Any]) -> list[str]:
    lines = [
        f"A1 판별: 정량평가 가능 {a1['analyzable']:,} ({_fmt(a1['analyzable_rate_pct'])}%), "
        f"차단 {a1['blocked']:,} ({_fmt(a1['blocked_rate_pct'])}%), 대상 {a1['checked']:,}"
    ]
    for code, count in a1["blocked_by_code"].items():
        lines.append(f"    {code}: {count:,}")
    return lines


def _render_a2(a2: dict[str, Any]) -> list[str]:
    matched = a2["matched"]
    analyzed = a2["analyzed"]
    return [
        f"A2 하한율 일치 (매칭 기준): {matched['equal']:,}/{matched['compared']:,} "
        f"({_fmt(matched['equal_rate_pct'])}%)"
        f"  결측 {matched['missing_announcement_rate']:,}, 별표기본0 {matched['rule_default_zero']:,}",
        f"   분석가능 전체 기준: {analyzed['equal']:,}/{analyzed['compared']:,} "
        f"({_fmt(analyzed['equal_rate_pct'])}%)",
    ]


def _render_a3(a3: dict[str, Any]) -> list[str]:
    return [
        f"A3 낙찰률 >= 실효 하한율: {a3['above']:,}/{a3['denominator']:,} "
        f"({_fmt(a3['above_rate_pct'])}%)"
    ]


def _render_a4(a4: dict[str, Any]) -> list[str]:
    return [
        f"A4 프리미엄(%p): n={a4['count']:,} 중앙 {_fmt(a4['median'], True)} "
        f"p10 {_fmt(a4['p10'], True)} p25 {_fmt(a4['p25'], True)} "
        f"p75 {_fmt(a4['p75'], True)} p90 {_fmt(a4['p90'], True)} "
        f"min {_fmt(a4['min'], True)} max {_fmt(a4['max'], True)}"
    ]


def render_text(payload: dict[str, Any]) -> str:
    window = payload["window"]
    counts = payload["counts"]
    lines = [
        f"구간: {window['from']} ~ {window['to']} (반열림), 분류: {window['category']}",
        f"수집: 적격심사 {counts['announcement_rows']:,}행 / {counts['notices']:,}건, "
        f"취소 제외 {counts['cancelled_excluded_rows']:,}행, 대표 {counts['representatives']:,}건, "
        f"예정가격 기준액 미보유 {counts['pred_non_positive']:,}건",
        "",
    ]
    lines += _render_a1(payload["a1_distribution"])
    lines += _render_a2(payload["a2_lwlt_match"])
    lines += _render_a3(payload["a3_rate_above_lwlt"])
    lines += _render_a4(payload["a4_rate_gap"])
    lines += ["", "규칙(별표)별:"]
    lines.append(
        f"  {'rule_id':<44}{'대상':>7}{'매칭':>7}{'A2 일치':>10}{'A3 이상':>10}{'A4 중앙':>12}"
    )
    for rule_id, block in payload["by_rule"].items():
        rule_counts = block["counts"]
        a2 = block["a2_lwlt_match"]["matched"]
        a3 = block["a3_rate_above_lwlt"]
        a4 = block["a4_rate_gap"]
        lines.append(
            f"  {rule_id:<44}{rule_counts['analyzed']:>7,}{rule_counts['matched']:>7,}"
            f"{_fmt(a2['equal_rate_pct']):>10}{_fmt(a3['above_rate_pct']):>10}"
            f"{_fmt(a4['median'], True):>12}"
        )
    return "\n".join(lines)


def build_payload(
    *,
    window_from: date,
    window_to: date,
    category: str,
    selection: AnnouncementSelection,
    blocked: Sequence[str],
    analyzed: Sequence[AnalyzedBid],
    pred_non_positive: int,
    limit: int | None,
) -> dict[str, Any]:
    metrics = compute_metrics(blocked, analyzed)
    metrics["counts"].update(
        {
            "announcement_rows": selection.announcement_rows,
            "cancelled_excluded_rows": selection.cancelled_excluded_rows,
            "notices": selection.notices,
            "representatives": len(selection.representatives),
            "pred_non_positive": pred_non_positive,
            "limit_applied": limit is not None
            and selection.notices > len(selection.representatives),
        }
    )
    return {
        "window": {
            "from": window_from.isoformat(),
            "to": window_to.isoformat(),
            "category": category,
        },
        "counts": metrics["counts"],
        "a1_distribution": metrics["a1_distribution"],
        "a2_lwlt_match": metrics["a2_lwlt_match"],
        "a3_rate_above_lwlt": metrics["a3_rate_above_lwlt"],
        "a4_rate_gap": metrics["a4_rate_gap"],
        "by_rule": metrics["by_rule"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="적격심사 정량평가 규칙 백테스트 (읽기 전용)")
    parser.add_argument(
        "--from",
        dest="date_from",
        type=date.fromisoformat,
        required=True,
        help="공고일 시작 YYYY-MM-DD (포함)",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        type=date.fromisoformat,
        required=True,
        help="공고일 끝 YYYY-MM-DD (미포함)",
    )
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="업무구분 (기본 Servc)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default=None, help="결과를 저장할 파일 경로 (선택)")
    parser.add_argument("--limit", type=int, default=None, help="개발용 대표 표본 상한 (선택)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.date_to <= args.date_from:
        sys.stderr.write("오류: --to 는 --from 보다 뒤여야 합니다.\n")
        return 2
    if args.limit is not None and args.limit < 1:
        sys.stderr.write("오류: --limit 은 1 이상이어야 합니다.\n")
        return 2

    db = SessionLocal()
    try:
        selection = load_representative_announcements(
            db,
            window_from=args.date_from,
            window_to=args.date_to,
            category=args.category,
            limit=args.limit,
        )
        results = load_results(
            db,
            category=args.category,
            notice_numbers=[row.bid_ntce_no for row in selection.representatives],
        )
    finally:
        db.close()

    blocked, analyzed, pred_non_positive = build_analyzed_bids(
        selection.representatives, results, category=args.category
    )
    payload = build_payload(
        window_from=args.date_from,
        window_to=args.date_to,
        category=args.category,
        selection=selection,
        blocked=blocked,
        analyzed=analyzed,
        pred_non_positive=pred_non_positive,
        limit=args.limit,
    )

    if args.format == "json":
        rendered = json.dumps(_to_primitive(payload), ensure_ascii=False, indent=2)
    else:
        rendered = render_text(payload)

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
