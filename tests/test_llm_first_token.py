"""
tests/test_llm_first_token.py

첫 토큰 지연 대책 검증.

Phase 7 에서 SSE 첫 토큰 P95 11.06초가 목표 3초에 미달했고, 원인이 로컬 LLM
프리필이라 애플리케이션으로는 손댈 수 없다고 기록돼 있었습니다. 2026-08-05
계측에서 실제 원인은 둘이었습니다.

| 원인 | 실측 |
| --- | --- |
| `gemma4` 사고(thinking) 단계가 끝나야 본문 토큰이 나옴 | 9.73초 -> 0.41초 |
| 모델이 내려가 있으면 로드 비용을 첫 질의가 부담 | 11.78초 |

프리필은 실제 운영 프롬프트(약 1,200자)에서 1초 미만이었습니다. 즉 진단이
틀렸던 것이고, 두 대책 모두 로컬 LLM 을 유지한 채 적용할 수 있습니다.

이 테스트는 그 대책이 요청에 실제로 실리는지 고정합니다. 네트워크는 태우지
않습니다.
"""

import pytest

from src.rag.llm import OllamaBackend, _coerce_keep_alive

SYSTEM = "당신은 공공조달 입찰 데이터 전문 어시스턴트입니다."
MESSAGES = [{"role": "user", "content": "적격심사 기준이 어떻게 되나요"}]


# --------------------------------------------------------------------------- #
# keep_alive
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("-1", -1), ("0", 0), ("300", 300), ("30m", "30m"), ("24h", "24h")],
)
def test_keep_alive_is_coerced_for_ollama(raw, expected):
    """숫자를 문자열로 보내면 Ollama 가 400(missing unit in duration)을 냅니다.

    값이 조용히 무시되는 것이 아니라 요청 자체가 실패해, 모델이 계속 내려가고
    매 질의가 로드 비용을 냅니다.
    """
    assert _coerce_keep_alive(raw) == expected


def test_payload_carries_keep_alive():
    backend = OllamaBackend(keep_alive="-1")
    payload = backend._payload(SYSTEM, MESSAGES, stream=True)
    assert payload["keep_alive"] == -1


# --------------------------------------------------------------------------- #
# thinking
# --------------------------------------------------------------------------- #


def test_thinking_disabled_by_default_sends_think_false():
    """사고를 켜 두면 본문 첫 토큰이 사고가 끝난 뒤에야 나옵니다(9.73초)."""
    backend = OllamaBackend(thinking=False)
    for stream in (True, False):
        assert backend._payload(SYSTEM, MESSAGES, stream=stream)["think"] is False


def test_thinking_enabled_omits_the_flag():
    """켤 때는 모델 기본값에 맡깁니다."""
    backend = OllamaBackend(thinking=True)
    assert "think" not in backend._payload(SYSTEM, MESSAGES, stream=False)


def test_system_prompt_is_first_message():
    backend = OllamaBackend()
    payload = backend._payload(SYSTEM, MESSAGES, stream=False)
    assert payload["messages"][0] == {"role": "system", "content": SYSTEM}
    assert payload["messages"][1:] == MESSAGES


# --------------------------------------------------------------------------- #
# 예열
# --------------------------------------------------------------------------- #


def test_warmup_posts_load_request(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    backend = OllamaBackend(base_url="http://ollama.test", keep_alive="-1")

    assert backend.warmup() is True
    assert captured["url"] == "http://ollama.test/api/chat"
    # 빈 messages 는 생성 없이 로드만 시키는 호출입니다.
    assert captured["json"]["messages"] == []
    assert captured["json"]["keep_alive"] == -1


def test_warmup_failure_does_not_raise(monkeypatch):
    """예열 실패는 첫 질의가 느려질 뿐, 기동을 막으면 안 됩니다."""

    def fake_post(url, json=None, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("httpx.post", fake_post)
    assert OllamaBackend().warmup() is False
