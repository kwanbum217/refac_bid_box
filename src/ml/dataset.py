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
2. 카테고리마다 조인 가능 비율이 다릅니다 (2026-08-03 백필 후 실측).

   | 카테고리 | 조인 성공 | 비율 |
   | --- | ---: | ---: |
   | Thng | 857,212 | 99.9% |
   | Servc | 1,077,789 | 높음 |
   | Cnstwk | 조사 필요 | - |

   백필 이전에는 용역 조인율이 5.2% 였습니다. 공고가 없는 구간을 다룰 때는
   `require_announcement=False` 로 낙찰 결과만 쓸 수 있으나, 이 경우 가격 컬럼이
   낙찰금액으로 채워지므로 특징 설계에서 반드시 감안해야 합니다.

3. 제도 필드는 전부 `raw_data` JSON 안에 있습니다.

   낙찰하한율·낙찰방법·용역구분 등은 정식 컬럼이 아니라 `bid_announcements.raw_data`
   에만 존재합니다. `INSTITUTION_FIELDS` 가 그 매핑이며, 근거는
   `docs/design/servc_institution_verification_20260803.md` 입니다.

4. 비예가 공고의 학습 프레임 배제 (수정 금지).

   비예가(``prearngPrceDcsnMthdNm`` 이 ``"없음"`` 또는 부재) 공고는 LEFT JOIN 후
   ``sucsf_bid_rate IS NOT NULL`` 조건과 후속 ``dropna()`` 에서 자연 배제된다.

   이는 의도적 설계이다:
   - 비예가 공고는 예정가격을 작성하지 않는 제도이므로 낙찰률(= 낙찰금액 /
     예정가격)의 분모가 존재하지 않는다.
   - 학습 데이터에 잔존했던 2,405건(0.47%)은 국지적 표기 관행의 예외 데이터로,
     낙찰률 100% 비율이 17.59% 에 달하는 등 정상 표본이 아니다.
   - 따라서 이 배제 동작을 오인하여 비예가를 학습에 복구해서는 안 된다.
   - 서빙 라우팅(API, 챗봇 도구)에서의 비예가 차단은
     ``model_registry.classify_price_decision_method`` 단일 함수가 담당한다.

   원인 규명: ``docs/design/servc_nonprearng_population_cause_20260812.md``
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

# 추정가격 유효 구간. 용역 표본에서 10만원 미만 7,215건, 1조 초과 6건이
# 확인되었고 (전체의 0.99%), 이 값들이 비율 특징의 평균을 통째로 망가뜨립니다.
# 근거: docs/design/servc_institution_verification_20260803.md 7장
MIN_PRESMPT_PRCE = 100_000
MAX_PRESMPT_PRCE = 1_000_000_000_000

# 데이터셋 parquet 캐시 기본 위치.
DEFAULT_OUTPUT_DIR = "data/feature_store"

# raw_data JSON 키 -> 학습 프레임 컬럼명.
# 전부 bid_announcements.raw_data 안에만 있어 정식 컬럼으로 조회할 수 없습니다.
INSTITUTION_FIELDS = {
    "lwlt_rate": "sucsfbidLwltRate",  # 낙찰하한율. 낙찰률과 Spearman 0.71
    "prearng_mthd": "prearngPrceDcsnMthdNm",  # 복수예가 / 단일예가 / 비예가
    "sucsfbid_mthd_nm": "sucsfbidMthdNm",  # 적격심사 구간이 문자열로 명시됨
    "srvce_div_nm": "srvceDivNm",  # 일반용역 / 기술용역. 산포가 7.92 대 2.97
    "lrg_clsfc_nm": "pubPrcrmntLrgClsfcNm",  # 공공조달 대분류 11종
    # 일반용역은 추정가격 구간이 아니라 용역 종류별 별표로 낙찰하한율이 갈립니다
    # (시설분야 89.995 대 보험 47.994). 대분류 11종으로는 그 차이를 못 담습니다.
    # 근거: docs/design/g2b_procurement_institution_analysis.md 5.4 절
    "mid_clsfc_nm": "pubPrcrmntMidClsfcNm",  # 중분류 40종
    "clsfc_nm": "pubPrcrmntClsfcNm",  # 소분류 200종
    "intrbid_yn": "intrbidYn",  # 국제입찰 여부
    "ppsw_gnrl_srvce_yn": "ppswGnrlSrvceYn",  # 조달청 일반용역 여부
    "tech_ablt_evl_rt": "techAbltEvlRt",  # 협상 계약 기술능력 평가비율
    "bid_prce_evl_rt": "bidPrceEvlRt",  # 협상 계약 입찰가격 평가비율
    "tot_prdprc_num": "totPrdprcNum",  # 복수예비가격 총수 (통상 15)
    "drwt_prdprc_num": "drwtPrdprcNum",  # 추첨수 (통상 4)
}

# 학습 프레임의 컬럼 계약. features.py 가 이 키들을 읽습니다.
TRAINING_COLUMNS = (
    "bid_ntce_no",
    "bid_ntce_nm",
    "ntce_instt_nm",
    "dminstt_nm",
    "category",
    "cntrct_mthd_nm",
    # 재공고는 유찰 뒤 재입찰이라 경쟁이 약합니다 (낙찰률 94.15 대 등록공고 91.16).
    "ntce_kind_nm",
    "bid_methd_nm",
    "presmpt_prce",
    "base_amount",
    "bid_ntce_dt",
    "bid_clse_dt",
    "openg_dt",
    "sucsf_bid_amt",
    "winning_rate",
    *INSTITUTION_FIELDS,
)


