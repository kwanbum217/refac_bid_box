"""tests/test_count_list_dedup_20261123.py

공고 차수 중복 감사(2026-11-23)의 P2·P3 회귀 시험입니다.

같은 공고번호가 차수(ord)를 달리해 여러 행으로 쌓이므로, 행 수를 그대로 쓰면
화면·목록·예측이 부풀려집니다. 이 파일은 세 지점이 같은 정의
(`bid_queries.similar_announcement_latest_filter`, `not_cancelled_clause`)를
쓰는지 고정합니다.

(a) 채팅 화면 'Records Indexed' 는 전체 행 수가 아니라 서로 다른 공고 수입니다.
(b) 홈 컨텍스트 최근 공고 목록은 최신 차수 행만 쓰고, 최신 차수가 취소공고인
    번호는 뺍니다. 재공고·변경공고·NULL 은 유지합니다.
(c) 챗봇 기본 예측 대상도 같은 규칙에 금액 0 초과 조건을 더해 지킵니다.
(d) Records Indexed 집계는 캐시하며 키에 색인 정의 버전이 붙습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.api import ui
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.services import home_context
from src.app.services.tools.bid_prediction_tool import _latest_predictable_bids

BASE_TIME = datetime(2026, 11, 20, 12, 0, 0)


def _row(
    *,
    bid_ntce_no: str,
    ord_: str,
    minutes_ago: int,
    category: str = "Servc",
    ntce_kind_nm: str | None = None,
    base_amount: int | None = 1_000_000,
    presmpt_prce: int | None = 990_000,
) -> BidAnnouncement:
    moment = BASE_TIME - timedelta(minutes=minutes_ago)
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=ord_,
        bid_ntce_nm=f"공고 {bid_ntce_no} {ord_}",
        category=category,
        ntce_kind_nm=ntce_kind_nm,
        base_amount=base_amount,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=moment,
        collected_at=moment,
        raw_data={},
    )


def _seed(db: Session, rows: list[BidAnnouncement]) -> None:
    db.add_all(rows)
    db.commit()


# --------------------------------------------------------------------------- #
# (a) 채팅 화면 Records Indexed
# --------------------------------------------------------------------------- #


def test_records_indexed_counts_distinct_announcements(isolated_db):
    """같은 공고의 000·001 차수 두 행은 색인 문서 1건으로 셉니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-IDX-001", ord_="000", minutes_ago=30),
            _row(bid_ntce_no="ANN-IDX-001", ord_="001", minutes_ago=20),
            _row(bid_ntce_no="ANN-IDX-002", ord_="000", minutes_ago=10),
        ],
    )

    assert ui._indexed_announcement_count(isolated_db) == 2


def test_chat_page_renders_distinct_announcement_count(isolated_db):
    """채팅 헤더 문구가 전체 행 수(3)가 아니라 서로 다른 공고 수(2)를 보여 줍니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-IDX-001", ord_="000", minutes_ago=30),
            _row(bid_ntce_no="ANN-IDX-001", ord_="001", minutes_ago=20),
            _row(bid_ntce_no="ANN-IDX-002", ord_="000", minutes_ago=10),
        ],
    )
    user = CustomUser(
        username="count_tester",
        password=make_password("pw-test-1234"),
        email="count@example.com",
        nickname="건수 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    client = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session(user.id, user.username)})

    body = client.get("/chatbot/").text

    assert "2 Records Indexed" in body
    assert "3 Records Indexed" not in body


# --------------------------------------------------------------------------- #
# (d) Records Indexed 캐시
# --------------------------------------------------------------------------- #


def test_records_indexed_cache_key_carries_definition_version():
    """색인 정의가 바뀌면 이전 값을 버리도록 키에 정의 버전이 붙습니다."""
    assert "distinct_announcement" in ui.CHAT_INDEXED_RECORDS_CACHE_KEY
    assert ui.CHAT_INDEXED_RECORDS_CACHE_KEY.endswith(":v1")
    assert ui.CHAT_INDEXED_RECORDS_CACHE_TTL > 0


def test_records_indexed_uses_cache_for_repeat_requests(isolated_db, monkeypatch):
    """페이지 요청마다 20초 넘는 집계를 다시 돌리지 않습니다."""
    calls: list[int] = []

    def _count(db: Session) -> int:
        calls.append(1)
        return 4_950_157

    monkeypatch.setattr(ui, "count_db_announcements", _count)

    assert ui._indexed_announcement_count(isolated_db) == 4_950_157
    assert ui._indexed_announcement_count(isolated_db) == 4_950_157
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# (b) 홈 컨텍스트 최근 공고 목록
# --------------------------------------------------------------------------- #


def _home_recent_rows(isolated_db) -> list[tuple[str, str]]:
    rows = home_context._recent_unique_announcements(
        isolated_db,
        select(BidAnnouncement),
        limit=8,
        latest_collected_at=BASE_TIME,
    )
    return [(row.bid_ntce_no, row.bid_ntce_ord) for row in rows]


def test_home_recent_uses_latest_ord_not_newest_collected_row(isolated_db):
    """이전 차수가 더 나중에 수집됐어도 최신 차수 행만 남깁니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-HOME-LATE", ord_="000", minutes_ago=5),
            _row(bid_ntce_no="ANN-HOME-LATE", ord_="001", minutes_ago=60),
        ],
    )

    assert _home_recent_rows(isolated_db) == [("ANN-HOME-LATE", "001")]


