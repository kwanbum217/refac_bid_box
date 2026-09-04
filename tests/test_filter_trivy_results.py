"""tests/test_filter_trivy_results.py

Trivy 스캔 결과 판정 스크립트(scripts/filter_trivy_results.py) 단위 테스트.

검증 케이스:
1. 결과 파일 부재 시 fail-closed (종료 코드 1)
2. 빈 파일 시 fail-closed (종료 코드 1)
3. 스캐너 오류 객체 입력 시 fail-closed 및 진단 메시지 확인 (종료 코드 1)
4. 빈 객체 입력 시 fail-closed (종료 코드 1)
5. 최상위 list 입력 시 트레이스백 없이 진단 메시지와 함께 fail-closed (종료 코드 1)
6. 지원하지 않거나 누락된 SchemaVersion 입력 시 fail-closed (종료 코드 1)
7. Results 키 부재(스캐너 결과 미생성) 시 fail-closed (종료 코드 1)
8. Results 빈 list(정상 0건) 시 정상 통과 (종료 코드 0)
9. Vulnerabilities 오타입 시 fail-closed (종료 코드 1)
10. 취약점 없음(LOW/MEDIUM만 있음) 시 정상 통과 (종료 코드 0)
11. allowlist 로 전부 허용 시 정상 통과 (종료 코드 0)
12. allowlist 밖 항목 잔존 시 차단 (종료 코드 1)
13. allowlist 에 있는 패키지의 다른 advisory(CVE) 잔존 시 차단 (종료 코드 1)
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.filter_trivy_results import (
    run_filter,
)


def _make_allowlist_file(tmp_path: Path, trivy_entries: list[dict[str, str]]) -> Path:
    data = {
        "python": [],
        "npm": [],
        "trivy": trivy_entries,
    }
    path = tmp_path / "vulnerability-allowlist.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _make_trivy_file(tmp_path: Path, vulnerabilities: list[dict[str, str]]) -> Path:
    data = {
        "SchemaVersion": 2,
        "Results": [
            {
                "Target": "refac-bid-box:ci (debian 12.8)",
                "Class": "os-pkgs",
                "Type": "debian",
                "Vulnerabilities": vulnerabilities,
            }
        ],
    }
    path = tmp_path / "trivy-results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_missing_result_file_fails_closed(tmp_path: Path):
    """케이스 1: 결과 파일 부재 시 fail-closed(exit 1)로 차단됩니다."""
    missing_file = tmp_path / "non_existent_trivy.json"
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()
    out = io.StringIO()

    exit_code = run_filter(missing_file, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 1
    assert "not found" in err.getvalue()


def test_empty_result_file_fails_closed(tmp_path: Path):
    """케이스 2: 결과 파일이 비어있는 경우에도 fail-closed(exit 1)로 차단됩니다."""
    empty_file = tmp_path / "empty_trivy.json"
    empty_file.write_text("", encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(empty_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "empty" in err.getvalue()


def test_error_object_fails_with_diagnostic_message(tmp_path: Path):
    """케이스 3: 스캐너 에러를 담은 객체는 종료 코드 1로 막고 사유를 stderr에 출력합니다."""
    error_file = tmp_path / "error_trivy.json"
    error_file.write_text(
        json.dumps({"Error": "scanner failed to scan container image"}), encoding="utf-8"
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(error_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    err_output = err.getvalue()
    assert "scanner error reported" in err_output
    assert "scanner failed to scan container image" in err_output


def test_empty_object_fails_closed_without_traceback(tmp_path: Path):
    """케이스 4: 빈 객체 {}는 트레이스백 없이 종료 코드 1과 진단 문구를 냅니다."""
    empty_obj_file = tmp_path / "empty_obj_trivy.json"
    empty_obj_file.write_text("{}", encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(empty_obj_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "Trivy input contract violation" in err.getvalue()


def test_top_level_list_fails_closed_without_traceback(tmp_path: Path):
    """케이스 5: 최상위 list []는 트레이스백 없이 종료 코드 1과 진단 문구를 냅니다."""
    list_file = tmp_path / "list_trivy.json"
    list_file.write_text("[]", encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(list_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "top-level JSON must be an object (got list)" in err.getvalue()


def test_unsupported_schema_version_fails(tmp_path: Path):
    """케이스 6: SchemaVersion이 지원 범위(2)가 아니면 차단(exit 1)합니다."""
    schema_file = tmp_path / "bad_schema_trivy.json"
    schema_file.write_text(json.dumps({"SchemaVersion": 99, "Results": []}), encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(schema_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "missing or unsupported SchemaVersion" in err.getvalue()


def test_missing_results_key_fails(tmp_path: Path):
    """케이스 7: Results 키 자체가 없는 것은 스캐너 결과 미생성이므로 차단(exit 1)합니다."""
    no_results_file = tmp_path / "no_results_trivy.json"
    no_results_file.write_text(json.dumps({"SchemaVersion": 2}), encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(no_results_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "missing 'Results' key (scanner failed to produce results)" in err.getvalue()


def test_empty_results_list_passes_as_zero_vulnerabilities(tmp_path: Path):
    """케이스 8: Results가 빈 리스트([])인 것은 정상 0건 스캔이므로 통과(exit 0)합니다."""
    zero_vuln_file = tmp_path / "zero_results_trivy.json"
    zero_vuln_file.write_text(json.dumps({"SchemaVersion": 2, "Results": []}), encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_filter(zero_vuln_file, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all CRITICAL/HIGH vulnerabilities are in allowlist" in out.getvalue()


def test_invalid_vulnerabilities_type_fails(tmp_path: Path):
    """케이스 9: Vulnerabilities 필드가 리스트가 아닌 오타입이면 차단(exit 1)합니다."""
    bad_vulns_file = tmp_path / "bad_vulns_trivy.json"
    data: dict[str, Any] = {
        "SchemaVersion": 2,
        "Results": [
            {
                "Target": "refac-bid-box:ci",
                "Vulnerabilities": "invalid-string-not-a-list",
            }
        ],
    }
    bad_vulns_file.write_text(json.dumps(data), encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(bad_vulns_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "Vulnerabilities must be a list or absent" in err.getvalue()


def test_no_vulnerabilities_passes(tmp_path: Path):
    """케이스 10: 취약점이 없거나 LOW/MEDIUM만 있는 경우 정상 통과(exit 0)합니다."""
    trivy_file = _make_trivy_file(
        tmp_path,
        [
            {"VulnerabilityID": "CVE-2026-0001", "PkgName": "libfoo", "Severity": "LOW"},
            {"VulnerabilityID": "CVE-2026-0002", "PkgName": "libbar", "Severity": "MEDIUM"},
        ],
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_filter(trivy_file, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all CRITICAL/HIGH vulnerabilities are in allowlist" in out.getvalue()


def test_all_vulnerabilities_in_allowlist_passes(tmp_path: Path):
    """케이스 11: 모든 CRITICAL/HIGH 취약점이 allowlist에 등록되어 있으면 통과(exit 0)합니다."""
    trivy_file = _make_trivy_file(
        tmp_path,
        [
            {"VulnerabilityID": "CVE-2026-1111", "PkgName": "pkg-a", "Severity": "HIGH"},
            {"VulnerabilityID": "CVE-2026-2222", "PkgName": "pkg-b", "Severity": "CRITICAL"},
        ],
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "CVE-2026-1111",
                "package": "pkg-a",
                "reason": "테스트",
                "expires_on": "2026-12-31",
            },
            {
                "id": "CVE-2026-2222",
                "package": "pkg-b",
                "reason": "테스트",
                "expires_on": "2026-12-31",
            },
        ],
    )
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_filter(trivy_file, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all CRITICAL/HIGH vulnerabilities are in allowlist" in out.getvalue()


def test_unregistered_vulnerability_fails(tmp_path: Path):
    """케이스 12: allowlist 밖 항목이 남아있으면 차단(exit 1)하고 목록을 출력합니다."""
    trivy_file = _make_trivy_file(
        tmp_path,
        [
            {"VulnerabilityID": "CVE-2026-1111", "PkgName": "pkg-a", "Severity": "HIGH"},
            {"VulnerabilityID": "CVE-2026-3333", "PkgName": "pkg-c", "Severity": "CRITICAL"},
        ],
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "CVE-2026-1111",
                "package": "pkg-a",
                "reason": "테스트",
                "expires_on": "2026-12-31",
            },
        ],
    )
    err = io.StringIO()

    exit_code = run_filter(trivy_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "CVE-2026-3333 pkg-c CRITICAL" in err.getvalue()


def test_different_advisory_on_same_package_fails(tmp_path: Path):
    """케이스 13: allowlist에 있는 패키지라도 다른 advisory(CVE ID)가 발생하면 차단(exit 1)합니다."""
    trivy_file = _make_trivy_file(
        tmp_path,
        [
            {"VulnerabilityID": "CVE-2026-1111", "PkgName": "pkg-a", "Severity": "HIGH"},
            {"VulnerabilityID": "CVE-2026-9999", "PkgName": "pkg-a", "Severity": "HIGH"},
        ],
    )
    # allowlist에는 CVE-2026-1111 만 등록됨
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "CVE-2026-1111",
                "package": "pkg-a",
                "reason": "테스트",
                "expires_on": "2026-12-31",
            },
        ],
    )
    err = io.StringIO()

    exit_code = run_filter(trivy_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    # CVE-2026-9999 가 차단되어야 함
    assert "CVE-2026-9999 pkg-a HIGH" in err.getvalue()
    # 등록된 CVE-2026-1111 은 출력되지 않아야 함
    assert "CVE-2026-1111" not in err.getvalue()
