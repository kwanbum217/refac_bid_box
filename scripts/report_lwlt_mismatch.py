"""공고 낙찰하한율과 적용 규칙 하한율의 불일치 진단 지표 생성기.

공고 원문의 낙찰하한율(sucsfbidLwltRate)과 서비스가 고른 규칙의 하한율을 소수
3자리로 비교해, 규칙 ID·판본(시행일)별 불일치율을
data/reference/lwlt_mismatch_metrics.yaml 로 남깁니다.

이 스크립트는 진단 전용입니다. 평가·추천 계산 경로를 부르기만 하고 고치지 않으며,
공고 하한율이 있으면 그것이 우선한다는 현행 동작도 그대로 둡니다. 따라서 여기의
불일치는 점수 계산 오류가 아니라 규칙 선택·규칙 기본값·폴백 경로의 정합성을 보는
값입니다.

모집단은 scripts/report_rule_coverage.py 의 조회 SQL·판정 함수·최신 차수 규칙을
그대로 재사용합니다. 공고값과 규칙값을 함께 보려면 원본 행이 필요해, 그 스크립트의
collect_records 와 같은 순서로 행을 모으되 행과 raw_data 를 함께 남깁니다. DB 는
READ ONLY 트랜잭션에서 SELECT 만 씁니다.

사용법:

    uv run python scripts/report_lwlt_mismatch.py
    uv run python scripts/report_lwlt_mismatch.py --months 12 --category Servc
    uv run python scripts/report_lwlt_mismatch.py --method-code 낙030001
    uv run python scripts/report_lwlt_mismatch.py --check
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import report_rule_coverage as coverage  # noqa: E402
from src.app.services.evaluation_rules import (  # noqa: E402
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    _band_lwlt_rate,
    _normalized_price,
)

SCHEMA = "LWLT_MISMATCH_METRICS_V1"
GENERATED_BY = "scripts/report_lwlt_mismatch.py"
DEFAULT_OUTPUT = "data/reference/lwlt_mismatch_metrics.yaml"

SCOPE_REGION = "REGION"
SCOPE_ALL = "ALL"
SCOPE_INSTITUTION = "INSTITUTION"
SCOPES: tuple[str, ...] = (SCOPE_REGION, SCOPE_ALL, SCOPE_INSTITUTION)

MATCH = "match"
MISMATCH = "mismatch"
NOT_COMPARABLE = "not_comparable"

MIN_RULE_MISMATCH = 5
TOP_DIFF_LIMIT = 3

# --check 는 생성 시점 값과 조회 창을 구조 차이에서 뺍니다.
DIFF_IGNORED_KEYS: tuple[str, ...] = (
    "generated_at",
    "window.from",
    "window.to",
)


@dataclass(frozen=True)
class RateSample:
    """공고 한 건의 비교 재료. 규칙이 적용된 공고만 이 객체가 됩니다."""

    rule_id: str
    edition: str
    scope: str
    notice_rate: Decimal | None
    rule_rate: Decimal | None
    declared_rate: Decimal | None


def _q3(value: Decimal) -> Decimal:
    """소수 3자리로 맞춥니다. 감사 문서 부록 A 의 비교 방식과 같습니다."""
    return value.quantize(Decimal("0.001"))


def parse_rate(value: Any) -> Decimal | None:
    """하한율 입력을 Decimal 로 바꿉니다. 빈 값·숫자가 아니면 None 입니다."""
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return Decimal(text_value)
    except (ArithmeticError, TypeError, ValueError):
        return None


def rule_scope(rule: Any) -> str:
    """규칙 객체의 institution_scope 를 지표 축으로 옮깁니다."""
    if rule.institution_scope == RULE_SCOPE_REGION:
        return SCOPE_REGION
    if rule.institution_scope == RULE_SCOPE_INSTITUTION:
        return SCOPE_INSTITUTION
    return SCOPE_ALL


def rule_lwlt_rate(rule: Any, estimated_price: Decimal | None) -> Decimal | None:
    """규칙이 이 공고에 선언하는 하한율.

    구간 인쇄값이 있으면 그 구간값을, 없으면 규칙 대표값을 씁니다. 추정가격을 몰라
    구간을 고르지 못한 경우도 대표값으로 대체합니다(감사 문서 부록 B.3 한계 1).
    """
    band_rate, _label, _reason = _band_lwlt_rate(rule, estimated_price)
    if band_rate is not None:
        return band_rate
    return rule.lwlt_rate


def rate_diff(sample: RateSample) -> Decimal | None:
    """공고값 - 규칙값(소수 3자리). 비교할 수 없으면 None 입니다."""
    if sample.rule_rate is None or sample.notice_rate is None or sample.notice_rate <= 0:
        return None
    return _q3(sample.notice_rate) - _q3(sample.rule_rate)


def classify(sample: RateSample) -> str:
    """비교 결과를 일치·불일치·비교 불가로 나눕니다."""
    diff = rate_diff(sample)
    if diff is None:
        return NOT_COMPARABLE
    return MATCH if diff == 0 else MISMATCH


def _summary(samples: list[RateSample]) -> dict[str, Any]:
    """표본 목록의 규칙 적용·비교 가능·일치·불일치·불일치율."""
    compared = 0
    matched = 0
    mismatched = 0
    for sample in samples:
        diff = rate_diff(sample)
        if diff is None:
            continue
        compared += 1
        if diff == 0:
            matched += 1
        else:
            mismatched += 1
    return {
        "rule_applied": len(samples),
        "compared": compared,
        "match": matched,
        "mismatch": mismatched,
        "mismatch_ratio": round(mismatched / compared, 6) if compared else 0.0,
    }


def _top_diffs(samples: list[RateSample], limit: int) -> list[dict[str, Any]]:
    """불일치 차이값 상위 limit 개. 건수 내림차순, 같으면 차이값 오름차순입니다."""
    diffs: Counter[Decimal] = Counter()
    for sample in samples:
        diff = rate_diff(sample)
        if diff is not None and diff != 0:
            diffs[diff] += 1
    ranked = sorted(diffs.items(), key=lambda item: (-item[1], item[0]))
    return [{"diff": float(diff), "count": count} for diff, count in ranked[:limit]]


def _by_rule(
    samples: list[RateSample], *, min_mismatch: int, top_limit: int
) -> dict[str, dict[str, Any]]:
    """규칙 ID·판본별 집계. 불일치 min_mismatch 건 이상인 규칙만 남깁니다."""
    groups: dict[str, list[RateSample]] = {}
    for sample in samples:
        groups.setdefault(sample.rule_id, []).append(sample)

    entries: list[tuple[str, dict[str, Any]]] = []
    for rule_id, group in groups.items():
        summary = _summary(group)
        if summary["mismatch"] < min_mismatch:
            continue
        first = group[0]
        entries.append(
            (
                rule_id,
                {
                    "rule_id": rule_id,
                    "edition": first.edition,
                    "scope": first.scope,
                    "declared_rate": str(first.declared_rate)
                    if first.declared_rate is not None
                    else None,
                    "rule_applied": summary["rule_applied"],
                    "compared": summary["compared"],
                    "match": summary["match"],
                    "mismatch": summary["mismatch"],
                    "mismatch_ratio": summary["mismatch_ratio"],
                    "top_diffs": _top_diffs(group, top_limit),
                },
            )
        )
    entries.sort(key=lambda item: (-item[1]["mismatch"], item[0]))
    return dict(entries)


def build_metrics(
    samples: list[RateSample],
    *,
    window: dict[str, str],
    generated_at: str,
    min_rule_mismatch: int = MIN_RULE_MISMATCH,
    top_diff_limit: int = TOP_DIFF_LIMIT,
) -> dict[str, Any]:
    """비교 표본 목록을 지표 dict 로 접습니다. DB 를 쓰지 않는 순수 함수입니다."""
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "generated_by": GENERATED_BY,
        "window": window,
        "totals": _summary(samples),
        "by_scope": {
            scope: _summary([sample for sample in samples if sample.scope == scope])
            for scope in SCOPES
        },
        "by_rule": _by_rule(samples, min_mismatch=min_rule_mismatch, top_limit=top_diff_limit),
    }


def _to_sample(row: Any, record: dict[str, Any]) -> RateSample | None:
    """공고 한 건을 비교 표본으로 바꿉니다. 규칙 미적용·차단·오류는 None 입니다."""
    result = record.get("result")
    if result is None or result.is_blocked or result.rule is None:
        return None
    rule = result.rule
    raw_data = coverage._as_dict(row.raw_data)
    return RateSample(
        rule_id=rule.rule_id,
        edition=rule.effective_date,
        scope=rule_scope(rule),
        notice_rate=parse_rate(raw_data.get("sucsfbidLwltRate")),
        rule_rate=rule_lwlt_rate(rule, _normalized_price(row.presmpt_prce)),
        declared_rate=rule.lwlt_rate,
    )


def collect_samples(
    *,
    months: int,
    category: str,
    method_code: str,
    today: date | None = None,
    engine: Engine | None = None,
) -> list[RateSample]:
    """공고를 DB 에서 읽어 비교 표본 목록으로 만듭니다.

    조회 창·최신 차수 선정·판정 함수는 scripts/report_rule_coverage.py 의
    collect_records 와 같습니다. 비교에 필요한 원본 하한율과 추정가격을 함께
    보려고 행을 직접 들고 있습니다. 세션은 READ ONLY 로 열어 SELECT 만 씁니다.
    """
    if engine is None:
        from src.app.core.db import engine as default_engine

        engine = default_engine

    window_to = today or date.today()
    window_from = coverage._months_ago(window_to, months)
    window_end = window_to + timedelta(days=1)

    samples: list[RateSample] = []
    with engine.connect() as conn:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        institutions = coverage._load_institutions(conn)
        result = conn.execution_options(stream_results=True).execute(
            text(coverage.ANNOUNCEMENT_SQL),
            {
                "category": category,
                "window_from": datetime.combine(window_from, day_time.min),
                "window_end": datetime.combine(window_end, day_time.min),
            },
        )
        current_key: tuple[str, str] | None = None
        best_row: Any = None
        best_ord = -1
        best_rows: list[Any] = []
        for row in result:
            raw_data = coverage._as_dict(row.raw_data)
            if method_code and str(raw_data.get("sucsfbidMthdCd") or "").strip() != method_code:
                continue
            key = (row.bid_ntce_no, row.category)
            if key != current_key:
                if best_row is not None:
                    best_rows.append(best_row)
                current_key = key
                best_row = None
                best_ord = -1
            ord_key = coverage._ord_key(row.bid_ntce_ord)
            if best_row is None or ord_key > best_ord:
                best_row = row
                best_ord = ord_key
        if best_row is not None:
            best_rows.append(best_row)
        result.close()
        regimes = coverage.lookup_attachment_regimes(
            conn, (coverage.attachment_regime_key(row) for row in best_rows)
        )

    for row in best_rows:
        record = coverage._to_record(
            row, institutions, regimes.get(coverage.attachment_regime_key(row))
        )
        sample = _to_sample(row, record)
        if sample is not None:
            samples.append(sample)
    return samples


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(node, dict):
        flat: dict[str, Any] = {}
        for key, value in node.items():
            flat.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    if isinstance(node, list):
        flat = {}
        for index, value in enumerate(node):
            flat.update(_flatten(value, f"{prefix}[{index}]"))
        return flat
    return {prefix: node}


def diff_metrics(
    existing: dict[str, Any] | None, computed: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """두 지표의 구조·값 차이를 (경로, 기존, 계산) 목록으로 돌려줍니다."""
    left = _flatten(existing or {})
    right = _flatten(computed)
    differences: list[tuple[str, Any, Any]] = []
    for key in sorted(set(left) | set(right)):
        if key in DIFF_IGNORED_KEYS:
            continue
        if left.get(key) != right.get(key):
            differences.append((key, left.get(key), right.get(key)))
    return differences


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="낙찰하한율 불일치 진단 지표 생성기")
    parser.add_argument("--months", type=int, default=12, help="조회 기간(개월, 기본 12)")
    parser.add_argument("--category", default="Servc", help="업무구분(기본 Servc)")
    parser.add_argument(
        "--method-code",
        default="",
        help="낙찰방법 코드. 빈 문자열이면 필터하지 않습니다(기본).",
    )
    parser.add_argument(
        "--min-rule-mismatch",
        type=int,
        default=MIN_RULE_MISMATCH,
        help="by_rule 최소 불일치 건수(기본 5)",
    )
    parser.add_argument(
        "--output",
        "--out",
        dest="output",
        default=DEFAULT_OUTPUT,
        help="지표 출력 경로",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="기준일 YYYY-MM-DD. 없으면 --check 는 기존 지표의 window.to, 그 외는 오늘",
    )
    parser.add_argument(
        "--check", action="store_true", help="파일을 쓰지 않고 기존 지표와 차이만 보고"
    )
    return parser.parse_args(argv)


def write_metrics(path: str | Path, metrics: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            metrics,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=4096,
        )


def _print_summary(metrics: dict[str, Any]) -> None:
    totals = metrics["totals"]
    print(
        f"규칙 적용 {totals['rule_applied']}건, 비교 가능 {totals['compared']}건, "
        f"일치 {totals['match']}건, 불일치 {totals['mismatch']}건 "
        f"({totals['mismatch_ratio']})"
    )
    for scope, summary in metrics["by_scope"].items():
        print(
            f"  {scope}: 적용 {summary['rule_applied']}건, 비교 {summary['compared']}건, "
            f"불일치 {summary['mismatch']}건 ({summary['mismatch_ratio']})"
        )
    for rule_id, entry in list(metrics["by_rule"].items())[:10]:
        print(
            f"  {rule_id} ({entry['edition']}): 불일치 {entry['mismatch']}건 / "
            f"비교 {entry['compared']}건 ({entry['mismatch_ratio']})"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)
    existing: dict[str, Any] | None = None
    if output.exists():
        existing = yaml.safe_load(output.read_text(encoding="utf-8"))

    today = coverage.resolve_as_of(
        args.as_of,
        ((existing or {}).get("window") or {}).get("to"),
        check=args.check,
    )
    window = {"from": coverage._months_ago(today, args.months).isoformat(), "to": today.isoformat()}
    samples = collect_samples(
        months=args.months,
        category=args.category,
        method_code=args.method_code,
        today=today,
    )
    metrics = build_metrics(
        samples,
        window=window,
        generated_at=today.isoformat(),
        min_rule_mismatch=args.min_rule_mismatch,
    )

    if args.check:
        differences = diff_metrics(existing, metrics)
        print(f"[check] 기존 지표: {output} ({'있음' if existing else '없음'})")
        print(f"[check] 차이 {len(differences)}건")
        for key, before, after in differences[:50]:
            print(f"  - {key}: {before!r} -> {after!r}")
        return 1 if differences else 0

    write_metrics(output, metrics)
    print(f"지표를 썼습니다: {output}")
    _print_summary(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
