"""dark:* 클래스의 후행 ! 정리 결과를 고정한다.

Bootstrap(510ac531 이전)의 !important 유틸리티를 이기려고 붙였던 접미사는 제거했다.
다만 tailwind.input.css 의 `.dark .h-card` 는 background-color·border-color 를,
`.dark .h-card:hover` 는 border-color 를 Tailwind 유틸리티보다 높은 명시도(0,2,0)로
덮으므로 h-card 요소의 dark 색상 유틸리티에만 ! 를 남긴다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "src/app/templates"
TAILWIND_CSS = ROOT / "src/app/static/css/tailwind.css"
TAILWIND_INPUT = ROOT / "src/app/static/css/tailwind.input.css"

CLASS_ATTR_RE = re.compile(r'class="([^"]*)"', re.S)
DARK_TOKEN_RE = re.compile(r"dark:[^\s\"!]+")
H_CARD_RULE_SELECTORS = (".dark .h-card", ".dark .h-card:hover")
# ! 를 남긴 곳과 근거. 모든 근거는 tailwind.input.css 의 `.dark .h-card` 계열 규칙이다.
RETAINED_IMPORTANT = {
    "src/app/templates/bids/compare.html": {
        36: ["dark:border-slate-800!"],
        45: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        55: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        65: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        75: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        98: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        118: ["dark:bg-slate-900!", "dark:border-slate-800!"],
        134: ["dark:bg-slate-900!", "dark:border-slate-800!"],
    },
    "src/app/templates/bids/result_detail.html": {
        41: ["dark:bg-slate-900!"],
        111: ["dark:bg-slate-900!"],
    },
}
PROPERTY_BY_PREFIX = {
    "dark:bg-": "background-color",
    "dark:border-": "border-color",
}
CLASS_SELECTOR_BOUNDARY = frozenset("{:,")


def _retained_tokens() -> set[str]:
    return {
        token
        for targets in RETAINED_IMPORTANT.values()
        for tokens in targets.values()
        for token in tokens
    }


def _line_classes(relpath: str, lineno: int) -> list[str]:
    path = ROOT / relpath
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lineno <= len(lines), f"{relpath}:{lineno} 행이 없다"
    match = re.search(r'class="([^"]*)"', lines[lineno - 1])
    assert match, f"{relpath}:{lineno} 에 class 속성이 없다"
    return match.group(1).split()


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


def _css_block(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    end = css.index("}", start)
    return css[start : end + 1]


def test_retained_important_suffixes_are_present():
    for relpath, targets in RETAINED_IMPORTANT.items():
        for lineno, tokens in targets.items():
            classes = _line_classes(relpath, lineno)
            for token in tokens:
                assert token in classes, f"{relpath}:{lineno} 에 {token} 가 없다"
                assert "h-card" in classes, f"{relpath}:{lineno} 는 h-card 요소가 아니다"


def test_only_retained_dark_tokens_end_with_important():
    found = set()
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        for match in CLASS_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
            found.update(
                token
                for token in match.group(1).split()
                if token.startswith("dark:") and token.endswith("!")
            )
    expected = _retained_tokens()
    assert found == expected, (
        f"예상 밖 ! 접미사: {sorted(found - expected)}, 사라진 ! 접미사: {sorted(expected - found)}"
    )


def test_retained_evidence_rules_declare_the_same_properties():
    css = TAILWIND_INPUT.read_text(encoding="utf-8")
    for selector in H_CARD_RULE_SELECTORS:
        assert selector + " {" in css, f"tailwind.input.css 에 {selector} 규칙이 없다"
    base_rule = _css_block(css, ".dark .h-card")
    hover_rule = _css_block(css, ".dark .h-card:hover")
    for property_name in set(PROPERTY_BY_PREFIX.values()):
        assert property_name in base_rule, f".dark .h-card 가 {property_name} 를 덮지 않는다"
    assert "border-color" in hover_rule
    for token in _retained_tokens():
        prefix = next((prefix for prefix in PROPERTY_BY_PREFIX if token.startswith(prefix)), None)
        assert prefix, f"{token} 의 근거 속성을 정할 수 없다"


def test_removed_dark_variants_still_exist_in_build_css():
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    retained = _retained_tokens()
    missing = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        for match in CLASS_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
            for token in match.group(1).split():
                if not token.startswith("dark:") or token.endswith("!") or token in retained:
                    continue
                if not _selector_present(_css_selector(token), css):
                    missing.append((path.name, token))
    assert not missing, f"tailwind.css 에 없는 dark 변형: {missing[:10]}"
