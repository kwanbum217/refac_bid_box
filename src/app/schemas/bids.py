from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class BidAnnouncementBase(BaseModel):
    bid_ntce_no: str = Field(..., description="입찰공고번호")
    bid_ntce_ord: str = Field("000", description="입찰공고차수")
    bid_ntce_nm: Optional[str] = Field(None, description="입찰공고명")
    dminstt_nm: Optional[str] = Field(None, description="수요기관명")
    ntce_instt_nm: Optional[str] = Field(None, description="공고기관명")
    category: str = Field("Thng", description="카테고리 (Thng/Servc/Cnstwk/Frgcpt)")
    base_amount: Optional[int] = Field(None, description="기초금액")
    presmpt_prce: Optional[int] = Field(None, description="추정가격")


class BidAnnouncementCreate(BidAnnouncementBase):
    pass


class BidAnnouncementResponse(BidAnnouncementBase):
    id: int
    bid_ntce_dt: Optional[datetime] = None
    collected_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BidResultResponse(BaseModel):
    id: int
    bid_ntce_no: str
    bid_ntce_nm: Optional[str] = None
    bidwinnr_nm: Optional[str] = None
    sucsf_bid_amt: Optional[int] = None
    sucsf_bid_rate: Optional[float] = None
    rl_openg_dt: Optional[datetime] = None
    dminstt_nm: Optional[str] = None
    category: str

    model_config = ConfigDict(from_attributes=True)
