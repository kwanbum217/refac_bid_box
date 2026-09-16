"""
tests/test_api_collector_xml_sanitize.py

G2B XML 응답 내 잘못된 문자 참조(&#x0; 등) 및 XML 1.0 금지 제어문자 살균을 검증합니다.

공공데이터 OpenAPI 응답에 간혹 포함되는 &#x0;, &#8; 등의 잘못된 숫자 문자 참조(NCR)로
인해 ElementTree.fromstring 파싱이 실패(reference to invalid character number)하고
수집 구간 전체가 실패로 처리되는 문제를 방지합니다.
외부 네트워크 및 실제 G2B API 호출은 일절 수행하지 않습니다.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET  # nosec B405
from unittest.mock import AsyncMock

import httpx
import pytest

from src.app.services.api_collector import (
    _fetch_paged,
    _map_announcement_item,
    is_valid_xml_char,
    sanitize_xml_text,
)

NORMAL_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <bidNtceNm>2026년 청사 유지보수 &amp; 환경개선 용역 &lt;긴급&gt;</bidNtceNm>
        <bidNtceNo>20260916001</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <ntceInsttNm>조달청</ntceInsttNm>
        <dminsttNm>서울특별시</dminsttNm>
        <presmptPrce>500,000,000</presmptPrce>
        <bdgtAmt>550,000,000</bdgtAmt>
        <bidNtceDt>2026/09/16 09:00:00</bidNtceDt>
        <bidClseDt>2026/09/23 18:00:00</bidClseDt>
        <opengDt>2026/09/24 10:00:00</opengDt>
        <ntceKindNm>일반공고</ntceKindNm>
        <bidMethdNm>전자입찰</bidMethdNm>
        <cntrctCnclsMthdNm>일반경쟁</cntrctCnclsMthdNm>
      </item>
    </items>
    <numOfRows>10</numOfRows>
    <pageNo>1</pageNo>
    <totalCount>1</totalCount>
  </body>
</response>
"""

INVALID_CHAR_REF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <bidNtceNm>오염된 공고명&#x0; 물품구매&#8; 테스트&#x1F; 및 &#0;</bidNtceNm>
        <bidNtceNo>20260916002</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <ntceInsttNm>조달청&#x0;</ntceInsttNm>
        <dminsttNm>경기도&#12;</dminsttNm>
        <presmptPrce>100,000,000</presmptPrce>
        <bdgtAmt>110,000,000</bdgtAmt>
        <bidNtceDt>2026/09/16 10:00:00</bidNtceDt>
        <bidClseDt>2026/09/25 18:00:00</bidClseDt>
        <opengDt>2026/09/26 10:00:00</opengDt>
        <ntceKindNm>일반공고</ntceKindNm>
        <bidMethdNm>전자입찰</bidMethdNm>
        <cntrctCnclsMthdNm>제한경쟁</cntrctCnclsMthdNm>
      </item>
    </items>
    <numOfRows>10</numOfRows>
    <pageNo>1</pageNo>
    <totalCount>1</totalCount>
  </body>
