"""bootstrap.min.css 의 !important 유틸리티를 Tailwind 다크 모드 값이 이기도록 고정한다.

묶음 1(dark:border-*), 묶음 2(dark:text-blue-*), 묶음 3(.dark .h-card 강화)은 2026-11-23 되돌렸으므로 그 규칙이 없는지 검사한다.
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
        223: "dark:border-slate-700!",
        253: "dark:border-slate-700!",
        259: "dark:border-slate-700!",
        265: "dark:border-slate-700!",
        285: "dark:border-slate-800!",
        304: "dark:border-slate-700!",
        312: "dark:border-slate-700!",
        320: "dark:border-slate-700!",
    },
    "src/app/templates/index.html": {
        69: "dark:border-slate-800!",
        85: "dark:border-slate-800!",
        96: "dark:border-slate-800!",
    },
    "src/app/templates/chatbot/chat.html": {
        686: "dark:border-slate-700!",
        688: "dark:border-slate-600!",
    },
}
DARK_FOCUS_BORDER_TARGETS = {
    "src/app/templates/chatbot/chat.html": {
        686: "dark:focus:border-primary!",
    },
}
DARK_TEXT_TARGETS = {
    "src/app/templates/index.html": {
        196: ["dark:text-blue-400!", "dark:hover:text-blue-300!"],
        203: ["dark:text-blue-400!", "dark:hover:text-blue-300!"],
    },
}
# 2026-11-23 되돌림: compare.html·result_detail.html 의 h-card 안 글자는 다크 변형이 없어
# 카드만 어둡게 강제하면 어두운 배경에 어두운 글자가 된다. 그 화면들을 다크 대응하기 전까지
# 이 강제 규칙을 다시 넣지 않는다.
FORBIDDEN_CSS_RULES = [
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


def test_tailwind_css_has_no_forced_h_card_dark_rules():
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    for selector in FORBIDDEN_CSS_RULES:
        assert selector not in css, f"tailwind.css 에 {selector} 강제 규칙이 다시 들어왔다"
