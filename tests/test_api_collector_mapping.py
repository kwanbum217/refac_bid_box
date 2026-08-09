"""
tests/test_api_collector_mapping.py

G2B 응답 항목을 DB 컬럼으로 옮기는 매핑을 검증합니다.

이 파일이 막는 사고는 조용한 결손입니다. 매핑이 존재하지 않는 태그명을 읽으면
_get_text 가 None 을 돌려주고, 수집은 성공한 것처럼 끝나며, 컬럼만 통째로
비어 있게 됩니다. 실제로 cntrct_mthd_nm 이 300만 행 내내 비어 있었고
원인은 응답에 없는 cntrctMthdNm 을 읽고 있었던 것입니다.

표본은 2026-08-03 운영 DB 의 raw_data 에서 확인한 실제 필드명입니다.
"""

import xml.etree.ElementTree as ET  # nosec B405

import pytest

from src.app.services.api_collector import _map_announcement_item, _map_result_item, get_service_key

ANNOUNCEMENT_XML = """
<item>
  <bidNtceNm>도로 보수 공사</bidNtceNm>
  <bidNtceNo>20260801234</bidNtceNo>
  <bidNtceOrd>000</bidNtceOrd>
  <ntceInsttNm>조달청</ntceInsttNm>
  <dminsttNm>서울특별시</dminsttNm>
  <presmptPrce>1,200,000,000</presmptPrce>
  <bdgtAmt>1,300,000,000</bdgtAmt>
  <bidNtceDt>2026/08/01 10:00:00</bidNtceDt>
  <bidClseDt>2026/08/10 17:00:00</bidClseDt>
  <opengDt>2026/08/11 11:00:00</opengDt>
  <ntceKindNm>일반공고</ntceKindNm>
  <bidMethdNm>전자입찰</bidMethdNm>
  <cntrctCnclsMthdNm>수의계약</cntrctCnclsMthdNm>
</item>
"""

RESULT_XML = """
<item>
  <bidNtceNm>도로 보수 공사</bidNtceNm>
  <bidNtceNo>20260801234</bidNtceNo>
  <bidNtceOrd>000</bidNtceOrd>
  <bidwinnrNm>한국건설</bidwinnrNm>
  <sucsfbidAmt>1,080,000,000</sucsfbidAmt>
  <sucsfbidRate>90.5</sucsfbidRate>
  <rlOpengDt>2026/08/11 11:00:00</rlOpengDt>
  <dminsttNm>서울특별시</dminsttNm>
</item>
"""


def _raw(xml: str) -> dict[str, str]:
    return {child.tag: (child.text or "") for child in ET.fromstring(xml)}  # noqa: S314


def test_service_key_accepts_canonical_and_legacy_environment_names(monkeypatch):
    monkeypatch.setenv("G2B_SERVICE_KEY", "canonical")
    monkeypatch.setenv("serviceKey", "legacy")
    assert get_service_key() == "canonical"

    monkeypatch.delenv("G2B_SERVICE_KEY")
    assert get_service_key() == "legacy"


@pytest.fixture
def announcement() -> dict:
    item = ET.fromstring(ANNOUNCEMENT_XML)  # noqa: S314
    return _map_announcement_item("Cnstwk")(item, _raw(ANNOUNCEMENT_XML))


@pytest.fixture
def result() -> dict:
    item = ET.fromstring(RESULT_XML)  # noqa: S314
    return _map_result_item("Cnstwk")(item, _raw(RESULT_XML))


def test_contract_method_reads_cntrct_cncls_mthd_nm(announcement):
    """계약체결방법 필드명은 cntrctCnclsMthdNm 입니다. cntrctMthdNm 은 응답에 없습니다."""
    assert announcement["cntrct_mthd_nm"] == "수의계약"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("bid_ntce_nm", "도로 보수 공사"),
        ("bid_ntce_no", "20260801234"),
        ("bid_ntce_ord", "000"),
        ("ntce_instt_nm", "조달청"),
        ("dminstt_nm", "서울특별시"),
        ("presmpt_prce", 1_200_000_000),
        # 기초금액은 태그가 아니라 raw_data 의 예산금액 키에서 뽑습니다.
        ("base_amount", 1_300_000_000),
        ("ntce_kind_nm", "일반공고"),
        ("bid_methd_nm", "전자입찰"),
        ("category", "Cnstwk"),
    ],
)
def test_announcement_columns_are_populated(announcement, column, expected):
    assert announcement[column] == expected


def test_announcement_datetimes_are_parsed(announcement):
    assert announcement["bid_ntce_dt"].isoformat() == "2026-08-01T10:00:00"
    assert announcement["bid_clse_dt"].isoformat() == "2026-08-10T17:00:00"
    assert announcement["openg_dt"].isoformat() == "2026-08-11T11:00:00"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("bid_ntce_nm", "도로 보수 공사"),
        ("bid_ntce_no", "20260801234"),
        ("bid_ntce_ord", "000"),
        ("bidwinnr_nm", "한국건설"),
        ("sucsf_bid_amt", 1_080_000_000),
        ("sucsf_bid_rate", 90.5),
        ("dminstt_nm", "서울특별시"),
        ("category", "Cnstwk"),
    ],
)
def test_result_columns_are_populated(result, column, expected):
    assert result[column] == expected


def test_no_mapped_column_is_silently_empty(announcement, result):
    """매핑 대상 전 컬럼이 값을 받아야 합니다. None 이 나오면 태그명이 틀린 것입니다."""
    for row in (announcement, result):
        empty = sorted(k for k, v in row.items() if k != "raw_data" and v is None)
        assert empty == [], f"값을 받지 못한 컬럼: {empty}"
