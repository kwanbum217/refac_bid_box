"""Bootstrap 제거 뒤 dark:border-*, dark:text-*, dark:focus:border-* 의 ! 접미사가
사라졌음을 고정한다.

2026-11-23 에 bootstrap.min.css 의 !important 유틸리티를 이기려고 붙였던 접미사는
510ac531 이후 필요 없다. h-card 요소의 dark:border-*! 만 `.dark .h-card` 규칙 때문에
남으며, 그 목록은 tests/test_dark_suffix_cleanup_20261124.py 가 관리한다.
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

# ! 를 걷어낸 dark:border-* 자리. 지운 뒤에도 다크 테두리 변형 자체는 남아야 한다.
DARK_SUFFIX_CLEARED_TARGETS = {
    "src/app/templates/base.html": {
        59: "dark:bg-slate-950",
        219: "dark:bg-slate-950",
        220: "dark:bg-slate-900",
        223: "dark:border-slate-700",
        244: "dark:border-slate-700",
        289: "dark:border-slate-700",
        295: "dark:border-slate-700",
        301: "dark:border-slate-700",
        321: "dark:border-slate-800",
        340: "dark:border-slate-700",
        348: "dark:border-slate-700",
        356: "dark:border-slate-700",
        362: "dark:bg-slate-900",
    },
    "src/app/templates/index.html": {
        158: "dark:border-slate-800",
        174: "dark:border-slate-800",
        185: "dark:border-slate-800",
    },
    "src/app/templates/chatbot/chat.html": {
        560: "dark:bg-slate-900",
        627: "dark:bg-slate-900",
        651: "dark:border-slate-700",
        653: "dark:border-slate-600",
    },
}
DARK_FOCUS_BORDER_TARGETS = {
    "src/app/templates/chatbot/chat.html": {
        651: "dark:focus:border-primary",
    },
}
DARK_TEXT_TARGETS = {
    "src/app/templates/index.html": {
        108: ["dark:text-blue-400", "dark:hover:text-blue-300"],
        115: ["dark:text-blue-400", "dark:hover:text-blue-300"],
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
    DARK_SUFFIX_CLEARED_TARGETS.items(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_dark_border_and_bg_classes_have_no_important_suffix(relpath, targets):
    path = ROOT / relpath
    for lineno, expected in targets.items():
        classes = _line_classes(path, lineno)
        assert expected in classes, f"{relpath}:{lineno} 에 {expected} 가 없다"
        offenders = [cls for cls in classes if cls.startswith("dark:") and cls.endswith("!")]
        assert not offenders, f"{relpath}:{lineno}: {offenders}"


def test_dark_focus_border_has_no_important_suffix():
    for relpath, targets in DARK_FOCUS_BORDER_TARGETS.items():
        path = ROOT / relpath
        for lineno, expected in targets.items():
            classes = _line_classes(path, lineno)
            assert expected in classes, f"{relpath}:{lineno} 에 {expected} 가 없다"


def test_dark_text_blue_classes_have_no_important_suffix():
    for relpath, targets in DARK_TEXT_TARGETS.items():
        path = ROOT / relpath
        for lineno, expected in targets.items():
            classes = _line_classes(path, lineno)
            for token in expected:
                assert token in classes, f"{relpath}:{lineno} 에 {token} 가 없다"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_dark_bg_and_border_suffix_only_on_h_card(path):
    offenders = []
    for match in CLASS_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
        classes = match.group(1).split()
        if "h-card" in classes:
            continue
        offenders += [
            cls
            for cls in classes
            if cls.startswith("dark:") and cls.endswith("!") and ("bg-" in cls or "border-" in cls)
        ]
    assert not offenders, f"{path.relative_to(ROOT)}: {offenders}"


def test_tailwind_css_has_no_forced_h_card_dark_rules():
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    for selector in FORBIDDEN_CSS_RULES:
        assert selector not in css, f"tailwind.css 에 {selector} 강제 규칙이 다시 들어왔다"
