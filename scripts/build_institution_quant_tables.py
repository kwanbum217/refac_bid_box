#!/usr/bin/env python3
"""기관 정량평가 배점표 명세(YAML)를 서빙 상수 모듈로 생성합니다.

Q2 명세 `data/reference/institution_quant_tables_20261013.yaml`(기관 10곳, 규칙 67개,
구간 136개)를 읽어 `src/app/services/evaluation_quant_institution.py` 의
`INSTITUTION_QUANT_SCORE_TABLES`(rule_id 키 QuantScoreTable 사전)를 만듭니다.

명세가 부분이라 배점표를 확정할 수 없는 규칙(한국가스공사)은 표를 만들지 않아
종전처럼 정량점수 직접 입력이 유지됩니다. 조달청 별표 표(QUANT_SCORE_TABLES)는
건드리지 않습니다.

결정적 생성입니다. 같은 YAML 에 대해 두 번 돌려도 같은 파일이 나오며, `--check` 는
커밋본이 지금 YAML 에서 생성한 내용과 바이트 단위로 같은지 검사합니다(드리프트 차단).

생성물은 ruff 포맷을 통과해야 하므로, 생성 텍스트를 ruff format 으로 정규화한 뒤
비교·기록합니다. ruff 는 uv 환경에 항상 있으므로 `uv run python ...` 로 실행하십시오.

사용:
  uv run python scripts/build_institution_quant_tables.py
  uv run python scripts/build_institution_quant_tables.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - 생성물을 ruff 로 정규화하려고 ruff 를 실행합니다
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "data/reference/institution_quant_tables_20261013.yaml"
OUTPUT_PATH = PROJECT_ROOT / "src/app/services/evaluation_quant_institution.py"

# 2026년 고시금액(용역 2.3억). evaluation_rules._INSTITUTION_NOTICE_AMOUNT 와 같은 값이며,
# 명세 band_label 의 "고시금액" 경계를 원으로 환산할 때 씁니다.
NOTICE_AMOUNT_2026 = Decimal("230000000")

_TABLE_HEADER = '''"""기관 적격심사 정량평가 배점표 (자동 생성).

`data/reference/institution_quant_tables_20261013.yaml`(Q2 명세)에서
`scripts/build_institution_quant_tables.py` 가 생성한 파일입니다. 직접 수정하지 말고
생성 스크립트로 다시 만드십시오.

기관 규칙 하나(rule_id)마다 QuantScoreTable 하나를 둡니다. 조달청 별표 표와 달리
경영상태·신인도는 기관 원문 등급표·신인도표를 쓰므로 is_institution=True 로 두어
조달청 별표 10·11 입력 경로를 타지 않게 합니다. 명세가 부분이라 배점표를 확정할 수 없는
규칙(한국가스공사)은 이 표에 넣지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    QUANT_LIMIT_KIND_ABSENT,
    QUANT_LIMIT_KIND_DISQUALIFICATION,
    QUANT_LIMIT_KIND_PRICE,
    QUANT_LIMIT_KIND_REPUTATION,
    QUANT_LIMIT_KIND_SCORE,
    QuantScoreBand,
    QuantScoreItem,
    QuantScoreTable,
)

SOURCE_YAML = "data/reference/institution_quant_tables_20261013.yaml"
NOTICE_AMOUNT_2026 = Decimal("230000000")


