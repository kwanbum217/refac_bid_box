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


def _default_institution_rate() -> float:
    """이력이 없거나 계산 불가능할 때 돌아갈 기본값."""
    # TODO-1: 담당자가 결정한 기본값을 반영하세요.
    # 현재는 features.py 의 DEFAULT_INST_RATE 와 동일하게 유지합니다.
    return 0.925


def _resolve_institution_name(features_dict: dict[str, Any]) -> str:
    """features_dict 에서 기관명을 우선순위대로 추출합니다."""
    # TODO-2: 수요기관명(dminstt_nm)과 공고기관명(ntce_instt_nm) 중
    # 어떤 기관 단위로 이력을 계산할지 결정하세요.
    #   - 수요기관: 실제 예산을 집행하는 기관(낙찰 결과에 직결)
    #   - 공고기관: 조달청 등 입찰을 공고하는 기관(예산 주인과 다를 수 있음)
    for key in ("dminstt_nm", "ntce_instt_nm", "ntceInsttNm"):
        value = features_dict.get(key)
        if value:
            return str(value).strip()
    return ""


def _resolve_category(features_dict: dict[str, Any]) -> str:
    """계산 범위를 제한할 업무구분을 추출합니다."""
    # TODO-3: 카테고리별 이력을 분리할지, 전체를 합산할지 결정하세요.
    # 용역(Servc) 모델 개선이 목표라면 Servc 이력만 쓰는 것도 후보입니다.
    category = features_dict.get("category") or features_dict.get("category_code") or ""
    return str(category).strip()


def _resolve_reference_date(features_dict: dict[str, Any]) -> datetime:
    """현재 예측 대상 입찰의 기준 시점을 결정합니다.

    기준 시점 이전의 낙찰 결과만 이력으로 사용해야 미래 정보 누출을 막습니다.
    """
    # TODO-4: 기준 시점을 개찰일, 공고일, 입찰마감일 중 하나로 결정하세요.
    # 시계열 분할과 마찬가지로 개찰일(rl_openg_dt / openg_dt)이 가장 안전합니다.
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
        return _default_institution_rate()

    # TODO-5: 실제 DB 쿼리를 작성하세요.
    # 필요한 컬럼:
    #   - dminstt_nm (수요기관명) 또는 ntce_instt_nm (공고기관명)
    #   - rl_openg_dt (개찰일시)
    #   - sucsf_bid_rate (낙찰률)
    #   - category (업무구분)
    #
    # 쿼리 조건 예시:
    #   - dminstt_nm == institution_name
    #   - rl_openg_dt < reference_date
    #   - rl_openg_dt >= reference_date - lookback_days
    #   - category == category (빈 값이면 조건 제외)
    #   - sucsf_bid_rate IS NOT NULL
    #   - sucsf_bid_rate > 0
    #
    # 낙찰률이 퍼센트(87.5)로 저장돼 있을 수 있으므로 100 으로 나눌지
    # 확인해야 합니다. BidResult.sucsf_bid_rate 는 Numeric(10,4) 입니다.
    #
    # 이상치 제거 여부(예: 0% 또는 100% 근처)도 담당자가 결정합니다.

    return _default_institution_rate()


def lookup_institution_history(features_dict: dict[str, Any], session: Any = None) -> float:
    """features_dict 에서 기관명과 기준일을 추출해 이력 낙찰률을 반환합니다.

    session 이 없으면(예: 테스트 또는 모델 로드 시) 기본값을 반환합니다.
    """
    institution_name = _resolve_institution_name(features_dict)
    if not institution_name:
        return _default_institution_rate()

    reference_date = _resolve_reference_date(features_dict)
    category = _resolve_category(features_dict)

    if session is None:
        # TODO: 캐시 레이어(Redis)를 도입할 경우 여기서 캐시 조회를 추가합니다.
        return _default_institution_rate()

    return calculate_institution_win_rate(
        session=session,
        institution_name=institution_name,
        reference_date=reference_date,
        category=category,
    )
