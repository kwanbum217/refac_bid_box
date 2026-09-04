"""
tests/test_dashboard_stats_parity.py

원본 apps/bids/tests.py 의 대시보드·비교 통계 테스트 이식입니다.

화면에 뜨는 숫자가 틀리면 곧바로 신뢰를 잃는 영역인데 회귀 테스트가 없었습니다.
원본이 테스트로 고정했던 집계 규칙(범위, 라벨, 단가성 제외, 캐시 갱신)을 옮깁니다.

대응하는 원본 테스트:

- test_dashboard_stats_api_returns_monthly_series
- test_dashboard_stats_totals_use_2015_to_present_scope
- test_dashboard_stats_renames_unclassified_agency_label
- test_dashboard_stats_cache_refreshes_after_new_result_is_collected
- test_dashboard_company_table_uses_total_amount_contracts_only
- test_dashboard_company_table_cleans_unreadable_company_names
- test_dashboard_page_formats_chart_units_readably
- test_compare_stats_api_returns_monthly_series
- test_compare_stats_base_total_ignores_estimated_price_only_rows
- test_compare_stats_api_returns_json_error_when_backend_fails
"""

import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import (
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
    extract_business_budget,
)
from src.app.services.dashboard import _compare_stats_cache_key, _dashboard_stats_cache_key

STATS_URL = "/api/v1/bids/stats"
COMPARE_URL = "/api/v1/bids/compare-stats"


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """집계는 캐시를 타므로 테스트마다 격리합니다.

    캐시를 끄지 않고 테스트 로컬 저장소로 바꿉니다. 꺼 버리면 캐시 갱신
    테스트가 아무것도 검증하지 못합니다.
    """
    from src.app.core import cache as cache_module

    store: dict = {}
    monkeypatch.setattr(cache_module.cache, "get", store.get)
    monkeypatch.setattr(
        cache_module.cache, "set", lambda key, value, ttl: store.__setitem__(key, value)
    )
    monkeypatch.setattr(cache_module.cache, "delete", lambda key: store.pop(key, None))
    return store


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="dashboard_tester",
        password=make_password("pw-test-1234"),
        email="dash@example.com",
        nickname="대시보드 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _add_result(db, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_no": "ANN-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 낙찰 결과",
        "bidwinnr_nm": "기준 업체",
        "dminstt_nm": "기준 발주기관",
        "category": "Servc",
        "sucsf_bid_amt": 950000,
        "sucsf_bid_rate": 95.0,
        "rl_openg_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "ANN-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 공고",
        "dminstt_nm": "기준 발주기관",
        "category": "Thng",
        "base_amount": 1100000,
        "presmpt_prce": 1000000,
        "bid_ntce_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# 대시보드 통계
# --------------------------------------------------------------------------- #


def test_dashboard_stats_api_returns_monthly_series(auth_client, isolated_db):
    """월별 시계열과 범위 라벨이 원본 규격대로 나온다."""
    _add_result(isolated_db)

    payload = auth_client.get(STATS_URL).json()

    assert payload["scope_label"] == "2015년 ~ 현재"
    assert payload["total_count"] == 1
    assert payload["by_month"]
    assert re.match(r"^\d{4}-\d{2}$", payload["by_month"][0]["month"])


def test_dashboard_stats_totals_use_2015_to_present_scope(auth_client, isolated_db):
    """2015년 이전 낙찰은 집계에서 제외한다.

    범위를 놓치면 총액과 평균 낙찰률이 통째로 달라집니다.
    """
    _add_result(isolated_db)
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-OLD",
        bid_ntce_nm="범위 밖 과거 낙찰",
        bidwinnr_nm="과거 업체",
        dminstt_nm="과거 발주기관",
        sucsf_bid_amt=999999999,
        sucsf_bid_rate=10.0,
        rl_openg_dt=datetime(2014, 12, 31, 23, 59),
    )

    payload = auth_client.get(STATS_URL).json()

    assert payload["total_count"] == 1
    assert payload["total_amount"] == 950000
    assert payload["avg_rate"] == 95.0


