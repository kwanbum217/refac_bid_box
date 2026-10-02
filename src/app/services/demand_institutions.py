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

logger = logging.getLogger(__name__)
API_URL = "https://apis.data.go.kr/1230000/ao/UsrInfoService02/getDminsttInfo02"


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
    if "nkoneps.com.response.ResponseError" in payload:
        detail = payload["nkoneps.com.response.ResponseError"]
        raise DemandInstitutionCollectionError(f"나라장터 오류 응답: {detail}")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise DemandInstitutionCollectionError("나라장터 response 가 없습니다.")
    header = response.get("header") or {}
    if str(header.get("resultCode", "")) != "00":
        raise DemandInstitutionCollectionError(f"나라장터 응답 오류: {header.get('resultMsg', '')}")
    body = response.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise DemandInstitutionCollectionError("나라장터 items 구조가 올바르지 않습니다.")
    return [item for item in items if isinstance(item, dict)], int(body.get("totalCount") or 0)


async def _get_with_retry(client: httpx.AsyncClient, params: dict[str, Any], attempts: int = 5):
    for attempt in range(attempts):
        try:
            response = await client.get(API_URL, params=params, timeout=120)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(min(2**attempt, 16))
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
                items, total_count = parse_response(response.json())
            except Exception:
                raise DemandInstitutionCollectionError(
                    "수요기관 API 조회에 실패했습니다."
                ) from None
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


def incremental_start(db: Session, today: date | None = None) -> date:
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
