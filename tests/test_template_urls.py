"""
tests/test_template_urls.py

화면 템플릿이 부르는 주소가 실제로 등록된 라우트인지 검증합니다.

이식 과정에서 chat.html 의 자동화 작업 제어 URL 3개가 원본 Django 경로
(`/chatbot/api/automation/job/<id>/...`)로 남아 있었습니다. 화면은 정상으로 보이지만
"요청 중지", "확인 실행" 버튼과 진행 상황 폴링이 전부 404 였습니다. 단위 테스트가
API 를 직접 호출하는 방식이라 아무도 눈치채지 못했습니다.
"""

import re
from pathlib import Path

import pytest

from src.app.core.templating import URL_MAP
from src.app.main import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "src" / "app" / "templates"

# 자리표시자를 라우트 파라미터로 되돌리기 위한 치환입니다.
PLACEHOLDER = "__JOB_ID__"


def _registered_paths() -> set[str]:
    """app.routes 는 include_router 를 래퍼로 감싸 평탄화되지 않습니다.

    OpenAPI 스키마가 실제로 노출되는 /api/ 경로의 정확한 목록입니다.
    """
    return set(app.openapi()["paths"])


def _normalize(path: str) -> str:
    """런타임에 값이 끼워지는 자리를 라우트 파라미터 형태로 되돌립니다."""
    path = path.replace(PLACEHOLDER, "{job_id}")
    path = re.sub(r"\{\w+\}", lambda m: m.group(0), path)
    return path.rstrip("/") or "/"


def _template_url_literals() -> list[tuple[str, str]]:
    """템플릿에 하드코딩된 /api/ 경로 문자열을 모읍니다."""
    found = []
    for template in TEMPLATE_DIR.rglob("*.html"):
        for literal in re.findall(r"'(/api/[^']*)'", template.read_text(encoding="utf-8")):
            found.append((template.name, literal))
    return found


@pytest.mark.parametrize("name", sorted(n for n in URL_MAP if n.startswith("chatbot:")))
def test_chatbot_url_map_entries_point_at_registered_routes(name):
    pattern = URL_MAP[name]
    if not pattern.startswith("/api/"):
        pytest.skip("SSR 페이지 경로는 별도 라우터에서 처리합니다.")
    assert _normalize(pattern) in {_normalize(p) for p in _registered_paths()}


@pytest.mark.parametrize(
    ("template", "literal"),
    _template_url_literals(),
    ids=[f"{t}:{u}" for t, u in _template_url_literals()],
)
def test_hardcoded_api_urls_in_templates_exist(template, literal):
    """템플릿에 직접 적힌 /api/ 주소가 실제 라우트여야 합니다."""
    assert _normalize(literal) in {_normalize(p) for p in _registered_paths()}


def test_no_template_references_original_django_automation_paths():
    """원본 Django 경로가 남아 있으면 화면 버튼이 404 가 됩니다."""
    offenders = []
    for template in TEMPLATE_DIR.rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        for match in re.findall(r"/chatbot/api/[\w/{}_.-]*", text):
            offenders.append(f"{template.name}: {match}")
    assert offenders == []


@pytest.mark.parametrize(
    "name",
    [
        "chatbot:automation_job_confirm",
        "chatbot:automation_job_status",
        "chatbot:automation_job_cancel",
    ],
)
def test_automation_control_urls_are_registered_in_url_map(name):
    """세 버튼 모두 url() 을 거치도록 URL_MAP 에 등록되어 있어야 합니다."""
    assert name in URL_MAP
    assert "{job_id}" in URL_MAP[name]
