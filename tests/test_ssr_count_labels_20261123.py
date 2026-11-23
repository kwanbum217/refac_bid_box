"""SSR 비교 화면 건수 카드 라벨의 집계 범위 일치 회귀 테스트.

2026-11-22~23 집계 정의 변경으로 비교 통계의 공고·낙찰 건수는 4대 업종
(파견·경비·위생관리·유료직업소개) 업종 제한 공고만 세고, 공고는 최신 차수
한 행에서 최신 차수가 취소공고인 것을 뺀 값입니다. 카드 라벨이 '전체 기간'
만 말해 업종 범위를 드러내지 않던 문제를 고정하고, 값 계산 코드는 그대로인지
함께 확인합니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/compare.html"
ANNOUNCE_LABEL = "입찰공고 건수 (4대 업종·전체 기간)"
RESULT_LABEL = "낙찰 건수 (4대 업종·전체 기간)"


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="count_label_tester",
        password=make_password("pw-test-1234"),
        email="count-label@example.com",
        nickname="건수 라벨 검증",
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


def test_비교_화면_건수_카드_라벨이_4대_업종_전체_기간을_드러낸다(auth_client):
    """렌더된 비교 화면에 4대 업종 범위를 밝힌 건수 라벨이 들어 있다."""
    body = auth_client.get("/bids/compare/").text

    assert ANNOUNCE_LABEL in body
    assert RESULT_LABEL in body
    assert "입찰공고 건수 (전체 기간)" not in body
    assert "낙찰 건수 (전체 기간)" not in body


def test_건수_값_계산_코드는_바꾸지_않는다():
    """카드 숫자를 채우는 자바스크립트 계산·대입은 그대로다."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert (
        "document.getElementById('announceCount').textContent = "
        "(data.announce_count || 0).toLocaleString() + '건';" in template
    )
    assert (
        "document.getElementById('resultCount').textContent = "
        "(data.result_count || 0).toLocaleString() + '건';" in template
    )
