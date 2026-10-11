"""
tests/test_api_collector_xml_safety.py

src/app/services/api_collector.py 의 외부 XML 파싱 안전성 회귀 테스트.

조달청(G2B) 응답은 제3자 입력이므로 defusedxml 로 파싱해야 합니다. 엔티티 선언이
든 XML(billion laughs)은 확장되지 않고 기존 파싱 실패 경로(ET.ParseError)로
처리되어야 하며, 정상 응답은 그대로 파싱되어야 합니다.
실제 네트워크와 G2B API 호출은 일절 수행하지 않습니다.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import xml.etree.ElementTree as ET

import httpx
import pytest
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

import src.app.services.api_collector as api_collector
from src.app.services.api_collector import _fetch_paged, _map_announcement_item

NORMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <bidNtceNo>20260101001</bidNtceNo>
        <bidNtceNm>정상 공고</bidNtceNm>
      </item>
    </items>
    <totalCount>1</totalCount>
  </body>
</response>
"""

BILLION_LAUGHS_XML = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<response>
  <header><resultCode>00</resultCode></header>
  <body>
    <items><item><bidNtceNo>20260101002</bidNtceNo><bidNtceNm>&lol4;</bidNtceNm></item></items>
    <totalCount>1</totalCount>
  </body>
</response>
"""


def _mock_response(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("src.app.services.api_collector.get_service_key", lambda: "dummy-key")
    mock_resp = httpx.Response(
        status_code=200,
        text=text,
        request=httpx.Request("GET", "https://example.invalid/mock"),
    )
    monkeypatch.setattr(
        "src.app.services.api_collector._make_request_with_retry",
        _async_return(mock_resp),
    )


def _async_return(value: object):
    async def _inner(*args: object, **kwargs: object) -> object:
        return value

    return _inner


async def _fetch() -> list[dict[str, object]]:
    sem = asyncio.Semaphore(1)
    async with httpx.AsyncClient() as client:
        return await _fetch_paged(
            client=client,
            api_url="https://example.invalid/mock",
            step_start="20260101",
            step_end="20260101",
            num_of_rows=10,
            mapper=_map_announcement_item("Thng"),
            error_label="물품 입찰공고",
            sem=sem,
        )


@pytest.mark.asyncio
async def test_fetch_paged_parses_normal_response(monkeypatch: pytest.MonkeyPatch):
    """정상 응답은 defusedxml 로도 그대로 파싱됩니다."""
    _mock_response(monkeypatch, NORMAL_XML)

    rows = await _fetch()

    assert len(rows) == 1
    assert rows[0]["bid_ntce_no"] == "20260101001"


@pytest.mark.asyncio
async def test_fetch_paged_rejects_entity_declaration_bomb(monkeypatch: pytest.MonkeyPatch):
    """엔티티 선언이 든 응답은 확장되지 않고 기존 파싱 실패 경로로 처리됩니다."""
    _mock_response(monkeypatch, BILLION_LAUGHS_XML)

    with pytest.raises(ET.ParseError, match="안전하지 않은 XML 응답"):
        await _fetch()


def test_defusedxml_refuses_entity_declaration_without_expansion():
    """defusedxml 은 엔티티 선언을 만나면 확장하지 않고 즉시 예외를 냅니다."""
    with pytest.raises(DefusedXmlException):
        DefusedET.fromstring(BILLION_LAUGHS_XML)


def test_collector_no_longer_uses_stdlib_fromstring():
    """외부 응답 파싱에 표준 ElementTree.fromstring 이 남아 있지 않아야 합니다."""
    source = inspect.getsource(api_collector)
    assert re.search(r"(?<!Defused)ET\.fromstring\(", source) is None
    assert "DefusedET.fromstring(" in source
