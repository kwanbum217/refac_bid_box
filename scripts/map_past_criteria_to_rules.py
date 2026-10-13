"""과거(2015~2024) 용역 공고의 기준명을 evaluation_rules 기존 규칙에 대응시켜 본다.

배경
----
과거 공고는 `sucsfbidMthdNm` 이 전부 `공고서참조` 자리표시자이고 첨부에 적격심사
별표가 없어 B·k 를 못 뽑는 경우가 많다. 다만 `scripts/pilot_past_notice_method_extract.py`
가 첨부 본문에서 **기준명**(예: `시설분야용역 적격심사`)을 뽑아낸 공고가 248건 있다.

이 스크립트는 그 기준명과 공고일·추정가격·수요기관을 `src/app/services/evaluation_rules.py`
의 기존 규칙(조달청 PRE/POST, LOCAL, 기관)에 대응시켜 B·k·통과점수(T)·낙찰하한율을
채울 수 있는지 **실측**한다. 운영 코드는 고치지 않으며 규칙 레지스트리를 읽기만 한다.

대응 절차
--------
1. 기준명을 용역 세부유형 집합으로 정규화한다(`_service_types_from_criteria`).
2. 규칙 후보를 운영과 같은 우선순위(기관 > 시·도(LOCAL) > 조달청)로 고른다.
3. **공고일보다 늦게 시행된 규칙은 후보에서 제외한다**(미래 규칙 금지).
4. 같은 유형의 후보가 여럿이면 추정가격 구간으로 하나를 확정한다.
5. 확정 규칙에 `resolve_score_params` 를 적용해 B·k·T 를, 구간 하한율로 낙찰하한율을 구한다.

산출 CSV 의 각 행은 재계산 가능하도록 대응 결과와 사유를 모두 담는다. 검증 집합은
별표에서 실제로 B·k 를 뽑은 공고이며, 대응 결과가 그 값과 일치하는지 함께 집계한다.

사용 예:
    uv run python scripts/map_past_criteria_to_rules.py \\
        --sample .cache/past_notice_pilot/sample_raw.json \\
        --pilot-results .cache/past_notice_pilot/sample_extract_results.csv \\
        --out-csv .cache/past_notice_pilot/criteria_rule_map.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services import evaluation_rules as er  # noqa: E402
from src.ml.notice_amount import notice_amount_for_year  # noqa: E402

_WHITESPACE_RE = re.compile(r"\s+")

# 기준명 표기 변형 -> 규칙 레지스트리 용역 세부유형 집합.
# 조달청 규칙과 LOCAL·기관 규칙이 같은 용역을 다른 코드로 표현하므로 집합으로 둔다.
_CRITERIA_SERVICE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("시설분야용역", ("FACILITY",)),
    ("시설분야", ("FACILITY",)),
    ("보험용역", ("INSURANCE",)),
    ("여객육상운송용역", ("PASSENGER_TRANSPORT", "LAND_TRANSPORT", "LAND_TRANSPORT_SME")),
    ("화물육상운송용역", ("FREIGHT", "LAND_TRANSPORT", "LAND_TRANSPORT_SME")),
    ("해양환경관리용역", ("FISHERY_CLEANUP",)),
    ("소프트웨어용역", ("SW_NON_SME", "SW_SME", "SW")),
    ("학술연구용역", ("ACADEMIC",)),
    ("폐기물처리용역", ("WASTE", "WASTE_HOUSEHOLD")),
    ("수리점검용역", ("REPAIR_INSPECTION",)),
    ("수리ㆍ점검용역", ("REPAIR_INSPECTION",)),
    ("임대차", ("LEASE",)),
    ("수요기관지정형", ("DEMAND_AGENCY",)),
    ("기술용역", ("TECH",)),
    ("일반용역", ("GENERAL",)),
    ("청소용역", ("SIMPLE_LABOR",)),
    ("경비용역", ("SIMPLE_LABOR",)),
    ("시설물경비용역", ("SIMPLE_LABOR",)),
    ("시설물관리용역", ("SIMPLE_LABOR",)),
    ("단순노무용역", ("SIMPLE_LABOR",)),
)

# 조달청 규칙 원문 표기에서 읽는 추정가격 경계. 기관·LOCAL 규칙은 price_bands 로 판정한다.
_E5EOK = Decimal("500000000")
_E2EOK = Decimal("200000000")
_E15EOK = Decimal("1500000000")
_E30EOK = Decimal("3000000000")


def _norm(text: str | None) -> str:
    return _WHITESPACE_RE.sub("", text or "")


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _service_types_from_criteria(criteria_name: str | None) -> tuple[str, ...]:
    """기준명에서 용역 세부유형 후보 집합을 뽑습니다. 못 뽑으면 빈 튜플입니다."""
    joined = _norm(criteria_name)
    if not joined:
        return ()
    for marker, service_types in _CRITERIA_SERVICE_TYPES:
        if _norm(marker) in joined:
            return service_types
    return ()


def _parse_announced(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _regime_rules(announced: date | None) -> tuple[er.EvaluationRule, ...]:
    """공고일이 속한 조달청 시행일 구간의 규칙 벌을 고릅니다. 미래 규칙은 쓰지 않습니다.

    공고일이 가장 이른 구간(2023-05-01)보다 앞서면 빈 튜플을 돌려주어, 시행일 대조에서
    대응 불가로 남깁니다. 이 스크립트는 미래 규칙으로 값을 채우지 않습니다.
    """
    if announced is None:
        return ()
    for start, rules in er.RULE_REGIME_BOUNDARIES:
        if announced >= start:
            return rules
    return ()


def _region_candidates(institution_name: str | None) -> tuple[er.EvaluationRule, ...]:
    """수요기관명이 시·도 이름과 정확히 같을 때 그 시·도의 LOCAL 규칙을 돌려줍니다."""
    cleaned = _norm(institution_name)
    if not cleaned:
        return ()
    return tuple(
        rule for rule in er.LOCAL_RULES if rule.region_name and _norm(rule.region_name) == cleaned
    )


def _institution_candidates(
    institution_code: str | None, institution_name: str | None
) -> tuple[er.EvaluationRule, ...]:
    """수요기관 축(코드·이름)으로 기관 규칙 후보를 고릅니다."""
    return tuple(
        rule
        for rule in er.INSTITUTION_RULES
        if er._axis_matches(
            rule,
            institution_code=institution_code,
            institution_name=institution_name,
            region_code=None,
            region_name=None,
            contract_regime=None,
        )
    )


_BAND_MARKERS: tuple[tuple[str, Decimal | None, bool], ...] = (
    ("고시금액 미만", None, False),
    ("고시금액미만", None, False),
    ("고시금액 이상", None, True),
    ("고시금액이상", None, True),
    ("2억원 미만", _E2EOK, False),
    ("2억원미만", _E2EOK, False),
    ("2억원 이상", _E2EOK, True),
    ("2억원이상", _E2EOK, True),
    ("5억원 미만", _E5EOK, False),
    ("5억원미만", _E5EOK, False),
    ("5억원 이상", _E5EOK, True),
    ("5억원이상", _E5EOK, True),
    ("15억원 이상", _E15EOK, True),
    ("15억원이상", _E15EOK, True),
    ("30억원 미만", _E30EOK, False),
    ("30억원미만", _E30EOK, False),
)


def _segment_conditions(segment: str, notice_amount: Decimal) -> list[tuple[Decimal, bool]]:
    """설명 한 토막에서 (경계, 경계 포함 여부) 조건 목록을 읽습니다. 조건은 모두 만족해야 합니다."""
    conditions: list[tuple[Decimal, bool]] = []
    seen: set[tuple[Decimal, bool]] = set()
    for marker, bound, inclusive in _BAND_MARKERS:
        if marker not in segment:
            continue
        resolved = notice_amount if bound is None else bound
        key = (resolved, inclusive)
        if key not in seen:
            seen.add(key)
            conditions.append(key)
    return conditions


def _band_applies(
    rule: er.EvaluationRule, price: Decimal | None, notice_amount: Decimal
) -> bool | None:
    """추정가격이 규칙의 구간에 드는지 봅니다. 판정 불가면 None 입니다.

    원문이 "5억원 미만 / 5억원 이상" 처럼 여러 구간을 한 규칙으로 인쇄하면 각 토막을
    OR 로 본다(조건부 B·k 규칙 하나가 전 구간을 담당). 토막 하나 안의 여러 조건은 AND 다.
    """
    if rule.price_bands:
        if price is None:
            return None if len(rule.price_bands) > 1 else True
        band, _, _ = er.select_price_band(rule.price_bands, price)
        return band is not None
    segments = [segment for segment in re.split(r"\s/\s", rule.description) if segment.strip()]
    if not segments:
        return True
    conditions = [_segment_conditions(segment, notice_amount) for segment in segments]
    if all(not segment for segment in conditions):
        return True
    if price is None:
        return None
    for segment in conditions:
        if not segment:
            return True
        if all((price >= bound) if inclusive else (price < bound) for bound, inclusive in segment):
            return True
    return False


@dataclass(frozen=True)
class MappingResult:
    service_type: str
    scope: str | None
    rule_id: str | None
    max_price_score: str
    multiplier: str
    pass_threshold: str
    lwlt_rate: str
    reason: str


def _unmapped(service_type: str, reason: str) -> MappingResult:
    return MappingResult(
        service_type=service_type,
        scope=None,
        rule_id=None,
        max_price_score="",
        multiplier="",
        pass_threshold="",  # nosec B106 - 배점표 통과점수(T) 필드이지 비밀번호가 아님
        lwlt_rate="",
        reason=reason,
    )


def _resolve_values(
    rule: er.EvaluationRule, price: Decimal | None, announced: date | None
) -> tuple[str, str, str, str]:
    """확정 규칙에서 (B, k, T, 낙찰하한율) 을 문자열로 뽑습니다."""
    resolution = er.resolve_score_params(rule, price, announced, method_name=None)
    b_text = _decimal_text(resolution.max_price_score)
    k_text = _decimal_text(resolution.multiplier)
    t_text = _decimal_text(resolution.pass_threshold)
    if rule.price_bands:
        band_rate, _, _ = er._band_lwlt_rate(rule, price)
    else:
        band_rate = rule.lwlt_rate
    return b_text, k_text, t_text, _decimal_text(band_rate)


def map_criteria_to_rule(
    criteria_name: str | None,
    announced: date | str | None,
    estimated_price: Decimal | str | float | int | None,
    institution_code: str | None = None,
    institution_name: str | None = None,
) -> MappingResult:
    """기준명·공고일·추정가격·수요기관으로 규칙 하나를 확정해 B·k·T·하한율을 채웁니다.

    공고일보다 늦게 시행된 규칙은 쓰지 않습니다. 규칙을 확정하지 못하면 사유만 남기고
    값을 비웁니다.
    """
    service_types = _service_types_from_criteria(criteria_name)
    if not service_types:
        return _unmapped("", "기준명에서 용역 세부유형을 확정하지 못함")
    announced_date = announced if isinstance(announced, date) else _parse_announced(announced)
    price = _to_decimal(estimated_price)

    institution_rules = _institution_candidates(institution_code, institution_name)
    if institution_rules:
        pool, scope = institution_rules, "INSTITUTION"
    else:
        region_rules = _region_candidates(institution_name)
        if region_rules:
            pool, scope = region_rules, "LOCAL"
        else:
            pool, scope = _regime_rules(announced_date), "PPS"

    typed_service = service_types[0]
    if not pool:
        return _unmapped(typed_service, "공고일 시점에 시행 중인 규칙이 없음(미래 규칙 미사용)")
    typed = [rule for rule in pool if rule.service_type in service_types]
    if not typed:
        return _unmapped(typed_service, f"{scope} 규칙에 대응하는 용역 유형이 없음")

    if announced_date is not None:
        dated = [
            rule for rule in typed if date.fromisoformat(rule.effective_date) <= announced_date
        ]
    else:
        dated = []
    if not dated:
        return _unmapped(typed_service, "공고일보다 늦게 시행된 규칙만 존재")

    notice_amount = Decimal(notice_amount_for_year(announced_date.year if announced_date else 2026))
    applicable = [rule for rule in dated if _band_applies(rule, price, notice_amount) is True]
    unknown_band = [rule for rule in dated if _band_applies(rule, price, notice_amount) is None]
    if len(applicable) > 1:
        return _unmapped(typed_service, "추정가격 구간이 겹치는 규칙이 둘 이상")
    if not applicable:
        if unknown_band:
            return _unmapped(typed_service, "추정가격이 없어 구간을 확정하지 못함")
        return _unmapped(typed_service, "추정가격이 어느 규칙 구간에도 들지 않음")

    rule = applicable[0]
    b_text, k_text, t_text, lwlt = _resolve_values(rule, price, announced_date)
    return MappingResult(
        service_type=rule.service_type,
        scope=scope,
        rule_id=rule.rule_id,
        max_price_score=b_text,
        multiplier=k_text,
        pass_threshold=t_text,
        lwlt_rate=lwlt,
        reason="",
    )


# ============================================================================
# 표본 대응 및 집계
# ============================================================================


def _load_raw_data(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _load_sample(path: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_key[str(row.get("bid_ntce_no") or "")] = row
    return by_key


@dataclass
class NoticeRow:
    year: int
    bid_ntce_no: str
    bid_ntce_dt: str
    institution_name: str
    institution_code: str
    criteria_name: str
    estimated_price: int | None
    extracted_b: str
    extracted_k: str
    extracted_t: str
    mapped: MappingResult

    def as_row(self) -> dict[str, object]:
        return {
            "year": self.year,
            "bid_ntce_no": self.bid_ntce_no,
            "bid_ntce_dt": self.bid_ntce_dt,
            "institution_name": self.institution_name,
            "criteria_name": self.criteria_name,
            "estimated_price": "" if self.estimated_price is None else self.estimated_price,
            "extracted_B": self.extracted_b,
            "extracted_k": self.extracted_k,
            "extracted_T": self.extracted_t,
            "scope": self.mapped.scope or "",
            "rule_id": self.mapped.rule_id or "",
            "service_type": self.mapped.service_type,
            "mapped_B": self.mapped.max_price_score,
            "mapped_k": self.mapped.multiplier,
            "mapped_T": self.mapped.pass_threshold,
            "mapped_lwlt_rate": self.mapped.lwlt_rate,
            "mapped": "1" if self.mapped.rule_id else "0",
            "reason": self.mapped.reason,
        }


def build_rows(
    sample: dict[str, dict[str, Any]],
    pilot_rows: list[dict[str, str]],
) -> list[NoticeRow]:
    """표본 raw 행과 파일럿 추출 CSV 를 공고번호로 맞대어 대응 결과를 만듭니다."""
    rows: list[NoticeRow] = []
    for pilot in pilot_rows:
        bid_no = pilot.get("bid_ntce_no") or ""
        raw = sample.get(bid_no, {})
        raw_data = _load_raw_data(raw)
        dt_text = str(raw.get("bid_ntce_dt") or "")
        year = int(pilot.get("year") or (dt_text[:4] if dt_text[:4].isdigit() else 0) or 0)
        estimated = _to_decimal(pilot.get("estimated_price"))
        institution_name = str(raw_data.get("dminsttNm") or "")
        institution_code = str(raw_data.get("dminsttCd") or "")
        criteria_name = pilot.get("criteria_name") or ""
        mapped = map_criteria_to_rule(
            criteria_name,
            dt_text,
            estimated,
            institution_code=institution_code,
            institution_name=institution_name,
        )
        rows.append(
            NoticeRow(
                year=year,
                bid_ntce_no=bid_no,
                bid_ntce_dt=dt_text[:10],
                institution_name=institution_name,
                institution_code=institution_code,
                criteria_name=criteria_name,
                estimated_price=int(estimated) if estimated is not None else None,
                extracted_b=pilot.get("max_price_score") or "",
                extracted_k=pilot.get("multiplier") or "",
                extracted_t=pilot.get("pass_threshold") or "",
                mapped=mapped,
            )
        )
    return rows


def _candidate_set(text: str) -> set[str]:
    return {part.strip() for part in text.split("|") if part.strip()}


def _agreement(mapped: str, extracted: str) -> bool:
    """대응값이 별표 추출값(후보 집합)에 드는지 봅니다."""
    if not mapped or not extracted:
        return False
    return mapped in _candidate_set(extracted)


def summarize(rows: list[NoticeRow]) -> dict[str, object]:
    """보고서 표를 만들 집계를 계산합니다. CSV 재집계로 재현됩니다."""
    with_criteria = [row for row in rows if row.criteria_name]
    missing_bk = [row for row in with_criteria if not (row.extracted_b and row.extracted_k)]
    mapped_missing = [row for row in missing_bk if row.mapped.rule_id]
    validation = [row for row in rows if row.extracted_b or row.extracted_k]
    b_agree = [row for row in validation if _agreement(row.mapped.max_price_score, row.extracted_b)]
    k_agree = [row for row in validation if _agreement(row.mapped.multiplier, row.extracted_k)]
    both_extracted = [row for row in validation if row.extracted_b and row.extracted_k]
    both_agree = [
        row for row in both_extracted if _agreement(row.mapped.multiplier, row.extracted_k)
    ]

    reasons: dict[str, int] = {}
    for row in missing_bk:
        if row.mapped.rule_id:
            continue
        reasons[row.mapped.reason] = reasons.get(row.mapped.reason, 0) + 1
    scopes: dict[str, int] = {}
    for row in mapped_missing:
        scope = row.mapped.scope or ""
        scopes[scope] = scopes.get(scope, 0) + 1
    mapped_criteria: dict[str, int] = {}
    for row in mapped_missing:
        mapped_criteria[row.criteria_name] = mapped_criteria.get(row.criteria_name, 0) + 1
    validation_mapped = [row for row in validation if row.mapped.rule_id]
    by_year: dict[int, dict[str, int]] = {}
    for row in missing_bk:
        bucket = by_year.setdefault(row.year, {"criteria": 0, "mapped": 0})
        bucket["criteria"] += 1
        if row.mapped.rule_id:
            bucket["mapped"] += 1

    return {
        "rows": len(rows),
        "criteria": len(with_criteria),
        "missing_bk_with_criteria": len(missing_bk),
        "mapped_missing_bk": len(mapped_missing),
        "mapping_rate": round(len(mapped_missing) / len(missing_bk), 4) if missing_bk else 0.0,
        "validation_set": len(validation),
        "validation_both_bk": len(both_extracted),
        "validation_mapped": len(validation_mapped),
        "b_agreement": len(b_agree),
        "k_agreement": len(k_agree),
        "both_agreement": len(both_agree),
        "unmapped_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "mapped_scopes": dict(sorted(scopes.items(), key=lambda kv: -kv[1])),
        "mapped_criteria": dict(sorted(mapped_criteria.items(), key=lambda kv: -kv[1])),
        "by_year": {str(year): by_year[year] for year in sorted(by_year)},
    }


RESULT_FIELDS = (
    "year",
    "bid_ntce_no",
    "bid_ntce_dt",
    "institution_name",
    "criteria_name",
    "estimated_price",
    "extracted_B",
    "extracted_k",
    "extracted_T",
    "scope",
    "rule_id",
    "service_type",
    "mapped_B",
    "mapped_k",
    "mapped_T",
    "mapped_lwlt_rate",
    "mapped",
    "reason",
)


def write_results_csv(rows: list[NoticeRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_row())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="과거 용역 공고 기준명을 evaluation_rules 규칙에 대응시켜 B·k·하한율 채움 가능성을 실측합니다."
    )
    parser.add_argument("--sample", required=True, help="표본 raw JSON (db_readonly_query 결과)")
    parser.add_argument("--pilot-results", required=True, help="파일럿 추출 CSV")
    parser.add_argument("--out-csv", default=".cache/past_notice_pilot/criteria_rule_map.csv")
    args = parser.parse_args(argv)

    sample = _load_sample(Path(args.sample))
    with Path(args.pilot_results).open(encoding="utf-8", newline="") as handle:
        pilot_rows = list(csv.DictReader(handle))

    rows = build_rows(sample, pilot_rows)
    write_results_csv(rows, Path(args.out_csv))
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
