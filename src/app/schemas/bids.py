from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BidAnnouncementBase(BaseModel):
    bid_notice_no: str = Field(..., description="공고번호")
    bid_notice_name: str = Field(..., description="공고명")
    order_institution: str = Field(..., description="발주기관")
    category_code: str = Field(..., description="카테고리 (Thng/Servc/Cnstwk)")
    presumed_price: float = Field(0.0, description="추정가격")
    base_price: float = Field(0.0, description="기초금액")


class BidAnnouncementCreate(BidAnnouncementBase):
    pass


class BidAnnouncementResponse(BidAnnouncementBase):
    id: int
    notice_date: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BidResultResponse(BaseModel):
    id: int
    winning_company: str
    winning_price: float
    winning_rate: float
    successful_bid_date: datetime

    model_config = ConfigDict(from_attributes=True)

