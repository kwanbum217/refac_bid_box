"""
tests/test_openg_results_collector.py

T1·T2 검증: `bid_openg_results` 신규 테이블 마이그레이션과 개찰결과 수집 매퍼.

외부 조달청 API 는 호출하지 않습니다. 모든 수집 시험은 고정 XML 응답을 돌려주는
가짜 httpx 클라이언트로만 돌리고, 서비스 키도 쓰지 않습니다.

설계 정본: docs/analysis/fail_bid_collection_design_20261031.md 2·3·8장.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET  # nosec B405 - 시험용 고정 XML 만 파싱합니다
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import src.app.models  # noqa: F401  모든 테이블을 Base.metadata 에 등록
from src.app.core.config import settings
from src.app.core.db import Base
from src.app.models.openg_results import (
    OPENG_STATUS_CLOSED,
    OPENG_STATUS_FAILED,
    OPENG_STATUS_OTHER,
    classify_openg_status,
)
from src.app.services import api_collector
from src.app.services.api_collector import (
    OPENG_RESULT_URLS,
    RangeCollectionError,
    _fetch_paged,
    _map_openg_result_item,
    fetch_openg_results,
    stream_openg_results,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREVIOUS_HEAD = "b7c8d9e0f1a2"
NEW_TABLE = "bid_openg_results"
EXPECTED_COLUMNS = (
    "id",
    "bid_ntce_no",
    "bid_ntce_ord",
    "rbid_no",
    "bid_clsfc_no",
    "category",
    "progrs_div_cd_nm",
    "prtcpt_cnum",
    "bid_ntce_nm",
    "dminstt_nm",
    "openg_dt",
    "raw_data",
    "first_seen_at",
    "last_seen_at",
    "collected_at",
)
EXPECTED_INDEXES = {
    "ix_openg_cat_dt": ("category", "openg_dt"),
    "ix_openg_status_dt": ("progrs_div_cd_nm", "openg_dt"),
    "ix_openg_inst_cat_dt": ("dminstt_nm", "category", "openg_dt"),
    "ix_openg_notice": ("bid_ntce_no", "category"),
}

OPENG_ITEM_XML = """
<item>
  <bidNtceNo>20260818123</bidNtceNo>
  <bidNtceOrd>00</bidNtceOrd>
  <rbidNo>000</rbidNo>
  <bidClsfcNo>0</bidClsfcNo>
  <bidNtceNm>도로 보수 공사</bidNtceNm>
  <dminsttNm>서울특별시</dminsttNm>
  <dminsttCd>6110000</dminsttCd>
  <ntceInsttNm>조달청</ntceInsttNm>
  <ntceInsttCd>1230000</ntceInsttCd>
  <opengDt>2026/08/18 11:00:00</opengDt>
  <inptDt>2026/08/18 11:30:00</inptDt>
  <progrsDivCdNm>유찰</progrsDivCdNm>
  <prtcptCnum>0</prtcptCnum>
  <opengRsltNtcCntnts>유찰</opengRsltNtcCntnts>
  <rsrvtnPrceFileExistnceYn>N</rsrvtnPrceFileExistnceYn>
  <opengCorpInfo>&lt;corp&gt;대표자 홍길동&lt;/corp&gt;</opengCorpInfo>
