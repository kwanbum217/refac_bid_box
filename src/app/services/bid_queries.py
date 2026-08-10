"""
src/app/services/bid_queries.py

입찰공고/낙찰결과 목록 조회 (원본 apps/bids/views.py 질의 로직 1:1 이식).
지역 그룹, 정렬 키, 최신 차수 서브쿼리, count 없는 offset 페이지네이션을 그대로 보존합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, and_, case, or_, select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.models.bids import BidAnnouncement, BidResult
from src.ml.model_registry import CATEGORY_DEFAULT_MODELS

# 매핑을 여기 다시 적으면 모델 교체 때 한쪽만 바뀝니다. 정본은 model_registry 입니다.
DEFAULT_PREDICTION_MODEL_BY_CATEGORY = CATEGORY_DEFAULT_MODELS
DEFAULT_PREDICTION_MODEL = "v25"
DEFAULT_BID_LIST_SORT = "notice"
DEFAULT_RESULT_LIST_SORT = "opening"
DEFAULT_REGION_SORT_RANK = 999
BID_LIST_SORT_CHOICES = ("notice", "deadline", "amount", "region")
RESULT_LIST_SORT_CHOICES = ("opening", "amount", "rate")
PAGE_SIZE = 20


def _meili_enabled() -> bool:
    return settings.MEILI_ENABLED


BID_REGION_GROUPS = (
    ("특별시", (("seoul", "서울특별시", ("서울특별시", "서울")),)),
    (
        "광역시",
        (
            ("busan", "부산광역시", ("부산광역시", "부산")),
            ("daegu", "대구광역시", ("대구광역시", "대구")),
            ("incheon", "인천광역시", ("인천광역시", "인천")),
            ("gwangju", "광주광역시", ("광주광역시", "광주")),
            ("daejeon", "대전광역시", ("대전광역시", "대전")),
            ("ulsan", "울산광역시", ("울산광역시", "울산")),
        ),
    ),
    ("특별자치시", (("sejong", "세종특별자치시", ("세종특별자치시", "세종")),)),
    (
        "도",
        (
            ("gyeonggi", "경기도", ("경기도", "경기")),
            ("chungbuk", "충청북도", ("충청북도", "충북")),
            ("chungnam", "충청남도", ("충청남도", "충남")),
            ("jeonnam", "전라남도", ("전라남도", "전남")),
            ("gyeongbuk", "경상북도", ("경상북도", "경북")),
            ("gyeongnam", "경상남도", ("경상남도", "경남")),
        ),
    ),
    (
        "특별자치도",
        (
            ("jeju", "제주특별자치도", ("제주특별자치도", "제주")),
            ("gangwon", "강원특별자치도", ("강원특별자치도", "강원도", "강원")),
            ("jeonbuk", "전북특별자치도", ("전북특별자치도", "전라북도", "전북")),
        ),
    ),
)
_BID_REGION_FLAT_CHOICES = [
    item for _group_label, group_items in BID_REGION_GROUPS for item in group_items
]
BID_REGION_CHOICES = [
    {"code": code, "label": label, "aliases": aliases, "rank": rank}
    for rank, (code, label, aliases) in enumerate(_BID_REGION_FLAT_CHOICES, start=1)
]
BID_REGION_BY_CODE = {item["code"]: item for item in BID_REGION_CHOICES}


@dataclass
class OffsetPage:
    """count 쿼리를 발생시키지 않는 페이지 객체 (원본 OffsetPage 동일)."""

    object_list: list
    number: int
    per_page: int
    has_next: bool

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def previous_page_number(self) -> int:
        return max(self.number - 1, 1)

    @property
    def next_page_number(self) -> int:
        return self.number + 1

    @property
    def start_index(self) -> int:
        if not self.object_list:
            return 0
        return ((self.number - 1) * self.per_page) + 1

    @property
    def end_index(self) -> int:
        if not self.object_list:
            return 0
        return self.start_index + len(self.object_list) - 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "per_page": self.per_page,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
            "previous_page_number": self.previous_page_number,
            "next_page_number": self.next_page_number,
            "start_index": self.start_index,
            "end_index": self.end_index,
        }


def region_groups_payload() -> list[dict[str, Any]]:
    return [
        {
            "label": group_label,
            "items": [{"code": code, "label": label} for code, label, _aliases in group_items],
        }
        for group_label, group_items in BID_REGION_GROUPS
    ]


def normalize_region_code(region_code: str | None) -> str:
    region_code = (region_code or "").strip()
    return region_code if region_code in BID_REGION_BY_CODE else ""


def normalize_bid_sort(sort_key: str | None) -> str:
    return sort_key if sort_key in BID_LIST_SORT_CHOICES else DEFAULT_BID_LIST_SORT


def normalize_result_sort(sort_key: str | None) -> str:
    return sort_key if sort_key in RESULT_LIST_SORT_CHOICES else DEFAULT_RESULT_LIST_SORT


def _region_match_clause(aliases) -> Any:
    clauses = []
    for alias in aliases:
        clauses.append(BidAnnouncement.dminstt_nm.contains(alias))
        clauses.append(BidAnnouncement.ntce_instt_nm.contains(alias))
    return or_(*clauses)


def _result_region_match_clause(aliases) -> Any:
    return or_(*[BidResult.dminstt_nm.contains(alias) for alias in aliases])


def _region_sort_rank():
    return case(
        *[(_region_match_clause(item["aliases"]), item["rank"]) for item in BID_REGION_CHOICES],
        else_=DEFAULT_REGION_SORT_RANK,
    ).cast(Integer)


def latest_announcement_filter(stmt):
    """공고번호+카테고리 기준 최신 차수 1건만 남기는 서브쿼리 필터."""
    latest_alias = BidAnnouncement.__table__.alias("latest_ann")
    latest_id_subquery = (
        select(latest_alias.c.id)
        .where(
            latest_alias.c.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            latest_alias.c.category == BidAnnouncement.category,
        )
        .order_by(
            latest_alias.c.bid_ntce_ord.desc(),
            latest_alias.c.bid_ntce_dt.desc(),
            latest_alias.c.collected_at.desc(),
            latest_alias.c.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    return stmt.where(BidAnnouncement.id == latest_id_subquery)


def latest_announcement_for_instance(db: Session, instance: BidAnnouncement | None):
    if instance is None:
        return None
    latest = (
        db.query(BidAnnouncement)
        .filter(
            BidAnnouncement.bid_ntce_no == instance.bid_ntce_no,
            BidAnnouncement.category == instance.category,
        )
        .order_by(
            BidAnnouncement.bid_ntce_ord.desc(),
            BidAnnouncement.bid_ntce_dt.desc(),
            BidAnnouncement.collected_at.desc(),
            BidAnnouncement.id.desc(),
        )
        .first()
    )
    return latest or instance


def _paginate_without_count(db: Session, stmt, page_number: int) -> OffsetPage:
    page_number = max(page_number, 1)
    offset = (page_number - 1) * PAGE_SIZE
    rows = db.execute(stmt.offset(offset).limit(PAGE_SIZE + 1)).scalars().all()
    has_next = len(rows) > PAGE_SIZE
    return OffsetPage(
        object_list=list(rows[:PAGE_SIZE]),
        number=page_number,
        per_page=PAGE_SIZE,
        has_next=has_next,
    )


def _page_from_search_ids(
    db: Session, model, ids: list[int], page_number: int, has_next: bool
) -> OffsetPage:
    if not ids:
        return OffsetPage(object_list=[], number=page_number, per_page=PAGE_SIZE, has_next=False)
    rows = db.execute(select(model).where(model.id.in_(ids))).scalars().all()
    by_id = {row.id: row for row in rows}
    return OffsetPage(
        object_list=[by_id[row_id] for row_id in ids if row_id in by_id],
        number=page_number,
        per_page=PAGE_SIZE,
        has_next=has_next,
    )


def _announcement_search_sort(sort_key: str) -> list[str]:
    if sort_key == "deadline":
        return ["bid_clse_dt:asc", "source_id:desc"]
    if sort_key == "amount":
        return ["base_amount:desc", "source_id:desc"]
    if sort_key == "region":
        return ["region_rank:asc", "bid_ntce_dt:desc", "source_id:desc"]
    return ["bid_ntce_dt:desc", "source_id:desc"]


def _result_search_sort(sort_key: str) -> list[str]:
    if sort_key == "amount":
        return ["sucsf_bid_amt:desc", "source_id:desc"]
    if sort_key == "rate":
        return ["sucsf_bid_rate:asc", "source_id:asc"]
    return ["rl_openg_dt:desc", "source_id:desc"]


def list_announcements(
    db: Session,
    *,
    q: str | None = None,
    cat: str | None = None,
    region: str | None = None,
    sort: str | None = None,
    page: int = 1,
) -> OffsetPage:
    region_code = normalize_region_code(region)
    sort_key = normalize_bid_sort(sort)

    if q and q.strip() and _meili_enabled():
        from src.app.services.search_index import MeiliSearchClient

        page_number = max(page, 1)
        result = MeiliSearchClient().search(
            query=q.strip(),
            dataset="announcement",
            category=cat or None,
            region=region_code or None,
            sort=_announcement_search_sort(sort_key),
            offset=(page_number - 1) * PAGE_SIZE,
            limit=PAGE_SIZE,
        )
        return _page_from_search_ids(db, BidAnnouncement, result.ids, page_number, result.has_next)

    stmt = select(BidAnnouncement)

    if q:
        q_clean = q.strip()
        # 숫자로만 이루어지거나 하이픈 포함 숫자인 경우 공고번호 전용 검색으로 인덱스 타게 함
        if q_clean.replace("-", "").isdigit():
            stmt = stmt.where(BidAnnouncement.bid_ntce_no.contains(q_clean))
        else:
            stmt = stmt.where(
                or_(
                    BidAnnouncement.bid_ntce_nm.contains(q_clean),
                    BidAnnouncement.bid_ntce_no.contains(q_clean),
                    BidAnnouncement.dminstt_nm.contains(q_clean),
                )
            )

    if cat:
        stmt = stmt.where(BidAnnouncement.category == cat)

    if region_code:
        stmt = stmt.where(_region_match_clause(BID_REGION_BY_CODE[region_code]["aliases"]))

    # 필터링을 거친 후 마지막에 최신 서브쿼리 필터를 적용하여 쿼리 범위를 대폭 축소
    stmt = latest_announcement_filter(stmt)

    if sort_key == "deadline":
        missing = case((BidAnnouncement.bid_clse_dt.is_(None), 1), else_=0)
        stmt = stmt.order_by(missing, BidAnnouncement.bid_clse_dt, BidAnnouncement.id.desc())
    elif sort_key == "amount":
        missing = case((BidAnnouncement.base_amount.is_(None), 1), else_=0)
        stmt = stmt.order_by(missing, BidAnnouncement.base_amount.desc(), BidAnnouncement.id.desc())
    elif sort_key == "region":
        stmt = stmt.order_by(
            _region_sort_rank(), BidAnnouncement.bid_ntce_dt.desc(), BidAnnouncement.id.desc()
        )
    else:
        stmt = stmt.order_by(BidAnnouncement.bid_ntce_dt.desc(), BidAnnouncement.id.desc())

    return _paginate_without_count(db, stmt, page)


def list_results(
    db: Session,
    *,
    q: str | None = None,
    cat: str | None = None,
    region: str | None = None,
    sort: str | None = None,
    page: int = 1,
) -> OffsetPage:
    region_code = normalize_region_code(region)
    sort_key = normalize_result_sort(sort)

    if q and q.strip() and _meili_enabled():
        from src.app.services.search_index import MeiliSearchClient

        page_number = max(page, 1)
        result = MeiliSearchClient().search(
            query=q.strip(),
            dataset="result",
            category=cat or None,
            region=region_code or None,
            sort=_result_search_sort(sort_key),
            offset=(page_number - 1) * PAGE_SIZE,
            limit=PAGE_SIZE,
        )
        return _page_from_search_ids(db, BidResult, result.ids, page_number, result.has_next)

    stmt = select(BidResult)

    if q:
        q_clean = q.strip()
        if q_clean.replace("-", "").isdigit():
            stmt = stmt.where(BidResult.bid_ntce_no.contains(q_clean))
        else:
            stmt = stmt.where(
                or_(
                    BidResult.bid_ntce_nm.contains(q_clean),
                    BidResult.bid_ntce_no.contains(q_clean),
                    BidResult.dminstt_nm.contains(q_clean),
                    BidResult.bidwinnr_nm.contains(q_clean),
                )
            )

    if cat:
        stmt = stmt.where(BidResult.category == cat)

    if region_code:
        stmt = stmt.where(_result_region_match_clause(BID_REGION_BY_CODE[region_code]["aliases"]))

    if sort_key == "amount":
        stmt = stmt.order_by(BidResult.sucsf_bid_amt.desc(), BidResult.id.desc())
    elif sort_key == "rate":
        stmt = stmt.where(BidResult.sucsf_bid_rate.is_not(None)).order_by(
            BidResult.sucsf_bid_rate, BidResult.id
        )
    else:
        stmt = stmt.order_by(BidResult.rl_openg_dt.desc(), BidResult.id.desc())

    return _paginate_without_count(db, stmt, page)


def get_announcement_detail(db: Session, pk: int) -> dict[str, Any] | None:
    """공고 상세 + 유사 공고 + 기관 과거 낙찰 이력 (원본 BidDetailView 이식)."""
    instance = db.get(BidAnnouncement, pk)
    if instance is None:
        return None

    bid = latest_announcement_for_instance(db, instance)

    similar_stmt = latest_announcement_filter(
        select(BidAnnouncement).where(
            BidAnnouncement.category == bid.category,
            BidAnnouncement.dminstt_nm == bid.dminstt_nm,
        )
    ).where(BidAnnouncement.id != bid.id)
    similar_bids = db.execute(similar_stmt.limit(5)).scalars().all()

    past_results = (
        db.query(BidResult)
        .filter(BidResult.dminstt_nm == bid.dminstt_nm)
        .order_by(BidResult.rl_openg_dt.desc())
        .limit(5)
        .all()
    )

    return {
        "bid": bid,
        "similar_bids": list(similar_bids),
        "past_results": past_results,
        "default_prediction_model": DEFAULT_PREDICTION_MODEL_BY_CATEGORY.get(
            bid.category, DEFAULT_PREDICTION_MODEL
        ),
    }


def get_result_detail(db: Session, pk: int) -> dict[str, Any] | None:
    """낙찰 상세 + 동일 기관/카테고리 관련 사례 (원본 BidResultDetailView 이식)."""
    result = db.get(BidResult, pk)
    if result is None:
        return None

    related_results = (
        db.query(BidResult)
        .filter(
            and_(
                BidResult.dminstt_nm == result.dminstt_nm,
                BidResult.category == result.category,
                BidResult.id != result.id,
            )
        )
        .order_by(BidResult.rl_openg_dt.desc())
        .limit(5)
        .all()
    )

    # 낙찰률은 공고 기준금액을 다시 조회해야 나오므로 원본과 달리 property 가
    # 아니라 db 를 받는 메서드입니다. Jinja2 는 속성 접근으로 메서드를 호출하지
    # 않으므로, 템플릿이 쓸 값을 여기서 미리 확정해 붙입니다.
    result.resolved_winning_rate = result.display_winning_rate(db)
    for row in related_results:
        row.resolved_winning_rate = row.display_winning_rate(db)

    return {
        "result": result,
        "related_results": related_results,
        "raw_json": result.raw_data,
    }