</response>
"""


def test_normal_xml_parsed_identically_after_sanitization():
    """(1) 정상 XML은 살균 후에도 항목과 구조가 변경 없이 그대로 파싱됩니다."""
    sanitized = sanitize_xml_text(NORMAL_SAMPLE_XML)
    root_before = ET.fromstring(NORMAL_SAMPLE_XML)  # noqa: S314
    root_after = ET.fromstring(sanitized)  # noqa: S314

    assert root_after.findtext(".//resultCode") == "00"
    assert root_after.findtext(".//bidNtceNo") == "20260916001"
    assert (
        root_after.findtext(".//bidNtceNm")
        == root_before.findtext(".//bidNtceNm")
        == "2026년 청사 유지보수 & 환경개선 용역 <긴급>"
    )


def test_invalid_character_reference_fails_raw_but_succeeds_after_sanitization():
    """(2) 금지 문자 참조(&#x0;, &#8;, &#0; 등)가 있는 XML은 원본에서 예외가 발생하나 살균 후 정상 파싱됩니다."""
    # 원본은 XML 1.0 규격 위반 문자 참조로 인해 ParseError 발생
    with pytest.raises(ET.ParseError) as exc_info:
        ET.fromstring(INVALID_CHAR_REF_XML)  # noqa: S314
    assert "reference to invalid character number" in str(exc_info.value)

    # 살균 처리 후에는 예외 없이 파싱 성공
    sanitized = sanitize_xml_text(INVALID_CHAR_REF_XML)
    root = ET.fromstring(sanitized)  # noqa: S314

    assert root.findtext(".//resultCode") == "00"
    assert root.findtext(".//bidNtceNo") == "20260916002"
    # 금지 문자 참조가 제거되고 나머지 텍스트가 온전히 보존됨
    assert root.findtext(".//bidNtceNm") == "오염된 공고명 물품구매 테스트 및 "
    assert root.findtext(".//ntceInsttNm") == "조달청"
    assert root.findtext(".//dminsttNm") == "경기도"


def test_sanitization_preserves_hangul_and_allowed_entities():
    """(3) 살균 함수가 허용 한글, 허용 XML 엔티티, 유효한 숫자 문자 참조 및 공백 문자를 보존합니다."""
    sample = (
        "<data>"
        "한글 테스트 및 English 12345 "
        "&lt;태그&gt; &amp; &quot;따옴표&quot; &apos;작은따옴표&apos; "
        "&#38; &#44; &#xac00; &#x20; \t \n \r"
        "</data>"
    )
    sanitized = sanitize_xml_text(sample)
    # 허용 문자 및 엔티티는 조금도 지워지지 않아야 함
    assert sanitized == sample

    root = ET.fromstring(sanitized)  # noqa: S314
    text = root.text or ""
    assert "한글 테스트" in text
    assert "<태그>" in text
    assert "&" in text
    assert '"따옴표"' in text
    assert "'작은따옴표'" in text
    assert "가" in text  # &#xac00;


def test_sanitization_removes_raw_invalid_control_characters():
    """XML 1.0 금지 원시 제어문자(\\x00, \\x08, \\x1b, \\x1f 등)를 제거합니다."""
    raw_dirty = "<item>테스트\x00\x08제어문자\x1b제거\x1f완료\t\n\r</item>"
    sanitized = sanitize_xml_text(raw_dirty)
    assert sanitized == "<item>테스트제어문자제거완료\t\n\r</item>"
    root = ET.fromstring(sanitized)  # noqa: S314
    # XML 1.0 사양(End-of-line Handling)에 따라 파서는 \r 을 \n 으로 정규화합니다.
    assert root.text == "테스트제어문자제거완료\t\n\n"


@pytest.mark.parametrize(
    ("code_point", "expected"),
    [
        (0x0, False),
        (0x8, False),
        (0x9, True),  # tab
        (0xA, True),  # newline
        (0xB, False),
        (0xC, False),
        (0xD, True),  # cr
        (0xE, False),
        (0x1F, False),
        (0x20, True),  # space
        (0xD7FF, True),
        (0xD800, False),  # surrogate
        (0xDFFF, False),  # surrogate
        (0xE000, True),
        (0xFFFD, True),
        (0xFFFE, False),  # noncharacter
        (0xFFFF, False),  # noncharacter
        (0x10000, True),
        (0x10FFFF, True),
        (0x110000, False),
    ],
)
def test_is_valid_xml_char(code_point: int, expected: bool):
    """XML 1.0 사양의 코드포인트 유효성 판별 로직을 단일 단위로 검증합니다."""
    assert is_valid_xml_char(code_point) is expected


@pytest.mark.asyncio
async def test_fetch_paged_recovers_page_with_invalid_char_references(monkeypatch):
    """_fetch_paged 가 금지 문자 참조가 섞인 응답을 받아도 버리지 않고 성공적으로 파싱합니다."""
    monkeypatch.setattr("src.app.services.api_collector.get_service_key", lambda: "dummy-key")

    mock_resp = httpx.Response(
        status_code=200,
        text=INVALID_CHAR_REF_XML,
        request=httpx.Request("GET", "https://example.invalid/mock"),
    )

    fake_request = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr("src.app.services.api_collector._make_request_with_retry", fake_request)

    sem = asyncio.Semaphore(1)
    mapper = _map_announcement_item("Thng")

    async with httpx.AsyncClient() as client:
        rows = await _fetch_paged(
            client=client,
            api_url="https://example.invalid/mock",
            step_start="20260916",
            step_end="20260916",
            num_of_rows=10,
            mapper=mapper,
            error_label="물품 입찰공고",
            sem=sem,
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["bid_ntce_no"] == "20260916002"
    assert row["bid_ntce_nm"] == "오염된 공고명 물품구매 테스트 및"
    assert row["ntce_instt_nm"] == "조달청"
    assert row["dminstt_nm"] == "경기도"
    assert row["category"] == "Thng"
