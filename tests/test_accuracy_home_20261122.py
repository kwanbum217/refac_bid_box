"""
tests/test_accuracy_home_20261122.py

2026-11-22 홈(/) '모델 정확도' 영역 계약을 고정합니다.

1. 실측 분포(`distribution`)가 있으면 타일 네 개(평균 오차, 10건 중 N건,
   예측 범위 적중, 오차 감소)와 그래프 두 개(오차 범위별 적중 비율 가로 막대,
   예측 대 실제 낙찰률 산점도)를 그린다.
2. 구간 실측이 null 이면 범위 적중 타일을 숨기고 목표치로 대체하지 않는다.
3. 분포가 없거나 사이드카 버전이 서빙 버전과 다르면 그래프 두 개를 숨기고
   사이드카·metadata 에서 가능한 타일만 보인다.
4. 캔버스는 부모 너비를 채우고 넓은 화면 2열·모바일 1열이며, 값은 모두
   지표 파일에서 읽어 고정 수치가 없다.

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 임시 지표 디렉터리를 씁니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.services import home_summary

MODEL_NAME = "servc_institution_v1"
PROMOTED_AT = "2026-11-16T05:14:42"
SIDECAR_METRICS: dict[str, Any] = {
    "rmse": 2.5635886886913912,
    "mae": 1.1696424888193127,
    "mape": 1.2762400216558372,
    "r2": 0.7127375883085246,
    "bias": -0.20955855193316036,
}
JS_PATH = Path(__file__).resolve().parents[1] / "src/app/static/js/home-accuracy-chart.js"


def _distribution(
    *,
    share_1pp: float = 0.6234,
    interval: bool = True,
    error_reduction: float = 0.7127,
) -> dict[str, Any]:
    """2026-11-22 계약 형식의 실측 분포입니다. 값은 모두 픽스처입니다."""
    return {
        "bands": [
            {"within_pp": 0.5, "share": 0.4123},
            {"within_pp": 1.0, "share": share_1pp},
            {"within_pp": 2.0, "share": 0.8571},
            {"within_pp": 3.0, "share": 0.9412},
        ],
        "interval": ({"coverage": 0.912, "evaluated": 2980, "target": 0.9} if interval else None),
        "scatter": {"points": [[41.2, 42.1], [55.5, 54.8], [60.1, 63.2]], "seed": 17},
        "error_reduction": error_reduction,
    }


def _write_files(
    serving_root: Path,
    metrics_root: Path,
    *,
    distribution: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
    sidecar_version: str = "v_live",
) -> None:
    slot = serving_root / MODEL_NAME
    generation = slot / "generations" / "v_live" / "metadata.json"
    generation.parent.mkdir(parents=True, exist_ok=True)
    generation.write_text(
        json.dumps(
            {
                "name": MODEL_NAME,
                "version": "v_live",
                "promoted_at": PROMOTED_AT,
                "source_metrics": {"rmse": 2.6994, "mape": 1.3941, "r2": 0.6834},
            }
        ),
        encoding="utf-8",
    )
    (slot / "LIVE").write_text("v_live", encoding="utf-8")

    metrics_root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "model_name": MODEL_NAME,
        "version": sidecar_version,
        "metrics": SIDECAR_METRICS if metrics is None else metrics,
        "measured_at": "2026-11-22T02:54:26.291057",
        "category": "Servc",
        "holdout_since": "2026-01-01",
        "samples": 3000,
        "failed": 0,
        "measured_via": "SingletonPredictor.predict (운영 경로)",
    }
    if distribution is not None:
        payload["distribution"] = distribution
    (metrics_root / f"{MODEL_NAME}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="accuracy_home_tester",
        password=make_password("pw-test-1234"),
        email="accuracy-home@example.com",
        nickname="정확도 화면 검증",
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


def _render(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    distribution: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
    sidecar_version: str = "v_live",
) -> str:
    serving = tmp_path / "serving"
    metrics_dir = tmp_path / "metrics"
    _write_files(
        serving,
        metrics_dir,
        distribution=distribution,
        metrics=metrics,
        sidecar_version=sidecar_version,
    )
    monkeypatch.setattr(home_summary, "SERVING_ROOT", serving)
    monkeypatch.setattr(home_summary, "METRICS_ROOT", metrics_dir)
    return auth_client.get("/").text


def _chart_payload(body: str) -> dict[str, Any]:
    match = re.search(
        r'<script type="application/json" id="home-accuracy-chart-data"[^>]*>(.*?)</script>',
        body,
        re.S,
    )
    assert match is not None
    return json.loads(match.group(1))


# --------------------------------------------------------------------------- #
# (a) 타일 네 개의 값과 문구
# --------------------------------------------------------------------------- #


def test_four_tiles_show_measured_values(auth_client, monkeypatch, tmp_path):
    body = _render(auth_client, monkeypatch, tmp_path, distribution=_distribution())

    assert 'data-home-accuracy-tile="mae"' in body
    assert "평균 오차" in body
    assert f"±{SIDECAR_METRICS['mae']:.2f}" in body
    assert "예측 낙찰률과 실제 낙찰률의 평균 차이" in body

    assert 'data-home-accuracy-tile="within_1pp"' in body
    assert "±1%p 이내 적중" in body
    assert "10건 중 6건" in body
    assert "실제 낙찰률과 ±1%p 이내로 맞힌 공고" in body

    assert 'data-home-accuracy-tile="interval_coverage"' in body
    assert "예측 범위 적중" in body
    assert "91.2" in body
    assert "제시한 하한~상한 범위 안에 실제 낙찰률이 들어온 비율(실측)" in body

    assert 'data-home-accuracy-tile="error_reduction"' in body
    assert "오차 감소" in body
    assert "71.3" in body
    assert "모든 공고를 평균 낙찰률로 예측할 때보다 오차(제곱 기준)를 줄인 정도" in body

    # 사용자가 근거를 읽을 수 있는 한 줄 설명과 작은 글씨입니다.
    assert "학습에 쓰지 않은 2026년 공고로 실제 예측해 잰 값입니다." in body
    assert "RMSE 2.56%p" in body
    assert "검증 3,000건" in body
    assert "2026-01-01 이후 공고" in body
    assert "2026-11-16 승격 모델" in body


# --------------------------------------------------------------------------- #
# (b) interval null 이면 범위 적중 타일을 숨긴다
# --------------------------------------------------------------------------- #


def test_interval_tile_hidden_when_coverage_missing(auth_client, monkeypatch, tmp_path):
    body = _render(
        auth_client,
        monkeypatch,
        tmp_path,
        distribution=_distribution(interval=False),
    )

    assert 'data-home-accuracy-tile="interval_coverage"' not in body
    assert "예측 범위 적중" not in body
    # 목표치(90%)를 실측처럼 대신 보여 주지 않는다.
    assert "목표" not in body
    # 나머지 타일 세 개는 그대로 보인다.
    assert 'data-home-accuracy-tile="mae"' in body
    assert 'data-home-accuracy-tile="within_1pp"' in body
    assert 'data-home-accuracy-tile="error_reduction"' in body


# --------------------------------------------------------------------------- #
# (c) 분포가 없거나 버전이 다르면 그래프를 숨기고 가능한 타일만 보인다
# --------------------------------------------------------------------------- #


def test_graphs_hidden_without_distribution(auth_client, monkeypatch, tmp_path):
    body = _render(auth_client, monkeypatch, tmp_path, distribution=None)

    assert 'id="home-accuracy-band-chart"' not in body
    assert 'id="home-accuracy-scatter-chart"' not in body
    assert 'id="home-accuracy-chart-data"' not in body
    assert "오차 범위별 적중 비율" not in body
    assert "예측 대 실제 낙찰률" not in body

    assert 'data-home-accuracy-tile="mae"' in body
    assert 'data-home-accuracy-tile="error_reduction"' in body
    assert 'data-home-accuracy-tile="within_1pp"' not in body
    assert 'data-home-accuracy-tile="interval_coverage"' not in body


def test_graphs_hidden_when_sidecar_version_differs(auth_client, monkeypatch, tmp_path):
    body = _render(
        auth_client,
        monkeypatch,
        tmp_path,
        distribution=_distribution(),
        sidecar_version="v_stale",
    )

    assert 'id="home-accuracy-band-chart"' not in body
    assert 'id="home-accuracy-scatter-chart"' not in body
    # 승격 지표로 물러나므로 실측 평균 오차 타일도 사라진다.
    assert 'data-home-accuracy-tile="mae"' not in body
    assert 'data-home-accuracy-tile="error_reduction"' in body
    assert "승격 시 검증 지표" in body


# --------------------------------------------------------------------------- #
# (d) 템플릿의 그래프 데이터와 반응형 설정
# --------------------------------------------------------------------------- #


def test_template_has_both_charts_and_responsive_layout(auth_client, monkeypatch, tmp_path):
    body = _render(auth_client, monkeypatch, tmp_path, distribution=_distribution())

    assert 'id="home-accuracy-band-chart"' in body
    assert 'id="home-accuracy-scatter-chart"' in body
    # 넓은 화면 2열, 모바일 1열이며 캔버스 영역이 부모 너비를 채운다.
    assert "lg:grid-cols-2" in body
    assert "h-64 w-full sm:h-80" in body
    assert "±2.0%p 범위" in body

    payload = _chart_payload(body)
    assert payload["visible"] is True
    assert [band["label"] for band in payload["bands"]] == [
        "±0.5%p",
        "±1%p",
        "±2%p",
        "±3%p",
    ]
    assert payload["scatter"]["points"] == [[41.2, 42.1], [55.5, 54.8], [60.1, 63.2]]
    assert payload["scatter"]["axis_min"] < payload["scatter"]["axis_max"]

    script = JS_PATH.read_text(encoding="utf-8")
    # 두 차트 모두 부모 크기를 따르고 세로 비율을 고정하지 않는다.
    assert script.count("maintainAspectRatio: false") == 2
    assert "indexAxis: 'y'" in script
    assert "homeAccuracyBarValueLabels" in script
    assert "homeAccuracyPerfectBand" in script
    assert "band_pp" in script


# --------------------------------------------------------------------------- #
# (e) 고정 수치 없음: 픽스처 값을 바꾸면 화면 값도 바뀐다
# --------------------------------------------------------------------------- #


def test_rendered_values_follow_metric_files(auth_client, monkeypatch, tmp_path):
    first = _render(auth_client, monkeypatch, tmp_path, distribution=_distribution())
    assert "10건 중 6건" in first
    assert "±1.17" in first
    assert _chart_payload(first)["bands"][1]["percent"] == 62.3

    second_metrics = {**SIDECAR_METRICS, "mae": 0.8712}
    second = _render(
        auth_client,
        monkeypatch,
        tmp_path / "second",
        distribution=_distribution(share_1pp=0.2821, error_reduction=0.5123),
        metrics=second_metrics,
    )
    assert "10건 중 3건" in second
    assert "±0.87" in second
    assert "51.2" in second
    assert "10건 중 6건" not in second
    assert "±1.17" not in second
    assert _chart_payload(second)["bands"][1]["percent"] == 28.2
    assert _chart_payload(second)["bands"][1]["percent"] != 62.3
