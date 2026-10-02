"""조달청 사용자정보 서비스의 수요기관 기준정보 ORM 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.db import Base
from src.app.core.timeutil import utcnow


class G2BDemandInstitution(Base):
    __tablename__ = "g2b_demand_institutions"

    dminstt_cd: Mapped[str] = mapped_column(String(20), primary_key=True)
    dminstt_nm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jrsdctn_div_nm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    instt_ty_lrgclsfc_nm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    instt_ty_midclsfc_nm: Mapped[str | None] = mapped_column(String(300), nullable=True)
    instt_ty_smlclsfc_nm: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rgn_cd: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rgn_nm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    toplvl_instt_cd: Mapped[str | None] = mapped_column(String(20), nullable=True)
    toplvl_instt_nm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dlt_yn: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rgst_dt: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chg_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