INSTITUTION_QUANT_SCORE_TABLES: dict[str, QuantScoreTable] = {
'''

_KIND_BY_NAME = (
    ("입찰가격", "QUANT_LIMIT_KIND_PRICE"),
    ("결격사유", "QUANT_LIMIT_KIND_DISQUALIFICATION"),
    ("신인도", "QUANT_LIMIT_KIND_REPUTATION"),
)


def _item_key(name: str) -> str:
    """원문 항목명을 안정 입력 키로 옮깁니다. 조달청 키와 같은 의미면 같은 키를 씁니다."""
    if "입찰가격" in name:
        return "price"
    if "결격사유" in name:
        return "disqualification"
    if "신인도" in name:
        return "reputation"
    if "근로조건" in name:
        return "labor_plan"
    if "경영상태" in name:
        return "management"
    if "사업경험" in name:
        return "revenue" if "매출액" in name else "performance_business"
    if "조사이행능력" in name:
        return "research_capacity"
    if "사업관리능력" in name:
        return "project_management"
    if "보험금 지급능력" in name:
        return "insurance_payment_ability"
    if "사후관리" in name:
        return "after_service"
    if "기술신용평가등급" in name:
        return "technical_credit"
    if "기술인력 보유상황" in name:
        return "technical_capacity"
    if "기술 보유상황" in name:
        return "technical_asset"
    if "기술능력" in name:
        return "technical_capacity"
    if "준비상태" in name:
        if "경비지도사" in name:
            return "readiness_guard"
        if "근로기준법" in name:
            return "readiness_labor"
        return "readiness"
    if "수행실적" in name or "수행능력" in name or "이행실적" in name:
        return "performance"
    raise ValueError(f"미분류 항목명입니다: {name!r}")


def _kind(yaml_kind: str | None, name: str) -> str:
    """YAML limit_kind 를 코드 상수 이름으로 옮깁니다.

    입찰가격은 명세가 score 로 두지만 화면·검증에서 별도 취급하므로 price 로,
    결격사유·신인도는 각각 disqualification·reputation 으로 맞춥니다. 원문이 '-' 로
    표기한 항목(absent)은 입력을 막는 absent 로 둡니다.
    """
    for token, constant in _KIND_BY_NAME:
        if token in name:
            return constant
    if yaml_kind == "absent":
        return "QUANT_LIMIT_KIND_ABSENT"
    return "QUANT_LIMIT_KIND_SCORE"


def _decimal(value: Any) -> str:
    if isinstance(value, float):
        return f'Decimal("{value!r}")'
    return f'Decimal("{value}")'


# 원문 항목명이 쓰는 로마 숫자(U+2160~U+2164)는 소스에서 유니코드 이스케이프로 적어
# ruff 의 모호 문자 경고(RUF001)를 피합니다. 런타임 값은 같은 문자입니다.
_AMBIGUOUS_ESCAPES = {
    "\u2160": "\\u2160",
    "\u2161": "\\u2161",
    "\u2162": "\\u2162",
    "\u2163": "\\u2163",
    "\u2164": "\\u2164",
}


def _py_str(value: str) -> str:
    text = json.dumps(value, ensure_ascii=False)
    for char, escape in _AMBIGUOUS_ESCAPES.items():
        text = text.replace(char, escape)
    return text


def _section_no(name: str) -> str:
    """항목명 앞머리의 심사분야 번호(1., 로마 숫자)를 뽑습니다. 없으면 빈 문자열입니다."""
    match = re.match(r"\s*([0-9]+|[\u2160-\u2164]+)\.", name)
    return match.group(1) if match else ""


def _band_upper_bound(label: str) -> Decimal | None:
    """구간 표기에서 상한(원)을 옮깁니다. 'N억원 미만' 또는 '고시금액 미만'만 씁니다.

    원문에 없는 경계는 만들지 않습니다. 상한 표기가 없으면 None(상한 없음)입니다.
    """
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)억원\s*미만", label)
    if match:
        return Decimal(match.group(1)) * Decimal("100000000")
    if "고시금액" in label and "미만" in label:
        return NOTICE_AMOUNT_2026
    return None


def _band_sort_key(band: dict[str, Any]) -> tuple[bool, Decimal]:
    bound = _band_upper_bound(str(band["band_label"]))
    return (bound is None, bound if bound is not None else Decimal("0"))


def _render_item(item: dict[str, Any], band_label: str) -> list[str]:
    name = str(item["name"])
    key = _item_key(name)
    kind = _kind(item.get("limit_kind"), name)
    limit = item.get("limit")
    limit_expr = "None" if limit is None else _decimal(limit)
    note = item.get("note")
    note_expr = "None" if note is None else _py_str(str(note))
    return [
        "                QuantScoreItem(",
        f"                    section_no={_py_str(_section_no(name))},",
        f"                    section_name={_py_str(band_label)},",
        f"                    item_key={_py_str(key)},",
        f"                    item_name={_py_str(name)},",
        f"                    limit={limit_expr},",
        f"                    limit_kind={kind},",
        f"                    source={_py_str(str(item.get('source', '')))},",
        f"                    note={note_expr},",
        "                ),",
    ]


def _render_band(band: dict[str, Any]) -> list[str]:
    label = str(band["band_label"])
    upper = _band_upper_bound(label)
    upper_expr = "None" if upper is None else _decimal(upper)
    lines = [
        "            QuantScoreBand(",
        f"                band_key={_py_str(str(band['band_key']))},",
        f"                band_label={_py_str(label)},",
        f"                total_limit={_decimal(band['total_limit'])},",
        f"                upper_bound={upper_expr},",
        "                items=(",
    ]
    for item in band["items"]:
        lines.extend(_render_item(item, label))
    lines.extend(["                ),", "            ),"])
    return lines


def _render_table(rule: dict[str, Any]) -> list[str]:
    attachment = str(rule.get("attachment", ""))
    table_name = (
        rule.get("table_name") or f"{rule.get('service_type', '')} 적격심사항목 및 배점한도"
    )
    note = rule.get("note")
    lines = [
        f"    {_py_str(str(rule['rule_id']))}: QuantScoreTable(",
        f"        attachment={_py_str(attachment)},",
        f"        table_name={_py_str(str(table_name))},",
        f"        source={_py_str(str(rule.get('source', '')))},",
        f"        note={'None' if note is None else _py_str(str(note))},",
        "        is_institution=True,",
        "        bands=(",
    ]
    for band in sorted(rule["bands"], key=_band_sort_key):
        lines.extend(_render_band(band))
    lines.extend(["        ),", "    ),"])
    return lines


def render_module() -> str:
    """YAML 전체를 기관 배점표 모듈 소스로 옮깁니다(ruff 포맷 전 원문)."""
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    lines = _TABLE_HEADER.splitlines()
    for institution in spec["institutions"]:
        if institution.get("quant_table_status") != "confirmed":
            continue
        for rule in institution["rules"]:
            lines.extend(_render_table(rule))
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _format_source(source: str) -> str:
    """ruff format 으로 정규화합니다. 생성물이 포맷 검사를 그대로 통과하게 합니다."""
    try:
        # 고정 실행 파일 이름과 고정 인자만 씁니다. 외부 입력이 없어 명령 주입 여지가 없습니다.
        completed = subprocess.run(  # nosec B603 B607
            ["ruff", "format", "--stdin-filename", str(OUTPUT_PATH), "-"],
            input=source,
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        print(f"ruff format 실행에 실패했습니다: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    return completed.stdout


def _normalized() -> str:
    return _format_source(render_module())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기관 정량 배점표 모듈 생성/검증")
    parser.add_argument(
        "--check",
        action="store_true",
        help="커밋본과 YAML 생성 결과가 같은지 검사하고 다르면 실패합니다.",
    )
    args = parser.parse_args(argv)

    generated = _normalized()
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != generated:
            print(
                f"{OUTPUT_PATH.relative_to(PROJECT_ROOT)} 이 YAML 과 다릅니다. "
                "scripts/build_institution_quant_tables.py 를 다시 실행하십시오.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH.relative_to(PROJECT_ROOT)} 이 YAML 과 일치합니다.")
        return 0

    OUTPUT_PATH.write_text(generated, encoding="utf-8")
    print(f"{OUTPUT_PATH.relative_to(PROJECT_ROOT)} 을 생성했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
