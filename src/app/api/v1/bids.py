from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from src.app.core.db import get_db
from src.app.models.bids import BidAnnouncement
from src.app.schemas.bids import BidAnnouncementResponse

router = APIRouter(prefix="/bids", tags=["Bids"])


@router.get("", response_model=list[BidAnnouncementResponse])
def get_bids(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: str = Query(None, description="카테고리 코드 (Thng/Servc/Cnstwk)"),
    db: Session = Depends(get_db),
):
    query = db.query(BidAnnouncement)
    if category:
        query = query.filter(BidAnnouncement.category_code == category)
    bids = query.order_by(BidAnnouncement.notice_date.desc()).offset(skip).limit(limit).all()
    return bids


@router.get("/{bid_notice_no}", response_model=BidAnnouncementResponse)
def get_bid_detail(bid_notice_no: str, db: Session = Depends(get_db)):
    bid = db.query(BidAnnouncement).filter(BidAnnouncement.bid_notice_no == bid_notice_no).first()
    if not bid:
        raise HTTPException(status_code=404, detail="입찰 공고를 찾을 수 없습니다.")
    return bid
