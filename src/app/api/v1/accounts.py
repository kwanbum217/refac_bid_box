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

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.db import get_db
from src.app.core.security import (
    AUTH_SERVICE_UNAVAILABLE_DETAIL,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SessionStoreUnavailable,
    check_password,
    create_session,
    destroy_session,
    login_rate_limiter,
    make_password,
    read_session,
    resolve_client_ip,
    signup_rate_limiter,
)
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.company_profiles import (
    CONSENT_KIND_PRIVACY,
    CONSENT_KIND_TERMS,
    CONSENT_PRIVACY_VERSION,
    CONSENT_TERMS_VERSION,
    QUALIFICATION_FACTS_VERSION,
    AccountCompanyProfile,
    AccountConsentEvent,
    AccountQualificationFact,
)
from src.app.services.evaluation_rules import (
    REPUTATION_ITEMS_BY_CODE,
    REPUTATION_OPTION_CHOICE,
    ReputationItem,
    find_credit_grade,
    find_reputation_item,
)
from src.app.services.evaluation_scoring import format_decimal_plain

router = APIRouter(prefix="/accounts", tags=["Accounts"])

SESSION_STORE_UNAVAILABLE_DETAIL = "세션 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주십시오."


def _session_store_unavailable() -> HTTPException:
    """저장소 장애를 401 이 아니라 503 으로 알립니다.

    401 로 내리면 클라이언트가 정상적인 비로그인과 구분하지 못해, 세션이 살아
    있는데도 로그아웃된 것처럼 보입니다.
    """
    return HTTPException(status_code=503, detail=SESSION_STORE_UNAVAILABLE_DETAIL)


class CompanyProfileRequest(BaseModel):
    """가입 화면의 회사·담당자 정보 섹션. 전 항목 선택 입력입니다."""

    company_name: str | None = Field(default=None, max_length=255, description="회사명")
    representative_name: str | None = Field(default=None, max_length=100, description="대표자 성명")
    address: str | None = Field(default=None, max_length=500, description="회사 주소")
    phone: str | None = Field(default=None, max_length=50, description="회사 전화")
    fax: str | None = Field(default=None, max_length=50, description="회사 팩스")
    email: EmailStr | None = Field(default=None, description="회사 이메일")
    contact_name: str | None = Field(default=None, max_length=100, description="담당자 성명")
    contact_position: str | None = Field(default=None, max_length=100, description="담당자 직책")
    contact_department: str | None = Field(default=None, max_length=100, description="담당자 부서")
    contact_phone: str | None = Field(default=None, max_length=50, description="담당자 전화")
    contact_email: EmailStr | None = Field(default=None, description="담당자 이메일")

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """폼의 빈 문자열을 None 으로 접습니다. 빈 선택 항목이 422 를 내지 않게 합니다."""
        if isinstance(value, str):
            return value.strip() or None
        return value


def _validate_reputation_score(item: ReputationItem, score: float) -> None:
    """항목별 선택 평점이 레지스트리 허용 범위인지 검사합니다. 추측·보정하지 않습니다."""
    try:
        value = Decimal(str(score))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{item.item_name}: 평점은 숫자여야 합니다.") from exc
    if item.option_kind == REPUTATION_OPTION_CHOICE:
        if value not in item.options:
            allowed = ", ".join(format_decimal_plain(option) for option in item.options)
            raise ValueError(f"{item.item_name}: 선택 가능한 평점({allowed})이 아닙니다.")
        return
    low, high = item.options[0], item.options[-1]
    if value < low or value > high:
        raise ValueError(
            f"{item.item_name}: 평점은 {format_decimal_plain(low)}~"
            f"{format_decimal_plain(high)} 범위여야 합니다."
        )


