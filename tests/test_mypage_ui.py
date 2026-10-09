"""마이페이지(GET /accounts/mypage/) SSR 화면 시험.

정본: .orca/capsules/task_1a01f8e9389f/capsule.yaml.
 - 비로그인 요청은 로그인 화면으로 리다이렉트된다.
 - 로그인 요청은 200 으로 계정·회사·정량 원자료 섹션을 그린다.
 - 프로필이 없으면 각 섹션에 미입력 안내를 보여 준다.
 - 사이드바 사용자 영역과 사이드바 없는 화면 헤더에서 진입 링크가 노출된다.
 - 비밀번호 해시 등 민감 필드는 화면에 나오지 않는다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.company_profiles import AccountCompanyProfile, AccountQualificationFact
from src.app.services.evaluation_rules import (
    REPUTATION_ITEMS_BY_CODE,
    find_reputation_item,
)

MYPAGE_URL = "/accounts/mypage/"


def _create_user(db, *, username: str = "mypage_tester") -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-test-1234"),
        email=f"{username}@example.com",
        nickname="마이페이지 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def test_mypage_redirects_anonymous_to_login(client):
    """비로그인 요청은 next 를 실어 로그인 화면으로 리다이렉트된다."""
    response = client.get(MYPAGE_URL, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/login/?next={MYPAGE_URL}"


def test_mypage_renders_account_company_and_qualification(client, isolated_db):
    """로그인 회원은 계정·회사·정량 원자료 섹션을 모두 본다."""
    user = _create_user(isolated_db)
    isolated_db.add(
        AccountCompanyProfile(
            user_id=user.id,
            company_name="테스트 주식회사",
            representative_name="홍길동",
            contact_name="김담당",
        )
    )
    first_code = next(iter(REPUTATION_ITEMS_BY_CODE))
    first_label = find_reputation_item(first_code).item_name
    isolated_db.add(
        AccountQualificationFact(
            user_id=user.id,
            credit_grade="BBB+",
            reputation_items={first_code: 1.0},
            non_price_quant_score=3,
        )
    )
    isolated_db.commit()

    body = _auth_client(user).get(MYPAGE_URL).text

    assert "마이페이지" in body
    assert user.username in body
    assert user.nickname in body
    assert user.email in body
    assert "테스트 주식회사" in body
    assert "홍길동" in body
    assert "김담당" in body
    assert "BBB+" in body
    assert first_label in body
    assert user.password not in body
    assert "아직 입력하지 않았습니다." not in body


def test_mypage_shows_empty_guidance_without_profile(client, isolated_db):
    """회사·정량 원자료가 없으면 두 섹션 모두 미입력 안내를 보여 준다."""
    user = _create_user(isolated_db, username="mypage_no_profile")

    body = _auth_client(user).get(MYPAGE_URL).text

    assert body.count("아직 입력하지 않았습니다.") >= 2
    assert user.password not in body


def test_mypage_entry_links_are_rendered(client, isolated_db):
    """사이드바 사용자 영역과 hide_sidebar 헤더 모두에서 진입 링크가 노출된다."""
    user = _create_user(isolated_db, username="mypage_linker")
    auth_client = _auth_client(user)

    mypage_body = auth_client.get(MYPAGE_URL).text
    assert f'href="{MYPAGE_URL}"' in mypage_body
    assert "/accounts/logout/" in mypage_body

    index_body = auth_client.get("/").text
    assert f'href="{MYPAGE_URL}"' in index_body
