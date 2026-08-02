"""
src/ml/dataset.py

학습 데이터셋 빌더.

`bid_announcements` 와 `bid_results` 를 조인해 학습 프레임을 만들고 Feature Store
(materialized parquet)에 캐싱합니다.

주의할 점 두 가지입니다.

1. 두 테이블 사이에 FK 가 없습니다. 공고번호(`bid_ntce_no`) + 차수(`bid_ntce_ord`)
   + 업무구분(`category`) 으로 붙이며, **차수 자리수가 서로 다릅니다.**
   `bid_results` 는 2자리(`00`), `bid_announcements` 는 3자리(`000`) 라서
   정규화 없이 조인하면 0건이 나옵니다.
2. 카테고리마다 조인 가능 비율이 크게 다릅니다 (2026-08-02 실측).

   | 카테고리 | 조인 성공 | 낙찰 전체 | 비율 |
   | --- | ---: | ---: | ---: |
   | Thng | 857,212 | 858,026 | 99.9% |
   | Servc | 46,587 | 889,933 | 5.2% |
   | Cnstwk | 65,541 | 1,254,295 | 5.2% |

   용역·건설은 공고 데이터가 거의 수집되지 않아 조인하면 표본이 급감합니다.
   가격 특징(예정가격/기초금액)이 필요 없다면 `require_announcement=False` 로
   낙찰 결과만 쓸 수 있습니다.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult

logger = logging.getLogger(__name__)

# 낙찰률 유효 구간. 이 범위를 벗어난 값은 입력 오류로 보고 제외합니다.
MIN_WINNING_RATE = 70.0
MAX_WINNING_RATE = 110.0

# 학습 프레임의 컬럼 계약. features.py 가 이 키들을 읽습니다.
TRAINING_COLUMNS = (
    "bid_ntce_no",
    "bid_ntce_nm",
    "ntce_instt_nm",
    "dminstt_nm",
    "category",
    "presmpt_prce",
    "base_amount",
    "bid_ntce_dt",
    "bid_clse_dt",
    "openg_dt",
    "sucsf_bid_amt",
    "winning_rate",
)


def _normalized_ord():
    """차수 자리수 차이를 흡수합니다 (`00` -> `000`).

    LPAD 는 SQLite 에 없어 테스트가 깨집니다. 앞에 `000` 을 붙이고 뒤 3자를
    잘라내는 방식은 MySQL/MariaDB 와 SQLite 모두에서 동작합니다.
    """
    return func.substr(literal("000").concat(BidResult.bid_ntce_ord), -3, 3)


def build_training_dataset(
    db_session: Session,
    category_code: str | None = None,
    output_dir: str = "data/feature_store",
    *,
    require_announcement: bool = True,
    limit: int | None = None,
) -> pd.DataFrame:
    """DB 조인 및 정제를 거친 학습 데이터셋을 만들고 parquet 으로 캐싱합니다.

    require_announcement=False 면 공고를 붙이지 않고 낙찰 결과만 씁니다.
    공고 수집률이 낮은 용역/건설에서 표본을 확보할 때 씁니다. 이때 가격 컬럼은
    낙찰금액으로 채워지므로 특징 설계에서 반드시 감안해야 합니다.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if require_announcement:
        stmt = select(
            BidResult.bid_ntce_no,
            BidAnnouncement.bid_ntce_nm,
            BidAnnouncement.ntce_instt_nm,
            BidResult.dminstt_nm,
            BidResult.category,
            BidAnnouncement.presmpt_prce,
            BidAnnouncement.base_amount,
            BidAnnouncement.bid_ntce_dt,
            BidAnnouncement.bid_clse_dt,
            BidResult.rl_openg_dt.label("openg_dt"),
            BidResult.sucsf_bid_amt,
            BidResult.sucsf_bid_rate.label("winning_rate"),
        ).join(
            BidAnnouncement,
            (BidAnnouncement.bid_ntce_no == BidResult.bid_ntce_no)
            & (BidAnnouncement.bid_ntce_ord == _normalized_ord())
            & (BidAnnouncement.category == BidResult.category),
        )
    else:
        stmt = select(
            BidResult.bid_ntce_no,
            BidResult.bid_ntce_nm,
            BidResult.dminstt_nm.label("ntce_instt_nm"),
            BidResult.dminstt_nm,
            BidResult.category,
            BidResult.sucsf_bid_amt.label("presmpt_prce"),
            BidResult.sucsf_bid_amt.label("base_amount"),
            BidResult.rl_openg_dt.label("bid_ntce_dt"),
            BidResult.rl_openg_dt.label("bid_clse_dt"),
            BidResult.rl_openg_dt.label("openg_dt"),
            BidResult.sucsf_bid_amt,
            BidResult.sucsf_bid_rate.label("winning_rate"),
        )

    stmt = stmt.where(BidResult.sucsf_bid_rate.is_not(None))
    if category_code:
        stmt = stmt.where(BidResult.category == category_code)
    if limit:
        stmt = stmt.limit(limit)

    rows = db_session.execute(stmt).mappings().all()
    df = pd.DataFrame([dict(row) for row in rows], columns=list(TRAINING_COLUMNS))

    if df.empty:
        logger.warning(
            "학습 데이터가 비었습니다 (category=%s, require_announcement=%s). "
            "용역/건설은 공고 조인율이 5%% 대라 require_announcement=False 를 검토하십시오.",
            category_code,
            require_announcement,
        )
        return df

    before = len(df)
    df["winning_rate"] = pd.to_numeric(df["winning_rate"], errors="coerce")
    df = df[df["winning_rate"].between(MIN_WINNING_RATE, MAX_WINNING_RATE)]
    df = df.dropna(subset=["sucsf_bid_amt", "winning_rate"])
    logger.info("정제 후 %d행 (제외 %d행)", len(df), before - len(df))

    parquet_file = out_path / f"dataset_{category_code or 'all'}.parquet"
    df.to_parquet(parquet_file, index=False)
    return df
