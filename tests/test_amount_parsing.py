"""
tests/test_amount_parsing.py

금액 정제(_coerce_amount) 및 적재 경로(api_collector) 금액 파싱 안전성 테스트.

검증 항목:
1. _coerce_amount 의 Decimal 기반 파싱 (2^53 초과 큰 정수 정밀도 보존)
2. 소수점 표기 내림(ROUND_DOWN) 정수부 절단 규칙 (과거 107건 불일치 데이터와 일관성)
3. NaN, Infinity, 음수, bool, 빈 값 등 이상치 명시적 제외 (None 반환)
4. extract_business_budget 의 raw_data 키 우선순위(asignBdgtAmt -> bdgtAmt)
5. 적재 매퍼(_map_announcement_item)의 BIGINT 범위 초과 방어 (NULL 저장 및 경고 로그)
6. BIGINT 범위 초과 시에도 raw_data 원본 100% 무손실 보존 (G1 원칙)
"""

import logging
import xml.etree.ElementTree as ET
from decimal import Decimal

from src.app.models.bids import _coerce_amount, extract_business_budget
from src.app.services.api_collector import (
    _map_announcement_item,
    _map_result_item,
)


class TestCoerceAmount:
    """_coerce_amount 단위 테스트."""

    def test_normal_integer(self):
        assert _coerce_amount(1000) == 1000
        assert _coerce_amount("1000") == 1000
        assert _coerce_amount("1,234,567") == 1234567

    def test_large_integer_precision_preserved(self):
        """2^53을 초과하는 20자리 큰 정수에서 정밀도 손실이 없어야 한다."""
        raw_val = "12240000012240000011"
        expected = 12240000012240000011
        # 2^53을 넘는 정밀도가 보존되어야 함
        assert _coerce_amount(raw_val) == expected

        raw_val_2 = "26849000084793201743"
        expected_2 = 26849000084793201743
        assert _coerce_amount(raw_val_2) == expected_2

    def test_decimal_fraction_truncation(self):
        """과거 107건 데이터와 동일하게 소수점 표기는 ROUND_DOWN(내림)으로 절단되어야 한다."""
        assert _coerce_amount("3469575370.8") == 3469575370
        assert _coerce_amount("691483403.6") == 691483403
        assert _coerce_amount("158420.9") == 158420
        assert _coerce_amount("27.5") == 27
        assert _coerce_amount("5988.67") == 5988
        assert _coerce_amount("0.0") == 0
        assert _coerce_amount("0.999") == 0

    def test_negative_values_rejected(self):
        """음수는 공고 금액으로 유효하지 않으므로 None을 반환해야 한다."""
        assert _coerce_amount(-1) is None
        assert _coerce_amount("-1000") is None
        assert _coerce_amount("-100.5") is None

    def test_special_floats_and_invalids_rejected(self):
        """NaN, Infinity, 빈 문자열, bool 등 유효하지 않은 입력은 None을 반환해야 한다."""
        assert _coerce_amount("NaN") is None
        assert _coerce_amount("nan") is None
        assert _coerce_amount("Infinity") is None
        assert _coerce_amount("-Infinity") is None
        assert _coerce_amount("inf") is None
        assert _coerce_amount("-inf") is None
        assert _coerce_amount("") is None
        assert _coerce_amount(None) is None
        assert _coerce_amount(True) is None
        assert _coerce_amount(False) is None
        assert _coerce_amount("abc") is None
        assert _coerce_amount("12a34") is None

    def test_decimal_input(self):
        """Decimal 인스턴스 입력도 정상 처리되어야 한다."""
        assert _coerce_amount(Decimal("1000")) == 1000
        assert _coerce_amount(Decimal("1000.75")) == 1000
        assert _coerce_amount(Decimal("-50")) is None
        assert _coerce_amount(Decimal("NaN")) is None


