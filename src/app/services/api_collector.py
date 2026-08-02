"""
src/app/services/api_collector.py

조달청(G2B) 공공데이터 API 수집기 (원본 apps/bids/services/api_collector.py 1:1 이식).

원본 정책을 그대로 보존합니다.
- API 최대 조회 기간 15일 제한에 맞춘 날짜 구간 분할
- 동시 요청 3건 제한 (조달청 서버 연결 거부 방지)
- 429/502/503/504 및 연결 오류에 대한 5회 지수 백오프 재시도
- XML 전체 필드를 raw_data 로 보존하여 기초금액 해석 근거 유지
"""

from __future__ import annotations

import asyncio
import logging
import os

# G2B 공공 API 응답 전용. 외부 사용자 입력이 아닙니다
import xml.etree.ElementTree as ET  # nosec B405
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from src.app.models.bids import extract_business_budget

logger = logging.getLogger(__name__)

API_BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusThng"
BID_ANNOUNCE_API_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng"
)

BID_CATEGORIES: dict[str, dict[str, str]] = {
    "Thng": {
        "name": "물품",
        "bid_url": "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusThng",
        "announce_url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng",
    },
    "Cnstwk": {
        "name": "공사",
        "bid_url": "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusCnstwk",
        "announce_url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk",
    },
    "Servc": {
        "name": "용역",
        "bid_url": "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusServc",
        "announce_url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc",
    },
    "Frgcpt": {
        "name": "외자",
        "bid_url": "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusFrgcpt",
        "announce_url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoFrgcpt",
    },
}

# 동시 요청 수 제한 (조달청 서버 연결 거부 방지)
MAX_CONCURRENT = 3
RANGE_DAYS = 15


def get_service_key() -> str:
    """G2B 서비스 키. 값은 .env 에서만 읽고 코드/로그에 노출하지 않습니다."""
    return os.getenv("serviceKey", "") or os.getenv("SERVICE_KEY", "")


def _get_text(item: ET.Element, tag_name: str, default: str | None = None) -> str | None:
    elem = item.find(tag_name)
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def _parse_datetime(dt_str: str | None) -> datetime | None:
    """개찰일시 문자열을 datetime 으로 변환 (예: 2025/02/15 10:00:00)"""
    if not dt_str:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(amt_str: str | None) -> int | None:
    if not amt_str:
        return None
    try:
        return int(amt_str.replace(",", ""))
    except ValueError:
        return None


def _parse_rate(rate_str: str | None) -> float | None:
    if not rate_str:
        return None
    try:
        return float(rate_str.replace("%", ""))
    except ValueError:
        return None


