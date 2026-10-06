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
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from src.app.models.bids import extract_business_budget, normalize_bid_ntce_ord

logger = logging.getLogger(__name__)

API_BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusThng"
BID_ANNOUNCE_API_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng"
)
BID_LICENSE_LIMIT_API_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoLicenseLimit"
)
BID_PARTICIPATION_REGION_API_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoPrtcptPsblRgn"
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

# DB BigInteger(signed 64-bit int) 범위 (-2^63 ~ 2^63 - 1)
BIGINT_MIN = -9_223_372_036_854_775_808
BIGINT_MAX = 9_223_372_036_854_775_807


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


_INVALID_XML_RAW_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_XML_CHAR_REF_RE = re.compile(r"&#(?:[xX]([0-9a-fA-F]+)|([0-9]+));")


def is_valid_xml_char(cp: int) -> bool:
    """XML 1.0 사양의 유효 문자 코드포인트인지 판별합니다.

    Char ::= #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
    """
    return (
        cp in (0x9, 0xA, 0xD)
        or (0x20 <= cp <= 0xD7FF)
        or (0xE000 <= cp <= 0xFFFD)
        or (0x10000 <= cp <= 0x10FFFF)
    )


def sanitize_xml_text(xml_text: str) -> str:
    """XML 1.0 명세에 위배되는 금지 문자 참조와 제어 문자를 살균합니다.

    조달청(G2B) OpenAPI 응답에 포함될 수 있는 &#x0; 등 유효하지 않은
    숫자 문자 참조(NCR)와 C0 제어문자를 제거하여 ElementTree.fromstring
    파싱 실패(reference to invalid character number 등)를 방지합니다.
    """
    if not xml_text:
        return xml_text

    def _replace_char_ref(match: re.Match[str]) -> str:
        hex_val, dec_val = match.groups()
        try:
            cp = int(hex_val, 16) if hex_val is not None else int(dec_val, 10)
        except ValueError:
            return ""
        if is_valid_xml_char(cp):
            return match.group(0)
        return ""

    cleaned = _XML_CHAR_REF_RE.sub(_replace_char_ref, xml_text)
    return _INVALID_XML_RAW_CHARS_RE.sub("", cleaned)


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
        root = ET.fromstring(sanitize_xml_text(resp.text))  # nosec B314

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
        bid_ntce_no = _get_text(item, "bidNtceNo", "")
        sucsf_bid_amt = _parse_amount(_get_text(item, "sucsfbidAmt"))
        if sucsf_bid_amt is not None and not (BIGINT_MIN <= sucsf_bid_amt <= BIGINT_MAX):
            logger.warning(
                "낙찰 금액이 BIGINT 범위를 초과하여 NULL 로 저장합니다: bid_ntce_no=%s, sucsf_bid_amt=%s",
                bid_ntce_no,
                sucsf_bid_amt,
            )
            sucsf_bid_amt = None

        return {
            "bid_ntce_nm": _get_text(item, "bidNtceNm"),
            "bid_ntce_no": bid_ntce_no,
            "bid_ntce_ord": _get_text(item, "bidNtceOrd", "00"),
            "bidwinnr_nm": _get_text(item, "bidwinnrNm"),
            "sucsf_bid_amt": sucsf_bid_amt,
            "sucsf_bid_rate": _parse_rate(_get_text(item, "sucsfbidRate")),
            "rl_openg_dt": _parse_datetime(_get_text(item, "rlOpengDt")),
            "dminstt_nm": _get_text(item, "dminsttNm"),
            "category": category,
            "raw_data": raw_data,
        }

    return _mapper


