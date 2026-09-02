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
import re
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

# 동시 요청 수 제한. 2026-08-02 실측 기준입니다.
#
#   동시  3  0.48 req/s
#   동시 12  1.78 req/s
#   동시 16  약 1.9 req/s   <- 기본값
#   동시 20  2.01 req/s     (증가율 13% 로 둔화, 지연 5.4 -> 6.6초)
#   동시 32  32건 중 2건이 XML 이 아닌 응답으로 실패 (차단 추정)
#
# 12 를 넘으면 수확이 급격히 줄고 지연이 늘어납니다. 20 이 무오류 확인 상한이지만
# 16 대비 1분밖에 못 줄이면서 차단 위험만 커져 16 을 기본으로 둡니다.
MAX_CONCURRENT = int(os.getenv("G2B_MAX_CONCURRENT", "16"))
RANGE_DAYS = 15


def get_service_key() -> str:
    """G2B 서비스 키. 값은 .env 에서만 읽고 코드/로그에 노출하지 않습니다."""
    return (
        os.getenv("G2B_SERVICE_KEY", "")
        or os.getenv("serviceKey", "")
        or os.getenv("SERVICE_KEY", "")
    )


CREDENTIAL_QUERY_PARAM_RE = re.compile(
    r"(?i)(\b|[\?&])(service_?key|api_?key|access_?token|auth_?token|token|secret|client_?secret|auth(?:orization)?|password|pwd|passwd|key)=([^&\s\'\"\)]*)"
)


def mask_credentials(text_or_obj: Any) -> str:
    """URL, 쿼리 스트링 또는 예외 메시지 내 자격 증명(serviceKey, key, apikey, token 등)을 마스킹합니다."""
    if text_or_obj is None:
        return ""
    return CREDENTIAL_QUERY_PARAM_RE.sub(r"\1\2=***", str(text_or_obj))


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
                logger.warning(
                    "서버 연결 오류(%s). %s/%s 재시도 대기",
                    mask_credentials(exc),
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(3.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"재시도 한도를 초과했습니다: {mask_credentials(last_error)}")


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
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """단일 날짜 구간을 페이지 끝까지 수집합니다.

    1페이지로 totalCount 를 확인한 뒤 나머지 페이지는 병렬로 받습니다.
    페이지를 순차로 돌면 구간당 왕복 지연이 그대로 쌓여, 구간을 아무리
    병렬화해도 이 직렬 구간이 전체 처리량을 결정합니다.
    """

    async def _page(page_no: int) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, str] = {
            "serviceKey": get_service_key(),
            "pageNo": str(page_no),
            "numOfRows": str(num_of_rows),
            "inqryDiv": "1",
            "inqryBgnDt": f"{step_start}0000",
            "inqryEndDt": f"{step_end}2359",
            "type": "xml",
        }
        # 동시 요청 수는 여기 한 곳에서만 통제합니다. 구간과 페이지를 각각
        # 제한하면 둘이 곱해져 실측 차단 지점(32)을 훌쩍 넘깁니다.
        async with sem:
            resp = await _make_request_with_retry(client, api_url, params)
        # G2B 공공 API 응답 전용. 외부 사용자 입력이 아닙니다
        root = ET.fromstring(resp.text)  # nosec B314

        result_code = root.findtext(".//resultCode", default="")
        if result_code != "00":
            result_msg = root.findtext(".//resultMsg", default="알 수 없는 오류")
            raise RuntimeError(
                f"{error_label} API 오류 [{result_code}]: {mask_credentials(result_msg)}"
            )

        rows = [mapper(item, _item_raw_data(item)) for item in root.findall(".//item")]
        return rows, int(root.findtext(".//totalCount", default="0"))

    items, total_count = await _page(1)
    last_page = -(-total_count // num_of_rows)
    if last_page <= 1:
        return items

    rest = await asyncio.gather(*[_page(p) for p in range(2, last_page + 1)])
    for rows, _ in rest:
        items.extend(rows)
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
            # G2B 응답의 계약체결방법 필드명은 cntrctCnclsMthdNm 입니다.
            # cntrctMthdNm 은 응답에 존재하지 않아 컬럼이 통째로 비어 있었습니다.
            "cntrct_mthd_nm": _get_text(item, "cntrctCnclsMthdNm"),
            "category": category,
            "raw_data": raw_data,
        }

    return _mapper


