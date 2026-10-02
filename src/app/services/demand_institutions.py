"""나라장터 사용자정보 서비스 수요기관 수집과 법령 판별."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.services.evaluation_rules import extract_contract_regime

logger = logging.getLogger(__name__)
API_URL = "https://apis.data.go.kr/1230000/ao/UsrInfoService02/getDminsttInfo02"
REQUEST_INTERVAL_SECONDS = 0.2
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 16


class DemandInstitutionCollectionError(RuntimeError):
    pass


def split_year_ranges(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        raise ValueError("start 가 end 보다 늦습니다.")
    result = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=364), end)
        result.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return result


def parse_changed_at(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    formats = (("%Y%m%d%H%M%S",) if len(text) == 14 else ("%Y%m%d%H%M",)) + (
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_response(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise DemandInstitutionCollectionError("응답 JSON 구조가 올바르지 않습니다.")
    if "OpenAPI_ServiceResponse" in payload:
        detail = payload["OpenAPI_ServiceResponse"]
        header = detail.get("cmmMsgHeader", {}) if isinstance(detail, dict) else {}
        raise DemandInstitutionCollectionError(
            "나라장터 오류 응답: "
            f"resultCode={header.get('returnAuthMsg', '')}, "
            f"returnReasonCode={header.get('returnReasonCode', '')}, "
            f"errMsg={header.get('errMsg', '')}"
        )
    if "nkoneps.com.response.ResponseError" in payload:
        detail = payload["nkoneps.com.response.ResponseError"]
        header = detail.get("header", {}) if isinstance(detail, dict) else {}
        raise DemandInstitutionCollectionError(
            "나라장터 오류 응답: "
            f"resultCode={header.get('resultCode', '')}, "
            f"returnReasonCode={header.get('returnReasonCode', '')}, "
            f"errMsg={header.get('errMsg', '')}"
        )
    response = payload.get("response")
    if not isinstance(response, dict):
        raise DemandInstitutionCollectionError("나라장터 response 가 없습니다.")
    header = response.get("header") or {}
    if str(header.get("resultCode", "")) != "00":
        raise DemandInstitutionCollectionError(
            "나라장터 응답 오류: "
            f"resultCode={header.get('resultCode', '')}, "
            f"returnReasonCode={header.get('returnReasonCode', '')}, "
            f"errMsg={header.get('errMsg', header.get('resultMsg', ''))}"
        )
    body = response.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise DemandInstitutionCollectionError("나라장터 items 구조가 올바르지 않습니다.")
    return [item for item in items if isinstance(item, dict)], int(body.get("totalCount") or 0)


def _throttle_reason(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("OpenAPI_ServiceResponse")
    if isinstance(detail, dict):
        header = detail.get("cmmMsgHeader", {})
        if isinstance(header, dict):
            reason = str(header.get("returnReasonCode", ""))
            if reason == "23":
                return reason
    error = payload.get("nkoneps.com.response.ResponseError")
    if isinstance(error, dict):
        header = error.get("header", {})
        if isinstance(header, dict) and str(header.get("returnReasonCode", "")) == "23":
            return "23"
    return None


async def _get_with_retry(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    attempts: int = MAX_RETRY_ATTEMPTS,
):
    for attempt in range(attempts):
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            response = await client.get(API_URL, params=params, timeout=120)
            reason = _throttle_reason(response)
            if response.status_code == 429 or reason == "23":
                if attempt + 1 == attempts:
                    return response
                await asyncio.sleep(min(2**attempt, MAX_BACKOFF_SECONDS))
                continue
            response.raise_for_status()
            return response
        except (httpx.HTTPError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(min(2**attempt, MAX_BACKOFF_SECONDS))
    raise AssertionError("unreachable")


async def collect_demand_institutions(
    client: httpx.AsyncClient,
    service_key: str,
    start: date,
    end: date,
    inqry_div: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for range_start, range_end in split_year_ranges(start, end):
        page = 1
        total_count = 1
        while (page - 1) * 999 < total_count:
            params = {
                "serviceKey": service_key,
                "numOfRows": 999,
                "pageNo": page,
                "type": "json",
                "inqryDiv": inqry_div,
                "inqryBgnDt": datetime.combine(range_start, time.min).strftime("%Y%m%d%H%M"),
                "inqryEndDt": datetime.combine(range_end, time.max).strftime("%Y%m%d%H%M"),
            }
            try:
                response = await _get_with_retry(client, params)
                response.raise_for_status()
                items, total_count = parse_response(response.json())
            except DemandInstitutionCollectionError:
                raise
            except httpx.HTTPStatusError as exc:
                reason = _throttle_reason(exc.response) or ""
                error_message = ""
                try:
                    payload = exc.response.json()
                except (ValueError, TypeError):
                    payload = {}
                if isinstance(payload, dict):
                    detail = payload.get("OpenAPI_ServiceResponse", {})
                    header = detail.get("cmmMsgHeader", {}) if isinstance(detail, dict) else {}
                    error_message = (
                        str(header.get("errMsg", "")) if isinstance(header, dict) else ""
                    )
                raise DemandInstitutionCollectionError(
                    "수요기관 API 조회 실패: "
                    f"HTTP {exc.response.status_code}, returnReasonCode={reason}, "
                    f"errMsg={error_message}"
                ) from exc
            except (httpx.HTTPError, TimeoutError, ValueError) as exc:
                detail = str(exc).replace(str(params["serviceKey"]), "[redacted]")
                raise DemandInstitutionCollectionError(
                    f"수요기관 API 조회 실패: {type(exc).__name__}: {detail}"
                ) from exc
            rows.extend(items)
            page += 1
    return rows


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def classify_contract_regime(
    institution: G2BDemandInstitution | dict[str, Any] | None,
) -> str | None:
    if institution is None:
        return None
    jurisdiction = _institution_value(institution, "jrsdctn_div_nm", "jrsdctnDivNm")
    large = _institution_value(institution, "instt_ty_lrgclsfc_nm", "insttTyCdLrgclsfcNm")
    middle = (
        _institution_value(institution, "instt_ty_midclsfc_nm", "insttTyCdMidclsfcNm") or ""
    ).strip()
    small = (
        _institution_value(institution, "instt_ty_smlclsfc_nm", "insttTyCdSmlclsfcNm") or ""
    ).strip()
    if large == "교육행정조직" and middle in {
        "시, 도교육청",
        "지역교육청",
        "시, 도교육청 직속기관",
    }:
        return "LOCAL"
    if jurisdiction in {"지방자치단체", "지방공기업"}:
        return "LOCAL"
    if large in {"초등학교", "중학교", "고등학교", "특수학교", "유치원"} and small == "공립":
        return "LOCAL"
    if jurisdiction in {"국가기관", "공기업", "준정부기관", "정부투자기관"}:
        return "NATIONAL"
    return None


def institution_region(
    institution: G2BDemandInstitution | dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if institution is None:
        return None, None
    return (
        _institution_value(institution, "rgn_cd", "rgnCd"),
        _institution_value(institution, "rgn_nm", "rgnNm"),
    )


def describe_contract_regime(
    raw_data: dict[str, Any] | None,
    cntrct_mthd_nm: str | None,
    institution: G2BDemandInstitution | dict[str, Any] | None,
) -> dict[str, str | None]:
    """공고 판정과 그 근거, 복수예가 범위를 화면/API 공용 설명으로 만듭니다."""
    data = raw_data if isinstance(raw_data, dict) else {}
    institution_regime = classify_contract_regime(institution)
    regime = extract_contract_regime(data, cntrct_mthd_nm, institution_regime)
    methods = f"{data.get('cntrctCnclsMthdNm') or ''} {cntrct_mthd_nm or ''}"
    jurisdiction = (
        _institution_value(institution, "jrsdctn_div_nm", "jrsdctnDivNm")
        if institution is not None
        else None
    )
    if regime == "LOCAL" and "지방" in methods:
        basis = "METHOD_NAME"
        basis_text = "계약방법명에 지방 표기"
    elif regime is not None and institution_regime == regime:
        basis = "INSTITUTION"
        basis_text = f"수요기관 소관구분: {jurisdiction}" if jurisdiction else "수요기관 기준정보"
    else:
        basis = None
        basis_text = None
    if regime == "LOCAL":
        label = "지방계약"
    elif regime == "NATIONAL":
        label = "국가계약"
    else:
        label = "계약 법령 미상"
    range_rate_label = (
        "±3%" if regime == "LOCAL" else "±2%" if regime == "NATIONAL" else "±2% (기본값, 법령 미상)"
    )
    return {
        "regime": regime,
        "label": label,
        "basis": basis,
        "basis_text": basis_text,
        "jurisdiction": jurisdiction,
        "range_rate_label": range_rate_label,
    }


def _institution_value(
    institution: G2BDemandInstitution | dict[str, Any], column: str, api_key: str
) -> str | None:
    value = (
        institution.get(column, institution.get(api_key))
        if isinstance(institution, dict)
        else getattr(institution, column, None)
    )
    return _clean(value)


def to_model_values(item: dict[str, Any]) -> dict[str, Any] | None:
    code = _clean(item.get("dminsttCd"))
    if not code:
        return None
    return {
        "dminstt_cd": code,
        "dminstt_nm": _clean(item.get("dminsttNm")),
        "jrsdctn_div_nm": _clean(item.get("jrsdctnDivNm")),
        "instt_ty_lrgclsfc_nm": _clean(item.get("insttTyCdLrgclsfcNm")),
        "instt_ty_midclsfc_nm": _clean(item.get("insttTyCdMidclsfcNm")),
        "instt_ty_smlclsfc_nm": _clean(item.get("insttTyCdSmlclsfcNm")),
        "rgn_cd": _clean(item.get("rgnCd")),
        "rgn_nm": _clean(item.get("rgnNm")),
        "toplvl_instt_cd": _clean(item.get("toplvlInsttCd")),
        "toplvl_instt_nm": _clean(item.get("toplvlInsttNm")),
        "dlt_yn": _clean(item.get("dltYn")),
        "rgst_dt": _clean(item.get("rgstDt")),
        "chg_dt": parse_changed_at(item.get("chgDt")),
        "raw_json": item,
        "fetched_at": utcnow(),
    }


def upsert_demand_institutions(db: Session, items: list[dict[str, Any]]) -> int:
    upserted = 0
    for item in items:
        values = to_model_values(item)
        if values is None:
            continue
        row = db.get(G2BDemandInstitution, values["dminstt_cd"])
        if row is None:
            row = G2BDemandInstitution(**values)
            db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        upserted += 1
    db.commit()
    return upserted


def incremental_start(db: Session) -> date:
    max_change = db.scalar(select(func.max(G2BDemandInstitution.chg_dt)))
    return max_change.date() - timedelta(days=1) if max_change else date(1950, 1, 1)


async def collect_and_upsert(
    db: Session,
    service_key: str,
    mode: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    if mode not in {"full", "incremental"}:
        raise ValueError("mode 는 full 또는 incremental 이어야 합니다.")
    today = date.today()
    start = date(1950, 1, 1) if mode == "full" else incremental_start(db)
    inqry_div = 1 if mode == "full" else 2
    async with httpx.AsyncClient() as client:
        items = await collect_demand_institutions(client, service_key, start, today, inqry_div)
    distribution: dict[str, int] = {}
    for item in items:
        jurisdiction = _clean(item.get("jrsdctnDivNm")) or "(빈 값)"
        distribution[jurisdiction] = distribution.get(jurisdiction, 0) + 1
    upserted = 0 if dry_run else upsert_demand_institutions(db, items)
    return {
        "mode": mode,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "collected_count": len(items),
        "upserted_count": upserted,
        "jurisdiction_distribution": distribution,
    }
