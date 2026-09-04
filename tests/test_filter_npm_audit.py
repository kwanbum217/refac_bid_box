"""tests/test_filter_npm_audit.py

npm audit 판정 스크립트(scripts/filter_npm_audit.py) 단위 테스트.

검증 케이스:
1. 결과 파일/입력 부재 시 fail-closed (종료 코드 1)
2. 취약점 없음 시 정상 통과 (종료 코드 0)
3. allowlist 로 전부 허용 시 정상 통과 (종료 코드 0, nanoid GHSA 예외 검증)
4. allowlist 밖 항목 잔존 시 차단 (종료 코드 1)
5. allowlist 에 있는 패키지의 다른 advisory 잔존 시 차단 (종료 코드 1)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

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


def _make_audit_json(vulnerabilities: dict) -> str:
    data = {
        "auditReportVersion": 2,
        "vulnerabilities": vulnerabilities,
        "metadata": {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": 1,
                "critical": 0,
                "total": 1,
            }
        },
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


def test_no_vulnerabilities_passes(tmp_path: Path):
    """케이스 2: HIGH/CRITICAL 취약점이 없으면 정상 통과(exit 0)합니다."""
    audit_json = _make_audit_json(
        {
            "some-pkg": {
                "name": "some-pkg",
                "severity": "low",
                "via": [{"title": "Low issue", "severity": "low"}],
            }
        }
    )
    allowlist_file = _make_allowlist_file(tmp_path, [])
    out = io.StringIO()
    err = io.StringIO()

    exit_code = run_npm_filter(audit_json, allowlist_file, err_stream=err, out_stream=out)

    assert exit_code == 0
    assert "all HIGH/CRITICAL vulnerabilities are in allowlist" in out.getvalue()


def test_all_vulnerabilities_in_allowlist_passes_including_nanoid(tmp_path: Path):
    """케이스 3: nanoid 를 포함해 allowlist 에 등록된 (package, advisory ID)는 통과합니다."""
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
        }
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
    """케이스 4: allowlist 밖 항목이 잔존하면 차단(exit 1)하고 항목을 출력합니다."""
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
        }
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
    """케이스 5: allowlist 에 있는 패키지라도 다른 advisory 가 발생하면 차단(exit 1)합니다."""
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
        }
    )
    # allowlist 에는 GHSA-2v37-7h3g-55p8 만 등록되어 있음
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
    # 허용된 GHSA 는 출력되지 않아야 함
    assert "GHSA-2v37-7h3g-55p8" not in err.getvalue()
