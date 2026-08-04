"""
src/app/api/ui.py

원본 Django SSR 화면(templates/ 12종)에 대응하는 FastAPI 라우트입니다.
경로와 로그인 요구 여부, 컨텍스트 변수명을 원본 뷰와 1:1로 맞췄습니다.
데이터 조회는 이미 이식된 서비스 계층(bid_queries, home_context)을 재사용합니다.
"""

from __future__ import annotations

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
    SESSION_COOKIE_NAME,
    check_password,
    create_session,
    destroy_session,
)
from src.app.core.templating import templates
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.models.chatbot import ChatSessionState
from src.app.services import bid_queries
from src.app.services.auth_forms import login_form, signup_form
from src.app.services.home_context import (
    DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
    get_home_page_context,
)

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
    payload = {
        "user": user,
        "active_nav": active_nav,
        "social_login_providers": SOCIAL_LOGIN_PROVIDERS,
        **context,
    }
    return templates.TemplateResponse(request, name, payload)


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
    page_obj = bid_queries.list_announcements(
        db, q=q, cat=cat, region=region, sort=sort, page=page
    )
    context = {
        "bids": page_obj.object_list,
        "page_obj": page_obj,
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
    page_obj = bid_queries.list_results(
        db, q=q, cat=cat, region=region, sort=sort, page=page
    )
    context = {
        "results": page_obj.object_list,
        "page_obj": page_obj,
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
def dashboard(
    request: Request, user: CustomUser | None = Depends(get_current_user)
):
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
def signup_page(
    request: Request, user: CustomUser | None = Depends(get_current_user)
):
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
        register_user(signup_payload, response, db)
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

    account = db.execute(
        select(CustomUser).where(CustomUser.username == username)
    ).scalar_one_or_none()

    if account is None or not check_password(password, account.password):
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

    account.last_login = utcnow()
    db.commit()

    redirect = RedirectResponse(url=_safe_next_path(next), status_code=303)
    redirect.set_cookie(
        SESSION_COOKIE_NAME,
        create_session(account.id, account.username),
        httponly=True,
        samesite="lax",
    )
    return redirect


@router.get("/accounts/logout/")
@router.post("/accounts/logout/")
def logout_submit(bidbox_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME)):
    """원본은 링크(GET)로 로그아웃하므로 두 메서드를 모두 받습니다."""
    destroy_session(bidbox_session)
    response = RedirectResponse(url="/accounts/login/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