class QualificationFactsRequest(BaseModel):
    """가입 화면의 정량평가 원자료 섹션. 점수는 계산하지 않고 원자료만 받습니다."""

    credit_grade: str | None = Field(
        default=None, max_length=50, description="경영상태 신용평가등급 표기(별표 10)"
    )
    credit_evaluated_on: date | None = Field(default=None, description="신용평가등급 평가일")
    reputation_items: dict[str, float] | list[str] | None = Field(
        default=None,
        description=(
            "신인도 항목별 선택 평점(dict 권장): 키는 별표 11 항목 코드, 값은 고른 평점입니다. "
            "구형 항목 코드 목록(list)도 그대로 받습니다."
        ),
    )
    non_price_quant_score: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("100"),
        description="기관 원문 미반영 공고용 비가격 정량점수 기본값",
    )

    @field_validator("credit_grade", "credit_evaluated_on", "non_price_quant_score", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("reputation_items", mode="before")
    @classmethod
    def _normalize_reputation_items(cls, value: Any) -> Any:
        """dict 는 항목별 평점, list 는 구형 코드 목록으로 정리합니다. 빈 값은 None 입니다."""
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        if isinstance(value, Mapping):
            cleaned: dict[str, Any] = {}
            for raw_code, raw_score in value.items():
                code = str(raw_code).strip() if raw_code is not None else ""
                if code and code not in cleaned:
                    cleaned[code] = raw_score
            return cleaned or None
        cleaned_codes: list[str] = []
        for entry in list(value):
            code = str(entry).strip() if entry is not None else ""
            if code and code not in cleaned_codes:
                cleaned_codes.append(code)
        return cleaned_codes or None

    @field_validator("credit_grade")
    @classmethod
    def _validate_credit_grade(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if find_credit_grade(value) is None:
            raise ValueError("신용평가등급 표기를 확인해 주세요.")
        return value

    @field_validator("reputation_items")
    @classmethod
    def _validate_reputation_items(
        cls, value: dict[str, float] | list[str] | None
    ) -> dict[str, float] | list[str] | None:
        if not value:
            return value
        if isinstance(value, dict):
            for code, score in value.items():
                item = find_reputation_item(code)
                if item is None:
                    raise ValueError(f"신인도 항목 코드를 확인해 주세요: {code}")
                _validate_reputation_score(item, score)
            return value
        unknown = sorted(code for code in value if code not in REPUTATION_ITEMS_BY_CODE)
        if unknown:
            raise ValueError(f"신인도 항목 코드를 확인해 주세요: {', '.join(unknown)}")
        return value


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
    company: CompanyProfileRequest | None = Field(
        default=None, description="회사·담당자 정보 (선택)"
    )
    qualification: QualificationFactsRequest | None = Field(
        default=None, description="정량평가 원자료 (선택)"
    )

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


class CompanyProfileResponse(BaseModel):
    company_name: str | None = None
    representative_name: str | None = None
    address: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    contact_name: str | None = None
    contact_position: str | None = None
    contact_department: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class QualificationFactsResponse(BaseModel):
    credit_grade: str | None = None
    credit_evaluated_on: date | None = None
    reputation_items: dict[str, float] | list[str] = Field(default_factory=list)
    non_price_quant_score: float | None = None
    version: str = QUALIFICATION_FACTS_VERSION


class ProfileResponse(BaseModel):
    company: CompanyProfileResponse | None = None
    qualification: QualificationFactsResponse | None = None


def _serialize_profile(
    company: AccountCompanyProfile | None,
    facts: AccountQualificationFact | None,
) -> ProfileResponse:
    company_payload = None
    if company is not None:
        company_payload = CompanyProfileResponse(
            company_name=company.company_name,
            representative_name=company.representative_name,
            address=company.address,
            phone=company.phone,
            fax=company.fax,
            email=company.email,
            contact_name=company.contact_name,
            contact_position=company.contact_position,
            contact_department=company.contact_department,
            contact_phone=company.contact_phone,
            contact_email=company.contact_email,
        )
    qualification_payload = None
    if facts is not None:
        stored_reputation = facts.reputation_items
        if isinstance(stored_reputation, dict):
            reputation_items: dict[str, float] | list[str] = {
                str(code): float(score) for code, score in stored_reputation.items()
            }
        else:
            reputation_items = list(stored_reputation or [])
        qualification_payload = QualificationFactsResponse(
            credit_grade=facts.credit_grade,
            credit_evaluated_on=facts.credit_evaluated_on,
            reputation_items=reputation_items,
            non_price_quant_score=(
                float(facts.non_price_quant_score)
                if facts.non_price_quant_score is not None
                else None
            ),
            version=facts.version,
        )
    return ProfileResponse(company=company_payload, qualification=qualification_payload)


def get_current_user(
    db: Session = Depends(get_db),
    bidbox_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> CustomUser | None:
    """세션 쿠키로 사용자를 해석합니다. 미인증이거나 비활성 계정이면 None."""
    try:
        payload = read_session(bidbox_session)
    except SessionStoreUnavailable as exc:
        raise _session_store_unavailable() from exc
    if not payload:
        return None
    user = db.get(CustomUser, int(payload.get("user_id") or 0))
    if user is None or not user.is_active:
        return None
    return user


def require_current_user(user: CustomUser | None = Depends(get_current_user)) -> CustomUser:
    """원본 @login_required 대응. 미인증 요청을 401 로 차단합니다."""
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_staff_user(user: CustomUser = Depends(require_current_user)) -> CustomUser:
    """관리자 권한 검사. staff 또는 superuser 가 아니면 403 을 반환합니다."""
    if not (user.is_staff or user.is_superuser):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


def _client_ip(request: Request) -> str:
    """시도 제한용 클라이언트 IP. 신뢰 프록시 뒤에서만 X-Forwarded-For 를 봅니다."""
    peer = request.client.host if request.client and request.client.host else ""
    return resolve_client_ip(peer, request.headers.get("x-forwarded-for"))


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


def _persist_signup_relations(db: Session, user_id: int, payload: SignUpRequest) -> None:
    """계정과 함께 저장할 회사·원자료·동의 행을 같은 트랜잭션에 추가합니다.

    선택 섹션을 비워 보내면 빈 행을 만들지 않습니다.
    """
    if payload.company is not None:
        company_values = payload.company.model_dump()
        if any(value is not None for value in company_values.values()):
            db.add(AccountCompanyProfile(user_id=user_id, **company_values))
    if payload.qualification is not None:
        facts_values = payload.qualification.model_dump()
        if any(value is not None for value in facts_values.values()):
            db.add(
                AccountQualificationFact(
                    user_id=user_id,
                    version=QUALIFICATION_FACTS_VERSION,
                    **facts_values,
                )
            )
    consented_at = utcnow()
    db.add_all(
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
    # 계정·회사·원자료·동의를 한 커밋으로 저장합니다. 중간 실패 시 롤백해
    # 계정만 남는 상태를 만들지 않습니다.
    db.add(user)
    try:
        db.flush()
        _persist_signup_relations(db, user.id, payload)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)

    # 원본 SignUpView 는 가입 직후 자동 로그인합니다.
    _issue_session(response, user)
    return _serialize(user)


@router.post(
    "/signup",
    response_model=UserResponse,
    summary="회원가입",
    responses={503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL}},
)
def signup(
    request: Request,
    payload: SignUpRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    signup_rate_limiter.check_rate_limit(ip)
    signup_rate_limiter.record_attempt(ip)
    return register_user(payload, response, db)


@router.post(
    "/login",
    response_model=UserResponse,
    summary="로그인",
    responses={503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL}},
)
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    login_rate_limiter.check_rate_limit(ip, payload.username)

    user = db.execute(
        select(CustomUser).where(CustomUser.username == payload.username)
    ).scalar_one_or_none()
    if user is None or not check_password(payload.password, user.password):
        login_rate_limiter.record_failure(ip, payload.username)
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.is_active:
        login_rate_limiter.record_failure(ip, payload.username)
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    login_rate_limiter.record_success(ip, payload.username)
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


@router.get(
    "/me/profile",
    response_model=ProfileResponse,
    summary="현재 로그인 사용자 회사·정량 원자료",
)
def me_profile(
    user: CustomUser = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """로그인 사용자의 회사·담당자 정보와 정량평가 원자료를 돌려줍니다.

    아직 입력하지 않은 섹션은 null 로 돌려줍니다.
    """
    company = db.execute(
        select(AccountCompanyProfile).where(AccountCompanyProfile.user_id == user.id)
    ).scalar_one_or_none()
    facts = db.execute(
        select(AccountQualificationFact).where(AccountQualificationFact.user_id == user.id)
    ).scalar_one_or_none()
    return _serialize_profile(company, facts)
