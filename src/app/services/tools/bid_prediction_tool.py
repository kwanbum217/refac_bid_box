"""
src/app/services/tools/bid_prediction_tool.py

공고 투찰가 예측 도구 (원본 apps/chatbot/tools/bid_prediction_tool.py 1:1 이식).

A4 교정:
- 비예가 판정을 model_registry.classify_price_decision_method 단일 함수로 통합.
- 도달 불가 재시도 패턴을 제거하고 predict_optimal_price_with_provenance 사용.
- actual_model, fallback_used, fallback_reason 이 실제 예측 모델을 가리키게 한다.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement
from src.ml.dataset import announcement_feature_payload
from src.ml.features import build_feature_dict
from src.ml.institution_history import lookup_institution_stats
from src.ml.model_registry import (
    CATEGORY_DEFAULT_MODELS,
    ModelRegistry,
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_optimal_price_with_provenance,
)
from src.ml.repeat_history import (
    DEFAULT_REPEAT_RATE,
    NO_HISTORY_DAYS,
    lookup_repeat_history,
)

# 정본은 model_registry 입니다.
DEFAULT_MODEL_BY_CATEGORY = CATEGORY_DEFAULT_MODELS

MODEL_ALIASES = {
    "quantum_leap_v25_pro": "quantum_leap_v25_pro",
    "ssh_hist_premium": "ssh_hist_premium",
    "ssh": "ssh_hist_premium",
    "servc_institution_v1": "servc_institution_v1",
    "servc": "servc_institution_v1",
    "v13_hybrid": "v13_hybrid",
    "v13": "v13_hybrid",
    "v25": "v25",
}
KOREAN_LIMIT_WORDS = {
    "한": 1,
    "하나": 1,
    "두": 2,
    "둘": 2,
    "세": 3,
    "셋": 3,
    "네": 4,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
MAX_PREDICTION_LIMIT = 10

# raw_data 예산이 "0" 인 건이 섞여 있어 SQL 필터만으로는 요청 건수를 못 채웁니다.
# 여유분을 더 읽고 파이썬에서 최종 판정한 뒤 자릅니다.
CANDIDATE_OVERSAMPLE = 3

# DB 파생 특징의 정의는 features.py 하나입니다(AGENTS.md 6항). 이 도구는 공고 K건을
# 한 번에 예측하므로 같은 기관·같은 조건의 조회가 K번 반복됩니다. 정의를 건드리지
# 않고 중복 조회만 걷어내려고, 한 번의 도구 호출 안에서만 사는 재사용 캐시를 둡니다.
INSTITUTION_FEATURE_KEYS = ("inst_hist_rate", "inst_sample_cnt", "inst_ewm_rate")
REPEAT_FEATURE_KEYS = (
    "is_repeat",
    "repeat_cnt",
    "repeat_hist_rate",
    "repeat_prev_rate",
    "repeat_hist_std",
    "repeat_days_since",
)
# features.py 의 _repeat_features 가 "이력 없음" 일 때 돌려주는 값과 같아야 합니다.
DEFAULT_REPEAT_FEATURES = {
    "is_repeat": 0.0,
    "repeat_cnt": 0.0,
    "repeat_hist_rate": DEFAULT_REPEAT_RATE,
    "repeat_prev_rate": DEFAULT_REPEAT_RATE,
    "repeat_hist_std": 0.0,
    "repeat_days_since": NO_HISTORY_DAYS,
}


def _institution_cache_key(features: dict[str, Any]) -> tuple[Any, ...]:
    """기관 이력 조회 결과를 좌우하는 입력을 원값 그대로 모읍니다.

    lookup_institution_stats 는 기관명 후보 4종 중 첫 값, 업무구분 후보 2종 중 첫
    값, 기준일 후보 3종 중 첫 값으로 조회합니다. 우선순위·정규화·플레이스홀더
    제외 규칙을 여기서 다시 구현하면 정의가 갈리므로, 후보를 전부 넣어 해석
    결과가 같으면 키도 같게 만듭니다. 후보를 넓게 잡는 쪽은 재사용이 줄 뿐
    다른 입력이 같은 값을 받는 일은 없습니다.
    """
    return (
        features.get("dminstt_nm"),
        features.get("order_institution"),
        features.get("ntce_instt_nm"),
        features.get("ntceInsttNm"),
        features.get("category"),
        features.get("category_code"),
        features.get("openg_dt"),
        features.get("bid_clse_dt"),
        features.get("bid_ntce_dt"),
    )


def _repeat_cache_key(features: dict[str, Any]) -> tuple[Any, ...]:
    """재발주 이력 조회 결과를 좌우하는 입력을 원값 그대로 모읍니다.

    lookup_repeat_history 는 기관명 후보 2종, 공고명 후보 2종, 업무구분 후보 2종,
    기준일 후보 2종을 읽고 공고명을 normalize_title 로 정규화해 매칭합니다.
    정규화된 제목 대신 원제목을 키에 넣어, 같은 사업이라도 원문이 다르면
    재사용하지 않습니다(정의를 다시 구현하지 않기 위한 보수적 선택).
    """
    return (
        features.get("dminstt_nm"),
        features.get("ntceInsttNm"),
        features.get("bid_ntce_nm"),
        features.get("bidNtceNm"),
        features.get("category"),
        features.get("category_code"),
        features.get("openg_dt"),
        features.get("bid_ntce_dt"),
    )


class _PredictionFeatureCache:
    """한 번의 도구 호출(execute) 안에서만 사는 DB 파생 특징 재사용 캐시.

    낙찰 이력은 수집으로 계속 바뀌므로 호출 간에 남기지 않습니다. 모듈 전역이나
    lru_cache 로 프로세스 수명 동안 유지하면 낡은 값이 그대로 서빙됩니다.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._institution: dict[tuple[Any, ...], dict[str, float]] = {}
        self._repeat: dict[tuple[Any, ...], dict[str, float]] = {}

    def fill(self, features: dict[str, Any]) -> None:
        """features 에 DB 파생 특징을 제자리에서 채웁니다.

        build_feature_dict 는 이 값들이 이미 있으면 같은 조회를 하지 않습니다
        (features.py 의 None 검사). 조회 결과를 그대로 되돌려 넣으므로 특징 값은
        재사용 여부와 무관하게 같습니다.
        """
        self._fill_institution(features)
        self._fill_repeat(features)

    def _fill_institution(self, features: dict[str, Any]) -> None:
        # features.py 와 같은 조건(셋 중 하나라도 없을 때)에만 조회합니다.
        if all(features.get(key) is not None for key in INSTITUTION_FEATURE_KEYS):
            return
        key = _institution_cache_key(features)
        stats = self._institution.get(key)
        if stats is None:
            stats = lookup_institution_stats(features, self._db)
            self._institution[key] = stats
        for name in INSTITUTION_FEATURE_KEYS:
            if features.get(name) is None:
                features[name] = stats[name]

    def _fill_repeat(self, features: dict[str, Any]) -> None:
        if features.get("is_repeat") is not None:
            return
        key = _repeat_cache_key(features)
        found = self._repeat.get(key)
        if found is None:
            lookup = lookup_repeat_history(features, self._db)
            found = dict(lookup) if lookup is not None else dict(DEFAULT_REPEAT_FEATURES)
            self._repeat[key] = found
        for name in REPEAT_FEATURE_KEYS:
            features[name] = found[name]


