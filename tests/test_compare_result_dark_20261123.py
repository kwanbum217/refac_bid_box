"""compare.html·result_detail.html 의 다크 모드 대응을 고정한다.

(a) 밝은 면·진한 글자·옅은 테두리 클래스에는 같은 요소에 대응 dark: 변형이 있어야 한다.
    (파란 강조 카드처럼 색을 유지하는 요소는 대상 클래스에 넣지 않는다.)
(b) dark: 변형의 ! 접미사는 h-card 요소에만 남는다. tailwind.input.css 의
    `.dark .h-card` 규칙이 같은 속성을 더 높은 명시도로 덮는 유일한 자리다.
(c) dark: 변형과 ! 를 지우면 main 브랜치 템플릿의 클래스와 같아야 한다(라이트 모드 불변).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE_TEMPLATES = [
    "src/app/templates/bids/compare.html",
    "src/app/templates/bids/result_detail.html",
]
CLASS_ATTR_RE = re.compile(r'class="([^"]*)"', re.S)
GIT_BIN = shutil.which("git") or "git"

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


def _strip_dark_variants(classes: list[str]) -> list[str]:
    return [
        token[:-1] if token.endswith("!") else token
        for token in classes
        if not token.startswith("dark:")
    ]


# 다크 대응 직전의 main 커밋이다. 움직이는 main 과 비교하면 병합 뒤 main 자체가 다크
# 변형을 포함해 항상 실패하므로, 라이트 모드 기준은 이 고정 커밋으로 둔다.
LIGHT_BASELINE_REF = "975bb823"


def _main_template_text(relpath: str) -> str:
    result = subprocess.run(  # noqa: S603
        [GIT_BIN, "show", f"{LIGHT_BASELINE_REF}:{relpath}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"기준 커밋 {LIGHT_BASELINE_REF} 에서 {relpath} 를 읽을 수 없습니다: {result.stderr.strip()}"
        )
    return result.stdout


@pytest.mark.parametrize("relpath", RELATIVE_TEMPLATES, ids=lambda value: Path(value).name)
def test_light_mode_matches_main(relpath):
    current = _template_path(relpath).read_text(encoding="utf-8")
    main = _main_template_text(relpath)

    current_classes = _class_tokens(current)
    main_classes = _class_tokens(main)
    assert len(current_classes) == len(main_classes), (
        f"{relpath}: class 속성 개수가 main 과 다릅니다 "
        f"({len(current_classes)} != {len(main_classes)})"
    )

    for index, (current_tokens, main_tokens) in enumerate(
        zip(current_classes, main_classes, strict=True)
    ):
        stripped = _strip_dark_variants(current_tokens)
        assert stripped == main_tokens, (
            f"{relpath}: {index + 1}번째 class 속성이 라이트 모드에서 main 과 다릅니다. "
            f"{stripped} != {main_tokens}"
        )
