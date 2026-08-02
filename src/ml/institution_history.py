"""
src/ml/institution_history.py

기관별 낙찰률 이력을 DB 에서 계산하는 모듈.

features.py 의 단일 특징 공급원 원칙을 유지하면서,
inst_hist_rate 를 DEFAULT_INST_RATE(0.925) 상수 대신 실제 기관 이력으로
채울 수 있게 뼈대를 제공합니다.

담당자가 아래 TODO 마커(# TODO) 5곳을 20~40줄 단위로 직접 구현합니다.
세부 구현 가이드는 docs/handoff/inst_hist_rate_impl_todo.md 를 참조하세요.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# SQLAlchemy 는 이 모듈이 실제로 DB 를 태울 때만 지연 임포트합니다.
# 테스트 환경이나 모델 로드 시 불필요한 의존성을 피하기 위함입니다.


def _default_institution_rate(category: str = "") -> float:
    """이력이 없거나 계산 불가능할 때 돌아갈 기본값.

    2024-06-01 ~ 2025-06-01 기간의 전체 평균 낙찰률을 사용합니다.
    Thng: 0.9132, Servc: 0.9011, Cnstwk: 0.8859
    """
    if category == "Servc":
        return 0.9011
    if category == "Thng":
        return 0.9132
    if category == "Cnstwk":
        return 0.8859
    return 0.9001


def _normalize_institution_name(name: str) -> str:
    """기관명에서 앞뒤 공백과 연속 공백을 정리합니다."""
    return " ".join(str(name).strip().split())


_PLACEHOLDER_INSTITUTIONS = {
    "각 수요기관",
    "수요기관",
    "조달청",
    "",
}


def _resolve_institution_name(features_dict: dict[str, Any]) -> str:
    """features_dict 에서 기관명을 우선순위대로 추출합니다.

    수요기관(dminstt_nm)이 예산 집행 주체이므로 낙찰률 예측에 더 직접적입니다.
    공고기관(ntce_instt_nm)은 조달청 등 예산 주인과 다를 수 있습니다.
    """
    for key in ("dminstt_nm", "ntce_instt_nm", "ntceInsttNm"):
        value = features_dict.get(key)
        if value:
            normalized = _normalize_institution_name(value)
            if normalized in _PLACEHOLDER_INSTITUTIONS:
                continue
            return normalized
    return ""


def _resolve_category(features_dict: dict[str, Any]) -> str:
    """계산 범위를 제한할 업무구분을 추출합니다."""
    category = features_dict.get("category") or features_dict.get("category_code") or ""
    return str(category).strip()


def _resolve_reference_date(features_dict: dict[str, Any]) -> datetime:
    """현재 예측 대상 입찰의 기준 시점을 결정합니다.

    기준 시점 이전의 낙찰 결과만 이력으로 사용해야 미래 정보 누출을 막습니다.
    시계열 분할과 일관되게 개찰일을 우선 사용합니다.
    """
    for key in ("openg_dt", "bid_clse_dt", "bid_ntce_dt"):
        value = features_dict.get(key)
        if value:
            try:
                import pandas as pd

                ts = pd.Timestamp(value)
                if pd.notna(ts):
                    return ts.to_pydatetime()
            except Exception:
                continue
    return datetime.utcnow()


def calculate_institution_win_rate(
    session: Any,
    institution_name: str,
    reference_date: datetime,
    category: str,
    lookback_days: int = 365,
    min_samples: int = 5,
) -> float:
    """주어진 기관/기준일/카테고리에 대한 평균 낙찰률을 반환합니다.

    Args:
        session: SQLAlchemy Session.
        institution_name: 기관명.
        reference_date: 이 시점 이전의 낙찰 결과만 이력으로 사용.
        category: 업무구분(예: Servc). 빈 문자열이면 카테고리 무시.
        lookback_days: 이력 조회 윈도우(일). 기본 1년.
        min_samples: 이력 최소 건수. 이 미만이면 기본값을 반환.

    Returns:
        평균 낙찰률(0.0~1.0 사이 비율) 또는 기본값.
    """
    if not institution_name:
        return _default_institution_rate(category)

    from sqlalchemy import func

    from src.app.models.bids import BidResult

    start_date = reference_date - timedelta(days=lookback_days)

    # 이상치 제거: 0% 또는 100% 이상(데이터 오류)인 낙찰률은 제외합니다.
    base_filters = [
        BidResult.dminstt_nm == institution_name,
        BidResult.rl_openg_dt < reference_date,
        BidResult.rl_openg_dt >= start_date,
        BidResult.sucsf_bid_rate.isnot(None),
        BidResult.sucsf_bid_rate > 0,
        BidResult.sucsf_bid_rate < 100,
    ]

    count_query = session.query(func.count(BidResult.id)).filter(*base_filters)
    if category:
        count_query = count_query.filter(BidResult.category == category)

    sample_count = count_query.scalar()
    if sample_count is None or sample_count < min_samples:
        return _default_institution_rate(category)

    avg_query = session.query(func.avg(BidResult.sucsf_bid_rate)).filter(*base_filters)
    if category:
        avg_query = avg_query.filter(BidResult.category == category)

    result = avg_query.scalar()
    if result is None:
        return _default_institution_rate(category)

    avg_rate = float(result)
    # BidResult.sucsf_bid_rate 는 Numeric(10,4)로 퍼센트(87.5) 형태로 저장돼 있습니다.
    if avg_rate > 1.0:
        avg_rate = avg_rate / 100.0

    return avg_rate


def lookup_institution_history(features_dict: dict[str, Any], session: Any = None) -> float:
    """features_dict 에서 기관명과 기준일을 추출해 이력 낙찰률을 반환합니다.

    session 이 없으면(예: 테스트 또는 모델 로드 시) 기본값을 반환합니다.
    """
    institution_name = _resolve_institution_name(features_dict)
    if not institution_name:
        return _default_institution_rate(_resolve_category(features_dict))

    reference_date = _resolve_reference_date(features_dict)
    category = _resolve_category(features_dict)

    if session is None:
        return _default_institution_rate(category)

    return calculate_institution_win_rate(
        session=session,
        institution_name=institution_name,
        reference_date=reference_date,
        category=category,
    )
