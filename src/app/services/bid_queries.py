"""
src/app/services/bid_queries.py

입찰공고/낙찰결과 목록 조회 (원본 apps/bids/views.py 질의 로직 1:1 이식).
지역 그룹, 정렬 키, 최신 차수, count 없는 offset 페이지네이션을 그대로 보존합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, and_, case, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, aliased

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
# 정렬된 목록의 깊은 offset 은 Meilisearch 에서 깊이에 비례해 비싸집니다.
# 같은 색인(공고 483만 건)에서 공고일 정렬 기준 page 1000 은 12ms, page 5000 은
# 56ms, page 100000 은 1310ms 입니다(2026-08-11 실측). 화면 페이지네이션은
# 이전/다음만 제공하므로 그 깊이는 주소를 직접 고쳐야 닿습니다. 도달 가능한
# 마지막 페이지를 여기서 끊어 비용의 꼬리를 잘라냅니다.
MAX_LIST_PAGE = 1_000
MYSQL_FALLBACK_MAX_EXECUTION_TIME_MS = 5_000
MYSQL_QUERY_TIMEOUT_ERROR_CODE = 3024


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
BID_REGION_CHOICES: list[dict[str, Any]] = [
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
    """공고번호+카테고리별 최신 차수 ID를 한 번만 계산해 결합합니다."""
    ranked_ids = select(
        BidAnnouncement.id.label("id"),
        func.row_number()
        .over(
            partition_by=(BidAnnouncement.bid_ntce_no, BidAnnouncement.category),
            order_by=(
                BidAnnouncement.bid_ntce_ord.desc(),
                BidAnnouncement.bid_ntce_dt.desc(),
                BidAnnouncement.collected_at.desc(),
                BidAnnouncement.id.desc(),
            ),
        )
        .label("latest_rank"),
    ).subquery("latest_ann")
    return stmt.join(ranked_ids, ranked_ids.c.id == BidAnnouncement.id).where(
        ranked_ids.c.latest_rank == 1
    )


def _is_newer_announcement_clause(other, current) -> Any:
    return or_(
        other.bid_ntce_ord > current.bid_ntce_ord,
        and_(
            other.bid_ntce_ord == current.bid_ntce_ord,
            or_(
                and_(other.bid_ntce_dt.is_not(None), current.bid_ntce_dt.is_(None)),
                and_(
                    other.bid_ntce_dt.is_not(None),
                    current.bid_ntce_dt.is_not(None),
                    other.bid_ntce_dt > current.bid_ntce_dt,
                ),
            ),
        ),
        and_(
            other.bid_ntce_ord == current.bid_ntce_ord,
            or_(
                other.bid_ntce_dt == current.bid_ntce_dt,
                and_(other.bid_ntce_dt.is_(None), current.bid_ntce_dt.is_(None)),
            ),
            other.collected_at > current.collected_at,
        ),
        and_(
            other.bid_ntce_ord == current.bid_ntce_ord,
            or_(
                other.bid_ntce_dt == current.bid_ntce_dt,
                and_(other.bid_ntce_dt.is_(None), current.bid_ntce_dt.is_(None)),
            ),
            other.collected_at == current.collected_at,
            other.id > current.id,
        ),
    )


def similar_announcement_latest_filter(stmt):
    """테이블 전체 랭킹 대신 후보 공고를 먼저 좁힌 뒤 동일 그룹 내 최신 차수 존재 여부를 NOT EXISTS로 판정합니다.
    다른 차수에서 기관이 변경된 공고를 배제하는 기존 window 함수의 결과 의미를 완전히 보존합니다.
    """
    newer_ann = aliased(BidAnnouncement)
    has_newer = (
        select(1)
        .where(
            newer_ann.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            newer_ann.category == BidAnnouncement.category,
            _is_newer_announcement_clause(newer_ann, BidAnnouncement),
        )
        .exists()
    )
    return stmt.where(~has_newer)


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


def _with_mysql_execution_limit(stmt):
    """MySQL fallback SELECT가 요청 수명보다 오래 실행되지 않게 제한합니다."""
    return stmt.prefix_with(
        f"/*+ MAX_EXECUTION_TIME({MYSQL_FALLBACK_MAX_EXECUTION_TIME_MS}) */",
        dialect="mysql",
    )


def _is_mysql_query_timeout(exc: DBAPIError) -> bool:
    # DBAPI 오류 사유코드는 args[0] 에 담깁니다. 빈 튜플(마이그레이션 실패 등)은
    # args[0] 을 읽지 않도록 bool(args) 로 먼저 걸러내므로 타입은 넓게 둡니다.
    args: tuple[Any, ...] = getattr(exc.orig, "args", ())
    return bool(args) and args[0] == MYSQL_QUERY_TIMEOUT_ERROR_CODE


def _page_beyond_limit(page_number: int) -> OffsetPage:
    """상한 밖 페이지는 검색 백엔드를 부르지 않고 빈 페이지로 끊습니다."""
    return OffsetPage(object_list=[], number=page_number, per_page=PAGE_SIZE, has_next=False)


def _apply_page_limit(page: OffsetPage) -> OffsetPage:
    """마지막 도달 가능 페이지에서 다음 링크를 내려 상한을 화면에 노출합니다."""
    if page.number >= MAX_LIST_PAGE:
        page.has_next = False
    return page


def _paginate_without_count(db: Session, stmt, page_number: int) -> OffsetPage:
    page_number = max(page_number, 1)
    offset = (page_number - 1) * PAGE_SIZE
    stmt = _with_mysql_execution_limit(stmt.offset(offset).limit(PAGE_SIZE + 1))
    try:
        rows = db.execute(stmt).scalars().all()
    except DBAPIError as exc:
        if not _is_mysql_query_timeout(exc):
            raise
        from src.app.services.search_index import SearchBackendUnavailable

        raise SearchBackendUnavailable("MySQL 검색 fallback 실행시간을 초과했습니다.") from exc
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


def _search_index_page(
    db: Session,
    *,
    model,
    query: str,
    dataset: str,
    category: str | None,
    region: str | None,
    sort: list[str],
    page_number: int,
) -> OffsetPage:
    from src.app.services.search_index import MeiliSearchClient

    result = MeiliSearchClient().search(
        query=query,
        dataset=dataset,
        category=category,
        region=region,
        sort=sort,
        offset=(page_number - 1) * PAGE_SIZE,
        limit=PAGE_SIZE,
    )
    return _page_from_search_ids(db, model, result.ids, page_number, result.has_next)


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
    page_number = max(page, 1)
    query = (q or "").strip()

    if page_number > MAX_LIST_PAGE:
        return _page_beyond_limit(page_number)

    if _meili_enabled():
        return _apply_page_limit(
            _search_index_page(
                db,
                model=BidAnnouncement,
                query=query,
                dataset="announcement",
                category=cat or None,
                region=region_code or None,
                sort=_announcement_search_sort(sort_key),
                page_number=page_number,
            )
        )

    stmt = select(BidAnnouncement)

    if query:
        # 숫자로만 이루어지거나 하이픈 포함 숫자인 경우 공고번호 전용 검색으로 인덱스 타게 함
        if query.replace("-", "").isdigit():
            stmt = stmt.where(BidAnnouncement.bid_ntce_no.contains(query))
        else:
            stmt = stmt.where(
                or_(
                    BidAnnouncement.bid_ntce_nm.contains(query),
                    BidAnnouncement.bid_ntce_no.contains(query),
                    BidAnnouncement.dminstt_nm.contains(query),
                )
            )

    if cat:
        stmt = stmt.where(BidAnnouncement.category == cat)

    if region_code:
        stmt = stmt.where(_region_match_clause(BID_REGION_BY_CODE[region_code]["aliases"]))

    # 필터와 무관하게 동일 공고번호·업무구분의 최신 차수만 노출합니다.
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

    return _apply_page_limit(_paginate_without_count(db, stmt, page_number))


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
    page_number = max(page, 1)
    query = (q or "").strip()

    if page_number > MAX_LIST_PAGE:
        return _page_beyond_limit(page_number)

    if _meili_enabled():
        return _apply_page_limit(
            _search_index_page(
                db,
                model=BidResult,
                query=query,
                dataset="result",
                category=cat or None,
                region=region_code or None,
                sort=_result_search_sort(sort_key),
                page_number=page_number,
            )
        )

    stmt = select(BidResult)

    if query:
        if query.replace("-", "").isdigit():
            stmt = stmt.where(BidResult.bid_ntce_no.contains(query))
        else:
            stmt = stmt.where(
                or_(
                    BidResult.bid_ntce_nm.contains(query),
                    BidResult.bid_ntce_no.contains(query),
                    BidResult.dminstt_nm.contains(query),
                    BidResult.bidwinnr_nm.contains(query),
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

    return _apply_page_limit(_paginate_without_count(db, stmt, page_number))


def get_announcement_detail(db: Session, pk: int) -> dict[str, Any] | None:
    """공고 상세 + 유사 공고 + 기관 과거 낙찰 이력 (원본 BidDetailView 이식)."""
    instance = db.get(BidAnnouncement, pk)
    if instance is None:
        return None

    bid = latest_announcement_for_instance(db, instance)

    similar_stmt = similar_announcement_latest_filter(
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
    # DDL 보존을 위해 모델에 비영속 필드를 추가하지 않고 동적 할당합니다.
    result.resolved_winning_rate = result.display_winning_rate(db)  # type: ignore[attr-defined]
    for row in related_results:
        row.resolved_winning_rate = row.display_winning_rate(db)  # type: ignore[attr-defined]

    return {
        "result": result,
        "related_results": related_results,
        "raw_json": result.raw_data,
    }
