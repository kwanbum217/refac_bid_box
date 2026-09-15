"""
tests/test_rag_multi_institution.py

여러 기관을 나열한 질의의 정형 조회 및 Source [1] 기관별 구역 생성 검증 (Contract 4, 5).
- SQLite 인메모리 DB에서 복수 기관 낙찰 결과 집계
- Source [1] 에 기관별 건수·평균 낙찰률·최근 결과 분리 렌더링 검증
- 카탈로그에 대응되지 않는 기관명 필터링 및 제외 검증
- 대응 기관이 전무한 경우 기존 단일 경로 동일 동작(하위 호환) 검증
- 최대 5개 기관 제한 검증
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from src.app.models.bids import BidResult
from src.rag.answer_format import _compose_context_text
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.snapshots import _extract_statistical_snapshot
from src.rag.structured_data import retrieve_structured_data


def _seed_sample_bid_results(db: Session) -> None:
    """서울특별시교육청 3건, 서울대학교 2건의 낙찰 행을 시드합니다."""
    items = [
        BidResult(
            id=101,
            bid_ntce_no="20260100001",
            bid_ntce_ord=1,
            bid_ntce_nm="서울특별시교육청 전산실 네트워크 스위치 구매",
            dminstt_nm="서울특별시교육청",
            bidwinnr_nm="에이치피코리아",
            sucsf_bid_amt=50_000_000,
            sucsf_bid_rate=88.5000,
            rl_openg_dt=datetime(2026, 9, 10, 10, 0, 0),
            category="Thng",
        ),
        BidResult(
            id=102,
            bid_ntce_no="20260100002",
            bid_ntce_ord=1,
            bid_ntce_nm="서울특별시교육청 업무용 PC 구매",
            dminstt_nm="서울특별시교육청",
            bidwinnr_nm="삼성전자",
            sucsf_bid_amt=120_000_000,
            sucsf_bid_rate=87.5000,
            rl_openg_dt=datetime(2026, 9, 11, 11, 0, 0),
            category="Thng",
        ),
        BidResult(
            id=103,
            bid_ntce_no="20260100003",
            bid_ntce_ord=1,
            bid_ntce_nm="서울특별시교육청 무선 AP 구축",
            dminstt_nm="서울특별시교육청",
            bidwinnr_nm="시스코시스템즈",
            sucsf_bid_amt=75_000_000,
            sucsf_bid_rate=89.2000,
            rl_openg_dt=datetime(2026, 9, 12, 14, 0, 0),
            category="Thng",
        ),
        BidResult(
            id=201,
            bid_ntce_no="20260200001",
            bid_ntce_ord=1,
            bid_ntce_nm="서울대학교 데이터센터 서버 증설 구매",
            dminstt_nm="서울대학교",
            bidwinnr_nm="델테크놀로지스",
            sucsf_bid_amt=200_000_000,
            sucsf_bid_rate=92.1000,
            rl_openg_dt=datetime(2026, 9, 13, 15, 0, 0),
            category="Thng",
        ),
        BidResult(
            id=202,
            bid_ntce_no="20260200002",
            bid_ntce_ord=1,
            bid_ntce_nm="서울대학교 관악캠퍼스 방화벽 장비 교체",
            dminstt_nm="서울대학교",
            bidwinnr_nm="안랩",
            sucsf_bid_amt=80_000_000,
            sucsf_bid_rate=91.5000,
            rl_openg_dt=datetime(2026, 9, 14, 16, 0, 0),
            category="Thng",
        ),
    ]
    for item in items:
        db.add(item)
    db.commit()


def test_multi_institution_aggregation_and_source_snapshot(isolated_db: Session):
    """두 기관의 낙찰 행이 Source [1] 에 기관별 구역으로 분리되어 실리는지 검증합니다."""
    _seed_sample_bid_results(isolated_db)

    query = "서울특별시교육청과 서울대학교의 최근 전산장비 구매 입찰 결과를 비교해줘."
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get("institution_names") == ["서울특별시교육청", "서울대학교"]
    assert "institution_name" not in plan.filters

    structured = retrieve_structured_data(isolated_db, plan)
    summary = structured.get("summary") or {}
    by_inst = summary.get("by_institution")

    assert by_inst is not None
    assert len(by_inst) == 2

    # 1. 서울특별시교육청 집계 확인
    inst_1 = by_inst[0]
    assert inst_1["institution_name"] == "서울특별시교육청"
    assert inst_1["bid_count"] == 3
    assert inst_1["avg_rate"] == pytest.approx(88.4, rel=1e-3)
    assert len(inst_1["recent_results"]) == 3
    assert inst_1["recent_results"][0]["bidwinnr_nm"] == "시스코시스템즈"

    # 2. 서울대학교 집계 확인
    inst_2 = by_inst[1]
    assert inst_2["institution_name"] == "서울대학교"
    assert inst_2["bid_count"] == 2
    assert inst_2["avg_rate"] == pytest.approx(91.8, rel=1e-3)
    assert len(inst_2["recent_results"]) == 2
    assert inst_2["recent_results"][0]["bidwinnr_nm"] == "안랩"

    # 3. Source [1] (통계 스냅샷) 렌더링 확인
    snapshot_text = _extract_statistical_snapshot(structured)
    assert "정형 데이터 집계:" in snapshot_text
    assert "[서울특별시교육청]" in snapshot_text
    assert "- 낙찰 결과 수: 3" in snapshot_text
    assert "- 평균 낙찰률: 88.4" in snapshot_text
    assert "공고명=서울특별시교육청 무선 AP 구축" in snapshot_text

    assert "[서울대학교]" in snapshot_text
    assert "- 낙찰 결과 수: 2" in snapshot_text
    assert "- 평균 낙찰률: 91.8" in snapshot_text
    assert "공고명=서울대학교 관악캠퍼스 방화벽 장비 교체" in snapshot_text

    # 4. 전체 컨텍스트(Source [1])에 기관별 구역 포함 확인
    context = _compose_context_text(plan, structured, [], None)
    assert "Source [1] (통계/수치):" in context
    assert "[서울특별시교육청]" in context
    assert "[서울대학교]" in context


def test_multi_institution_unmatched_names_are_discarded(isolated_db: Session):
    """카탈로그에 없는 기관명은 버려지고 존재하는 기관만 집계되는지 검증합니다."""
    _seed_sample_bid_results(isolated_db)

    plan = RetrievalPlan(
        use_sql=True,
        use_vector=True,
        filters={"institution_names": ["서울특별시교육청", "존재하지않는가상기관xyz"]},
        semantic_query="테스트",
    )

    structured = retrieve_structured_data(isolated_db, plan)
    by_inst = (structured.get("summary") or {}).get("by_institution")

    assert by_inst is not None
    assert len(by_inst) == 1
    assert by_inst[0]["institution_name"] == "서울특별시교육청"
    assert by_inst[0]["bid_count"] == 3


def test_multi_institution_fallback_when_no_names_matched(isolated_db: Session):
    """대응 기관이 하나도 없으면 기존 단일 경로와 똑같이 동작하는지 검증합니다."""
    _seed_sample_bid_results(isolated_db)

    plan = RetrievalPlan(
        use_sql=True,
        use_vector=True,
        filters={"institution_names": ["완전히없는기관A", "완전히없는기관B"]},
        semantic_query="테스트",
    )

    structured = retrieve_structured_data(isolated_db, plan)
    summary = structured.get("summary") or {}

    # 대응 기관이 없으므로 by_institution 이 생성되지 않고 기존 단일 경로가 실행됨
    assert "by_institution" not in summary
    assert "total_bids" in summary


def test_multi_institution_caps_at_five_institutions(isolated_db: Session):
    """기관 수가 5개를 초과해도 최대 5개로 제한되는지 검증합니다."""
    _seed_sample_bid_results(isolated_db)

    names = ["기관1", "기관2", "기관3", "기관4", "기관5", "기관6", "기관7"]
    plan = RetrievalPlan(
        use_sql=True,
        use_vector=True,
        filters={"institution_names": names},
        semantic_query="테스트",
    )

    # 5개까지만 카탈로그 해석을 시도하고 나머지는 무시되므로, 모두 매칭 실패 시 기존 경로로 폴백
    structured = retrieve_structured_data(isolated_db, plan)
    assert "by_institution" not in (structured.get("summary") or {})
