"""
tests/test_ngram_prefilter_equivalence.py

Wave F ngram FULLTEXT 선행필터 회귀 검증 하네스 및 경계값 동등성 테스트.

================================================================================
실행 방법 및 환경 설정
================================================================================
1. 단위 테스트 (MySQL 불필요, CI 상시 실행):
   uv run pytest tests/test_ngram_prefilter_equivalence.py -k "unit" -q

2. 통합 회귀 테스트 (실제 MySQL 8 인스턴스 필요):
   MYSQL_TEST_URL="mysql+pymysql://root:rootpassword@localhost:3306/procurement" \\
   uv run pytest tests/test_ngram_prefilter_equivalence.py -m "mysql_integration" -v

3. CI 기본 실행 (통합 테스트 제외):
   uv run pytest tests/ -q -m "not data_assets and not mysql_integration"

================================================================================
운영 안전 원칙 (Non-negotiable Safety Invariants)
================================================================================
- 본 테스트 파일 및 하네스는 운영 스키마(procurement)에 대해 어떠한 DDL(CREATE, ALTER, DROP 등)도 실행하지 않습니다.
- FULLTEXT 인덱스 생성 및 변경은 프로브 스키마 또는 격리된 세션에서만 수행되며, 본 하네스는 순수 SELECT 질의만을 통한 결과 집합 동등성 검증을 담당합니다.
- src/rag/structured_data.py 에 MATCH AGAINST 를 임의 도입하지 않으며, 선행 검증 안전망 역할을 수행합니다.
- 식별자 집합(set of IDs)을 직접 비교하며, 단순 건수(COUNT) 일치만으로 통과시키지 않습니다.
- MySQL 미가용 환경에서는 실패가 아닌 명시적 skip 사유를 남깁니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from src.app.core.config import Settings, settings
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import (
    _announcement_conditions,
    _result_conditions,
    is_safe_for_ngram_prefilter,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ngram_edge_keywords.json"

REQUIRED_14_EDGE_CLASSES = [
    "single_char_hangul",
    "exact_two_char",
    "whitespace_delimited",
    "parentheses",
    "hyphen",
    "slash",
    "alphanumeric_mixed",
    "unicode_nfd_nfc",
    "like_wildcard_percent",
    "like_wildcard_underscore",
    "single_quote",
    "boolean_operators",
    "very_long_exact_name",
    "middle_substring",
]

F3_CANONICAL_10_BASELINE_KEYWORDS = [
    "서울",
    "거제",
    "공사",
    "거제시",
    "교육청",
    "한국전",
    "한국토지주택공사",
    "한국도로공사",
    "부산광역시",
    "경찰청",
]


def load_fixture_data() -> dict[str, Any]:
    """경계값 및 기준선 키워드 픽스처 JSON을 로드합니다."""
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(f"Fixture file not found: {FIXTURE_PATH}")
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_boolean_ft_query(keyword: str) -> str:
    """F3 사양에 따른 MySQL BOOLEAN MODE 구문 검색 문자열(+'"kw"')을 생성합니다.

    내부 따옴표는 이스케이프하고 구문 검색으로 묶어 특수문자 오해석을 방지합니다.
    """
    clean_kw = keyword.replace('"', '\\"')
    return f'+"{clean_kw}"'


def build_query_sql(
    query_type: str,
    table: str,
    column: str,
    with_category: bool = False,
) -> str:
    """F3 문서 3장 규격에 맞춘 3가지 형태의 검증 SQL을 생성합니다.

    - baseline_like: WHERE col LIKE :like_pattern
    - ngram_like: WHERE MATCH(col) AGAINST(:ft_query IN BOOLEAN MODE) AND col LIKE :like_pattern
    - pure_ngram: WHERE MATCH(col) AGAINST(:ft_query IN BOOLEAN MODE)
    """
    cat_clause = " AND category = :cat" if with_category else ""

    if query_type == "baseline_like":
        return f"SELECT id FROM {table} WHERE {column} LIKE :like_pattern{cat_clause}"  # noqa: S608
    elif query_type == "ngram_like":
        return (
            f"SELECT id FROM {table} "  # noqa: S608
            f"WHERE MATCH({column}) AGAINST(:ft_query IN BOOLEAN MODE) "
            f"AND {column} LIKE :like_pattern{cat_clause}"
        )
    elif query_type == "pure_ngram":
        return (
            f"SELECT id FROM {table} "  # noqa: S608
            f"WHERE MATCH({column}) AGAINST(:ft_query IN BOOLEAN MODE){cat_clause}"
        )
    else:
        raise ValueError(f"Unknown query_type: {query_type}")


def compare_id_sets(
    baseline_ids: set[int | str],
    ngram_ids: set[int | str],
    context_info: str,
) -> tuple[bool, str]:
    """두 식별자 집합의 동등성을 검증하고 차집합 상세 메시지를 생성합니다."""
    missing_in_ngram = baseline_ids - ngram_ids
    extra_in_ngram = ngram_ids - baseline_ids

    if not missing_in_ngram and not extra_in_ngram:
        return True, "100% Identical"

    detail_lines = [
        f"동등성 불일치 발생 [{context_info}]",
        f"- Baseline LIKE 건수: {len(baseline_ids)}",
        f"- NGRAM+LIKE 건수: {len(ngram_ids)}",
        f"- NGRAM 누락 건수(Missing in NGRAM): {len(missing_in_ngram)}",
        f"- NGRAM 초과 건수(Extra in NGRAM): {len(extra_in_ngram)}",
    ]
    if missing_in_ngram:
        sample_missing = sorted(missing_in_ngram)[:5]
        detail_lines.append(f"- 누락 ID 표본 (최대 5건): {sample_missing}")
    if extra_in_ngram:
        sample_extra = sorted(extra_in_ngram)[:5]
        detail_lines.append(f"- 초과 ID 표본 (최대 5건): {sample_extra}")

    return False, "\n".join(detail_lines)


# ==============================================================================
# 단위 테스트 (Unit Tests - SQLite/인메모리/CI 상시 실행)
# ==============================================================================


def test_unit_fixture_file_exists_and_valid():
    """픽스처 파일이 존재하며 필수 메타데이터와 버전 정보를 포함해야 합니다."""
    data = load_fixture_data()
    assert "version" in data
    assert "metadata" in data
    assert "required_edge_classes" in data
    assert "keywords" in data
    assert data["metadata"]["required_edge_classes_count"] == 14
    assert data["metadata"]["baseline_keywords_count"] == 10


def test_unit_fixture_covers_all_14_required_edge_classes():
    """픽스처가 Capsule에 명시된 14개 경계값 클래스를 빠짐없이 전부 덮어야 합니다."""
    data = load_fixture_data()
    covered_classes = {
        item["class_id"] for item in data["keywords"] if not item.get("is_baseline", False)
    }

    for req_class in REQUIRED_14_EDGE_CLASSES:
        assert req_class in covered_classes, (
            f"필수 경계값 클래스 '{req_class}' 가 픽스처에 누락되었습니다."
        )


def test_unit_fixture_all_keywords_have_safety_indicator():
    """모든 픽스처 항목은 ngram 선행필터 적용 안전 여부(is_safe_for_ngram: bool)를 명시해야 합니다."""
    data = load_fixture_data()
    for item in data["keywords"]:
        assert "is_safe_for_ngram" in item, (
            f"키워드 '{item.get('keyword')}'에 is_safe_for_ngram 필드가 누락되었습니다."
        )
        assert isinstance(item["is_safe_for_ngram"], bool), (
            f"is_safe_for_ngram 은 bool 타입이어야 합니다: {item}"
        )
        assert "description" in item or "rationale" in item, (
            f"키워드 '{item.get('keyword')}'에 검증 사유가 누락되었습니다."
        )


def test_unit_fixture_contains_10_f3_baseline_keywords():
    """F3 조사가 검증한 10개 키워드가 회귀 기준선으로 픽스처에 포함되고 경계값과 구분되어야 합니다."""
    data = load_fixture_data()
    baseline_items = [item for item in data["keywords"] if item.get("is_baseline", False)]

    assert len(baseline_items) == 10, (
        f"F3 기준선 키워드 수는 정확히 10개여야 함: {len(baseline_items)}"
    )

    baseline_keywords = [item["keyword"] for item in baseline_items]
    for expected_kw in F3_CANONICAL_10_BASELINE_KEYWORDS:
        assert expected_kw in baseline_keywords, (
            f"F3 기준선 키워드 '{expected_kw}' 가 픽스처에 누락되었습니다."
        )
        # 기준선은 모두 안전함이 이미 실측으로 확인됨
        item = next(it for it in baseline_items if it["keyword"] == expected_kw)
        assert item["is_safe_for_ngram"] is True


def test_unit_fixture_single_char_hangul_is_marked_unsafe():
    """1글자 한글 토큰(예: '시', '청')은 ngram_token_size=2 환경에서 누락을 유발하므로 반드시 unsafe 로 표시되어야 합니다."""
    data = load_fixture_data()
    single_char_items = [
        item for item in data["keywords"] if item.get("class_id") == "single_char_hangul"
    ]
    assert len(single_char_items) >= 1
    for item in single_char_items:
        assert item["is_safe_for_ngram"] is False, (
            f"1글자 한글 토큰 '{item['keyword']}' 는 is_safe_for_ngram=False 여야 합니다."
        )


def test_unit_boolean_query_builder():
    """BOOLEAN MODE 구문 검색 쿼리 빌더가 따옴표 및 연산자 이스케이프를 올바르게 처리하는지 검증합니다."""
    assert build_boolean_ft_query("서울") == '+"서울"'
    assert build_boolean_ft_query("한국도로공사(본사)") == '+"한국도로공사(본사)"'
    assert build_boolean_ft_query('공사"특수"') == '+"공사\\"특수\\""'


def test_unit_compare_id_sets_detects_omission_and_extras():
    """식별자 집합 비교 유틸리티가 단순 건수뿐 아니라 ID 차집합을 정확히 탐지하는지 검증합니다."""
    # 1. 완전 일치
    ok, _ = compare_id_sets({1, 2, 3}, {1, 2, 3}, "test_match")
    assert ok is True

    # 2. 건수는 같지만 ID가 다른 경우 (건수 비교 결함 방지)
    ok_diff, msg_diff = compare_id_sets({1, 2, 3}, {1, 2, 4}, "test_same_count_diff_id")
    assert ok_diff is False
    assert "누락 ID 표본" in msg_diff
    assert "초과 ID 표본" in msg_diff

    # 3. 누락 발생
    ok_miss, msg_miss = compare_id_sets({1, 2, 3}, {1, 2}, "test_missing")
    assert ok_miss is False
    assert "NGRAM 누락 건수(Missing in NGRAM): 1" in msg_miss


def test_unit_flag_default_is_false():
    """(1) config.py의 NGRAM_PREFILTER_ENABLED 기본값은 반드시 False여야 합니다."""
    assert settings.NGRAM_PREFILTER_ENABLED is False
    fresh_settings = Settings(
        SECRET_KEY="test-secret-key-12345678901234567890",
        DATABASE_URL="mysql+pymysql://root:rootpassword@localhost:3306/procurement",
    )
    assert fresh_settings.NGRAM_PREFILTER_ENABLED is False


def test_unit_flag_off_generates_no_match_sql(monkeypatch: pytest.MonkeyPatch):
    """(2) 플래그 OFF 일 때 생성 SQL 에 MATCH 구문이 전혀 없어야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", False)

    plan = RetrievalPlan(filters={"institution_name": "서울"})
    winner_conds = _result_conditions(plan, enable_ngram_prefilter=True)
    instt_conds = _announcement_conditions(plan, enable_ngram_prefilter=True)

    stmt_winner = (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .where(*winner_conds)
        .group_by(BidResult.bidwinnr_nm)
    )
    stmt_instt = (
        select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
        .where(*instt_conds)
        .group_by(BidAnnouncement.dminstt_nm)
    )

    sql_winner = str(
        stmt_winner.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )
    sql_instt = str(
        stmt_instt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "MATCH" not in sql_winner.upper()
    assert "AGAINST" not in sql_winner.upper()
    assert "LIKE" in sql_winner.upper()

    assert "MATCH" not in sql_instt.upper()
    assert "AGAINST" not in sql_instt.upper()
    assert "LIKE" in sql_instt.upper()


def test_unit_flag_on_safe_keyword_includes_match_and_like(monkeypatch: pytest.MonkeyPatch):
    """(3) 플래그 ON 이고 안전한 키워드면 MATCH 와 LIKE 가 함께 포함되어야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", True)

    safe_keywords = ["서울", "한국도로공사", "부산광역시"]
    for kw in safe_keywords:
        plan = RetrievalPlan(filters={"institution_name": kw})
        winner_conds = _result_conditions(plan, enable_ngram_prefilter=True)
        instt_conds = _announcement_conditions(plan, enable_ngram_prefilter=True)

        stmt_winner = (
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .where(*winner_conds)
            .group_by(BidResult.bidwinnr_nm)
        )
        stmt_instt = (
            select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
            .where(*instt_conds)
            .group_by(BidAnnouncement.dminstt_nm)
        )

        sql_winner = str(
            stmt_winner.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        sql_instt = str(
            stmt_instt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )

        assert "MATCH" in sql_winner.upper()
        assert "AGAINST" in sql_winner.upper()
        assert "LIKE" in sql_winner.upper()
        assert f'+"{kw}"' in sql_winner

        assert "MATCH" in sql_instt.upper()
        assert "AGAINST" in sql_instt.upper()
        assert "LIKE" in sql_instt.upper()
        assert f'+"{kw}"' in sql_instt


def test_unit_flag_on_single_char_keyword_generates_no_match_sql(monkeypatch: pytest.MonkeyPatch):
    """(4) 플래그 ON 이어도 1글자 키워드에는 MATCH 가 들어가지 않고 LIKE 단독이어야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", True)

    single_char_keywords = ["시", "청", "A", "1"]
    for kw in single_char_keywords:
        assert is_safe_for_ngram_prefilter(kw) is False

        plan = RetrievalPlan(filters={"institution_name": kw})
        winner_conds = _result_conditions(plan, enable_ngram_prefilter=True)
        instt_conds = _announcement_conditions(plan, enable_ngram_prefilter=True)

        stmt_winner = select(BidResult.bidwinnr_nm).where(*winner_conds)
        stmt_instt = select(BidAnnouncement.dminstt_nm).where(*instt_conds)

        sql_winner = str(
            stmt_winner.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        sql_instt = str(
            stmt_instt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )

        assert "MATCH" not in sql_winner.upper()
        assert "AGAINST" not in sql_winner.upper()
        assert "LIKE" in sql_winner.upper()

        assert "MATCH" not in sql_instt.upper()
        assert "AGAINST" not in sql_instt.upper()
        assert "LIKE" in sql_instt.upper()


def test_unit_flag_on_unsafe_keywords_generate_no_match_sql(monkeypatch: pytest.MonkeyPatch):
    """(5) 플래그 ON 이어도 와일드카드·boolean 연산자·따옴표 문자가 든 키워드에는 MATCH 가 들어가지 않아야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", True)

    unsafe_keywords = [
        "100%",  # like_wildcard_percent
        "공사_1차",  # like_wildcard_underscore
        "공사's",  # single_quote
        '공사"특수"',  # double quote
        "+공사*",  # boolean_operators
        "한국도로공사(본사)",  # parentheses
        "서울-경기",  # hyphen
    ]
    for kw in unsafe_keywords:
        assert is_safe_for_ngram_prefilter(kw) is False, f"Keyword '{kw}' should be marked unsafe"

        plan = RetrievalPlan(filters={"institution_name": kw})
        winner_conds = _result_conditions(plan, enable_ngram_prefilter=True)
        instt_conds = _announcement_conditions(plan, enable_ngram_prefilter=True)

        stmt_winner = select(BidResult.bidwinnr_nm).where(*winner_conds)
        stmt_instt = select(BidAnnouncement.dminstt_nm).where(*instt_conds)

        sql_winner = str(
            stmt_winner.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        sql_instt = str(
            stmt_instt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )

        assert "MATCH" not in sql_winner.upper()
        assert "AGAINST" not in sql_winner.upper()
        assert "LIKE" in sql_winner.upper()

        assert "MATCH" not in sql_instt.upper()
        assert "AGAINST" not in sql_instt.upper()
        assert "LIKE" in sql_instt.upper()


def test_unit_flag_on_bid_ntce_nm_query_generates_no_match_sql(monkeypatch: pytest.MonkeyPatch):
    """(6) bid_ntce_nm 대상 쿼리 및 단건/목록 조회에는 플래그 ON 이어도 MATCH 가 없어야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", True)

    plan = RetrievalPlan(filters={"institution_name": "서울"})

    # 1. bid_ntce_nm 집계 쿼리는 prefilter를 받지 않음
    ann_conds = _announcement_conditions(plan, enable_ngram_prefilter=False)
    stmt_top_ann = (
        select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
        .where(*ann_conds)
        .group_by(BidAnnouncement.bid_ntce_nm)
    )
    sql_top_ann = str(
        stmt_top_ann.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "MATCH" not in sql_top_ann.upper()
    assert "LIKE" in sql_top_ann.upper()

    # 2. recent_results (단건/목록 조회) 경로
    res_conds = _result_conditions(plan, enable_ngram_prefilter=False)
    stmt_recent = select(BidResult).where(*res_conds)
    sql_recent = str(
        stmt_recent.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "MATCH" not in sql_recent.upper()
    assert "LIKE" in sql_recent.upper()

    # 3. 표본 공고 조회 경로
    stmt_sample = select(BidAnnouncement.bid_ntce_no, BidAnnouncement.bid_ntce_nm).where(*ann_conds)
    sql_sample = str(
        stmt_sample.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "MATCH" not in sql_sample.upper()


def test_unit_flag_off_sql_identical_to_baseline(monkeypatch: pytest.MonkeyPatch):
    """(7) 플래그 OFF 경로의 생성 SQL 이 변경 전과 100% 동일해야 합니다."""
    monkeypatch.setattr(settings, "NGRAM_PREFILTER_ENABLED", False)

    test_filter_cases = [
        {},
        {"institution_name": "서울"},
        {"institution_name": "한국도로공사", "category": "Servc"},
        {"institution_name": "부산광역시", "date_from": "2026-01-01", "date_to": "2026-06-30"},
        {"category": "Cnstwk", "date_from": "2025-01-01"},
    ]

    for filters in test_filter_cases:
        plan = RetrievalPlan(filters=filters)

        # enable_ngram_prefilter=True 일 때도 플래그가 OFF면 False 호출과 동일
        conds_winner_prefilter = _result_conditions(plan, enable_ngram_prefilter=True)
        conds_winner_legacy = _result_conditions(plan, enable_ngram_prefilter=False)
        stmt_pre = (
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .where(*conds_winner_prefilter)
            .group_by(BidResult.bidwinnr_nm)
        )
        stmt_leg = (
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .where(*conds_winner_legacy)
            .group_by(BidResult.bidwinnr_nm)
        )

        sql_pre = str(
            stmt_pre.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        sql_leg = str(
            stmt_leg.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert sql_pre == sql_leg

        conds_instt_prefilter = _announcement_conditions(plan, enable_ngram_prefilter=True)
        conds_instt_legacy = _announcement_conditions(plan, enable_ngram_prefilter=False)
        stmt_instt_pre = (
            select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
            .where(*conds_instt_prefilter)
            .group_by(BidAnnouncement.dminstt_nm)
        )
        stmt_instt_leg = (
            select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
            .where(*conds_instt_legacy)
            .group_by(BidAnnouncement.dminstt_nm)
        )

        sql_instt_pre = str(
            stmt_instt_pre.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        sql_instt_leg = str(
            stmt_instt_leg.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert sql_instt_pre == sql_instt_leg


def test_unit_is_safe_for_ngram_prefilter_with_fixture_classes():
    """안전성 판정 함수가 픽스처의 기준선 키워드(10종) 및 위험 경계값 클래스를 정확히 판정하는지 검증합니다."""
    # 1. 기준선 10종은 모두 True
    for kw in F3_CANONICAL_10_BASELINE_KEYWORDS:
        assert is_safe_for_ngram_prefilter(kw) is True, f"Baseline keyword '{kw}' should be safe"

    # 2. 위험 문자 및 경계값
    assert is_safe_for_ngram_prefilter("") is False
    assert is_safe_for_ngram_prefilter(None) is False
    assert is_safe_for_ngram_prefilter("시") is False
    assert is_safe_for_ngram_prefilter("청") is False
    assert is_safe_for_ngram_prefilter("100%") is False
    assert is_safe_for_ngram_prefilter("공사_1차") is False
    assert is_safe_for_ngram_prefilter("공사's") is False
    assert is_safe_for_ngram_prefilter("+공사*") is False
    assert is_safe_for_ngram_prefilter("한국도로공사(본사)") is False
    assert is_safe_for_ngram_prefilter("서울-경기") is False

    # 3. 안전한 복합 문자열
    assert is_safe_for_ngram_prefilter("구청") is True
    assert is_safe_for_ngram_prefilter("서울특별시 강남구") is True
    assert is_safe_for_ngram_prefilter("한국농어촌공사전남지역본부영광지사") is True
    assert is_safe_for_ngram_prefilter("토지주택") is True


# ==============================================================================
# MySQL 통합 회귀 테스트 (Integration Tests - 실제 MySQL 8 인스턴스 전용)
# ==============================================================================


def _get_mysql_test_engine() -> Engine | None:
    """환경변수에서 MySQL 접속 정보를 취득하고 연결 가능한 엔진을 생성합니다."""
    db_url = os.environ.get("MYSQL_TEST_URL") or os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        try:
            from src.app.core.config import settings

            if "mysql" in settings.DATABASE_URL:
                db_url = settings.DATABASE_URL
        except (ImportError, AttributeError):
            db_url = None

    if not db_url or "mysql" not in db_url:
        return None

    try:
        engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except (OperationalError, Exception):
        return None


@pytest.fixture(scope="module")
def mysql_session():
    """MySQL 8 실제 연결 세션을 제공하며, 불가 시 명시적 사유와 함께 skip 합니다."""
    engine = _get_mysql_test_engine()
    if engine is None:
        pytest.skip(
            "MySQL 8 인스턴스에 접속할 수 없거나 MYSQL_TEST_URL/DATABASE_URL 환경변수가 "
            "설정되지 않아 MySQL 통합 동등성 테스트를 건너뜁니다."
        )
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _check_fulltext_index_exists(
    session: Session, table: str, column: str, expected_index_name: str | None = None
) -> bool:
    """테이블의 특정 컬럼에 FULLTEXT 인덱스가 존재하는지 확인합니다."""
    try:
        result = session.execute(text(f"SHOW INDEX FROM {table} WHERE Index_type = 'FULLTEXT'"))
        rows = result.fetchall()
        return any(len(row) > 4 and row[4] == column for row in rows)
    except Exception:
        return False


@pytest.mark.mysql_integration
def test_integration_mysql_baseline_keywords_equivalence(mysql_session: Session):
    """F3 기준선 10개 키워드에 대해 dminstt_nm 및 bidwinnr_nm 집계 대상 컬럼에서

    LIKE 결과와 MATCH+LIKE 결과 집합이 100% 동일함을 실측 검증합니다.
    """
    data = load_fixture_data()
    baseline_items = [item for item in data["keywords"] if item.get("is_baseline", False)]

    # 검증 대상: bid_announcements.dminstt_nm, bid_results.dminstt_nm, bid_results.bidwinnr_nm
    target_columns = [
        ("bid_announcements", "dminstt_nm"),
        ("bid_results", "dminstt_nm"),
        ("bid_results", "bidwinnr_nm"),
    ]

    for table, col in target_columns:
        # FULLTEXT 인덱스가 없으면 MATCH AGAINST 실행 시 구문 에러가 발생하므로 확인
        has_ft = _check_fulltext_index_exists(mysql_session, table, col)
        if not has_ft:
            pytest.skip(
                f"{table}.{col} 에 FULLTEXT 인덱스가 없어 동등성 실측을 건너뜁니다. "
                "(운영 스키마에는 DDL을 실행하지 않으므로 probe 인덱스가 있는 환경에서만 실행됩니다.)"
            )

        for item in baseline_items:
            kw = item["keyword"]
            for with_cat in [False, True]:
                cat_val = "Servc" if with_cat else None
                like_sql = build_query_sql("baseline_like", table, col, with_category=with_cat)
                ngram_like_sql = build_query_sql("ngram_like", table, col, with_category=with_cat)

                params = {"like_pattern": f"%{kw}%"}
                if with_cat:
                    params["cat"] = cat_val

                like_rows = mysql_session.execute(text(like_sql), params).scalars().all()
                like_ids = set(like_rows)

                params["ft_query"] = build_boolean_ft_query(kw)
                ngram_rows = mysql_session.execute(text(ngram_like_sql), params).scalars().all()
                ngram_ids = set(ngram_rows)

                ok, msg = compare_id_sets(
                    like_ids,
                    ngram_ids,
                    f"Baseline: {kw} on {table}.{col} (cat={cat_val})",
                )
                assert ok is True, msg


@pytest.mark.mysql_integration
def test_integration_mysql_single_char_hangul_observed_as_unsafe(mysql_session: Session):
    """1글자 한글 토큰(예: '시')의 경우 ngram_token_size=2 환경에서

    pure MATCH AGAINST가 0건을 반환하여 조용한 누락이 발생함을 관측하고,
    해당 클래스가 안전하지 않다는 사실을 단정으로 고정합니다.
    """
    table = "bid_announcements"
    col = "dminstt_nm"

    has_ft = _check_fulltext_index_exists(mysql_session, table, col)
    if not has_ft:
        pytest.skip(f"{table}.{col} 에 FULLTEXT 인덱스가 없어 1글자 누락 관측 테스트를 건너뜁니다.")

    single_char_kw = "시"
    like_sql = build_query_sql("baseline_like", table, col, with_category=False)
    like_ids = set(
        mysql_session.execute(text(like_sql), {"like_pattern": f"%{single_char_kw}%"})
        .scalars()
        .all()
    )

    # 1글자 한글은 LIKE로는 수많은 행이 매칭됨 (예: 서울특별시, 경기도 성남시 등)
    assert len(like_ids) > 0, "LIKE '%시%' 매칭 결과가 존재해야 합니다."

    # Pure NGRAM MATCH AGAINST 실행
    pure_ngram_sql = build_query_sql("pure_ngram", table, col, with_category=False)
    pure_ngram_ids = set(
        mysql_session.execute(
            text(pure_ngram_sql), {"ft_query": build_boolean_ft_query(single_char_kw)}
        )
        .scalars()
        .all()
    )

    # 핵심 안전망 단정: ngram_token_size=2 환경에서 1글자 토큰은 MATCH AGAINST 매칭이 실패하므로
    # LIKE 결과와 Pure NGRAM 결과가 불일치(0건 또는 극심한 누락)함을 직접 관측하여 고정함
    assert len(pure_ngram_ids) < len(like_ids), (
        f"1글자 한글 '{single_char_kw}'에 대해 MATCH AGAINST가 LIKE 결과({len(like_ids)}건)를 "
        f"누락하지 않고 {len(pure_ngram_ids)}건을 반환했습니다. ngram_token_size 확인 필요."
    )