def _default_model_for_bid(bid: BidAnnouncement) -> str:
    return DEFAULT_MODEL_BY_CATEGORY.get(bid.category, "v25")


def _resolve_model_id(query: str, model_id: str = "") -> str:
    normalized = f"{model_id} {query}".strip().lower()
    for alias, resolved in MODEL_ALIASES.items():
        if alias in normalized:
            return resolved
    return ""


def coerce_limit(value: Any, query: str = "") -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        match = re.search(r"(?<![a-zA-Z])(\d{1,2})\s*(?:개|건)\s*(?:만)?", query)
        if match:
            limit = int(match.group(1))
    if limit <= 0:
        normalized = query.replace(" ", "")
        for word, number in KOREAN_LIMIT_WORDS.items():
            if f"{word}개" in normalized or f"{word}건" in normalized:
                limit = number
                break
    if limit <= 0:
        limit = 1
    return max(1, min(limit, MAX_PREDICTION_LIMIT))


def _build_prediction_features(
    bid: BidAnnouncement,
    db: Session | None = None,
    cache: _PredictionFeatureCache | None = None,
) -> dict[str, Any]:
    """공고 상세 API 와 같은 특징을 만듭니다.

    제도 특징은 raw_data JSON 안에 있어 공고 컬럼만으로는 채울 수 없습니다.
    기관 이력과 재발주 이력은 DB 조회가 필요하므로 db 세션을 넘겨
    build_feature_dict 로 채웁니다.
    원본 키 위에 덮어씁니다. 통째로 갈아끼우면 규칙 기반 구 모델이 쓰는
    title / agency_name / scenario_mode 가 사라집니다.

    두 경로가 다른 특징을 쓰는 것은 AGENTS.md 가 금지한 train/serve skew 입니다.

    cache 가 있으면 호출 범위 안에서 같은 조건의 기관·재발주 이력 조회를 한 번만
    실행하고, 그 결과를 features 에 되돌려 넣어 build_feature_dict 가 같은 조회를
    다시 하지 않게 합니다. 특징 값 자체는 캐시 유무와 무관하게 같습니다.
    """
    reference_amount = float(bid.prediction_reference_amount or 0)
    features = {
        **announcement_feature_payload(bid),
        "title": bid.bid_ntce_nm or "",
        "agency_name": bid.dminstt_nm or bid.ntce_instt_nm or "",
        "scenario_mode": "2",
        "presmpt_prce": reference_amount,
        "presmptPrce": reference_amount,
        "real_budget": reference_amount,
        "bid_ntce_nm": bid.bid_ntce_nm or "",
        "ntce_instt_nm": bid.ntce_instt_nm or "",
        "ntceInsttNm": bid.ntce_instt_nm or "",
        "dminstt_nm": bid.dminstt_nm or "",
        "bidMethdNm": bid.bid_methd_nm or "",
        "cntrctCnclsMthdNm": bid.cntrct_mthd_nm or "",
        "category": bid.category or "",
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
    }
    if cache is not None:
        cache.fill(features)
    return {**features, **build_feature_dict(features, db)}


