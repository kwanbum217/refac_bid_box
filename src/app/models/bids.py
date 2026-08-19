"""
src/app/models/bids.py

입찰 도메인 ORM (원본 apps/bids/models.py 1:1 이식).
테이블명, 컬럼명, 타입, 인덱스, 유니크 제약을 원본 그대로 보존합니다.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)

from src.app.core.db import Base, PKBigInteger
from src.app.core.timeutil import utcnow

CATEGORY_LABELS = {
    "Thng": "물품",
    "Cnstwk": "건설",
    "Servc": "용역",
    "Frgcpt": "외자",
}
CORRUPTED_TEXT_FALLBACKS = {
    "title": "낙찰 결과 원문 인코딩 확인 필요",
    "agency": "기관 정보 확인 필요",
    "winner": "업체 정보 확인 필요",
}
SUSPICIOUS_TEXT_PATTERN = re.compile(r"[�À-ɏͰ-Ͽ]")
HANGUL_SYLLABLE_PATTERN = re.compile(r"[가-힣]")

BUSINESS_BUDGET_RAW_KEYS = (
    "asignBdgtAmt",
    "bdgtAmt",
)

DATASET_ANNOUNCEMENT = "announcement"
DATASET_RESULT = "result"
DATASET_LABELS = {
    DATASET_ANNOUNCEMENT: "입찰공고",
    DATASET_RESULT: "낙찰결과",
}


def _coerce_amount(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.replace(",", "").strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _coerce_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _format_rate(value: Any) -> Decimal | None:
    numeric = _coerce_decimal(value)
    if numeric is None:
        return None
    return numeric.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def normalize_bid_ntce_ord(value: Any) -> str:
    """차수를 3자리로 맞춥니다.

    공고 API 는 3자리(`000`), 낙찰 API 는 2자리(`00`) 로 같은 차수를 내려줍니다.
    정규화 없이 두 테이블을 문자열로 이으면 거의 모든 행이 어긋납니다.
    SQL 조인 쪽 대응은 `src/ml/dataset.py` 의 `_normalized_ord` 입니다.
    """
    text = str(value or "").strip()
    return text.zfill(3)[-3:] if text else "000"


def extract_business_budget(raw_data: Any, fallback: Any = None) -> Any:
    """기초금액은 예산금액/배정예산금액만 사용한다."""
    if isinstance(raw_data, dict):
        for key in BUSINESS_BUDGET_RAW_KEYS:
            amount = _coerce_amount(raw_data.get(key))
            if amount is not None:
                return amount
    return fallback


def _is_heavily_corrupted_text(value: Any) -> bool:
    if not value:
        return False
    text = str(value)
    compact_length = len("".join(text.split()))
    if compact_length == 0:
        return False

    replacement_count = text.count("�")
    suspicious_count = len(SUSPICIOUS_TEXT_PATTERN.findall(text))
    hangul_count = len(HANGUL_SYLLABLE_PATTERN.findall(text))
    return (
        replacement_count >= 2
        or suspicious_count >= 4
        or suspicious_count / compact_length > 0.12
        or (replacement_count >= 1 and hangul_count == 0)
    )


def is_corrupted_display_text(value: Any) -> bool:
    """표시하기 어려울 만큼 인코딩이 깨진 값인지 판정합니다.

    parquet 복구분 1,244,778행(`bid_results` 의 41%)이 원본 바이트를 U+FFFD 로
    잃은 상태이고 `raw_data` 도 비어 있어 복구가 불가능합니다. 집계·순위에서
    걸러내는 용도로 쓰며, 판정 기준은 화면 표시용 `clean_display_text` 와 같습니다.
    """
    return _is_heavily_corrupted_text(value)


def clean_display_text(value: Any, fallback: str = "") -> str:
    if value in (None, ""):
        return fallback
    text = re.sub(r"\s+", " ", str(value)).strip()
    if _is_heavily_corrupted_text(text):
        return fallback
    return text.replace("�", "·")


class BidResult(Base):
    """조달청 낙찰 결과 테이블"""

    __tablename__ = "bid_results"
    __table_args__ = (
        # 이름이 긴 것은 원본 Django unique_together 가 만든 실제 인덱스명이기 때문입니다.
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "category",
            name="bid_results_bid_ntce_no_bid_ntce_ord_category_94d04c58_uniq",
        ),
        Index("ix_bid_results_bidwinnr_nm", "bidwinnr_nm"),
        Index("ix_bid_results_dt_cat", "rl_openg_dt", "category"),
        Index("ix_bid_results_amt_id", "sucsf_bid_amt", "id"),
        Index("ix_bid_results_rate_id", "sucsf_bid_rate", "id"),
        Index("bid_results_dminstt_nm_1b809760", "dminstt_nm"),
        Index("bid_results_category_981358ae", "category"),
        Index("bid_results_collected_at_25a564b9", "collected_at"),
        Index("bid_results_rl_openg_dt_00b70e7a", "rl_openg_dt"),
        # 챗봇 통계 질의(업무구분 + 기간별 건수/평균낙찰률/합계금액) 전용 커버링
        # 인덱스입니다. 집계 컬럼까지 넣어야 테이블을 읽지 않습니다. 앞의
        # category 단일 인덱스만으로는 옵티마이저가 340만 행 풀스캔을 택합니다.
        Index(
            "ix_bid_results_cat_dt_stats",
            "category",
            "rl_openg_dt",
            "sucsf_bid_rate",
            "sucsf_bid_amt",
        ),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_nm = Column(String(500), nullable=True, comment="입찰공고명")
    bid_ntce_no = Column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord = Column(String(10), nullable=False, default="00", comment="입찰공고차수")
    bidwinnr_nm = Column(String(200), nullable=True, comment="낙찰업체명")
    sucsf_bid_amt = Column(BigInteger, nullable=True, comment="낙찰금액")
    sucsf_bid_rate = Column(Numeric(10, 4), nullable=True, comment="낙찰률")
    rl_openg_dt = Column(DateTime, nullable=True, comment="개찰일시")
    dminstt_nm = Column(String(200), nullable=True, comment="수요기관명")
    category = Column(
        String(10), nullable=False, default="Thng", comment="업무구분(Thng/Cnstwk/Servc/Frgcpt)"
    )
    raw_data = Column(JSON, nullable=True, comment="전체 원본 데이터")
    collected_at = Column(DateTime, nullable=False, default=utcnow, comment="수집일시")

    def __str__(self) -> str:
        return f"[{self.category}] {self.bid_ntce_no} - {self.bidwinnr_nm}"

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def display_bid_ntce_nm(self) -> str:
        return clean_display_text(self.bid_ntce_nm, CORRUPTED_TEXT_FALLBACKS["title"])

    @property
    def display_dminstt_nm(self) -> str:
        return clean_display_text(self.dminstt_nm, CORRUPTED_TEXT_FALLBACKS["agency"])

    @property
    def display_bidwinnr_nm(self) -> str:
        return clean_display_text(self.bidwinnr_nm, CORRUPTED_TEXT_FALLBACKS["winner"])

    @property
    def has_corrupted_display_text(self) -> bool:
        return any(
            _is_heavily_corrupted_text(value)
            for value in (self.bid_ntce_nm, self.dminstt_nm, self.bidwinnr_nm)
        )

    def matching_announcement(self, db) -> BidAnnouncement | None:
        """동일 공고번호/카테고리 공고를 차수 정규화까지 고려해 탐색합니다."""
        if hasattr(self, "_matching_announcement_cache"):
            # 첫 호출 뒤 인스턴스에 채워지는 동적 캐시입니다. 클래스 주석을
            # 달면 ORM 매퍼가 오류를 내므로 여기서만 추론 한계를 무시합니다.
            return self._matching_announcement_cache  # type: ignore[has-type]

        query = db.query(BidAnnouncement).filter(
            BidAnnouncement.bid_ntce_no == self.bid_ntce_no,
            BidAnnouncement.category == self.category,
        )
        announcement = query.filter(BidAnnouncement.bid_ntce_ord == self.bid_ntce_ord).first()
        if announcement is None:
            normalized_ord = (self.bid_ntce_ord or "").lstrip("0") or "0"
            for candidate in query.limit(10).all():
                candidate_ord = (candidate.bid_ntce_ord or "").lstrip("0") or "0"
                if candidate_ord == normalized_ord:
                    announcement = candidate
                    break

        self._matching_announcement_cache = announcement
        return announcement

    def reference_basis_winning_rate(self, db) -> Decimal | None:
        announcement = self.matching_announcement(db)
        reference_amount = announcement.prediction_reference_amount if announcement else None
        awarded_amount = _coerce_decimal(self.sucsf_bid_amt)
        reference_value = _coerce_decimal(reference_amount)
        if awarded_amount is None or reference_value in (None, Decimal("0")):
            return _format_rate(self.sucsf_bid_rate)
        return _format_rate((awarded_amount / reference_value) * Decimal("100"))

    def display_winning_rate(self, db) -> Decimal | None:
        return self.reference_basis_winning_rate(db) or _format_rate(self.sucsf_bid_rate)


class BidAnnouncement(Base):
    """조달청 입찰공고 테이블"""

    __tablename__ = "bid_announcements"
    __table_args__ = (
        # 이름이 긴 것은 원본 Django unique_together 가 만든 실제 인덱스명이기 때문입니다.
        UniqueConstraint(
            "bid_ntce_no",
            "bid_ntce_ord",
            "category",
            name="bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq",
        ),
        Index("ix_bid_ann_dt_cat", "bid_ntce_dt", "category"),
        Index("bid_announcements_dminstt_nm_952da702", "dminstt_nm"),
        Index("bid_announcements_bid_ntce_dt_c42f1afb", "bid_ntce_dt"),
        Index("bid_announcements_category_02e9e006", "category"),
        Index("ix_bid_ann_collected", "collected_at"),
        # 홈 화면의 카테고리별 최신 공고 표본 조회 전용 복합 인덱스입니다.
        # category 등치 조건과 collected_at 기간 조건을 선두에서 줄여
        # 대량 행 filesort 및 반복적인 범위 스캔을 방지합니다.
        Index(
            "ix_bid_ann_category_collected_dt",
            "category",
            "collected_at",
            "bid_ntce_dt",
            "id",
        ),
        # 카테고리 공통 최근 공고 조회에서 수집일 범위와 정렬을 함께 사용합니다.
        Index("ix_bid_ann_collected_dt", "collected_at", "bid_ntce_dt", "id"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    bid_ntce_nm = Column(String(500), nullable=True, comment="입찰공고명")
    bid_ntce_no = Column(String(50), nullable=False, comment="입찰공고번호")
    bid_ntce_ord = Column(String(10), nullable=False, default="000", comment="입찰공고차수")
    ntce_instt_nm = Column(String(200), nullable=True, comment="공고기관명")
    dminstt_nm = Column(String(200), nullable=True, comment="수요기관명")
    base_amount = Column(BigInteger, nullable=True, comment="기초금액(사업예산)")
    presmpt_prce = Column(BigInteger, nullable=True, comment="원본 참고금액")
    bid_ntce_dt = Column(DateTime, nullable=True, comment="입찰공고일시")
    bid_clse_dt = Column(DateTime, nullable=True, comment="입찰마감일시")
    openg_dt = Column(DateTime, nullable=True, comment="개찰일시")
    ntce_kind_nm = Column(String(100), nullable=True, comment="공고종류명")
    bid_methd_nm = Column(String(100), nullable=True, comment="입찰방식명")
    cntrct_mthd_nm = Column(String(100), nullable=True, comment="계약방법명")
    category = Column(
        String(10), nullable=False, default="Thng", comment="업무구분(Thng/Cnstwk/Servc/Frgcpt)"
    )
    raw_data = Column(JSON, nullable=True, comment="전체 원본 데이터")
    collected_at = Column(DateTime, nullable=False, default=utcnow, comment="수집일시")

    def __str__(self) -> str:
        return f"[{self.category}] {self.bid_ntce_no} - {self.bid_ntce_nm}"

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def resolved_base_amount(self) -> int | None:
        raw_amount = extract_business_budget(self.raw_data)
        if raw_amount is not None:
            return raw_amount
        if self.raw_data is None:
            return self.base_amount
        return None

    @property
    def display_base_amount(self) -> int | None:
        return self.resolved_base_amount

    @property
    def has_base_amount(self) -> bool:
        return self.resolved_base_amount is not None

    @property
    def prediction_reference_amount(self) -> int | None:
        resolved = self.resolved_base_amount
        return resolved if resolved is not None else self.presmpt_prce


class BidDatasetSummary(Base):
    """대시보드용 전용 집계 스냅샷."""

    __tablename__ = "bid_dataset_summaries"
    __table_args__ = (Index("bid_dataset_summaries_rebuilt_at_8d77f9db", "rebuilt_at"),)

    dataset = Column(String(20), primary_key=True, comment="집계 대상")
    total_count = Column(BigInteger, nullable=False, default=0, comment="전체 건수")
    total_amount = Column(Numeric(30, 0), nullable=False, default=0, comment="전체 금액 합계")
    avg_rate = Column(Numeric(10, 4), nullable=True, comment="평균 낙찰률")
    source_latest_collected_at = Column(DateTime, nullable=True, comment="원본 최신 수집 시각")
    rebuilt_at = Column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        comment="집계 갱신 시각",
    )

    def __str__(self) -> str:
        return f"{DATASET_LABELS.get(self.dataset, self.dataset)} 요약"


class BidRankingSnapshot(Base):
    """상위 N 집계 스냅샷.

    원본에는 없는 테이블입니다. `retrieve_structured_data` 가 매 질의마다
    300만 행에 GROUP BY 를 걸어 33초를 쓰던 문제를 해결하기 위해 추가했습니다.
    (docs/ops/latency_benchmark.md)

    `bid_dataset_summaries` 와 같은 사전 집계 방식이며, 필터가 category 뿐인
    질의만 대상으로 합니다. 날짜나 기관명이 걸린 질의는 조합이 무한하므로
    기존 실시간 집계 경로를 그대로 씁니다.
    """

    __tablename__ = "bid_ranking_snapshots"
    __table_args__ = (
        UniqueConstraint("dataset", "dimension", "category", "rank", name="uq_bid_ranking_slot"),
        Index("ix_bid_ranking_lookup", "dataset", "dimension", "category", "rank"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    dataset = Column(String(20), nullable=False, comment="집계 대상 (announcement/result)")
    dimension = Column(String(30), nullable=False, comment="집계 축 컬럼명")
    # 전체 집계는 빈 문자열로 둡니다. NULL 은 유니크 제약에서 중복을 허용해 못 씁니다.
    category = Column(String(10), nullable=False, default="", comment="업무구분 (전체는 빈 문자열)")
    rank = Column(BigInteger, nullable=False, comment="순위 (1부터)")
    label = Column(String(500), nullable=True, comment="집계 축 값")
    metric_count = Column(BigInteger, nullable=False, default=0, comment="건수")
    rebuilt_at = Column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        comment="집계 갱신 시각",
    )

    def __str__(self) -> str:
        scope = self.category or "전체"
        return f"[{self.dataset}/{self.dimension}/{scope}] {self.rank}위 {self.label}"


class InstitutionWinRateStat(Base):
    """기관별 낙찰률 이력 사전 집계.

    원본에는 없는 테이블입니다. `inst_hist_rate` 는 낙찰률 예측의 유일한 실질
    신호이지만(단독 R2 0.33), 추론 때마다 bid_results 를 COUNT + AVG 하면
    건당 150ms 가 걸립니다. 학습은 pandas 배치로 처리하고, 추론은 이 표를
    PK 조회합니다.

    학습과 같은 정의를 씁니다. "해당 기관의 기준 시점 이전 낙찰률 평균"이며,
    이 표는 그 정의의 현재 시점 값입니다. 정의가 갈리면 train/serve skew 가
    생겨 운영 성능이 무너집니다 (AGENTS.md 6항).

    야간 스케줄에서 갱신합니다.
    """

    __tablename__ = "institution_win_rate_stats"
    __table_args__ = (
        UniqueConstraint("institution_name", "category", name="uq_inst_win_rate_scope"),
    )

    id = Column(PKBigInteger, primary_key=True, autoincrement=True)
    institution_name = Column(String(200), nullable=False, comment="수요기관명")
    # 전체 집계는 빈 문자열로 둡니다. NULL 은 유니크 제약에서 중복을 허용해 못 씁니다.
    category = Column(String(10), nullable=False, default="", comment="업무구분 (전체는 빈 문자열)")
    sample_count = Column(BigInteger, nullable=False, default=0, comment="집계에 쓴 낙찰 건수")
    avg_rate = Column(Numeric(10, 4), nullable=False, comment="평균 낙찰률 (퍼센트)")
    ewm_rate = Column(
        Numeric(10, 4),
        nullable=True,
        comment="지수감쇠 낙찰률 (퍼센트, 반감기 20건)",
    )
    rebuilt_at = Column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        comment="집계 갱신 시각",
    )

    def __str__(self) -> str:
        scope = self.category or "전체"
        return f"[{scope}] {self.institution_name} {self.avg_rate}% ({self.sample_count}건)"
