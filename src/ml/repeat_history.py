"""
src/ml/repeat_history.py

같은 발주처가 반복 발주하는 사업의 과거 낙찰 이력을 계산하는 모듈.

용역은 청소·경비·통학버스·방과후프로그램처럼 **같은 기관이 1~2년 주기로 같은
사업을 다시 발주**합니다. 2025년 검증 표본의 26.05% 가 재발주 건이고, 재발주
주기 중앙값은 358일입니다. 그리고 재발주 건의 낙찰률은 **직전 회차와의 절대차
중앙값이 0.252%p** 로 사실상 그대로 재현됩니다.

공고명을 분야 분류로 쓰는 것과는 다릅니다. 분야 신호는 이미 소분류 200종이
담고 있어 TF-IDF 를 얹어도 개선이 없었습니다(RMSE -0.19%). 반면 공고명을
**개체 식별 키**로 써서 재발주 이력을 붙이면 전체 RMSE 가 3.1% 내려갑니다.
근거: docs/design/servc_repeat_procurement_20260803.md

경로가 둘이고 정의는 하나여야 합니다 (AGENTS.md 6항, train/serve skew 금지).

| 경로 | 함수 | 방식 |
| --- | --- | --- |
| 학습 | `attach_repeat_history` | 프레임 전체를 pandas 로 한 번에 |
| 추론 | `lookup_repeat_history` | 같은 기관 이력을 조회해 제목으로 매칭 |

양쪽 모두 `normalize_title` 로 키를 만들고 **기준 시점 이전 개찰 건만** 씁니다.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# 회차·연도·긴급 표기를 지워야 같은 사업의 서로 다른 해 공고가 한 키로 묶입니다.
# "2026학년도 창남초등학교 통학버스 임차 용역 입찰 공고" 와
# "2025학년도 창남초등학교 통학버스 임차 용역 재공고" 는 같은 사업입니다.
_BRACKET_RE = re.compile(r"[\[\(\{<][^\]\)\}>]*[\]\)\}>]")
_YEAR_RE = re.compile(r"(19|20)\d{2}\s*(학년도|년도|년분|년)?")
_NOISE_RE = re.compile(
    # 긴 표기를 먼저 둬야 합니다. "입찰" 을 앞에 두면 "입찰공고" 의 뒷글자가 남습니다.
    r"(재공고|재입찰|긴급|입찰공고|입찰|공고|제\s*\d+\s*차|\d+차|소액수의|견적|"
    r"단가계약|총액계약|변경|정정|취소|연장|추가)"
)
_NONWORD_RE = re.compile(r"[^가-힣A-Za-z]+")

# 정규화 후 이보다 짧으면 서로 다른 사업이 한 키로 뭉칩니다. 이력을 붙이지 않습니다.
MIN_TITLE_LENGTH = 4

RATE_COLUMN = "winning_rate"
TIME_COLUMN = "openg_dt"
TITLE_COLUMN = "bid_ntce_nm"
INSTITUTION_COLUMN = "dminstt_nm"

# institution_history 와 같은 이상치 기준을 씁니다.
VALID_RATE_MIN = 50.0
VALID_RATE_MAX = 120.0

DEFAULT_REPEAT_RATE = 0.925
NO_HISTORY_DAYS = -1.0

REPEAT_FEATURES = (
    "is_repeat",
    "repeat_cnt",
    "repeat_hist_rate",
    "repeat_prev_rate",
    "repeat_hist_std",
    "repeat_days_since",
)


def normalize_title(text: Any) -> str:
    """공고명을 재발주 매칭 키로 정규화합니다.

    학습과 추론이 반드시 이 함수를 공유해야 합니다. 정규화가 갈리면 같은
    사업이 다른 키가 되어 이력이 붙지 않습니다.
    """
    if text is None:
        return ""
    value = _BRACKET_RE.sub(" ", str(text))
    value = _YEAR_RE.sub(" ", value)
    value = _NOISE_RE.sub(" ", value)
    value = _NONWORD_RE.sub(" ", value)
    return " ".join(value.split())


def repeat_key(institution: Any, title: Any) -> str:
    """기관명 + 정규화 공고명. 제목이 너무 짧으면 빈 키를 돌려줍니다."""
    normalized = normalize_title(title)
    if len(normalized) < MIN_TITLE_LENGTH:
        return ""
    return f"{str(institution).strip()}|{normalized}"


def attach_repeat_history(df: pd.DataFrame) -> pd.DataFrame:
    """학습 프레임에 재발주 이력을 붙입니다.

    각 행은 **자기 자신과 미래를 제외한** 같은 키의 과거 낙찰 결과를 받습니다.
    개찰일 순으로 정렬한 뒤 `shift(1).expanding()` 을 쓰므로 누수가 없습니다.

    Returns:
        REPEAT_FEATURES 가 추가된 새 프레임. 입력 행 순서는 유지됩니다.
    """
    import pandas as pd

    out = df.copy()
    required = {TITLE_COLUMN, INSTITUTION_COLUMN, RATE_COLUMN}
    if not required.issubset(out.columns):
        return _fill_defaults(out)

    keys = [
        repeat_key(inst, title)
        for inst, title in zip(out[INSTITUTION_COLUMN], out[TITLE_COLUMN], strict=False)
    ]
    key_series = pd.Series(keys, index=out.index, dtype="string")

    rate = pd.to_numeric(out[RATE_COLUMN], errors="coerce")
    rate = rate.where(rate.between(VALID_RATE_MIN, VALID_RATE_MAX))

    if TIME_COLUMN in out.columns:
        time_index = pd.to_datetime(out[TIME_COLUMN], errors="coerce")
    else:
        time_index = pd.Series(range(len(out)), index=out.index)

    work = pd.DataFrame({"key": key_series, "rate": rate, "t": time_index})
    # 안정 정렬이라 개찰일이 같은 행끼리는 원래 순서를 지킵니다.
    ordered = work.sort_values("t", kind="mergesort", na_position="first")

    grouped = ordered.groupby("key", sort=False)
    prior_rate = grouped["rate"]
    count = prior_rate.transform(lambda s: s.shift(1).expanding().count())
    mean = prior_rate.transform(lambda s: s.shift(1).expanding().mean())
    std = prior_rate.transform(lambda s: s.shift(1).expanding().std())
    prev = prior_rate.transform(lambda s: s.shift(1))
    prev_time = grouped["t"].transform(lambda s: s.shift(1))
    days_since = (ordered["t"] - prev_time).dt.total_seconds() / 86400.0

    # 정렬 전 순서로 되돌립니다.
    count = count.reindex(out.index).fillna(0.0)
    mean = mean.reindex(out.index)
    std = std.reindex(out.index)
    prev = prev.reindex(out.index)
    days_since = days_since.reindex(out.index)

    # 키가 비면(제목이 너무 짧으면) 이력을 무효로 둡니다.
    usable = (key_series.fillna("") != "") & (count > 0)

    out["is_repeat"] = usable.astype(float)
    out["repeat_cnt"] = count.where(usable, 0.0).astype(float)
    out["repeat_hist_rate"] = (mean / 100.0).where(usable, DEFAULT_REPEAT_RATE)
    out["repeat_prev_rate"] = (prev / 100.0).where(usable, DEFAULT_REPEAT_RATE)
    out["repeat_hist_std"] = (std / 100.0).where(usable).fillna(0.0)
    out["repeat_days_since"] = days_since.where(usable, NO_HISTORY_DAYS).fillna(NO_HISTORY_DAYS)
    return out


def _fill_defaults(out: pd.DataFrame) -> pd.DataFrame:
    out["is_repeat"] = 0.0
    out["repeat_cnt"] = 0.0
    out["repeat_hist_rate"] = DEFAULT_REPEAT_RATE
    out["repeat_prev_rate"] = DEFAULT_REPEAT_RATE
    out["repeat_hist_std"] = 0.0
    out["repeat_days_since"] = NO_HISTORY_DAYS
    return out


def lookup_repeat_history(
    features_dict: dict[str, Any],
    session: Any,
    *,
    max_rows: int = 5000,
) -> dict[str, float] | None:
    """추론 경로에서 재발주 이력을 조회합니다.

    정규화 제목은 DB 컬럼이 아니라 인덱스를 못 씁니다. 기관으로 먼저 좁힌 뒤
    파이썬에서 매칭합니다. 기관 한 곳의 이력은 통상 수백~수천 건입니다.

    반환값이 None 이면 이력이 없다는 뜻이며, 호출부가 기본값을 씁니다.
    """
    if session is None:
        return None

    institution = features_dict.get("dminstt_nm") or features_dict.get("ntceInsttNm")
    title = features_dict.get("bid_ntce_nm") or features_dict.get("bidNtceNm")
    key = repeat_key(institution, title)
    if not key:
        return None

    try:
        import pandas as pd
        from sqlalchemy import select

        from src.app.models.bids import BidResult

        stmt = (
            select(BidResult.bid_ntce_nm, BidResult.sucsf_bid_rate, BidResult.rl_openg_dt)
            .where(
                BidResult.dminstt_nm == institution,
                BidResult.sucsf_bid_rate.is_not(None),
                BidResult.sucsf_bid_rate > VALID_RATE_MIN,
                BidResult.sucsf_bid_rate < VALID_RATE_MAX,
            )
            .order_by(BidResult.rl_openg_dt.desc())
            .limit(max_rows)
        )
        rows = session.execute(stmt).all()
    except Exception:
        # 조회 실패는 이력 없음으로 처리합니다. 예측 자체를 막지 않습니다.
        return None

    matched = [
        (float(rate), opened)
        for name, rate, opened in rows
        if repeat_key(institution, name) == key
    ]
    if not matched:
        return None

    reference = features_dict.get(TIME_COLUMN) or features_dict.get("bid_ntce_dt")
    reference_ts = pd.to_datetime(reference, errors="coerce")
    if pd.notna(reference_ts):
        matched = [(r, t) for r, t in matched if t is not None and t < reference_ts]
    if not matched:
        return None

    matched.sort(key=lambda item: item[1])
    rates = pd.Series([r for r, _ in matched], dtype="float64")
    last_rate, last_time = matched[-1]

    days_since = NO_HISTORY_DAYS
    if pd.notna(reference_ts) and last_time is not None:
        days_since = float((reference_ts - last_time).total_seconds() / 86400.0)

    return {
        "is_repeat": 1.0,
        "repeat_cnt": float(len(rates)),
        "repeat_hist_rate": float(rates.mean()) / 100.0,
        "repeat_prev_rate": float(last_rate) / 100.0,
        "repeat_hist_std": float(rates.std()) / 100.0 if len(rates) > 1 else 0.0,
        "repeat_days_since": days_since,
    }
