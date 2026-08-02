"""
src/ml/institution_history.py

기관별 낙찰률 이력을 DB 에서 계산하는 모듈.

주의: 이 모듈은 아직 학습·추론 경로에 연결되어 있지 않습니다.

`features.py` 는 `session` 을 받도록 준비돼 있지만 실제 호출부인
`trainer.py` 와 `predictor.py` 는 session 을 넘기지 않습니다. 따라서
`inst_hist_rate` 는 여전히 `_default_institution_rate()` 상수로 채워집니다.

연결하지 않은 이유는 두 가지입니다.

1. 행당 2쿼리(COUNT + AVG)라 용역 학습셋 773,045 행 기준 약 32시간이 걸립니다.
   기관/카테고리/기간을 GROUP BY 로 한 번에 집계해 매핑하는 배치 설계가 필요합니다.
2. 추론 경로에만 연결하면 학습은 상수, 추론은 DB 값이 되어 AGENTS.md 6항이
   금지하는 train/serve skew 가 발생합니다. 양쪽을 같은 방식으로 바꿔야 합니다.

배치 집계 방식(윈도우 크기, 누수 방지 기준, 최소 표본)은 실측으로 정합니다.
설계 배경은 docs/handoff/inst_hist_rate_impl_todo.md 참조.
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
            # 파싱 실패한 후보 키는 건너뛰고 다음 키를 봅니다
            except Exception:  # nosec B112
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
