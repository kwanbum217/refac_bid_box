"""적격심사 규칙 커버리지 원장 생성기.

최근 N개월 공고에 서비스의 실제 판정 함수(resolve_evaluation_rule_from_raw_data)를 그대로
돌려 수요기관별 적용 규칙(기관·지역·조달청 기본·차단)과 명세 상태, 원문 보관 여부를
data/reference/rule_coverage_ledger.yaml 로 남깁니다.

판정 로직은 여기서 새로 만들지 않습니다. evaluations.py 끝단과 같은 세 함수
(classify_contract_regime, institution_sido, resolve_evaluation_rule_from_raw_data)를
같은 인자로 부르기만 합니다. DB 는 READ ONLY 트랜잭션에서 SELECT 만 씁니다.

사용법:

    uv run python scripts/report_rule_coverage.py
    uv run python scripts/report_rule_coverage.py --months 12 --category Servc
    uv run python scripts/report_rule_coverage.py --method-code "" --min-announcements 5
    uv run python scripts/report_rule_coverage.py --check
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.demand_institutions import (  # noqa: E402
    classify_contract_regime,
    institution_sido,
    is_education_institution,
)
from src.app.services.evaluation_rules import (  # noqa: E402
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)

SCHEMA = "RULE_COVERAGE_LEDGER_V1"
GENERATED_BY = "scripts/report_rule_coverage.py"
DEFAULT_OUTPUT = "data/reference/rule_coverage_ledger.yaml"
INSTITUTION_RULES_PATH = "data/reference/institution_rules_20261013.yaml"
MANIFEST_PATH = "data/sources/qualification/manifest.json"

# 원장의 applied_scope 값. 규칙 객체의 institution_scope(ALL/INSTITUTION/REGION)를
# 그대로 쓰지 않고 ALL 만 PPS_DEFAULT 로 옮겨, 차단·오류까지 한 축에서 셉니다.
LEDGER_SCOPE_INSTITUTION = "INSTITUTION"
LEDGER_SCOPE_REGION = "REGION"
LEDGER_SCOPE_PPS_DEFAULT = "PPS_DEFAULT"
LEDGER_SCOPE_BLOCKED = "BLOCKED"
LEDGER_SCOPE_ERROR = "ERROR"
LEDGER_SCOPES: tuple[str, ...] = (
    LEDGER_SCOPE_INSTITUTION,
    LEDGER_SCOPE_REGION,
    LEDGER_SCOPE_PPS_DEFAULT,
    LEDGER_SCOPE_BLOCKED,
    LEDGER_SCOPE_ERROR,
)

# --check 는 재계산이 불가능한 값(generated_at)과 생성 시점에 따라 달라지는 값
# (조회 창), 사람이 채우는 값(investigation)을 구조 차이에서 뺍니다.
DIFF_IGNORED_TOKENS: tuple[str, ...] = (
    "generated_at",
    "window_from",
    "window_to",
    "investigation",
)

ANNOUNCEMENT_SQL = """
SELECT bid_ntce_no, bid_ntce_ord, category, dminstt_nm, cntrct_mthd_nm,
       presmpt_prce, raw_data
FROM bid_announcements
WHERE category = :category
  AND bid_ntce_dt >= :window_from
  AND bid_ntce_dt < :window_end
ORDER BY bid_ntce_no, category, bid_ntce_ord
"""

INSTITUTION_SQL = """
SELECT dminstt_cd, dminstt_nm, jrsdctn_div_nm, instt_ty_lrgclsfc_nm,
       instt_ty_midclsfc_nm, instt_ty_smlclsfc_nm, rgn_cd, rgn_nm,
       toplvl_instt_cd, toplvl_instt_nm
