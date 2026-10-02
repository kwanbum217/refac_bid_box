from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.app.api.v1.evaluations import _scenario_prices
from src.app.services.demand_institutions import (
    classify_contract_regime,
    collect_demand_institutions,
    incremental_start,
    institution_region,
    parse_response,
    split_year_ranges,
    upsert_demand_institutions,
)
from src.app.services.evaluation_rules import (
    extract_contract_regime,
    resolve_evaluation_rule_from_raw_data,
)


def test_parse_response_success_empty_and_single_item() -> None:
    item = {"dminsttCd": "123", "dminsttNm": "기관"}
    assert parse_response(
        {"response": {"header": {"resultCode": "00"}, "body": {"items": [item], "totalCount": 1}}}
    ) == ([item], 1)
    assert parse_response(
        {"response": {"header": {"resultCode": "00"}, "body": {"items": [], "totalCount": 0}}}
    ) == ([], 0)
    assert parse_response(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"items": {"item": item}, "totalCount": 1},
            }
        }
    ) == ([item], 1)


@pytest.mark.parametrize("code", ["07", "08"])
def test_parse_response_error_payloads(code: str) -> None:
    payload = {"nkoneps.com.response.ResponseError": {"header": {"resultCode": code}}}
    with pytest.raises(RuntimeError, match="오류 응답"):
        parse_response(payload)


def test_year_ranges_are_at_most_one_year() -> None:
    ranges = split_year_ranges(date(1950, 1, 1), date(1952, 6, 1))
    assert len(ranges) == 3
    assert ranges[0] == (date(1950, 1, 1), date(1950, 12, 31))
    assert all((end - start).days < 365 for start, end in ranges)


@pytest.mark.asyncio
async def test_collection_walks_all_pages_and_sends_api_parameters() -> None:
    pages = [
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"items": [{"dminsttCd": "1"}], "totalCount": 1000},
            }
        },
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"items": [{"dminsttCd": "2"}], "totalCount": 1000},
            }
        },
    ]

    class Response:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code

        def json(self):
            return self.payload

        def raise_for_status(self):
            pass

    client = SimpleNamespace(get=AsyncMock(side_effect=[Response(page) for page in pages]))
    rows = await collect_demand_institutions(
        client, "redacted-test-key", date(2025, 1, 1), date(2025, 1, 2), 1
    )
    assert rows == [{"dminsttCd": "1"}, {"dminsttCd": "2"}]
    assert [call.kwargs["params"]["pageNo"] for call in client.get.await_args_list] == [1, 2]
    assert client.get.await_args.kwargs["params"]["inqryDiv"] == 1


def test_upsert_is_idempotent_by_institution_code() -> None:
    class FakeDB:
        def __init__(self):
            self.rows = {}
            self.commits = 0

        def get(self, model, key):
            return self.rows.get(key)

        def add(self, row):
            self.rows[row.dminstt_cd] = row

        def commit(self):
            self.commits += 1

    db = FakeDB()
    first = {"dminsttCd": "A", "dminsttNm": "기관", "chgDt": "202601020304"}
    assert upsert_demand_institutions(db, [first]) == 1
    row = db.rows["A"]
    assert row.chg_dt == datetime(2026, 1, 2, 3, 4)
    assert upsert_demand_institutions(db, [{**first, "dminsttNm": "변경 기관"}]) == 1
    assert len(db.rows) == 1
    assert db.rows["A"].dminstt_nm == "변경 기관"
    assert db.commits == 2


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"instt_ty_lrgclsfc_nm": "교육행정조직", "instt_ty_midclsfc_nm": "지역교육청"}, "LOCAL"),
        ({"jrsdctn_div_nm": "지방자치단체"}, "LOCAL"),
        ({"jrsdctn_div_nm": "지방공기업"}, "LOCAL"),
        ({"instt_ty_lrgclsfc_nm": "유치원", "instt_ty_smlclsfc_nm": "공립"}, "LOCAL"),
        ({"instt_ty_lrgclsfc_nm": "특수학교", "instt_ty_smlclsfc_nm": "공립"}, "LOCAL"),
        ({"instt_ty_lrgclsfc_nm": "고등학교", "instt_ty_smlclsfc_nm": "공립"}, "LOCAL"),
        (
            {
                "instt_ty_lrgclsfc_nm": "교육행정조직",
                "instt_ty_midclsfc_nm": " 시, 도교육청 직속기관 ",
            },
            "LOCAL",
        ),
        ({"instt_ty_lrgclsfc_nm": "초등학교", "instt_ty_smlclsfc_nm": " 공립 "}, "LOCAL"),
        ({"jrsdctn_div_nm": "국가기관"}, "NATIONAL"),
        ({"jrsdctn_div_nm": "공기업"}, "NATIONAL"),
        ({"jrsdctn_div_nm": "준정부기관"}, "NATIONAL"),
        ({"jrsdctn_div_nm": "정부투자기관"}, "NATIONAL"),
        ({"jrsdctn_div_nm": "기타공공기관"}, None),
        ({"instt_ty_lrgclsfc_nm": "대학교", "instt_ty_smlclsfc_nm": "국립"}, None),
        ({"instt_ty_lrgclsfc_nm": "중학교", "instt_ty_smlclsfc_nm": "국립"}, None),
        ({}, None),
    ],
)
def test_regime_mapping_rules(row: dict, expected: str | None) -> None:
    assert classify_contract_regime(row) == expected


