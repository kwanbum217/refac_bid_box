"""tests/test_bid_list_amount_contract_filter_20261125.py

공고 목록(/bids/) 금액 구간·계약방법 필터 검증.

Capsule 계약 (a)~(f):
  (a) 금액 구간 경계값(1억 정확히, 5억 정확히)이 올바른 구간에 들어간다.
  (b) 추정가격이 없으면 기초금액으로 물러난다.
  (c) 수의계약 제외·수의계약만이 계약방법명 기준으로 거른다.
  (d) SQL 경로와 Meilisearch(가짜 클라이언트) 경로가 같은 결과를 낸다.
  (e) 페이지 이동 링크에 amount·contract 파라미터가 유지된다.
  (f) 파라미터가 없으면 기존 결과와 같다.

공개 진입점인 /bids/ 라우트로 검증합니다. 새 필터는 기준 코드에서 질의
파라미터가 무시되므로 이 시험의 단언은 기준 코드에서 실패합니다.
"""

from __future__ import annotations

import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement
from src.app.services.search_index import SearchPage, announcement_document

# 사용자 결정(2026-10-31)의 금액대 4구간. 경계값은 상위 구간에 들어갑니다.
AMOUNT_RANGES = {
    "under_100m": (None, 100_000_000),
    "100m_500m": (100_000_000, 500_000_000),
    "500m_1b": (500_000_000, 1_000_000_000),
    "over_1b": (1_000_000_000, None),
}
SEARCH_CACHE_PREFIX = "search_ids:v1:"
BID_ID_PATTERN = re.compile(r'data-url="/bids/(\d+)/"')


@pytest.fixture
def auth_user(isolated_db):
    user = CustomUser(
        username="amount_contract_tester",
        password=make_password("pw-filter-1234"),
        email="amount-contract@example.com",
        nickname="금액계약 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


@pytest.fixture
def logged_in_client(auth_user):
    token = create_session(auth_user.id, auth_user.username)
    # 목록 검색 결과 캐시가 시험 사이에 남으면 가짜 색인 결과가 섞입니다.
    cache.delete_prefix(SEARCH_CACHE_PREFIX)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _add_announcement(
    db,
    bid_ntce_no: str,
    *,
    presmpt_prce: int | None = None,
    base_amount: int | None = None,
    cntrct_mthd_nm: str | None = None,
) -> BidAnnouncement:
    """공고와 파견 업종 제한 행을 넣고, 컬럼이 채워진 행을 돌려줍니다.

    요청마다 get_db 가 세션을 닫아 인스턴스가 분리되므로, 단언과 가짜 색인
    문서 작성에서 만료된 속성을 다시 읽지 않도록 마지막에 컬럼을 다시 채웁니다.
    """
    now = utcnow()
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"{bid_ntce_no} 공고",
        dminstt_nm="테스트발주기관",
        category="Servc",
        presmpt_prce=presmpt_prce,
        base_amount=base_amount,
        cntrct_mthd_nm=cntrct_mthd_nm,
        bid_ntce_dt=now,
        collected_at=now,
    )
    db.add(row)
    db.commit()
    # 공고 탐색은 4개 업종 제한 공고만 노출하므로 파견 업종 제한 행을 붙입니다.
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="파견업/1172",
            collected_at=now,
        )
    )
    db.commit()
    db.refresh(row)
    return row


def _rendered_ids(response) -> set[int]:
    assert response.status_code == 200
    return {int(match) for match in BID_ID_PATTERN.findall(response.text)}


def _use_sql_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)


class _FakeMeiliClient:
    """색인 문서로 같은 조건을 거르는 가짜 Meilisearch 클라이언트입니다.

    문서는 운영 색인과 같은 `announcement_document` 로 만들어, 색인 문서에
    금액·계약 판정 필드가 실제로 실리는지까지 함께 검증합니다.
    """

    def __init__(self, documents: list[dict], has_next: bool = False):
        self.documents = documents
        self.has_next = has_next
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        matched: list[int] = []
        for document in self.documents:
            if document["dataset"] != kwargs["dataset"]:
                continue
            if document.get("is_cancelled"):
                continue
            amount_band = kwargs.get("amount_band") or ""
            if amount_band:
                lower, upper = AMOUNT_RANGES[amount_band]
                amount = document.get("filter_amount")
                if amount is None:
                    continue
                if lower is not None and amount < lower:
                    continue
                if upper is not None and amount >= upper:
                    continue
            contract = kwargs.get("contract") or ""
            if contract == "only_private" and not document.get("is_private_contract"):
                continue
            if contract == "exclude_private" and document.get("is_private_contract"):
                continue
            matched.append(int(document["source_id"]))
        return SearchPage(ids=matched, has_next=self.has_next)


