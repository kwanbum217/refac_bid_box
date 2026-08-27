"""
tests/test_build_generalization_fixture.py

scripts/build_generalization_fixture.py 단위 테스트.
DB 연결 없이 순수 메모리 모의 데이터를 활용하여
스트라타 판정 함수, ord 정규화, 스키마 직렬화, 스트라타 미충족 시 예외 처리를 검증합니다.
"""

import pytest

from scripts.build_generalization_fixture import (
    FORBIDDEN_LITERALS,
    build_answerable_item,
    check_strata_quotas,
    classify_amount_tier,
    classify_institution_type,
    classify_rate_tier,
    classify_region,
    generate_refusal_items,
    normalize_bid_ntce_ord,
    select_answerable_candidates,
)


def test_normalize_bid_ntce_ord():
    """공고 차수 3자리 정규화 검증."""
    assert normalize_bid_ntce_ord("00") == "000"
    assert normalize_bid_ntce_ord("01") == "001"
    assert normalize_bid_ntce_ord("000") == "000"
    assert normalize_bid_ntce_ord("123") == "123"
    assert normalize_bid_ntce_ord("") == "000"
    assert normalize_bid_ntce_ord(None) == "000"


def test_classify_institution_type():
    """수요기관명 5대 유형 분류 검증."""
    assert classify_institution_type("대구광역시동부교육지원청 계성초등학교") == "교육청"
    assert classify_institution_type("서울대학교 산학협력단") == "교육청"
    assert classify_institution_type("한국토지주택공사 인천지역본부") == "공기업"
    assert classify_institution_type("인천시설관리공단") == "공기업"
    assert classify_institution_type("전라남도 도로관리사업소") == "광역"
    assert classify_institution_type("서울특별시 도시기반시설본부") == "광역"
    assert classify_institution_type("부산광역시 기장군") == "기초"
    assert classify_institution_type("부천시 체육진흥과") == "기초"
    assert classify_institution_type("국토교통부 서울지방국토관리청 수원국토관리사무소") == "기타"
    assert classify_institution_type("한국생산기술연구원") == "기타"


def test_classify_amount_tier():
    """낙찰금액 4개 구간 분류 검증."""
    assert classify_amount_tier(33_000_000) == "<1억"
    assert classify_amount_tier(99_999_999) == "<1억"
    assert classify_amount_tier(100_000_000) == "1~5억"
    assert classify_amount_tier(499_999_999) == "1~5억"
    assert classify_amount_tier(500_000_000) == "5~10억"
    assert classify_amount_tier(999_999_999) == "5~10억"
    assert classify_amount_tier(1_000_000_000) == ">=10억"
    assert classify_amount_tier(5_000_000_000) == ">=10억"


def test_classify_region():
    """수도권 / 비수도권 분류 검증."""
    assert classify_region("서울특별시 강남구", "도로정비공사") == "수도권"
    assert classify_region("경기도 수원시", "시설보수용역") == "수도권"
    assert classify_region("인천광역시 부평구", "물품구매") == "수도권"
    assert classify_region("전라남도 광양시", "폐기물처리") == "비수도권"
    assert classify_region("경상북도 봉화군", "감리용역") == "비수도권"
    assert classify_region("대전광역시", "전기공사") == "비수도권"


def test_classify_rate_tier():
    """낙찰률 3개 구간 분류 검증."""
    assert classify_rate_tier(80.5000) == "<85%"
    assert classify_rate_tier(84.9999) == "<85%"
    assert classify_rate_tier(85.0000) == "85~95%"
    assert classify_rate_tier(88.5100) == "85~95%"
    assert classify_rate_tier(95.0000) == "85~95%"
    assert classify_rate_tier(95.0001) == ">95%"
    assert classify_rate_tier(100.0000) == ">95%"