def _map_announcement_item(category: str):
    def _mapper(item: ET.Element, raw_data: dict[str, str]) -> dict[str, Any]:
        bid_ntce_no = _get_text(item, "bidNtceNo", "")
        base_amount = extract_business_budget(raw_data)
        if base_amount is not None and not (BIGINT_MIN <= base_amount <= BIGINT_MAX):
            logger.warning(
                "공고 기초금액이 BIGINT 범위를 초과하여 NULL 로 저장합니다: bid_ntce_no=%s, base_amount=%s",
                bid_ntce_no,
                base_amount,
            )
            base_amount = None

        presmpt_prce = _parse_amount(_get_text(item, "presmptPrce"))
        if presmpt_prce is not None and not (BIGINT_MIN <= presmpt_prce <= BIGINT_MAX):
            logger.warning(
                "공고 추정가격이 BIGINT 범위를 초과하여 NULL 로 저장합니다: bid_ntce_no=%s, presmpt_prce=%s",
                bid_ntce_no,
                presmpt_prce,
            )
            presmpt_prce = None

        return {
            "bid_ntce_nm": _get_text(item, "bidNtceNm"),
            "bid_ntce_no": bid_ntce_no,
            "bid_ntce_ord": _get_text(item, "bidNtceOrd", "000"),
            "ntce_instt_nm": _get_text(item, "ntceInsttNm"),
            "dminstt_nm": _get_text(item, "dminsttNm"),
            "base_amount": base_amount,
            "presmpt_prce": presmpt_prce,
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


def _clean_str(val: str | None) -> str | None:
    if not val:
        return None
    stripped = val.strip()
    return stripped if stripped else None


def _map_license_limit_item(item: ET.Element, raw_data: dict[str, str]) -> dict[str, Any]:
    bid_ntce_no = _clean_str(_get_text(item, "bidNtceNo")) or ""
    return {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": _clean_str(_get_text(item, "bidNtceOrd")) or "000",
        "lmt_grp_no": _clean_str(_get_text(item, "lmtGrpNo")) or "1",
        "lmt_sno": _clean_str(_get_text(item, "lmtSno")) or "1",
        "lcns_lmt_nm": _clean_str(_get_text(item, "lcnsLmtNm")),
        "permsn_indstryty_list": _clean_str(_get_text(item, "permsnIndstrytyList")),
        "indstryty_mfrc_fld_list": _clean_str(_get_text(item, "indstrytyMfrcFldList")),
        "rgst_dt": _parse_datetime(_clean_str(_get_text(item, "rgstDt"))),
        "bsns_div_nm": _clean_str(_get_text(item, "bsnsDivNm")),
    }


def _map_participation_region_item(item: ET.Element, raw_data: dict[str, str]) -> dict[str, Any]:
    bid_ntce_no = _clean_str(_get_text(item, "bidNtceNo")) or ""
    return {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": _clean_str(_get_text(item, "bidNtceOrd")) or "000",
        "lmt_sno": _clean_str(_get_text(item, "lmtSno")) or "1",
        "prtcpt_psbl_rgn_nm": _clean_str(_get_text(item, "prtcptPsblRgnNm")),
        "rgst_dt": _parse_datetime(_clean_str(_get_text(item, "rgstDt"))),
        "bsns_div_nm": _clean_str(_get_text(item, "bsnsDivNm")),
    }


async def stream_bid_license_limits(
    start_date: str,
    end_date: str,
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = 999,
) -> int:
    """면허제한정보를 15일 구간 단위로 받아 즉시 `sink` 로 넘깁니다."""
    return await _run_ranges(
        BID_LICENSE_LIMIT_API_URL,
        start_date,
        end_date,
        num_of_rows,
        _map_license_limit_item,
        "면허제한정보",
        sink,
    )


async def stream_bid_participation_regions(
    start_date: str,
    end_date: str,
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = 999,
) -> int:
    """참가가능지역을 15일 구간 단위로 받아 즉시 `sink` 로 넘깁니다."""
    return await _run_ranges(
        BID_PARTICIPATION_REGION_API_URL,
        start_date,
        end_date,
        num_of_rows,
        _map_participation_region_item,
        "참가가능지역",
        sink,
    )


# ---------------------------------------------------------------------------
# 개찰결과 예비가격 상세(용역)
#
# 낙찰정보 오퍼레이션과 같은 서비스(as/ScsbidInfoService) 소속이며 같은 키로
# 호출합니다. 다만 날짜 형식이 YYYYMMDDHHMM 이고 창 상한이 약 1개월이라
# 기존 15일 분할 경로를 재사용하지 않고 전용 창 분할을 둡니다. 기존 수집 함수의
# 동작은 바꾸지 않습니다.
# ---------------------------------------------------------------------------

PREARNG_PRICE_API_URL = (
    "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoServcPreparPcDetail"
)
PREARNG_PAGE_SIZE = 500
PREARNG_RESULT_ERROR_CODES = frozenset({"06", "07"})


class PrearngResponseError(RuntimeError):
    """예비가격 상세 응답이 오류 봉투이거나 JSON 이 아닐 때 발생합니다.

    `resultCode` 06/07 은 날짜 형식 오류·입력범위 초과라 재시도해도 실패합니다.
    `_make_request_with_retry` 는 HTTP 상태·연결 오류만 재시도하므로 이 오류는
    창 단위 실패 원장으로 곧바로 기록됩니다.
    """

    def __init__(self, result_code: str, message: str) -> None:
        self.result_code = result_code
        self.message = message
        super().__init__(f"예비가격상세 API 오류 [{result_code}]: {mask_credentials(message)}")

    @property
    def retryable(self) -> bool:
        """06/07(형식·범위 오류)은 재시도해도 실패하므로 False 입니다."""
        return self.result_code not in PREARNG_RESULT_ERROR_CODES


def _prearng_text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prearng_int(item: dict[str, Any], key: str) -> int | None:
    return _parse_amount(_prearng_text(item, key))


def map_prearng_price_row(item: dict[str, Any]) -> dict[str, Any]:
    """예비가격 상세 행 1개(후보 1개)를 평평한 dict 로 매핑합니다.

    공통 필드는 15행에 반복되지만 집약 전 단계에서는 그대로 보존합니다.
    """
    return {
        "bid_ntce_no": _prearng_text(item, "bidNtceNo") or "",
        "bid_ntce_ord": normalize_bid_ntce_ord(_prearng_text(item, "bidNtceOrd")),
        "bid_clsfc_no": _prearng_text(item, "bidClsfcNo") or "0",
        "rbid_no": _prearng_text(item, "rbidNo") or "000",
        "category": _prearng_text(item, "category") or "Servc",
        "bid_ntce_nm": _prearng_text(item, "bidNtceNm"),
        "bssamt": _prearng_int(item, "bssamt"),
        "plnprc": _prearng_int(item, "plnprc"),
        "tot_prce_num": _prearng_int(item, "totRsrvtnPrceNum"),
        "bss_up_num": _prearng_int(item, "bssamtBssUpNum"),
        "slctn_bss": _prearng_text(item, "bidwinrSlctnAplBssCntnts"),
        "sno": _prearng_int(item, "compnoRsrvtnPrceSno"),
        "bsis_plnprc": _prearng_int(item, "bsisPlnprc"),
        "drwt_yn": _prearng_text(item, "drwtYn") or "",
        "drwt_num": _prearng_int(item, "drwtNum"),
        "rl_openg_dt": _parse_datetime(_prearng_text(item, "rlOpengDt")),
        "mkng_dt": _parse_datetime(_prearng_text(item, "compnoRsrvtnPrceMkngDt")),
        "inpt_dt": _parse_datetime(_prearng_text(item, "inptDt")),
        # raw_data 는 JSON 컬럼입니다. 변환한 datetime 을 담으면 직렬화가 실패하므로
        # 응답 원문(문자열)을 그대로 보존합니다.
        "raw": dict(item),
    }


def compute_sajeong_rate(plnprc: int | None, bssamt: int | None) -> Decimal | None:
    """사정률(%) = 예정가격/기초금액*100, 소수 4자리 반올림. 계산 불가면 None."""
    if plnprc is None or bssamt is None or bssamt <= 0:
        return None
    return (Decimal(plnprc) / Decimal(bssamt) * Decimal(100)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _prearng_sno_key(candidate: dict[str, Any]) -> tuple[bool, int]:
    """순번 없는 후보를 맨 뒤로 보내는 정렬 키."""
    sno = candidate.get("sno")
    return (sno is None, int(sno) if sno is not None else 0)


def aggregate_prearng_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """공고당 15행을 1행으로 집약합니다.

    복합키(공고번호+차수+분류+재입찰번호+업무구분)로 묶어 공통 필드는 첫 행에서,
    후보 15개는 JSON `items` 로, 추첨 건수는 `drwtYn=Y` 개수로 만듭니다.
    """
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        bid_ntce_no = row.get("bid_ntce_no")
        if not bid_ntce_no:
            continue
        key = (
            str(bid_ntce_no),
            str(row.get("bid_ntce_ord") or "000"),
            str(row.get("bid_clsfc_no") or "0"),
            str(row.get("rbid_no") or "000"),
            str(row.get("category") or "Servc"),
        )
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    aggregated: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        first = group[0]
        ordered = sorted(group, key=_prearng_sno_key)
        aggregated.append(
            {
                "bid_ntce_no": key[0],
                "bid_ntce_ord": key[1],
                "bid_clsfc_no": key[2],
                "rbid_no": key[3],
                "category": key[4],
                "bid_ntce_nm": first.get("bid_ntce_nm"),
                "bssamt": first.get("bssamt"),
                "plnprc": first.get("plnprc"),
                "sajeong_rate": compute_sajeong_rate(first.get("plnprc"), first.get("bssamt")),
                "tot_prce_num": first.get("tot_prce_num"),
                "drwt_prce_num": sum(1 for row in group if row.get("drwt_yn") == "Y"),
                "bss_up_num": first.get("bss_up_num"),
                "slctn_bss": first.get("slctn_bss"),
                "items": [
                    {
                        "sno": row.get("sno"),
                        "bsis_plnprc": row.get("bsis_plnprc"),
                        "drwt_yn": row.get("drwt_yn") or "",
                        "drwt_num": row.get("drwt_num"),
                    }
                    for row in ordered
                ],
                "rl_openg_dt": first.get("rl_openg_dt"),
                "mkng_dt": first.get("mkng_dt"),
                "inpt_dt": first.get("inpt_dt"),
                "raw_data": [row.get("raw") or {} for row in group],
            }
        )
    return aggregated


def _parse_month(value: str) -> date:
    text = str(value or "").strip()
    for fmt in ("%Y-%m", "%Y%m"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"월 형식이 올바르지 않습니다(YYYY-MM 필요): {value!r}")


def _next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def split_prearng_month_windows(start_month: str, end_month: str) -> list[tuple[str, str]]:
    """YYYY-MM 구간을 달력 월 단위 (bgn, end) 창으로 쪼갭니다.

    API 창 상한이 약 1개월이라 달력 월로 자릅니다. 날짜 파라미터는
    YYYYMMDDHHMM 형식이며 시작은 1일 00:00, 끝은 말일 23:59 입니다.
    """
    start = _parse_month(start_month)
    end = _parse_month(end_month)
    if start > end:
        raise ValueError("--start 가 --end 보다 늦습니다")
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        window_end = _next_month(cursor) - timedelta(days=1)
        windows.append(
            (
                f"{cursor.strftime('%Y%m%d')}0000",
                f"{window_end.strftime('%Y%m%d')}2359",
            )
        )
        cursor = _next_month(cursor)
    return windows


def _parse_prearng_payload(payload: Any) -> tuple[list[dict[str, Any]], int]:
    """응답 JSON 에서 항목 목록과 totalCount 를 꺼냅니다.

    오류 봉투가 두 종류입니다. 게이트웨이는 `nkoneps.com.response.ResponseError`,
    정상 봉투는 `response.header.resultCode != '00'` 입니다. 둘 다 검사합니다.
    """
    if not isinstance(payload, dict):
        raise PrearngResponseError("", "예비가격상세 응답이 JSON 객체가 아닙니다")

    gateway = payload.get("nkoneps.com.response.ResponseError")
    if isinstance(gateway, dict):
        header = gateway.get("header") or {}
        raise PrearngResponseError(
            str(header.get("resultCode") or ""),
            str(header.get("resultMsg") or "게이트웨이 오류"),
        )

    response = payload.get("response")
    if isinstance(response, dict):
        header = response.get("header") or {}
        body = response.get("body") or {}
    else:
        header = payload.get("header") or {}
        body = payload.get("body") if isinstance(payload.get("body"), dict) else payload

    code = str(header.get("resultCode") or "")
    if code and code != "00":
        raise PrearngResponseError(code, str(header.get("resultMsg") or ""))

    total_raw = body.get("totalCount")
    try:
        total_count = int(total_raw) if total_raw not in (None, "") else 0
    except (TypeError, ValueError):
        total_count = 0

    raw_items = body.get("items")
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("item", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        raw_items = []
    return [entry for entry in raw_items if isinstance(entry, dict)], total_count


async def fetch_prearng_page(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    page_no: int,
    num_of_rows: int = PREARNG_PAGE_SIZE,
    inqry_div: str = "1",
    inqry_bgn_dt: str | None = None,
    inqry_end_dt: str | None = None,
    bid_ntce_no: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """예비가격 상세 한 페이지를 요청해 행별 매핑 결과와 totalCount 를 돌려줍니다."""
    params: dict[str, str] = {
        "serviceKey": get_service_key(),
        "pageNo": str(page_no),
        "numOfRows": str(num_of_rows),
        "inqryDiv": inqry_div,
        "type": "json",
    }
    if inqry_bgn_dt is not None:
        params["inqryBgnDt"] = inqry_bgn_dt
    if inqry_end_dt is not None:
        params["inqryEndDt"] = inqry_end_dt
    if bid_ntce_no is not None:
        params["bidNtceNo"] = bid_ntce_no

    async with sem:
        resp = await _make_request_with_retry(client, PREARNG_PRICE_API_URL, params)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise PrearngResponseError("", f"응답 JSON 파싱 실패: {exc}") from exc

    raw_items, total_count = _parse_prearng_payload(payload)
    rows = [map_prearng_price_row(entry) for entry in raw_items]
    return rows, total_count


async def _fetch_prearng_window(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    inqry_bgn_dt: str,
    inqry_end_dt: str,
    num_of_rows: int,
) -> list[dict[str, Any]]:
    """한 달 창을 페이지 끝까지 받아 공고당 1행으로 집약합니다."""
    rows, total_count = await fetch_prearng_page(
        client,
        sem,
        page_no=1,
        num_of_rows=num_of_rows,
        inqry_div="1",
        inqry_bgn_dt=inqry_bgn_dt,
        inqry_end_dt=inqry_end_dt,
    )
    last_page = -(-total_count // num_of_rows) if num_of_rows else 1
    if last_page > 1:
        rest = await asyncio.gather(
            *[
                fetch_prearng_page(
                    client,
                    sem,
                    page_no=page,
                    num_of_rows=num_of_rows,
                    inqry_div="1",
                    inqry_bgn_dt=inqry_bgn_dt,
                    inqry_end_dt=inqry_end_dt,
                )
                for page in range(2, last_page + 1)
            ]
        )
        for page_rows, _ in rest:
            rows.extend(page_rows)
    return aggregate_prearng_prices(rows)


async def _fetch_prearng_notice(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    bid_ntce_no: str,
    num_of_rows: int,
) -> list[dict[str, Any]]:
    """공고번호 단건(inqryDiv=2)을 페이지 끝까지 받아 1행으로 집약합니다."""
    rows, total_count = await fetch_prearng_page(
        client,
        sem,
        page_no=1,
        num_of_rows=num_of_rows,
        inqry_div="2",
        bid_ntce_no=bid_ntce_no,
    )
    last_page = -(-total_count // num_of_rows) if num_of_rows else 1
    if last_page > 1:
        rest = await asyncio.gather(
            *[
                fetch_prearng_page(
                    client,
                    sem,
                    page_no=page,
                    num_of_rows=num_of_rows,
                    inqry_div="2",
                    bid_ntce_no=bid_ntce_no,
                )
                for page in range(2, last_page + 1)
            ]
        )
        for page_rows, _ in rest:
            rows.extend(page_rows)
    return aggregate_prearng_prices(rows)


async def stream_servc_prearng_range(
    start_month: str,
    end_month: str,
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = PREARNG_PAGE_SIZE,
) -> int:
    """과거 창을 달력 월 단위로 열거해 공고당 1행을 `sink` 로 넘깁니다.

    소급 수집 전용입니다. 한 창이 실패해도 성공 창은 이미 적재되었으며,
    실패 창은 `RangeCollectionError.failed_ranges` 로 원장에 기록됩니다.
    """
    windows = split_prearng_month_windows(start_month, end_month)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    sink_lock = asyncio.Lock()
    total = 0

    async with httpx.AsyncClient() as client:

        async def _limited(bgn: str, end: str) -> int:
            rows = await _fetch_prearng_window(client, sem, bgn, end, num_of_rows)
            if not rows:
                return 0
            async with sink_lock:
                saved = await asyncio.to_thread(sink, rows)
            return saved if isinstance(saved, int) else len(rows)

        results = await asyncio.gather(
            *[_limited(bgn, end) for bgn, end in windows], return_exceptions=True
        )

    failed_windows: list[tuple[str, str]] = []
    for (bgn, end), result in zip(windows, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "예비가격상세 %s~%s 창 수집 실패: %s",
                bgn,
                end,
                mask_credentials(result),
            )
            failed_windows.append((bgn, end))
            continue
        total += result

    if failed_windows:
        raise RangeCollectionError("예비가격상세", total, failed_windows)
    return total


async def stream_servc_prearng_by_notices(
    notices: Iterable[str],
    sink: Callable[[list[dict[str, Any]]], Any],
    num_of_rows: int = PREARNG_PAGE_SIZE,
) -> int:
    """신규 용역 공고를 공고번호 단건(inqryDiv=2)으로 1콜씩 수집합니다.

    일일 증분 경로입니다. 실패한 공고번호는 `RangeCollectionError.failed_ranges`
    에 (공고번호, 공고번호) 쌍으로 남겨 수동 재수집 근거로 삼습니다.
    """
    notice_list = [str(notice).strip() for notice in notices if str(notice).strip()]
    if not notice_list:
        return 0

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    sink_lock = asyncio.Lock()
    total = 0

    async with httpx.AsyncClient() as client:

        async def _one(bid_ntce_no: str) -> int:
            rows = await _fetch_prearng_notice(client, sem, bid_ntce_no, num_of_rows)
            if not rows:
                return 0
            async with sink_lock:
                saved = await asyncio.to_thread(sink, rows)
            return saved if isinstance(saved, int) else len(rows)

        results = await asyncio.gather(
            *[_one(notice) for notice in notice_list], return_exceptions=True
        )

    failed_notices: list[tuple[str, str]] = []
    for bid_ntce_no, result in zip(notice_list, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "예비가격상세 공고 %s 수집 실패: %s",
                bid_ntce_no,
                mask_credentials(result),
            )
            failed_notices.append((bid_ntce_no, bid_ntce_no))
            continue
        total += result

    if failed_notices:
        raise RangeCollectionError("예비가격상세", total, failed_notices)
    return total


async def fetch_servc_prearng_detail(
    bid_ntce_no: str, num_of_rows: int = PREARNG_PAGE_SIZE
) -> list[dict[str, Any]]:
    """공고번호 단건으로 예비가격 상세를 조회해 공고당 1행으로 집약합니다."""
    sem = asyncio.Semaphore(1)
    async with httpx.AsyncClient() as client:
        return await _fetch_prearng_notice(client, sem, bid_ntce_no, num_of_rows)
