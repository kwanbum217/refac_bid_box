"""
src/app/schemas/bids.py

입찰 도메인 응답 스키마. 원본 템플릿 컨텍스트가 사용하던 표시용 필드
(category_label, display_*, prediction_reference_amount)를 응답 계약에 포함합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BidAnnouncementBase(BaseModel):
    bid_ntce_no: str = Field(..., description="입찰공고번호")
    bid_ntce_ord: str = Field("000", description="입찰공고차수")
    bid_ntce_nm: str | None = Field(None, description="입찰공고명")
    dminstt_nm: str | None = Field(None, description="수요기관명")
    ntce_instt_nm: str | None = Field(None, description="공고기관명")
    category: str = Field("Thng", description="업무구분 (Thng/Servc/Cnstwk/Frgcpt)")
    base_amount: int | None = Field(None, description="기초금액(사업예산)")
    presmpt_prce: int | None = Field(None, description="원본 참고금액")


class BidAnnouncementCreate(BidAnnouncementBase):
    pass


class BidAnnouncementResponse(BidAnnouncementBase):
    id: int
    bid_ntce_dt: datetime | None = None
    bid_clse_dt: datetime | None = None
    openg_dt: datetime | None = None
    ntce_kind_nm: str | None = None
    bid_methd_nm: str | None = None
    cntrct_mthd_nm: str | None = None
    collected_at: datetime | None = None
    category_label: str = Field("", description="업무구분 한글 라벨")
    resolved_base_amount: int | None = Field(None, description="raw_data 기준 확정 기초금액")
    has_base_amount: bool = Field(False, description="기초금액 확정 가능 여부")
    prediction_reference_amount: int | None = Field(None, description="예측 기준 금액")

    model_config = ConfigDict(from_attributes=True)


class BidResultResponse(BaseModel):
    id: int
    bid_ntce_no: str
    bid_ntce_ord: str = "00"
    bid_ntce_nm: str | None = None
    bidwinnr_nm: str | None = None
    sucsf_bid_amt: int | None = None
    sucsf_bid_rate: float | None = None
    rl_openg_dt: datetime | None = None
    dminstt_nm: str | None = None
    category: str = "Thng"
    collected_at: datetime | None = None
    category_label: str = Field("", description="업무구분 한글 라벨")
    display_bid_ntce_nm: str = Field("", description="정제된 공고명")
    display_dminstt_nm: str = Field("", description="정제된 수요기관명")
    display_bidwinnr_nm: str = Field("", description="정제된 낙찰업체명")
    has_corrupted_display_text: bool = Field(False, description="원문 인코딩 손상 여부")
    display_winning_rate: float | None = Field(None, description="기초금액 기준 재계산 낙찰률")

    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    number: int
    per_page: int
    has_next: bool
    has_previous: bool
    previous_page_number: int
    next_page_number: int
    start_index: int
    end_index: int


class RegionGroupItem(BaseModel):
    code: str
    label: str


class RegionGroup(BaseModel):
    label: str
    items: list[RegionGroupItem]


class BidListResponse(BaseModel):
    bids: list[BidAnnouncementResponse]
    page_obj: PageMeta
    is_paginated: bool
    q: str = ""
    cat: str = ""
    sort: str = "notice"
    region: str = ""
    region_groups: list[RegionGroup] = Field(default_factory=list)


class BidResultListResponse(BaseModel):
    results: list[BidResultResponse]
    page_obj: PageMeta
    is_paginated: bool
    q: str = ""
    cat: str = ""
    sort: str = "opening"
    region: str = ""
    region_groups: list[RegionGroup] = Field(default_factory=list)


class BidDetailResponse(BaseModel):
    bid: BidAnnouncementResponse
    similar_bids: list[BidAnnouncementResponse] = Field(default_factory=list)
    past_results: list[BidResultResponse] = Field(default_factory=list)
    default_prediction_model: str


class BidResultDetailResponse(BaseModel):
    result: BidResultResponse
    related_results: list[BidResultResponse] = Field(default_factory=list)
    raw_json: dict[str, Any] | None = None


class HomeCategorySection(BaseModel):
    code: str
    label: str
    entries: list[BidAnnouncementResponse] = Field(default_factory=list)


class HomeContextResponse(BaseModel):
    recent_bids: list[BidAnnouncementResponse] = Field(default_factory=list)
    recent_results: list[BidResultResponse] = Field(default_factory=list)
    recent_bid_sections: list[HomeCategorySection] = Field(default_factory=list)
    announcement_total: int = 0
    result_total: int = 0
    latest_result_rate: float | None = None
    latest_collected_at: datetime | None = None
