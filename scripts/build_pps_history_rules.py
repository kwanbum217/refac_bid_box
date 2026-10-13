"""P2 명세 YAML 에서 과거 공고 전용 적격심사 이력 레지스트리를 생성합니다.

배경
----
`data/reference/pps_servc_qual_history_2015_2022.yaml` 은 2015~2022 년 시행 조달청
일반용역 적격심사 세부기준 12 개 판의 입찰가격 평점 별표(B·k·기준비율·통과점수·하한율)를
담은 기계 판독 명세입니다. 서빙 레지스트리 `src/app/services/evaluation_rules.py` 는
2023-05-01 이후 판만 담으므로, 그 이전 공고는 대응 규칙 자체가 없습니다.

이 스크립트는 명세를 **과거 공고 전용 이력 레지스트리 모듈**
`src/app/services/evaluation_rules_history.py` 로 옮깁니다. 서빙 모듈은 건드리지 않으므로
현행 공고 매칭 결과가 바뀌지 않습니다.

생성 규칙
--------
1. YAML 만 읽습니다. 값을 추정하거나 파생값을 만들지 않습니다. YAML 에 없는 값은 None 입니다.
2. 시행 구간이 뒤집힌 판(2016-48)은 그대로 싣되 `routable=False` 로 두어 조회에서 뺍니다.
   같은 날 시행된 2016-51 이 그 구간을 담당합니다(명세 gaps 참조).
3. `고시금액` 경계는 문자열 표기를 그대로 두고, 조회 시점에 연도별 고시금액으로 풉니다.
   근거가 있는 연도만 상수로 두며, 근거가 없으면 값을 만들지 않고 사유를 돌려줍니다.
4. 생성 결과가 커밋된 모듈과 같은지 `--check` 로 검증합니다.

사용 예:
    uv run python scripts/build_pps_history_rules.py
    uv run python scripts/build_pps_history_rules.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_YAML = PROJECT_ROOT / "data" / "reference" / "pps_servc_qual_history_2015_2022.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "app" / "services" / "evaluation_rules_history.py"
YAML_NAME = "data/reference/pps_servc_qual_history_2015_2022.yaml"

NOTICE_AMOUNT_LABEL = "고시금액"

# YAML 의 용역 표기를 서빙 레지스트리와 같은 코드로 옮깁니다. 표기가 늘어나면 여기에 추가합니다.
YAML_SERVICE_TYPE_CODES: dict[str, str] = {
    "학술연구용역": "ACADEMIC",
    "시설분야용역": "FACILITY",
    "정보통신용역(중소기업자간 경쟁제품 비대상)": "SW_NON_SME",
    "정보통신용역(중소기업자간 경쟁제품 대상)": "SW_SME",
    "소프트웨어용역(중소기업자간 경쟁제품 비대상)": "SW_NON_SME",
    "소프트웨어용역(중소기업자간 경쟁제품 대상)": "SW_SME",
    "폐기물처리용역": "WASTE",
    "육상운송용역(중소기업자간 경쟁제품 비대상)": "LAND_TRANSPORT",
    "육상운송용역(중소기업자간 경쟁제품 대상)": "LAND_TRANSPORT_SME",
    "육상운송용역": "LAND_TRANSPORT",
    "여객 육상운송용역": "PASSENGER_TRANSPORT",
    "화물 육상운송용역": "FREIGHT",
    "보험용역": "INSURANCE",
}

# 시행 구간이 뒤집혀 조회에서 빼는 판과 그 사유. 명세 gaps 의 2016-48 항목과 같은 근거입니다.
NON_ROUTABLE_REVISIONS: dict[str, str] = {
    "2016-48": "명세상 시행 구간이 뒤집혀 있습니다(종료일 2016-04-30 < 시행일 2016-05-01).",
}

# 연도별 용역 고시금액. 근거가 있는 값만 둡니다. 2019~2022 년 값은 저장소에 근거가 없어
# 두지 않으며, 그 해 '고시금액' 경계는 조회 시 미확정으로 돌려줍니다.
NOTICE_AMOUNT_BY_YEAR: dict[int, int] = {
    2023: 220_000_000,
}

NOTICE_AMOUNT_SOURCES: dict[int, str] = {
    2023: "기획재정부 고시 제2022-32호(2022-12-30). src/ml/notice_amount.py:4 와 같은 값",
}

MODULE_HEADER = '''"""과거(2015~2022 시행) 공고 전용 조달청 일반용역 적격심사 이력 레지스트리.