def split_date_range(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """시작일과 종료일을 15일 단위로 분할합니다 (API 최대 조회 기간 제한)."""
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        return [(start_date, end_date)]

    ranges: list[tuple[str, str]] = []
    curr_date = start_dt
    while curr_date <= end_dt:
        curr_end = min(curr_date + timedelta(days=RANGE_DAYS - 1), end_dt)
        ranges.append((curr_date.strftime("%Y%m%d"), curr_end.strftime("%Y%m%d")))
        curr_date = curr_end + timedelta(days=1)
    return ranges


def _resolve_bid_url(category: str) -> str:
    info = BID_CATEGORIES.get(category)
    return info["bid_url"] if info else API_BASE_URL


def _resolve_announce_url(category: str) -> str:
    info = BID_CATEGORIES.get(category)
    return info["announce_url"] if info else BID_ANNOUNCE_API_URL


async def _make_request_with_retry(
    client: httpx.AsyncClient, url: str, params: dict, max_retries: int = 5
) -> httpx.Response:
    """429 및 50x(502, 503, 504) 에러 발생 시 재시도합니다."""
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params, timeout=120)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code in (429, 502, 503, 504) and attempt < max_retries - 1:
                logger.warning(
                    "서버 응답 에러(%s). %s/%s 재시도 대기",
                    exc.response.status_code,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(3.0 * (attempt + 1))
                continue
            raise
        except httpx.RequestError as exc:
            last_error = exc
            if attempt < max_retries - 1:
                logger.warning("서버 연결 오류(%s). %s/%s 재시도 대기", exc, attempt + 1, max_retries)
                await asyncio.sleep(3.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"재시도 한도를 초과했습니다: {last_error}")


def _item_raw_data(item: ET.Element) -> dict[str, str]:
    return {child.tag: (child.text.strip() if child.text else "") for child in item}


async def _fetch_paged(
    client: httpx.AsyncClient,
    api_url: str,
    step_start: str,
    step_end: str,
    num_of_rows: int,
    mapper: Callable[[ET.Element, dict[str, str]], dict[str, Any]],
    error_label: str,
) -> list[dict[str, Any]]:
    """단일 날짜 구간을 페이지 끝까지 순회 수집합니다."""
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        params = {
            "serviceKey": get_service_key(),
            "pageNo": str(page),
            "numOfRows": str(num_of_rows),
            "inqryDiv": "1",
            "inqryBgnDt": f"{step_start}0000",
            "inqryEndDt": f"{step_end}2359",
            "type": "xml",
        }
        resp = await _make_request_with_retry(client, api_url, params)
        # G2B 공공 API 응답 전용. 외부 사용자 입력이 아닙니다
        root = ET.fromstring(resp.text)  # nosec B314

        result_code = root.findtext(".//resultCode", default="")
        if result_code != "00":
            result_msg = root.findtext(".//resultMsg", default="알 수 없는 오류")
            raise RuntimeError(f"{error_label} API 오류 [{result_code}]: {result_msg}")

        total_count = int(root.findtext(".//totalCount", default="0"))
        for item in root.findall(".//item"):
            items.append(mapper(item, _item_raw_data(item)))

        if page * num_of_rows >= total_count:
            break
        page += 1
        await asyncio.sleep(0.1)

    return items


def _map_result_item(category: str):
    def _mapper(item: ET.Element, raw_data: dict[str, str]) -> dict[str, Any]:
        return {
            "bid_ntce_nm": _get_text(item, "bidNtceNm"),
            "bid_ntce_no": _get_text(item, "bidNtceNo", ""),
            "bid_ntce_ord": _get_text(item, "bidNtceOrd", "00"),
            "bidwinnr_nm": _get_text(item, "bidwinnrNm"),
            "sucsf_bid_amt": _parse_amount(_get_text(item, "sucsfbidAmt")),
            "sucsf_bid_rate": _parse_rate(_get_text(item, "sucsfbidRate")),
            "rl_openg_dt": _parse_datetime(_get_text(item, "rlOpengDt")),
            "dminstt_nm": _get_text(item, "dminsttNm"),
            "category": category,
            "raw_data": raw_data,
        }

    return _mapper


def _map_announcement_item(category: str):
    def _mapper(item: ET.Element, raw_data: dict[str, str]) -> dict[str, Any]:
        return {
            "bid_ntce_nm": _get_text(item, "bidNtceNm"),
            "bid_ntce_no": _get_text(item, "bidNtceNo", ""),
            "bid_ntce_ord": _get_text(item, "bidNtceOrd", "000"),
            "ntce_instt_nm": _get_text(item, "ntceInsttNm"),
            "dminstt_nm": _get_text(item, "dminsttNm"),
            "base_amount": extract_business_budget(raw_data),
            "presmpt_prce": _parse_amount(_get_text(item, "presmptPrce")),
            "bid_ntce_dt": _parse_datetime(_get_text(item, "bidNtceDt")),
            "bid_clse_dt": _parse_datetime(_get_text(item, "bidClseDt")),
            "openg_dt": _parse_datetime(_get_text(item, "opengDt")),
            "ntce_kind_nm": _get_text(item, "ntceKindNm"),
            "bid_methd_nm": _get_text(item, "bidMethdNm"),
            "cntrct_mthd_nm": _get_text(item, "cntrctMthdNm"),
            "category": category,
            "raw_data": raw_data,
        }

    return _mapper


async def _gather_ranges(
    api_url: str,
    start_date: str,
    end_date: str,
    num_of_rows: int,
    mapper: Callable[[ET.Element, dict[str, str]], dict[str, Any]],
    error_label: str,
) -> list[dict[str, Any]]:
    date_ranges = split_date_range(start_date, end_date)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient() as client:

        async def _limited(step_start: str, step_end: str):
            async with sem:
                return await _fetch_paged(
                    client, api_url, step_start, step_end, num_of_rows, mapper, error_label
                )

        results = await asyncio.gather(
            *[_limited(s, e) for s, e in date_ranges], return_exceptions=True
        )

    all_items: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("%s 구간 수집 실패: %s", error_label, result)
            continue
        all_items.extend(result)
    return all_items


async def fetch_bid_data(
    start_date: str, end_date: str, num_of_rows: int = 999, category: str = "Thng"
) -> list[dict[str, Any]]:
    """조달청 낙찰정보를 비동기 병렬 수집합니다."""
    return await _gather_ranges(
        _resolve_bid_url(category),
        start_date,
        end_date,
        num_of_rows,
        _map_result_item(category),
        "낙찰정보",
    )


async def fetch_bid_announcements(
    start_date: str, end_date: str, num_of_rows: int = 999, category: str = "Thng"
) -> list[dict[str, Any]]:
    """조달청 입찰공고를 비동기 병렬 수집합니다."""
    return await _gather_ranges(
        _resolve_announce_url(category),
        start_date,
        end_date,
        num_of_rows,
        _map_announcement_item(category),
        "입찰공고",
    )