def test_check_strata_quotas_pass_and_fail():
    """스트라타 할당 판정 통과 및 실패 검증."""
    # 1. 부족한 데이터 (실패 케이스)
    sparse_items = [
        {
            "category": "Servc",
            "instt_type": "광역",
            "amt_tier": "<1억",
            "region": "수도권",
            "rate_tier": "85~95%",
        }
    ]
    ok, _counts, missing = check_strata_quotas(sparse_items)
    assert ok is False
    assert len(missing) > 0
    assert "category:Cnstwk" in missing

    # 2. 완벽히 충족하는 24문항 목 데이터 (성공 케이스)
    # 최소 요구: Cnstwk 2, Servc 2, Thng 2, 광역 1, 기초 1, 교육청 1, 공기업 1, 기타 1,
    # <1억 2, 1~5억 2, 5~10억 2, >=10억 2, 수도권 4, 비수도권 4, <85% 2, 85~95% 2, >95% 2
    full_items = []
    # 24개 항목을 스트라타를 채우도록 합성
    categories = ["Cnstwk"] * 8 + ["Servc"] * 8 + ["Thng"] * 8
    instt_types = ["광역", "기초", "교육청", "공기업", "기타"] * 4 + [
        "광역",
        "기초",
        "교육청",
        "공기업",
    ]
    amt_tiers = ["<1억", "1~5억", "5~10억", ">=10억"] * 6
    regions = ["수도권"] * 12 + ["비수도권"] * 12
    rate_tiers = ["<85%", "85~95%", ">95%"] * 8

    for i in range(24):
        full_items.append(
            {
                "category": categories[i],
                "instt_type": instt_types[i],
                "amt_tier": amt_tiers[i],
                "region": regions[i],
                "rate_tier": rate_tiers[i],
            }
        )

    ok_full, _counts_full, missing_full = check_strata_quotas(full_items)
    assert ok_full is True
    assert len(missing_full) == 0


def test_select_answerable_candidates_failure_raises():
    """후보 부족 시 select_answerable_candidates 가 ValueError 를 발생시키는지 검증."""
    insufficient_cands = [
        {
            "ann_id": 1,
            "bid_ntce_no": "N01",
            "bid_ntce_nm": "공사1",
            "dminstt_nm": "서울시",
            "bidwinnr_nm": "업체A",
            "sucsf_bid_amt": 50000000.0,
            "sucsf_bid_rate": 88.0,
            "category": "Cnstwk",
            "instt_type": "광역",
            "amt_tier": "<1억",
            "region": "수도권",
            "rate_tier": "85~95%",
        }
    ]
    with pytest.raises(ValueError, match="스트라타 최소 할당을 충족하지 못했습니다"):
        select_answerable_candidates(insufficient_cands, target_count=24)


def test_build_answerable_item_structure():
    """답변 가능 문항 직렬화 구조 및 numeric 분리 검증."""
    cand = {
        "ann_id": 10015927,
        "bid_ntce_no": "R26BK01659912-001",
        "bid_ntce_nm": "봉화 공설운동장 리모델링 감리용역",
        "dminstt_nm": "경상북도 봉화군 체육시설사업소",
        "bidwinnr_nm": "건축사사무소 가온",
        "sucsf_bid_amt": 46602100.0,
        "sucsf_bid_rate": 88.5100,
        "category": "Servc",
        "instt_type": "광역",
        "amt_tier": "<1억",
        "region": "비수도권",
        "rate_tier": "85~95%",
    }
    item = build_answerable_item(cand, "q01")

    assert item["id"] == "q01"
    assert item["context_sufficient"] is True
    assert item["refusal_expected"] is False
    assert item["expected_evidence_ids"] == ["bid_10015927"]
    assert item["forbidden_literals"] == FORBIDDEN_LITERALS

    # 자기모순 제재 문구 검증
    assert any("자기모순" in claim for claim in item["semantic_forbidden_claims"])

    facts = item["expected_facts"]
    assert len(facts) == 5

    numeric_facts = [f for f in facts if f["fact_type"] == "numeric"]
    assert len(numeric_facts) == 2

    # 금액 및 낙찰률 tolerance 및 단위 검증
    amt_fact = next(f for f in numeric_facts if f["unit"] == "원")
    rate_fact = next(f for f in numeric_facts if f["unit"] == "%")
    assert amt_fact["tolerance"] == 1
    assert amt_fact["expected_value"] == "46602100"
    assert rate_fact["tolerance"] == 0.01
    assert rate_fact["expected_value"] == "88.5100"


def test_generate_refusal_items_structure():
    """거절 문항 생성기 검증 (8문항)."""
    refusals = generate_refusal_items(start_id_num=25, count=8)
    assert len(refusals) == 8

    for idx, ref in enumerate(refusals, start=25):
        assert ref["id"] == f"q{idx:02d}"
        assert ref["context_sufficient"] is False
        assert ref["refusal_expected"] is True
        assert ref["citation_required"] is False
        assert ref["expected_evidence_ids"] == []
        assert ref["numeric_tolerance"] is None
        assert len(ref["expected_facts"]) == 1
        assert ref["expected_facts"][0]["fact_type"] == "refusal"
        assert ref["expected_facts"][0]["expected_value"] is None
        assert ref["forbidden_literals"] == FORBIDDEN_LITERALS
        assert any("자기모순" in claim for claim in ref["semantic_forbidden_claims"])