def test_dashboard_stats_renames_unclassified_agency_label(auth_client, isolated_db):
    """수집 원본의 분석불가 라벨을 화면 표기로 치환한다."""
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-UNCLASSIFIED",
        bid_ntce_nm="미분류 기관 낙찰",
        bidwinnr_nm="미분류 업체",
        dminstt_nm="기타 기관(분석불가)",
        sucsf_bid_amt=9900000,
        sucsf_bid_rate=90.0,
    )

    agency_names = [item["name"] for item in auth_client.get(STATS_URL).json()["by_agency"]]

    assert "미분류 기관" in agency_names
    assert "기타 기관(분석불가)" not in agency_names


def test_dashboard_stats_cache_refreshes_after_new_result_is_collected(auth_client, isolated_db):
    """새 낙찰이 들어오면 캐시가 갱신되어야 한다.

    무효화가 안 되면 데이터를 갱신해도 화면에 옛 숫자가 계속 보입니다.
    """
    _add_result(isolated_db)
    assert auth_client.get(STATS_URL).json()["total_count"] == 1

    _add_result(
        isolated_db,
        bid_ntce_no="ANN-002",
        bid_ntce_nm="두 번째 낙찰",
        bidwinnr_nm="다른 업체",
        dminstt_nm="다른 발주기관",
        category="Thng",
        sucsf_bid_amt=880000,
        sucsf_bid_rate=88.0,
        rl_openg_dt=utcnow() + timedelta(minutes=5),
        collected_at=utcnow() + timedelta(minutes=5),
    )

    assert auth_client.get(STATS_URL).json()["total_count"] == 2


def test_dashboard_company_table_uses_total_amount_contracts_only(auth_client, isolated_db):
    """업체 순위는 총액 계약만 집계한다.

    학교주관구매 같은 단가성 입찰은 금액이 실제 계약 규모가 아니라, 섞으면
    순위가 뒤집힙니다.
    """
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-UNIT-PRICE",
        bid_ntce_nm="2026학년도 테스트중학교 교복 학교주관구매",
        bidwinnr_nm="단가성 업체",
        dminstt_nm="단가 발주기관",
        sucsf_bid_amt=9999999999,
        sucsf_bid_rate=99.0,
    )
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-TOTAL-LARGE",
        bid_ntce_nm="총액 계약 검증",
        bidwinnr_nm="대형 총액 업체",
        dminstt_nm="총액 발주기관",
        sucsf_bid_amt=5000000,
        sucsf_bid_rate=90.0,
    )
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-TOTAL-SMALL",
        bid_ntce_nm="소액 총액 계약 검증",
        bidwinnr_nm="소형 총액 업체",
        dminstt_nm="총액 발주기관",
        sucsf_bid_amt=2000000,
        sucsf_bid_rate=91.0,
    )

    companies = auth_client.get(STATS_URL).json()["by_company"]
    names = [item["name"] for item in companies]

    assert "단가성 업체" not in names
    assert companies[0]["name"] == "대형 총액 업체"
    assert companies[0]["total_amt"] == 5000000


def test_dashboard_company_table_cleans_unreadable_company_names(auth_client, isolated_db):
    """깨진 업체명은 빼고, 공동수급 문자열에서는 실제 상호를 뽑는다."""
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-GARBLED",
        bid_ntce_nm="깨진 업체명 검증",
        bidwinnr_nm="!!!@@@",
        dminstt_nm="깨진 발주기관",
        sucsf_bid_amt=9000000,
        sucsf_bid_rate=90.0,
    )
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-JOINT",
        bid_ntce_nm="공동수급 업체명 검증",
        bidwinnr_nm=(
            "[1^도급업체^공동^에스케이에코플랜트 주식회사^장동현^대한민국^29^"
            "에스케이에코플랜트 주식회사^^1018134928]"
        ),
        dminstt_nm="공동 발주기관",
        sucsf_bid_amt=8000000,
        sucsf_bid_rate=91.0,
    )
    _add_result(
        isolated_db,
        bid_ntce_no="ANN-READABLE",
        bid_ntce_nm="정상 업체명 검증",
        bidwinnr_nm="정상 업체",
        dminstt_nm="정상 발주기관",
        sucsf_bid_amt=7000000,
        sucsf_bid_rate=92.0,
    )

    names = [item["name"] for item in auth_client.get(STATS_URL).json()["by_company"]]

    assert "!!!@@@" not in names
    assert "에스케이에코플랜트 주식회사" in names
    assert "정상 업체" in names


