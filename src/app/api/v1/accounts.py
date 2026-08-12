"""
src/app/api/v1/accounts.py

계정 API (원본 apps/accounts 3개 라우트 1:1 대응).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `accounts:signup` | `POST /api/v1/accounts/signup` |
| `accounts:login` | `POST /api/v1/accounts/login` |
| `accounts:logout` | `POST /api/v1/accounts/logout` |
| (신규) 현재 사용자 | `GET /api/v1/accounts/me` |

원본 SignUpForm 의 필수 항목(닉네임, 이메일, 생년월일, 성별, 약관 2종 동의)을
그대로 검증합니다.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.db import get_db
from src.app.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SessionStoreUnavailable,
    check_password,
    create_session,
    destroy_session,
    make_password,
    read_session,
)
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser

router = APIRouter(prefix="/accounts", tags=["Accounts"])

SESSION_STORE_UNAVAILABLE_DETAIL = "세션 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주십시오."


def _session_store_unavailable() -> HTTPException:
    """저장소 장애를 401 이 아니라 503 으로 알립니다.

    401 로 내리면 클라이언트가 정상적인 비로그인과 구분하지 못해, 세션이 살아
    있는데도 로그아웃된 것처럼 보입니다.
    """
    return HTTPException(status_code=503, detail=SESSION_STORE_UNAVAILABLE_DETAIL)


class SignUpRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    password1: str = Field(..., min_length=8)
    password2: str = Field(..., min_length=8)
    nickname: str = Field(..., max_length=50, description="닉네임")
    email: EmailStr = Field(..., description="이메일")
    birth_date: date = Field(..., description="생년월일 (YYYY-MM-DD)")
    gender: str = Field(..., description="성별 (M/F)")
    agree_terms: bool = Field(..., description="이용약관 동의")
    agree_privacy: bool = Field(..., description="개인정보처리방침 동의")

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: str) -> str:
        if value not in ("M", "F"):
            raise ValueError("성별은 M 또는 F 여야 합니다.")
        return value

    @field_validator("agree_terms", "agree_privacy")
    @classmethod
    def _require_agreement(cls, value: bool) -> bool:
        if not value:
            raise ValueError("약관에 동의해야 가입할 수 있습니다.")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    nickname: str
    email: str
    is_superuser: bool
    is_staff: bool


def _serialize(user: CustomUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        nickname=user.nickname or "",
        email=user.email or "",
        is_superuser=bool(user.is_superuser),
        is_staff=bool(user.is_staff),
    )


def get_current_user(
    db: Session = Depends(get_db),
    bidbox_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> CustomUser | None:
    """세션 쿠키로 사용자를 해석합니다. 미인증이면 None."""
    try:
        payload = read_session(bidbox_session)
    except SessionStoreUnavailable as exc:
        raise _session_store_unavailable() from exc
    if not payload:
        return None
    return db.get(CustomUser, int(payload.get("user_id") or 0))


def require_current_user(user: CustomUser | None = Depends(get_current_user)) -> CustomUser:
    """원본 @login_required 대응. 미인증 요청을 401 로 차단합니다."""
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def _issue_session(response: Response, user: CustomUser) -> None:
    try:
        token = create_session(user.id, user.username)
    except SessionStoreUnavailable as exc:
        raise _session_store_unavailable() from exc
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        # samesite 는 lax 를 유지합니다. main.py 의 CORS 가 allow_origins=["*"] 에
        # allow_credentials=True 라 쿠키가 실린 요청에 요청 Origin 을 그대로
        # 반사합니다. none 으로 완화하면 임의 사이트가 사용자 세션으로 API 를
        # 호출할 수 있게 됩니다. CORS 를 먼저 좁히기 전에는 건드리지 마십시오.
        samesite="lax",
        # http://localhost 개발에서는 secure 쿠키가 저장되지 않아 로그인이
        # 깨집니다. 기존 ENVIRONMENT 게이트를 그대로 씁니다.
        secure=settings.ENVIRONMENT != "development",
    )


def register_user(payload: SignUpRequest, response: Response, db: Session) -> UserResponse:
    if payload.password1 != payload.password2:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    exists = db.execute(
        select(CustomUser.id).where(CustomUser.username == payload.username)
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    user = CustomUser(
        username=payload.username,
        password=make_password(payload.password1),
        nickname=payload.nickname,
        email=str(payload.email),
        birth_y=payload.birth_date.year,
        birth_m=payload.birth_date.month,
        birth_d=payload.birth_date.day,
        gender=payload.gender,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 원본 SignUpView 는 가입 직후 자동 로그인합니다.
    _issue_session(response, user)
    return _serialize(user)


@router.post("/signup", response_model=UserResponse, summary="회원가입")
def signup(payload: SignUpRequest, response: Response, db: Session = Depends(get_db)):
    return register_user(payload, response, db)


@router.post("/login", response_model=UserResponse, summary="로그인")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.execute(
        select(CustomUser).where(CustomUser.username == payload.username)
    ).scalar_one_or_none()
    if user is None or not check_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    user.last_login = utcnow()
    db.commit()
    db.refresh(user)

    _issue_session(response, user)
    return _serialize(user)


@router.post("/logout", summary="로그아웃")
def logout(
    response: Response,
    bidbox_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    # 저장소가 죽어 있으면 서버측 무효화를 못 합니다. 쿠키만 지우고 성공을
    # 돌려주면 복구된 Redis 에서 그 토큰이 되살아나므로 503 으로 알립니다.
    try:
        destroy_session(bidbox_session)
    except SessionStoreUnavailable as exc:
        raise _session_store_unavailable() from exc
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success"}


@router.get("/me", response_model=UserResponse, summary="현재 로그인 사용자")
def me(user: CustomUser = Depends(require_current_user)):
    return _serialize(user)
