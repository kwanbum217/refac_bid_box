"""
tests/test_qualification_badge_regime_20261109.py

F-04 회귀 시험: 목록·홈 배지와 Meilisearch 색인 문서가 저장된 첨부 판별 갈래
(`bid_announcement_regime`)를 쓰지 않아 DB 대체 필터·`/evaluations/analyze` 판정과
어긋나던 결함을 고정합니다.

검증 항목:
(1) MOIS_ACADEMIC 갈래가 있는 '2억미만 1억이상' 띠 공고는 목록 배지, 홈 배지,
    색인 문서 `qualification_analyzable`, DB 대체 필터, analyze 규칙 판별이 모두 같다.
(2) 갈래가 없는 같은 띠 공고는 수정 이전과 같이 분석 대상이 아니다.
(3) 목록 한 페이지의 갈래 조회 질의는 한 번이다.
(4) 갈래 분류 실행 뒤 새로 CLASSIFIED 된 공고의 색인 upsert 가 호출된다.

실물 Meilisearch·운영 DB 는 쓰지 않습니다. conftest 의 SQLite 인메모리 DB 와
가짜 내려받기·추출·Meilisearch 클라이언트만 사용합니다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event

from scripts import classify_band_regime as classify_script
from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.announcement_regime import (
    REGIME_STATUS_CLASSIFIED,
    BidAnnouncementRegime,
)
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services import bid_queries
from src.app.services.band_regime_lookup import (
    attachment_regime_key,
    lookup_attachment_regimes,
)
from src.app.services.bid_queries import qualification_analyzable_ids
from src.app.services.search_index import _build_announcement_batch
from tests.test_ui_ssr import auth_client, seeded_user  # noqa: F401

BADGE_TEXT = "적격심사 분석"
BAND_METHOD = "적격심사제-추정가격 2억미만 1억이상"
MOIS_ACADEMIC = "MOIS_ACADEMIC"
ANALYZE_URL = "/api/v1/evaluations/analyze"

MOIS_BID_NO = "R26BK91000001"
PLAIN_BAND_NO = "R26BK91000002"
NORMAL_BID_NO = "R26BK91000003"
CLASSIFY_BID_NO = "R26BK92000001"

BAND_RAW: dict[str, Any] = {
    "prearngPrceDcsnMthdNm": "복수예가",
    "sucsfbidMthdNm": BAND_METHOD,
    "sucsfbidLwltRate": "89.995",
}
NORMAL_RAW: dict[str, Any] = {
    "prearngPrceDcsnMthdNm": "복수예가",
    "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
    "sucsfbidLwltRate": "89.995",
    "srvceDivNm": "일반용역",
}
CLASSIFIER_TEXT = (
    "「지방자치단체 입찰시 낙찰자 결정기준」의 [별표 4] 학술연구용역의 "
    "적격심사 세부기준 중 추정가격 2억미만 1억이상"
)
CLASSIFY_BID_DT = datetime(2026, 6, 1, 10, 0, 0)
CLASSIFY_PERIOD = (date(2026, 5, 1), date(2026, 7, 1))


def _add_bid(
    db,
    bid_ntce_no: str,
    raw_data: dict[str, Any],
    *,
    presmpt_prce: int,
    bid_ntce_dt: datetime,
    collected_at: datetime,
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"적격심사 갈래 시험 공고 {bid_ntce_no}",
        dminstt_nm="갈래 시험 수요기관",
        category="Servc",
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=bid_ntce_dt,
        bid_clse_dt=bid_ntce_dt + timedelta(days=7),
        collected_at=collected_at,
        raw_data=dict(raw_data),
    )
    db.add(bid)
    db.commit()
    # 목록 화면의 기본 조건인 4개 업종 중 하나에 걸리도록 면허제한 행을 함께 심습니다.
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="건물위생관리업/1162",
            collected_at=collected_at,
        )
    )
    db.commit()
    db.refresh(bid)
    return bid


@pytest.fixture
def seeded_regime_bids(isolated_db) -> dict[str, BidAnnouncement]:
    """갈래 있는 띠 공고, 갈래 없는 띠 공고, 일반 적격심사 공고를 함께 심습니다."""
    now = utcnow()
    bids = {
        "regime": _add_bid(
            isolated_db,
            MOIS_BID_NO,
            BAND_RAW,
            presmpt_prce=150_000_000,
            bid_ntce_dt=now,
            collected_at=now,
        ),
        "plain_band": _add_bid(
            isolated_db,
            PLAIN_BAND_NO,
            BAND_RAW,
            presmpt_prce=150_000_000,
            bid_ntce_dt=now,
            collected_at=now,
        ),
        "normal": _add_bid(
            isolated_db,
            NORMAL_BID_NO,
            NORMAL_RAW,
            presmpt_prce=500_000_000,
            bid_ntce_dt=now,
            collected_at=now,
        ),
    }
    isolated_db.add(
        BidAnnouncementRegime(
            bid_ntce_no=MOIS_BID_NO,
            bid_ntce_ord="000",
            category="Servc",
            regime=MOIS_ACADEMIC,
            status=REGIME_STATUS_CLASSIFIED,
            classifier_version="1.2.0",
        )
    )
    isolated_db.commit()
    # 요청마다 get_db 대역이 세션을 닫으므로, 마지막 commit 으로 만료된 속성을 미리
    # 다시 읽어 두어야 응답 뒤에도 공고 식별자를 쓸 수 있습니다.
    for bid in bids.values():
        isolated_db.refresh(bid)
    return bids


def _row_html(html: str, title: str) -> str:
    start = html.index(title)
    row_start = html.rfind("<tr", 0, start)
    row_end = html.index("</tr>", start)
    return html[row_start:row_end]


def _home_card_html(html: str, bid_id: int) -> str:
    marker = f'href="/bids/{bid_id}/" class="home-slide-card'
    start = html.index(marker)
    card_start = html.rfind("<a ", 0, start)
    card_end = html.index("</a>", start)
    return html[card_start:card_end]


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=7)
    yield
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture
def stub_prediction(monkeypatch):
    """모델 가중치를 로드하지 않도록 예측 API 를 대역으로 덮습니다."""

    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=130_000_000,
            prediction_rate=86.0,
            model_name="테스트 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _analyze_payload(bid_id: int) -> dict[str, Any]:
    return {
        "bid_id": bid_id,
        "candidate_bid_amount": 130_000_000,
        "qualification_input": {"manual_non_price_score": 60.0},
    }


def _analyze_resolves_rule(client, bid_id: int) -> bool:
    """analyze 응답의 규칙 판별 성공 여부. 차단 응답은 rule_id 가 None 입니다."""
    response = client.post(ANALYZE_URL, json=_analyze_payload(bid_id))
    assert response.status_code == 200, response.text
    return response.json()["rule_id"] is not None


def _document_by_id(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {document["id"]: document for document in documents}


# --------------------------------------------------------------------------- #
# (1) 갈래가 있으면 배지·색인·필터·analyze 판정이 모두 같다
# --------------------------------------------------------------------------- #


def test_regime_bid_badge_filter_index_and_analysis_all_agree(
    monkeypatch,
    auth_client,  # noqa: F811
    client,
    seeded_regime_bids,
    isolated_db,
    as_user,
    stub_prediction,
):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    regime_bid = seeded_regime_bids["regime"]

    list_html = auth_client.get("/bids/").text
    assert BADGE_TEXT in _row_html(list_html, regime_bid.bid_ntce_nm)

    home_html = auth_client.get("/").text
    assert BADGE_TEXT in _home_card_html(home_html, regime_bid.id)

    documents = _document_by_id(_build_announcement_batch(isolated_db, [regime_bid]))
    assert documents[f"announcement_Servc_{MOIS_BID_NO}"]["qualification_analyzable"] is True

    filtered = bid_queries.list_announcements(isolated_db, qualification_only=True)
    assert regime_bid.id in {row.id for row in filtered.object_list}

    assert _analyze_resolves_rule(client, regime_bid.id) is True


# --------------------------------------------------------------------------- #
# (2) 갈래가 없는 공고는 수정 이전과 같은 판정을 유지한다
# --------------------------------------------------------------------------- #


def test_regime_free_band_bid_keeps_existing_judgement(
    monkeypatch,
    client,
    seeded_regime_bids,
    isolated_db,
    as_user,
    stub_prediction,
):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    plain_bid = seeded_regime_bids["plain_band"]
    normal_bid = seeded_regime_bids["normal"]

    assert qualification_analyzable_ids([plain_bid]) == set()
    regimes = lookup_attachment_regimes(
        isolated_db, (attachment_regime_key(plain_bid), attachment_regime_key(normal_bid))
    )
    assert regimes == {}
    assert qualification_analyzable_ids([plain_bid], regimes) == set()
    assert qualification_analyzable_ids([normal_bid], regimes) == {normal_bid.id}

    documents = _document_by_id(_build_announcement_batch(isolated_db, [plain_bid]))
    assert documents[f"announcement_Servc_{PLAIN_BAND_NO}"]["qualification_analyzable"] is False

    filtered = bid_queries.list_announcements(isolated_db, qualification_only=True)
    filtered_ids = {row.id for row in filtered.object_list}
    assert plain_bid.id not in filtered_ids
    assert normal_bid.id in filtered_ids

    assert _analyze_resolves_rule(client, plain_bid.id) is False


# --------------------------------------------------------------------------- #
# (3) 목록 한 페이지의 갈래 조회 질의는 한 번
# --------------------------------------------------------------------------- #


def test_list_page_looks_up_regimes_once(monkeypatch, auth_client, isolated_db):  # noqa: F811
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    now = utcnow()
    for index in range(5):
        bid_ntce_no = f"R26BK9300000{index}"
        bid = _add_bid(
            isolated_db,
            bid_ntce_no,
            BAND_RAW,
            presmpt_prce=150_000_000,
            bid_ntce_dt=now - timedelta(minutes=index),
            collected_at=now,
        )
        isolated_db.add(
            BidAnnouncementRegime(
                bid_ntce_no=bid_ntce_no,
                bid_ntce_ord=bid.bid_ntce_ord,
                category=bid.category,
                regime=MOIS_ACADEMIC,
                status=REGIME_STATUS_CLASSIFIED,
                classifier_version="1.2.0",
            )
        )
    isolated_db.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    bind = isolated_db.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        response = auth_client.get("/bids/")
    finally:
        event.remove(bind, "before_cursor_execute", record)

    assert response.status_code == 200
    regime_queries = [
        statement for statement in statements if "bid_announcement_regime" in statement.lower()
    ]
    assert len(regime_queries) == 1


# --------------------------------------------------------------------------- #
# (4) 갈래 분류 뒤 변경 공고의 색인 upsert 호출
# --------------------------------------------------------------------------- #


def test_classification_refreshes_changed_announcement_index(monkeypatch, isolated_db):
    bid = _add_bid(
        isolated_db,
        CLASSIFY_BID_NO,
        {
            **BAND_RAW,
            "ntceSpecDocUrl1": "https://www.g2b.go.kr/download/regime.hwp",
            "ntceSpecFileNm1": "적격심사.hwp",
        },
        presmpt_prce=150_000_000,
        bid_ntce_dt=CLASSIFY_BID_DT,
        collected_at=CLASSIFY_BID_DT,
    )

    class _FakeMeiliClient:
        def __init__(self) -> None:
            self.documents: list[dict[str, Any]] = []

        def upsert(self, documents: list[dict[str, Any]]) -> None:
            self.documents.extend(documents)

    fake = _FakeMeiliClient()
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient", lambda: fake)
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)

    def fake_download(url: str) -> bytes:
        return b"fake-hwp-bytes:" + url.encode()

    def fake_extract(name: str, data: bytes) -> classify_script.DocumentTexts:
        assert data.startswith(b"fake-hwp-bytes:")
        return classify_script.DocumentTexts(texts=(CLASSIFIER_TEXT,))

    summary = classify_script.run_batch(
        isolated_db,
        start=CLASSIFY_PERIOD[0],
        end=CLASSIFY_PERIOD[1],
        dry_run=False,
        sleep_seconds=0,
        max_calls=10,
        download_fn=fake_download,
        extract_fn=fake_extract,
    )

    assert summary["classified"] == 1
    assert summary["index_refreshed"] == 1
    documents = _document_by_id(fake.documents)
    document = documents[f"announcement_Servc_{CLASSIFY_BID_NO}"]
    assert document["source_id"] == bid.id
    assert document["qualification_analyzable"] is True