def _latest_predictable_bids(db: Session, category: str = "", limit: int = 1):
    # NULL 만 거르면 presmpt_prce = 0 인 공고가 통과합니다. 금액이 0 이면
    # 추천 투찰가가 0 원으로 나와 답변 전체가 무의미해집니다. 외자(Frgcpt)는
    # 절반 가까이가 이 상태라 필터를 0 초과로 둡니다.
    stmt = select(BidAnnouncement).where(
        or_(BidAnnouncement.base_amount > 0, BidAnnouncement.presmpt_prce > 0)
    )
    if category:
        stmt = stmt.where(BidAnnouncement.category == category)
    stmt = stmt.order_by(
        BidAnnouncement.collected_at.desc(),
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    ).limit(limit * CANDIDATE_OVERSAMPLE)

    # 최종 판정은 prediction_reference_amount 로 합니다. raw_data 의 예산 필드가
    # "0" 이면 SQL 필터를 통과하고도 기준 금액이 0 이 됩니다.
    rows = [
        row
        for row in db.execute(stmt).scalars().all()
        if float(row.prediction_reference_amount or 0) > 0
    ]
    return rows[:limit]


def _model_display_name(model_id: str) -> str:
    wrapper = ModelRegistry.get_model(model_id)
    return wrapper.get_display_name() if wrapper else model_id


