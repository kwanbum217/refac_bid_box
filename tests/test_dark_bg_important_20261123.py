"""bg-white 요소의 dark:bg-* 대응이 빌드 CSS 에 살아 있는지 고정한다.

510ac531 로 Bootstrap 을 제거한 뒤로는 dark:bg-* 의 ! 접미사가 필요 없다. h-card
요소만 `.dark .h-card` 규칙과 겨루므로 ! 를 남기며, 그 목록은
tests/test_dark_suffix_cleanup_20261124.py 가 관리한다.
"""

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
CLASS_SELECTOR_BOUNDARY = frozenset("{:,")


def _css_selector(token: str) -> str:
    parts = ["."]
    for char in token:
        parts.append("\\" + char if char in ":/.#%()[]!,*+~" else char)
    return "".join(parts)


def _selector_present(selector: str, css: str) -> bool:
    start = 0
    while True:
        index = css.find(selector, start)
        if index == -1:
            return False
        following = index + len(selector)
        if following >= len(css) or css[following] in CLASS_SELECTOR_BOUNDARY:
            return True
        start = index + 1


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_dark_bg_variants_exist_in_build_css(path):
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    missing = []
    for match in CLASS_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
        classes = match.group(1).split()
        if "bg-white" not in classes:
            continue
        for cls in classes:
            if cls.startswith("dark:bg-") and not _selector_present(_css_selector(cls), css):
                missing.append(cls)
    assert not missing, f"{path.relative_to(ROOT)}: {missing}"


def test_all_bg_white_templates_covered():
    found = [path for path in TEMPLATES if "bg-white" in path.read_text(encoding="utf-8")]
    assert found == TEMPLATES


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_bg_white_elements_keep_important_suffix_only_on_h_card(path):
    offenders = []
    for match in CLASS_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
        classes = match.group(1).split()
        if "bg-white" not in classes or "h-card" in classes:
            continue
        offenders += [cls for cls in classes if cls.startswith("dark:bg-") and cls.endswith("!")]
    assert not offenders, f"{path.relative_to(ROOT)}: {offenders}"