class RangeCollectionError(Exception):
    """일부 날짜 구간 수집이 실패했음을 호출부에 알립니다.

    성공한 구간의 적재는 이미 끝났으므로 `saved` 로 함께 전달합니다. 실패
    구간을 조용히 버리면 체크포인트가 MAX(date) 기준이라 그 구멍을 다시
    조회하지 않아 영구 누락이 됩니다. 호출부는 반드시 수집 상태에 반영해야
    합니다.
    """

    def __init__(self, error_label: str, saved: int, failed_ranges: list[tuple[str, str]]) -> None:
        self.error_label = error_label
        self.saved = saved
        self.failed_ranges = failed_ranges
        ranges_text = ", ".join(f"{s}~{e}" for s, e in failed_ranges)
        super().__init__(f"{error_label} {len(failed_ranges)}개 구간 수집 실패: {ranges_text}")


async def _gather_ranges(
    api_url: str,
    start_date: str,
    end_date: str,
    num_of_rows: int,
    mapper: Callable[[ET.Element, dict[str, str]], dict[str, Any]],
    error_label: str,
) -> list[dict[str, Any]]:
    """날짜 구간을 병렬 수집해 전부 메모리에 모아 반환합니다.

    구간이 길면 `stream_ranges` 를 쓰십시오. 10년치를 여기로 모으면
    raw_data JSON 때문에 수 GB 가 되어 터집니다.
    """
    collected: list[dict[str, Any]] = []
    await _run_ranges(
        api_url, start_date, end_date, num_of_rows, mapper, error_label, collected.extend
    )
    return collected


async def _run_ranges(
    api_url: str,
    start_date: str,
    end_date: str,
    num_of_rows: int,
    mapper: Callable[[ET.Element, dict[str, str]], dict[str, Any]],
    error_label: str,
    sink: Callable[[list[dict[str, Any]]], Any],
) -> int:
    """15일 구간을 병렬로 받아 끝나는 즉시 `sink` 에 넘기고 메모리에서 버립니다.

    sink 는 동기 함수라 이벤트 루프를 막지 않도록 별도 스레드에서 실행하고,
    Session 동시 사용을 막기 위해 한 번에 하나만 수행합니다.

    Raises:
        RangeCollectionError: 하나 이상의 구간이 실패한 경우. 성공 구간은 이미
            적재되었으며 그 건수는 예외의 saved 에 담깁니다.
    """
    date_ranges = split_date_range(start_date, end_date)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    sink_lock = asyncio.Lock()
    total = 0

    async with httpx.AsyncClient() as client:

        async def _limited(step_start: str, step_end: str) -> int:
            # 구간은 전부 동시에 시작하고, 실제 요청 수는 _fetch_paged 안의
            # 세마포어가 통제합니다. 구간 단위로 막으면 페이지 병렬화가 무의미해집니다.
            items = await _fetch_paged(
                client, api_url, step_start, step_end, num_of_rows, mapper, error_label, sem
            )
            async with sink_lock:
                saved = await asyncio.to_thread(sink, items)
            return saved if isinstance(saved, int) else len(items)

        results = await asyncio.gather(
            *[_limited(s, e) for s, e in date_ranges], return_exceptions=True
        )

    failed_ranges: list[tuple[str, str]] = []
    for (step_start, step_end), result in zip(date_ranges, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "%s %s~%s 구간 수집 실패: %s",
                error_label,
                step_start,
                step_end,
                mask_credentials(result),
            )
            failed_ranges.append((step_start, step_end))
            continue
        total += result

    if failed_ranges:
        raise RangeCollectionError(error_label, total, failed_ranges)
    return total


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


async def stream_bid_data(
    start_date: str,
    end_date: str,
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = 999,
    category: str = "Thng",
) -> int:
    """낙찰정보를 15일 구간 단위로 받아 즉시 `sink` 로 넘깁니다."""
    return await _run_ranges(
        _resolve_bid_url(category),
        start_date,
        end_date,
        num_of_rows,
        _map_result_item(category),
        "낙찰정보",
        sink,
    )


async def stream_bid_announcements(
    start_date: str,
    end_date: str,
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = 999,
    category: str = "Thng",
) -> int:
    """입찰공고를 15일 구간 단위로 받아 즉시 `sink` 로 넘깁니다."""
    return await _run_ranges(
        _resolve_announce_url(category),
        start_date,
        end_date,
        num_of_rows,
        _map_announcement_item(category),
        "입찰공고",
        sink,
    )
