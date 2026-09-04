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


def is_cause_resolved(
    pkg_name: str, vuln_map: dict[str, Any], visited: set[str] | None = None
) -> bool:
    """원인 패키지가 궁극적으로 유효한 HIGH/CRITICAL advisory를 가지고 존재하는지 확인합니다."""
    if visited is None:
        visited = set()
    if pkg_name in visited:
        return False
    visited.add(pkg_name)

    info = vuln_map.get(pkg_name)
    if not isinstance(info, dict):
        return False

    via_list = info.get("via") or []
    pkg_sev = str(info.get("severity") or "").lower()

    # 1. dict via에서 HIGH/CRITICAL advisory가 있는지 확인
    for item in via_list:
        if isinstance(item, dict):
            item_sev = str(item.get("severity") or pkg_sev).lower()
            if item_sev in ("high", "critical"):
                return True

    # 2. str via를 재귀적으로 추적
    for item in via_list:
        if (
            isinstance(item, str)
            and item.strip()
            and is_cause_resolved(item.strip(), vuln_map, visited)
        ):
            return True

    return False


def validate_npm_audit_contract(audit_data: Any) -> str | None:
    """npm audit JSON 입력 계약을 검증합니다. 위반 시 오류 사유를 반환하고 유효하면 None을 반환합니다."""
    if not isinstance(audit_data, dict):
        return f"top-level JSON must be an object (got {type(audit_data).__name__})"

    if "error" in audit_data and audit_data["error"] is not None:
        return f"scanner error reported: {audit_data['error']}"

    if "errors" in audit_data and audit_data["errors"] is not None:
        errors_val = audit_data["errors"]
        if (isinstance(errors_val, list) and len(errors_val) > 0) or (
            not isinstance(errors_val, list) and errors_val
        ):
            return f"scanner errors reported: {errors_val}"

    if "auditReportVersion" not in audit_data or audit_data["auditReportVersion"] is None:
        return "missing required 'auditReportVersion' field"

    if "vulnerabilities" not in audit_data or not isinstance(audit_data["vulnerabilities"], dict):
        return "missing or invalid 'vulnerabilities' mapping"

    if "metadata" not in audit_data or not isinstance(audit_data.get("metadata"), dict):
        return "missing or invalid 'metadata' mapping"

    meta_vulns = audit_data["metadata"].get("vulnerabilities")
    if not isinstance(meta_vulns, dict):
        return "missing or invalid 'metadata.vulnerabilities' mapping"

    meta_high = meta_vulns.get("high")
    meta_critical = meta_vulns.get("critical")
    if not isinstance(meta_high, int) or not isinstance(meta_critical, int):
        return "metadata.vulnerabilities 'high' and 'critical' counts must be integers"

    return None


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
            # dict 항목이 없는 경우: 문자열 via(전이 의존성 링크) 또는 빈 via 목록
            str_entries = [v for v in via_list if isinstance(v, str) and v.strip()]
            if str_entries and any(
                is_cause_resolved(cause, vuln_map, {pkg_name}) for cause in str_entries
            ):
                # 원인 패키지가 vulnerabilities에 유효한 HIGH/CRITICAL advisory를 가지고 존재하므로
                # 해당 원인 패키지가 독립적으로 검사되며 여기서는 중복 차단하지 않습니다.
                pass
            else:
                # 원인 패키지가 없거나, advisory가 없거나, via가 비어있는 경우 fail-closed
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

    contract_error = validate_npm_audit_contract(audit_data)
    if contract_error:
        err_stream.write(f"npm audit input contract violation: {contract_error}\n")
        return 1

    try:
        allowed_pairs = load_npm_allowlist_pairs(allowlist_path)
    except Exception as exc:
        err_stream.write(f"Failed to load allowlist: {exc}\n")
        return 1

    all_vulns = parse_npm_vulnerabilities(audit_data)

    # metadata의 high + critical 합계와 파싱 결과의 설명 가능성(explainability) 검증
    meta_vulns = audit_data["metadata"]["vulnerabilities"]
    expected_pkg_count = meta_vulns["high"] + meta_vulns["critical"]

    vuln_map = audit_data.get("vulnerabilities") or {}
    target_pkgs = {
        pkg_name
        for pkg_name, info in vuln_map.items()
        if isinstance(info, dict)
        and str(info.get("severity") or "").lower() in ("high", "critical")
    }

    # 1. metadata의 high+critical 패키지 수와 vulnerabilities 맵 내의 high/critical 패키지 수 일치 검증
    if len(target_pkgs) != expected_pkg_count:
        err_stream.write(
            f"npm audit input contract violation: metadata count mismatch "
            f"(expected high+critical={expected_pkg_count} packages, found {len(target_pkgs)} in vulnerabilities mapping)\n"
        )
        return 1

    # 2. metadata는 0건인데 파서가 high/critical 취약점을 찾은 경우
    if expected_pkg_count == 0 and len(all_vulns) > 0:
        err_stream.write(
            "npm audit input contract violation: metadata reports 0 high/critical packages, "
            f"but parser found {len(all_vulns)} vulnerabilities\n"
        )
        return 1

    # 3. metadata는 1건 이상인데 파서가 0건을 찾은 경우
    if expected_pkg_count > 0 and len(all_vulns) == 0:
        err_stream.write(
            f"npm audit input contract violation: metadata reports {expected_pkg_count} high/critical packages, "
            "but parser found 0 vulnerabilities\n"
        )
        return 1

    # 4. 대상 패키지들이 파싱된 취약점(all_vulns) 또는 유효한 전이 체인으로 완전히 설명되는지 검증
    parsed_pkgs = {pkg for pkg, _adv_id, _sev in all_vulns}
    unaccounted_pkgs: list[str] = []
    for pkg in target_pkgs:
        if pkg in parsed_pkgs:
            continue
        info = vuln_map[pkg]
        via_list = info.get("via") or []
        str_entries = [v for v in via_list if isinstance(v, str) and v.strip()]
        if not any(is_cause_resolved(cause, vuln_map, {pkg}) for cause in str_entries):
            unaccounted_pkgs.append(pkg)

    if unaccounted_pkgs:
        err_stream.write(
            f"npm audit input contract violation: target packages not accounted for by parser: {unaccounted_pkgs}\n"
        )
        return 1

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
    parser.add_argument(
        "--stderr-file",
        type=Path,
        default=None,
        help="Optional path to npm audit stderr log file for error diagnostics",
    )
    args = parser.parse_args(argv)

    stderr_diag = ""
    if args.stderr_file is not None and args.stderr_file.exists():
        try:
            stderr_diag = args.stderr_file.read_text(encoding="utf-8").strip()
        except OSError:
            stderr_diag = ""

    if args.input is not None:
        if not args.input.exists():
            sys.stderr.write(f"npm audit result file not found: {args.input}\n")
            if stderr_diag:
                sys.stderr.write(f"npm audit stderr log:\n{stderr_diag}\n")
            return 1
        try:
            content = args.input.read_text(encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"Failed to read npm audit file: {exc}\n")
            if stderr_diag:
                sys.stderr.write(f"npm audit stderr log:\n{stderr_diag}\n")
            return 1
    else:
        if sys.stdin.isatty():
            sys.stderr.write("npm audit result input is empty (stdin is a tty)\n")
            return 1
        content = sys.stdin.read()

    exit_code = run_npm_filter(content, args.allowlist)
    if exit_code != 0 and stderr_diag:
        sys.stderr.write(f"npm audit stderr log:\n{stderr_diag}\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
