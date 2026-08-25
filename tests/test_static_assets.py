"""Tests for local static asset localization in templates and vendor directories."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "src" / "app"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
BASE_HTML = TEMPLATES_DIR / "base.html"


def test_base_html_has_no_external_asset_references():
    """Verify that base.html does not reference external CDN/remote assets."""
    content = BASE_HTML.read_text(encoding="utf-8")

    # Check for http:// or https:// in link href or script src
    external_refs = re.findall(
        r"""<(?:link|script)[^>]+(?:href|src)=["'](https?://[^"']+)["']""",
        content,
        re.IGNORECASE,
    )
    assert not external_refs, f"External asset references found in base.html: {external_refs}"

    # Also verify no preconnect tags remain
    preconnect_tags = re.findall(
        r"""<link[^>]+rel=["']preconnect["'][^>]*>""",
        content,
        re.IGNORECASE,
    )
    assert not preconnect_tags, f"Preconnect tags found in base.html: {preconnect_tags}"

    # Verify no general https:// references remain in base.html
    https_matches = [line.strip() for line in content.splitlines() if "https://" in line]
    assert not https_matches, f"https:// found in base.html lines: {https_matches}"


def test_base_html_static_assets_exist_on_disk():
    """Dynamically extract all url_for static paths from base.html and ensure files exist."""
    content = BASE_HTML.read_text(encoding="utf-8")

    # Matches url_for('static', path='...') or url_for("static", path="...")
    pattern = r"""url_for\(\s*['"]static['"]\s*,\s*path=['"]([^'"]+)['"]\s*\)"""
    static_paths = re.findall(pattern, content)

    assert len(static_paths) > 0, "Expected at least one url_for static path in base.html"

    missing_files = []
    checked_files = []
    for rel_path in static_paths:
        target = STATIC_DIR / rel_path
        checked_files.append(rel_path)
        if not target.is_file():
            missing_files.append(str(rel_path))

    assert not missing_files, f"Missing static files referenced in base.html: {missing_files}"
    # Ensure vendor assets are among the parsed static paths
    assert any("vendor/bootstrap" in p for p in checked_files)
    assert any("vendor/daisyui" in p for p in checked_files)
    assert any("vendor/tailwindcss" in p for p in checked_files)
    assert any("vendor/jquery" in p for p in checked_files)
    assert any("vendor/fontawesome" in p for p in checked_files)
    assert any("vendor/fonts" in p for p in checked_files)


def test_fontawesome_webfonts_exist_and_resolve():
    """Verify all font files referenced by fontawesome CSS exist on disk."""
    fa_css_path = STATIC_DIR / "vendor" / "fontawesome" / "6.4.0" / "css" / "all.min.css"
    assert fa_css_path.is_file(), f"FontAwesome CSS not found at {fa_css_path}"

    css_content = fa_css_path.read_text(encoding="utf-8")
    # Extract url(...) paths
    font_urls = re.findall(r"""url\((?:['"])?([^)'"?#]+)(?:[?#][^)'"]*)?(?:['"])?\)""", css_content)
    assert font_urls, "No font urls found in FontAwesome CSS"

    missing_fonts = []
    for rel_url in set(font_urls):
        font_path = (fa_css_path.parent / rel_url).resolve()
        if not font_path.is_file():
            missing_fonts.append(f"{rel_url} -> {font_path}")

    assert not missing_fonts, f"Missing FontAwesome webfont files: {missing_fonts}"


def test_fonts_css_webfonts_exist_and_resolve():
    """Verify all font files referenced by fonts.css (Inter, Noto Sans KR) exist on disk."""
    fonts_css_path = STATIC_DIR / "vendor" / "fonts" / "fonts.css"
    assert fonts_css_path.is_file(), f"fonts.css not found at {fonts_css_path}"

    css_content = fonts_css_path.read_text(encoding="utf-8")
    font_urls = re.findall(r"""url\((?:['"])?([^)'"?#]+)(?:[?#][^)'"]*)?(?:['"])?\)""", css_content)
    assert font_urls, "No font urls found in fonts.css"

    missing_fonts = []
    for rel_url in set(font_urls):
        font_path = (fonts_css_path.parent / rel_url).resolve()
        if not font_path.is_file():
            missing_fonts.append(f"{rel_url} -> {font_path}")

    assert not missing_fonts, f"Missing font files in fonts.css: {missing_fonts}"
