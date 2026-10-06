"""
tests/test_signup_company_profile.py

회원가입 회사·담당자 정보와 정량평가 원자료(D-W4) 저장·조회 검증.

검증 범위:
  - 마이그레이션 c2d3e4f5a6b7 이 신규 테이블 3개를 만들고 기존 계정 테이블을
    바꾸지 않는다.
  - JSON API 가입과 SSR 가입 두 경로가 같은 필드를 같은 규칙으로 저장한다.
  - 중간 실패 시 계정·회사·원자료·동의가 한 트랜잭션으로 롤백된다.
  - 기존 회원(신규 테이블 없는 계정) 로그인이 유지된다.
  - 로그인 사용자 프로필 조회 API 가 저장값을 돌려준다.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import src.app.api.v1.accounts as accounts_module
import src.app.models  # noqa: F401  모든 테이블 등록
from src.app.core.config import settings
from src.app.core.db import Base
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.company_profiles import (
    AccountCompanyProfile,
    AccountConsentEvent,
    AccountQualificationFact,
)
from tests.test_csrf import csrf_form

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_SIGNUP_URL = "/api/v1/accounts/signup"
API_LOGIN_URL = "/api/v1/accounts/login"
SSR_SIGNUP_URL = "/accounts/signup/"
PROFILE_URL = "/api/v1/accounts/me/profile"

NEW_TABLES = (
    "account_company_profiles",
    "account_qualification_facts",
    "account_consent_events",
)

COMPANY_INPUT = {
    "company_name": "테스트 주식회사",
    "representative_name": "대표자",
    "address": "서울특별시 중구 세종대로 1",
    "phone": "02-0000-0000",
    "fax": "02-0000-0001",
    "email": "company@example.com",
    "contact_name": "담당자",
    "contact_position": "과장",
    "contact_department": "입찰팀",
    "contact_phone": "010-0000-0000",
    "contact_email": "contact@example.com",
}

QUALIFICATION_INPUT = {
    "credit_grade": "BBB0",
    "credit_evaluated_on": "2026-01-15",
    "reputation_items": ["sme_support", "woman_company"],
    "non_price_quant_score": "40.00",
}


def _api_payload(**overrides) -> dict:
    payload = {
        "username": "profile-user",
        "password1": "StrongPass123!!",
        "password2": "StrongPass123!!",
        "nickname": "프로필 검증",
        "email": "profile@example.com",
        "birth_date": "1990-01-01",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
        "company": dict(COMPANY_INPUT),
        "qualification": dict(QUALIFICATION_INPUT),
    }
    payload.update(overrides)
    return payload


def _ssr_payload(**overrides) -> dict:
    payload = {
        "username": "profile-user",
        "password1": "StrongPass123!!",
        "password2": "StrongPass123!!",
        "nickname": "프로필 검증",
        "email": "profile@example.com",
        "birth_date": "1990-01-01",
        "gender": "M",
        "agree_terms": "on",
        "agree_privacy": "on",
        "company_name": COMPANY_INPUT["company_name"],
        "representative_name": COMPANY_INPUT["representative_name"],
        "address": COMPANY_INPUT["address"],
        "phone": COMPANY_INPUT["phone"],
        "fax": COMPANY_INPUT["fax"],
        "company_email": COMPANY_INPUT["email"],
        "contact_name": COMPANY_INPUT["contact_name"],
        "contact_position": COMPANY_INPUT["contact_position"],
        "contact_department": COMPANY_INPUT["contact_department"],
        "contact_phone": COMPANY_INPUT["contact_phone"],
        "contact_email": COMPANY_INPUT["contact_email"],
        "credit_grade": QUALIFICATION_INPUT["credit_grade"],
        "credit_evaluated_on": QUALIFICATION_INPUT["credit_evaluated_on"],
        "reputation_items": list(QUALIFICATION_INPUT["reputation_items"]),
        "non_price_quant_score": QUALIFICATION_INPUT["non_price_quant_score"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# 마이그레이션
# --------------------------------------------------------------------------- #


def test_migration_creates_new_tables_without_touching_account_table(tmp_path, monkeypatch):
    """신규 리비전이 신규 테이블 3개를 만들고 기존 계정 컬럼을 바꾸지 않는다.

    기준선 리비전(0001_django_baseline)은 MySQL 전용 타입(TINYINT)을 써서
    SQLite 로 그대로 올릴 수 없습니다. 그래서 기존 테이블은 ORM 메타데이터로
    만들고 직전 리비전(bd7c2e9a104f)을 스탬프한 뒤, 신규 리비전만 적용해
    upgrade/downgrade 를 검증합니다.
    """
    db_path = tmp_path / "migration.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)

    engine = create_engine(url)
    legacy_tables = [
        table for name, table in Base.metadata.tables.items() if name not in NEW_TABLES
    ]
    Base.metadata.create_all(engine, tables=legacy_tables)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('bd7c2e9a104f')"))

    # migrations/env.py 의 fileConfig 가 전역 로깅을 재설정해 이후 테스트의 caplog 를
    # 비웁니다. 로깅 재설정만 no-op 으로 막고 마이그레이션은 그대로 실행합니다.
    monkeypatch.setattr(logging.config, "fileConfig", lambda *args, **kwargs: None)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")

        inspector = inspect(engine)
        assert set(NEW_TABLES) <= set(inspector.get_table_names())

        migrated_columns = {c["name"] for c in inspector.get_columns("accounts_customuser")}
        assert migrated_columns == set(Base.metadata.tables["accounts_customuser"].columns.keys())

        command.downgrade(config, "bd7c2e9a104f")
        assert not set(NEW_TABLES) & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_revision_points_at_current_head(monkeypatch):
    """새 리비전이 기존 단일 head(bd7c2e9a104f) 바로 뒤에 붙는다."""
    from migrations.versions import c2d3e4f5a6b7_add_account_company_profiles as migration

    assert migration.revision == "c2d3e4f5a6b7"
    assert migration.down_revision == "bd7c2e9a104f"


# --------------------------------------------------------------------------- #
# 두 가입 경로 저장
# --------------------------------------------------------------------------- #


def test_api_signup_persists_company_qualification_and_consent(isolated_db):
    client = TestClient(app, follow_redirects=False)

    response = client.post(API_SIGNUP_URL, json=_api_payload())

    assert response.status_code == 200, response.text
    user = isolated_db.query(CustomUser).filter_by(username="profile-user").one()

    company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
    assert company.company_name == COMPANY_INPUT["company_name"]
    assert company.representative_name == COMPANY_INPUT["representative_name"]
    assert company.email == COMPANY_INPUT["email"]
    assert company.contact_name == COMPANY_INPUT["contact_name"]
    assert company.contact_email == COMPANY_INPUT["contact_email"]

    facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()
    assert facts.credit_grade == "BBB0"
    assert facts.credit_evaluated_on.isoformat() == "2026-01-15"
    assert set(facts.reputation_items) == set(QUALIFICATION_INPUT["reputation_items"])
    assert Decimal(facts.non_price_quant_score) == Decimal("40.00")

    consents = isolated_db.query(AccountConsentEvent).filter_by(user_id=user.id).all()
    assert {event.consent_kind for event in consents} == {"terms", "privacy"}


def test_ssr_signup_persists_company_qualification_and_consent(isolated_db):
    client = TestClient(app, follow_redirects=False)

    response = client.post(SSR_SIGNUP_URL, data=csrf_form(client, SSR_SIGNUP_URL, _ssr_payload()))

    assert response.status_code == 303, response.text
    user = isolated_db.query(CustomUser).filter_by(username="profile-user").one()
    company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
    facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()

    assert company.company_name == COMPANY_INPUT["company_name"]
    assert facts.credit_grade == "BBB0"
    assert set(facts.reputation_items) == set(QUALIFICATION_INPUT["reputation_items"])


def test_two_signup_paths_store_identical_values(isolated_db):
    """API 가입과 SSR 가입이 같은 입력을 같은 값으로 저장한다."""
    api_client = TestClient(app, follow_redirects=False)
    assert api_client.post(API_SIGNUP_URL, json=_api_payload()).status_code == 200

    ssr_client = TestClient(app, follow_redirects=False)
    ssr_response = ssr_client.post(
        SSR_SIGNUP_URL,
        data=csrf_form(ssr_client, SSR_SIGNUP_URL, _ssr_payload(username="ssr-user")),
    )
    assert ssr_response.status_code == 303, ssr_response.text

    api_user = isolated_db.query(CustomUser).filter_by(username="profile-user").one()
    ssr_user = isolated_db.query(CustomUser).filter_by(username="ssr-user").one()

    ignored = {"id", "user_id", "created_at", "updated_at"}

    def _snapshot(user):
        company = isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).one()
        facts = isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).one()
        return (
            {
                c.name: getattr(company, c.name)
                for c in company.__table__.columns
                if c.name not in ignored
            },
            {
                "credit_grade": facts.credit_grade,
                "credit_evaluated_on": facts.credit_evaluated_on,
                "reputation_items": sorted(facts.reputation_items or []),
                "non_price_quant_score": Decimal(facts.non_price_quant_score),
            },
        )

    assert _snapshot(api_user) == _snapshot(ssr_user)


def test_signup_without_optional_sections_still_creates_account(isolated_db):
    """정량 원자료는 선택 입력이라 비워도 가입되고 빈 행을 만들지 않는다."""
    client = TestClient(app, follow_redirects=False)
    payload = _api_payload()
    payload.pop("company")
    payload.pop("qualification")

    assert client.post(API_SIGNUP_URL, json=payload).status_code == 200

    user = isolated_db.query(CustomUser).filter_by(username="profile-user").one()
    assert isolated_db.query(AccountCompanyProfile).filter_by(user_id=user.id).count() == 0
    assert isolated_db.query(AccountQualificationFact).filter_by(user_id=user.id).count() == 0
    assert isolated_db.query(AccountConsentEvent).filter_by(user_id=user.id).count() == 2


# --------------------------------------------------------------------------- #
# 검증 오류
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "override",
    [
        {"qualification": {**QUALIFICATION_INPUT, "credit_grade": "ZZZ"}},
        {"qualification": {**QUALIFICATION_INPUT, "reputation_items": ["unknown_item"]}},
        {"qualification": {**QUALIFICATION_INPUT, "non_price_quant_score": "150"}},
        {"company": {**COMPANY_INPUT, "email": "not-an-email"}},
    ],
)
def test_signup_rejects_invalid_optional_input(isolated_db, override):
    client = TestClient(app, follow_redirects=False)

    response = client.post(API_SIGNUP_URL, json=_api_payload(**override))

    assert response.status_code == 422, response.text
    assert isolated_db.query(CustomUser).count() == 0


def test_ssr_signup_rejects_invalid_credit_grade(isolated_db):
    client = TestClient(app, follow_redirects=False)

    response = client.post(
        SSR_SIGNUP_URL,
        data=csrf_form(
            client,
            SSR_SIGNUP_URL,
            _ssr_payload(credit_grade="ZZZ"),
        ),
    )

    assert response.status_code == 422, response.text
    assert isolated_db.query(CustomUser).count() == 0


# --------------------------------------------------------------------------- #
# 원자성
# --------------------------------------------------------------------------- #


def _failing_relation_save(db, user_id, payload):
    db.add(AccountCompanyProfile(user_id=user_id, company_name="부분 저장"))
    raise RuntimeError("주입된 원자료 저장 실패")


def test_api_signup_rolls_back_account_on_relation_failure(isolated_db, monkeypatch):
    monkeypatch.setattr(accounts_module, "_persist_signup_relations", _failing_relation_save)
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)

    response = client.post(API_SIGNUP_URL, json=_api_payload())

    assert response.status_code == 500, response.text
    assert isolated_db.query(CustomUser).count() == 0
    assert isolated_db.query(AccountCompanyProfile).count() == 0


def test_ssr_signup_rolls_back_account_on_relation_failure(isolated_db, monkeypatch):
    monkeypatch.setattr(accounts_module, "_persist_signup_relations", _failing_relation_save)
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)

    response = client.post(SSR_SIGNUP_URL, data=csrf_form(client, SSR_SIGNUP_URL, _ssr_payload()))

    assert response.status_code == 500, response.text
    assert isolated_db.query(CustomUser).count() == 0
    assert isolated_db.query(AccountCompanyProfile).count() == 0


# --------------------------------------------------------------------------- #
# 기존 회원 로그인과 프로필 조회
# --------------------------------------------------------------------------- #


def test_existing_member_can_still_login_without_profile_rows(isolated_db):
    """신규 테이블에 행이 없는 기존 계정도 그대로 로그인한다."""
    user = CustomUser(
        username="legacy-user",
        password=make_password("StrongPass123!!"),
        nickname="기존 회원",
        email="legacy@example.com",
        is_active=True,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()

    client = TestClient(app, follow_redirects=False)
    response = client.post(
        API_LOGIN_URL, json={"username": "legacy-user", "password": "StrongPass123!!"}
    )

    assert response.status_code == 200, response.text


def _login_client(db, username: str) -> TestClient:
    user = db.query(CustomUser).filter_by(username=username).one()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def test_profile_returns_saved_company_and_qualification(isolated_db):
    client = TestClient(app, follow_redirects=False)
    assert client.post(API_SIGNUP_URL, json=_api_payload()).status_code == 200

    profile_client = _login_client(isolated_db, "profile-user")
    response = profile_client.get(PROFILE_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company"]["company_name"] == COMPANY_INPUT["company_name"]
    assert body["company"]["contact_email"] == COMPANY_INPUT["contact_email"]
    assert body["qualification"]["credit_grade"] == "BBB0"
    assert body["qualification"]["credit_evaluated_on"] == "2026-01-15"
    assert set(body["qualification"]["reputation_items"]) == set(
        QUALIFICATION_INPUT["reputation_items"]
    )
    assert body["qualification"]["non_price_quant_score"] == 40.0


def test_profile_returns_null_sections_for_account_without_profile(isolated_db):
    user = CustomUser(
        username="legacy-user",
        password=make_password("StrongPass123!!"),
        nickname="기존 회원",
        email="legacy@example.com",
        is_active=True,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()

    response = _login_client(isolated_db, "legacy-user").get(PROFILE_URL)

    assert response.status_code == 200, response.text
    assert response.json() == {"company": None, "qualification": None}


def test_profile_requires_login(isolated_db):
    client = TestClient(app, follow_redirects=False)

    response = client.get(PROFILE_URL)

    assert response.status_code == 401
