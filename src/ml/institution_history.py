"""
src/ml/institution_history.py

기관별 낙찰률 이력(`inst_hist_rate`)을 계산하는 모듈.

이 특징이 낙찰률 예측의 유일한 실질 신호입니다. 2026-08-02 실측 기준
용역 773,045 행에서 이 값 하나만으로 R2 0.33 이 나오고, 모델에 넣으면
전체 R2 가 0.026 에서 0.358 로, RMSE 는 4.61 에서 3.75 로 개선됩니다.
금액 계열은 신호가 없습니다. 기초금액은 제도상 예정가격의 1.1 배라
독립 정보를 담지 않습니다.

경로가 둘이고 정의는 하나여야 합니다 (AGENTS.md 6항, train/serve skew 금지).

| 경로 | 함수 | 방식 |
| --- | --- | --- |
| 학습 | `attach_institution_history` | 프레임 전체를 pandas 로 한 번에. 773,045 행 3.2초 |
| 추론 | `calculate_institution_win_rate` | 단건 조회. 기준일 이전 이력만 집계 |

양쪽 모두 **기준 시점 이전의 낙찰 결과만** 사용합니다. 학습에서 미래를 보면
검증 지표가 부풀고, 운영에서는 존재하지 않는 정보라 성능이 무너집니다.

행당 조회는 쓰지 마십시오. 150ms/행이라 773,045 행이면 32시간입니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.app.core.timeutil import utcnow

# SQLAlchemy 와 pandas 는 이 모듈이 실제로 DB/프레임을 태울 때만 지연 임포트합니다.
# 테스트 환경이나 모델 로드 시 불필요한 의존성을 피하기 위함입니다.
if TYPE_CHECKING:
    import pandas as pd


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

    order_institution 은 예측 API 스키마(PredictionRequest)가 쓰는 이름입니다.
    이 별칭이 빠지면 API 로 들어온 기관명이 통째로 무시되어 추론이 상수로 떨어집니다.
    """
    for key in ("dminstt_nm", "order_institution", "ntce_instt_nm", "ntceInsttNm"):
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
    return utcnow()


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


HISTORY_MIN_SAMPLES = 5
RATE_COLUMN = "winning_rate"
TIME_COLUMN = "openg_dt"
INSTITUTION_COLUMN = "dminstt_nm"

# 명백한 오류값입니다. 낙찰률이 0 이거나 100 을 넘는 행은 이력에서 제외합니다.
VALID_RATE_MIN = 50.0
VALID_RATE_MAX = 120.0


def attach_institution_history(
    df: pd.DataFrame,
    *,
    min_samples: int = HISTORY_MIN_SAMPLES,
) -> pd.DataFrame:
    """학습 프레임에 기관 이력 낙찰률을 붙입니다.

    각 행은 **자기 자신과 미래를 제외한** 같은 기관의 과거 낙찰률 평균을 받습니다.
    개찰일 순으로 정렬한 뒤 `shift(1).expanding().mean()` 을 쓰므로 누수가 없습니다.

    이력이 `min_samples` 미만인 행은 카테고리 기본값으로 채웁니다. 표본이 한둘인
    평균은 잡음이라 오히려 성능을 떨어뜨립니다.

    Returns:
        `inst_hist_rate`(0~1 비율)와 `inst_sample_cnt` 가 추가된 새 프레임.
        입력 행 순서는 그대로 유지됩니다.
    """
    import pandas as pd

    out = df.copy()
    if INSTITUTION_COLUMN not in out.columns or RATE_COLUMN not in out.columns:
        out["inst_hist_rate"] = _default_institution_rate(_frame_category(out))
        out["inst_sample_cnt"] = 0
        return out

    rate = pd.to_numeric(out[RATE_COLUMN], errors="coerce")
    # 오류값을 NaN 으로 만들면 expanding 평균과 건수 집계에서 자동으로 빠집니다.
    rate = rate.where(rate.between(VALID_RATE_MIN, VALID_RATE_MAX))

    if TIME_COLUMN in out.columns:
        time_index = pd.to_datetime(out[TIME_COLUMN], errors="coerce")
    else:
        time_index = pd.Series(range(len(out)), index=out.index)

    work = pd.DataFrame(
        {"key": out[INSTITUTION_COLUMN].astype("string"), "rate": rate, "t": time_index}
    )
    # 안정 정렬이라 개찰일이 같은 행끼리는 원래 순서를 지킵니다.
    # 날짜를 못 읽은 행은 맨 앞에 둬 뒤쪽 행의 이력을 오염시키지 않게 합니다.
    ordered = work.sort_values("t", kind="mergesort", na_position="first")

    grouped = ordered.groupby("key", sort=False)["rate"]
    hist = grouped.transform(lambda s: s.shift(1).expanding().mean())
    count = grouped.transform(lambda s: s.shift(1).expanding().count())

    # 정렬 전 순서로 되돌립니다.
    hist = hist.reindex(out.index)
    count = count.reindex(out.index).fillna(0)

    fallback = _default_institution_rate(_frame_category(out))
    usable = hist.notna() & (count >= min_samples)

    out["inst_hist_rate"] = (hist / 100.0).where(usable, fallback)
    out["inst_sample_cnt"] = count.astype(int)
    return out


