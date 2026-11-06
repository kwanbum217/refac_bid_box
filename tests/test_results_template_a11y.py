"""낙찰 결과 화면 검색 입력의 접근성 이름 계약을 렌더 결과로 고정합니다.

검색 입력은 상시 노출되는 폼 컨트롤인데 화면 읽기 프로그램이 읽을 이름이
없었습니다. placeholder 는 접근성 이름으로 신뢰할 수 없으므로 aria-label 로
고정하고, 이후 템플릿 수정이 이 속성을 지우지 않도록 렌더 결과를 검사합니다.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser

RESULTS_PATH = "/bids/results/"
# base.html 의 전역 헤더 검색도 name="q" 를 쓰므로 결과 화면 전용 placeholder 로 구분합니다.
SEARCH_INPUT = re.compile(
    r'<input\b[^>]*\bplaceholder="공고명, 번호, 업체 검색"[^>]*>',
    re.DOTALL,
)


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="results_a11y_tester",
        password=make_password("pw-test-1234"),
        email="results-a11y@example.com",
        nickname="검색 접근성 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _search_input(auth_client: TestClient) -> str:
    response = auth_client.get(RESULTS_PATH)
    assert response.status_code == 200, RESULTS_PATH
    match = SEARCH_INPUT.search(response.text)
    assert match, "낙찰 결과 검색 입력을 찾지 못했습니다"
    assert 'name="q"' in match.group(0)
    return match.group(0)


def test_results_search_input_has_aria_label(auth_client):
    markup = _search_input(auth_client)

    label = re.search(r'aria-label="([^"]*)"', markup)
    assert label, "검색 입력에 aria-label 이 없습니다"
    assert label.group(1).strip() != "", "검색 입력의 aria-label 이 비어 있습니다"


def test_results_search_input_keeps_placeholder(auth_client):
    markup = _search_input(auth_client)

    assert 'placeholder="공고명, 번호, 업체 검색"' in markup
