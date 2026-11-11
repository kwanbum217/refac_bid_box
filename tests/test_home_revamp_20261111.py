"""
tests/test_home_revamp_20261111.py

한 화면 메인(2026-11-11 개편)의 계약을 고정합니다.

1. 홈 응답에 4개 지표와 비교 분석 링크가 있고 스와이프 마크업이 없다.
2. 관심 조건이 없으면 마이페이지 입력 안내를, 있으면 셈 결과를 보여 준다.
3. 365일·입찰 중 셈이 용역·기간·마감·최신 차수 조건을 지킨다.
4. 정확도 문구가 서빙 메타데이터 값에서 나오고, 없으면 '측정값 준비 중' 이다.
5. 요약 캐시가 두 번째 요청에서 대형 테이블을 다시 세지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from src.app.core.cache import cache
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_preferences import AccountBidPreference
from src.app.models.bids import BidAnnouncement
from src.app.services import home_summary

BASE_TIME = datetime(2026, 11, 11, 12, 0, 0)
MODEL_NAME = "servc_institution_v1"


@pytest.fixture(autouse=True)
def _clear_summary_cache():
    """프로세스 간 캐시(Redis 또는 로컬)가 시험 사이에 새지 않게 지웁니다."""
    cache.delete(home_summary.SERVIC_COUNTS_CACHE_KEY)
    yield
    cache.delete(home_summary.SERVIC_COUNTS_CACHE_KEY)


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="home_revamp_tester",
        password=make_password("pw-test-1234"),
        email="home-revamp@example.com",
        nickname="메인 검증",
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
def auth_client(seeded_user):
    token = create_session(seeded_user.id, seeded_user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _write_metadata(root: Path, *, rmse: float, promoted_at: str) -> None:
    slot = root / MODEL_NAME
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "metadata.json").write_text(
        json.dumps(
            {
                "version": "v_test",
                "source_metrics": {"rmse": rmse, "mape": 1.0, "r2": 0.5},
                "promoted_at": promoted_at,
            }
        ),
        encoding="utf-8",
    )


def _add(db, **overrides) -> BidAnnouncement:
    payload: dict[str, Any] = {
        "bid_ntce_no": "ANN-BASE",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 공고",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "bid_ntce_dt": BASE_TIME - timedelta(days=1),
        "bid_clse_dt": BASE_TIME + timedelta(days=1),
        "collected_at": BASE_TIME,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    return row


# --------------------------------------------------------------------------- #
# (1) 화면 구성
# --------------------------------------------------------------------------- #


def test_home_renders_four_metrics_and_shortcuts(auth_client, monkeypatch, tmp_path):
    _write_metadata(tmp_path, rmse=3.4567, promoted_at="2026-01-02T03:04:05")
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    body = auth_client.get("/").text

    for metric in ("accuracy", "recent-year", "open", "matching"):
        assert f'data-home-metric="{metric}"' in body, metric
    for shortcut in ("bid-list", "result-list", "compare", "chatbot"):
        assert f'data-home-shortcut="{shortcut}"' in body, shortcut
    assert "/bids/compare/" in body
    assert "±3.46" in body
    assert ">%p</span>" in body
    assert "2026-01-02" in body
    assert "data-home-swipe-slide" not in body
    assert "data-home-swipe-track" not in body


def test_home_keeps_sidebar_visible(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    body = auth_client.get("/").text

    assert '<aside id="sidebar"' in body
    assert 'id="mobile-nav-drawer"' in body


# --------------------------------------------------------------------------- #
# (2) 관심 조건
# --------------------------------------------------------------------------- #


def test_home_prompts_interest_input_when_preferences_missing(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    body = auth_client.get("/").text

    assert 'data-home-metric="matching"' in body
    assert "/accounts/mypage/edit/" in body
    assert "마이페이지에서 관심 업종·지역 입력" in body
    assert "data-home-matching-count" not in body


def test_home_shows_matching_count_when_preferences_exist(
    auth_client, isolated_db, seeded_user, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    isolated_db.add(
        AccountBidPreference(
            user_id=seeded_user.id,
            license_codes=["1172"],
            region_code="seoul",
        )
    )
    isolated_db.commit()
    monkeypatch.setattr(home_summary, "count_open_servc_matching", lambda *args, **kwargs: 7)

    body = auth_client.get("/").text

    assert 'data-home-matching-count="7"' in body
    assert "마이페이지에서 관심 업종·지역 입력" not in body


# --------------------------------------------------------------------------- #
# (3) 셈 조건
# --------------------------------------------------------------------------- #


def test_servc_counts_respect_category_period_deadline_and_latest_ord(
    isolated_db, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    # 최근 365일 안이지만 이미 마감된 공고
    _add(
        isolated_db,
        bid_ntce_no="ANN-YEAR-CLOSED",
        bid_ntce_dt=BASE_TIME - timedelta(days=100),
        bid_clse_dt=BASE_TIME - timedelta(days=99),
    )
    # 365일 안이며 입찰 중
    _add(
        isolated_db,
        bid_ntce_no="ANN-OPEN",
        bid_ntce_dt=BASE_TIME - timedelta(days=10),
        bid_clse_dt=BASE_TIME + timedelta(days=5),
    )
    # 90일 스캔 경계 안쪽이며 입찰 중
    _add(
        isolated_db,
        bid_ntce_no="ANN-OPEN-LOOKBACK",
        bid_ntce_dt=BASE_TIME - timedelta(days=89),
        bid_clse_dt=BASE_TIME + timedelta(days=1),
    )
    # 365일 밖이라 어느 쪽에도 들지 않음
    _add(
        isolated_db,
        bid_ntce_no="ANN-TOO-OLD",
        bid_ntce_dt=BASE_TIME - timedelta(days=400),
        bid_clse_dt=BASE_TIME + timedelta(days=1),
    )
    # 용역이 아닌 분야
    _add(
        isolated_db,
        bid_ntce_no="ANN-CNSTWK",
        category="Cnstwk",
        bid_ntce_dt=BASE_TIME - timedelta(days=5),
        bid_clse_dt=BASE_TIME + timedelta(days=3),
    )
    # 마감된 공고
    _add(
        isolated_db,
        bid_ntce_no="ANN-CLOSED",
        bid_ntce_dt=BASE_TIME - timedelta(days=20),
        bid_clse_dt=BASE_TIME - timedelta(days=1),
    )
    # 같은 공고번호의 이전 차수와 최신 차수: 최신 차수만 한 건으로 센다
    _add(
        isolated_db,
        bid_ntce_no="ANN-DUP",
        bid_ntce_ord="000",
        bid_ntce_dt=BASE_TIME - timedelta(days=50),
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )
    _add(
        isolated_db,
        bid_ntce_no="ANN-DUP",
        bid_ntce_ord="001",
        bid_ntce_dt=BASE_TIME - timedelta(days=49),
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )

    summary = home_summary.get_home_summary(isolated_db, None, now=BASE_TIME)

    # 연도: YEAR-CLOSED, OPEN, OPEN-LOOKBACK, CLOSED, DUP(최신) = 5
    assert summary["recent_year_count"] == 5
    # 입찰 중: OPEN, OPEN-LOOKBACK, DUP(최신) = 3
    assert summary["open_count"] == 3


# --------------------------------------------------------------------------- #
# (4) 정확도
# --------------------------------------------------------------------------- #


def test_accuracy_is_read_from_serving_metadata(monkeypatch, tmp_path):
    _write_metadata(tmp_path, rmse=1.2345, promoted_at="2026-02-03T04:05:06")
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    accuracy = home_summary.load_serving_accuracy()

    assert accuracy["available"] is True
    assert accuracy["rmse_display"] == "1.23"
    assert accuracy["promoted_date"] == "2026-02-03"


def test_accuracy_placeholder_when_metadata_missing(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    accuracy = home_summary.load_serving_accuracy()
    body = auth_client.get("/").text

    assert accuracy["available"] is False
    assert "측정값 준비 중" in body


# --------------------------------------------------------------------------- #
# (5) 캐시
# --------------------------------------------------------------------------- #


def test_summary_counts_are_not_recounted_on_second_request(isolated_db, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    _add(isolated_db, bid_ntce_no="ANN-CACHE")

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    connection = isolated_db.get_bind()
    event.listen(connection, "before_cursor_execute", record)
    try:
        home_summary.get_home_summary(isolated_db)
        first_counts = [s for s in statements if "count(" in s.lower()]
        statements.clear()
        home_summary.get_home_summary(isolated_db)
        second_counts = [s for s in statements if "count(" in s.lower()]
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert len(first_counts) == 2
    assert second_counts == []
