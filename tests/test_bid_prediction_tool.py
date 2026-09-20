"""tests/test_bid_prediction_tool.py

복수 공고 투찰가 예측에서 DB 파생 특징(기관 이력·재발주 이력)의 중복 조회를
한 번의 도구 호출 안에서 재사용하는지 검증합니다.

세 가지를 증명합니다.
  1. 재사용을 켜고 끈 두 경우의 특징 딕셔너리와 예측 결과가 같다.
  2. 같은 기관·같은 조건의 공고를 여러 건 예측해도 조회는 기관 수·조건 수만큼만 난다.
  3. 재사용 캐시가 도구 호출을 넘어 유지되지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult, InstitutionWinRateStat
from src.app.services.tools import bid_prediction_tool as tool
from src.ml.model_registry import PredictionOutcome

OPENED_AT = datetime(2026, 9, 16, 10, 0)


def _outcome() -> PredictionOutcome:
    return PredictionOutcome(
        predicted_rate=0.97,
        requested_model="v25",
        actual_model="v25",
        fallback_used=False,
        fallback_reason=None,
    )


def _seed_institution_stats(
    db,
    name: str,
    category: str = "Servc",
    *,
    avg_rate: str = "91.5",
    ewm_rate: str = "90.25",
    sample_count: int = 12,
) -> None:
    db.add(
        InstitutionWinRateStat(
            institution_name=name,
            category=category,
            sample_count=sample_count,
            avg_rate=Decimal(avg_rate),
            ewm_rate=Decimal(ewm_rate),
            rebuilt_at=utcnow(),
        )
    )
    db.commit()


def _seed_repeat_result(
    db,
    *,
    no: str,
    institution: str,
    title: str,
    category: str = "Servc",
    opened_at: datetime = datetime(2025, 9, 1, 10, 0),
    rate: str = "88.0",
) -> None:
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord="00",
            bid_ntce_nm=title,
            dminstt_nm=institution,
            category=category,
            sucsf_bid_rate=Decimal(rate),
            rl_openg_dt=opened_at,
            collected_at=opened_at,
        )
    )
    db.commit()


def _bid(index: int, *, institution: str, title: str, category: str = "Servc") -> BidAnnouncement:
    return BidAnnouncement(
        id=1000 + index,
        bid_ntce_no=f"20260903{index:03d}",
        bid_ntce_ord="000",
        bid_ntce_nm=title,
        ntce_instt_nm=institution,
        dminstt_nm=institution,
        category=category,
        base_amount=100_000_000 + index,
        presmpt_prce=90_000_000,
        bid_ntce_dt=datetime(2026, 9, 1, 10, 0),
        bid_clse_dt=datetime(2026, 9, 15, 18, 0),
        openg_dt=OPENED_AT,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "sucsfbidLwltRate": "87.745"},
        collected_at=OPENED_AT + timedelta(minutes=index),
    )


def _assert_feature_dicts_equal(left: dict[str, Any], right: dict[str, Any]) -> None:
    assert set(left) == set(right)
    for key, value in left.items():
        if isinstance(value, float):
            assert right[key] == pytest.approx(value), f"특징 '{key}' 불일치"
        else:
            assert right[key] == value, f"특징 '{key}' 불일치"


def _reuse_cache(db) -> tool._PredictionFeatureCache:
    return tool._PredictionFeatureCache(db)


# --------------------------------------------------------------------------- #
# 1. 특징 값·예측 결과 동일성
# --------------------------------------------------------------------------- #


def test_feature_values_identical_with_and_without_reuse(isolated_db):
    """재사용을 켠 특징 딕셔너리가 끈 경우와 완전히 같아야 합니다."""
    _seed_institution_stats(isolated_db, "한국도로공사")
    _seed_repeat_result(
        isolated_db,
        no="R-인프라-1",
        institution="한국도로공사",
        title="2025년 클라우드 전환 용역",
    )
    bids = [
        _bid(1, institution="한국도로공사", title="2026년 클라우드 전환 용역"),
        _bid(2, institution="한국도로공사", title="2026년 클라우드 전환 용역"),
    ]

    cache = _reuse_cache(isolated_db)
    for bid in bids:
        without_reuse = tool._build_prediction_features(bid, isolated_db)
        with_reuse = tool._build_prediction_features(bid, isolated_db, cache=cache)
        _assert_feature_dicts_equal(without_reuse, with_reuse)

    # 기본값이 아니라 캐시가 되돌려 준 실제 조회 값인지 확인합니다.
    assert with_reuse["inst_sample_cnt"] == 12.0
    assert with_reuse["inst_hist_rate"] == pytest.approx(0.915)
    assert with_reuse["is_repeat"] == 1.0


def test_prediction_result_identical_with_and_without_reuse(isolated_db):
    """재사용을 켠 예측 결과가 끈 경우와 같아야 합니다."""
    _seed_institution_stats(isolated_db, "한국도로공사")
    _seed_repeat_result(
        isolated_db,
        no="R-인프라-2",
        institution="한국도로공사",
        title="2025년 클라우드 전환 용역",
    )
    bids = [
        _bid(1, institution="한국도로공사", title="2026년 클라우드 전환 용역"),
        _bid(2, institution="한국도로공사", title="2026년 클라우드 전환 용역"),
    ]

    cache = _reuse_cache(isolated_db)
    with patch.object(
        tool, "predict_optimal_price_with_provenance", side_effect=lambda *a: _outcome()
    ):
        for bid in bids:
            without_reuse = tool._predict_bid(bid, "v25", db=isolated_db)
            with_reuse = tool._predict_bid(bid, "v25", db=isolated_db, cache=cache)
            assert with_reuse == without_reuse


# --------------------------------------------------------------------------- #
# 2. 질의 수 감소
# --------------------------------------------------------------------------- #


def test_institution_history_query_runs_once_per_institution(isolated_db):
    """같은 기관 공고를 여러 건 예측해도 기관 이력 조회는 기관 수만큼만 납니다."""
    _seed_institution_stats(isolated_db, "기관A")
    _seed_institution_stats(isolated_db, "기관B")
    bids = [
        _bid(1, institution="기관A", title="기관A 사업 1"),
        _bid(2, institution="기관A", title="기관A 사업 2"),
        _bid(3, institution="기관A", title="기관A 사업 3"),
        _bid(4, institution="기관B", title="기관B 사업 1"),
        _bid(5, institution="기관B", title="기관B 사업 2"),
        _bid(6, institution="기관B", title="기관B 사업 3"),
    ]

    queried_keys: list[tuple[Any, ...]] = []
    real_lookup = tool.lookup_institution_stats

    def counting_lookup(features, session=None):
        queried_keys.append(tool._institution_cache_key(features))
        return real_lookup(features, session)

    with (
        patch.object(tool, "_latest_predictable_bids", return_value=bids),
        patch.object(tool, "lookup_institution_stats", side_effect=counting_lookup),
        patch("src.ml.features.lookup_institution_stats") as features_lookup,
        patch.object(
            tool, "predict_optimal_price_with_provenance", side_effect=lambda *a: _outcome()
        ),
    ):
        result = tool.execute(db=isolated_db, query="용역 6개", category="Servc", limit=6)

    assert result["status"] == "success"
    assert result["result_count"] == 6
    # 공고 6건이지만 기관 이력 조회는 기관 수(2)만큼만 발생합니다.
    assert len(queried_keys) == 2
    assert len(set(queried_keys)) == 2
    # features.py 내부 조회는 발생하지 않아야 합니다(주입으로 대체됨).
    features_lookup.assert_not_called()


def test_repeat_history_query_runs_once_per_scope(isolated_db):
    """같은 기관·같은 공고명 조건이 반복되면 재발주 이력 조회가 재사용됩니다."""
    _seed_institution_stats(isolated_db, "기관A")
    _seed_repeat_result(
        isolated_db,
        no="R-재발주-1",
        institution="기관A",
        title="2025학년도 통학버스 임차 용역",
    )
    bids = [
        _bid(1, institution="기관A", title="2026학년도 통학버스 임차 용역"),
        _bid(2, institution="기관A", title="2026학년도 통학버스 임차 용역"),
        _bid(3, institution="기관A", title="정수처리 시설 유지보수 용역"),
    ]

    queried_keys: list[tuple[Any, ...]] = []
    real_lookup = tool.lookup_repeat_history

    def counting_lookup(features, session, **kwargs):
        queried_keys.append(tool._repeat_cache_key(features))
        return real_lookup(features, session, **kwargs)

    with (
        patch.object(tool, "_latest_predictable_bids", return_value=bids),
        patch.object(tool, "lookup_repeat_history", side_effect=counting_lookup),
        patch("src.ml.features.lookup_repeat_history") as features_lookup,
        patch.object(
            tool, "predict_optimal_price_with_provenance", side_effect=lambda *a: _outcome()
        ),
    ):
        result = tool.execute(db=isolated_db, query="용역 3개", category="Servc", limit=3)

    assert result["status"] == "success"
    assert result["result_count"] == 3
    # 같은 조건(공고 1,2)은 한 번, 다른 조건(공고 3)은 한 번.
    assert len(queried_keys) == 2
    assert len(set(queried_keys)) == 2
    features_lookup.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. 캐시 수명
# --------------------------------------------------------------------------- #


def test_reuse_cache_does_not_outlive_tool_call(isolated_db):
    """도구 호출마다 새 캐시를 써서 낡은 이력이 다음 호출로 새지 않아야 합니다."""
    _seed_institution_stats(isolated_db, "기관A")
    bids = [
        _bid(1, institution="기관A", title="기관A 사업 1"),
        _bid(2, institution="기관A", title="기관A 사업 2"),
    ]

    call_count = 0
    real_lookup = tool.lookup_institution_stats

    def counting_lookup(features, session=None):
        nonlocal call_count
        call_count += 1
        return real_lookup(features, session)

    with (
        patch.object(tool, "_latest_predictable_bids", return_value=bids),
        patch.object(tool, "lookup_institution_stats", side_effect=counting_lookup),
        patch.object(
            tool, "predict_optimal_price_with_provenance", side_effect=lambda *a: _outcome()
        ),
    ):
        tool.execute(db=isolated_db, query="용역 2개", category="Servc", limit=2)
        tool.execute(db=isolated_db, query="용역 2개", category="Servc", limit=2)

    # 호출마다 새 캐시를 쓰므로 기관 이력 조회는 호출당 1회씩, 총 2회입니다.
    assert call_count == 2
