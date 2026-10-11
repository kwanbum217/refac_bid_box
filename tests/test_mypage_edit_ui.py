"""마이페이지 회원정보 수정(GET/POST /accounts/mypage/edit/) SSR 화면 시험.

정본: .orca/capsules/task_777d7eb2770c/capsule.yaml.
 - 비로그인 GET/POST 는 로그인 화면으로 리다이렉트된다.
 - CSRF 없는 POST 는 403 으로 거부된다.
 - 닉네임·이메일·회사·정량 원자료를 수정하면 DB 에 반영되고 303 으로 마이페이지로 간다.
 - 잘못된 이메일·범위 밖 정량값은 200 으로 같은 폼에 오류를 보여 준다.
 - 프로필 행이 없던 회원은 수정 시 행이 새로 만들어진다.
 - 요청 본문의 user_id 류 값은 무시되고 다른 회원 행은 바뀌지 않는다.
 - 가입 경로는 그대로 동작한다(회귀 없음).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from src.app.core import security
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.company_profiles import (
    CONSENT_KIND_PRIVACY,
    CONSENT_KIND_TERMS,
    AccountCompanyProfile,
    AccountConsentEvent,
    AccountQualificationFact,
)
from src.app.services.evaluation_rules import (
    REPUTATION_ITEMS,
    REPUTATION_OPTION_CHOICE,
    find_credit_grade,
)
from tests.test_csrf import csrf_form

EDIT_URL = "/accounts/mypage/edit/"
MYPAGE_URL = "/accounts/mypage/"
VALID_CREDIT_GRADE = "BBB+"


def _create_user(
    db, *, username: str, nickname: str = "수정 전 닉네임", email: str | None = None
) -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-test-1234"),
        email=email or f"{username}@example.com",
        nickname=nickname,
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


def _range_item():
    for item in REPUTATION_ITEMS:
        if item.option_kind != REPUTATION_OPTION_CHOICE:
            return item
    raise AssertionError("구간형 신인도 항목이 없습니다")


def _payload(**overrides: str) -> dict[str, str]:
    data = {
        "nickname": "수정한 닉네임",
        "email": "edited@example.com",
        "company_name": "수정 주식회사",
        "representative_name": "대표자 이름",
        "address": "서울시 중구",
        "phone": "02-0000-0000",
        "fax": "02-0000-0001",
        "company_email": "company@example.com",
        "contact_name": "담당자 이름",
        "contact_position": "과장",
        "contact_department": "영업팀",
        "contact_phone": "010-0000-0000",
        "contact_email": "contact@example.com",
        "credit_grade": VALID_CREDIT_GRADE,
        "credit_evaluated_on": "2026-01-02",
        "non_price_quant_score": "3",
    }
    data.update(overrides)
    return data


def test_edit_redirects_anonymous_get_to_login(client):
    response = client.get(EDIT_URL, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/login/?next={EDIT_URL}"


def test_edit_redirects_anonymous_post_to_login(client):
    response = client.post(EDIT_URL, data={"nickname": "x"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/login/?next={EDIT_URL}"


def test_mypage_renders_edit_link(client, isolated_db):
    user = _create_user(isolated_db, username="edit_linker")

    body = _auth_client(user).get(MYPAGE_URL).text

    assert f'href="{EDIT_URL}"' in body


def test_edit_form_renders_current_values(client, isolated_db):
    user = _create_user(isolated_db, username="edit_viewer", nickname="원래 닉네임")
    isolated_db.add(
        AccountCompanyProfile(user_id=user.id, company_name="원래 회사", contact_name="원래 담당")
    )
    isolated_db.add(
        AccountQualificationFact(
            user_id=user.id, credit_grade=VALID_CREDIT_GRADE, non_price_quant_score=5
        )
    )
    isolated_db.commit()

    body = _auth_client(user).get(EDIT_URL).text

    assert user.username in body
    assert "원래 닉네임" in body
    assert f'value="{user.email}"' in body
    assert "원래 회사" in body
    assert "원래 담당" in body
    assert f'value="{VALID_CREDIT_GRADE}" selected' in body
    # 아이디·비밀번호는 수정 대상이 아니므로 입력 필드가 없다.
    assert 'name="username"' not in body
    assert 'type="password"' not in body


def test_edit_post_without_csrf_is_rejected(monkeypatch, isolated_db):
    user = _create_user(isolated_db, username="edit_csrf")
    monkeypatch.setattr(security.settings, "CSRF_PROTECTION_ENABLED", True, raising=False)

    response = _auth_client(user).post(EDIT_URL, data=_payload(), follow_redirects=False)

    assert response.status_code == 403


def test_edit_updates_account_company_and_qualification(client, isolated_db):
    user = _create_user(isolated_db, username="edit_success")
    isolated_db.add(AccountCompanyProfile(user_id=user.id, company_name="수정 전 회사"))
    isolated_db.add(AccountQualificationFact(user_id=user.id, credit_grade="CCC"))
    isolated_db.commit()

    range_item = _range_item()
    valid_score = str(range_item.options[0])
    auth_client = _auth_client(user)
    data = _payload(**{f"reputation_score__{range_item.item_code}": valid_score})

    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, data), follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == MYPAGE_URL

    isolated_db.expire_all()
    refreshed = isolated_db.get(CustomUser, user.id)
    assert refreshed.nickname == "수정한 닉네임"
    assert refreshed.email == "edited@example.com"

    company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
    assert company.company_name == "수정 주식회사"
    assert company.contact_name == "담당자 이름"
    assert company.email == "company@example.com"

    facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()
    assert facts.credit_grade == VALID_CREDIT_GRADE
    assert facts.credit_evaluated_on == date(2026, 1, 2)
    assert facts.reputation_items == {range_item.item_code: float(range_item.options[0])}
    assert float(facts.non_price_quant_score) == 3.0

    mypage_body = auth_client.get(MYPAGE_URL).text
    assert "수정한 닉네임" in mypage_body
    assert "수정 주식회사" in mypage_body


def test_edit_creates_missing_profile_rows(client, isolated_db):
    user = _create_user(isolated_db, username="edit_creator")
    assert isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).count() == 0
    assert isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).count() == 0

    auth_client = _auth_client(user)
    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, _payload()), follow_redirects=False
    )

    assert response.status_code == 303
    isolated_db.expire_all()
    company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
    assert company.company_name == "수정 주식회사"
    facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()
    assert facts.credit_grade == VALID_CREDIT_GRADE
    assert facts.version


def test_edit_invalid_email_rerenders_with_submitted_value(client, isolated_db):
    user = _create_user(isolated_db, username="edit_bad_email")
    auth_client = _auth_client(user)
    data = _payload(email="not-an-email")

    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, data), follow_redirects=False
    )

    assert response.status_code == 200
    assert 'value="not-an-email"' in response.text
    isolated_db.expire_all()
    refreshed = isolated_db.get(CustomUser, user.id)
    assert refreshed.email == "edit_bad_email@example.com"


def test_edit_out_of_range_reputation_rerenders_with_error(client, isolated_db):
    user = _create_user(isolated_db, username="edit_bad_reputation")
    range_item = _range_item()
    too_low = str(range_item.options[0] - Decimal("1"))
    auth_client = _auth_client(user)
    data = _payload(**{f"reputation_score__{range_item.item_code}": too_low})

    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, data), follow_redirects=False
    )

    assert response.status_code == 200
    assert "범위여야 합니다" in response.text
    assert isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).count() == 0


def test_edit_out_of_range_quant_score_rerenders_with_error(client, isolated_db):
    user = _create_user(isolated_db, username="edit_bad_quant")
    auth_client = _auth_client(user)
    data = _payload(non_price_quant_score="150")

    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, data), follow_redirects=False
    )

    assert response.status_code == 200
    assert 'value="150"' in response.text
    isolated_db.expire_all()
    refreshed = isolated_db.get(CustomUser, user.id)
    assert refreshed.nickname == "수정 전 닉네임"
    assert isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).count() == 0


def test_edit_ignores_other_user_and_does_not_touch_other_rows(client, isolated_db):
    user_a = _create_user(isolated_db, username="edit_a", nickname="A 닉네임")
    user_b = _create_user(isolated_db, username="edit_b", nickname="B 닉네임")
    isolated_db.add(AccountCompanyProfile(user_id=user_b.id, company_name="B 회사"))
    isolated_db.add(AccountQualificationFact(user_id=user_b.id, credit_grade="CCC"))
    isolated_db.commit()
    b_password = user_b.password

    auth_client = _auth_client(user_a)
    data = _payload(user_id=str(user_b.id), username="hacked", password1="hacked-password")
    response = auth_client.post(
        EDIT_URL, data=csrf_form(auth_client, EDIT_URL, data), follow_redirects=False
    )

    assert response.status_code == 303
    isolated_db.expire_all()
    refreshed_a = isolated_db.get(CustomUser, user_a.id)
    refreshed_b = isolated_db.get(CustomUser, user_b.id)
    assert refreshed_a.nickname == "수정한 닉네임"
    assert refreshed_b.nickname == "B 닉네임"
    assert refreshed_b.username == "edit_b"
    assert refreshed_b.password == b_password
    b_company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user_b.id).one()
    assert b_company.company_name == "B 회사"
    b_facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user_b.id).one()
    assert b_facts.credit_grade == "CCC"


def test_signup_post_still_creates_relations(client, isolated_db):
    """가입 SSR 경로가 공통 파싱 함수로 바뀐 뒤에도 회사·원자료·동의를 저장한다."""
    response = client.post(
        "/accounts/signup/",
        data=csrf_form(
            client,
            "/accounts/signup/",
            {
                "username": "edit_signup_regression",
                "password1": "pw-test-1234",
                "password2": "pw-test-1234",
                "nickname": "가입 회귀",
                "email": "signup-regression@example.com",
                "birth_date": "1990-01-02",
                "gender": "M",
                "agree_terms": "on",
                "agree_privacy": "on",
                "company_name": "가입 회사",
                "contact_name": "가입 담당",
                "credit_grade": VALID_CREDIT_GRADE,
                "non_price_quant_score": "7",
            },
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    user = isolated_db.query(CustomUser).filter_by(username="edit_signup_regression").one()
    company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
    assert company.company_name == "가입 회사"
    assert company.contact_name == "가입 담당"
    facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()
    assert facts.credit_grade == VALID_CREDIT_GRADE
    kinds = {
        row.consent_kind
        for row in isolated_db.query(AccountConsentEvent).filter_by(user_id=user.id).all()
    }
    assert kinds == {CONSENT_KIND_TERMS, CONSENT_KIND_PRIVACY}


def test_edit_rejects_unknown_credit_grade(client, isolated_db):
    user = _create_user(isolated_db, username="edit_bad_grade")
    grade = "ZZZ-NOT-A-GRADE"
    assert find_credit_grade(grade) is None
    auth_client = _auth_client(user)

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, _payload(credit_grade=grade)),
        follow_redirects=False,
    )

    assert response.status_code == 200
    isolated_db.expire_all()
    assert isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).count() == 0
