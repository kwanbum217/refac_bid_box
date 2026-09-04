"""scripts/filter_trivy_results.py

Trivy 컨테이너 스캔 결과를 allowlist와 대조하여 차단 여부를 판정합니다.

스캐너 스텝과 차단 판정 스텝을 분리하여, Trivy 스텝은 결과 파일 생성만 담당하고
본 스크립트가 단독으로 게이트 결정을 내립니다.
결과 파일 부재 또는 파싱 오류 시 fail-closed(종료 코드 1)로 차단합니다.
대조 키는 (CVE ID + 패키지 이름) 쌍으로 좁혀 정밀하게 판정합니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TRIVY_PATH = Path("trivy-results.json")
DEFAULT_ALLOWLIST_PATH = Path(".github/vulnerability-allowlist.yml")
# 핀된 aquasecurity/trivy-action@v0.36.0 이 실제로 생성하는 SchemaVersion 은 2 입니다.
# 미지 스키마에 대해서는 fail-closed(차단)를 엄격히 유지합니다.
SUPPORTED_SCHEMA_VERSIONS = (2, "2")


def validate_trivy_contract(trivy_data: Any) -> str | None:
    """Trivy 스캔 결과 JSON 입력 계약을 검증합니다. 위반 시 오류 사유를 반환하고 정상이면 None을 반환합니다."""
    if not isinstance(trivy_data, dict):
        return f"top-level JSON must be an object (got {type(trivy_data).__name__})"

    if "Error" in trivy_data and trivy_data["Error"] is not None:
        return f"scanner error reported: {trivy_data['Error']}"

    schema_version = trivy_data.get("SchemaVersion")
    if schema_version is None or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return f"missing or unsupported SchemaVersion: {schema_version!r} (expected {list(SUPPORTED_SCHEMA_VERSIONS)})"

    if "Results" not in trivy_data:
        return "missing 'Results' key (scanner failed to produce results)"

    results = trivy_data["Results"]
    if not isinstance(results, list):
        return f"'Results' must be a list (got {type(results).__name__})"

    for index, res in enumerate(results):
        if not isinstance(res, dict):
            return f"Results[{index}] must be an object (got {type(res).__name__})"
        if "Error" in res and res["Error"] is not None:
            return f"Results[{index}] reported scanner error: {res['Error']}"
        if "Vulnerabilities" in res:
            vulns = res["Vulnerabilities"]
            if vulns is not None and not isinstance(vulns, list):
                return f"Results[{index}].Vulnerabilities must be a list or absent (got {type(vulns).__name__})"

    return None


def load_allowlist_pairs(allowlist_path: Path) -> set[tuple[str, str]]:
    """allowlist 파일에서 trivy 섹션의 (id, package) 쌍 집합을 추출합니다."""
    if not allowlist_path.exists():
        raise FileNotFoundError(f"allowlist 파일이 없습니다: {allowlist_path}")
    raw_text = allowlist_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text) or {}
    entries = data.get("trivy") or []
    allowed: set[tuple[str, str]] = set()
    for item in entries:
        if isinstance(item, dict):
            vuln_id = str(item.get("id") or "").strip()
            pkg = str(item.get("package") or "").strip()
            if vuln_id and pkg:
                allowed.add((vuln_id, pkg))
    return allowed


def parse_trivy_vulnerabilities(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Trivy 결과 JSON에서 CRITICAL 및 HIGH 취약점을 (VulnerabilityID, PkgName, Severity)로 추출합니다."""
    vulnerabilities: list[tuple[str, str, str]] = []
    results = data.get("Results") or []
    if not isinstance(results, list):
        return vulnerabilities

    for res in results:
        if not isinstance(res, dict):
            continue
        vuln_list = res.get("Vulnerabilities") or []
        if not isinstance(vuln_list, list):
            continue
        for v in vuln_list:
            if not isinstance(v, dict):
                continue
            sev = str(v.get("Severity") or "").upper()
            if sev in ("CRITICAL", "HIGH"):
                vuln_id = str(v.get("VulnerabilityID") or "").strip()
                pkg_name = str(v.get("PkgName") or "").strip()
                vulnerabilities.append((vuln_id, pkg_name, sev))
    return vulnerabilities


def filter_vulnerabilities(
    vulnerabilities: list[tuple[str, str, str]],
    allowed_pairs: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """allowlist에 등록된 (id, package) 쌍을 제외하고 남은 취약점 목록을 반환합니다."""
    remaining: list[tuple[str, str, str]] = []
    for vuln_id, pkg_name, sev in vulnerabilities:
        if (vuln_id, pkg_name) not in allowed_pairs:
            remaining.append((vuln_id, pkg_name, sev))
    return remaining


def run_filter(
    trivy_path: Path,
    allowlist_path: Path,
    err_stream=sys.stderr,
    out_stream=sys.stdout,
) -> int:
    """Trivy 결과를 검사하고 종료 코드를 반환합니다."""
    if not trivy_path.exists():
        err_stream.write(f"Trivy result file not found: {trivy_path}\n")
        return 1

    try:
        content = trivy_path.read_text(encoding="utf-8").strip()
        if not content:
            err_stream.write(f"Trivy result file is empty: {trivy_path}\n")
            return 1
        trivy_data = json.loads(content)
    except Exception as exc:
        err_stream.write(f"Failed to parse Trivy result file: {exc}\n")
        return 1

    contract_error = validate_trivy_contract(trivy_data)
    if contract_error:
        err_stream.write(f"Trivy input contract violation: {contract_error}\n")
        return 1

    try:
        allowed_pairs = load_allowlist_pairs(allowlist_path)
    except Exception as exc:
        err_stream.write(f"Failed to load allowlist: {exc}\n")
        return 1

    all_vulns = parse_trivy_vulnerabilities(trivy_data)
    remaining = filter_vulnerabilities(all_vulns, allowed_pairs)

    if remaining:
        err_stream.write("Trivy failed; CRITICAL/HIGH not in allowlist:\n")
        for vuln_id, pkg, sev in remaining:
            err_stream.write(f"  - {vuln_id} {pkg} {sev}\n")
        return 1

    out_stream.write("Trivy: all CRITICAL/HIGH vulnerabilities are in allowlist\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filter Trivy scan results against allowlist")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_TRIVY_PATH,
        help="Path to trivy results JSON file",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="Path to vulnerability allowlist YAML",
    )
    args = parser.parse_args(argv)
    return run_filter(args.input, args.allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