이 파일은 생성물입니다. 직접 고치지 말고 명세 YAML 을 고친 뒤
`uv run python scripts/build_pps_history_rules.py` 로 다시 생성하십시오.

정본 명세: `data/reference/pps_servc_qual_history_2015_2022.yaml`
근거 문서: `docs/analysis/pps_servc_qual_history_20261013.md`

서빙 레지스트리 `src/app/services/evaluation_rules.py` 는 2023-05-01 이후 판만 담습니다.
이 모듈은 그 이전 공고를 되짚을 때만 쓰며, 서빙 경로는 이 모듈을 import 하지 않습니다.
따라서 현행 공고의 규칙 매칭 결과는 이 모듈로 바뀌지 않습니다.

값의 성격
--------
- B(max_price_score)·k(multiplier)·base_ratio·flat_ratio·pass_score 는 YAML 에 실린 원문
  인쇄값 또는 본문 제10조 통과점수입니다. 추정하거나 파생하지 않습니다.
- lwlt_rate(낙찰하한율)는 원문에 인쇄되지 않아 `기준비율 - (100 - 통과점수) / k` 로 역산한
  YAML 파생값이며, 소수 둘째 자리까지 버린 뒤 0.005 를 뺀 `.995` 표기 관행을 따릅니다.
- 시행 구간이 뒤집힌 제2016-48호는 routable=False 로 두어 조회에서 뺍니다.
- 원문 별표의 계산식 문자열은 정본 YAML 에 그대로 있으며, 각 별표의 `source`(flSeq)로 찾습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

NOTICE_AMOUNT_BOUNDARY: Final[Literal["고시금액"]] = "고시금액"

# 추정가격 구간 경계. Decimal 이면 금액, NOTICE_AMOUNT_BOUNDARY 면 그 해 고시금액,
# None 이면 하한 또는 상한 없음입니다.
Boundary = Decimal | Literal["고시금액"] | None


@dataclass(frozen=True)
class HistoryScoreTier:
    """평점산식 구간 하나. 배점한도 구간과 경계가 다를 수 있어 별도 축으로 둡니다."""

    formula_lower: Boundary
    formula_upper: Boundary
    k: Decimal
    base_ratio: Decimal
    flat_ratio: Decimal | None
    pass_score: Decimal
    lwlt_rate: Decimal


@dataclass(frozen=True)
class HistoryPriceBand:
    """별표의 배점한도 구간 하나. 그 안에 평점산식 구간이 여럿일 수 있습니다."""

    price_lower: Boundary
    price_upper: Boundary
    max_price_score: Decimal | None
    tiers: tuple[HistoryScoreTier, ...]


@dataclass(frozen=True)
class HistoryAttachment:
    """별표 하나. service_type 은 서빙 레지스트리와 같은 코드입니다."""

    attachment: str
    title: str
    service_type: str
    source_service_type: str
    fl_seq: str
    rule_id: str
    source: str
    bands: tuple[HistoryPriceBand, ...]


@dataclass(frozen=True)
class HistoryRevision:
    """고시 판 하나. effective_from~effective_to 가 그 판이 시행된 구간입니다."""

    notice_key: str
    notice_no: str
    effective_from: date
    effective_to: date
    routable: bool
    exclusion_reason: str | None
    source: str
    attachments: tuple[HistoryAttachment, ...]


'''

MODULE_TABLES = """HISTORY_NOTICE_AMOUNT_BY_YEAR: Final[dict[int, int]] = {
"""

MODULE_SECTIONS = '''

@dataclass(frozen=True)
class HistoryBandResolution:
    """조회 결과. 개정판·별표·구간과 B·k·기준비율·통과점수·하한율, 출처를 담습니다."""

    rule_id: str
    revision_key: str
    revision_notice_no: str
    attachment: str
    service_type: str
    source_service_type: str
    max_price_score: Decimal | None
    multiplier: Decimal
    base_ratio: Decimal
    flat_ratio: Decimal | None
    pass_score: Decimal
    lwlt_rate: Decimal
    source: str