def test_home_recent_excludes_latest_cancelled_without_falling_back(isolated_db):
    """최신 차수가 취소공고인 번호는 이전 차수로 대신 채우지 않고 뺍니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-HOME-CANCEL", ord_="000", minutes_ago=40),
            _row(
                bid_ntce_no="ANN-HOME-CANCEL",
                ord_="001",
                minutes_ago=10,
                ntce_kind_nm="취소공고",
            ),
        ],
    )

    assert _home_recent_rows(isolated_db) == []


def test_home_recent_keeps_reannouncement_change_and_null_kind(isolated_db):
    """재공고·변경공고와 공고종류가 없는 행은 유지합니다."""
    _seed(
        isolated_db,
        [
            _row(
                bid_ntce_no="ANN-HOME-RE",
                ord_="001",
                minutes_ago=30,
                ntce_kind_nm="재공고",
            ),
            _row(
                bid_ntce_no="ANN-HOME-CHG",
                ord_="001",
                minutes_ago=20,
                ntce_kind_nm="변경공고",
            ),
            _row(bid_ntce_no="ANN-HOME-NULL", ord_="000", minutes_ago=10),
        ],
    )

    assert sorted(_home_recent_rows(isolated_db)) == [
        ("ANN-HOME-CHG", "001"),
        ("ANN-HOME-NULL", "000"),
        ("ANN-HOME-RE", "001"),
    ]


def test_home_recent_latest_is_per_category_partition(isolated_db):
    """최신 차수 판정은 공고번호+카테고리 파티션 단위입니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-HOME-CAT", ord_="000", minutes_ago=30, category="Servc"),
            _row(bid_ntce_no="ANN-HOME-CAT", ord_="001", minutes_ago=20, category="Thng"),
        ],
    )

    assert sorted(_home_recent_rows(isolated_db)) == [
        ("ANN-HOME-CAT", "000"),
        ("ANN-HOME-CAT", "001"),
    ]


# --------------------------------------------------------------------------- #
# (c) 챗봇 기본 예측 대상
# --------------------------------------------------------------------------- #


def _predictable_keys(isolated_db, limit: int = 8) -> list[tuple[str, str]]:
    rows = _latest_predictable_bids(isolated_db, limit=limit)
    return [(row.bid_ntce_no, row.bid_ntce_ord) for row in rows]


def test_prediction_targets_use_latest_ord(isolated_db):
    """이전 차수가 더 최근에 수집돼도 예측 대상은 최신 차수 행입니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-PRED-LATE", ord_="000", minutes_ago=5),
            _row(bid_ntce_no="ANN-PRED-LATE", ord_="001", minutes_ago=60),
        ],
    )

    assert _predictable_keys(isolated_db) == [("ANN-PRED-LATE", "001")]


def test_prediction_targets_exclude_latest_cancelled(isolated_db):
    """최신 차수가 취소공고면 이전 차수로 대신 예측하지 않습니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-PRED-CANCEL", ord_="000", minutes_ago=40),
            _row(
                bid_ntce_no="ANN-PRED-CANCEL",
                ord_="001",
                minutes_ago=10,
                ntce_kind_nm="취소공고",
            ),
        ],
    )

    assert _predictable_keys(isolated_db) == []


def test_prediction_targets_keep_amount_rule(isolated_db):
    """최신 차수에 금액이 없으면 이전 차수의 금액으로 대체하지 않습니다."""
    _seed(
        isolated_db,
        [
            _row(bid_ntce_no="ANN-PRED-ZERO", ord_="000", minutes_ago=40),
            _row(
                bid_ntce_no="ANN-PRED-ZERO",
                ord_="001",
                minutes_ago=10,
                base_amount=0,
                presmpt_prce=0,
            ),
            _row(
                bid_ntce_no="ANN-PRED-OK",
                ord_="001",
                minutes_ago=20,
                ntce_kind_nm="재공고",
            ),
        ],
    )

    rows = _latest_predictable_bids(isolated_db, limit=8)

    assert [(row.bid_ntce_no, row.bid_ntce_ord) for row in rows] == [("ANN-PRED-OK", "001")]
    assert all(float(row.prediction_reference_amount or 0) > 0 for row in rows)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
