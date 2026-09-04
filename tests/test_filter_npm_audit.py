"""tests/test_filter_npm_audit.py

npm audit 판정 스크립트(scripts/filter_npm_audit.py) 단위 테스트.

검증 케이스:
1. 결과 파일/입력 부재 시 fail-closed (종료 코드 1)
2. 스캐너 오류 객체(error 키) 입력 시 fail-closed 및 진단 메시지 확인 (종료 코드 1)
3. 스캐너 오류 배열(errors 키) 입력 시 fail-closed 및 진단 메시지 확인 (종료 코드 1)
4. 빈 객체 입력 시 fail-closed (종료 코드 1)
5. 최상위 list 입력 시 트레이스백 없이 진단 메시지와 함께 fail-closed (종료 코드 1)
6. auditReportVersion 누락 시 fail-closed (종료 코드 1)
7. metadata 취약점 패키지 건수와 vulnerabilities 매핑 불일치 시 fail-closed (종료 코드 1)
8. 문자열 via 미해소(원인 패키지 부재/advisory 없음) 시 fail-closed 차단 (종료 코드 1)
9. 문자열 via 해소(원인 패키지에 advisory 존재, metadata.high=2) 시 중복 없이 allowlist 대조 정상 통과 (종료 코드 0)
10. 단일 패키지에 다중 advisory 존재 시(metadata.high=1) 정상 파싱 및 allowlist 통과 (거짓 차단 방지, 종료 코드 0)
11. 정상 0건 취약점 시 정상 통과 (종료 코드 0)
12. allowlist 로 전부 허용 시 정상 통과 (종료 코드 0, nanoid GHSA 예외 검증)
13. allowlist 밖 항목 잔존 시 차단 (종료 코드 1)
14. allowlist 에 있는 패키지의 다른 advisory 잔존 시 차단 (종료 코드 1)
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.filter_npm_audit import (
    run_npm_filter,
)


def _make_allowlist_file(tmp_path: Path, npm_entries: list[dict[str, str]]) -> Path:
    data = {
        "python": [],
        "npm": npm_entries,
        "trivy": [],
    }
    path = tmp_path / "vulnerability-allowlist.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _make_audit_json(
    vulnerabilities: dict[str, Any],
    high: int = 1,
    critical: int = 0,
    audit_report_version: int | None = 2,
    metadata: dict[str, Any] | None = None,
) -> str:
    data: dict[str, Any] = {}
    if audit_report_version is not None:
        data["auditReportVersion"] = audit_report_version
    data["vulnerabilities"] = vulnerabilities
    if metadata is not None:
        data["metadata"] = metadata
    else:
        data["metadata"] = {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": high,
                "critical": critical,
                "total": high + critical,
            }
        }
    return json.dumps(data)


def test_missing_or_empty_input_fails_closed(tmp_path: Path):
    """케이스 1: 입력이 비어있거나 부재한 경우 fail-closed(exit 1)로 차단됩니다."""
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    assert run_npm_filter(None, allowlist_file, err_stream=err) == 1
    assert "empty" in err.getvalue()

    err2 = io.StringIO()
    assert run_npm_filter("   ", allowlist_file, err_stream=err2) == 1
    assert "empty" in err2.getvalue()

    err3 = io.StringIO()
    assert run_npm_filter("invalid-json{", allowlist_file, err_stream=err3) == 1
    assert "Failed to parse" in err3.getvalue()


def test_error_object_fails_with_diagnostic_message(tmp_path: Path):
    """케이스 2: 스캐너 에러(error 키)를 담은 객체는 종료 코드 1로 막고 사유를 stderr에 출력합니다."""
    error_json = json.dumps({"error": {"summary": "registry unavailable", "code": "E503"}})
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter(error_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    err_output = err.getvalue()
    assert "scanner error reported" in err_output
    assert "registry unavailable" in err_output


def test_errors_array_fails_with_diagnostic_message(tmp_path: Path):
    """케이스 3: 스캐너 에러 배열(errors 키)을 담은 객체는 종료 코드 1로 막고 사유를 stderr에 출력합니다."""
    errors_json = json.dumps(
        {
            "errors": [{"code": "ENOTFOUND", "detail": "getaddrinfo ENOTFOUND registry.npmjs.org"}],
            "vulnerabilities": {},
        }
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter(errors_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    err_output = err.getvalue()
    assert "scanner errors reported" in err_output
    assert "ENOTFOUND" in err_output


def test_empty_object_fails_closed_without_traceback(tmp_path: Path):
    """케이스 4: 빈 객체 {}는 트레이스백 없이 종료 코드 1과 진단 문구를 냅니다."""
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter("{}", allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "npm audit input contract violation" in err.getvalue()


def test_top_level_list_fails_closed_without_traceback(tmp_path: Path):
    """케이스 5: 최상위 list []는 트레이스백 없이 종료 코드 1과 진단 문구를 냅니다."""
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter("[]", allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "top-level JSON must be an object (got list)" in err.getvalue()


def test_missing_audit_report_version_fails(tmp_path: Path):
    """케이스 6: auditReportVersion 필드가 누락되면 계약 위반으로 차단(exit 1)합니다."""
    audit_json = _make_audit_json(
        {},
        high=0,
        critical=0,
        audit_report_version=None,
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "missing required 'auditReportVersion' field" in err.getvalue()


def test_metadata_count_mismatch_fails(tmp_path: Path):
    """케이스 7: metadata에 명시된 high+critical 수와 vulnerabilities 패키지 수가 불일치하면 차단(exit 1)합니다."""
    # metadata는 high=3이라고 주장하지만 vulnerabilities에는 1개 패키지만 존재
    audit_json = _make_audit_json(
        {
            "pkg-a": {
                "name": "pkg-a",
                "severity": "high",
                "via": [
                    {"url": "https://github.com/advisories/GHSA-1111-1111-1111", "severity": "high"}
                ],
            }
        },
        high=3,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-1111-1111-1111",
                "package": "pkg-a",
                "reason": "테스트",
                "expires_on": "2026-12-31",
            }
        ],
    )
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "metadata count mismatch" in err.getvalue()
    assert "expected high+critical=3 packages, found 1 in vulnerabilities mapping" in err.getvalue()


def test_string_via_unresolved_fails(tmp_path: Path):
    """케이스 8: 문자열 via만 있고 원인 패키지가 vulnerabilities에 없으면 UNKNOWN으로 차단(exit 1)합니다."""
    audit_json = _make_audit_json(
        {
            "direct-pkg": {
                "name": "direct-pkg",
                "severity": "high",
                "via": ["missing-cause-pkg"],
            }
        },
        high=1,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "direct-pkg (UNKNOWN, HIGH)" in err.getvalue()


def test_string_via_resolved_passes_when_allowlisted(tmp_path: Path):
    """케이스 9: 전이 의존성(direct-pkg)과 원인 패키지(cause-pkg)가 존재(metadata.high=2)할 때, 해소된 원인 패키지가 검사됩니다."""
    audit_json = _make_audit_json(
        {
            "direct-pkg": {
                "name": "direct-pkg",
                "severity": "high",
                "via": ["cause-pkg"],
            },
            "cause-pkg": {
                "name": "cause-pkg",
                "severity": "high",
                "via": [
                    {
                        "name": "cause-pkg",
                        "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
                        "severity": "high",
                    }
                ],
            },
        },
        high=2,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-aaaa-bbbb-cccc",
                "package": "cause-pkg",
                "reason": "해소된 원인 패키지 예외",
                "expires_on": "2026-12-31",
            }
        ],
    )
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all HIGH/CRITICAL vulnerabilities are in allowlist" in out.getvalue()


def test_single_package_multiple_advisories_passes_when_allowlisted(tmp_path: Path):
    """케이스 10: 패키지 1개(metadata.high=1)에 high advisory가 2개인 정상 출력이 거짓 차단 없이 정상 통과합니다."""
    audit_json = _make_audit_json(
        {
            "multi-vuln-pkg": {
                "name": "multi-vuln-pkg",
                "severity": "high",
                "via": [
                    {
                        "url": "https://github.com/advisories/GHSA-1111-2222-3333",
                        "severity": "high",
                    },
                    {
                        "url": "https://github.com/advisories/GHSA-4444-5555-6666",
                        "severity": "high",
                    },
                ],
            }
        },
        high=1,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-1111-2222-3333",
                "package": "multi-vuln-pkg",
                "reason": "사유 1",
                "expires_on": "2026-12-31",
            },
            {
                "id": "GHSA-4444-5555-6666",
                "package": "multi-vuln-pkg",
                "reason": "사유 2",
                "expires_on": "2026-12-31",
            },
        ],
    )
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all HIGH/CRITICAL vulnerabilities are in allowlist" in out.getvalue()


def test_no_vulnerabilities_passes(tmp_path: Path):
    """케이스 11: HIGH/CRITICAL 취약점이 0건이면 정상 통과(exit 0)합니다."""
    audit_json = _make_audit_json(
        {
            "some-pkg": {
                "name": "some-pkg",
                "severity": "low",
                "via": [{"title": "Low issue", "severity": "low"}],
            }
        },
        high=0,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all HIGH/CRITICAL vulnerabilities are in allowlist" in out.getvalue()


def test_all_vulnerabilities_in_allowlist_passes_including_nanoid(tmp_path: Path):
    """케이스 12: nanoid를 포함해 allowlist에 등록된 (package, advisory ID)는 통과합니다."""
    audit_json = _make_audit_json(
        {
            "nanoid": {
                "name": "nanoid",
                "severity": "high",
                "isDirect": False,
                "via": [
                    {
                        "source": 1097678,
                        "name": "nanoid",
                        "dependency": "nanoid",
                        "title": "Predictable results in nanoid generation",
                        "url": "https://github.com/advisories/GHSA-2v37-7h3g-55p8",
                        "severity": "high",
                        "range": "<3.3.8",
                    }
                ],
            }
        },
        high=1,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-2v37-7h3g-55p8",
                "package": "nanoid",
                "reason": "Vite/React 전이 의존성",
                "expires_on": "2026-10-31",
            }
        ],
    )
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all HIGH/CRITICAL vulnerabilities are in allowlist" in out.getvalue()


def test_unregistered_vulnerability_fails(tmp_path: Path):
    """케이스 13: allowlist 밖 항목이 잔존하면 차단(exit 1)하고 항목을 출력합니다."""
    audit_json = _make_audit_json(
        {
            "other-pkg": {
                "name": "other-pkg",
                "severity": "high",
                "via": [
                    {
                        "name": "other-pkg",
                        "url": "https://github.com/advisories/GHSA-xxxx-xxxx-xxxx",
                        "severity": "high",
                    }
                ],
            }
        },
        high=1,
        critical=0,
    )
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-2v37-7h3g-55p8",
                "package": "nanoid",
                "reason": "사유",
                "expires_on": "2026-10-31",
            }
        ],
    )
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "other-pkg (GHSA-xxxx-xxxx-xxxx, HIGH)" in err.getvalue()


def test_different_advisory_on_same_package_fails(tmp_path: Path):
    """케이스 14: allowlist에 있는 패키지라도 다른 advisory가 발생하면 차단(exit 1)합니다."""
    audit_json = _make_audit_json(
        {
            "nanoid": {
                "name": "nanoid",
                "severity": "high",
                "via": [
                    {
                        "url": "https://github.com/advisories/GHSA-2v37-7h3g-55p8",
                        "severity": "high",
                    },
                    {
                        "url": "https://github.com/advisories/GHSA-neww-advi-sory",
                        "severity": "high",
                    },
                ],
            }
        },
        high=1,
        critical=0,
    )
    # allowlist에는 GHSA-2v37-7h3g-55p8만 등록되어 있음
    allowlist_file = _make_allowlist_file(
        tmp_path,
        [
            {
                "id": "GHSA-2v37-7h3g-55p8",
                "package": "nanoid",
                "reason": "기존 예외",
                "expires_on": "2026-10-31",
            }
        ],
    )
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err)

    assert exit_code == 1
    assert "nanoid (GHSA-neww-advi-sory, HIGH)" in err.getvalue()
    # 허용된 GHSA는 출력되지 않아야 함
    assert "GHSA-2v37-7h3g-55p8" not in err.getvalue()