def _json_text(db_session: Session, column, key: str):
    """raw_data JSON 키를 텍스트로 추출합니다.

    MySQL 은 JSON_EXTRACT 결과가 따옴표로 감싸여 나와 JSON_UNQUOTE 가 필요합니다.
    SQLite 의 json_extract 는 스칼라를 이미 언쿼트해 돌려주고 JSON_UNQUOTE 자체가
    없으므로, 방언을 보고 갈라야 테스트와 운영이 모두 동작합니다.
    """
    bind = db_session.get_bind()
    if bind is not None and bind.dialect.name == "mysql":
        return func.json_unquote(func.json_extract(column, f"$.{key}"))
    return func.json_extract(column, f"$.{key}")


def _institution_columns(db_session: Session) -> list:
    return [
        func.nullif(_json_text(db_session, BidAnnouncement.raw_data, key), literal("")).label(
            alias
        )
        for alias, key in INSTITUTION_FIELDS.items()
    ]


def _normalized_ord():
    """차수 자리수 차이를 흡수합니다 (`00` -> `000`).

    LPAD 는 SQLite 에 없어 테스트가 깨집니다. 앞에 `000` 을 붙이고 뒤 3자를
    잘라내는 방식은 MySQL/MariaDB 와 SQLite 모두에서 동작합니다.
    """
    return func.substr(literal("000").concat(BidResult.bid_ntce_ord), -3, 3)


def build_training_dataset(
    db_session: Session,
    category_code: str | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
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
            BidAnnouncement.cntrct_mthd_nm,
            BidAnnouncement.ntce_kind_nm,
            BidAnnouncement.bid_methd_nm,
            BidAnnouncement.presmpt_prce,
            BidAnnouncement.base_amount,
            BidAnnouncement.bid_ntce_dt,
            BidAnnouncement.bid_clse_dt,
            BidResult.rl_openg_dt.label("openg_dt"),
            BidResult.sucsf_bid_amt,
            BidResult.sucsf_bid_rate.label("winning_rate"),
            *_institution_columns(db_session),
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
            # 공고를 붙이지 않는 경로에는 계약방법·제도 필드가 없습니다.
            # 뒤에서 None 으로 채워 컬럼 계약만 맞춥니다.
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

    # 정렬을 걸지 않으면 행 순서가 DB 반환 순서에 좌우되어 홀드아웃 구간이 매번
    # 달라지고, limit 을 걸었을 때 어떤 표본이 뽑힐지도 알 수 없습니다.
    # limit 은 최근 구간을 보려는 용도이므로 내림차순으로 잘라냅니다.
    # trainer 가 개찰일로 다시 정렬하므로 프레임 순서 자체는 학습에 영향이 없습니다.
    if limit:
        stmt = stmt.order_by(BidResult.rl_openg_dt.desc()).limit(limit)
    else:
        stmt = stmt.order_by(BidResult.rl_openg_dt.asc())

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

    # 추정가격 이상값을 걸러냅니다. 공고를 붙이지 않는 경로는 이 컬럼이 낙찰금액
    # 이므로 같은 규칙을 적용해도 의미가 어긋나지 않습니다.
    df["presmpt_prce"] = pd.to_numeric(df["presmpt_prce"], errors="coerce")
    after_rate = len(df)
    df = df[df["presmpt_prce"].between(MIN_PRESMPT_PRCE, MAX_PRESMPT_PRCE)]
    if after_rate != len(df):
        logger.info("추정가격 이상값 %d행 제외", after_rate - len(df))

    for column in ("lwlt_rate", "tech_ablt_evl_rt", "bid_prce_evl_rt"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ("tot_prdprc_num", "drwt_prdprc_num"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    # 하한율 0 은 값이 아니라 미기재입니다. 결측으로 되돌려야 특징 쪽에서
    # 결측 지시자와 절단 로직이 올바르게 갈립니다.
    df.loc[df["lwlt_rate"] == 0, "lwlt_rate"] = pd.NA

    logger.info("정제 후 %d행 (제외 %d행)", len(df), before - len(df))

    parquet_file = out_path / f"dataset_{category_code or 'all'}.parquet"
    df.to_parquet(parquet_file, index=False)
    return df


def announcement_feature_payload(bid: BidAnnouncement) -> dict:
    """공고 한 건을 학습 프레임과 같은 키 규격으로 펼칩니다.

    추론 경로가 이 함수를 거치지 않으면 제도 특징 26종이 전부 기본값으로
    떨어집니다. 학습은 raw_data JSON 에서 뽑아 쓰는데 API 가 안 뽑아 주면
    같은 모델이 학습 때와 다른 입력을 보게 됩니다(train/serve skew).
    키 매핑은 INSTITUTION_FIELDS 단일 정의를 그대로 씁니다.
    """
    raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    payload = {
        column: getattr(bid, column, None)
        for column in TRAINING_COLUMNS
        if column not in INSTITUTION_FIELDS
    }
    for column, json_key in INSTITUTION_FIELDS.items():
        value = raw.get(json_key)
        payload[column] = None if value in ("", None) else value
    return payload
