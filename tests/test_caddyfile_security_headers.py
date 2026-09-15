"""tests/test_caddyfile_security_headers.py

deploy/Caddyfile 보안 응답 헤더 및 프록시 설정 검증 테스트.
- Strict-Transport-Security "max-age=31536000" 존재 검증 (includeSubDomains, preload 제외)
- X-Content-Type-Options "nosniff" 존재 검증
- X-Frame-Options "SAMEORIGIN" 존재 검증
- Referrer-Policy "strict-origin-when-cross-origin" 존재 검증
- -Server (Server 헤더 제거) 존재 검증
- Content-Security-Policy 부재 검증 (SSR 인라인 스크립트 호환성)
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CADDYFILE_PATH = REPO_ROOT / "deploy" / "Caddyfile"


def test_caddyfile_security_headers_present_and_csp_absent():
    assert CADDYFILE_PATH.exists(), f"{CADDYFILE_PATH} 가 존재해야 합니다."
    content = CADDYFILE_PATH.read_text(encoding="utf-8")

    # 4개 필수 보안 응답 헤더
    assert 'Strict-Transport-Security "max-age=31536000"' in content
    assert 'X-Content-Type-Options "nosniff"' in content
    assert 'X-Frame-Options "SAMEORIGIN"' in content
    assert 'Referrer-Policy "strict-origin-when-cross-origin"' in content

    # Server 헤더 제거 지시어
    assert "-Server" in content

    # 금지 항목 검증: includeSubDomains, preload, Content-Security-Policy 부재
    assert "includeSubDomains" not in content
    assert "preload" not in content
    assert "Content-Security-Policy" not in content

    # 기본 프록시 설정 유지 검증
    assert "auto_https off" in content
    assert "reverse_proxy app:8000" in content