</item>
"""


def _item_and_raw(xml: str) -> tuple[ET.Element, dict[str, str]]:
    item = ET.fromstring(xml)  # noqa: S314
    raw = {child.tag: (child.text or "").strip() for child in item}
    return item, raw


def _mapped_row(xml: str = OPENG_ITEM_XML, category: str = "Cnstwk") -> dict:
    item, raw = _item_and_raw(xml)
    return _map_openg_result_item(category)(item, raw)


def _response_xml(items: str, result_code: str = "00", total_count: int = 0) -> str:
    return (
        "<response>"
        f"<header><resultCode>{result_code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><totalCount>{total_count}</totalCount><items>{items}</items></body>"
        "</response>"
    )


def _xml_response(xml: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=xml,
        request=httpx.Request("GET", "https://example.invalid/api"),
    )


class _FakeAsyncClient:
    """미리 준비한 응답을 순서대로 돌려주고 요청 파라미터를 기록합니다."""

    def __init__(self, responses: list[httpx.Response], calls: list[dict]) -> None:
        self._responses = responses
        self._calls = calls

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url: str, params=None, timeout=None) -> httpx.Response:
        self._calls.append({"url": url, "params": dict(params or {})})
        if not self._responses:
            raise AssertionError("준비한 응답을 모두 소진했습니다")
        return self._responses.pop(0)


def _install_fake_client(monkeypatch, responses: list[httpx.Response]) -> list[dict]:
    calls: list[dict] = []

    def factory(*args, **kwargs) -> _FakeAsyncClient:
        return _FakeAsyncClient(responses, calls)

    monkeypatch.setattr(api_collector.httpx, "AsyncClient", factory)
    return calls


def _table_columns(engine, table: str) -> list[tuple[str, str, bool]]:
    return [
        (column["name"], str(column["type"]), bool(column["nullable"]))
        for column in inspect(engine).get_columns(table)
    ]


# --------------------------------------------------------------------------- #
# T1: 마이그레이션
# --------------------------------------------------------------------------- #


def test_migration_revision_follows_current_head():
    from migrations.versions import c1d2e3f4a5b6_add_bid_openg_results as migration

    assert migration.revision == "c1d2e3f4a5b6"
    assert migration.down_revision == PREVIOUS_HEAD


def test_migration_upgrade_and_downgrade_on_sqlite(tmp_path, monkeypatch):
    """신규 테이블만 만들고, 기존 테이블 스키마는 그대로 두어야 합니다(G1)."""
    db_path = tmp_path / "openg_migration.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)

    engine = create_engine(url)
    legacy_tables = [table for name, table in Base.metadata.tables.items() if name != NEW_TABLE]
    Base.metadata.create_all(engine, tables=legacy_tables)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": PREVIOUS_HEAD},
        )

    before_tables = set(inspect(engine).get_table_names())
    before_columns = _table_columns(engine, "bid_announcements") + _table_columns(
        engine, "bid_results"
    )

    # migrations/env.py 의 fileConfig 가 전역 로깅을 재설정해 이후 테스트의 caplog 를
    # 비웁니다. 로깅 재설정만 no-op 으로 막고 마이그레이션은 그대로 실행합니다.
    monkeypatch.setattr(logging.config, "fileConfig", lambda *args, **kwargs: None)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")

        inspector = inspect(engine)
        assert set(inspector.get_table_names()) - before_tables == {NEW_TABLE}
        assert tuple(c["name"] for c in inspector.get_columns(NEW_TABLE)) == EXPECTED_COLUMNS
        assert (
            _table_columns(engine, "bid_announcements") + _table_columns(engine, "bid_results")
            == before_columns
        )

        unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(NEW_TABLE)
        }
        assert unique_constraints == {
            "uq_bid_openg_results": ("bid_ntce_no", "bid_ntce_ord", "rbid_no", "category")
        }
        assert {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes(NEW_TABLE)
        } == EXPECTED_INDEXES

        command.downgrade(config, PREVIOUS_HEAD)
        assert set(inspect(engine).get_table_names()) == before_tables
    finally:
        engine.dispose()


def test_model_columns_match_the_migrated_table():
    """모델과 마이그레이션의 컬럼 집합이 어긋나면 autogenerate 가 DDL 을 만듭니다."""
    assert tuple(Base.metadata.tables[NEW_TABLE].columns.keys()) == EXPECTED_COLUMNS


# --------------------------------------------------------------------------- #
# T2: 매퍼
# --------------------------------------------------------------------------- #


def test_mapper_maps_response_fields():
    row = _mapped_row()

    assert row["bid_ntce_no"] == "20260818123"
    assert row["bid_ntce_ord"] == "000"
    assert row["rbid_no"] == "000"
    assert row["bid_clsfc_no"] == "0"
    assert row["category"] == "Cnstwk"
    assert row["progrs_div_cd_nm"] == "유찰"
    assert row["prtcpt_cnum"] == 0
    assert row["bid_ntce_nm"] == "도로 보수 공사"
    assert row["dminstt_nm"] == "서울특별시"
    assert row["openg_dt"] == datetime(2026, 8, 18, 11, 0, 0)


def test_mapper_output_is_exactly_the_model_columns():
    """매퍼는 모델 컬럼만 내야 합니다. T3 의 upsert 가 그대로 펼쳐 씁니다."""
    row = _mapped_row()
    defaulted = {"id", "first_seen_at", "last_seen_at", "collected_at"}
    assert set(row) == set(Base.metadata.tables[NEW_TABLE].columns.keys()) - defaulted


def test_openg_corp_info_is_not_stored():
    """개찰 업체 정보에는 대표자명 등 개인정보가 있어 저장하지 않습니다."""
    row = _mapped_row()

    assert "opengCorpInfo" not in row["raw_data"]
    assert "대표자 홍길동" not in str(row["raw_data"])
    assert row["raw_data"]["bidNtceNo"] == "20260818123"
    assert row["raw_data"]["progrsDivCdNm"] == "유찰"


@pytest.mark.parametrize(
    ("raw_ord", "expected"),
    [
        ("000", "000"),
        ("00", "000"),
        ("0", "000"),
        ("1", "001"),
        ("0001", "001"),
        (None, "000"),
    ],
)
def test_bid_ntce_ord_is_normalized_to_three_digits(raw_ord, expected):
    ord_tag = "" if raw_ord is None else f"<bidNtceOrd>{raw_ord}</bidNtceOrd>"
    row = _mapped_row(f"<item><bidNtceNo>20260818123</bidNtceNo>{ord_tag}</item>")
    assert row["bid_ntce_ord"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("유찰", OPENG_STATUS_FAILED),
        ("개찰완료", OPENG_STATUS_CLOSED),
        ("개찰완료(예정가격 초과)", OPENG_STATUS_CLOSED),
        ("재입찰", OPENG_STATUS_OTHER),
        ("", OPENG_STATUS_OTHER),
        (None, OPENG_STATUS_OTHER),
    ],
)
def test_status_is_classified_into_three_groups(value, expected):
    """유찰만 유찰로 세고 재입찰은 별도 상태로 둡니다(설계 2.3, 7절 결정 5)."""
    assert classify_openg_status(value) == expected


# --------------------------------------------------------------------------- #
# T2: 수집 함수
# --------------------------------------------------------------------------- #


def test_supported_categories_exclude_foreign_currency():
    assert set(OPENG_RESULT_URLS) == {"Thng", "Cnstwk", "Servc"}
    with pytest.raises(ValueError, match="지원하지 않는 분류"):
        api_collector._resolve_openg_result_url("Frgcpt")


async def test_stream_openg_results_uses_openg_day_axis(monkeypatch):
    calls = _install_fake_client(
        monkeypatch, [_xml_response(_response_xml(OPENG_ITEM_XML, total_count=1))]
    )
    rows: list[dict] = []

    total = await stream_openg_results("20260818", "20260818", rows.extend, category="Servc")

    assert total == 1
    assert [row["bid_ntce_no"] for row in rows] == ["20260818123"]
    assert rows[0]["progrs_div_cd_nm"] == "유찰"
    assert calls[0]["url"] == OPENG_RESULT_URLS["Servc"]
    assert calls[0]["params"] == {
        "serviceKey": "",
        "pageNo": "1",
        "numOfRows": "999",
        "inqryDiv": "3",
        "inqryBgnDt": "202608180000",
        "inqryEndDt": "202608182359",
        "type": "xml",
    }


async def test_fetch_openg_results_returns_rows(monkeypatch):
    calls = _install_fake_client(
        monkeypatch, [_xml_response(_response_xml(OPENG_ITEM_XML, total_count=1))]
    )

    rows = await fetch_openg_results("20260818", "20260818", category="Cnstwk")

    assert [row["bid_ntce_ord"] for row in rows] == ["000"]
    assert calls[0]["url"] == OPENG_RESULT_URLS["Cnstwk"]
    assert calls[0]["params"]["inqryDiv"] == "3"


async def test_stream_openg_results_reports_error_envelope(monkeypatch, caplog):
    """resultCode 가 00 이 아니면 성공으로 넘기지 않고 실패 구간으로 남깁니다."""
    _install_fake_client(
        monkeypatch, [_xml_response(_response_xml("", result_code="03", total_count=0))]
    )

    with (
        caplog.at_level(logging.ERROR, logger="src.app.services.api_collector"),
        pytest.raises(RangeCollectionError) as exc_info,
    ):
        await stream_openg_results("20260818", "20260818", lambda rows: len(rows))

    assert exc_info.value.error_label == "개찰결과"
    assert exc_info.value.saved == 0
    assert exc_info.value.failed_ranges == [("20260818", "20260818")]
    assert "API 오류 [03]" in caplog.text


async def test_fetch_paged_keeps_input_day_axis_by_default():
    """기존 수집 호출은 inqryDiv 를 넘기지 않으므로 기본값 1 이 유지되어야 합니다."""
    calls: list[dict] = []
    client = _FakeAsyncClient([_xml_response(_response_xml("", total_count=0))], calls)

    rows = await _fetch_paged(
        client,
        OPENG_RESULT_URLS["Servc"],
        "20260818",
        "20260818",
        999,
        _map_openg_result_item("Servc"),
        "개찰결과",
        asyncio.Semaphore(1),
    )

    assert rows == []
    assert calls[0]["params"]["inqryDiv"] == "1"