FROM g2b_demand_institutions
"""


@dataclass(frozen=True)
class ResolutionOutcome:
    """공고 한 건의 판정을 원장 축으로 정규화한 결과."""

    applied_scope: str
    rule_id: str | None = None
    region_name: str | None = None
    block_code: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class RegistryIndex:
    """명세 YAML 과 코드 규칙을 registry_status 판정용으로 뒤집은 색인."""

    by_name: dict[str, str] = field(default_factory=dict)
    by_rule_id: dict[str, str] = field(default_factory=dict)


def _ord_key(value: Any) -> int:
    """공고 차수를 최신 비교용 정수로 만듭니다. 숫자가 아니면 가장 낮게 둡니다."""
    text_value = str(value or "").strip()
    return int(text_value) if text_value.isdigit() else -1


def _months_ago(today: date, months: int) -> date:
    """N개월 전 같은 날짜. 그 달에 없는 일이면 그 달 마지막 날로 당깁니다."""
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _scope_for_rule(rule: Any) -> str:
    if rule.institution_scope == RULE_SCOPE_INSTITUTION:
        return LEDGER_SCOPE_INSTITUTION
    if rule.institution_scope == RULE_SCOPE_REGION:
        return LEDGER_SCOPE_REGION
    return LEDGER_SCOPE_PPS_DEFAULT


def classify_result(
    result: RuleResolutionResult | None, error_type: str | None = None
) -> ResolutionOutcome:
    """판정 결과 하나를 applied_scope 로 분류합니다.

    차단(is_blocked)이 규칙 범위보다 우선합니다. RULE_REGIME_MISMATCH 처럼 규칙이
    붙은 채로 차단되는 경로가 있어, 범위를 먼저 보면 차단 건이 기본 규칙으로 새어나갑니다.
    """
    if error_type is not None or result is None:
        return ResolutionOutcome(
            applied_scope=LEDGER_SCOPE_ERROR, error_type=error_type or "UnknownError"
        )
    if result.is_blocked:
        return ResolutionOutcome(
            applied_scope=LEDGER_SCOPE_BLOCKED, block_code=result.block_reason_code
        )
    rule = result.rule
    if rule is None:
        return ResolutionOutcome(
            applied_scope=LEDGER_SCOPE_BLOCKED,
            block_code=result.block_reason_code or "RULE_NOT_FOUND",
        )
    scope = _scope_for_rule(rule)
    region_name = rule.region_name or result.region_name if scope == LEDGER_SCOPE_REGION else None
    return ResolutionOutcome(applied_scope=scope, rule_id=rule.rule_id, region_name=region_name)


def _registry_status(
    scope_counts: Counter,
    inst_rule_ids: Counter,
    representative_name: str | None,
    registry_index: RegistryIndex,
) -> str:
    """기관의 registry_status. 적용된 기관 규칙이 있으면 명세 status, 없으면 명세 이름 일치."""
    if scope_counts.get(LEDGER_SCOPE_INSTITUTION):
        for rule_id, _count in inst_rule_ids.most_common():
            status = registry_index.by_rule_id.get(rule_id)
            if status:
                return status
    exact = registry_index.by_name.get((representative_name or "").strip())
    return exact or "unregistered"


def _split_scopes(counter: Counter) -> dict[str, int]:
    return {scope: counter[scope] for scope in LEDGER_SCOPES if counter[scope]}


def build_ledger(
    records: list[dict[str, Any]],
    *,
    filter_meta: dict[str, Any],
    min_announcements: int,
    generated_at: str,
    registry_index: RegistryIndex | None = None,
    manifest_sources_by_name: dict[str, list[dict[str, Any]]] | None = None,
    existing_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """공고별 레코드 목록을 커버리지 원장 dict 로 접습니다. DB 를 쓰지 않는 순수 함수입니다.

    레코드의 ``result`` 는 판정 함수 반환값(RuleResolutionResult)이고, ``error_type``
    이 있으면 판정 중 예외가 난 건입니다. 분류는 classify_result 가 전담합니다.
    """
    registry_index = registry_index or RegistryIndex()
    manifest_sources_by_name = manifest_sources_by_name or {}

    investigation_by_code: dict[str, Any] = {}
    for item in (existing_ledger or {}).get("institutions") or []:
        code = item.get("dminstt_cd")
        if code:
            investigation_by_code[str(code)] = item.get("investigation")

    scope_totals: Counter = Counter()
    region_acc: dict[str, dict[str, Any]] = {}
    institution_acc: dict[str, dict[str, Any]] = {}

    for record in records:
        outcome = classify_result(record.get("result"), record.get("error_type"))
        scope_totals[outcome.applied_scope] += 1

        if outcome.applied_scope == LEDGER_SCOPE_REGION:
            key = outcome.region_name or "(미상)"
            acc = region_acc.setdefault(key, {"rule_ids": Counter(), "announcements": 0})
            acc["announcements"] += 1
            if outcome.rule_id:
                acc["rule_ids"][outcome.rule_id] += 1
            continue

        code = str(record.get("dminstt_cd") or "")
        acc = institution_acc.setdefault(
            code,
            {
                "names": Counter(),
                "scope_counts": Counter(),
                "rule_ids": Counter(),
                "inst_rule_ids": Counter(),
                "block_codes": Counter(),
                "announcements": 0,
                "jurisdiction": None,
                "contract_regime": None,
            },
        )
        acc["announcements"] += 1
        name = record.get("dminstt_nm")
        if name:
            acc["names"][name] += 1
        acc["scope_counts"][outcome.applied_scope] += 1
        if outcome.rule_id:
            acc["rule_ids"][outcome.rule_id] += 1
            if outcome.applied_scope == LEDGER_SCOPE_INSTITUTION:
                acc["inst_rule_ids"][outcome.rule_id] += 1
        if outcome.applied_scope == LEDGER_SCOPE_BLOCKED and outcome.block_code:
            acc["block_codes"][outcome.block_code] += 1
        if outcome.applied_scope == LEDGER_SCOPE_ERROR:
            acc["block_codes"][outcome.error_type or "UnknownError"] += 1
        if acc["jurisdiction"] is None and record.get("jurisdiction"):
            acc["jurisdiction"] = record["jurisdiction"]
        if acc["contract_regime"] is None and record.get("contract_regime"):
            acc["contract_regime"] = record["contract_regime"]

    regions = [
        {
            "region_name": region_name,
            "rule_ids": [rule_id for rule_id, _count in acc["rule_ids"].most_common()],
            "announcements": acc["announcements"],
        }
        for region_name, acc in sorted(
            region_acc.items(), key=lambda item: (-item[1]["announcements"], item[0])
        )
    ]

    institutions: list[dict[str, Any]] = []
    tail_scope_counts: Counter = Counter()
    tail_institutions = 0
    tail_announcements = 0
    for code, acc in sorted(institution_acc.items()):
        if acc["announcements"] < min_announcements:
            tail_institutions += 1
            tail_announcements += acc["announcements"]
            tail_scope_counts.update(acc["scope_counts"])
            continue

        most_common_names = acc["names"].most_common()
        representative_name = most_common_names[0][0] if most_common_names else None
        variants = [name for name, _count in most_common_names if name != representative_name][:5]
        scope_counts = _split_scopes(acc["scope_counts"])

        applied_scope = None
        best_count = -1
        for scope in LEDGER_SCOPES:
            count = scope_counts.get(scope, 0)
            if count > best_count:
                best_count = count
                applied_scope = scope

        institutions.append(
            {
                "dminstt_cd": code,
                "dminstt_nm": representative_name,
                "name_variants": variants,
                "jurisdiction": acc["jurisdiction"],
                "contract_regime": acc["contract_regime"],
                "applied_scope": applied_scope,
                "scope_counts": scope_counts,
                "rule_ids": [rule_id for rule_id, _count in acc["rule_ids"].most_common(3)],
                "block_codes": dict(acc["block_codes"].most_common()),
                "announcements": acc["announcements"],
                "registry_status": _registry_status(
                    acc["scope_counts"], acc["inst_rule_ids"], representative_name, registry_index
                ),
                "manifest_sources": manifest_sources_by_name.get(representative_name or ""),
                "investigation": investigation_by_code.get(code),
            }
        )

    institutions.sort(key=lambda item: (-item["announcements"], item["dminstt_cd"]))

    total_announcements = sum(scope_totals.values())
    applied_scope_summary = {
        scope: {
            "announcements": scope_totals[scope],
            "ratio": round(scope_totals[scope] / total_announcements, 6)
            if total_announcements
            else 0.0,
        }
        for scope in LEDGER_SCOPES
    }

    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "generated_by": GENERATED_BY,
        "filter": filter_meta,
        "totals": {
            "announcements": total_announcements,
            "institutions": len(institutions) + tail_institutions,
            "applied_scope": applied_scope_summary,
        },
        "tail": {
            "institutions": tail_institutions,
            "announcements": tail_announcements,
            "applied_scope": _split_scopes(tail_scope_counts),
        },
        "regions": regions,
        "institutions": institutions,
    }


def _load_institutions(conn: Any) -> dict[str, dict[str, Any]]:
    rows = conn.execute(text(INSTITUTION_SQL)).mappings().all()
    return {str(row["dminstt_cd"]): dict(row) for row in rows}


def _as_dict(value: Any) -> dict[str, Any]:
    """raw SQL 로 읽은 JSON 컬럼을 dict 로 맞춥니다.

    text() 로 실행하면 SQLAlchemy 가 컬럼 타입을 모르므로 MySQL JSON 컬럼이 파이썬
    문자열로 돌아옵니다. 여기서 파싱해 판정 함수에 dict 를 넘깁니다.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _to_record(row: Any, institutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_data = _as_dict(row.raw_data)
    institution_code = str(raw_data.get("dminsttCd") or "").strip()
    institution = institutions.get(institution_code)
    regime = classify_contract_regime(institution)
    sido_code, sido_name = institution_sido(institution)
    try:
        result: RuleResolutionResult | None = resolve_evaluation_rule_from_raw_data(
            category=row.category,
            raw_data=raw_data,
            institution_name_fallback=row.dminstt_nm,
            cntrct_mthd_nm=row.cntrct_mthd_nm,
            institution_regime=regime,
            region_code=sido_code,
            region_name=sido_name,
            estimated_price=row.presmpt_prce,
            education_institution=is_education_institution(institution),
        )
        error_type = None
    except Exception as exc:  # 판정 실패는 ERROR 로 세고 예외 형식 이름만 남깁니다.
        result = None
        error_type = type(exc).__name__
    return {
        "dminstt_cd": institution_code,
        "dminstt_nm": row.dminstt_nm or raw_data.get("dminsttNm"),
        "jurisdiction": (institution or {}).get("jrsdctn_div_nm"),
        "contract_regime": regime,
        "result": result,
        "error_type": error_type,
    }


def collect_records(
    *,
    months: int,
    category: str,
    method_code: str,
    today: date | None = None,
    engine: Engine | None = None,
) -> list[dict[str, Any]]:
    """공고를 DB 에서 읽어 공고별 레코드 목록으로 만듭니다.

    기간과 업무구분으로 거른 뒤 낙찰방법 코드는 raw_data 에서 파이썬으로 거르고,
    같은 공고번호·업무구분의 최신 차수만 남깁니다. 세션을 READ ONLY 로 열어 SELECT 만 씁니다.
    """
    if engine is None:
        from src.app.core.db import engine as default_engine

        engine = default_engine

    window_to = today or date.today()
    window_from = _months_ago(window_to, months)
    window_end = window_to + timedelta(days=1)

    records: list[dict[str, Any]] = []
    with engine.connect() as conn:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        institutions = _load_institutions(conn)
        result = conn.execution_options(stream_results=True).execute(
            text(ANNOUNCEMENT_SQL),
            {
                "category": category,
                "window_from": datetime.combine(window_from, day_time.min),
                "window_end": datetime.combine(window_end, day_time.min),
            },
        )
        current_key: tuple[str, str] | None = None
        best_row: Any = None
        best_ord = -1
        for row in result:
            raw_data = _as_dict(row.raw_data)
            if method_code and str(raw_data.get("sucsfbidMthdCd") or "").strip() != method_code:
                continue
            key = (row.bid_ntce_no, row.category)
            if key != current_key:
                if best_row is not None:
                    records.append(_to_record(best_row, institutions))
                current_key = key
                best_row = None
                best_ord = -1
            ord_key = _ord_key(row.bid_ntce_ord)
            if best_row is None or ord_key > best_ord:
                best_row = row
                best_ord = ord_key
        if best_row is not None:
            records.append(_to_record(best_row, institutions))
    return records


def load_registry_index(path: str | Path = INSTITUTION_RULES_PATH) -> RegistryIndex:
    """명세 YAML 을 이름·별칭 → status, 코드 규칙 rule_id → status 색인으로 만듭니다."""
    from src.app.services.evaluation_rules import INSTITUTION_RULES

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    by_name: dict[str, str] = {}
    status_by_institution: dict[str, str] = {}
    for entry in payload.get("institutions") or []:
        institution_name = str(entry.get("institution_name") or "").strip()
        status = entry.get("status")
        if not institution_name or not status:
            continue
        status_by_institution[institution_name] = status
        for candidate in (institution_name, *(entry.get("name_aliases") or [])):
            name = str(candidate or "").strip()
            if name:
                by_name.setdefault(name, status)
    by_rule_id = {
        rule.rule_id: status_by_institution[rule.institution_name]
        for rule in INSTITUTION_RULES
        if rule.institution_name in status_by_institution
    }
    return RegistryIndex(by_name=by_name, by_rule_id=by_rule_id)


def load_manifest_sources(path: str | Path = MANIFEST_PATH) -> dict[str, list[dict[str, Any]]]:
    """manifest 의 표시명 → [{source: 약칭, files: 보관 파일 수}] 색인.

    manifest 의 institutions 는 약칭 → 표시명이고, files 의 institution 값은 표시명입니다.
    따라서 약칭의 파일 수는 표시명으로 집계합니다.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = Counter(
        str(item.get("institution"))
        for item in payload.get("files") or []
        if item.get("institution")
    )
    by_name: dict[str, list[dict[str, Any]]] = {}
    for abbreviation, display_name in (payload.get("institutions") or {}).items():
        display = str(display_name or "").strip()
        if not display:
            continue
        by_name.setdefault(display, []).append(
            {"source": str(abbreviation), "files": int(counts.get(display, 0))}
        )
    return by_name


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


def diff_ledgers(
    existing: dict[str, Any] | None, computed: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """두 원장의 구조·값 차이를 (경로, 기존, 계산) 목록으로 돌려줍니다.

    생성 시점 값과 사람이 채우는 값은 차이에서 뺍니다.
    """
    left = _flatten(existing or {})
    right = _flatten(computed)
    differences: list[tuple[str, Any, Any]] = []
    for key in sorted(set(left) | set(right)):
        if any(token in key for token in DIFF_IGNORED_TOKENS):
            continue
        if left.get(key) != right.get(key):
            differences.append((key, left.get(key), right.get(key)))
    return differences


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="적격심사 규칙 커버리지 원장 생성기")
    parser.add_argument("--months", type=int, default=12, help="조회 기간(개월, 기본 12)")
    parser.add_argument("--category", default="Servc", help="업무구분(기본 Servc)")
    parser.add_argument(
        "--method-code",
        default="낙030001",
        help="낙찰방법 코드. 빈 문자열이면 필터하지 않습니다.",
    )
    parser.add_argument(
        "--min-announcements", type=int, default=5, help="기관 개별 항목 최소 공고 수(기본 5)"
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="원장 출력 경로")
    parser.add_argument(
        "--check", action="store_true", help="파일을 쓰지 않고 기존 원장과 차이만 보고"
    )
    return parser.parse_args(argv)


def write_ledger(path: str | Path, ledger: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            ledger,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=4096,
        )


def _print_summary(ledger: dict[str, Any]) -> None:
    totals = ledger["totals"]
    print(f"공고 {totals['announcements']}건, 기관 {totals['institutions']}곳")
    for scope, summary in totals["applied_scope"].items():
        print(f"  {scope}: {summary['announcements']}건 ({summary['ratio']})")
    unregistered = [
        item for item in ledger["institutions"] if item["registry_status"] == "unregistered"
    ][:10]
    if unregistered:
        print("미등록 상위 기관:")
        for item in unregistered:
            print(
                f"  {item['dminstt_cd']} {item['dminstt_nm']} "
                f"({item['announcements']}건, {item['applied_scope']})"
            )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)
    existing: dict[str, Any] | None = None
    if output.exists():
        existing = yaml.safe_load(output.read_text(encoding="utf-8"))

    today = date.today()
    filter_meta = {
        "months": args.months,
        "category": args.category,
        "method_code": args.method_code,
        "window_from": _months_ago(today, args.months).isoformat(),
        "window_to": today.isoformat(),
        "min_announcements": args.min_announcements,
    }
    records = collect_records(
        months=args.months, category=args.category, method_code=args.method_code, today=today
    )
    ledger = build_ledger(
        records,
        filter_meta=filter_meta,
        min_announcements=args.min_announcements,
        generated_at=today.isoformat(),
        registry_index=load_registry_index(),
        manifest_sources_by_name=load_manifest_sources(),
        existing_ledger=existing,
    )

    if args.check:
        differences = diff_ledgers(existing, ledger)
        print(f"[check] 기존 원장: {output} ({'있음' if existing else '없음'})")
        print(f"[check] 차이 {len(differences)}건")
        for key, before, after in differences[:50]:
            print(f"  - {key}: {before!r} -> {after!r}")
        return 0

    write_ledger(output, ledger)
    print(f"원장을 썼습니다: {output}")
    _print_summary(ledger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
