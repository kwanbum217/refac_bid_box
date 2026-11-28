"""compare.html·result_detail.html 의 다크 모드 대응을 고정한다.

(a) 밝은 면·진한 글자·옅은 테두리 클래스에는 같은 요소에 대응 dark: 변형이 있어야 한다.
    (파란 강조 카드처럼 색을 유지하는 요소는 대상 클래스에 넣지 않는다.)
(b) dark: 변형의 ! 접미사는 h-card 요소에만 남는다. tailwind.input.css 의
    `.dark .h-card` 규칙이 같은 속성을 더 높은 명시도로 덮는 유일한 자리다.
(c) 병합 뒤 폐기(2026-11-28, 의도된 라이트 디자인 변경을 막음)
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE_TEMPLATES = [
    "src/app/templates/bids/compare.html",
    "src/app/templates/bids/result_detail.html",
]
CLASS_ATTR_RE = re.compile(r'class="([^"]*)"', re.S)

# 다크 배경 위에서 그대로 두면 밝게 남는 면
LIGHT_SURFACE_CLASSES = frozenset(
    {
        "bg-white",
        "bg-slate-50",
        "bg-slate-50/50",
        "bg-slate-100",
        "bg-emerald-50",
        "bg-amber-50",
    }
)
# 다크 배경 위에서 읽히지 않는 진한 글자(text-slate-400 은 다크에서도 읽히므로 제외)
LIGHT_TEXT_CLASSES = frozenset(
    {
        "text-slate-900",
        "text-slate-800",
        "text-slate-700",
        "text-slate-600",
        "text-slate-500",
        "text-emerald-600",
    }
)
# 다크 배경 위에서 밝게 남는 테두리
LIGHT_BORDER_CLASSES = frozenset(
    {
        "border-slate-100",
        "border-slate-200",
        "border-white",
        "border-emerald-100",
    }
)


def _template_path(relpath: str) -> Path:
    return ROOT / relpath


def _class_tokens(text: str) -> list[list[str]]:
    return [match.group(1).split() for match in CLASS_ATTR_RE.finditer(text)]


def _missing_dark_variants(classes: list[str]) -> list[str]:
    # 파란 강조 카드(bg-primary)는 다크에서도 파란색을 유지하고, 그 안의 흰 버튼도
    # 카드 대비를 위해 흰색을 유지한다. text-primary 를 가진 흰 면은 그 예외다.
    exempt_surface = "bg-white" in classes and "text-primary" in classes
    missing = []
    has_dark_bg = any(token.startswith("dark:bg-") for token in classes)
    has_dark_text = any(token.startswith("dark:text-") for token in classes)
    has_dark_border = any(token.startswith("dark:border-") for token in classes)

    if LIGHT_SURFACE_CLASSES.intersection(classes) and not has_dark_bg and not exempt_surface:
        missing.append("dark:bg-*")
    if LIGHT_TEXT_CLASSES.intersection(classes) and not has_dark_text:
        missing.append("dark:text-*")
    if LIGHT_BORDER_CLASSES.intersection(classes) and not has_dark_border:
        missing.append("dark:border-*")
    return missing


@pytest.mark.parametrize("relpath", RELATIVE_TEMPLATES, ids=lambda value: Path(value).name)
def test_light_classes_have_dark_counterparts(relpath):
    text = _template_path(relpath).read_text(encoding="utf-8")
    offenders = []
    for classes in _class_tokens(text):
        missing = _missing_dark_variants(classes)
        if missing:
            offenders.append((" ".join(classes)[:120], missing))
    assert not offenders, f"{relpath}: dark 변형이 없는 요소 {offenders}"


@pytest.mark.parametrize("relpath", RELATIVE_TEMPLATES, ids=lambda value: Path(value).name)
def test_important_suffix_only_on_h_card(relpath):
    text = _template_path(relpath).read_text(encoding="utf-8")
    offenders = []
    for classes in _class_tokens(text):
        if "h-card" in classes:
            continue
        offenders += [
            token for token in classes if token.startswith("dark:") and token.endswith("!")
        ]
    assert not offenders, f"{relpath}: h-card 밖에 남은 ! 접미사 {sorted(set(offenders))}"
