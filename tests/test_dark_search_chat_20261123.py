"""상단 검색창과 채팅 대화 기록 패널의 다크 모드 대응을 검증합니다."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src/app/templates/base.html"
CHAT = ROOT / "src/app/templates/chatbot/chat.html"
CSS = ROOT / "src/app/static/css/tailwind.css"


def test_header_search_input_has_dark_classes():
    line = next(x for x in BASE.read_text(encoding="utf-8").splitlines() if "pl-9 pr-4 py-1.5" in x)
    classes = line.split('class="', 1)[1].split('"', 1)[0].split()
    for cls in (
        "dark:bg-slate-800",
        "dark:border-slate-700!",
        "dark:text-slate-100",
        "dark:placeholder:text-slate-500",
        "dark:focus:bg-slate-900",
    ):
        assert cls in classes, cls


def test_chat_sessions_panel_overrides_light_sidebar_in_dark():
    text = CHAT.read_text(encoding="utf-8")
    assert ".dark #chat-sessions-panel {" in text
    assert "--h-sidebar-bg: var(--color-slate-900);" in text
    assert ".dark .session-item-li:hover .p-3" in text
    assert ".dark .session-item-li.active .p-3" in text
    assert "dark:bg-transparent" in text
    assert "dark:text-slate-300" in text


def test_built_css_contains_new_dark_utilities():
    css = CSS.read_text(encoding="utf-8")
    for token in (
        "dark\\:placeholder\\:text-slate-500",
        "dark\\:border-slate-700\\!",
        "dark\\:focus\\:bg-slate-900",
        "dark\\:bg-transparent",
        "--color-slate-900:",
    ):
        assert token in css, token
