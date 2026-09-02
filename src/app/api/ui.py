"""
src/app/api/ui.py

원본 Django SSR 화면(templates/ 12종)에 대응하는 FastAPI 라우트입니다.
경로와 로그인 요구 여부, 컨텍스트 변수명을 원본 뷰와 1:1로 맞췄습니다.
데이터 조회는 이미 이식된 서비스 계층(bid_queries, home_context)을 재사용합니다.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import SignUpRequest, get_current_user, register_user
from src.app.core.config import settings
from src.app.core.db import get_db
from src.app.core.security import (
    CSRF_COOKIE_NAME,
    CSRF_FORM_FIELD,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SessionStoreUnavailable,
    check_password,
    create_session,
    csrf_tokens_match,
    destroy_session,
    login_rate_limiter,
    make_csrf_token,
    resolve_client_ip,
)
from src.app.core.templating import templates
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.chatbot import ChatSessionState
from src.app.services import bid_queries
from src.app.services.auth_forms import login_form, signup_form
from src.app.services.home_context import (
    DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
    get_home_page_context,
)
from src.app.services.search_index import SearchBackendUnavailable

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ui"])


def _compact_count(value: int) -> str:
    """842K 처럼 축약 표기합니다 (원본 하드코딩 문구의 형식을 유지)."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value // 1_000}K"
    return str(value)


def _login_redirect(request: Request) -> RedirectResponse:
    """원본 LoginRequiredMixin 과 동일하게 next 파라미터를 붙여 로그인으로 보냅니다."""
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/accounts/login/?next={quote(next_path, safe='/')}", status_code=303
    )


def _compat_redirect(request: Request, target: str) -> RedirectResponse:
    """이식 과도기에 쓰던 단축 경로를 원본 경로로 되돌립니다.

    정본은 원본 Django URL(apps/bids/urls.py) 입니다. 화면 링크는 전부 원본
    경로를 직접 가리키므로 이 리다이렉트는 옛 주소를 저장해 둔 요청에만 걸립니다.
    """
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{target}{query}", status_code=307)


def _safe_next_path(value: str | None) -> str:
    candidate = (value or "/").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    return candidate


# 원본은 django-allauth 소셜 로그인을 붙였습니다. 이식본에는 소셜 인증이 없으므로
# 전부 비활성으로 두어 동작하지 않는 버튼이 노출되지 않게 합니다.
SOCIAL_LOGIN_PROVIDERS = {"kakao": False, "naver": False, "google": False}


def _render(request: Request, name: str, context: dict, user, active_nav: str = ""):
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME) or make_csrf_token()
    payload = {
        "user": user,
        "active_nav": active_nav,
        "csrf_token": csrf_token,
        "social_login_providers": SOCIAL_LOGIN_PROVIDERS,
        **context,
    }
    response = templates.TemplateResponse(request, name, payload)
    if not request.cookies.get(CSRF_COOKIE_NAME):
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, samesite="lax")
    return response


async def _verify_ssr_csrf(request: Request) -> None:
    if not settings.CSRF_PROTECTION_ENABLED:
        return
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    # 토큰 쿠키를 아직 발급받지 않은 기존 비자바스크립트 소비자는 호환합니다.
    # 로그인 페이지를 먼저 방문한 브라우저는 쿠키가 있으므로 반드시 검증됩니다.
    if not cookie_token:
        return
    form_data = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    request_token = (form_data.get(CSRF_FORM_FIELD) or [""])[0]
    if not csrf_tokens_match(cookie_token, request_token):
        raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다.")


def _result_analysis_prompt(db: Session, result_id: int | None) -> str:
    """낙찰 상세에서 챗봇으로 넘길 분석 문맥을 만듭니다."""
    if result_id is None:
        return ""

    result = db.get(BidResult, result_id)
    if result is None:
        return ""

    def value(raw) -> str:
        return str(raw) if raw not in (None, "") else "정보 없음"

    winning_rate = result.display_winning_rate(db)
    return "\n".join(
        [
            "다음 낙찰 결과 상세를 기준으로 AI 인텔리전스 분석을 시작해 주세요.",
            "낙찰 결과의 가격 적정성, 경쟁 강도, 유사 사례와 향후 투찰 전략을 구체적으로 분석해 주세요.",
            "",
            f"- 결과 ID: {result.id}",
            f"- 공고번호: {value(result.bid_ntce_no)}-{value(result.bid_ntce_ord)}",
            f"- 공고명: {result.display_bid_ntce_nm}",
            f"- 업무구분: {result.category_label}",
            f"- 수요기관: {result.display_dminstt_nm}",
            f"- 낙찰업체: {result.display_bidwinnr_nm}",
            f"- 낙찰금액: {value(result.sucsf_bid_amt)}원",
            f"- 낙찰률: {value(winning_rate)}%",
            f"- 개찰일시: {value(result.rl_openg_dt)}",
        ]
    )


