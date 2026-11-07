"""비예가(PQ) 공고의 후속 가격입찰 공고 연결 시험.

docs/analysis/pq_followup_match_20261107.md 5절 결정(사용자 승인)에 따라 매칭 키는
raw_data.bfSpecRgstNo 정확 일치만 쓴다. 1:N 분할 발주는 모두 목록으로 보이고,
기초금액·예정가격은 후속 공고 목록에 노출하지 않는다.
"""

from datetime import timedelta

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries

PROJECT_ROOT_DETAIL_TEMPLATE = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "src"
    / "app"
    / "templates"
    / "bids"
    / "detail.html"
)


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-PQ-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기본 공고명",
        "dminstt_nm": "수요기관A",
        "ntce_instt_nm": "공고기관A",
        "category": "Servc",
        "base_amount": 10000000,
        "presmpt_prce": 10000000,
        "bid_ntce_dt": now,
        "bid_clse_dt": None,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _pq_raw_data(spec_no: str | None, method: str = "비예가") -> dict:
    raw = {
        "prearngPrceDcsnMthdNm": method,
        "sucsfbidMthdNm": "적격심사제-조달청",
        "sucsfbidLwltRate": "79.995",
    }
    if spec_no is not None:
        raw["bfSpecRgstNo"] = spec_no
    return raw


def _pq_notice(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "PQ-NOTICE-001",
        "bid_ntce_nm": "사업수행능력평가서 제출 안내 공고",
        "bid_ntce_dt": now,
        "bid_clse_dt": None,
        "raw_data": _pq_raw_data("R26BD00160160"),
    }
    payload.update(overrides)
    return _add_announcement(db, **payload)


def _followup_notice(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "PQ-FOLLOW-001",
        "bid_ntce_nm": "사업수행능력평가 후 가격입찰 공고",
        "bid_ntce_dt": now + timedelta(days=40),
        "bid_clse_dt": now + timedelta(days=50),
        "raw_data": _pq_raw_data("R26BD00160160", method="복수예가"),
    }
    payload.update(overrides)
    return _add_announcement(db, **payload)


def test_same_spec_number_followup_is_listed(isolated_db):
    """(a) 사전규격등록번호가 같은 후속 공고가 목록에 나옵니다."""
    target = _pq_notice(isolated_db)
    followup = _followup_notice(isolated_db)

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)

    assert detail is not None
    followup_ids = [row.id for row in detail["followup_bids"]]
    assert followup_ids == [followup.id]


def test_missing_or_different_spec_number_is_not_listed(isolated_db):
    """(b) 사전규격등록번호가 비었거나 다르면 목록에 나오지 않습니다."""
    target = _pq_notice(isolated_db, bid_ntce_no="PQ-NOTICE-EMPTY", raw_data=_pq_raw_data(None))
    _followup_notice(isolated_db, bid_ntce_no="PQ-FOLLOW-EMPTY")

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)

    assert detail is not None
    assert detail["followup_bids"] == []


def test_same_institution_and_amount_without_spec_number_is_not_listed(isolated_db):
    """(b) 이름·기관·추정가격이 같아도 키가 다르면 붙이지 않습니다 (결정 3)."""
    target = _pq_notice(isolated_db, bid_ntce_no="PQ-NOTICE-KEYED")
    _followup_notice(
        isolated_db,
        bid_ntce_no="PQ-FOLLOW-OTHER-KEY",
        bid_ntce_nm=target.bid_ntce_nm.replace("안내", "후 가격입찰"),
        raw_data=_pq_raw_data("R26BD00999999", method="복수예가"),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)

    assert detail is not None
    assert detail["followup_bids"] == []


def test_split_order_lists_every_followup(isolated_db):
    """(c) 1:N 분할 발주는 후속 공고를 모두 목록으로 보여 줍니다 (결정 2)."""
    target = _pq_notice(isolated_db, bid_ntce_no="PQ-NOTICE-SPLIT", base_amount=8556454545)
    first = _followup_notice(
        isolated_db,
        bid_ntce_no="PQ-FOLLOW-SPLIT-1",
        bid_ntce_nm="1지구 가격입찰",
        base_amount=3098400000,
    )
    second = _followup_notice(
        isolated_db,
        bid_ntce_no="PQ-FOLLOW-SPLIT-2",
        bid_ntce_nm="2지구 가격입찰",
        base_amount=3215300000,
        bid_ntce_dt=utcnow() + timedelta(days=45),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)

    assert detail is not None
    assert [row.id for row in detail["followup_bids"]] == [first.id, second.id]


def test_non_pq_announcement_does_not_query_followups(isolated_db, monkeypatch):
    """(d) 비예가가 아닌 공고에서는 후보 질의를 실행하지 않습니다."""
    target = _pq_notice(
        isolated_db,
        bid_ntce_no="PQ-NOTICE-NORMAL-METHOD",
        raw_data=_pq_raw_data("R26BD00160160", method="복수예가"),
    )
    _followup_notice(
        isolated_db,
        bid_ntce_no="PQ-FOLLOW-OTHER-KEY",
        raw_data=_pq_raw_data("R26BD00999999", method="복수예가"),
    )

    statements: list[str] = []
    original_execute = isolated_db.execute

    def _record(statement, *args, **kwargs):
        statements.append(str(statement))
        return original_execute(statement, *args, **kwargs)

    # 커밋 뒤 만료된 속성을 미리 읽어 지연 로드가 기록에 섞이지 않게 합니다.
    _ = target.raw_data, target.bid_ntce_dt
    monkeypatch.setattr(isolated_db, "execute", _record)

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)

    assert detail is not None
    assert detail["followup_bids"] == []
    # 상세 조회 안에서 후보 질의(수요기관 조건 + 공고일 범위)가 나가지 않아야 합니다.
    assert not [
        statement
        for statement in statements
        if "bid_announcements.dminstt_nm = " in statement
        and "bid_announcements.bid_ntce_dt >= " in statement
    ]

    statements.clear()
    assert bid_queries.get_followup_announcements(isolated_db, target) == []
    assert statements == []


def test_template_shows_followup_list_without_amounts():
    """(e) 템플릿에 후속 공고 목록이 있고 기초금액·예정가격 표시는 없습니다."""
    source = PROJECT_ROOT_DETAIL_TEMPLATE.read_text(encoding="utf-8")

    assert "후속 가격입찰 공고" in source
    assert "아직 연결된 후속 공고가 없습니다" in source
    assert "followup_bids" in source
    assert "show_followup_bids" in source

    block_start = source.index('id="followup-bids"')
    block_end = source.index('id="recommend-blocked-gap"')
    block = source[block_start:block_end]
    assert "기초금액" not in block
    assert "예정가격" not in block
    assert "base_amount" not in block
    assert "display_base_amount" not in block
