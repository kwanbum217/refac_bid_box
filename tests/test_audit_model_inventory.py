"""등록 모델 실재 대조 도구 테스트.

이 도구가 막으려는 것은 2026-08-20 의 실제 사고입니다. 무료 풀 1순위가
제공자에서 사라졌는데 라우터는 그대로 들고 있었고, 선택되는 순간에야
`Model not found` 로 드러났습니다.
"""

from __future__ import annotations

import pytest

from scripts import audit_model_inventory as audit_tool


@pytest.fixture
def fake_pool(monkeypatch):
    def _apply(pool: dict) -> None:
        monkeypatch.setattr(audit_tool, "MODEL_POOL", pool)

    return _apply


def test_missing_model_is_detected(fake_pool, monkeypatch):
    """제공자 목록에 없는 배정 대상은 소멸로 판정되고 종료 코드 1 이 납니다."""
    fake_pool(
        {
            "gone": {
                "id": "opencode/vanished-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    missing, lines = audit_tool.audit()

    assert missing == 1
    assert any("소멸" in line for line in lines)
    assert audit_tool.main([]) == 1


def test_present_model_passes(fake_pool, monkeypatch):
    fake_pool(
        {
            "alive": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    missing, _ = audit_tool.audit()

    assert missing == 0
    assert audit_tool.main([]) == 0


def test_unassignable_entry_is_skipped(fake_pool, monkeypatch):
    """suitable_for 가 비어 있으면 소멸해도 배정되지 않으므로 검사하지 않습니다."""
    fake_pool(
        {
            "retired": {
                "id": "opencode/vanished-free",
                "provider": "opencode",
                "suitable_for": [],
            }
        }
    )

    def _fail(cmd):
        raise AssertionError("배정 대상이 아닌 항목은 조회하지 않아야 합니다")

    monkeypatch.setattr(audit_tool, "_run_listing", _fail)

    missing, lines = audit_tool.audit()

    assert missing == 0
    assert any("건너뜀" in line for line in lines)


def test_listing_failure_is_not_reported_as_vanished(fake_pool, monkeypatch):
    """조회 실패와 소멸은 다릅니다. 실패를 소멸로 승격하면 fail-open 의 반대편입니다."""
    fake_pool(
        {
            "alive": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )

    def _boom(cmd):
        raise RuntimeError("opencode models 실패 (종료 코드 1)")

    monkeypatch.setattr(audit_tool, "_run_listing", _boom)

    missing, lines = audit_tool.audit()

    assert missing == 0
    assert any("확인불가" in line for line in lines)