@router.get("/")
def index(
    request: Request,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is None:
        return _login_redirect(request)
    context = get_home_page_context(db, DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
    context["hide_sidebar"] = True
    return _render(request, "index.html", context, user, "index")


@router.get("/bids/")
def bid_list(
    request: Request,
    q: str = Query(""),
    cat: str = Query(""),
    region: str = Query(""),
    sort: str = Query(""),
    page: int = Query(1),
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is None:
        return _login_redirect(request)
    try:
        page_obj = bid_queries.list_announcements(
            db, q=q, cat=cat, region=region, sort=sort, page=page
        )
    except SearchBackendUnavailable as exc:
        logger.exception("공고 SSR 목록 검색 백엔드 실패")
        raise HTTPException(
            status_code=503,
            detail="공고 검색 인덱스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    context = {
        "bids": page_obj.object_list,
        "page_obj": page_obj,
        "max_page": bid_queries.MAX_LIST_PAGE,
        "is_paginated": page_obj.has_previous or page_obj.has_next,
        "q": q,
        "cat": cat,
        "sort": bid_queries.normalize_bid_sort(sort),
        "region": bid_queries.normalize_region_code(region),
        "region_groups": bid_queries.region_groups_payload(),
    }
    return _render(request, "bids/list.html", context, user, "bids")


# 아래 네 경로는 /bids/{pk} 보다 먼저 등록해야 합니다. 뒤에 두면 "results" 같은
# 문자열이 pk 로 해석되어 422 가 납니다.
@router.get("/bids/results/")
def result_list(
    request: Request,
    q: str = Query(""),
    cat: str = Query(""),
    region: str = Query(""),
    sort: str = Query(""),
    page: int = Query(1),
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is None:
        return _login_redirect(request)
    try:
        page_obj = bid_queries.list_results(db, q=q, cat=cat, region=region, sort=sort, page=page)
    except SearchBackendUnavailable as exc:
        logger.exception("낙찰 SSR 목록 검색 백엔드 실패")
        raise HTTPException(
            status_code=503,
            detail="낙찰 검색 인덱스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    context = {
        "results": page_obj.object_list,
        "page_obj": page_obj,
        "max_page": bid_queries.MAX_LIST_PAGE,
        "is_paginated": page_obj.has_previous or page_obj.has_next,
        "q": q,
        "cat": cat,
        "sort": bid_queries.normalize_result_sort(sort),
        "region": bid_queries.normalize_region_code(region),
        "region_groups": bid_queries.region_groups_payload(),
    }
    return _render(request, "bids/results.html", context, user, "results")


@router.get("/bids/result/{pk}/")
def result_detail(
    request: Request,
    pk: int,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is None:
        return _login_redirect(request)
    detail = bid_queries.get_result_detail(db, pk)
    if detail is None:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다.")
    return _render(request, "bids/result_detail.html", detail, user, "results")


@router.get("/bids/dashboard/")
def dashboard(request: Request, user: CustomUser | None = Depends(get_current_user)):
    if user is None:
        return _login_redirect(request)
    return _render(request, "bids/dashboard.html", {}, user, "dashboard")


@router.get("/bids/compare/")
def compare(request: Request, user: CustomUser | None = Depends(get_current_user)):
    if user is None:
        return _login_redirect(request)
    return _render(request, "bids/compare.html", {}, user, "dashboard")


@router.get("/bids/{pk}/")
def bid_detail(
    request: Request,
    pk: int,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is None:
        return _login_redirect(request)
    detail = bid_queries.get_announcement_detail(db, pk)
    if detail is None:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다.")
    return _render(request, "bids/detail.html", detail, user, "bids")


@router.get("/results/", include_in_schema=False)
def compat_result_list(request: Request):
    return _compat_redirect(request, "/bids/results/")


@router.get("/results/{pk}/", include_in_schema=False)
def compat_result_detail(request: Request, pk: int):
    return _compat_redirect(request, f"/bids/result/{pk}/")


@router.get("/dashboard/", include_in_schema=False)
def compat_dashboard(request: Request):
    return _compat_redirect(request, "/bids/dashboard/")


@router.get("/compare/", include_in_schema=False)
def compat_compare(request: Request):
    return _compat_redirect(request, "/bids/compare/")


@router.get("/chatbot/")
def chat_page(
    request: Request,
    result_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
    bidbox_session: str | None = Cookie(None),
):
    """원본 chatbot_page 대응. 사이드바에 최근 대화 세션 20건을 싣습니다."""
    if user is None:
        return _login_redirect(request)

    sessions = (
        db.execute(
            select(ChatSessionState)
            .where(
                ChatSessionState.user_id == user.id,
                ChatSessionState.last_query != "",
                ChatSessionState.session_key.not_like("user:%"),
            )
            .order_by(ChatSessionState.updated_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    # 원본은 모델명과 색인 건수가 하드코딩("Gemini 3.1 Flash-Lite preview", "842K")되어
    # 있었습니다. LLM 백엔드를 Ollama 로 바꾼 이상 그대로 두면 사실과 달라지므로
    # 실제 설정값과 실집계로 연결합니다.
    if settings.LLM_PROVIDER == "gemini":
        llm_model_label = settings.GEMINI_MODEL
    else:
        llm_model_label = f"Ollama {settings.OLLAMA_MODEL}"

    indexed_records = int(db.scalar(select(func.count(BidAnnouncement.id))) or 0)

    context = {
        "sessions": list(sessions),
        "current_session_key": bidbox_session or f"user:{user.id}",
        "llm_model_label": llm_model_label,
        "indexed_record_label": _compact_count(indexed_records),
        "initial_message": _result_analysis_prompt(db, result_id),
    }
    return _render(request, "chatbot/chat.html", context, user, "chatbot")


@router.get("/chat/", include_in_schema=False)
def compat_chat_page(request: Request):
    return _compat_redirect(request, "/chatbot/")


@router.get("/accounts/login/")
def login_page(
    request: Request,
    next: str = Query("/"),
    user: CustomUser | None = Depends(get_current_user),
):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    context = {"hide_sidebar": True, "form": login_form(), "next": _safe_next_path(next)}
    return _render(request, "accounts/login.html", context, None)


@router.get("/accounts/signup/")
def signup_page(request: Request, user: CustomUser | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    context = {"hide_sidebar": True, "form": signup_form()}
    return _render(request, "accounts/signup.html", context, None)


@router.post("/accounts/signup/")
async def signup_submit(request: Request, db: Session = Depends(get_db)):
    """JavaScript 없이도 원본 SSR 회원가입 폼을 처리합니다."""
    form_data = parse_qs((await request.body()).decode("utf-8"))

    def value(name: str) -> str:
        return (form_data.get(name) or [""])[0]

    payload = {
        "username": value("username"),
        "password1": value("password1"),
        "password2": value("password2"),
        "nickname": value("nickname"),
        "email": value("email"),
        "birth_date": value("birth_date"),
        "gender": value("gender"),
        "agree_terms": "agree_terms" in form_data,
        "agree_privacy": "agree_privacy" in form_data,
    }

    try:
        signup_payload = SignUpRequest.model_validate(payload)
        response = RedirectResponse(url="/", status_code=303)
        # register_user 는 동기 DB 트랜잭션과 PBKDF2 해싱을 함께 수행합니다.
        await asyncio.to_thread(register_user, signup_payload, response, db)
        return response
    except ValidationError as exc:
        errors: dict[str, list[str]] = {}
        for item in exc.errors():
            field_name = str(item.get("loc", ("__all__",))[0])
            errors.setdefault(field_name, []).append(str(item.get("msg", "입력값을 확인해주세요.")))
        status_code = 422
    except HTTPException as exc:
        errors = {}
        if exc.status_code == 409:
            errors["username"] = [str(exc.detail)]
        else:
            errors["__all__"] = [str(exc.detail)]
        status_code = exc.status_code

    render_response = _render(
        request,
        "accounts/signup.html",
        {
            "hide_sidebar": True,
            "form": signup_form(data=payload, errors=errors),
        },
        None,
    )
    render_response.status_code = status_code
    return render_response


def _load_account_and_verify(db: Session, username: str, password: str) -> tuple:
    """계정 조회와 비밀번호 검증을 한 스레드에서 수행합니다.

    check_password 는 PBKDF2 600,000 회로 CPU 를 수백 밀리초 점유합니다.
    조회와 검증을 따로 오프로드하면 왕복이 두 번이라 한 번에 묶습니다.
    """
    account = db.execute(
        select(CustomUser).where(CustomUser.username == username)
    ).scalar_one_or_none()
    if account is None:
        return None, False
    return account, check_password(password, account.password)


def _touch_last_login(db: Session, account: CustomUser) -> None:
    account.last_login = utcnow()
    db.commit()


@router.post("/accounts/login/")
async def login_submit(
    request: Request,
    next: str = Query("/"),
    db: Session = Depends(get_db),
):
    """원본 Django LoginView 대응. 실패 시 폼 오류와 함께 같은 화면을 다시 그립니다.

    원본 폼은 application/x-www-form-urlencoded 이므로 표준 라이브러리로 직접
    파싱합니다. Starlette 의 request.form() 은 python-multipart 를 요구하는데,
    신규 의존성 추가는 사전 합의가 필요하므로 회피했습니다.
    """
    form_data = parse_qs((await request.body()).decode("utf-8"))
    username = (form_data.get("username") or [""])[0]
    password = (form_data.get("password") or [""])[0]
    ip = resolve_client_ip(
        request.client.host if request.client and request.client.host else "",
        request.headers.get("x-forwarded-for"),
    )

    login_rate_limiter.check_rate_limit(ip, username)

    # 동기 DB 조회와 PBKDF2 검증을 루프 스레드에서 하면 무인증 요청만으로
    # 이벤트 루프를 점유할 수 있습니다.
    account, password_ok = await asyncio.to_thread(_load_account_and_verify, db, username, password)

    if account is None or not password_ok:
        login_rate_limiter.record_failure(ip, username)
        context = {
            "hide_sidebar": True,
            "form": login_form(
                data={"username": username},
                non_field_errors=["아이디 또는 비밀번호가 올바르지 않습니다."],
            ),
            "next": _safe_next_path(next),
        }
        response = _render(request, "accounts/login.html", context, None)
        response.status_code = 401
        return response

    if not account.is_active:
        login_rate_limiter.record_failure(ip, username)
        context = {
            "hide_sidebar": True,
            "form": login_form(
                data={"username": username},
                non_field_errors=["비활성화된 계정입니다."],
            ),
            "next": _safe_next_path(next),
        }
        response = _render(request, "accounts/login.html", context, None)
        response.status_code = 403
        return response

    login_rate_limiter.record_success(ip, username)
    await asyncio.to_thread(_touch_last_login, db, account)

    try:
        token = await asyncio.to_thread(create_session, account.id, account.username)
    except SessionStoreUnavailable as exc:
        logger.exception("SSR 로그인 세션 저장 실패")
        raise HTTPException(
            status_code=503,
            detail="세션 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주십시오.",
        ) from exc

    redirect = RedirectResponse(url=_safe_next_path(next), status_code=303)
    redirect.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT != "development",
    )
    return redirect


@router.post("/accounts/logout/")
async def logout_submit(
    request: Request,
    bidbox_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    """POST 로그아웃만 허용하여 GET 기반 CSRF 로그아웃 통로를 차단합니다.

    저장소 장애 시 서버측 무효화 없이 쿠키만 지우면 복구 후 토큰이 되살아납니다.
    API 경로와 동일하게 503 으로 차단합니다.
    """
    await _verify_ssr_csrf(request)
    try:
        destroy_session(bidbox_session)
    except SessionStoreUnavailable as exc:
        logger.exception("SSR 로그아웃 세션 삭제 실패")
        raise HTTPException(
            status_code=503,
            detail="세션 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주십시오.",
        ) from exc
    response = RedirectResponse(url="/accounts/login/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
