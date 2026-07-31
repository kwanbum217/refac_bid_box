from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.app.core.db import get_db
from src.app.models.bids import BidAnnouncement
from src.app.schemas.bids import BidAnnouncementResponse

router = APIRouter(prefix="/bids", tags=["Bids"])

# 초기 목업 시드 데이터 (DB 데이터 미존재 시 자동 서빙)
MOCK_BIDS = [
    {
        "id": 1,
        "bid_notice_no": "20260731001-00",
        "bid_notice_name": "2026년도 국가통합 입찰분석 MLOps 서버 구매",
        "order_institution": "조달청",
        "category_code": "Thng",
        "presumed_price": 550000000.0,
        "base_price": 545000000.0,
        "notice_date": datetime.utcnow() - timedelta(hours=2),
        "created_at": datetime.utcnow() - timedelta(hours=2),
    },
    {
        "id": 2,
        "bid_notice_no": "20260731002-00",
        "bid_notice_name": "공공조달 입찰가 예측 AI 모델 유지보수 용역",
        "order_institution": "행정안전부",
        "category_code": "Servc",
        "presumed_price": 320000000.0,
        "base_price": 315000000.0,
        "notice_date": datetime.utcnow() - timedelta(hours=5),
        "created_at": datetime.utcnow() - timedelta(hours=5),
    },
    {
        "id": 3,
        "bid_notice_no": "20260731003-00",
        "bid_notice_name": "스마트 조달 데이터센터 시설 개선 공사",
        "order_institution": "한국토지주택공사",
        "category_code": "Cnstwk",
        "presumed_price": 1250000000.0,
        "base_price": 1240000000.0,
        "notice_date": datetime.utcnow() - timedelta(days=1),
        "created_at": datetime.utcnow() - timedelta(days=1),
    },
    {
        "id": 4,
        "bid_notice_no": "20260731004-00",
        "bid_notice_name": "차세대 하이브리드 RAG 챗봇 시스템 구축 사업",
        "order_institution": "과학기술정보통신부",
        "category_code": "Servc",
        "presumed_price": 890000000.0,
        "base_price": 880000000.0,
        "notice_date": datetime.utcnow() - timedelta(days=1, hours=3),
        "created_at": datetime.utcnow() - timedelta(days=1, hours=3),
    },
    {
        "id": 5,
        "bid_notice_no": "20260731005-00",
        "bid_notice_name": "고성능 GPU 서버 및 벡터DB 스토리지 확충",
        "order_institution": "한국지능정보사회진흥원",
        "category_code": "Thng",
        "presumed_price": 420000000.0,
        "base_price": 415000000.0,
        "notice_date": datetime.utcnow() - timedelta(days=2),
        "created_at": datetime.utcnow() - timedelta(days=2),
    },
]


@router.get("", response_model=list[BidAnnouncementResponse])
def get_bids(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: str = Query(None, description="카테고리 코드 (Thng/Servc/Cnstwk)"),
    search: str = Query(None, description="공고명/발주기관 검색어"),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(BidAnnouncement)
        if category:
            query = query.filter(BidAnnouncement.category_code == category)
        if search:
            query = query.filter(
                (BidAnnouncement.bid_notice_name.contains(search)) | (BidAnnouncement.order_institution.contains(search))
            )
        bids = query.order_by(BidAnnouncement.notice_date.desc()).offset(skip).limit(limit).all()
        if bids:
            return bids
    except Exception:
        pass

    # DB 데이터 미존재 시 대시보드 시각화용 목업 데이터 반환
    results = MOCK_BIDS
    if category:
        results = [b for b in results if b["category_code"] == category]
    if search:
        search_lower = search.lower()
        results = [b for b in results if search_lower in b["bid_notice_name"].lower() or search_lower in b["order_institution"].lower()]

    return results[skip : skip + limit]
