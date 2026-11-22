"""
tests/test_web_home_accuracy_chart_20261122.py

2026-11-22 메인 화면 계약을 고정합니다.

1. '최근 365일 공고' 카드가 없고 '모델 정확도' 카드가 전체 너비 한 줄이다.
2. 입찰 중 공고 건수와 마감 구간은 4대 업종(파견·경비업·위생관리용역업·
   유료직업소개업) 공고만 세고, 업종 밖·업종 제한 행 없음 공고는 뺀다.
   네 구간 합은 항상 건수와 같다.
3. 정확도 타일과 그래프 데이터는 지표 파일(사이드카·세대 metadata)에서 읽은
   값과 같고, 세대가 두 개 미만이거나 파일이 없으면 그래프를 숨긴다.

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 임시 지표 디렉터리를 씁니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement
from src.app.services import home_summary

BASE_TIME = datetime(2026, 11, 22, 12, 0, 0)
MODEL_NAME = "servc_institution_v1"


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


def _add_license(db, bid: BidAnnouncement, code: str, *, field: str = "lcns_lmt_nm") -> None:
    values: dict[str, Any] = {"collected_at": BASE_TIME, field: f"/{code}/"}
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord=bid.bid_ntce_ord,
            **values,
        )
    )
    db.commit()


def _write_generation(
    serving_root: Path,
    version: str,
    *,
    rmse: float,
    mape: float,
    r2: float,
    promoted_at: str,
    interval: dict[str, Any] | None = None,
) -> None:
    gen_dir = serving_root / MODEL_NAME / "generations" / version / "metadata.json"
    gen_dir.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "name": MODEL_NAME,
        "version": version,
        "promoted_at": promoted_at,
        "source_metrics": {"rmse": rmse, "mape": mape, "r2": r2},
    }
    if interval is not None:
        payload["interval"] = interval
    gen_dir.write_text(json.dumps(payload), encoding="utf-8")


def _write_live(serving_root: Path, version: str) -> None:
    slot = serving_root / MODEL_NAME
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "LIVE").write_text(version, encoding="utf-8")


def _write_sidecar(metrics_root: Path, version: str, metrics: dict[str, Any], **extra: Any) -> None:
    metrics_root.mkdir(parents=True, exist_ok=True)
    payload = {"model_name": MODEL_NAME, "version": version, "metrics": metrics}
    payload.update(extra)
    (metrics_root / f"{MODEL_NAME}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="web_home_accuracy_tester",
        password=make_password("pw-test-1234"),
        email="web-home-accuracy@example.com",
        nickname="정확도 검증",
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


# --------------------------------------------------------------------------- #
# (1) 화면 구성: 365일 카드 삭제, 정확도 카드 전체 너비
# --------------------------------------------------------------------------- #


def test_home_has_no_recent_year_card_and_renders_accuracy_chart(
    auth_client, monkeypatch, tmp_path
):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_live(serving, "v_new")
    _write_generation(
        serving,
        "v_old",
        rmse=2.7003,
        mape=1.3917,
        r2=0.6833,
        promoted_at="2026-11-14T02:04:07",
    )
    _write_generation(
        serving,
        "v_new",
        rmse=2.6994,
        mape=1.3941,
        r2=0.6834,
        promoted_at="2026-11-16T05:14:42",
        interval={"target_coverage": 0.9, "calibration_samples": 140350},
    )
    _write_sidecar(
        metrics,
        "v_new",
        {"rmse": 2.5635886886913912, "mae": 1.1696424888193127, "r2": 0.7127375883085246},
        samples=3000,
        holdout_since="2026-01-01",
    )
    monkeypatch.setattr(home_summary, "SERVING_ROOT", serving)
    monkeypatch.setattr(home_summary, "METRICS_ROOT", metrics)

    body = auth_client.get("/").text

    assert 'data-home-metric="recent-year"' not in body
    assert "최근 365일 공고" not in body
    assert 'data-home-metric="accuracy"' in body
    assert "data-home-accuracy-chart-card" in body
    assert 'id="home-accuracy-chart"' in body
    assert 'id="home-accuracy-chart-data"' in body
    assert "승격 세대별 오차 추이" in body
    # 정확도 카드는 2열 지표 그리드가 아니라 단독 섹션입니다.
    assert "grid gap-4 md:grid-cols-2" not in body
    # 값은 사이드카 실측에서 읽습니다.
    assert "2.56" in body


def test_home_shows_pending_label_without_accuracy_files(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path / "empty_serving")
    monkeypatch.setattr(home_summary, "METRICS_ROOT", tmp_path / "empty_metrics")

    body = auth_client.get("/").text

    assert "측정값 준비 중" in body
    assert 'id="home-accuracy-chart"' not in body
    assert 'data-home-metric="recent-year"' not in body


# --------------------------------------------------------------------------- #
# (2) 입찰 중 건수·마감 구간: 4대 업종만 센다
# --------------------------------------------------------------------------- #


def test_open_counts_only_four_industry_codes(isolated_db):
    expected_versions = {
        "INDUSTRY-DISPATCH": ("1172", "lcns_lmt_nm", datetime(2026, 11, 22, 18, 0)),
        "INDUSTRY-SECURITY": ("1167", "permsn_indstryty_list", datetime(2026, 11, 24, 9, 0)),
        "INDUSTRY-SANITATION": ("1162", "lcns_lmt_nm", datetime(2026, 11, 27, 9, 0)),
        "INDUSTRY-JOB": ("5603", "lcns_lmt_nm", datetime(2026, 12, 5, 9, 0)),
    }
    for bid_no, (code, field, close_dt) in expected_versions.items():
        bid = _add(isolated_db, bid_ntce_no=bid_no, bid_clse_dt=close_dt)
        _add_license(isolated_db, bid, code, field=field)

    # 업종 코드 묶음 밖(7740 가축방역위생관리업, 9999)은 세지 않는다.
    outside = _add(
        isolated_db, bid_ntce_no="OUTSIDE-CODE", bid_clse_dt=BASE_TIME + timedelta(days=2)
    )
    _add_license(isolated_db, outside, "7740")
    outside_etc = _add(
        isolated_db, bid_ntce_no="OUTSIDE-9999", bid_clse_dt=BASE_TIME + timedelta(days=2)
    )
    _add_license(isolated_db, outside_etc, "9999")

    # 업종 제한 행이 없는 공고도 세지 않는다.
    _add(isolated_db, bid_ntce_no="NO-LICENSE", bid_clse_dt=BASE_TIME + timedelta(days=2))
    # 마감된 공고, 다른 분야, 90일 밖 공고는 세지 않는다.
    closed = _add(isolated_db, bid_ntce_no="CLOSED", bid_clse_dt=BASE_TIME - timedelta(hours=1))
    _add_license(isolated_db, closed, "1172")
    other_category = _add(
        isolated_db,
        bid_ntce_no="CNSTWK",
        category="Cnstwk",
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )
    _add_license(isolated_db, other_category, "1172")
    old = _add(
        isolated_db,
        bid_ntce_no="OLD-NOTICE",
        bid_ntce_dt=BASE_TIME - timedelta(days=120),
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )
    _add_license(isolated_db, old, "1172")

    # 같은 공고번호의 두 차수는 최신 차수만 한 건으로 센다.
    for order, notice_days in (("000", 10), ("001", 5)):
        duplicate = _add(
            isolated_db,
            bid_ntce_no="INDUSTRY-DUP",
            bid_ntce_ord=order,
            bid_ntce_dt=BASE_TIME - timedelta(days=notice_days),
            bid_clse_dt=BASE_TIME + timedelta(days=5),
        )
        _add_license(isolated_db, duplicate, "1164")

    summary = home_summary.get_home_summary(isolated_db, None, now=BASE_TIME)
    buckets = {bucket["key"]: bucket["count"] for bucket in summary["open_deadline_buckets"]}

    assert summary["open_count"] == 5
    assert buckets == {"today": 1, "d1_3": 1, "d4_7": 2, "d8_plus": 1}
    assert sum(buckets.values()) == summary["open_count"]
    assert "recent_year_count" not in summary


def test_cached_open_counts_keep_four_industry_definition(isolated_db, monkeypatch):
    class FakeCache:
        def __init__(self) -> None:
            self._store: dict[str, Any] = {}
            self.set_calls: list[tuple[str, Any, int]] = []

        def get(self, key: str) -> Any:
            return self._store.get(key)

        def set(self, key: str, value: Any, ttl: int) -> None:
            self._store[key] = value
            self.set_calls.append((key, value, ttl))

    fake_cache = FakeCache()
    monkeypatch.setattr(home_summary, "cache", fake_cache)
    monkeypatch.setattr(home_summary, "kst_now", lambda: BASE_TIME)

    bid = _add(isolated_db, bid_ntce_no="CACHE-OPEN", bid_clse_dt=BASE_TIME + timedelta(days=2))
    _add_license(isolated_db, bid, "1172")

    warmed = home_summary.warm_home_summary_cache(isolated_db)

    assert "recent_year_count" not in warmed
    assert warmed["open_count"] == 1
    assert sum(bucket["count"] for bucket in warmed["open_deadline_buckets"]) == 1
    assert fake_cache.set_calls[-1][0] == home_summary.SERVIC_COUNTS_CACHE_KEY
    # 셈 정의가 4대 업종으로 바뀌었으므로 옛 v1 키를 쓰지 않는다.
    assert home_summary.SERVIC_COUNTS_CACHE_KEY.endswith(":v2")


# --------------------------------------------------------------------------- #
# (3) 정확도 지표·그래프 데이터: 지표 파일 값과 같다
# --------------------------------------------------------------------------- #


def test_accuracy_tiles_and_chart_match_metric_files(tmp_path):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_live(serving, "v_new")

    old_meta = {
        "version": "v_old",
        "promoted_at": "2026-11-14T02:04:07",
        "source_metrics": {"rmse": 2.7003, "mape": 1.3917, "r2": 0.6833},
    }
    new_meta = {
        "version": "v_new",
        "promoted_at": "2026-11-16T05:14:42",
        "source_metrics": {"rmse": 2.6994, "mape": 1.3941, "r2": 0.6834},
        "interval": {"target_coverage": 0.9, "calibration_samples": 140350},
    }
    for version, payload in (("v_old", old_meta), ("v_new", new_meta)):
        path = serving / MODEL_NAME / "generations" / version / "metadata.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    sidecar_metrics = {
        "rmse": 2.5635886886913912,
        "mae": 1.1696424888193127,
        "mape": 1.2762400216558372,
        "r2": 0.7127375883085246,
        "bias": -0.20955855193316036,
    }
    _write_sidecar(
        metrics,
        "v_new",
        sidecar_metrics,
        samples=3000,
        holdout_since="2026-01-01",
    )

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)

    assert accuracy["available"] is True
    assert accuracy["source"] == "measured"
    assert accuracy["version"] == "v_new"
    assert accuracy["rmse_display"] == f"{sidecar_metrics['rmse']:.2f}"
    tiles = {tile["key"]: tile for tile in accuracy["tiles"]}
    assert tiles["rmse"]["value"] == f"{sidecar_metrics['rmse']:.2f}"
    assert tiles["mae"]["value"] == f"{sidecar_metrics['mae']:.2f}"
    assert tiles["r2"]["value"] == f"{sidecar_metrics['r2'] * 100:.1f}"
    assert tiles["coverage"]["value"] == "90"
    assert "140,350" in tiles["coverage"]["note"]
    assert tiles["validation"]["value"] == "3,000"
    assert "2026-01-01" in tiles["validation"]["note"]

    chart = accuracy["chart"]
    assert chart["visible"] is True
    assert chart["labels"] == ["2026-11-14", "2026-11-16"]
    assert chart["versions"] == ["v_old", "v_new"]
    series = {item["key"]: item for item in chart["series"]}
    assert series["rmse"]["data"] == [
        round(old_meta["source_metrics"]["rmse"], 4),
        round(new_meta["source_metrics"]["rmse"], 4),
    ]
    assert series["mape"]["data"] == [
        round(old_meta["source_metrics"]["mape"], 4),
        round(new_meta["source_metrics"]["mape"], 4),
    ]


def test_accuracy_falls_back_to_promoted_metrics_when_sidecar_version_differs(tmp_path):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    _write_live(serving, "v_new")
    _write_generation(
        serving,
        "v_new",
        rmse=2.6994,
        mape=1.3941,
        r2=0.6834,
        promoted_at="2026-11-16T05:14:42",
        interval={"target_coverage": 0.9},
    )
    _write_sidecar(metrics, "v_stale", {"rmse": 1.0, "mae": 0.5})

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)
    tiles = {tile["key"]: tile for tile in accuracy["tiles"]}

    assert accuracy["source"] == "promoted"
    assert accuracy["rmse_display"] == "2.70"
    assert tiles["rmse"]["value"] == "2.70"
    # 세대가 하나뿐이라 추이 그래프는 숨긴다.
    assert accuracy["chart"]["visible"] is False
    assert accuracy["chart"]["series"] == []


def test_accuracy_chart_hidden_when_generation_metadata_missing(tmp_path):
    serving = tmp_path / "serving"
    metrics = tmp_path / "metrics"
    slot = serving / MODEL_NAME
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "metadata.json").write_text(
        json.dumps({"version": "v_only", "source_metrics": {"rmse": 2.5, "mape": 1.2, "r2": 0.7}}),
        encoding="utf-8",
    )

    accuracy = home_summary.load_serving_accuracy(serving, metrics_dir=metrics)

    assert accuracy["available"] is True
    assert accuracy["chart"]["visible"] is False
    assert accuracy["tiles"]