def _frame_category(df: pd.DataFrame) -> str:
    """프레임이 단일 카테고리면 그 값을, 아니면 빈 문자열을 돌려줍니다."""
    if "category" not in df.columns:
        return ""
    unique = df["category"].dropna().unique()
    return str(unique[0]) if len(unique) == 1 else ""


def rebuild_institution_stats(session: Any, *, min_samples: int = HISTORY_MIN_SAMPLES) -> dict:
    """`institution_win_rate_stats` 를 통째로 다시 만듭니다.

    추론 경로가 매번 bid_results 를 COUNT + AVG 하면 건당 150ms 가 걸립니다.
    이 표를 두면 유니크 키 조회 한 번으로 끝납니다.

    학습(`attach_institution_history`)과 같은 정의이며, 이 표는 그 정의의
    현재 시점 값입니다. 이상치 제외 기준도 같습니다.
    """
    from sqlalchemy import delete, func, select

    from src.app.models.bids import BidResult, InstitutionWinRateStat

    rate = BidResult.sucsf_bid_rate
    stmt = (
        select(
            BidResult.dminstt_nm,
            BidResult.category,
            func.count(BidResult.id).label("sample_count"),
            func.avg(rate).label("avg_rate"),
        )
        .where(
            BidResult.dminstt_nm.is_not(None),
            BidResult.dminstt_nm != "",
            rate.is_not(None),
            rate > VALID_RATE_MIN,
            rate < VALID_RATE_MAX,
        )
        .group_by(BidResult.dminstt_nm, BidResult.category)
        .having(func.count(BidResult.id) >= min_samples)
    )

    rows = session.execute(stmt).all()
    now = utcnow()
    payload = [
        {
            "institution_name": name,
            "category": category or "",
            "sample_count": int(count),
            "avg_rate": avg,
            "rebuilt_at": now,
        }
        for name, category, count, avg in rows
        if _normalize_institution_name(name) not in _PLACEHOLDER_INSTITUTIONS
    ]

    session.execute(delete(InstitutionWinRateStat))
    if payload:
        session.bulk_insert_mappings(InstitutionWinRateStat, payload)
    session.commit()
    return {"institutions": len(payload), "rebuilt_at": now.isoformat()}


def _lookup_from_stats(session: Any, institution_name: str, category: str) -> float | None:
    """사전 집계 표에서 조회합니다. 표가 비었거나 항목이 없으면 None."""
    from sqlalchemy import select

    from src.app.models.bids import InstitutionWinRateStat

    stmt = select(InstitutionWinRateStat.avg_rate).where(
        InstitutionWinRateStat.institution_name == institution_name,
        InstitutionWinRateStat.category == (category or ""),
    )
    value = session.execute(stmt).scalar()
    if value is None:
        return None
    rate = float(value)
    # 표에는 퍼센트(87.5)로 저장하고 특징은 비율(0.875)로 씁니다.
    return rate / 100.0 if rate > 1.0 else rate


def lookup_institution_history(features_dict: dict[str, Any], session: Any = None) -> float:
    """features_dict 에서 기관명과 기준일을 추출해 이력 낙찰률을 반환합니다.

    사전 집계 표를 먼저 봅니다. 표에 없으면(신규 기관, 아직 갱신 전) 실시간
    집계로 내려가고, 그것도 안 되면 카테고리 기본값입니다.

    session 이 없으면(예: 모델 로드 시) 기본값을 반환합니다.
    """
    institution_name = _resolve_institution_name(features_dict)
    category = _resolve_category(features_dict)
    if not institution_name or session is None:
        return _default_institution_rate(category)

    cached = _lookup_from_stats(session, institution_name, category)
    if cached is not None:
        return cached

    return calculate_institution_win_rate(
        session=session,
        institution_name=institution_name,
        reference_date=_resolve_reference_date(features_dict),
        category=category,
    )


def lookup_institution_sample_count(features_dict: dict[str, Any], session: Any = None) -> float:
    """이력 표본 수를 집계 표에서 조회합니다.

    이 함수가 없던 동안 서빙은 이 특징을 **항상 0 으로** 넘겼습니다.
    `attach_institution_history` 가 학습 때 만드는 파생 컬럼이라
    `announcement_feature_payload` 의 원본 컬럼 목록에 없고, `inst_hist_rate`
    와 달리 조회 폴백도 없었기 때문입니다.

    2026-08-05 대조 실측에서 학습값과 서빙값의 평균절대차가 761 이었습니다.
    모델은 "표본이 많으면 이력을 믿어라" 를 배웠는데 운영에서는 늘 표본 0 을
    받고 있었습니다 (`servc_feature_parity_20260805.md`).
    """
    institution_name = _resolve_institution_name(features_dict)
    if not institution_name or session is None:
        return 0.0

    from sqlalchemy import select

    from src.app.models.bids import InstitutionWinRateStat

    stmt = select(InstitutionWinRateStat.sample_count).where(
        InstitutionWinRateStat.institution_name == institution_name,
        InstitutionWinRateStat.category == (_resolve_category(features_dict) or ""),
    )
    value = session.execute(stmt).scalar()
    return float(value) if value is not None else 0.0
