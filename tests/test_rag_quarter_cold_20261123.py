"""분기 시계열 공고 집계의 최신 차수·취소 제외 의미와 실행 계획 회귀 테스트.

2026-11-23 실측에서 최근 5년 용역 분기 시계열 공고 집계가 콜드 26.5초로 챗봇
집계 경로 중 유일하게 10초를 넘었습니다. 이 경로는 기간·업무구분 조건을 먼저
건 파생 테이블로 id 를 인덱스에서만 추리고, 최신 차수 판정을 상관 MAX 서브쿼리
대신 반조인으로 겁니다. 실행 계획만 바꾸고 의미(최신 차수 1행, 최신 차수
취소공고 제외)는 그대로인지 SQLite 인메모리 픽스처로 확인합니다. 운영 DB,
Redis, 로컬 .env 에 기대지 않습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement
from src.rag import structured_data as structured_data_module
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

CANCELLED = "취소공고"
HALF_YEAR = {"date_from": "2026-01-01", "date_to": "2026-06-30"}
FIRST_QUARTER = {"date_from": "2026-01-01", "date_to": "2026-03-31"}

# (공고번호, 차수, 공고종류, 공고명, 수요기관, 공고일시)
# QTR-A: 000(1분기)·001(1분기) -> 최신 차수 001 한 행만 센다.
# QTR-B: 000(1분기)·001 취소(1분기) -> 최신 차수가 취소이므로 통째로 뺀다.
# QTR-C: 000(1분기)·001 재공고(1분기) -> 재공고는 유효하므로 001 한 행만 센다.
# QTR-D: 000(1분기)·공고종류 NULL -> 유지한다.
# QTR-E: 000(1분기)·002 변경공고(2분기) -> 1분기 창에서는 한 행도 세지 않는다.
# QTR-F: 000(2분기)·001 취소(2분기) -> 최신 차수가 취소이므로 뺀다.
SEEDS: tuple[tuple[str, str, str | None, str, str, datetime], ...] = (
    ("QTR-A", "000", "등록공고", "분기 검증 공고 A 000", "서울특별시", datetime(2026, 1, 5, 9)),
    ("QTR-A", "001", "등록공고", "분기 검증 공고 A 001", "서울특별시", datetime(2026, 2, 10, 9)),
    ("QTR-B", "000", "등록공고", "분기 검증 공고 B 000", "부산광역시", datetime(2026, 1, 15, 9)),
    ("QTR-B", "001", CANCELLED, "분기 검증 공고 B 001", "부산광역시", datetime(2026, 2, 15, 9)),
    ("QTR-C", "000", "등록공고", "분기 검증 공고 C 000", "대구광역시", datetime(2026, 1, 20, 9)),
    ("QTR-C", "001", "재공고", "분기 검증 공고 C 001", "대구광역시", datetime(2026, 3, 20, 9)),
    ("QTR-D", "000", None, "분기 검증 공고 D 000", "인천광역시", datetime(2026, 2, 1, 9)),
    ("QTR-E", "000", "등록공고", "분기 검증 공고 E 000", "서울특별시", datetime(2026, 1, 10, 9)),
    ("QTR-E", "002", "변경공고", "분기 검증 공고 E 002", "서울특별시", datetime(2026, 5, 10, 9)),
    ("QTR-F", "000", "등록공고", "분기 검증 공고 F 000", "부산광역시", datetime(2026, 4, 10, 9)),
    ("QTR-F", "001", CANCELLED, "분기 검증 공고 F 001", "부산광역시", datetime(2026, 5, 10, 9)),
)

# 상반기 창에서 최신 차수 한 행만 세고 취소된 최신 차수를 뺀 기대 건수입니다.
EXPECTED_FIRST_QUARTER = 3  # QTR-A 001, QTR-C 001, QTR-D 000
EXPECTED_SECOND_QUARTER = 1  # QTR-E 002


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def seeded_db(isolated_db):
    """분기 경계와 차수 중복을 함께 담은 픽스처를 넣은 세션을 돌려줍니다."""
    for index, (no, ord_value, kind, title, agency, noticed_at) in enumerate(SEEDS):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=no,
                bid_ntce_ord=ord_value,
                bid_ntce_nm=title,
                dminstt_nm=agency,
                ntce_kind_nm=kind,
                category="Servc",
                presmpt_prce=50_000_000,
                base_amount=50_000_000,
                bid_ntce_dt=noticed_at,
                collected_at=datetime(2026, 7, 1, 9) + timedelta(minutes=index),
            )
        )
    isolated_db.commit()
    return isolated_db


def _summary(db, filters: dict) -> dict:
    plan = RetrievalPlan(use_sql=True, filters={**filters, "category": "Servc"})
    return retrieve_structured_data(db, plan)["summary"]


def _quarter_counts(summary: dict) -> dict[str, int]:
    return {item["label"]: item["announcement_count"] for item in summary["time_series"]}


def test_분기_시계열은_최신_차수_한_행만_센다(seeded_db):
    """(a) 같은 공고의 000·001 차수 중 최신 차수 001 만 셉니다."""
    counts = _quarter_counts(_summary(seeded_db, {**HALF_YEAR, "time_bucket": "quarter"}))

    assert counts["2026년 1분기"] == EXPECTED_FIRST_QUARTER
    assert counts["2026년 2분기"] == EXPECTED_SECOND_QUARTER


def test_최신_차수가_취소공고면_이전_차수로도_세지_않는다(seeded_db):
    """(b) 최신 차수가 취소공고면 그 공고는 분기 집계에서 통째로 빠집니다."""
    counts = _quarter_counts(_summary(seeded_db, {**HALF_YEAR, "time_bucket": "quarter"}))

    # QTR-B 000 과 QTR-F 000 은 이전 차수인데도 대신 세지 않습니다.
    assert counts["2026년 1분기"] == EXPECTED_FIRST_QUARTER
    assert counts["2026년 2분기"] == EXPECTED_SECOND_QUARTER
    assert sum(counts.values()) == EXPECTED_FIRST_QUARTER + EXPECTED_SECOND_QUARTER


def test_창_밖_최신_차수는_창_안_이전_차수를_대신_세지_않는다(seeded_db):
    """최신 차수 판정은 요청 창이 아니라 공고 전체를 봅니다.

    QTR-E 의 최신 차수 002 는 2분기(창 밖)에 있습니다. 1분기만 요청한 창에서는
    000 차수를 대신 세우지 않습니다. 파생 테이블로 기간을 먼저 좁히는 계획을
    쓰더라도 이 의미가 유지되는지 확인합니다.
    """
    first_only = _quarter_counts(_summary(seeded_db, {**FIRST_QUARTER, "time_bucket": "quarter"}))
    first_and_second = _quarter_counts(_summary(seeded_db, {**HALF_YEAR, "time_bucket": "quarter"}))

    assert first_only == {"2026년 1분기": EXPECTED_FIRST_QUARTER}
    assert first_and_second["2026년 1분기"] == EXPECTED_FIRST_QUARTER
    assert first_and_second["2026년 2분기"] == EXPECTED_SECOND_QUARTER


def test_분기_합계가_같은_기간_공고_총계와_같다(seeded_db):
    """반조인 범위를 쓰는 분기 경로와 MAX 서브쿼리 총계가 같은 모집단을 봅니다."""
    for window in (HALF_YEAR, FIRST_QUARTER):
        summary = _summary(seeded_db, {**window, "time_bucket": "quarter"})
        counts = _quarter_counts(summary)

        assert sum(counts.values()) == summary["announcement_count"]


def test_공고종류_지정_질의는_분기_범위를_걸지_않는다():
    """공고번호 단건·공고종류 지정 질의는 종전 문장을 그대로 씁니다."""
    identity = structured_data_module._identity_statement
    detail = RetrievalPlan(use_sql=True, filters={"bid_ntce_no": "QTR-A"})
    notice_kind = RetrievalPlan(use_sql=True, filters={"notice_kind": CANCELLED})

    assert structured_data_module._quarter_announcement_scope(detail) is identity
    assert structured_data_module._quarter_announcement_scope(notice_kind) is identity


def test_분기_공고_집계는_기간_파생_테이블과_반조인을_쓴다(seeded_db, monkeypatch):
    """콜드 지연을 줄인 실행 계획 형태가 실제 문장에 남아 있는지 확인합니다."""
    compiled: list[str] = []
    original = structured_data_module._cached_rows

    def _capture(db, stmt):
        compiled.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return original(db, stmt)

    monkeypatch.setattr(structured_data_module, "_cached_rows", _capture)
    _summary(seeded_db, {**HALF_YEAR, "time_bucket": "quarter"})

    announcement_sql = [sql for sql in compiled if "quarter_period_announcements" in sql]
    assert len(announcement_sql) == 1

    # 최신 차수 판정은 "자기보다 큰 차수가 없는 행" 반조인이고, 취소 제외가 뒤따릅니다.
    sql = announcement_sql[0]
    assert "later_ann" in sql
    assert sql.index("later_ann") < sql.index(CANCELLED)
