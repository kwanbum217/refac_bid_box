r"""
tests/test_templating_escape.py

escapejs / to_json 필터의 JS 문맥 이스케이프를 검증합니다.

escapejs 는 작은따옴표 문자열과 script 본문에서 리터럴을 조기 종료시키는 문자를,
to_json 은 script 태그를 닫거나 JS 문자열을 끊는 문자를 \uXXXX 로 치환해야 합니다.
"""

from __future__ import annotations

import json

from markupsafe import Markup

from src.app.core.templating import escapejs, templates, to_json


def test_escapejs_removes_dangerous_literals():
    raw = "a'</script>\"&=\\;`b\n\t\u2028\u2029\x07"
    escaped = str(escapejs(raw))
    for forbidden in ("'", '"', "<", ">", "&", "`", "\n", "\t", "\u2028", "\u2029", "\x07"):
        assert forbidden not in escaped, f"{forbidden!r} 가 남았습니다: {escaped}"
    assert "\\u0027" in escaped
    assert "\\u003C" in escaped
    assert "\\u003E" in escaped
    assert "\\u0026" in escaped
    assert "\\u005C" in escaped
    assert "\\u003D" in escaped
    assert "\\u003B" in escaped
    assert "\\u2028" in escaped
    assert "\\u2029" in escaped
    assert "\\u0007" in escaped


def test_escapejs_keeps_safe_text_intact():
    assert str(escapejs("Thng")) == "Thng"


def test_escapejs_returns_markup_so_jinja_does_not_double_escape():
    result = escapejs("a'b")
    assert isinstance(result, Markup)
    assert str(result) == "a\\u0027b"


def test_escapejs_renders_inside_js_string_literal_without_breaking_out():
    template = templates.env.from_string("const c = '{{ value|escapejs }}';")
    output = template.render(value="x'; alert(1); //")
    assert "x'; alert(1); //" not in output
    assert "&#39;" not in output
    assert "\\u0027" in output


def test_to_json_escapes_script_breakers():
    encoded = str(to_json({"note": "</script><b>&</b>", "sep": "a\u2028b\u2029c"}))
    for forbidden in ("</script>", "<", ">", "&", "\u2028", "\u2029"):
        assert forbidden not in encoded, f"{forbidden!r} 가 남았습니다: {encoded}"
    assert "\\u003c" in encoded
    assert "\\u003e" in encoded
    assert "\\u0026" in encoded
    assert "\\u2028" in encoded
    assert "\\u2029" in encoded


def test_to_json_remains_valid_json_after_escaping():
    payload = {"note": "<script>alert(1)</script>", "items": [1, "a&b"]}
    assert json.loads(str(to_json(payload))) == payload


def test_to_json_is_markup():
    assert isinstance(to_json({"a": 1}), Markup)
