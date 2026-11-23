"""bootstrap.min.css 의 .bg-white !important 를 Tailwind dark:bg-* 가 이기도록 고정한다."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = [
    ROOT / "src/app/templates/base.html",
    ROOT / "src/app/templates/chatbot/chat.html",
    ROOT / "src/app/templates/index.html",
]
TAILWIND_CSS = ROOT / "src/app/static/css/tailwind.css"

CLASS_ATTR_RE = re.compile(r'class="([^"]*)"', re.S)
REQUIRED_CSS_CLASSES = [
    r".dark\:bg-slate-950\!",
    r".dark\:bg-slate-900\!",
    r".dark\:bg-slate-950\/40\!",
]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_dark_bg_classes_have_important_suffix(path):
    text = path.read_text(encoding="utf-8")
    offenders = []
    for match in CLASS_ATTR_RE.finditer(text):
        classes = match.group(1).split()
        if "bg-white" not in classes:
            continue
        for cls in classes:
            if cls.startswith("dark:bg-") and not cls.endswith("!"):
                offenders.append(cls)
    assert not offenders, f"{path.relative_to(ROOT)}: {offenders}"


def test_all_bg_white_templates_covered():
    found = [path for path in TEMPLATES if "bg-white" in path.read_text(encoding="utf-8")]
    assert found == TEMPLATES


def test_tailwind_css_contains_important_rules():
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    missing = [selector for selector in REQUIRED_CSS_CLASSES if selector not in css]
    assert not missing, f"tailwind.css 에 없는 중요도 클래스: {missing}"
    for selector in REQUIRED_CSS_CLASSES:
        start = css.index(selector)
        body = css[start : css.index("}", start) + 1]
        assert "!important" in body, body
