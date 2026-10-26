"""
tests/test_region_list_union.py

비교 표지 없이 광역 지역명만 나열한 목록·건수·통계 질의를 나열 지역들의
합집합 지역 조건 하나로 다루는 계약을 검증합니다.

- 나열 이름이 모두 지역이면 기관명 등호 조건 대신 지역 별칭 부분 일치 OR
  조건 하나를 씁니다.
- 비교 표지가 있는 질의는 기존 지역 비교 경로가 우선합니다.
- 지역이 아닌 이름이 섞이면 기존 기관 목록 경로를 그대로 씁니다.
- 목록 개수는 유지되고, 공고 건수 응답은 낙찰 건수가 아니라 공고 건수입니다.
"""

from __future__ import annotations

from datetime import datetime

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.answer_format import _build_single_metric_answer, _format_filters_for_prompt
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

_NOW = datetime(2026, 5, 10, 9, 0, 0)


def _seed_announcement(
    session,
    *,
    row_id: int,
    institution: str,
    category: str = "Thng",
    ntce_dt: datetime = _NOW,
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"ANN-{row_id}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bid_ntce_dt=ntce_dt,
            category=category,
            raw_data=None,
        )
    )


def _seed_result(
    session,
    *,
    row_id: int,
    institution: str,
    category: str = "Thng",
    opened_at: datetime = _NOW,
    rate: float | None = 90.0,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"RES-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=1_000_000,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


def test_region_list_count_uses_union_condition(isolated_db):
    """지역 나열 건수는 기관명 등호가 아니라 지역 합집합 공고 건수로 답합니다."""
    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=2, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청")
    _seed_announcement(isolated_db, row_id=4, institution="대구대학교")
    # 두 지역 별칭을 모두 품은 기관도 OR 조건에서는 한 행으로만 셉니다.
    _seed_announcement(isolated_db, row_id=5, institution="부산대구협력단")
    _seed_announcement(isolated_db, row_id=6, institution="서울특별시")
    for index in range(7):
        _seed_result(isolated_db, row_id=100 + index, institution="부산광역시청")
    _seed_result(isolated_db, row_id=200, institution="서울특별시")
    isolated_db.commit()

    plan = build_retrieval_plan("부산 및 대구 공고 건수")

    assert plan.filters.get("region_scope_names") == ["부산", "대구"]
    assert "institution_names" not in plan.filters
    assert "institution_name" not in plan.filters

    structured = retrieve_structured_data(isolated_db, plan)
    summary = structured["summary"]

    assert summary["announcement_count"] == 5
    # 낙찰 건수(7건)가 아니라 공고 건수로 답해야 합니다.
    assert summary["total_bids"] == 7

    answer = _build_single_metric_answer(plan, structured)
    assert "부산, 대구" in answer
    assert "5건" in answer
    assert "7건" not in answer


def test_region_list_keeps_announcement_limit(isolated_db):
    """지역 나열 목록 질의는 요청 개수를 잃지 않고 두 지역 공고만 냅니다."""
    for index in range(3):
        _seed_announcement(isolated_db, row_id=index + 1, institution="서울특별시")
    for index in range(4):
        _seed_announcement(isolated_db, row_id=10 + index, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=20, institution="대전광역시청")
    isolated_db.commit()

    plan = build_retrieval_plan("서울과 부산 공고 5개")

    assert plan.filters.get("region_scope_names") == ["서울", "부산"]
    assert plan.filters.get("announcement_limit") == 5
    assert "institution_names" not in plan.filters

    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    samples = summary["sample_announcements"]

    assert len(samples) == 5
    assert all(
        "서울" in str(item["dminstt_nm"]) or "부산" in str(item["dminstt_nm"]) for item in samples
    )


def test_region_list_applies_category_scope(isolated_db):
    """지역 세 곳과 분야가 함께 걸리면 세 지역 합집합 안에서 분야만 셉니다."""
    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청", category="Servc")
    _seed_announcement(isolated_db, row_id=2, institution="부산광역시청", category="Servc")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청", category="Servc")
    _seed_announcement(isolated_db, row_id=4, institution="광주광역시청", category="Servc")
    _seed_announcement(isolated_db, row_id=5, institution="서울특별시", category="Servc")
    _seed_announcement(isolated_db, row_id=6, institution="부산광역시청", category="Cnstwk")
    _seed_announcement(isolated_db, row_id=7, institution="부산광역시청", category="Cnstwk")
    isolated_db.commit()

    plan = build_retrieval_plan("부산, 대구, 광주 용역 공고 몇 건")

    assert plan.filters.get("region_scope_names") == ["부산", "대구", "광주"]
    assert plan.filters.get("category") == "Servc"

    structured = retrieve_structured_data(isolated_db, plan)
    summary = structured["summary"]

    assert summary["announcement_count"] == 4
    answer = _build_single_metric_answer(plan, structured)
    assert "부산, 대구, 광주" in answer
    assert "4건" in answer


def test_region_list_applies_result_scope(isolated_db):
    """지역 나열 낙찰 결과 질의는 첫 지역 하나가 아니라 두 지역 합집합을 읽습니다."""
    _seed_announcement(isolated_db, row_id=1, institution="경기도청")
    _seed_announcement(isolated_db, row_id=2, institution="경기도청")
    _seed_announcement(isolated_db, row_id=3, institution="강원도청")
    _seed_announcement(isolated_db, row_id=4, institution="서울특별시")
    _seed_result(isolated_db, row_id=10, institution="경기도청")
    _seed_result(isolated_db, row_id=11, institution="경기도청")
    _seed_result(isolated_db, row_id=12, institution="강원도청")
    _seed_result(isolated_db, row_id=13, institution="서울특별시")
    isolated_db.commit()

    plan = build_retrieval_plan("경기와 강원 낙찰 결과 보여줘")

    assert plan.filters.get("region_scope_names") == ["경기", "강원"]
    assert "institution_name" not in plan.filters
    assert "institution_names" not in plan.filters

    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["total_bids"] == 3
    assert summary["announcement_count"] == 3
    assert {item["dminstt_nm"] for item in summary["top_institutions"]} == {
        "경기도청",
        "강원도청",
    }


def test_region_list_applies_average_rate_scope(isolated_db):
    """지역 나열 평균 낙찰률은 두 지역 합집합의 평균입니다."""
    _seed_result(isolated_db, row_id=1, institution="서울특별시", category="Cnstwk", rate=90.0)
    _seed_result(isolated_db, row_id=2, institution="서울특별시", category="Cnstwk", rate=80.0)
    _seed_result(isolated_db, row_id=3, institution="경기도청", category="Cnstwk", rate=70.0)
    _seed_result(isolated_db, row_id=4, institution="부산광역시청", category="Cnstwk", rate=100.0)
    _seed_result(isolated_db, row_id=5, institution="서울특별시", category="Servc", rate=50.0)
    isolated_db.commit()

    plan = build_retrieval_plan("서울 및 경기 공사 평균 낙찰률")

    assert plan.filters.get("region_scope_names") == ["서울", "경기"]
    assert plan.filters.get("category") == "Cnstwk"

    structured = retrieve_structured_data(isolated_db, plan)
    summary = structured["summary"]

    assert summary["average_winning_rate"] == 80.0
    answer = _build_single_metric_answer(plan, structured)
    assert "서울, 경기" in answer
    assert "80.00%" in answer


def test_region_list_comparison_marker_uses_existing_region_comparison(isolated_db):
    """'및' 으로 이은 비교 질의는 기존 지역 비교 경로로 보냅니다."""
    _seed_announcement(isolated_db, row_id=1, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=2, institution="부산광역시청")
    _seed_announcement(isolated_db, row_id=3, institution="대구광역시청")
    _seed_announcement(isolated_db, row_id=4, institution="서울특별시")
    isolated_db.commit()

    plan = build_retrieval_plan("부산 및 대구 공고 건수 비교")

    assert plan.filters.get("region_names") == ["부산", "대구"]
    assert plan.filters.get("metric") == "announcement_count"
    assert "region_scope_names" not in plan.filters
    assert "institution_names" not in plan.filters

    summary = retrieve_structured_data(isolated_db, plan)["summary"]
    entries = {item["label"]: item for item in summary["comparison"]}

    assert entries["부산"]["announcement_count"] == 2
    assert entries["대구"]["announcement_count"] == 1


def test_region_list_with_non_region_name_keeps_institution_scope():
    """지역과 기관이 섞인 나열은 새 지역 합집합으로 보내지 않습니다."""
    plan = build_retrieval_plan("부산과 한국전력공사 공고 5개")

    assert plan.filters.get("institution_names") == ["부산", "한국전력공사"]
    assert plan.filters.get("announcement_limit") == 5
    assert "region_scope_names" not in plan.filters


def test_non_bidding_region_list_has_no_region_scope():
    """입찰 도메인 표지가 없는 지역 나열은 지역 조건을 만들지 않습니다."""
    plan = build_retrieval_plan("부산이랑 대구 여행 코스 비교")

    assert "region_scope_names" not in plan.filters
    assert "region_names" not in plan.filters
    assert "institution_names" not in plan.filters


def test_region_list_normalizes_admin_suffix():
    """시·도 접미사가 붙은 나열도 대표 지역명으로 접어 합집합 조건을 만듭니다."""
    plan = build_retrieval_plan("서울시와 경기도 공고")

    assert plan.filters.get("region_scope_names") == ["서울", "경기"]
    assert plan.filters.get("announcement_limit") == 5
    assert "institution_names" not in plan.filters


def test_snapshot_scope_is_disabled_for_region_scope_names():
    """나열 지역 조건도 스냅샷을 쓸 수 없어 실시간 집계로 넘깁니다."""
    plan = RetrievalPlan(filters={"region_scope_names": ["부산", "대구"]})

    assert structured_data._snapshot_scope(plan) is None


def test_prompt_filters_show_region_scope_names():
    """프롬프트용 필터 표기에 나열 지역이 대상 지역으로 나옵니다."""
    plan = build_retrieval_plan("부산 및 대구 공고 건수")

    rendered = _format_filters_for_prompt(plan.filters)

    assert "- 대상 지역: 부산, 대구" in rendered
