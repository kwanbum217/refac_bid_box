"""tests/test_filter_trivy_results.py

Trivy 스캔 결과 판정 스크립트(scripts/filter_trivy_results.py) 단위 테스트.

검증 케이스:
1. 결과 파일 부재 시 fail-closed (종료 코드 1)
2. 취약점 없음 시 정상 통과 (종료 코드 0)
3. allowlist 로 전부 허용 시 정상 통과 (종료 코드 0)
4. allowlist 밖 항목 잔존 시 차단 (종료 코드 1)
5. allowlist 에 있는 패키지의 다른 advisory(CVE) 잔존 시 차단 (종료 코드 1)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

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
    """결과 파일이 비어있는 경우에도 fail-closed(exit 1)로 차단됩니다."""
    empty_file = tmp_path / "empty_trivy.json"
    empty_file.write_text("", encoding="utf-8")
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_filter(empty_file, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "empty" in err.getvalue()


def test_no_vulnerabilities_passes(tmp_path: Path):
    """케이스 2: 취약점이 없거나 LOW/MEDIUM만 있는 경우 정상 통과(exit 0)합니다."""
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
    """케이스 3: 모든 CRITICAL/HIGH 취약점이 allowlist에 등록되어 있으면 통과(exit 0)합니다."""
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
    """케이스 4: allowlist 밖 항목이 남아있으면 차단(exit 1)하고 목록을 출력합니다."""
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
    """케이스 5: allowlist에 있는 패키지라도 다른 advisory(CVE ID)가 발생하면 차단(exit 1)합니다."""
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
