"""정적 파일 버전 쿼리와 /static Cache-Control 시험 (2026-11-23).

배포·수정 뒤 브라우저가 옛 정적 파일을 계속 쓰는 문제를 막는 계약입니다.
템플릿은 고치지 않고, url_for 가 만든 static URL 에 파일 버전을 붙이고
버전 유무에 따라 /static 응답의 Cache-Control 만 바꿉니다.
"""

from __future__ import annotations

import os

from starlette.requests import Request

from src.app.core import templating
from src.app.main import STATIC_IMMUTABLE_CACHE, STATIC_REVALIDATE_CACHE, app

STATIC_CSS = "css/tailwind.css"


def _request() -> Request:
    """앱 라우터를 붙인 최소 요청. 템플릿의 pass_context url_for 가 씁니다."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "app": app,
    }
    return Request(scope)


def _render(source: str) -> str:
    return templating.templates.env.from_string(source).render({"request": _request()})


def test_static_url_carries_version_query():
    """(a) 템플릿 렌더 결과의 static URL 에 ?v=<버전> 이 붙습니다."""
    html = templating.templates.env.get_template("base.html").render({"request": _request()})
    assert f"/static/{STATIC_CSS}?v=" in html

    rendered = _render("{{ url_for('static', path='css/tailwind.css') }}")
    assert "?v=" in rendered
    assert rendered.rstrip().endswith(
        "css/tailwind.css?v=" + templating.static_asset_version(STATIC_CSS)
    )

    # static 이 아닌 라우트 URL 은 그대로입니다.
    assert "?v=" not in _render("{{ url_for('index') }}")


def test_version_changes_when_file_changes(tmp_path, monkeypatch):
    """(b) 파일 mtime·크기가 바뀌면 재시작 없이 버전이 바뀝니다."""
    static_dir = tmp_path / "static"
    target = static_dir / STATIC_CSS
    target.parent.mkdir(parents=True)
    target.write_text("a{}", encoding="utf-8")
    monkeypatch.setattr(templating, "STATIC_DIR", static_dir)

    first = templating.static_asset_version(STATIC_CSS)
    assert first

    os.utime(target, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    second = templating.static_asset_version(STATIC_CSS)
    assert second
    assert second != first

    target.write_text("a{color:red}", encoding="utf-8")
    third = templating.static_asset_version(STATIC_CSS)
    assert third
    assert third != second


def test_missing_file_and_escape_paths_have_no_version():
    """(c) 없는 파일과 static 밖 경로는 쿼리 없이 원래 URL 을 돌려줍니다."""
    assert templating.static_asset_version("css/does-not-exist.css") == ""
    assert templating.static_asset_version("../core/templating.py") == ""
    assert templating.static_asset_version("/etc/passwd") == ""

    assert "?v=" not in _render("{{ url_for('static', path='css/does-not-exist.css') }}")
    assert "?v=" not in _render("{{ url_for('static', path='../app/core/templating.py') }}")


def test_static_cache_control_depends_on_version_query(client):
    """(d) v 가 있으면 장기 immutable, 없으면 재검증, 304 도 같은 규칙입니다."""
    plain = client.get(f"/static/{STATIC_CSS}")
    assert plain.status_code == 200
    assert plain.headers["cache-control"] == STATIC_REVALIDATE_CACHE

    versioned = client.get(f"/static/{STATIC_CSS}", params={"v": "abc"})
    assert versioned.status_code == 200
    assert versioned.headers["cache-control"] == STATIC_IMMUTABLE_CACHE

    etag = versioned.headers.get("etag")
    assert etag
    not_modified = client.get(
        f"/static/{STATIC_CSS}",
        params={"v": "abc"},
        headers={"If-None-Match": etag},
    )
    assert not_modified.status_code == 304
    assert not_modified.headers["cache-control"] == STATIC_IMMUTABLE_CACHE


def test_non_static_response_is_untouched(client):
    """(e) /static 밖 응답에는 Cache-Control 을 새로 붙이지 않습니다."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert "cache-control" not in response.headers
