"""
src/app/api/v1/bids.py

입찰공고/낙찰결과 API (원본 apps/bids/urls.py 8개 라우트 1:1 대응).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `bids:bid_list` | `GET /api/v1/bids` |
| `bids:result_list` | `GET /api/v1/bids/results` |
| `bids:bid_detail` | `GET /api/v1/bids/{pk}` |
| `bids:result_detail` | `GET /api/v1/bids/results/{pk}` |
| `bids:api_stats` | `GET /api/v1/bids/stats` |
| `bids:api_compare_stats` | `GET /api/v1/bids/compare-stats` |
| `index` (홈 컨텍스트) | `GET /api/v1/bids/home` |
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import require_current_user
from src.app.core.db import get_db
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.schemas.bids import (
    BidDetailResponse,
    BidListResponse,
    BidResultDetailResponse,
    BidResultListResponse,
    HomeContextResponse,
)
from src.app.services import bid_queries
from src.app.services.dashboard import get_compare_stats_data, get_dashboard_stats
from src.app.services.home_context import (
    DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
    get_home_page_context,
)
from src.app.services.search_index import SearchBackendUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bids", tags=["Bids"])


def _serialize_announcement(bid: BidAnnouncement) -> dict[str, Any]:
    return {
        "id": bid.id,
        "bid_ntce_no": bid.bid_ntce_no,
        "bid_ntce_ord": bid.bid_ntce_ord or "000",
        "bid_ntce_nm": bid.bid_ntce_nm,
        "dminstt_nm": bid.dminstt_nm,
        "ntce_instt_nm": bid.ntce_instt_nm,
        "category": bid.category,
        "base_amount": bid.base_amount,
        "presmpt_prce": bid.presmpt_prce,
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
        "ntce_kind_nm": bid.ntce_kind_nm,
        "bid_methd_nm": bid.bid_methd_nm,
        "cntrct_mthd_nm": bid.cntrct_mthd_nm,
        "collected_at": bid.collected_at,
        "category_label": bid.category_label,
        "resolved_base_amount": bid.resolved_base_amount,
        "has_base_amount": bid.has_base_amount,
        "prediction_reference_amount": bid.prediction_reference_amount,
    }


def _serialize_result(db: Session, result: BidResult) -> dict[str, Any]:
    winning_rate = result.display_winning_rate(db)
    return {
        "id": result.id,
        "bid_ntce_no": result.bid_ntce_no,
        "bid_ntce_ord": result.bid_ntce_ord or "00",
        "bid_ntce_nm": result.bid_ntce_nm,
        "bidwinnr_nm": result.bidwinnr_nm,
        "sucsf_bid_amt": result.sucsf_bid_amt,
        "sucsf_bid_rate": float(result.sucsf_bid_rate)
        if result.sucsf_bid_rate is not None
        else None,
        "rl_openg_dt": result.rl_openg_dt,
        "dminstt_nm": result.dminstt_nm,
        "category": result.category,
        "collected_at": result.collected_at,
        "category_label": result.category_label,
        "display_bid_ntce_nm": result.display_bid_ntce_nm,
        "display_dminstt_nm": result.display_dminstt_nm,
        "display_bidwinnr_nm": result.display_bidwinnr_nm,
        "has_corrupted_display_text": result.has_corrupted_display_text,
        "display_winning_rate": float(winning_rate) if winning_rate is not None else None,
    }


@router.get("", response_model=BidListResponse, summary="입찰공고 목록")
def list_bids(
    q: str = Query("", description="공고명/공고번호/수요기관명 검색어"),
    cat: str = Query("", description="업무구분 코드 (Thng/Servc/Cnstwk/Frgcpt)"),
    region: str = Query("", description="지역 코드"),
    sort: str = Query(
        bid_queries.DEFAULT_BID_LIST_SORT, description="정렬 키 (notice/deadline/amount/region)"
    ),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    try:
        page_obj = bid_queries.list_announcements(
            db, q=q, cat=cat, region=region, sort=sort, page=page
        )
    except SearchBackendUnavailable as exc:
        logger.exception("공고 목록 검색 백엔드 실패")
        raise HTTPException(
            status_code=503,
            detail="공고 검색 인덱스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    return BidListResponse(
        bids=[_serialize_announcement(bid) for bid in page_obj.object_list],
        page_obj=page_obj.as_dict(),
        is_paginated=page_obj.has_previous or page_obj.has_next,
        q=q or "",
        cat=cat or "",
        sort=bid_queries.normalize_bid_sort(sort),
        region=bid_queries.normalize_region_code(region),
        region_groups=bid_queries.region_groups_payload(),
    )


@router.get("/results", response_model=BidResultListResponse, summary="낙찰결과 목록")
def list_bid_results(
    q: str = Query("", description="공고명/공고번호/수요기관명/낙찰업체명 검색어"),
    cat: str = Query("", description="업무구분 코드"),
    region: str = Query("", description="지역 코드"),
    sort: str = Query(
        bid_queries.DEFAULT_RESULT_LIST_SORT, description="정렬 키 (opening/amount/rate)"
    ),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    try:
        page_obj = bid_queries.list_results(db, q=q, cat=cat, region=region, sort=sort, page=page)
    except SearchBackendUnavailable as exc:
        logger.exception("낙찰 목록 검색 백엔드 실패")
        raise HTTPException(
            status_code=503,
            detail="낙찰 검색 인덱스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    return BidResultListResponse(
        results=[_serialize_result(db, row) for row in page_obj.object_list],
        page_obj=page_obj.as_dict(),
        is_paginated=page_obj.has_previous or page_obj.has_next,
        q=q or "",
        cat=cat or "",
        sort=bid_queries.normalize_result_sort(sort),
        region=bid_queries.normalize_region_code(region),
        region_groups=bid_queries.region_groups_payload(),
    )


def _stats_error(message: str) -> JSONResponse:
    """원본 JsonResponse 오류 계약입니다.

    화면(compare.html)이 `data.message` 를 읽습니다. FastAPI 기본 `detail` 로
    돌려주면 사유가 표시되지 않고 fallback 문구만 뜹니다.
    """
    return JSONResponse(status_code=500, content={"status": "error", "message": message})


@router.get("/stats", summary="대시보드 통계")
def api_stats(db: Session = Depends(get_db)):
    try:
        return get_dashboard_stats(db)
    except Exception:
        logger.exception("대시보드 통계 API 처리 실패")
        return _stats_error("대시보드 통계 데이터를 불러오지 못했습니다.")


@router.get("/compare-stats", summary="공고 대비 낙찰 비교 통계")
def api_compare_stats(db: Session = Depends(get_db)):
    try:
        return get_compare_stats_data(db)
    except Exception:
        logger.exception("비교 분석 통계 API 처리 실패")
        return _stats_error("비교 분석 데이터를 불러오지 못했습니다.")


@router.get("/home", response_model=HomeContextResponse, summary="홈 화면 컨텍스트")
def api_home_context(db: Session = Depends(get_db)):
    context = get_home_page_context(db, DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
    return HomeContextResponse(
        recent_bids=[_serialize_announcement(bid) for bid in context["recent_bids"]],
        recent_results=[_serialize_result(db, row) for row in context["recent_results"]],
        recent_bid_sections=[
            {
                "code": section["code"],
                "label": section["label"],
                "entries": [_serialize_announcement(bid) for bid in section["entries"]],
            }
            for section in context["recent_bid_sections"]
        ],
        announcement_total=context["announcement_total"] or 0,
        result_total=context["result_total"] or 0,
        latest_result_rate=context["latest_result_rate"],
        latest_collected_at=context["latest_collected_at"],
    )


@router.get("/results/{pk}", response_model=BidResultDetailResponse, summary="낙찰결과 상세")
def get_bid_result_detail(pk: int, db: Session = Depends(get_db)):
    detail = bid_queries.get_result_detail(db, pk)
    if detail is None:
        raise HTTPException(status_code=404, detail="낙찰 결과를 찾을 수 없습니다.")
    return BidResultDetailResponse(
        result=_serialize_result(db, detail["result"]),
        related_results=[_serialize_result(db, row) for row in detail["related_results"]],
        raw_json=detail["raw_json"] if isinstance(detail["raw_json"], dict) else None,
    )


@router.get("/{pk}", response_model=BidDetailResponse, summary="입찰공고 상세")
def get_bid_detail(pk: int, db: Session = Depends(get_db)):
    detail = bid_queries.get_announcement_detail(db, pk)
    if detail is None:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    return BidDetailResponse(
        bid=_serialize_announcement(detail["bid"]),
        similar_bids=[_serialize_announcement(bid) for bid in detail["similar_bids"]],
        past_results=[_serialize_result(db, row) for row in detail["past_results"]],
        default_prediction_model=detail["default_prediction_model"],
    )


@router.post("/collect", summary="G2B 데이터 수집 실행")
async def collect_bids_api(
    start_date: str = Query("", description="수집 시작일 (YYYYMMDD, 미지정 시 어제)"),
    end_date: str = Query("", description="수집 종료일 (YYYYMMDD, 미지정 시 어제)"),
    fetch_type: str = Query("both", description="both/announce/result"),
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """원본 collect_bids 관리 명령 대응. 장시간 수집은 자동화 큐를 사용하십시오."""
    if not (user.is_staff or user.is_superuser):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")

    from src.app.services.collector_service import collect_bids

    return await collect_bids(
        db,
        start_date=start_date or None,
        end_date=end_date or None,
        fetch_type=fetch_type,
    )
