"""마이페이지 정보 수정 화면의 '등급확인서로 채우기' 시험.

정본: .orca/capsules/task_e4380edcfe23/capsule.yaml.
 - 기능 토글이 꺼져 있으면 업로드 블록과 스크립트를 렌더링하지 않는다.
 - 토글이 켜지면 PDF 선택 input(accept=application/pdf), '등급확인서로 채우기' 버튼,
   결과 영역, 안내 문구, doc-autofill.js <script src> 가 나온다.
 - 블록에는 인라인 이벤트 속성(on*=)이 없고 저장·제출을 유발하는 요소가 없다.
 - doc-autofill.js 는 innerHTML·insertAdjacentHTML 을 쓰지 않고 textContent 로만 넣으며,
   /api/v1/documents/extract 로만 fetch 하고 폼 submit 을 호출하지 않는다.
 - 이용약관 개인정보처리방침에 자동 입력 고지가 있다.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

import src.app.api.ui as ui_module
from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser

EDIT_URL = "/accounts/mypage/edit/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = PROJECT_ROOT / "src/app/static/js/doc-autofill.js"
TERMS_PATH = PROJECT_ROOT / "src/app/templates/accounts/terms_content.html"
EXTRACT_ENDPOINT = "/api/v1/documents/extract"

INLINE_HANDLER_NAMES = {"onclick", "onchange", "onsubmit", "oninput", "onload"}


class _AttributeCollector(HTMLParser):
    """응답 본문 모든 시작 태그의 속성을 모읍니다."""

    def __init__(self) -> None:
        super().__init__()
        self.attributes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.attributes.append(dict(attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.attributes.append(dict(attrs))


def _create_user(db, *, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-test-1234"),
        email=f"{username}@example.com",
        nickname="자동 입력 시험",
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


class _SettingsWithToggle:
    """ui.py 가 읽는 설정 객체에 기능 토글만 덧씌우는 프록시입니다.

    설정 필드는 다른 빌더가 config.py 에 추가하므로 이 워크트리에는 아직 없습니다.
    pydantic Settings 는 미정의 필드 대입을 막으므로, ui 모듈의 settings 바인딩만
    바꿔 getattr 기본값 False 경로와 True 경로를 모두 시험합니다.
    """

    def __init__(self, base, enabled: bool) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "DOCUMENT_EXTRACTION_ENABLED", enabled)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_base"), name)


def _set_toggle(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(ui_module, "settings", _SettingsWithToggle(settings, enabled))


def test_block_hidden_when_toggle_off(monkeypatch, isolated_db):
    _set_toggle(monkeypatch, False)
    user = _create_user(isolated_db, username="doc_autofill_off")

    body = _auth_client(user).get(EDIT_URL).text

    assert "등급확인서로 채우기" not in body
    assert "doc-autofill.js" not in body
    assert "doc-autofill-file" not in body


def test_block_rendered_when_toggle_on(monkeypatch, isolated_db):
    _set_toggle(monkeypatch, True)
    user = _create_user(isolated_db, username="doc_autofill_on")

    body = _auth_client(user).get(EDIT_URL).text

    assert "등급확인서로 채우기" in body
    assert 'accept="application/pdf"' in body
    assert "doc-autofill-status" in body
    assert "doc-autofill-result-credit_grade" in body
    assert "doc-autofill-result-credit_evaluated_on" in body
    assert "저장하지 않습니다" in body
    assert "외부로 전송하지 않습니다" in body
    assert "js/doc-autofill.js" in body


def test_block_has_no_inline_event_attributes(monkeypatch, isolated_db):
    _set_toggle(monkeypatch, True)
    user = _create_user(isolated_db, username="doc_autofill_events")

    body = _auth_client(user).get(EDIT_URL).text
    inspector = _AttributeCollector()
    inspector.feed(body)

    assert "data-doc-autofill" in body, "업로드 블록을 찾지 못했습니다"
    for attributes in inspector.attributes:
        assert INLINE_HANDLER_NAMES.isdisjoint(attributes)
        assert not any(name.lower().startswith("on") for name in attributes)
    assert "/api/v1/documents/extract" not in body


def test_javascript_avoids_unsafe_rendering_and_submit():
    source = JS_PATH.read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "document.write" not in source
    assert "textContent" in source
    assert "createElement" in source
    assert "addEventListener" in source
    assert "javascript:" not in source.lower()


def test_javascript_only_calls_extract_endpoint():
    source = JS_PATH.read_text(encoding="utf-8")

    assert f"'{EXTRACT_ENDPOINT}'" in source
    assert "credentials: 'same-origin'" in source
    assert "'Content-Type': 'application/pdf'" in source
    assert ".submit(" not in source
    assert ".submit()" not in source
    assert "form.submit" not in source
    # 외부 도메인 호출이 없고, fetch 대상은 추출 API 하나뿐이다.
    assert "http://" not in source
    assert "https://" not in source
    assert source.count("fetch(") == 1


def test_javascript_guards_file_size_and_type():
    source = JS_PATH.read_text(encoding="utf-8")

    assert "5 * 1024 * 1024" in source
    assert "application/pdf" in source
    assert "disabled" in source


def test_terms_include_document_extraction_notice():
    terms = TERMS_PATH.read_text(encoding="utf-8")

    assert "등급확인서 자동 입력" in terms
    assert "저장하지 않고" in terms
    assert "외부로 전송하지 않습니다" in terms
    assert "평가 입력 보조" in terms


def _js_block(source: str, start_marker: str, end_marker: str) -> str:
    """source 에서 start_marker 부터 end_marker 직전까지 잘라 돌려줍니다."""

    start = source.index(start_marker)
    return source[start : source.index(end_marker, start)]


def test_unrecognized_fills_only_evaluated_on():
    source = JS_PATH.read_text(encoding="utf-8")

    branch = _js_block(
        source,
        "payload.status === 'unrecognized'",
        "var fields = payload.fields || {};",
    )

    assert "UNRECOGNIZED_DATE_MESSAGE" in branch
    assert "payload.fields && payload.fields.credit_evaluated_on" in branch
    assert "fillEvaluatedOn(date)" in branch
    assert "fillCreditGrade" not in branch
    # 평가일도 없거나 채우지 못했으면 기존 미인식 문구로 끝난다.
    assert "UNRECOGNIZED_MESSAGE" in branch


def test_append_evidence_uses_single_object():
    source = JS_PATH.read_text(encoding="utf-8")

    # 서버는 근거를 단일 객체로 주므로 배열 분기를 두지 않는다.
    assert "Array.isArray" not in source
    block = _js_block(source, "function appendEvidence(", "function renderField(")

    assert "evidence.page" in block
    assert "evidence.text" in block
    assert "'p.' + evidence.page + ' '" in block
