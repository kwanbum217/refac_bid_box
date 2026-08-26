"""Contrast verification for Tailwind production CSS build.

Reads committed build output only (no Node/npm subprocess). CI must pass without Node.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "src" / "app" / "templates"
BASE_HTML = TEMPLATES_DIR / "base.html"
TAILWIND_CSS = REPO_ROOT / "src" / "app" / "static" / "css" / "tailwind.css"
TAILWIND_CONFIG = REPO_ROOT / "tailwind.config.js"

TEMPLATE_HTML_FILES = sorted(TEMPLATES_DIR.rglob("*.html"))

NON_TAILWIND_EXACT = frozenset(
    {
        "is-active",
        "is-dragging",
        "is-loading",
        "modal",
        "modal-box",
        "modal-backdrop",
        "toggle",
        "toggle-primary",
        "toggle-sm",
        "select",
        "select-bordered",
        "select-sm",
    }
)

NON_TAILWIND_PREFIXES = (
    "fa-",
    "fas",
    "far",
    "fab",
    "h-btn",
    "h-card",
    "h-sidebar",
    "home-",
    "quick-btn",
)

PRIMARY_COLORS = ("0 115 230", "0 91 179")
HARNESS_COLORS = ("2 11 26", "230 233 239")

CLASS_SELECTOR_SUFFIX = frozenset("{:,)>+~. ")

CLASS_ATTR_PATTERN = re.compile(
    r"""class\s*=\s*(?P<q>['"])(?P<value>.*?)(?P=q)""",
    re.DOTALL | re.IGNORECASE,
)


def _clean_class_value(raw_value: str) -> str:
    cleaned = re.sub(r"\{%[^%]*%\}", " ", raw_value, flags=re.DOTALL)
    return re.sub(r"\{\{[^}]*\}\}", " ", cleaned, flags=re.DOTALL)


def _is_tailwind_utility(token: str) -> bool:
    if not token or token in NON_TAILWIND_EXACT:
        return False
    if any(ch in token for ch in ("{%", "{{", "}}", "%}", "$", "{", "}")):
        return False
    if token.startswith("'") or token.endswith("'"):
        return False
    for prefix in NON_TAILWIND_PREFIXES:
        if token == prefix or token.startswith(prefix):
            return False
    if token.startswith("modal") or token.startswith("toggle") or token.startswith("select"):
        return False
    if token.startswith("fa-") or token.startswith("fas"):
        return False
    if token.startswith(
        (
            "aura-",
            "badge",
            "chat-",
            "source-",
            "message-",
            "detail-",
            "result-",
            "agreement-",
            "pagination-",
            "session-",
            "award-",
            "bid-",
            "custom-",
            "chart-",
            "search-",
            "no-scrollbar",
            "results-",
            "data-",
            "stat-",
        )
    ):
        return False
    if token.startswith("h-") and not token.startswith(("h-[", "h-screen", "h-full", "h-auto")):
        return False
    if token.startswith("text-primary-"):
        return False
    if token in {
        "animate-in",
        "fade-in",
        "slide-in-from-bottom-2",
        "slide-in-from-top-2",
        "transform",
        "active",
    }:
        return False
    return not token.startswith("prose")


def _strip_script_blocks(html_content: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)


def _extract_class_tokens_from_templates() -> set[str]:
    tokens: set[str] = set()
    for template_path in TEMPLATE_HTML_FILES:
        content = _strip_script_blocks(template_path.read_text(encoding="utf-8"))
        for match in CLASS_ATTR_PATTERN.finditer(content):
            raw_value = _clean_class_value(match.group("value"))
            for piece in raw_value.split():
                piece = piece.strip()
                if piece:
                    tokens.add(piece)
    return tokens


def _tailwind_minified_selector(class_name: str) -> str:
    parts = ["."]
    if class_name.startswith("!"):
        parts.append("\\!")
        class_name = class_name[1:]
    in_arbitrary = False
    for char in class_name:
        if char == "[":
            in_arbitrary = True
            parts.append("\\[")
            continue
        if char == "]":
            in_arbitrary = False
            parts.append("\\]")
            continue
        if in_arbitrary and char == ",":
            parts.append("\\2c ")
            continue
        if char == ".":
            parts.append("\\.")
            continue
        if char in "/:#%()":
            parts.append("\\" + char)
            continue
        parts.append(char)
    return "".join(parts)


def _class_present_in_css(class_name: str, css_content: str) -> bool:
    selector = _tailwind_minified_selector(class_name)
    start = 0
    while True:
        idx = css_content.find(selector, start)
        if idx == -1:
            return False
        next_idx = idx + len(selector)
        if next_idx >= len(css_content):
            return True
        if css_content[next_idx] in CLASS_SELECTOR_SUFFIX:
            return True
        start = idx + 1


def test_tailwind_css_exists_and_nonempty():
    assert TAILWIND_CSS.is_file(), f"Missing build output: {TAILWIND_CSS}"
    content = TAILWIND_CSS.read_text(encoding="utf-8")
    assert content.strip(), "tailwind.css is empty"


def test_base_html_has_no_tailwind_jit_script():
    content = BASE_HTML.read_text(encoding="utf-8")
    assert "vendor/tailwindcss" not in content
    assert "tailwind.config" not in content


def test_custom_theme_tokens_in_build_css():
    css_content = TAILWIND_CSS.read_text(encoding="utf-8")
    for color in PRIMARY_COLORS:
        assert color in css_content, f"primary color rgb({color}) missing from tailwind.css"
    for color in HARNESS_COLORS:
        assert color in css_content, f"harness color rgb({color}) missing from tailwind.css"


def test_template_tailwind_utilities_exist_in_build_css():
    css_content = TAILWIND_CSS.read_text(encoding="utf-8")
    all_tokens = _extract_class_tokens_from_templates()
    tailwind_tokens = sorted(token for token in all_tokens if _is_tailwind_utility(token))
    assert tailwind_tokens, "No Tailwind-like class tokens found in templates"

    missing = [token for token in tailwind_tokens if not _class_present_in_css(token, css_content)]
    assert not missing, f"Tailwind utilities missing from build CSS: {missing[:20]}"


def test_all_twelve_templates_are_scanned():
    assert len(TEMPLATE_HTML_FILES) == 12


def test_tailwind_config_values_match_inline_spec():
    config_content = TAILWIND_CONFIG.read_text(encoding="utf-8")
    config_hex_colors = (
        "#0073E6",
        "#005BB3",
        "#E6F1FF",
        "#F9FAFB",
        "#020B1A",
        "#E6E9EF",
        "#1F2937",
        "#6B7280",
    )
    for color in config_hex_colors:
        assert color in config_content, f"{color} missing from tailwind.config.js"
    assert "enterprise: '0.75rem'" in config_content
    assert "'h-sm': '0 1px 2px 0 rgba(0, 0, 0, 0.05)'" in config_content
    assert (
        "'h-md': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)'"
        in config_content
    )
    assert "darkMode: 'class'" in config_content
