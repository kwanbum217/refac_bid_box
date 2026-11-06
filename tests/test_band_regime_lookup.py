"""저장된 첨부 판별 갈래(`bid_announcement_regime`)의 조회와 규칙 해석 연결 시험.

정본: `.orca/capsules/task_band_regime_wiring_20261106/capsule.yaml`

(a) 조회 함수는 `CLASSIFIED` 인 같은 차수·업무구분 행만 돌려주고, 행이 없거나 다른
상태·다른 차수면 `None` 입니다. (b) 평가 API 는 저장된 `MOIS_ACADEMIC` 갈래를 해석기로
넘겨 '2억미만 1억이상' 띠 공고를 행안부 학술연구 규칙으로 계산하고, 판별 행이 없는 공고는
기존 차단을 유지합니다. (c) 조회가 예외로 실패해도 API 는 판별 이전과 같은 결과를 냅니다.
실물 서비스는 부르지 않고 conftest 의 SQLite 인메모리 DB 를 씁니다.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.main import app
from src.app.models.announcement_regime import (
    REGIME_STATUS_CLASSIFIED,
    REGIME_STATUS_FAILED,
    REGIME_STATUS_NO_ATTACHMENT,
    BidAnnouncementRegime,
)
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services import band_regime_lookup
from src.app.services.band_regime_lookup import (
    lookup_attachment_regime,
    lookup_attachment_regimes,
)

METHOD_BAND = "적격심사제-추정가격 2억미만 1억이상"
BID_DATE = "2026-06-01"
CATEGORY = "Servc"
INSTITUTION_CODE = "T1001"
MOIS_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
RULES_URL = "/api/v1/evaluations/rules"
ANALYZE_URL = "/api/v1/evaluations/analyze"
CLASSIFIER_VERSION = "1.1.0"


def _regime_row(
    bid_ntce_no: str,
    *,
    regime: str,
    status: str,
    bid_ntce_ord: str = "000",
    category: str = CATEGORY,
) -> BidAnnouncementRegime:
    return BidAnnouncementRegime(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        category=category,
        regime=regime,
        status=status,
        classifier_version=CLASSIFIER_VERSION,
    )


def _seed_regimes(db) -> None:
    db.add_all(
        [
            _regime_row("R26BK10000001", regime="MOIS_ACADEMIC", status=REGIME_STATUS_CLASSIFIED),
            _regime_row("R26BK10000002", regime="MOIS_ACADEMIC", status=REGIME_STATUS_FAILED),
            _regime_row("R26BK10000003", regime="NO_ATTACH", status=REGIME_STATUS_NO_ATTACHMENT),
            _regime_row(
                "R26BK10000004",
                regime="MOIS_ACADEMIC",
                status=REGIME_STATUS_CLASSIFIED,
                bid_ntce_ord="001",
            ),
            _regime_row(
                "R26BK10000005",
                regime="PPS",
                status=REGIME_STATUS_CLASSIFIED,
                category="Cnstwk",
            ),
        ]
    )
    db.commit()


# --------------------------------------------------------------------------- #
# (a) CLASSIFIED 이고 키가 정확히 같은 행만 돌려준다
# --------------------------------------------------------------------------- #


def test_lookup_returns_only_classified_exact_key(isolated_db) -> None:
    _seed_regimes(isolated_db)

    assert lookup_attachment_regime(isolated_db, "R26BK10000001", "000", CATEGORY) == (
        "MOIS_ACADEMIC"
    )
    assert lookup_attachment_regime(isolated_db, "R26BK10000002", "000", CATEGORY) is None
    assert lookup_attachment_regime(isolated_db, "R26BK10000003", "000", CATEGORY) is None
    # 다른 차수의 CLASSIFIED 행으로 대체하지 않는다.
    assert lookup_attachment_regime(isolated_db, "R26BK10000004", "000", CATEGORY) is None
    assert lookup_attachment_regime(isolated_db, "R26BK10000004", "001", CATEGORY) == (
        "MOIS_ACADEMIC"
    )
    # 업무구분이 다르면 다른 행이다.
    assert lookup_attachment_regime(isolated_db, "R26BK10000005", "000", CATEGORY) is None
    assert lookup_attachment_regime(isolated_db, "R26BK10000005", "000", "Cnstwk") == "PPS"
    # 행 자체가 없으면 None.
    assert lookup_attachment_regime(isolated_db, "R26BK99999999", "000", CATEGORY) is None


def test_bulk_lookup_matches_exact_keys_only(isolated_db) -> None:
    _seed_regimes(isolated_db)

    found = lookup_attachment_regimes(
        isolated_db,
        [
            ("R26BK10000001", "000", CATEGORY),
            ("R26BK10000002", "000", CATEGORY),
            ("R26BK10000004", "000", CATEGORY),
            ("R26BK10000005", "000", "Cnstwk"),
            ("R26BK99999999", "000", CATEGORY),
        ],
    )

    assert found == {
        ("R26BK10000001", "000", CATEGORY): "MOIS_ACADEMIC",
        ("R26BK10000005", "000", "Cnstwk"): "PPS",
    }
    assert lookup_attachment_regimes(isolated_db, []) == {}


# --------------------------------------------------------------------------- #
# (b) 평가 API 가 저장된 갈래를 해석기에 넘긴다
# --------------------------------------------------------------------------- #


def _seed_institution(db) -> None:
    db.add(
        G2BDemandInstitution(
            dminstt_cd=INSTITUTION_CODE,
            dminstt_nm="충청남도 테스트 기관",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="44",
            rgn_nm="충청남도",
            toplvl_instt_nm="충청남도",
            raw_json={},
        )
    )


def _create_band_bid(db, bid_ntce_no: str) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="첨부 판별 연결 시험 공고",
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        dminstt_nm="충청남도 테스트 기관",
        category=CATEGORY,
        base_amount=150_000_000,
        presmpt_prce=150_000_000,
        bid_ntce_dt=datetime(2026, 6, 1, 10, 0, 0),
        raw_data={
            "dminsttCd": INSTITUTION_CODE,
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": METHOD_BAND,
            "bidNtceDt": BID_DATE,
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _matched_rule_id(client, bid_id: int) -> str | None:
    response = client.get(RULES_URL, params={"bid_id": bid_id})
    assert response.status_code == 200, response.text
    matched = response.json()["matched_rule"]
    return None if matched is None else matched["rule_id"]


def test_rules_api_uses_classified_mois_academic(client, isolated_db) -> None:
    _seed_institution(isolated_db)
    baseline_bid = _create_band_bid(isolated_db, "R26BK20000001")
    classified_bid = _create_band_bid(isolated_db, "R26BK20000002")
    isolated_db.add(
        _regime_row("R26BK20000002", regime="MOIS_ACADEMIC", status=REGIME_STATUS_CLASSIFIED)
    )
    isolated_db.commit()

    baseline_id = baseline_bid.id
    classified_id = classified_bid.id
    # 판별 행이 없으면 판별 이전과 같이 차단되어 매칭 규칙이 없다.
    assert _matched_rule_id(client, baseline_id) is None
    # MOIS_ACADEMIC 으로 판별된 공고만 행안부 학술연구 1억~2억 규칙으로 계산된다.
    assert _matched_rule_id(client, classified_id) == MOIS_RULE_ID


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=7)
    yield
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture
def stub_prediction(monkeypatch):
    """모델 가중치를 로드하지 않도록 예측 API 를 대역으로 덮는다."""

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


def _analyze_payload(bid_id: int) -> dict:
    return {
        "bid_id": bid_id,
        "candidate_bid_amount": 130_000_000,
        "qualification_input": {"manual_non_price_score": 60.0},
    }


def test_analyze_api_uses_classified_mois_academic(
    client, isolated_db, as_user, stub_prediction
) -> None:
    _seed_institution(isolated_db)
    baseline_bid = _create_band_bid(isolated_db, "R26BK30000001")
    classified_bid = _create_band_bid(isolated_db, "R26BK30000002")
    isolated_db.add(
        _regime_row("R26BK30000002", regime="MOIS_ACADEMIC", status=REGIME_STATUS_CLASSIFIED)
    )
    isolated_db.commit()

    baseline_id = baseline_bid.id
    classified_id = classified_bid.id
    assert client.post(ANALYZE_URL, json=_analyze_payload(baseline_id)).json()["rule_id"] is None

    resolved = client.post(ANALYZE_URL, json=_analyze_payload(classified_id))
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["rule_id"] == MOIS_RULE_ID


# --------------------------------------------------------------------------- #
# (c) 조회 예외가 나도 API 는 판별 이전 결과로 응답한다
# --------------------------------------------------------------------------- #


def test_lookup_failure_keeps_previous_result(client, isolated_db, monkeypatch) -> None:
    _seed_institution(isolated_db)
    bid = _create_band_bid(isolated_db, "R26BK40000001")
    isolated_db.add(
        _regime_row("R26BK40000001", regime="MOIS_ACADEMIC", status=REGIME_STATUS_CLASSIFIED)
    )
    isolated_db.commit()

    bid_id = bid.id
    assert _matched_rule_id(client, bid_id) == MOIS_RULE_ID

    def _boom(*args, **kwargs):
        raise RuntimeError("regime lookup down")

    monkeypatch.setattr(band_regime_lookup, "lookup_attachment_regime", _boom)

    response = client.get(RULES_URL, params={"bid_id": bid_id})
    assert response.status_code == 200, response.text
    assert response.json()["matched_rule"] is None
