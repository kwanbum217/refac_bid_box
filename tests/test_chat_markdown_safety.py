"""
tests/test_chat_markdown_safety.py

챗봇 응답 markdown 렌더링의 XSS 방어를 검증합니다.

chat.js 는 marked renderer 로 원시 HTML 토큰(블록·인라인)을 이스케이프하고
링크·이미지는 허용 스킴만 통과시킵니다. Node 와 vendor marked 가 있으면
chat.js 의 renderer 설정을 그대로 추출해 실제 렌더 결과를 확인하고, 없으면
소스에 대한 정적 단언으로 대체합니다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_JS = REPO_ROOT / "src" / "app" / "static" / "js" / "chat.js"
MARKED_JS = REPO_ROOT / "src" / "app" / "static" / "vendor" / "marked" / "15.0.12" / "marked.min.js"

PAYLOADS = [
    {"name": "unsafe_img", "input": "업체 <img src=x onerror=alert(1)> 안내"},
    {"name": "unsafe_script", "input": "<script>alert(1)</script>"},
    {"name": "fenced_html", "input": "```html\n<script>alert(1)</script>\n```"},
    {"name": "js_link", "input": "[click](javascript:alert(1))"},
    {"name": "data_image", "input": "![pic](data:text/html;base64,PHNjcmlwdD4=)"},
    {"name": "vbscript_link", "input": "[x](vbscript:msgbox(1))"},
    {"name": "protocol_relative", "input": "[x](//evil.example/path)"},
    {"name": "safe_http", "input": "[ok](https://example.com/a?b=1&c=2)"},
    {"name": "safe_relative", "input": "[rel](/bids/list/?q=1)"},
    {"name": "safe_hash", "input": "[here](#section)"},
    {"name": "safe_mailto", "input": "[mail](mailto:a@example.com)"},
    {"name": "normal_table", "input": "| a | b |\n| --- | --- |\n| 1 | 2 |"},
    {"name": "normal_bold", "input": "**bold** text"},
    {"name": "normal_list", "input": "- one\n- two"},
    {"name": "normal_code", "input": "```python\nprint(1)\n```"},
    {
        "name": "citation_badge",
        "input": '<span class="citation-badge" title="Source #1">1</span>',
    },
]


def _source() -> str:
    return CHAT_JS.read_text(encoding="utf-8")


def _extract_balanced(text: str, open_index: int) -> str:
    """text[open_index] 가 '{' 일 때 짝이 맞는 '}' 까지를 돌려줍니다."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
    raise AssertionError("중괄호 짝이 맞지 않습니다")


def _extract_function(text: str, name: str) -> str:
    start = text.index(f"function {name}(")
    brace = text.index("{", start)
    return text[start:brace] + _extract_balanced(text, brace)


def _extract_statement(text: str, marker: str) -> str:
    start = text.index(marker)
    return text[start : text.index(";", start) + 1]


def _extract_marked_use(text: str) -> str:
    start = text.index("marked.use(")
    brace = text.index("{", start)
    return "marked.use(" + _extract_balanced(text, brace) + ");"


def _build_node_harness() -> str:
    text = _source()
    return "\n".join(
        [
            f"const marked = require({json.dumps(str(MARKED_JS))});",
            "marked.setOptions({ breaks: true, gfm: true });",
            _extract_function(text, "escapeHtml"),
            _extract_statement(text, "const CITATION_BADGE_OPEN"),
            _extract_function(text, "isSafeMarkdownUrl"),
            _extract_marked_use(text),
            f"const payloads = {json.dumps(PAYLOADS)};",
            "const out = payloads.map((p) => ({ name: p.name, html: marked.parse(p.input) }));",
            "process.stdout.write(JSON.stringify(out));",
        ]
    )


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    node = shutil.which("node")
    if node is None or not MARKED_JS.is_file():
        pytest.skip("node 또는 vendor marked 를 사용할 수 없습니다")
    result = subprocess.run(  # noqa: S603 - node 경로와 인자를 이 테스트가 직접 고정합니다
        [node, "-e", _build_node_harness()],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return {item["name"]: item["html"] for item in json.loads(result.stdout)}


# --------------------------------------------------------------------------- #
# 소스 정적 단언. Node 없이도 방어 설정 자체가 남아 있는지 확인합니다.
# --------------------------------------------------------------------------- #


def test_fence_stripping_removed():
    """```html 펜스를 지우던 코드가 제거되어 코드블록이 일반 markdown 으로 렌더된다."""
    text = _source()
    assert "replace(/```html/gi" not in text
    assert "replace(/```/g" not in text


def test_renderer_escapes_raw_html_and_limits_schemes():
    text = _source()
    use_block = _extract_marked_use(text)
    assert "escapeHtml(raw)" in use_block
    assert "isSafeMarkdownUrl(token.href)" in use_block
    assert "renderer:" in use_block
    # 표·굵게·목록 등 다른 토큰의 renderer 를 덮어쓰지 않습니다.
    for overridden in ("table(", "strong(", "list(", "code("):
        assert overridden not in use_block


# --------------------------------------------------------------------------- #
# 실제 렌더 결과. (Node 가 없으면 skip)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name,forbidden",
    [
        ("unsafe_img", ["<img"]),
        ("unsafe_script", ["<script"]),
        ("fenced_html", ["<script"]),
        ("js_link", ["javascript:"]),
        ("data_image", ["data:", "<img"]),
        ("vbscript_link", ["vbscript:"]),
        ("protocol_relative", ["//evil.example"]),
    ],
)
def test_dangerous_markup_is_neutralized(rendered, name, forbidden):
    html = rendered[name]
    for fragment in forbidden:
        assert fragment not in html, f"{name}: {fragment!r} 가 렌더 결과에 남았습니다: {html}"


def test_raw_html_is_escaped_not_executed(rendered):
    html = rendered["unsafe_img"]
    assert "&lt;img" in html
    assert "<img" not in html


def test_safe_links_are_preserved(rendered):
    assert '<a href="https://example.com/a?b=1&amp;c=2">ok</a>' in rendered["safe_http"]
    assert '<a href="/bids/list/?q=1">rel</a>' in rendered["safe_relative"]
    assert '<a href="#section">here</a>' in rendered["safe_hash"]
    assert '<a href="mailto:a@example.com">mail</a>' in rendered["safe_mailto"]


def test_general_markdown_still_renders(rendered):
    assert "<table>" in rendered["normal_table"]
    assert "<strong>bold</strong>" in rendered["normal_bold"]
    assert "<ul>" in rendered["normal_list"]
    assert "<li>" in rendered["normal_list"]
    assert '<pre><code class="language-python">' in rendered["normal_code"]


def test_own_citation_badge_passes_through(rendered):
    html = rendered["citation_badge"]
    assert '<span class="citation-badge" title="Source #1">' in html
    assert "&lt;span" not in html
