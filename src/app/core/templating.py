"""
src/app/core/templating.py

원본 Django 템플릿을 Jinja2 로 1:1 이식하기 위한 호환 계층입니다.
Django 내장 필터/태그와 동일한 이름·동작을 제공해 템플릿 본문을 원본 그대로
유지할 수 있게 합니다. 템플릿 이식 시 문법 변환량을 최소화하는 것이 목적입니다.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup
from starlette.datastructures import URL
from starlette.requests import Request

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
STATIC_VERSION_QUERY = "v"
STATIC_VERSION_LENGTH = 10

# Django url name -> FastAPI SSR 경로. 원본 템플릿의 {% url %} 호출을 그대로 옮기기 위한 표입니다.
URL_MAP = {
    "index": "/",
    "bids:bid_list": "/bids/",
    "bids:bid_detail": "/bids/{pk}/",
    "bids:result_list": "/bids/results/",
    "bids:result_detail": "/bids/result/{pk}/",
    "bids:dashboard": "/bids/dashboard/",
    "bids:compare": "/bids/compare/",
    "bids:api_stats": "/api/v1/bids/stats",
    "bids:api_compare_stats": "/api/v1/bids/compare-stats",
    "predictions:list_models": "/api/v1/predictions/list-models",
    "predictions:predict_price": "/api/v1/predictions/predict-price",
    "chatbot:chat_page": "/chatbot/",
    "chatbot:chat_api": "/api/v1/chatbot/chat",
    # 원본에는 없던 경로입니다. 설계서 G3 레이턴시 목표에 따라 추가한 SSE 스트리밍이며
    # 응답 계약은 chat_api 와 같습니다 (final 이벤트가 동일한 ChatResponse).
    "chatbot:chat_stream": "/api/v1/chatbot/chat/stream",
    "chatbot:new_chat_session": "/api/v1/chatbot/session/new",
    # 자동화 작업 제어. 원본은 /chatbot/api/automation/job/<id>/... 였습니다.
    # 화면 스크립트가 job_id 를 런타임에 끼워 넣으므로 자리표시자를 그대로 둡니다.
    "chatbot:automation_job_confirm": "/api/v1/automation/job/{job_id}/confirm",
    "chatbot:automation_job_status": "/api/v1/automation/job/{job_id}/status",
    "chatbot:automation_job_cancel": "/api/v1/automation/job/{job_id}/cancel",
    "accounts:login": "/accounts/login/",
    "accounts:logout": "/accounts/logout/",
    "accounts:signup": "/accounts/signup/",
    "accounts:mypage": "/accounts/mypage/",
    "accounts:mypage_edit": "/accounts/mypage/edit/",
    "accounts:logout_all": "/accounts/mypage/logout-all/",
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


# Django escapejs 와 동일한 JS 문맥 이스케이프 표입니다. 작은따옴표 문자열이나
# script 본문에서 리터럴이 조기 종료되거나 태그가 닫히지 않도록 위험 문자를
# \uXXXX 로 치환합니다.
_JS_ESCAPES = {
    ord("\\"): "\\u005C",
    ord("'"): "\\u0027",
    ord('"'): "\\u0022",
    ord(">"): "\\u003E",
    ord("<"): "\\u003C",
    ord("&"): "\\u0026",
    ord("="): "\\u003D",
    ord("-"): "\\u002D",
    ord(";"): "\\u003B",
    ord("`"): "\\u0060",
    ord("\u2028"): "\\u2028",
    ord("\u2029"): "\\u2029",
}
_JS_ESCAPES.update((code, f"\\u{code:04X}") for code in range(32))


def escapejs(value) -> str:
    """{{ x|escapejs }} 대응. JS 리터럴 안에 안전하게 삽입합니다.

    json.dumps 는 작은따옴표와 </script> 를 그대로 남겨, 작은따옴표 문자열이나
    script 본문에서 이스케이프가 깨집니다. Django escapejs 와 같이 위험 문자를
    \\uXXXX 로 치환합니다.
    """
    return Markup(str(value or "").translate(_JS_ESCAPES))  # nosec B704 - JS 이스케이프를 거친 값만 Markup 으로 감쌉니다


def to_json(value) -> Markup:
    """script 태그 안에 파이썬 객체를 그대로 실어 보내기 위한 헬퍼입니다.

    json.dumps 결과의 <, >, & 는 script 본문에서 태그를 조기에 닫거나 엔티티로
    해석될 수 있고, U+2028/U+2029 는 JS 문자열을 끊습니다. 모두 \\uXXXX 로
    치환합니다.
    """
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    for char, replacement in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        encoded = encoded.replace(char, replacement)
    return Markup(encoded)  # nosec B704 - JS 이스케이프를 거친 값만 Markup 으로 감쌉니다


def csp_nonce_context(request: Request) -> dict[str, str]:
    """요청 상태에 실린 CSP nonce 를 모든 템플릿 컨텍스트에 넣습니다.

    값은 src/app/core/csp.py 미들웨어가 요청마다 새로 발급합니다. 미들웨어를
    거치지 않은 렌더(테스트의 직접 렌더 등)에서는 빈 문자열로 떨어집니다.
    """
    return {"csp_nonce": str(getattr(request.state, "csp_nonce", ""))}


def _resolve_static_path(path: str) -> Path | None:
    """static 디렉터리 안의 실제 파일 경로를 돌려줍니다. 벗어나면 None 입니다.

    템플릿 변수에서 온 경로라도 정규화한 뒤 부모 디렉터리로 벗어나는지 확인해,
    static 밖 파일의 stat·노출을 막습니다.
    """
    if not path or path.startswith("/"):
        return None
    normalized = posixpath.normpath(path)
    if normalized in ("", ".") or normalized.startswith("..") or normalized.startswith("/"):
        return None
    try:
        resolved = (STATIC_DIR / normalized).resolve(strict=True)
        static_root = STATIC_DIR.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        resolved.relative_to(static_root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def static_asset_version(path: str) -> str:
    """정적 파일의 mtime·크기로 짧은 버전 문자열을 만듭니다.

    렌더마다 stat 한 번만 쓰므로 파일이 바뀌면 프로세스 재시작 없이 새 버전이
    나갑니다. 파일이 없거나 static 밖 경로면 빈 문자열을 돌려줍니다.
    """
    target = _resolve_static_path(path)
    if target is None:
        return ""
    try:
        stat = target.stat()
    except OSError:
        return ""
    seed = f"{stat.st_mtime_ns}:{stat.st_size}".encode()
    return hashlib.sha256(seed).hexdigest()[:STATIC_VERSION_LENGTH]


@pass_context
def url_for_static_versioned(context: dict[str, Any], name: str, /, **path_params: Any) -> URL:
    """url_for 를 감싸 static URL 에만 파일 버전 쿼리를 붙입니다.

    Starlette 의 url_for 와 같은 pass_context 규약을 따릅니다. static 외
    라우트와 버전을 만들 수 없는 경로는 원래 URL 을 그대로 돌려줍니다.
    """
    request: Request = context["request"]
    generated = request.url_for(name, **path_params)
    if name != "static":
        return generated
    version = static_asset_version(str(path_params.get("path", "")))
    if not version:
        return generated
    url = str(generated)
    separator = "&" if "?" in url else "?"
    return URL(f"{url}{separator}{STATIC_VERSION_QUERY}={version}")


def _build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[csp_nonce_context])
    env = templates.env
    env.globals["url_for"] = url_for_static_versioned
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
