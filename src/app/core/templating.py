"""
src/app/core/templating.py

원본 Django 템플릿을 Jinja2 로 1:1 이식하기 위한 호환 계층입니다.
Django 내장 필터/태그와 동일한 이름·동작을 제공해 템플릿 본문을 원본 그대로
유지할 수 있게 합니다. 템플릿 이식 시 문법 변환량을 최소화하는 것이 목적입니다.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = APP_DIR / "templates"

# Django url name -> FastAPI SSR 경로. 원본 템플릿의 {% url %} 호출을 그대로 옮기기 위한 표입니다.
URL_MAP = {
    "index": "/",
    "bids:bid_list": "/bids/",
    "bids:bid_detail": "/bids/{pk}/",
    "bids:result_list": "/results/",
    "bids:result_detail": "/results/{pk}/",
    "bids:dashboard": "/dashboard/",
    "bids:compare": "/compare/",
    "bids:api_stats": "/api/v1/bids/stats",
    "bids:api_compare_stats": "/api/v1/bids/compare-stats",
    "predictions:list_models": "/api/v1/predictions/list-models",
    "predictions:predict_price": "/api/v1/predictions/predict-price",
    "chatbot:chat_page": "/chat/",
    "chatbot:chat_api": "/api/v1/chatbot/chat",
    "chatbot:new_chat_session": "/api/v1/chatbot/session/new",
    # 자동화 작업 제어. 원본은 /chatbot/api/automation/job/<id>/... 였습니다.
    # 화면 스크립트가 job_id 를 런타임에 끼워 넣으므로 자리표시자를 그대로 둡니다.
    "chatbot:automation_job_confirm": "/api/v1/automation/job/{job_id}/confirm",
    "chatbot:automation_job_status": "/api/v1/automation/job/{job_id}/status",
    "chatbot:automation_job_cancel": "/api/v1/automation/job/{job_id}/cancel",
    "accounts:login": "/accounts/login/",
    "accounts:logout": "/accounts/logout/",
    "accounts:signup": "/accounts/signup/",
}


def url(name: str, *args, **kwargs) -> str:
    """{% url 'name' arg %} 대응. 위치 인자는 경로 파라미터 순서대로 치환합니다."""
    try:
        pattern = URL_MAP[name]
    except KeyError as exc:
        raise ValueError(f"알 수 없는 URL 이름입니다: {name}") from exc

    if args:
        for value in args:
            pattern = pattern.replace("{pk}", str(value), 1)
    for key, value in kwargs.items():
        pattern = pattern.replace("{" + key + "}", str(value))
    return pattern


def provider_login_url(provider: str, **kwargs) -> str:
    """원본은 django-allauth 소셜 로그인을 사용했습니다.

    이식본에는 소셜 인증이 없으므로 링크를 비활성 처리합니다. 동작하지 않는 경로를
    정상 링크처럼 보이게 두지 않기 위해 명시적으로 빈 앵커를 반환합니다.
    """
    return ""


def intcomma(value) -> str:
    """{{ x|intcomma }} 대응. 천 단위 구분 기호를 넣습니다."""
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,}"


def floatformat(value, digits: int = -1) -> str:
    """{{ x|floatformat:n }} 대응. 음수 자릿수는 소수부가 있을 때만 표시합니다."""
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits < 0:
        if number == int(number):
            return str(int(number))
        return f"{number:.{abs(digits)}f}"
    if digits == 0:
        return str(round(number))
    return f"{number:.{digits}f}"


# Django date 포맷 문자 -> strftime 대응표
_DATE_FORMAT_MAP = {
    "Y": "%Y",
    "y": "%y",
    "m": "%m",
    "n": "%-m",
    "d": "%d",
    "j": "%-d",
    "H": "%H",
    "i": "%M",
    "s": "%S",
    "M": "%b",
    "D": "%a",
}


def django_date(value, fmt: str = "Y-m-d") -> str:
    """{{ x|date:"Y-m-d" }} 대응. Django 포맷 문자를 strftime 으로 변환합니다.

    Redis 캐시는 JSON 직렬화를 쓰기 때문에 datetime 이 문자열로 되돌아옵니다.
    원본(Django pickle 캐시)과 동일한 출력이 되도록 문자열도 파싱합니다.
    """
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, (datetime, date)):
        return "" if value is None else str(value)
    out = []
    for char in fmt:
        out.append(_DATE_FORMAT_MAP.get(char, char))
    try:
        return value.strftime("".join(out))
    except ValueError:
        return str(value)


def truncatechars(value, length: int) -> str:
    """{{ x|truncatechars:n }} 대응."""
    if value is None:
        return ""
    text = str(value)
    if len(text) <= length:
        return text
    return text[: max(length - 1, 0)] + "…"


def add(value, addend):
    """{{ x|add:n }} 대응. 숫자로 변환 가능하면 더하고, 아니면 문자열을 잇습니다."""
    try:
        return int(value) + int(addend)
    except (TypeError, ValueError):
        return f"{value}{addend}"


def default_if_none(value, fallback):
    """{{ x|default_if_none:y }} 대응. Django default 와 달리 None 만 대체합니다."""
    return fallback if value is None else value


def urlencode_filter(value) -> str:
    """{{ x|urlencode }} 대응."""
    return quote(str(value or ""), safe="")


def escapejs(value) -> str:
    """{{ x|escapejs }} 대응. JS 리터럴 안에 안전하게 삽입합니다."""
    return Markup(json.dumps(str(value or ""))[1:-1])


def to_json(value) -> Markup:
    """script 태그 안에 파이썬 객체를 그대로 실어 보내기 위한 헬퍼입니다."""
    return Markup(json.dumps(value, ensure_ascii=False, default=str))


def _build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    env = templates.env
    env.globals["url"] = url
    env.globals["provider_login_url"] = provider_login_url
    env.filters["intcomma"] = intcomma
    env.filters["add"] = add
    env.filters["floatformat"] = floatformat
    env.filters["date"] = django_date
    env.filters["truncatechars"] = truncatechars
    env.filters["default_if_none"] = default_if_none
    env.filters["urlencode"] = urlencode_filter
    env.filters["escapejs"] = escapejs
    env.filters["to_json"] = to_json
    return templates


templates = _build_templates()