def _predict_bid(
    bid: BidAnnouncement,
    requested_model: str,
    db: Session | None = None,
    cache: _PredictionFeatureCache | None = None,
) -> dict[str, Any]:
    """공고 한 건에 대해 투찰가를 예측한다.

    비예가 공고는 낙찰률 모델로 보내지 않고 사유를 반환한다.
    모델 출처는 predict_optimal_price_with_provenance 가 추적하므로
    이 함수에서 별도 재시도를 하지 않는다.
    """
    features = _build_prediction_features(bid, db, cache)

    # 비예가 판정: model_registry.classify_price_decision_method 단일 함수 사용.
    # 명시적 Servc 비예가만 차단하고 missing/unknown/non-Servc는 pass-through 한다.
    raw: dict[str, Any] = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_class = classify_price_decision_method(raw)
    if method_class == PriceDecisionMethod.NON_PREARNG and bid.category == "Servc":
        reference_amount = float(bid.prediction_reference_amount or 0)
        return {
            "bid": {
                "id": bid.id,
                "bid_ntce_no": bid.bid_ntce_no,
                "bid_ntce_ord": bid.bid_ntce_ord,
                "bid_ntce_nm": bid.bid_ntce_nm or "",
                "dminstt_nm": bid.dminstt_nm or "",
                "ntce_instt_nm": bid.ntce_instt_nm or "",
                "category": bid.category,
                "category_label": bid.category_label,
                "bid_ntce_dt": (bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else ""),
                "collected_at": (bid.collected_at.isoformat() if bid.collected_at else ""),
            },
            "model_id": "",
            "model_name": "",
            "requested_model": requested_model,
            "fallback_used": False,
            "fallback_reason": "",
            "reference_amount": int(reference_amount),
            "optimal_price": 0,
            "prediction_rate": 0,
            "skipped": True,
            "skip_reason": (
                "비예가 공고는 예정가격을 작성하지 않는 제도라 "
                "낙찰률 기반 투찰가를 산출할 수 없습니다."
            ),
        }

    # predict_optimal_price_with_provenance 를 사용하여 actual_model,
    # fallback_used, fallback_reason 이 실제 예측 모델을 가리키게 한다.
    # 종전의 도달 불가 재시도 패턴(요청 모델 실패 -> 카테고리 기본 모델 재시도)은
    # provenance 함수 내부의 후보 순회와 중복이므로 제거한다.
    try:
        outcome = predict_optimal_price_with_provenance(requested_model, features)
    except Exception:
        # 후보 전량 실패 시 챗봇은 오류 대신 사유를 반환한다.
        reference_amount = float(bid.prediction_reference_amount or 0)
        return {
            "bid": {
                "id": bid.id,
                "bid_ntce_no": bid.bid_ntce_no,
                "bid_ntce_ord": bid.bid_ntce_ord,
                "bid_ntce_nm": bid.bid_ntce_nm or "",
                "dminstt_nm": bid.dminstt_nm or "",
                "ntce_instt_nm": bid.ntce_instt_nm or "",
                "category": bid.category,
                "category_label": bid.category_label,
                "bid_ntce_dt": (bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else ""),
                "collected_at": (bid.collected_at.isoformat() if bid.collected_at else ""),
            },
            "model_id": "",
            "model_name": "",
            "requested_model": requested_model,
            "fallback_used": True,
            "fallback_reason": "모델 후보 전량 실패",
            "reference_amount": int(reference_amount),
            "optimal_price": 0,
            "prediction_rate": 0,
            "skipped": True,
            "skip_reason": "예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다.",
        }

    predicted_rate = outcome.predicted_rate
    actual_model = outcome.actual_model
    model_name = _model_display_name(actual_model)
    if outcome.fallback_used:
        model_name = f"{model_name} (Fallback)"

    reference_amount = float(bid.prediction_reference_amount or 0)
    if predicted_rate < 2.0:
        optimal_price = int(reference_amount * predicted_rate)
        prediction_rate_percent = round(predicted_rate * 100, 4)
    else:
        optimal_price = int(predicted_rate)
        prediction_rate_percent = round(predicted_rate, 4)

    return {
        "bid": {
            "id": bid.id,
            "bid_ntce_no": bid.bid_ntce_no,
            "bid_ntce_ord": bid.bid_ntce_ord,
            "bid_ntce_nm": bid.bid_ntce_nm or "",
            "dminstt_nm": bid.dminstt_nm or "",
            "ntce_instt_nm": bid.ntce_instt_nm or "",
            "category": bid.category,
            "category_label": bid.category_label,
            "bid_ntce_dt": bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else "",
            "collected_at": bid.collected_at.isoformat() if bid.collected_at else "",
        },
        "model_id": actual_model,
        "model_name": model_name,
        "requested_model": outcome.requested_model,
        "fallback_used": outcome.fallback_used,
        "fallback_reason": outcome.fallback_reason or "",
        "reference_amount": int(reference_amount),
        "optimal_price": optimal_price,
        "prediction_rate": prediction_rate_percent,
    }


def execute(
    *,
    db: Session,
    query: str = "",
    category: str = "",
    model_id: str = "",
    limit: int = 1,
    **_ignored: Any,
) -> dict[str, Any]:
    resolved_limit = coerce_limit(limit, query)
    bids = _latest_predictable_bids(db, category, resolved_limit)
    if not bids:
        return {
            "status": "error",
            "message": "예측 가능한 최근 공고를 찾지 못했습니다.",
            "query": query,
            "category": category,
            "requested_count": resolved_limit,
            "result_count": 0,
        }

    first_model = _resolve_model_id(query, model_id) or _default_model_for_bid(bids[0])
    # 캐시 수명은 이 호출 하나입니다. 반환 뒤에는 참조가 사라집니다.
    cache = _PredictionFeatureCache(db)
    predictions = [_predict_bid(bid, first_model, db=db, cache=cache) for bid in bids]
    first_prediction = predictions[0]

    return {
        "status": "success",
        "query": query,
        "requested_count": resolved_limit,
        "result_count": len(predictions),
        "predictions": predictions,
        **first_prediction,
    }
