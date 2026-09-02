"""
tests/test_signup_form_parity.py

원본 apps/accounts/tests.py 의 회원가입 폼 테스트 이식입니다.

대응하는 원본 테스트:

- test_signup_form_saves_birth_date_parts_and_gender
- test_signup_page_renders_updated_fields

원본은 Django SignUpForm 객체를 직접 만들어 `form.save()` 결과를 봤습니다.
이식본에 폼 클래스는 없고 SSR POST 핸들러(src/app/api/ui.py:304)가 같은 일을
하므로, 화면이 실제로 보내는 것과 같은 form-urlencoded 요청으로 검증합니다.
폼 객체가 아니라 사용자가 지나가는 경로를 그대로 밟는 셈이라 이쪽이 더
강한 검증입니다.

소셜 로그인 관련 원본 3건은 이식 대상에서 제외했습니다(allauth 미도입).
"""

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form

SIGNUP_URL = "/accounts/signup/"


def _signup_payload(**overrides) -> dict:
    payload = {
        "username": "signup-user",
        "nickname": "테스터",
        "email": "signup@example.com",
        "birth_date": "1999-05-17",
        "gender": "F",
        "password1": "StrongPass123!!",
        "password2": "StrongPass123!!",
        "agree_terms": "on",
        "agree_privacy": "on",
    }
    payload.update(overrides)
    return payload


def test_signup_form_saves_birth_date_parts_and_gender(isolated_db):
    """생년월일 하나를 받아 birth_y/m/d 세 컬럼으로 쪼개 저장한다.

    DB 스키마는 세 컬럼으로 나뉘어 있는데 화면은 date 입력 하나만 받습니다.
    분해가 빠지면 birth_y 가 NULL 로 남아 연령대 통계가 전부 비어 버립니다.
    """
    client = TestClient(app, follow_redirects=False)

    response = client.post(
        SIGNUP_URL, data=csrf_form(client, "/accounts/signup/", _signup_payload())
    )

    assert response.status_code == 303, response.text

    user = isolated_db.query(CustomUser).filter(CustomUser.username == "signup-user").one()
    assert user.birth_y == 1999
    assert user.birth_m == 5
    assert user.birth_d == 17
    assert user.gender == "F"


def test_signup_page_renders_updated_fields():
    """회원가입 화면이 생년월일 date 입력과 성별 선택지를 그대로 노출한다."""
    client = TestClient(app)

    body = client.get(SIGNUP_URL).text

    assert "생년월일" in body
    assert 'type="date"' in body
    assert 'value="M"' in body
    assert 'value="F"' in body
    assert "남" in body
    assert "여" in body


def test_signup_rejects_mismatched_password_without_creating_user(isolated_db):
    """비밀번호가 어긋나면 폼을 다시 그리고 계정은 만들지 않는다.

    원본 폼 검증에 대응합니다. 리다이렉트로 끝나 버리면 실패를 성공으로
    오인하므로 상태 코드와 미생성 여부를 함께 봅니다.

    원본은 폼 오류를 200 재렌더로 돌려주지만 이식본은 오류 상태 코드를
    유지합니다. 같은 핸들러를 API 로도 쓰기 때문이며, 화면 동작(폼 재렌더)은
    동일합니다.
    """
    client = TestClient(app, follow_redirects=False)

    response = client.post(
        SIGNUP_URL,
        data=csrf_form(
            client, "/accounts/signup/", _signup_payload(password2="DifferentPass123!!")
        ),
    )

    assert response.status_code == 400
    assert "회원가입" in response.text
    assert isolated_db.query(CustomUser).filter(CustomUser.username == "signup-user").count() == 0