class TestExtractBusinessBudget:
    """extract_business_budget 단위 테스트."""

    def test_priority_asign_over_bdgt(self):
        data = {
            "asignBdgtAmt": "1,000,000",
            "bdgtAmt": "2,000,000",
        }
        assert extract_business_budget(data) == 1000000

    def test_fallback_to_bdgt(self):
        data = {
            "asignBdgtAmt": "",
            "bdgtAmt": "2,000,000",
        }
        assert extract_business_budget(data) == 2000000

    def test_no_keys_returns_fallback(self):
        assert extract_business_budget({}, fallback=None) is None
        assert extract_business_budget(None, fallback=0) == 0


class TestCollectorAmountHardening:
    """api_collector 적재 경로 BIGINT 초과 방어 및 G1 무손실 검증."""

    def test_announcement_item_bigint_overflow_sets_none_and_logs_warning(self, caplog):
        """BIGINT 범위를 초과하는 공고 금액은 컬럼에 NULL로 저장되고 경고가 기록되어야 한다."""
        item_xml = """<item>
            <bidNtceNo>R25BK01131785</bidNtceNo>
            <bidNtceOrd>000</bidNtceOrd>
            <bidNtceNm>포화 공고</bidNtceNm>
            <presmptPrce>12240000012240000011</presmptPrce>
        </item>"""
        element = ET.fromstring(item_xml)  # noqa: S314 # nosec B314
        raw_data = {
            "bidNtceNo": "R25BK01131785",
            "asignBdgtAmt": "12240000012240000011",
            "presmptPrce": "12240000012240000011",
        }

        mapper = _map_announcement_item("Thng")
        with caplog.at_level(logging.WARNING):
            result = mapper(element, raw_data)

        # 컬럼에 NULL(None)이 들어가야 함
        assert result["base_amount"] is None
        assert result["presmpt_prce"] is None

        # raw_data 원본은 G1 원칙대로 100% 보존되어야 함
        assert result["raw_data"]["asignBdgtAmt"] == "12240000012240000011"
        assert result["raw_data"]["presmptPrce"] == "12240000012240000011"

        # 경고 로그가 남아야 함
        assert any(
            "BIGINT 범위를 초과하여 NULL 로 저장합니다" in record.message
            for record in caplog.records
        )

    def test_announcement_item_normal_amount(self):
        """정상 범위 금액은 base_amount와 presmpt_prce에 올바르게 매핑되어야 한다."""
        item_xml = """<item>
            <bidNtceNo>20250600001</bidNtceNo>
            <bidNtceOrd>000</bidNtceOrd>
            <bidNtceNm>정상 공고</bidNtceNm>
            <presmptPrce>1,000,000</presmptPrce>
        </item>"""
        element = ET.fromstring(item_xml)  # noqa: S314 # nosec B314
        raw_data = {
            "bidNtceNo": "20250600001",
            "asignBdgtAmt": "1,100,000",
            "presmptPrce": "1,000,000",
        }

        mapper = _map_announcement_item("Thng")
        result = mapper(element, raw_data)

        assert result["base_amount"] == 1100000
        assert result["presmpt_prce"] == 1000000
        assert result["raw_data"] == raw_data

    def test_result_item_bigint_overflow_sets_none_and_logs_warning(self, caplog):
        """낙찰 결과에서도 sucsfbidAmt가 BIGINT 범위를 초과하면 NULL로 저장되고 경고가 기록되어야 한다."""
        item_xml = """<item>
            <bidNtceNo>RES-OVERFLOW</bidNtceNo>
            <bidNtceOrd>00</bidNtceOrd>
            <sucsfbidAmt>99999999999999999999</sucsfbidAmt>
        </item>"""
        element = ET.fromstring(item_xml)  # noqa: S314 # nosec B314
        raw_data = {
            "bidNtceNo": "RES-OVERFLOW",
            "sucsfbidAmt": "99999999999999999999",
        }

        mapper = _map_result_item("Servc")
        with caplog.at_level(logging.WARNING):
            result = mapper(element, raw_data)

        assert result["sucsf_bid_amt"] is None
        assert result["raw_data"]["sucsfbidAmt"] == "99999999999999999999"
        assert any(
            "BIGINT 범위를 초과하여 NULL 로 저장합니다" in record.message
            for record in caplog.records
        )
