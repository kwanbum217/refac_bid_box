"""
tests/test_detail_recommendations.py

공고 상세의 '비슷한 진행 중 공고'와 과거 사례 선정 규칙을 검증합니다.
분야 일치, 마감 전 공고만, 제목 중복 제거, 공고명 유사도 우선, 기관 부족 시
유사 기관 보충 표지를 확인합니다.
"""

from datetime import timedelta

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-NTCE-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기본 공고명",
        "dminstt_nm": "수요기관A",
        "ntce_instt_nm": "공고기관A",
        "category": "Servc",
        "base_amount": 10000000,
        "presmpt_prce": 10000000,
        "bid_ntce_dt": now,
        "bid_clse_dt": now + timedelta(days=30),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-RES-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기본 낙찰명",
        "bidwinnr_nm": "낙찰업체A",
        "dminstt_nm": "수요기관A",
        "category": "Servc",
        "sucsf_bid_amt": 9000000,
        "sucsf_bid_rate": 90.0,
        "rl_openg_dt": now - timedelta(days=10),
        "collected_at": now - timedelta(days=10),
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_past_results_never_cross_category(isolated_db):
    """(a) 과거 사례는 현재 공고와 같은 분야 결과만 남깁니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="PAST-CAT-TARGET",
        bid_ntce_nm="하수관로 정비공사",
        category="Servc",
        bid_ntce_dt=now,
    )
    servc_result = _add_result(
        isolated_db,
        bid_ntce_no="PAST-CAT-SERVC",
        bid_ntce_nm="하수관로 정비공사",
        category="Servc",
        rl_openg_dt=now - timedelta(days=5),
    )
    thng_result = _add_result(
        isolated_db,
        bid_ntce_no="PAST-CAT-THNG",
        bid_ntce_nm="하수관로 정비공사 자재 구매",
        category="Thng",
        rl_openg_dt=now - timedelta(days=1),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    past = detail["past_results"]
    assert past
    assert {row.category for row in past} == {"Servc"}
    past_ids = {row.id for row in past}
    assert servc_result.id in past_ids
    assert thng_result.id not in past_ids


def test_recommendations_exclude_closed_and_open_other_institution(isolated_db):
    """(b) 추천은 마감 전 공고만 담고, 같은 분야의 다른 기관 공고도 유사하면 담습니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-TARGET",
        bid_ntce_nm="하수관로 정비사업",
        bid_ntce_dt=now,
    )
    open_same = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-OPEN-SAME",
        bid_ntce_nm="하수관로 정비사업 2차",
        bid_ntce_dt=now - timedelta(days=1),
        bid_clse_dt=now + timedelta(days=5),
    )
    closed_same = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-CLOSED-SAME",
        bid_ntce_nm="하수관로 정비사업 3차",
        bid_ntce_dt=now - timedelta(days=2),
        bid_clse_dt=now - timedelta(days=1),
    )
    null_deadline = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-NULL-SAME",
        bid_ntce_nm="하수관로 정비사업 4차",
        bid_ntce_dt=now - timedelta(days=3),
        bid_clse_dt=None,
    )
    open_other = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-OPEN-OTHER",
        bid_ntce_nm="하수관로 정비사업",
        dminstt_nm="수요기관B",
        bid_ntce_dt=now - timedelta(days=4),
        bid_clse_dt=now + timedelta(days=7),
    )
    closed_other = _add_announcement(
        isolated_db,
        bid_ntce_no="REC-CLOSED-OTHER",
        bid_ntce_nm="하수관로 정비사업",
        dminstt_nm="수요기관C",
        bid_ntce_dt=now - timedelta(days=5),
        bid_clse_dt=now - timedelta(days=2),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    similar_ids = {row.id for row in detail["similar_bids"]}
    assert open_same.id in similar_ids
    assert open_other.id in similar_ids
    assert closed_same.id not in similar_ids
    assert null_deadline.id not in similar_ids
    assert closed_other.id not in similar_ids
    assert target.id not in similar_ids
    assert all(
        row.bid_clse_dt is not None and row.bid_clse_dt >= now for row in detail["similar_bids"]
    )


def test_recommendations_dedupe_same_title(isolated_db):
    """(c) 공백과 괄호만 다른 같은 제목 공고는 하나만 남깁니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="DEDUPE-TARGET",
        bid_ntce_nm="업무용 차량 임차계약",
        bid_ntce_dt=now,
    )
    first = _add_announcement(
        isolated_db,
        bid_ntce_no="DEDUPE-FIRST",
        bid_ntce_nm="업무용 차량 임차계약",
        bid_ntce_dt=now - timedelta(days=1),
    )
    second = _add_announcement(
        isolated_db,
        bid_ntce_no="DEDUPE-SECOND",
        bid_ntce_nm="업무용 차량 임차계약(재공고)",
        bid_ntce_dt=now - timedelta(days=2),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    similar_ids = [row.id for row in detail["similar_bids"]]
    duplicated = [row_id for row_id in similar_ids if row_id in {first.id, second.id}]
    assert len(duplicated) == 1


def test_recommendations_rank_similarity_before_recency(isolated_db):
    """(d) 공고명 유사도가 높은 공고가 더 최신인 무관 공고보다 앞섭니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="RANK-TARGET",
        bid_ntce_nm="하수관로 정비사업 GRP맨홀 구입",
        bid_ntce_dt=now,
    )
    similar_but_older = _add_announcement(
        isolated_db,
        bid_ntce_no="RANK-SIMILAR",
        bid_ntce_nm="하수관로 정비사업 GRP맨홀 구입",
        bid_ntce_dt=now - timedelta(days=10),
    )
    unrelated_but_newer = _add_announcement(
        isolated_db,
        bid_ntce_no="RANK-UNRELATED",
        bid_ntce_nm="사무용 가구 구입",
        bid_ntce_dt=now,
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    similar_ids = [row.id for row in detail["similar_bids"]]
    assert similar_ids[0] == similar_but_older.id
    assert similar_ids.index(similar_but_older.id) < similar_ids.index(unrelated_but_newer.id)


def test_past_results_fill_with_related_institutions_and_label(isolated_db):
    """(e) 같은 기관 결과가 5건 미만일 때만 유사 기관이 채워지고 표지가 붙습니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="FILL-TARGET",
        bid_ntce_nm="늘봄학교 프로그램 운영 용역",
        bid_ntce_dt=now,
    )
    same_agency = [
        _add_result(
            isolated_db,
            bid_ntce_no=f"FILL-SAME-{index}",
            bid_ntce_nm="늘봄학교 프로그램 운영 용역",
            rl_openg_dt=now - timedelta(days=index + 1),
        )
        for index in range(2)
    ]
    related_agency = [
        _add_result(
            isolated_db,
            bid_ntce_no=f"FILL-OTHER-{index}",
            bid_ntce_nm="늘봄학교 프로그램 운영 위탁",
            dminstt_nm="수요기관B",
            rl_openg_dt=now - timedelta(days=index + 1),
        )
        for index in range(3)
    ]
    unrelated_agency = _add_result(
        isolated_db,
        bid_ntce_no="FILL-UNRELATED",
        bid_ntce_nm="급식용 우유 구매",
        dminstt_nm="수요기관C",
        rl_openg_dt=now - timedelta(days=1),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    past = detail["past_results"]
    assert len(past) == 5
    labels = [getattr(row, "institution_match_label", "") for row in past]
    assert labels[:2] == ["같은 기관", "같은 기관"]
    assert labels[2:] == ["유사 기관", "유사 기관", "유사 기관"]
    assert {row.id for row in same_agency} <= {row.id for row in past}
    assert {row.id for row in related_agency} <= {row.id for row in past}
    assert unrelated_agency.id not in {row.id for row in past}
    assert {row.category for row in past} == {"Servc"}


def test_past_results_do_not_fill_when_same_agency_is_enough(isolated_db):
    """(e) 같은 기관 결과가 5건 이상이면 유사 기관 보충이 일어나지 않습니다."""
    now = utcnow()
    target = _add_announcement(
        isolated_db,
        bid_ntce_no="FULL-TARGET",
        bid_ntce_nm="늘봄학교 프로그램 운영 용역",
        bid_ntce_dt=now,
    )
    same_agency = [
        _add_result(
            isolated_db,
            bid_ntce_no=f"FULL-SAME-{index}",
            bid_ntce_nm="늘봄학교 프로그램 운영 용역",
            rl_openg_dt=now - timedelta(days=index + 1),
        )
        for index in range(5)
    ]
    other_agency = _add_result(
        isolated_db,
        bid_ntce_no="FULL-OTHER",
        bid_ntce_nm="늘봄학교 프로그램 운영 위탁",
        dminstt_nm="수요기관B",
        rl_openg_dt=now - timedelta(days=1),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target.id)
    assert detail is not None

    past = detail["past_results"]
    assert {row.id for row in past} == {row.id for row in same_agency}
    assert all(getattr(row, "institution_match_label", "") == "같은 기관" for row in past)
    assert other_agency.id not in {row.id for row in past}


def test_announcement_name_tokens_and_similarity():
    """(f) 핵심어 추출은 연도·차수·일반어를 빼고, 유사도는 겹침 비율입니다."""
    tokens = bid_queries.announcement_name_tokens(
        "2027학년도 대구남산초등학교 늘봄학교 프로그램(맞춤형 및 선택형) 운영 용역 2단계"
    )
    assert "대구남산초등학교" in tokens
    assert "늘봄학교" in tokens
    assert "프로그램" in tokens
    assert "2027" not in tokens
    assert "2027학년도" not in tokens
    assert "2단계" not in tokens
    assert "용역" not in tokens
    assert "맞춤형" not in tokens

    assert (
        bid_queries.announcement_name_similarity(
            "하수관로 정비사업 GRP맨홀 구입",
            "2026년 하수관로 정비사업(2차) GRP맨홀 구입",
        )
        == 1.0
    )
    assert bid_queries.announcement_name_similarity("하수관로 정비사업", "사무용 가구 구입") == 0.0
