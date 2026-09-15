"""
tests/test_rag_quarter_breakdown.py

분기별 시계열 집계 및 분기 경계 반열림 구간 검증 테스트.
- adv_date_02 질문 계획의 date_from, date_to, time_bucket 단언
- SQLite 인메모리 DB에서 3월 31일 23:30 과 4월 1일 00:10 낙찰 건이
  1분기 1건, 2분기 1건으로 명확히 구분되는지 검증
"""

from datetime import datetime

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.query_planning import build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data


def _seed_bid_result(db, **overrides):
    defaults = {
        "bid_ntce_no": "BID-001",
        "bid_ntce_ord": "00",
        "bidwinnr_nm": "테스트건설",
        "sucsf_bid_amt": 1000000,
        "sucsf_bid_rate": 98.1234,
        "rl_openg_dt": datetime(2026, 3, 31, 23, 30, 0),
        "dminstt_nm": "서울특별시",
        "category": "Cnstwk",
    }
    defaults.update(overrides)
    db.add(BidResult(**defaults))


def _seed_announcement(db, **overrides):
    defaults = {
        "bid_ntce_no": "ANN-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "테스트 공고",
        "dminstt_nm": "서울특별시",
        "bid_ntce_dt": datetime(2026, 3, 31, 23, 30, 0),
        "category": "Cnstwk",
        "raw_data": None,
    }
    defaults.update(overrides)
    db.add(BidAnnouncement(**defaults))


def test_adv_date_02_plan_quarter_breakdown():
    """adv_date_02 질문 계획이 date_from 2026-01-01, date_to 2026-06-30, time_bucket quarter 임을 단언합니다."""
    query = (
        "2026년 1분기(1월~3월)와 2분기(4월~6월)의 경계인 3월 31일 공고가 2분기 실적에 포함되지 않도록 "
        "분기별 통계를 명확히 구분해줘."
    )
    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("date_from") == "2026-01-01"
    assert plan.filters.get("date_to") == "2026-06-30"
    assert plan.filters.get("time_bucket") == "quarter"


def test_quarter_breakdown_boundary_split_half_open(isolated_db):
    """3월 31일 23:30 과 4월 1일 00:10 낙찰 두 건이 1분기 1건, 2분기 1건으로 정확히 나뉘는지 검증합니다."""
    # 3월 31일 23:30 낙찰 (1분기 속함)
    _seed_bid_result(
        isolated_db,
        bid_ntce_no="BID-2026-Q1",
        bidwinnr_nm="1분기업체",
        sucsf_bid_amt=1500000,
        sucsf_bid_rate=95.5000,
        rl_openg_dt=datetime(2026, 3, 31, 23, 30, 0),
    )
    _seed_announcement(
        isolated_db,
        bid_ntce_no="ANN-2026-Q1",
        bid_ntce_nm="1분기 공고",
        bid_ntce_dt=datetime(2026, 3, 31, 23, 30, 0),
    )

    # 4월 1일 00:10 낙찰 (2분기 속함)
    _seed_bid_result(
        isolated_db,
        bid_ntce_no="BID-2026-Q2",
        bidwinnr_nm="2분기업체",
        sucsf_bid_amt=2500000,
        sucsf_bid_rate=98.0000,
        rl_openg_dt=datetime(2026, 4, 1, 0, 10, 0),
    )
    _seed_announcement(
        isolated_db,
        bid_ntce_no="ANN-2026-Q2",
        bid_ntce_nm="2분기 공고",
        bid_ntce_dt=datetime(2026, 4, 1, 0, 10, 0),
    )

    isolated_db.commit()

    query = (
        "2026년 1분기(1월~3월)와 2분기(4월~6월)의 경계인 3월 31일 공고가 2분기 실적에 포함되지 않도록 "
        "분기별 통계를 명확히 구분해줘."
    )
    plan = build_retrieval_plan(query)
    data = retrieve_structured_data(isolated_db, plan)

    series = data["summary"]["time_series"]
    assert len(series) == 2, f"분기 시계열 버킷 수는 2개여야 합니다: {series}"

    q1_bucket = next(item for item in series if item["label"] == "2026년 1분기")
    assert q1_bucket["period"] == "quarter"
    assert q1_bucket["bid_count"] == 1
    assert q1_bucket["avg_rate"] == 95.5
    assert q1_bucket["announcement_count"] == 1

    q2_bucket = next(item for item in series if item["label"] == "2026년 2분기")
    assert q2_bucket["period"] == "quarter"
    assert q2_bucket["bid_count"] == 1
    assert q2_bucket["avg_rate"] == 98.0
    assert q2_bucket["announcement_count"] == 1


def test_quarter_breakdown_empty_quarters(isolated_db):
    """데이터가 없는 분기는 bid_count 0, announcement_count 0으로 반환되는지 검증합니다."""
    _seed_bid_result(
        isolated_db,
        bid_ntce_no="BID-2026-Q1-ONLY",
        rl_openg_dt=datetime(2026, 2, 15, 12, 0, 0),
        sucsf_bid_rate=92.0,
    )
    isolated_db.commit()

    plan = build_retrieval_plan("2026년 1분기와 2분기 통계 비교")
    data = retrieve_structured_data(isolated_db, plan)

    series = data["summary"]["time_series"]
    assert len(series) == 2
    q1 = series[0]
    assert q1["label"] == "2026년 1분기"
    assert q1["bid_count"] == 1
    assert q1["avg_rate"] == 92.0

    q2 = series[1]
    assert q2["label"] == "2026년 2분기"
    assert q2["bid_count"] == 0
    assert q2["avg_rate"] == 0.0
    assert q2["announcement_count"] == 0