def history_notice_amount_for_year(year: int) -> int | None:
    """그 해 용역 고시금액. 근거가 있는 연도만 값을 돌려주고 나머지는 None 입니다."""
    return HISTORY_NOTICE_AMOUNT_BY_YEAR.get(year)


def _coerce_date(value: date | datetime | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _coerce_amount(value: Decimal | str | float | int | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError, InvalidOperation):
        return None
    return amount if amount > 0 else None


def _resolve_boundary(
    value: Boundary, notice_amount: Decimal | None
) -> tuple[Decimal | None, str | None]:
    """경계 표기를 금액으로 풉니다. 둘째 값이 있으면 확정 실패입니다."""
    if value is None:
        return None, None
    if isinstance(value, Decimal):
        return value, None
    if notice_amount is None:
        return None, "구간 경계가 고시금액인데 해당 연도 고시금액 근거가 없습니다."
    return notice_amount, None


def _select_revision(day: date) -> HistoryRevision | None:
    for revision in HISTORY_REVISIONS:
        if revision.effective_from <= day <= revision.effective_to:
            return revision
    return None


def _match(
    price: Decimal,
    lower: Boundary,
    upper: Boundary,
    notice_amount: Decimal | None,
) -> tuple[bool, str | None]:
    """하한 이상, 상한 미만으로 구간을 판정합니다. 둘째 값이 있으면 확정 실패입니다."""
    low, reason = _resolve_boundary(lower, notice_amount)
    if reason:
        return False, reason
    high, reason = _resolve_boundary(upper, notice_amount)
    if reason:
        return False, reason
    if low is not None and price < low:
        return False, None
    if high is not None and price >= high:
        return False, None
    return True, None


def resolve_history_band(
    notice_date: date | datetime | str | None,
    service_type: str,
    estimated_price: Decimal | str | float | int | None,
    notice_amount_boundary: Decimal | str | float | int | None = None,
) -> tuple[HistoryBandResolution | None, str | None]:
    """공고일·용역 유형·추정가격으로 개정판·별표·구간을 확정합니다.

    확정하면 (결과, None), 못 하면 (None, 사유)를 돌려줍니다. 값을 추정하지 않습니다.
    하한은 이상, 상한은 미만이며 경계값은 상위 구간에 듭니다.
    """
    day = _coerce_date(notice_date)
    if day is None:
        return None, "공고일이 없어 시행 중인 개정판을 고르지 못했습니다."
    price = _coerce_amount(estimated_price)
    if price is None:
        return None, "추정가격이 없어 구간을 고르지 못했습니다."
    revision = _select_revision(day)
    if revision is None:
        return None, "공고일 시점에 시행 중인 이력 개정판이 없습니다."
    if not revision.routable:
        return None, revision.exclusion_reason or "조회에서 제외된 개정판입니다."
    attachments = [item for item in revision.attachments if item.service_type == service_type]
    if not attachments:
        return None, f"이력 레지스트리에 {service_type} 별표가 없습니다."
    if len(attachments) > 1:
        return None, f"이력 레지스트리에 {service_type} 별표가 둘 이상입니다."
    attachment = attachments[0]
    notice_amount = _coerce_amount(notice_amount_boundary)

    matched_bands: list[HistoryPriceBand] = []
    band_reasons: list[str] = []
    for band in attachment.bands:
        ok, reason = _match(price, band.price_lower, band.price_upper, notice_amount)
        if reason:
            band_reasons.append(reason)
        elif ok:
            matched_bands.append(band)
    if not matched_bands:
        if band_reasons:
            return None, band_reasons[0]
        return None, "추정가격이 어느 배점 구간에도 들지 않습니다."
    if len(matched_bands) > 1:
        return None, "추정가격이 배점 구간 둘 이상에 겹칩니다."
    band = matched_bands[0]

    matched_tiers: list[HistoryScoreTier] = []
    tier_reasons: list[str] = []
    for tier in band.tiers:
        ok, reason = _match(price, tier.formula_lower, tier.formula_upper, notice_amount)
        if reason:
            tier_reasons.append(reason)
        elif ok:
            matched_tiers.append(tier)
    if not matched_tiers:
        if tier_reasons:
            return None, tier_reasons[0]
        return None, "추정가격이 어느 평점산식 구간에도 들지 않습니다."
    if len(matched_tiers) > 1:
        return None, "추정가격이 평점산식 구간 둘 이상에 겹칩니다."
    tier = matched_tiers[0]

    return (
        HistoryBandResolution(
            rule_id=attachment.rule_id,
            revision_key=revision.notice_key,
            revision_notice_no=revision.notice_no,
            attachment=attachment.attachment,
            service_type=attachment.service_type,
            source_service_type=attachment.source_service_type,
            max_price_score=band.max_price_score,
            multiplier=tier.k,
            base_ratio=tier.base_ratio,
            flat_ratio=tier.flat_ratio,
            pass_score=tier.pass_score,
            lwlt_rate=tier.lwlt_rate,
            source=attachment.source,
        ),
        None,
    )


def _validate_revisions(revisions: tuple[HistoryRevision, ...]) -> None:
    """생성물의 시행 구간과 필수값을 검사합니다. 어긋나면 import 시점에 실패합니다."""
    for revision in revisions:
        if revision.routable and revision.effective_to < revision.effective_from:
            raise ValueError(f"{revision.notice_key} 판의 시행 구간이 뒤집혔습니다.")
        if not revision.attachments:
            raise ValueError(f"{revision.notice_key} 판에 별표가 없습니다.")
        for attachment in revision.attachments:
            if not attachment.bands:
                raise ValueError(f"{attachment.rule_id} 별표에 배점 구간이 없습니다.")
            for band in attachment.bands:
                if band.price_lower is None and band.price_upper is None:
                    raise ValueError(f"{attachment.rule_id} 배점 구간에 경계가 없습니다.")
                if not band.tiers:
                    raise ValueError(f"{attachment.rule_id} 배점 구간에 평점산식이 없습니다.")
                multiple = len(band.tiers) > 1
                for tier in band.tiers:
                    unbounded = tier.formula_lower is None and tier.formula_upper is None
                    if multiple and unbounded:
                        raise ValueError(f"{attachment.rule_id} 평점산식 구간에 경계가 없습니다.")
                    if tier.k <= 0:
                        raise ValueError(f"{attachment.rule_id} 평점계수는 0보다 커야 합니다.")


_validate_revisions(HISTORY_REVISIONS)
'''


def _decimal_literal(value: Any) -> str:
    if value is None:
        return "None"
    return f'Decimal("{format(Decimal(str(value)).normalize(), "f")}")'


def _boundary_literal(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, str):
        if value != NOTICE_AMOUNT_LABEL:
            raise ValueError(f"명세에 없는 경계 표기입니다: {value!r}")
        return "NOTICE_AMOUNT_BOUNDARY"
    return _decimal_literal(value)


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _attachment_code(attachment: str) -> str:
    parts = attachment.replace("별표 ", "").split("의")
    if not parts[0].isdigit() or (len(parts) > 1 and not parts[1].isdigit()):
        raise ValueError(f"별표 표기를 해석하지 못했습니다: {attachment!r}")
    code = f"ATTACH_{int(parts[0]):02d}"
    return f"{code}_{int(parts[1])}" if len(parts) > 1 else code


def _date_literal(value: str) -> str:
    year, month, day = (int(part) for part in value.split("-"))
    return f"date({year}, {month}, {day})"


def _render_attachment(yaml_attachment: dict[str, Any], revision: dict[str, Any]) -> list[str]:
    raw_type = yaml_attachment["service_type"]
    if raw_type not in YAML_SERVICE_TYPE_CODES:
        raise ValueError(f"용역 유형 코드를 모릅니다: {raw_type!r}")
    attachment_name = yaml_attachment["attachment"]
    fl_seq = yaml_attachment["fl_seq"]
    rule_id = (
        f"SERVC_QUAL_HIST_{str(revision['notice_key']).replace('-', '_')}_"
        f"{_attachment_code(attachment_name)}"
    )
    lines = [
        "            HistoryAttachment(",
        f"                attachment={_text(attachment_name)},",
        f"                title={_text(yaml_attachment['title'])},",
        f"                service_type={_text(YAML_SERVICE_TYPE_CODES[raw_type])},",
        f"                source_service_type={_text(raw_type)},",
        f"                fl_seq={_text(fl_seq)},",
        f"                rule_id={_text(rule_id)},",
        f"                source={_text(f'{YAML_NAME} (flSeq {fl_seq})')},",
        "                bands=(",
    ]
    for band in yaml_attachment["bands"]:
        lines.extend(
            [
                "                    HistoryPriceBand(",
                f"                        price_lower={_boundary_literal(band['price_lower'])},",
                f"                        price_upper={_boundary_literal(band['price_upper'])},",
                f"                        max_price_score={_decimal_literal(band['B'])},",
                "                        tiers=(",
            ]
        )
        for tier in band["score_tiers"]:
            lines.extend(
                [
                    "                            HistoryScoreTier(",
                    f"                                formula_lower={_boundary_literal(tier['formula_lower'])},",
                    f"                                formula_upper={_boundary_literal(tier['formula_upper'])},",
                    f"                                k={_decimal_literal(tier['k'])},",
                    f"                                base_ratio={_decimal_literal(tier['base_ratio'])},",
                    f"                                flat_ratio={_decimal_literal(tier['flat_ratio'])},",
                    f"                                pass_score={_decimal_literal(tier['pass_score'])},",
                    f"                                lwlt_rate={_decimal_literal(tier['lwlt_rate'])},",
                    "                            ),",
                ]
            )
        lines.extend(["                        ),", "                    ),"])
    lines.extend(["                ),", "            ),"])
    return lines


def _render_revision(yaml_revision: dict[str, Any]) -> list[str]:
    notice_key = str(yaml_revision["notice_key"])
    reason = NON_ROUTABLE_REVISIONS.get(notice_key)
    lines = [
        "    HistoryRevision(",
        f"        notice_key={_text(notice_key)},",
        f"        notice_no={_text(yaml_revision['notice_no'])},",
        f"        effective_from={_date_literal(yaml_revision['effective_from'])},",
        f"        effective_to={_date_literal(yaml_revision['effective_to'])},",
        f"        routable={reason is None!r},",
        f"        exclusion_reason={_text(reason) if reason else 'None'},",
        "        source="
        + _text(
            f"{yaml_revision['notice_no']} "
            f"({yaml_revision['promulgated']} 발령, {yaml_revision['change_type']})"
        )
        + ",",
        "        attachments=(",
    ]
    for attachment in yaml_revision["attachments"]:
        lines.extend(_render_attachment(attachment, yaml_revision))
    lines.extend(["        ),", "    ),"])
    return lines


def render_module(yaml_path: Path = DEFAULT_YAML) -> str:
    """명세 YAML 을 이력 레지스트리 모듈 소스로 렌더링합니다."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    revisions = data.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError("명세에 revisions 가 없습니다.")

    blocks = [MODULE_HEADER, MODULE_TABLES]
    for year in sorted(NOTICE_AMOUNT_BY_YEAR):
        source = NOTICE_AMOUNT_SOURCES[year]
        blocks.append(f"    {year}: {NOTICE_AMOUNT_BY_YEAR[year]:_},  # {source}\n")
    blocks.append("}\n\nHISTORY_REVISIONS: Final[tuple[HistoryRevision, ...]] = (\n")
    for revision in revisions:
        blocks.append("\n".join(_render_revision(revision)))
        blocks.append("\n")
    blocks.append(")\n")
    blocks.append(MODULE_SECTIONS)
    text = "".join(blocks)
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) > 100:
            raise ValueError(f"생성 {number} 행이 100 자를 넘습니다: {line!r}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2 명세 YAML 에서 과거 공고 전용 이력 레지스트리 모듈을 생성합니다."
    )
    parser.add_argument("--yaml", default=str(DEFAULT_YAML), help="정본 명세 YAML 경로")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="생성할 모듈 경로")
    parser.add_argument(
        "--check",
        action="store_true",
        help="생성 결과를 커밋된 모듈과 대조만 하고 쓰지 않습니다(다르면 실패).",
    )
    args = parser.parse_args(argv)

    text = render_module(Path(args.yaml))
    out_path = Path(args.out)
    if args.check:
        if not out_path.exists():
            print(f"생성 대상이 없습니다: {out_path}", file=sys.stderr)
            return 1
        if out_path.read_text(encoding="utf-8") != text:
            print(f"커밋된 모듈이 명세와 다릅니다. 재생성하십시오: {out_path}", file=sys.stderr)
            return 1
        print(f"명세와 모듈이 일치합니다: {out_path}")
        return 0

    out_path.write_text(text, encoding="utf-8")
    print(f"생성했습니다: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
