"""bootstrap.min.css 의 !important 유틸리티를 Tailwind 다크 모드 값이 이기도록 고정한다.

묶음 1(dark:border-*), 묶음 2(dark:text-blue-*), 묶음 3(.dark .h-card 강화)를 검사한다.
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
LINE_CLASS_RE = re.compile(r'class="([^"]*)"')

# 묶음 1: dark:border-*, 묶음 2: dark:text-blue-*
DARK_BORDER_TARGETS = {
    "src/app/templates/base.html": {
        224: "dark:border-slate-700!",
        254: "dark:border-slate-700!",
        260: "dark:border-slate-700!",
        266: "dark:border-slate-700!",
        286: "dark:border-slate-800!",
        305: "dark:border-slate-700!",
        313: "dark:border-slate-700!",
        321: "dark:border-slate-700!",
    },
    "src/app/templates/index.html": {
        69: "dark:border-slate-800!",
        85: "dark:border-slate-800!",
        96: "dark:border-slate-800!",
    },
    "src/app/templates/chatbot/chat.html": {
        673: "dark:border-slate-700!",
        675: "dark:border-slate-600!",
    },
}
DARK_FOCUS_BORDER_TARGETS = {
    "src/app/templates/chatbot/chat.html": {
        673: "dark:focus:border-primary!",
    },
}
DARK_TEXT_TARGETS = {
    "src/app/templates/index.html": {
        196: ["dark:text-blue-400!", "dark:hover:text-blue-300!"],
        203: ["dark:text-blue-400!", "dark:hover:text-blue-300!"],
    },
}
REQUIRED_CSS_RULES = [
    ".dark .h-card.bg-white",
    ".dark .h-card.border",
]


def _line_classes(path: Path, lineno: int) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lineno <= len(lines), f"{path.name}:{lineno} 행이 없다"
    match = LINE_CLASS_RE.search(lines[lineno - 1])
    assert match, f"{path.name}:{lineno} 에 class 속성이 없다"
    return match.group(1).split()


@pytest.mark.parametrize(
    "relpath,targets",
    DARK_BORDER_TARGETS.items(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_dark_border_classes_have_important_suffix(relpath, targets):
    path = ROOT / relpath
    for lineno, expected in targets.items():
        classes = _line_classes(path, lineno)
        assert expected in classes, f"{relpath}:{lineno} 에 {expected} 가 없다"
        offenders = [
            cls
            for cls in classes
            if cls.startswith("dark:") and "border-" in cls and not cls.endswith("!")
        ]
        assert not offenders, f"{relpath}:{lineno}: {offenders}"


def test_dark_focus_border_has_important_suffix():
    for relpath, targets in DARK_FOCUS_BORDER_TARGETS.items():
        path = ROOT / relpath
        for lineno, expected in targets.items():
            classes = _line_classes(path, lineno)
            assert expected in classes, f"{relpath}:{lineno} 에 {expected} 가 없다"


def test_dark_text_blue_classes_have_important_suffix():
    for relpath, targets in DARK_TEXT_TARGETS.items():
        path = ROOT / relpath
        for lineno, expected in targets.items():
            classes = _line_classes(path, lineno)
            for token in expected:
                assert token in classes, f"{relpath}:{lineno} 에 {token} 가 없다"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_dark_bg_and_border_utilities_have_important_suffix(path):
    text = path.read_text(encoding="utf-8")
    offenders = []
    for match in CLASS_ATTR_RE.finditer(text):
        classes = match.group(1).split()
        if "bg-white" in classes:
            offenders += [
                cls for cls in classes if cls.startswith("dark:bg-") and not cls.endswith("!")
            ]
        if "border" in classes:
            offenders += [
                cls
                for cls in classes
                if cls.startswith("dark:") and "border-" in cls and not cls.endswith("!")
            ]
    assert not offenders, f"{path.relative_to(ROOT)}: {offenders}"


def test_tailwind_css_contains_h_card_important_rules():
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    for selector in REQUIRED_CSS_RULES:
        pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}")
        match = pattern.search(css)
        assert match, f"tailwind.css 에 {selector} 규칙이 없다"
        assert "!important" in match.group(1), match.group(0)