# --------------------------------------------------------------------------- #
# (a) 금액 구간 경계값
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("amount_band", "expected_numbers"),
    [
        ("under_100m", [99_999_999]),
        ("100m_500m", [100_000_000, 499_999_999]),
        ("500m_1b", [500_000_000, 999_999_999]),
        ("over_1b", [1_000_000_000]),
    ],
)
def test_amount_band_puts_boundary_values_in_upper_band(
    monkeypatch, logged_in_client, isolated_db, amount_band, expected_numbers
):
    """1억·5억 정확히는 상위 구간에 들어가고, 경계 바로 아래는 아래 구간에 남는다."""
    _use_sql_path(monkeypatch)
    expected_ids = set()
    for index, amount in enumerate(
        [99_999_999, 100_000_000, 499_999_999, 500_000_000, 999_999_999, 1_000_000_000]
    ):
        row = _add_announcement(
            isolated_db, f"AMT-BOUNDARY-{index}", presmpt_prce=amount, base_amount=amount
        )
        if amount in expected_numbers:
            expected_ids.add(row.id)

    response = logged_in_client.get("/bids/", params={"amount": amount_band})

    assert _rendered_ids(response) == expected_ids


# --------------------------------------------------------------------------- #
# (b) 추정가격이 없으면 기초금액
# --------------------------------------------------------------------------- #


def test_amount_band_falls_back_to_base_amount_when_presmpt_missing(
    monkeypatch, logged_in_client, isolated_db
):
    """추정가격이 비면 기초금액으로 구간을 정하고, 두 값이 모두 없으면 어느 구간에도 없다."""
    _use_sql_path(monkeypatch)
    fallback = _add_announcement(
        isolated_db, "AMT-FALLBACK", presmpt_prce=None, base_amount=300_000_000
    )
    missing = _add_announcement(isolated_db, "AMT-MISSING", presmpt_prce=None, base_amount=None)
    fallback_id, missing_id = fallback.id, missing.id

    mid = _rendered_ids(logged_in_client.get("/bids/", params={"amount": "100m_500m"}))
    under = _rendered_ids(logged_in_client.get("/bids/", params={"amount": "under_100m"}))
    over = _rendered_ids(logged_in_client.get("/bids/", params={"amount": "over_1b"}))

    assert fallback_id in mid
    assert fallback_id not in under
    assert fallback_id not in over
    assert missing_id not in mid | under | over


# --------------------------------------------------------------------------- #
# (c) 계약방법: 수의계약 제외 / 수의계약만
# --------------------------------------------------------------------------- #


def test_contract_filter_excludes_or_keeps_only_private_contracts(
    monkeypatch, logged_in_client, isolated_db
):
    """계약방법명에 '수의'가 있으면 수의계약이며, 값이 비어 있는 공고는 수의계약이 아니다."""
    _use_sql_path(monkeypatch)
    general = _add_announcement(isolated_db, "CTR-GENERAL", cntrct_mthd_nm="일반경쟁")
    limited = _add_announcement(isolated_db, "CTR-LIMITED", cntrct_mthd_nm="제한경쟁")
    private = _add_announcement(isolated_db, "CTR-PRIVATE", cntrct_mthd_nm="수의계약(소액수의)")
    blank = _add_announcement(isolated_db, "CTR-BLANK", cntrct_mthd_nm=None)
    general_id, limited_id, private_id, blank_id = (
        general.id,
        limited.id,
        private.id,
        blank.id,
    )

    excluded = _rendered_ids(logged_in_client.get("/bids/", params={"contract": "exclude_private"}))
    only = _rendered_ids(logged_in_client.get("/bids/", params={"contract": "only_private"}))

    assert excluded == {general_id, limited_id, blank_id}
    assert only == {private_id}


# --------------------------------------------------------------------------- #
# (d) SQL 경로와 Meilisearch 경로 결과 일치
# --------------------------------------------------------------------------- #