def test_regime_mapping_accepts_raw_api_field_names() -> None:
    institution = {
        "jrsdctnDivNm": "지방자치단체",
        "insttTyCdLrgclsfcNm": "교육행정조직",
        "insttTyCdMidclsfcNm": "지역교육청",
        "rgnCd": "26000",
        "rgnNm": "부산광역시",
    }
    assert classify_contract_regime(institution) == "LOCAL"
    assert institution_region(institution) == ("26000", "부산광역시")


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"dminstt_nm": "국토교통부 부산지방국토관리청", "jrsdctn_div_nm": "국가기관"}, "NATIONAL"),
        ({"dminstt_nm": "대법원 전주지방법원 군산지원", "jrsdctn_div_nm": "국가기관"}, "NATIONAL"),
        ({"dminstt_nm": "구미도시공사", "jrsdctn_div_nm": "지방공기업"}, "LOCAL"),
        ({"dminstt_nm": "서울시 강북구도시관리공단", "jrsdctn_div_nm": "지방공기업"}, "LOCAL"),
        (
            {
                "dminstt_nm": "교육지원청",
                "instt_ty_lrgclsfc_nm": "교육행정조직",
                "instt_ty_midclsfc_nm": "지역교육청",
            },
            "LOCAL",
        ),
        (
            {
                "dminstt_nm": "부석초등학교",
                "instt_ty_lrgclsfc_nm": "초등학교",
                "instt_ty_smlclsfc_nm": "공립",
            },
            "LOCAL",
        ),
        (
            {
                "dminstt_nm": "한남대학교",
                "instt_ty_lrgclsfc_nm": "대학교",
                "instt_ty_smlclsfc_nm": "사립",
            },
            None,
        ),
        ({"dminstt_nm": "한국학중앙연구원", "jrsdctn_div_nm": "기타공공기관"}, None),
    ],
)
def test_known_counterexamples(row: dict, expected: str | None) -> None:
    assert classify_contract_regime(row) == expected


def test_regime_extraction_prefers_explicit_contract_method() -> None:
    assert (
        extract_contract_regime({"cntrctCnclsMthdNm": "지방계약"}, institution_regime="NATIONAL")
        == "LOCAL"
    )
    assert extract_contract_regime({}, institution_regime="LOCAL") == "LOCAL"
    assert extract_contract_regime({}, institution_regime=None) is None


def test_region_passes_to_rule_context() -> None:
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {"sucsfbidMthdNm": "적격심사제-보험용역 적격심사 추정가격 5억원미만"},
        institution_regime="LOCAL",
        region_code="26000",
        region_name="부산광역시",
    )
    assert result.contract_regime == "LOCAL"
    assert result.region_code == "26000"
    assert result.region_name == "부산광역시"
    assert institution_region({"rgn_cd": "26000", "rgn_nm": " 부산광역시 "}) == (
        "26000",
        "부산광역시",
    )


@pytest.mark.parametrize(
    ("regime", "expected_range"), [("LOCAL", Decimal("0.03")), (None, Decimal("0.02"))]
)
def test_scenarios_select_local_three_percent_and_unknown_two_percent(
    regime, expected_range
) -> None:
    bid = SimpleNamespace(
        raw_data={},
        cntrct_mthd_nm=None,
        prediction_reference_amount=Decimal("100000"),
    )
    scenarios = _scenario_prices(bid, None, regime)
    assert scenarios[0].pred_price == Decimal("100000") * (Decimal("1") - expected_range)
    assert scenarios[2].pred_price == Decimal("100000") * (Decimal("1") + expected_range)


