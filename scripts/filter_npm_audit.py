"""scripts/filter_npm_audit.py

npm audit JSON 결과를 allowlist와 대조하여 차단 여부를 판정합니다.

패키지 단위가 아닌 (패키지 이름 + advisory ID) 쌍으로 대조하여,
동일 패키지에 새로운 취약점이 발생했을 때 자동으로 통과하는 결함을 방지합니다.
결과 파일 부재 또는 빈 입력/파싱 오류 시 fail-closed(종료 코드 1)로 차단합니다.
stdin 파이프 및 --input 파일 인자를 모두 지원합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ALLOWLIST_PATH = Path(".github/vulnerability-allowlist.yml")


def extract_advisory_id(via_entry: dict[str, Any]) -> str | None:
    """via 항목 딕셔너리에서 advisory ID(GHSA 또는 CVE)를 추출합니다."""
    # 1. 명시적 키 확인
    for key in ("id", "github_advisory_id", "ghsa_id", "cve"):
        val = via_entry.get(key)
        if isinstance(val, str) and (val.startswith("GHSA-") or val.startswith("CVE-")):
            return val

    # 2. url 확인 (예: https://github.com/advisories/GHSA-2v37-7h3g-55p8)
    url = via_entry.get("url")
    if isinstance(url, str):
        match = re.search(r"(GHSA-[a-zA-Z0-9_-]+|CVE-\d{4}-\d+)", url)
        if match:
            return match.group(1)

    # 3. title 확인
    title = via_entry.get("title")
    if isinstance(title, str):
        match = re.search(r"(GHSA-[a-zA-Z0-9_-]+|CVE-\d{4}-\d+)", title)
        if match:
            return match.group(1)

    # 4. source 필드가 문자열 ID인 경우
    source = via_entry.get("source")
    if isinstance(source, str) and (source.startswith("GHSA-") or source.startswith("CVE-")):
        return source

    return None


def load_npm_allowlist_pairs(allowlist_path: Path) -> set[tuple[str, str]]:
    """allowlist 파일에서 npm 섹션의 (package, id) 쌍 집합을 추출합니다."""
    if not allowlist_path.exists():
        raise FileNotFoundError(f"allowlist 파일이 없습니다: {allowlist_path}")
    raw_text = allowlist_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text) or {}
    entries = data.get("npm") or []
    allowed: set[tuple[str, str]] = set()
    for item in entries:
        if isinstance(item, dict):
            pkg = str(item.get("package") or "").strip()
            adv_id = str(item.get("id") or "").strip()
            if pkg and adv_id:
                allowed.add((pkg, adv_id))
    return allowed


def parse_npm_vulnerabilities(audit_data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """npm audit JSON에서 HIGH 및 CRITICAL 취약점을 (package, advisory_id, severity)로 추출합니다."""
    vulnerabilities: list[tuple[str, str, str]] = []
    vuln_map = audit_data.get("vulnerabilities") or {}
    if not isinstance(vuln_map, dict):
        return vulnerabilities

    for pkg_name, info in vuln_map.items():
        if not isinstance(info, dict):
            continue
        overall_sev = str(info.get("severity") or "").lower()
        if overall_sev not in ("high", "critical"):
            continue

        via_list = info.get("via") or []
        dict_entries = [v for v in via_list if isinstance(v, dict)]

        if dict_entries:
            for item in dict_entries:
                item_sev = str(item.get("severity") or overall_sev).lower()
                if item_sev in ("high", "critical"):
                    adv_id = extract_advisory_id(item)
                    if adv_id:
                        vulnerabilities.append((pkg_name, adv_id, item_sev.upper()))
                    else:
                        vulnerabilities.append(
                            (pkg_name, f"UNKNOWN-{item.get('source', 'adv')}", item_sev.upper())
                        )
        else:
            # 전이 의존성 링크만 있거나(via에 문자열만 있음) 비어 있는 경우
            # via에 문자열(원인 패키지 이름)이 있다면 해당 원인 패키지가 vulnerabilities에 별도 존재하여 검사됨.
            # via가 완전히 비어있다면 원인을 특정할 수 없으므로 fail-closed로 등록.
            if not via_list:
                vulnerabilities.append((pkg_name, "UNKNOWN", overall_sev.upper()))

    return vulnerabilities


def filter_npm_vulnerabilities(
    vulnerabilities: list[tuple[str, str, str]],
    allowed_pairs: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """allowlist에 등록된 (package, id) 쌍을 제외하고 남은 취약점 목록을 반환합니다."""
    remaining: list[tuple[str, str, str]] = []
    for pkg_name, adv_id, sev in vulnerabilities:
        if (pkg_name, adv_id) not in allowed_pairs:
            remaining.append((pkg_name, adv_id, sev))
    return remaining


def run_npm_filter(
    audit_json_str: str | None,
    allowlist_path: Path,
    err_stream=sys.stderr,
    out_stream=sys.stdout,
) -> int:
    """npm audit JSON 문자열을 검사하고 종료 코드를 반환합니다."""
    if audit_json_str is None or not audit_json_str.strip():
        err_stream.write("npm audit result input is empty\n")
        return 1

    try:
        audit_data = json.loads(audit_json_str)
    except Exception as exc:
        err_stream.write(f"Failed to parse npm audit result JSON: {exc}\n")
        return 1

    try:
        allowed_pairs = load_npm_allowlist_pairs(allowlist_path)
    except Exception as exc:
        err_stream.write(f"Failed to load allowlist: {exc}\n")
        return 1

    all_vulns = parse_npm_vulnerabilities(audit_data)
    remaining = filter_npm_vulnerabilities(all_vulns, allowed_pairs)

    if remaining:
        err_stream.write("npm audit failed; HIGH/CRITICAL not in allowlist:\n")
        for pkg, adv_id, sev in remaining:
            err_stream.write(f"  - {pkg} ({adv_id}, {sev})\n")
        return 1

    out_stream.write("npm audit: all HIGH/CRITICAL vulnerabilities are in allowlist\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filter npm audit results against allowlist")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to npm audit JSON file (reads stdin if omitted)",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="Path to vulnerability allowlist YAML",
    )
    args = parser.parse_args(argv)

    if args.input is not None:
        if not args.input.exists():
            sys.stderr.write(f"npm audit result file not found: {args.input}\n")
            return 1
        try:
            content = args.input.read_text(encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"Failed to read npm audit file: {exc}\n")
            return 1
    else:
        if sys.stdin.isatty():
            sys.stderr.write("npm audit result input is empty (stdin is a tty)\n")
            return 1
        content = sys.stdin.read()

    return run_npm_filter(content, args.allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