def test_amount_and_contract_filters_match_between_sql_and_meili(
    monkeypatch, logged_in_client, isolated_db
):
    """같은 조건에서 SQL 경로와 색인 문서 경로가 같은 공고 집합을 낸다."""
    rows = [
        _add_announcement(
            isolated_db, "PAR-MID-GENERAL", presmpt_prce=300_000_000, cntrct_mthd_nm="일반경쟁"
        ),
        _add_announcement(
            isolated_db, "PAR-MID-PRIVATE", presmpt_prce=200_000_000, cntrct_mthd_nm="수의계약"
        ),
        _add_announcement(
            isolated_db,
            "PAR-MID-FALLBACK",
            presmpt_prce=None,
            base_amount=150_000_000,
            cntrct_mthd_nm="제한경쟁",
        ),
        _add_announcement(
            isolated_db, "PAR-UNDER-GENERAL", presmpt_prce=50_000_000, cntrct_mthd_nm="일반경쟁"
        ),
        _add_announcement(
            isolated_db, "PAR-OVER-GENERAL", presmpt_prce=2_000_000_000, cntrct_mthd_nm="일반경쟁"
        ),
    ]
    # 기대값과 색인 문서는 요청 전에 만들어 둡니다(요청 뒤에는 세션이 닫혀 분리됨).
    documents = [announcement_document(row) for row in rows]
    # 100m_500m + 수의계약 제외: 일반경쟁 3억과, 추정가격 없이 기초금액 1.5억인
    # 제한경쟁 공고가 남습니다.
    expected_ids = {rows[0].id, rows[2].id}
    params = {"amount": "100m_500m", "contract": "exclude_private"}

    _use_sql_path(monkeypatch)
    sql_ids = _rendered_ids(logged_in_client.get("/bids/", params=params))

    fake_client = _FakeMeiliClient(documents)
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search", fake_client.search
    )
    cache.delete_prefix(SEARCH_CACHE_PREFIX)
    meili_ids = _rendered_ids(logged_in_client.get("/bids/", params=params))

    assert sql_ids == expected_ids
    assert meili_ids == sql_ids
    assert fake_client.calls[-1]["amount_band"] == "100m_500m"
    assert fake_client.calls[-1]["contract"] == "exclude_private"


# --------------------------------------------------------------------------- #
# (e) 페이지 링크에 amount·contract 유지
# --------------------------------------------------------------------------- #


def test_bids_page_preserves_amount_and_contract_in_pagination(
    monkeypatch, logged_in_client, isolated_db
):
    row = _add_announcement(
        isolated_db, "PAGINATE-AMOUNT", presmpt_prce=200_000_000, cntrct_mthd_nm="일반경쟁"
    )
    row_id = row.id

    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    search_mock = Mock(return_value=SearchPage(ids=[row_id], has_next=True))
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search_mock)
    cache.delete_prefix(SEARCH_CACHE_PREFIX)

    response = logged_in_client.get(
        "/bids/",
        params={"amount": "100m_500m", "contract": "exclude_private", "page": 1},
    )

    assert response.status_code == 200
    html = response.text
    assert 'name="amount"' in html
    assert 'name="contract"' in html
    assert "page=2" in html
    assert "&amount=100m_500m" in html
    assert "&contract=exclude_private" in html


# --------------------------------------------------------------------------- #
# (f) 파라미터가 없으면 기존 결과와 같다
# --------------------------------------------------------------------------- #


def test_no_amount_or_contract_param_keeps_previous_results(
    monkeypatch, logged_in_client, isolated_db
):
    """필터를 넘기지 않으면 금액·계약 조건 없이 이전과 같은 목록을 보여준다."""
    _use_sql_path(monkeypatch)
    rows = [
        _add_announcement(isolated_db, "NONE-A", presmpt_prce=50_000_000),
        _add_announcement(isolated_db, "NONE-B", base_amount=None),
        _add_announcement(isolated_db, "NONE-C", presmpt_prce=3_000_000_000),
    ]
    expected_ids = {row.id for row in rows}

    response = logged_in_client.get("/bids/")

    assert _rendered_ids(response) == expected_ids
    assert 'name="amount"' in response.text
    assert 'name="contract"' in response.text


def test_unknown_amount_and_contract_values_are_ignored(monkeypatch, logged_in_client, isolated_db):
    """허용 목록에 없는 값은 전체 조건으로 되돌린다."""
    _use_sql_path(monkeypatch)
    row_id = _add_announcement(isolated_db, "UNKNOWN-FILTER", presmpt_prce=50_000_000).id

    response = logged_in_client.get("/bids/", params={"amount": "bogus", "contract": "drop table"})

    assert _rendered_ids(response) == {row_id}
