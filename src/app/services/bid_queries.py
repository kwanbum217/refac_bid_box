"""
src/app/services/bid_queries.py

입찰공고/낙찰결과 목록 조회 (원본 apps/bids/views.py 질의 로직 1:1 이식).
지역 그룹, 정렬 키, 최신 차수, count 없는 offset 페이지네이션을 그대로 보존합니다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, and_, case, func, or_, select, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, aliased

from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import (
    BidAnnouncement,
    BidResult,
    preload_matching_announcements,
)
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.services.demand_institutions import describe_contract_regime
from src.app.services.evaluation_rules import resolve_evaluation_rule_from_raw_data
from src.ml.model_registry import CATEGORY_DEFAULT_MODELS

TOP_INDUSTRY_CHOICES_CACHE_KEY = "bid_queries:top_industry_choices:200"
TOP_INDUSTRY_CHOICES_CACHE_TTL = 3600  # 1 hour
_INDUSTRY_NAME_CODE_PATTERN = re.compile(r"([^\/\[\],]+)\/(\d{4})(?!\d)")


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


def normalize_license_code(lic: str | None) -> str:
    candidate = (lic or "").strip()
    return candidate if len(candidate) == 4 and candidate.isdigit() else ""


# 4개 업종(파견, 경비업, 위생관리용역업, 유료직업소개업)의 확정 면허 코드 매핑입니다.
# 명칭 부분 문자열로 연결하지 않고 코드 묶음으로만 판정합니다. 7740 가축방역위생관리업은
# 별개 업종이라 포함하지 않습니다.
BID_INDUSTRY_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("dispatch", "파견", ("1172",)),
    ("security", "경비업", ("1164", "1167", "1165", "1168", "2775")),
    ("sanitation", "위생관리용역업", ("1162",)),
    ("job_placement", "유료직업소개업", ("5603", "5604", "5601", "5602")),
)
BID_INDUSTRY_CODES: tuple[str, ...] = tuple(
    code for _key, _label, codes in BID_INDUSTRY_GROUPS for code in codes
)
BID_INDUSTRY_CODE_SET = frozenset(BID_INDUSTRY_CODES)
# 4개 업종을 모두 고르면 합집합 전체를 넘겨야 하므로 상한은 합집합 크기 이상입니다.
MAX_LICENSE_FILTER_CODES = max(10, len(BID_INDUSTRY_CODES))


def industry_filter_codes(lic: str | None) -> list[str]:
    """업종 선택값을 4개 업종 확정 코드 안으로 좁힌 목록으로 돌려줍니다.

    선택이 없거나 모두 4개 업종 밖이면 4개 업종 전체를 돌려줍니다. 이 값이 목록
    질의의 기본 조건이 되어, 업종 제한 행이 없는 공고는 목록에서 빠집니다.
    """
    selected = [code for code in normalize_license_codes(lic) if code in BID_INDUSTRY_CODE_SET]
    return selected or list(BID_INDUSTRY_CODES)


def industry_groups_payload(selected_codes: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """화면의 업종 선택 위젯이 쓸 그룹 목록입니다."""
    selected = set(selected_codes) if selected_codes is not None else set(BID_INDUSTRY_CODES)
    return [
        {
            "key": key,
            "label": label,
            "codes": list(codes),
            "codes_csv": ",".join(codes),
            "selected": set(codes) <= selected,
        }
        for key, label, codes in BID_INDUSTRY_GROUPS
    ]


def normalize_license_codes(lic: str | None) -> list[str]:
    """쉼표로 구분한 업종 코드를 정규화합니다.

    각 토큰의 앞뒤 공백을 제거해 4자리 숫자만 남기고, 처음 나온 순서를 유지하며
    중복을 제거합니다. 필터 문자열이 비대해지지 않도록 최대 MAX_LICENSE_FILTER_CODES
    개까지만 받습니다.
    """
    codes: list[str] = []
    seen: set[str] = set()
    for token in (lic or "").split(","):
        candidate = token.strip()
        if len(candidate) != 4 or not candidate.isdigit():
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        codes.append(candidate)
        if len(codes) >= MAX_LICENSE_FILTER_CODES:
            break
    return codes


def get_top_industry_choices(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    cached = cache.get(TOP_INDUSTRY_CHOICES_CACHE_KEY)
    if isinstance(cached, list):
        return cached

    rows = db.execute(
        select(
            BidAnnouncementLicenseLimit.bid_ntce_no,
            BidAnnouncementLicenseLimit.lcns_lmt_nm,
            BidAnnouncementLicenseLimit.permsn_indstryty_list,
        ).where(
            or_(
                BidAnnouncementLicenseLimit.lcns_lmt_nm.is_not(None),
                BidAnnouncementLicenseLimit.permsn_indstryty_list.is_not(None),
            )
        )
    ).all()

    code_notices: dict[str, set[str]] = {}
    code_names: dict[str, Counter[str]] = {}

    for ntce_no, lcns_nm, permsn_list in rows:
        texts = [t for t in (lcns_nm, permsn_list) if t]
        for text in texts:
            for match in _INDUSTRY_NAME_CODE_PATTERN.finditer(text):
                raw_name = match.group(1).strip()
                code = match.group(2)
                if not raw_name or not code:
                    continue
                code_notices.setdefault(code, set()).add(ntce_no)
                code_names.setdefault(code, Counter())[raw_name] += 1

    choices: list[dict[str, Any]] = []
    for code, notices in code_notices.items():
        count = len(notices)
        names = code_names.get(code)
        most_common_name = names.most_common(1)[0][0] if names else code
        choices.append(
            {
                "code": code,
                "name": most_common_name,
                "count": count,
                "label": f"{most_common_name} ({code})",
            }
        )

    choices.sort(key=lambda item: (-item["count"], item["code"]))
    top_choices = choices[:limit]

    cache.set(TOP_INDUSTRY_CHOICES_CACHE_KEY, top_choices, TOP_INDUSTRY_CHOICES_CACHE_TTL)
    return top_choices


def _region_match_clause(aliases) -> Any:
    clauses = []
    for alias in aliases:
        clauses.append(BidAnnouncement.dminstt_nm.contains(alias))
        clauses.append(BidAnnouncement.ntce_instt_nm.contains(alias))
    return or_(*clauses)


def _result_region_match_clause(aliases) -> Any:
    return or_(*[BidResult.dminstt_nm.contains(alias) for alias in aliases])


def _participation_region_match_clause(region_code: str) -> Any:
    """참가가능지역 행이 선택 지역을 포함하는 공고만 통과시킵니다.

    기존 기관명 기반 지역 필터와 달리 참가가능지역 테이블을 기준으로 봅니다.
    행이 없는 공고는 어떤 지역을 골라도 통과하지 못합니다.
    """
    aliases = BID_REGION_BY_CODE[region_code]["aliases"]
    like_clauses = [
        BidAnnouncementParticipationRegion.prtcpt_psbl_rgn_nm.contains(alias) for alias in aliases
    ]
    return (
        select(1)
        .where(
            BidAnnouncementParticipationRegion.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            BidAnnouncementParticipationRegion.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
            or_(*like_clauses),
        )
        .exists()
    )


def institution_region_label(dminstt_nm: str | None, ntce_instt_nm: str | None) -> str:
    """수요기관·공고기관명에서 발주처 지역(시·도) 라벨을 찾습니다."""
    text = f"{dminstt_nm or ''} {ntce_instt_nm or ''}"
    for item in BID_REGION_CHOICES:
        if any(alias in text for alias in item["aliases"]):
            return str(item["label"])
    return ""


# 목록 지역 칸의 참가가능 한 줄에 들어가는 글자 수다. 이 안에 끝나는 지역명만
# 그대로 두고, 나머지가 있으면 말줄임을 붙여 행이 아래로 늘지 않게 한다.
PARTICIPATION_REGION_PREVIEW_CHARS = 12


def participation_region_preview(names: Iterable[str]) -> str:
    """참가가능지역을 목록 한 줄용 문자열로 줄입니다."""
    cleaned = list(dict.fromkeys(name.strip() for name in names if name and name.strip()))
    if not cleaned:
        return ""
    shown: list[str] = []
    used = 0
    for name in cleaned:
        extra = len(name) if not shown else len(name) + 2
        if shown and used + extra > PARTICIPATION_REGION_PREVIEW_CHARS:
            break
        shown.append(name)
        used += extra
    if len(shown) == len(cleaned):
        return ", ".join(shown)
    if not shown:
        shown = [cleaned[0]]
    return f"{', '.join(shown)}..."


def load_announcement_region_display(db: Session, bids: Iterable[BidAnnouncement]) -> None:
    """목록 행에 발주처 지역과 참가가능지역 표시값을 붙입니다.

    발주처 지역은 기관명 기반(정렬·표시용)이고, 참가가능지역은 참가가능지역
    테이블에서 읽습니다. 행이 없으면 빈 목록으로 두어 화면이 '참가 지역 제한 정보
    없음' 을 표시할 수 있게 합니다.
    """
    rows = list(bids)
    for bid in rows:
        bid.institution_region = institution_region_label(  # type: ignore[attr-defined]
            bid.dminstt_nm, bid.ntce_instt_nm
        )
        bid.participation_regions = []  # type: ignore[attr-defined]
        bid.participation_region_preview = ""  # type: ignore[attr-defined]

    pairs = {(bid.bid_ntce_no, bid.bid_ntce_ord or "000") for bid in rows}
    if not pairs:
        return

    region_rows = (
        db.execute(
            select(BidAnnouncementParticipationRegion).where(
                tuple_(
                    BidAnnouncementParticipationRegion.bid_ntce_no,
                    BidAnnouncementParticipationRegion.bid_ntce_ord,
                ).in_(pairs)
            )
        )
        .scalars()
        .all()
    )

    def _region_order(row: BidAnnouncementParticipationRegion) -> tuple[int, str, int]:
        sno = row.lmt_sno or ""
        return (int(sno) if sno.isdigit() else 10**9, sno, row.id)

    names_by_key: dict[tuple[str, str], list[str]] = {}
    for row in sorted(region_rows, key=_region_order):
        if not row.prtcpt_psbl_rgn_nm:
            continue
        names_by_key.setdefault((row.bid_ntce_no, row.bid_ntce_ord), []).append(
            row.prtcpt_psbl_rgn_nm
        )

    for bid in rows:
        names = names_by_key.get((bid.bid_ntce_no, bid.bid_ntce_ord or "000"))
        if names:
            regions = list(dict.fromkeys(names))
            bid.participation_regions = regions  # type: ignore[attr-defined]
            bid.participation_region_preview = participation_region_preview(regions)  # type: ignore[attr-defined]


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


def is_qualification_analyzable(bid: BidAnnouncement) -> bool:
    """공고 상세의 적격심사 분석(점수와 입찰가격 보완)이 계산되는지 단건 판정합니다.

    분석 API 와 같은 두 조건을 봅니다. 규칙 판별이 차단되지 않고 예정가격 기준액이
    있어야 합니다. DB 를 조회하지 않으므로 목록 한 페이지분이나 검색 문서 생성에
    쓸 수 있습니다. 목록 뱃지와 qual 필터와 검색 문서가 모두 이 함수 하나를 씁니다.
    """
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    rule = resolve_evaluation_rule_from_raw_data(category=bid.category, raw_data=raw_data)
    if rule.is_blocked:
        return False
    reference = bid.prediction_reference_amount
    return reference is not None and reference > 0


def qualification_analyzable_ids(bids: Iterable[BidAnnouncement]) -> set[int]:
    """적격심사 분석이 계산되는 공고의 id 집합입니다. 판정은 단건 함수에 위임합니다."""
    return {bid.id for bid in bids if is_qualification_analyzable(bid)}


# DB 대체 경로는 판정이 파이썬 함수라 SQL 조건으로 밀어 넣을 수 없어, 정렬 순서대로
# 후보를 훑으며 통과 행을 모읍니다. 후보를 끝까지 훑으면 페이지 하나에 목록 전체를
# 읽게 되므로 스캔 상한을 둡니다. 상한에 닿으면 그때까지 모은 행으로 페이지를 만들고
# 다음 페이지는 없다고 봅니다(개발·테스트 대체 경로라 정확도보다 비용을 우선합니다).
QUALIFICATION_ONLY_CANDIDATE_LIMIT = 5_000
QUALIFICATION_ONLY_CHUNK_SIZE = 200


def _paginate_qualification_only(db: Session, stmt, page_number: int) -> OffsetPage:
    """적격심사 분석 대상만 모아 페이지를 만드는 개발·테스트용 DB 대체 경로입니다.

    운영 목록은 Meilisearch 경로를 타므로 이 함수는 MEILI_ENABLED 가 거짓일 때만
    쓰입니다. 정렬 순서대로 후보를 QUALIFICATION_ONLY_CHUNK_SIZE 행씩 읽으며 판정을
    통과한 행을 모으고, 앞 페이지의 통과 행은 건너뜁니다. 통과 행이 PAGE_SIZE 를
    넘으면 다음 페이지가 있다고 표시합니다.
    """
    page_number = max(page_number, 1)
    skip_remaining = (page_number - 1) * PAGE_SIZE
    collected: list[BidAnnouncement] = []
    has_next = False
    scanned = 0
    offset = 0
    while scanned < QUALIFICATION_ONLY_CANDIDATE_LIMIT:
        chunk = _with_mysql_execution_limit(
            stmt.offset(offset).limit(QUALIFICATION_ONLY_CHUNK_SIZE)
        )
        try:
            rows = db.execute(chunk).scalars().all()
        except DBAPIError as exc:
            if not _is_mysql_query_timeout(exc):
                raise
            from src.app.services.search_index import SearchBackendUnavailable

            raise SearchBackendUnavailable("MySQL 검색 fallback 실행시간을 초과했습니다.") from exc
        if not rows:
            break
        scanned += len(rows)
        offset += len(rows)
        for row in rows:
            if not is_qualification_analyzable(row):
                continue
            if skip_remaining > 0:
                skip_remaining -= 1
                continue
            if len(collected) >= PAGE_SIZE:
                has_next = True
                break
            collected.append(row)
        if has_next or len(rows) < QUALIFICATION_ONLY_CHUNK_SIZE:
            break
    return OffsetPage(
        object_list=collected, number=page_number, per_page=PAGE_SIZE, has_next=has_next
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
    license_codes: list[str] | None = None,
    qualification_only: bool = False,
) -> OffsetPage:
    from src.app.services.search_index import MeiliSearchClient

    search_kwargs: dict[str, Any] = {
        "query": query,
        "dataset": dataset,
        "category": category,
        "region": region,
        "sort": sort,
        "offset": (page_number - 1) * PAGE_SIZE,
        "limit": PAGE_SIZE,
    }
    # 코드 하나면 기존 단일 코드 인자를 그대로 써 검색 필터 문자열을 보존합니다.
    if license_codes:
        if len(license_codes) == 1:
            search_kwargs["license_code"] = license_codes[0]
        else:
            search_kwargs["license_codes"] = license_codes
    if qualification_only:
        search_kwargs["qualification_only"] = True
    result = MeiliSearchClient().search(**search_kwargs)
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
    lic: str | None = None,
    qualification_only: bool = False,
) -> OffsetPage:
    region_code = normalize_region_code(region)
    license_codes = normalize_license_codes(lic)
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
                license_codes=license_codes or None,
                qualification_only=qualification_only,
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
        stmt = stmt.where(_participation_region_match_clause(region_code))

    if license_codes:
        # 여러 코드는 각 코드의 LIKE 조건을 OR 로 묶어, 하나라도 참가자격이면 통과시킵니다.
        like_clauses: list[Any] = []
        for code in license_codes:
            pattern = f"%/{code}%"
            like_clauses.append(BidAnnouncementLicenseLimit.lcns_lmt_nm.like(pattern))
            like_clauses.append(BidAnnouncementLicenseLimit.permsn_indstryty_list.like(pattern))
        has_license = (
            select(1)
            .where(
                BidAnnouncementLicenseLimit.bid_ntce_no == BidAnnouncement.bid_ntce_no,
                BidAnnouncementLicenseLimit.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
                or_(*like_clauses),
            )
            .exists()
        )
        stmt = stmt.where(has_license)

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

    if qualification_only:
        # 적격심사 분석 대상은 용역(Servc) 공고에서만 계산되므로 후보를 먼저 좁힙니다.
        stmt = stmt.where(BidAnnouncement.category == "Servc")
        return _apply_page_limit(_paginate_qualification_only(db, stmt, page_number))

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
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    institution_code = str(raw_data.get("dminsttCd") or "").strip()
    institution = db.get(G2BDemandInstitution, institution_code) if institution_code else None

    similar_stmt = similar_announcement_latest_filter(
        select(BidAnnouncement).where(
            BidAnnouncement.category == bid.category,
            BidAnnouncement.dminstt_nm == bid.dminstt_nm,
        )
    ).where(BidAnnouncement.id != bid.id)
    # 최신 공고순 정렬. (dminstt_nm, category, bid_ntce_dt) 인덱스가 이 정렬을 받칩니다
    # (migrations/versions/f5a6b7c8d9e0).
    similar_stmt = similar_stmt.order_by(
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    )
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
        "contract_regime": describe_contract_regime(raw_data, bid.cntrct_mthd_nm, institution),
        "similar_bids": list(similar_bids),
        "past_results": past_results,
        "restrictions": get_announcement_restrictions(db, bid),
        "is_negotiation": _is_negotiation(bid),
        "default_prediction_model": DEFAULT_PREDICTION_MODEL_BY_CATEGORY.get(
            bid.category, DEFAULT_PREDICTION_MODEL
        ),
    }


def _is_negotiation(bid: BidAnnouncement) -> bool:
    raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    sucsfbid = str(raw.get("sucsfbidMthdNm") or "")
    cntrct = str(bid.cntrct_mthd_nm or "")
    bid_methd = str(raw.get("bidMethdNm") or "")
    return "협상" in sucsfbid or "협상" in cntrct or "협상" in bid_methd


def _sort_key(value: str | None) -> tuple[int, str]:
    text = value or ""
    return (int(text), text) if text.isdigit() else (10**9, text)


def get_announcement_restrictions(db: Session, bid: BidAnnouncement) -> dict[str, Any]:
    """공고의 면허제한 그룹과 참가가능지역.

    그룹 간 결합 의미(AND/OR)는 확인되지 않아 해석하지 않고 그룹별로 나열합니다.
    수집은 2026-09-14 이후 신규 공고부터라, 과거 공고는 공고 API 의 제한 여부만 남습니다.
    """
    license_rows = (
        db.execute(
            select(BidAnnouncementLicenseLimit).where(
                BidAnnouncementLicenseLimit.bid_ntce_no == bid.bid_ntce_no,
                BidAnnouncementLicenseLimit.bid_ntce_ord == bid.bid_ntce_ord,
            )
        )
        .scalars()
        .all()
    )
    region_rows = (
        db.execute(
            select(BidAnnouncementParticipationRegion).where(
                BidAnnouncementParticipationRegion.bid_ntce_no == bid.bid_ntce_no,
                BidAnnouncementParticipationRegion.bid_ntce_ord == bid.bid_ntce_ord,
            )
        )
        .scalars()
        .all()
    )

    groups: dict[str, list[BidAnnouncementLicenseLimit]] = {}
    for row in sorted(license_rows, key=lambda r: (_sort_key(r.lmt_grp_no), _sort_key(r.lmt_sno))):
        groups.setdefault(row.lmt_grp_no, []).append(row)

    raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    industry_limited = (raw.get("indstrytyLmtYn") or "").strip().upper() or None
    collected = bool(license_rows or region_rows)

    uncollected_legacy = False
    if not collected and bid.bid_ntce_dt is not None and bid.bid_clse_dt is not None:
        ntce_dt = (
            bid.bid_ntce_dt.replace(tzinfo=None) if bid.bid_ntce_dt.tzinfo else bid.bid_ntce_dt
        )
        clse_dt = (
            bid.bid_clse_dt.replace(tzinfo=None) if bid.bid_clse_dt.tzinfo else bid.bid_clse_dt
        )
        uncollected_legacy = (ntce_dt < datetime(2025, 7, 1, 0, 0)) and (clse_dt >= utcnow())

    return {
        "license_groups": [
            {
                "group_no": group_no,
                "licenses": [
                    {"name": row.lcns_lmt_nm, "permitted": row.permsn_indstryty_list}
                    for row in rows
                    if row.lcns_lmt_nm or row.permsn_indstryty_list
                ],
            }
            for group_no, rows in groups.items()
        ],
        "regions": [
            row.prtcpt_psbl_rgn_nm
            for row in sorted(region_rows, key=lambda r: _sort_key(r.lmt_sno))
            if row.prtcpt_psbl_rgn_nm
        ],
        "industry_limited": industry_limited,
        "collected": collected,
        "uncollected_legacy": uncollected_legacy,
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

    # 본건 및 관련 낙찰 공고를 일괄 선채움하여 N+1 질의를 방지합니다.
    preload_matching_announcements(db, [result, *related_results])

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
