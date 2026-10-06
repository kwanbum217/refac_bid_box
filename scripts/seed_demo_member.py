"""
scripts/seed_demo_member.py

시연·검증 환경용 시험 회원을 만듭니다. 정량평가 원자료가 채워진 계정이라
공고 상세에서 자동 기입 경로를 시험할 수 있습니다.

안전장치:
  - `ALLOW_DEMO_SEED=1` 이 명시로 있을 때만 동작합니다. 운영 DB 오용을 막습니다.
  - 비밀번호는 코드에 하드코딩하지 않고 `--password` 또는 `DEMO_MEMBER_PASSWORD`
    환경변수로만 받습니다.

실행 예:
    ALLOW_DEMO_SEED=1 uv run python scripts/seed_demo_member.py \
        --password 'DemoPass123!!'
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.security import make_password  # noqa: E402
from src.app.core.timeutil import utcnow  # noqa: E402
from src.app.models.accounts import CustomUser  # noqa: E402
from src.app.models.company_profiles import (  # noqa: E402
    CONSENT_KIND_PRIVACY,
    CONSENT_KIND_TERMS,
    CONSENT_PRIVACY_VERSION,
    CONSENT_TERMS_VERSION,
    QUALIFICATION_FACTS_VERSION,
    AccountCompanyProfile,
    AccountConsentEvent,
    AccountQualificationFact,
)

DEMO_USERNAME = "demo_member"
DEMO_EMAIL = "demo_member@example.com"
DEMO_NICKNAME = "시연 회원"
DEMO_PASSWORD_ENV = "DEMO_MEMBER_PASSWORD"  # noqa: S105  # nosec B105 (환경변수 이름)


def _get_or_create_user(session: Session, username: str, email: str, password: str) -> CustomUser:
    user = session.execute(
        select(CustomUser).where(CustomUser.username == username)
    ).scalar_one_or_none()
    if user is None:
        user = CustomUser(
            username=username,
            password=make_password(password),
            nickname=DEMO_NICKNAME,
            email=email,
            birth_y=1990,
            birth_m=1,
            birth_d=1,
            gender="M",
            date_joined=utcnow(),
        )
        session.add(user)
        session.flush()
    else:
        user.password = make_password(password)
    return user


def _replace_company(session: Session, user_id: int) -> None:
    session.query(AccountCompanyProfile).filter(AccountCompanyProfile.user_id == user_id).delete()
    session.add(
        AccountCompanyProfile(
            user_id=user_id,
            company_name="시연 주식회사",
            representative_name="홍길동",
            address="서울특별시 중구 세종대로 1",
            phone="02-1234-5678",
            fax="02-1234-5679",
            email="demo_company@example.com",
            contact_name="김담당",
            contact_position="과장",
            contact_department="입찰팀",
            contact_phone="010-1234-5678",
            contact_email="demo_contact@example.com",
        )
    )


def _replace_qualification(session: Session, user_id: int) -> None:
    session.query(AccountQualificationFact).filter(
        AccountQualificationFact.user_id == user_id
    ).delete()
    session.add(
        AccountQualificationFact(
            user_id=user_id,
            credit_grade="BBB0",
            credit_evaluated_on=date(2026, 1, 15),
            reputation_items=["sme_support", "woman_company"],
            non_price_quant_score=Decimal("40.00"),
            version=QUALIFICATION_FACTS_VERSION,
        )
    )


def _record_consent(session: Session, user_id: int) -> None:
    consented_at = utcnow()
    session.add_all(
        [
            AccountConsentEvent(
                user_id=user_id,
                consent_kind=CONSENT_KIND_TERMS,
                terms_version=CONSENT_TERMS_VERSION,
                consented_at=consented_at,
            ),
            AccountConsentEvent(
                user_id=user_id,
                consent_kind=CONSENT_KIND_PRIVACY,
                terms_version=CONSENT_PRIVACY_VERSION,
                consented_at=consented_at,
            ),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="시연용 시험 회원을 만듭니다.")
    parser.add_argument("--username", default=os.environ.get("DEMO_MEMBER_USERNAME", DEMO_USERNAME))
    parser.add_argument("--email", default=os.environ.get("DEMO_MEMBER_EMAIL", DEMO_EMAIL))
    parser.add_argument(
        "--password",
        default=os.environ.get(DEMO_PASSWORD_ENV),
        help="비밀번호. 미지정 시 DEMO_MEMBER_PASSWORD 환경변수를 씁니다.",
    )
    args = parser.parse_args(argv)

    if os.environ.get("ALLOW_DEMO_SEED") != "1":
        print("ALLOW_DEMO_SEED=1 이 없어 실행하지 않습니다. 시연·검증 환경에서만 지정하세요.")
        return 1
    if not args.password:
        print("비밀번호가 필요합니다. --password 또는 DEMO_MEMBER_PASSWORD 를 지정하세요.")
        return 1

    session = SessionLocal()
    try:
        user = _get_or_create_user(session, args.username, args.email, args.password)
        _replace_company(session, user.id)
        _replace_qualification(session, user.id)
        _record_consent(session, user.id)
        session.commit()
        print(f"시연 회원 준비 완료: {user.username} (id={user.id})")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