def test_dashboard_page_formats_chart_units_readably(auth_client, isolated_db):
    """대시보드 화면이 원본 문구와 포매팅 함수를 그대로 쓴다."""
    _add_result(isolated_db)

    body = auth_client.get("/bids/dashboard/").text

    for phrase in (
        "전체 낙찰 건수",
        "누적 낙찰금액",
        "2015년 ~ 현재",
        "총액 계약 상위 10개 업체",
        "단가성 입찰을 제외",
        "총액 합계",
        "최근 12개월 기준 낙찰 건수 흐름",
        "function formatCount",
        "낙찰 건수",
        "jo.toLocaleString",
    ):
        assert phrase in body, phrase
    # 억원 단위 반올림 표기는 원본에서 제거된 형식입니다.
    assert ".toFixed(1) + '억원'" not in body


# --------------------------------------------------------------------------- #
# 비교 통계
# --------------------------------------------------------------------------- #


def test_compare_stats_api_returns_monthly_series(auth_client, isolated_db):
    """공고·낙찰 양쪽 월별 시계열과 기관 순위가 나온다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)

    payload = auth_client.get(COMPARE_URL).json()

    assert payload["announce_count"] == 1
    assert payload["announce_total_base_amount"] == 1100000
    assert payload["result_count"] == 1
    assert payload["announce_by_month"]
    assert payload["result_by_month"]
    assert re.match(r"^\d{4}-\d{2}$", payload["announce_by_month"][0]["month"])
    assert payload["agency_announce_top10"][0]["total_base_amount"] == 1100000


def test_compare_stats_base_total_ignores_estimated_price_only_rows(auth_client, isolated_db):
    """예정가격만 있는 공고는 기초금액 합계에 넣지 않는다.

    넣으면 공고 총액이 부풀어 낙찰 총액과의 비교가 무의미해집니다.
    """
    _add_announcement(isolated_db)
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-ONLY-PRESMPT",
        bid_ntce_nm="예정가격만 있는 공고",
        base_amount=None,
        presmpt_prce=2200000,
    )

    payload = auth_client.get(COMPARE_URL).json()

    assert payload["announce_count"] == 2
    assert payload["announce_total_base_amount"] == 1100000


def test_compare_stats_excludes_outlier_amounts_from_totals(auth_client, isolated_db):
    """상한을 넘는 기초금액은 집계에서 뺀다.

    2026-09-04 실측에서 조달청 원본 오류 33건(자릿수 중복 입력, 111111111111111
    더미값, BIGINT 포화)이 공고 총액을 -6,063,896,128,872,295,352 로 만들었습니다.
    상한 초과분을 빼지 않으면 화면 숫자가 통째로 뒤집힙니다.
    """
    _add_announcement(isolated_db)
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-OUTLIER",
        bid_ntce_nm="자릿수가 깨진 공고",
        base_amount=137150000137150000,
        raw_data={"asignBdgtAmt": "137150000137150000"},
    )

    payload = auth_client.get(COMPARE_URL).json()

    assert payload["announce_count"] == 2
    assert payload["announce_total_base_amount"] == 1100000
    assert [row["total_base_amount"] for row in payload["agency_announce_top10"]] == [1100000]


def test_compare_stats_keeps_largest_realistic_amount(auth_client, isolated_db):
    """상한 아래의 대형 사업은 그대로 집계한다.

    실재하는 최대 규모(가덕도신공항 약 10.7조)까지 잘라내면 상한이 이상치 제거가
    아니라 데이터 절단이 됩니다.
    """
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-LARGE",
        bid_ntce_nm="대형 사업 공고",
        base_amount=10717478400000,
        raw_data={"bdgtAmt": "10717478400000"},
    )

    payload = auth_client.get(COMPARE_URL).json()

    assert payload["announce_total_base_amount"] == 10717478400000


def test_compare_stats_reads_comma_separated_amount(auth_client, isolated_db):
    """콤마가 섞인 금액을 파이썬 경로와 같게 읽어 적재하고 집계한다.

    `models.bids._coerce_amount` 는 콤마를 지우고 base_amount 에 적재하며,
    대시보드는 base_amount 컬럼 기반으로 동일한 금액을 집계합니다.
    """
    raw_data = {"asignBdgtAmt": "1,234,567"}
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-COMMA",
        bid_ntce_nm="콤마 표기 공고",
        base_amount=extract_business_budget(raw_data),
        raw_data=raw_data,
    )

    payload = auth_client.get(COMPARE_URL).json()

    assert payload["announce_total_base_amount"] == 1234567


def test_compare_stats_api_returns_json_error_when_backend_fails(auth_client):
    """집계 실패 시 원본과 같은 오류 계약을 돌려준다.

    화면(compare.html)이 data.message 를 읽습니다. FastAPI 기본 detail 로
    내보내면 사유가 표시되지 않고 fallback 문구만 뜹니다.
    """
    with patch(
        "src.app.api.v1.bids.get_compare_stats_data", side_effect=RuntimeError("boom")
    ) as mocked:
        response = auth_client.get(COMPARE_URL)

    assert response.status_code == 500
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["message"]
    mocked.assert_called_once()


def test_dashboard_stats_api_returns_json_error_when_backend_fails(auth_client):
    """대시보드 통계도 같은 오류 계약을 따른다."""
    with patch("src.app.api.v1.bids.get_dashboard_stats", side_effect=RuntimeError("boom")):
        response = auth_client.get(STATS_URL)

    assert response.status_code == 500
    assert response.json()["status"] == "error"


def test_dashboard_stats_cache_key_includes_aggregation_version():
    """요약 집계 버전이 캐시 키에 포함되어 알고리즘 변경 시 캐시가 분리된다."""
    t0 = utcnow()
    summary_v1 = BidDatasetSummary(
        dataset="result",
        total_count=10,
        total_amount=1000,
        source_latest_collected_at=t0,
        aggregation_version=1,
        rebuilt_at=t0,
    )
    summary_v2 = BidDatasetSummary(
        dataset="result",
        total_count=10,
        total_amount=1000,
        source_latest_collected_at=t0,
        aggregation_version=2,
        rebuilt_at=t0,
    )

    key_v1 = _dashboard_stats_cache_key(summary_v1)
    key_v2 = _dashboard_stats_cache_key(summary_v2)

    assert "v1" in key_v1
    assert "v2" in key_v2
    assert key_v1 != key_v2


def test_compare_stats_cache_key_includes_aggregation_versions():
    """비교 통계 캐시 키에도 양쪽 데이터셋의 버전이 포함된다."""
    t0 = utcnow()
    ann_v1 = BidDatasetSummary(
        dataset="announcement",
        total_count=10,
        total_amount=1000,
        source_latest_collected_at=t0,
        aggregation_version=1,
        rebuilt_at=t0,
    )
    ann_v2 = BidDatasetSummary(
        dataset="announcement",
        total_count=10,
        total_amount=1000,
        source_latest_collected_at=t0,
        aggregation_version=2,
        rebuilt_at=t0,
    )
    res = BidDatasetSummary(
        dataset="result",
        total_count=5,
        total_amount=500,
        source_latest_collected_at=t0,
        aggregation_version=1,
        rebuilt_at=t0,
    )

    key_v1 = _compare_stats_cache_key(ann_v1, res)
    key_v2 = _compare_stats_cache_key(ann_v2, res)

    assert "v1" in key_v1
    assert "v2" in key_v2
    assert key_v1 != key_v2


def test_announcement_amount_column_parity_with_legacy_json_path(isolated_db):
    """옛 JSON 파싱 집계 경로와 새 base_amount 컬럼 기반 집계 경로의 산출값 동일성 대조.

    343건 불일치 분석(docs/analysis/base_amount_column_mismatch_343_20260904.md)의 세 가지 형태:
    1. raw 금액 '0.0', 컬럼 NULL (234건 형태): SUM 에서 NULL 무시 및 0 기여로 결과 동일
    2. raw 금액 소수점 표기, 컬럼 정수 절단 (107건 형태): 소수점 표기 데이터의 정수 절단 적재로 결과 동일
    3. 100조 초과 이상치 / BIGINT 포화 (2건 형태 + 31건 이상치): 양쪽 경로 모두 상한 초과로 제외(NULL)
    """
    from sqlalchemy import case, func, literal, select

    from src.app.services.dashboard import (
        AMOUNT_NUMERIC,
        MAX_REASONABLE_ANNOUNCEMENT_AMOUNT,
        _announcement_amount_expr,
        _dialect_name,
    )

    def _legacy_json_text(db, column, key: str):
        if _dialect_name(db) == "mysql":
            return func.json_unquote(func.json_extract(column, f"$.{key}"))
        return func.json_extract(column, f"$.{key}")

    def _legacy_announcement_amount_expr(db):
        raw_text = func.coalesce(
            func.nullif(
                _legacy_json_text(db, BidAnnouncement.raw_data, "asignBdgtAmt"), literal("")
            ),
            func.nullif(_legacy_json_text(db, BidAnnouncement.raw_data, "bdgtAmt"), literal("")),
        )
        raw_amount = func.cast(func.replace(raw_text, literal(","), literal("")), AMOUNT_NUMERIC)
        resolved = case(
            (
                BidAnnouncement.raw_data.is_(None),
                func.cast(BidAnnouncement.base_amount, AMOUNT_NUMERIC),
            ),
            else_=raw_amount,
        )
        return case((resolved > literal(MAX_REASONABLE_ANNOUNCEMENT_AMOUNT), None), else_=resolved)

    # 1. 일반 정상 공고 (정상 값 기여)
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-NORMAL",
        base_amount=1500000,
        raw_data={"asignBdgtAmt": "1500000"},
    )

    # 2. 형태 1 (234건 유형): raw 금액 '0.0', 컬럼 base_amount 는 NULL
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-FORM-1",
        base_amount=None,
        raw_data={"asignBdgtAmt": "0.0"},
    )

    # 3. 형태 2 (107건 유형): raw 금액 소수점 표기('158420.00'), 컬럼 base_amount 는 정수 절단 158420
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-FORM-2",
        base_amount=158420,
        raw_data={"asignBdgtAmt": "158420.00"},
    )

    # 4. 형태 3 (포화 2건 유형): 20자리 포화 건 (raw 12240000012240000011, 컬럼 9223372036854775807)
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-FORM-3-SAT",
        base_amount=9223372036854775807,
        raw_data={"bdgtAmt": "12240000012240000011"},
    )

    # 5. 형태 3 추가 (자릿수 반복 이상치 유형): 137150000137150000 (100조 초과)
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-FORM-3-REPEAT",
        base_amount=137150000137150000,
        raw_data={"asignBdgtAmt": "137150000137150000"},
    )

    legacy_sum = isolated_db.scalar(select(func.sum(_legacy_announcement_amount_expr(isolated_db))))
    new_sum = isolated_db.scalar(select(func.sum(_announcement_amount_expr(isolated_db))))

    # 세 가지 형태가 포함된 픽스처에서 두 경로의 전체 SUM 집계 결과가 완전히 일치해야 함
    assert legacy_sum is not None
    assert new_sum is not None
    assert legacy_sum == new_sum

    # 정상 공고(1,500,000) + 절단 공고(158,420) = 1,658,420 (형태 1은 0, 형태 3은 상한 초과 제외)
    expected_sum = 1500000 + 158420
    assert int(new_sum) == expected_sum

    # 추가 검증: 과거 107건 실측 예시(raw '3469575370.8' vs 컬럼 3469575370)처럼
    # 소수부 .8 로 인해 SQL CAST 반올림과 컬럼 절단 간 1원 차이가 발생하는 케이스에서도
    # 차이가 정확히 1원(건당 1원 이하, 총액 대비 5e-17) 이내임을 확인
    _add_announcement(
        isolated_db,
        bid_ntce_no="PARITY-FORM-2-FRACTION",
        base_amount=3469575370,
        raw_data={"asignBdgtAmt": "3469575370.8"},
    )
    legacy_sum_fraction = isolated_db.scalar(
        select(func.sum(_legacy_announcement_amount_expr(isolated_db)))
    )
    new_sum_fraction = isolated_db.scalar(select(func.sum(_announcement_amount_expr(isolated_db))))
    assert abs(legacy_sum_fraction - new_sum_fraction) <= 1