def test_worker_skips_when_service_key_is_missing(monkeypatch) -> None:
    from src.app.core.config import settings
    from src.tasks import summary_tasks

    monkeypatch.setattr(settings, "G2B_USRINFO_SERVICE_KEY", "")
    monkeypatch.setattr(
        summary_tasks, "collect_and_upsert", AsyncMock(side_effect=AssertionError("must skip"))
    )
    result = summary_tasks._collect_demand_institutions()
    assert result["status"] == "skipped"


def test_incremental_start_uses_day_before_latest_change() -> None:
    class FakeDB:
        def scalar(self, query):
            return datetime(2026, 9, 30, 12, 0)

    assert incremental_start(FakeDB()) == date(2026, 9, 29)


@pytest.mark.asyncio
async def test_rate_limit_429_retries_then_succeeds(monkeypatch) -> None:
    from src.app.services import demand_institutions as service

    monkeypatch.setattr(service.asyncio, "sleep", AsyncMock())
    item = {"dminsttCd": "retry-ok"}

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.payload = payload

        def json(self):
            return self.payload

        def raise_for_status(self):
            if self.status_code == 429:
                import httpx

                request = httpx.Request("GET", service.API_URL)
                response = httpx.Response(429, request=request)
                raise httpx.HTTPStatusError("limited", request=request, response=response)

    client = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                Response(429, {}),
                Response(
                    200,
                    {
                        "response": {
                            "header": {"resultCode": "00"},
                            "body": {"items": [item], "totalCount": 1},
                        }
                    },
                ),
            ]
        )
    )
    rows = await collect_demand_institutions(
        client, "hidden-key", date(2026, 1, 1), date(2026, 1, 1), 2
    )
    assert rows == [item]
    assert client.get.await_count == 2
    assert [call.kwargs["params"]["inqryDiv"] for call in client.get.await_args_list] == [2, 2]


@pytest.mark.asyncio
async def test_rate_limit_retry_exhaustion_reports_http_status(monkeypatch) -> None:
    from src.app.services import demand_institutions as service

    monkeypatch.setattr(service.asyncio, "sleep", AsyncMock())

    class Response:
        status_code = 429

        def json(self):
            return {}

        def raise_for_status(self):
            import httpx

            request = httpx.Request("GET", service.API_URL)
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("limited", request=request, response=response)

    client = SimpleNamespace(get=AsyncMock(return_value=Response()))
    with pytest.raises(RuntimeError, match="HTTP 429") as exc_info:
        await collect_demand_institutions(
            client, "hidden-key", date(2026, 1, 1), date(2026, 1, 1), 1
        )
    assert client.get.await_count == service.MAX_RETRY_ATTEMPTS
    assert "hidden-key" not in str(exc_info.value)


def test_error_payload_diagnostics_preserve_codes_without_service_key() -> None:
    payload = {
        "nkoneps.com.response.ResponseError": {
            "header": {
                "resultCode": "99",
                "returnReasonCode": "23",
                "errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR",
            }
        }
    }
    with pytest.raises(RuntimeError) as exc_info:
        parse_response(payload)
    message = str(exc_info.value)
    assert "resultCode=99" in message
    assert "returnReasonCode=23" in message
    assert "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR" in message
    assert "serviceKey" not in message


@pytest.mark.asyncio
async def test_return_reason_23_retries_then_succeeds(monkeypatch) -> None:
    from src.app.services import demand_institutions as service

    sleep = AsyncMock()
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    limited = {
        "OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {
                "errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR",
                "returnReasonCode": "23",
            }
        }
    }
    success = {"response": {"header": {"resultCode": "00"}, "body": {"items": [], "totalCount": 0}}}

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

        def raise_for_status(self):
            pass

    client = SimpleNamespace(get=AsyncMock(side_effect=[Response(limited), Response(success)]))
    assert (
        await collect_demand_institutions(
            client, "hidden-key", date(2026, 1, 1), date(2026, 1, 1), 2
        )
        == []
    )
    assert client.get.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [0.2, 1, 0.2]
