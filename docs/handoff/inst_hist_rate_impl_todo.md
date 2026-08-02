> **작성일**: 2026-08-02
> **버전**: v0.1.0
> **상태**: 단건 계산 함수만 구현. **학습·추론 경로에 미연결**

# 기관별 낙찰률 이력(inst_hist_rate) 구현 TODO

## 배경

현재 `src/ml/features.py` 는 `inst_hist_rate` 가 입력되지 않으면 `DEFAULT_INST_RATE(0.925)` 를 상수로 사용합니다. 용역 모델 성능을 올리려면 이 값을 실제 기관별 낙찰률 이력으로 계산해야 합니다.

이 문서는 `src/ml/institution_history.py` 의 설계 배경과 남은 연결 작업을 정리합니다.

---

## 현재 상태 (2026-08-02 검토)

단건 계산 함수 `calculate_institution_win_rate()` 는 구현·검증되었습니다. 그러나 **학습·추론 경로 어디에도 연결되어 있지 않습니다.**

`features.py` 는 `session` 인자를 받도록 준비돼 있으나, 실제 호출부인 `trainer.py:229` 와 `predictor.py:35` 는 session 을 넘기지 않습니다. 따라서 `inst_hist_rate` 는 여전히 상수입니다. 기존 `DEFAULT_INST_RATE(0.925)` 가 카테고리별 상수(Thng 0.9132 / Servc 0.9011 / Cnstwk 0.8859)로 바뀌었을 뿐입니다.

남은 작업은 두 가지 제약을 동시에 만족해야 합니다.

| 제약 | 내용 |
| --- | --- |
| 성능 | 행당 2쿼리(COUNT + AVG). 실측 150ms/행. 용역 773,045행 기준 **약 32시간**. 기관/카테고리/기간 GROUP BY 배치 집계가 필요합니다 |
| train/serve 단일화 | 추론에만 연결하면 학습은 상수, 추론은 DB 값이 되어 AGENTS.md 6항이 금지하는 skew 가 발생합니다. **양쪽을 함께** 바꿔야 합니다 |

배치 집계의 윈도우 크기, 미래 정보 누수 방지 기준, 최소 표본 수는 실측으로 정합니다. 후보안을 비교해 근거와 함께 결정하고 이 문서에 기록하십시오.

현재 상태는 `tests/test_institution_history.py` 의 `test_production_feature_path_still_uses_constant` 와 `test_train_and_serve_use_the_same_session_policy` 가 고정하고 있습니다. 연결 작업을 하면 이 두 테스트를 함께 갱신하십시오.

---

## 파일 구조

| 파일 | 역할 |
| --- | --- |
| `src/ml/institution_history.py` | 뼈대(스켈레톤) |
| `src/ml/features.py` | `inst_hist_rate` 산출 지점 |
| `src/app/models/bids.py` | `BidResult` 스키마 참조 |

---

## TODO-1: 기본값 결정 (20줄 이내)

**위치**: `src/ml/institution_history.py` `_default_institution_rate`

**작업**:

- 이력이 없는 기관에 적용할 기본 낙찰률을 결정합니다.
- 전체 평균, 카테고리별 평균, 또는 훈련셋 중앙값 중 하나를 선택합니다.

**고려사항**:

- 용역(Servc)과 물품(Thng)의 평균 낙찰률은 다릅니다.
- 현재 0.925는 92.5%로, 물품/용역 평균과 맞지 않을 수 있습니다.

**예시**:

```python
def _default_institution_rate(category: str = "") -> float:
    if category == "Servc":
        return 0.887
    if category == "Thng":
        return 0.842
    return 0.871
```

---

## TODO-2: 기관명 추출 기준 (20줄 이내)

**위치**: `src/ml/institution_history.py` `_resolve_institution_name`

**작업**:

- `dminstt_nm` (수요기관)과 `ntce_instt_nm` (공고기관) 중 하나를 선택합니다.
- 동일 기관명의 정규화(띄어쓰기, 특수문자, 지사명) 규칙을 결정합니다.

**고려사항**:

- 수요기관이 실제 예산 집행 주체이므로 낙찰률 예측에 더 직접적입니다.
- 공고기관은 조달청이 될 수 있어 수요기관과 다릅니다.

**예시**:

```python
def _normalize_institution_name(name: str) -> str:
    return name.strip().replace("  ", " ").split(" ")[0]

institution_name = _normalize_institution_name(
    features_dict.get("dminstt_nm") or features_dict.get("ntce_instt_nm") or ""
)
```

---

## TODO-3: 카테고리 필터 결정 (20줄 이내)

**위치**: `src/ml/institution_history.py` `_resolve_category`

**작업**:

- 이력 계산 시 카테고리를 필터할지, 전체 카테고리를 합산할지 결정합니다.

**옵션**:

| 옵션 | 장점 | 단점 |
| --- | --- | --- |
| 동일 카테고리만 | 업종 특성 반영 | 샘플 수 적음 |
| 전체 카테고리 합산 | 샘플 수 많음 | 업종 차이 무시 |
| 동일 카테고리 + 전체 평균 가중 | 중간 | 구현 복잡 |

**권장**: 용역 모델 개선이 목표이므로, 기본은 동일 카테고리, 샘플 부족 시 전체로 폴백.

---

## TODO-4: 기준 시점 결정 (20줄 이내)

**위치**: `src/ml/institution_history.py` `_resolve_reference_date`

**작업**:

- 현재 예측 대상 입찰의 기준 시점을 개찰일, 공고일, 입찰마감일 중 하나로 결정합니다.

**고려사항**:

- 개찰일(`openg_dt` / `rl_openg_dt`) 이후의 낙찰 결과를 이력으로 쓰면 미래 정보 누출입니다.
- 따라서 **기준 시점 이전**의 낙찰 결과만 사용해야 합니다.
- 개찰일을 기준으로 하는 것이 시계열 분할과 일관됩니다.

---

## TODO-5: 실제 DB 쿼리 작성 (30~40줄)

**위치**: `src/ml/institution_history.py` `calculate_institution_win_rate`

**작업**:

- `BidResult` 테이블에서 기관/기준일/카테고리 조건으로 낙찰률을 평균냅니다.
- `sucsf_bid_rate` 가 퍼센트(87.5) 단위인지 비율(0.875) 단위인지 확인 후 변환합니다.

**참고 스키마**:

```python
# src/app/models/bids.py
class BidResult(Base):
    __tablename__ = "bid_results"
    dminstt_nm = Column(String(200), nullable=True, comment="수요기관명")
    rl_openg_dt = Column(DateTime, nullable=True, comment="개찰일시")
    sucsf_bid_rate = Column(Numeric(10, 4), nullable=True, comment="낙찰률")
    category = Column(String(10), nullable=False, default="Thng")
```

**쿼리 예시**:

```python
from sqlalchemy import func

from src.app.models.bids import BidResult

query = session.query(func.avg(BidResult.sucsf_bid_rate)).filter(
    BidResult.dminstt_nm == institution_name,
    BidResult.rl_openg_dt < reference_date,
    BidResult.rl_openg_dt >= reference_date - timedelta(days=lookback_days),
    BidResult.sucsf_bid_rate.isnot(None),
    BidResult.sucsf_bid_rate > 0,
)
if category:
    query = query.filter(BidResult.category == category)

result = query.scalar()
if result is None:
    return _default_institution_rate(category)

# Numeric(10,4) 이 Decimal 이므로 float 변환
avg_rate = float(result)

# 87.5 형태로 저장돼 있다면 100 으로 나눔
if avg_rate > 1.0:
    avg_rate = avg_rate / 100.0

return avg_rate
```

**추가 고려**:

- 이상치 제거: 0% 또는 100%에 근접한 값 제외
- 최소 샘플 수: `min_samples` 미만 시 기본값
- 가중 평균: 최근 이력에 더 높은 가중치

---

## 연결 지점

`src/ml/features.py` 는 이미 다음과 같이 연결되어 있습니다.

```python
inst_hist_rate = _coerce_float(
    features_dict.get("inst_hist_rate") or lookup_institution_history(features_dict, session),
    DEFAULT_INST_RATE,
)
```

따라서 TODO-5를 구현하면 `/api/v1/predictions/predict-price` 에서 자동으로 실제 기관 이력이 반영됩니다.

---

## 검증 방법

1. 로컬 DB 또는 Docker Compose 로 MySQL 서버를 띄웁니다.
2. `bid_results` 테이블에 수요기관별로 충분한(5건 이상) 낙찰 결과가 있는지 확인합니다.
3. 다음 Python 스크립트로 특정 기관의 `inst_hist_rate` 를 확인합니다.

```python
from src.app.core.db import SessionLocal
from src.ml.institution_history import calculate_institution_win_rate
from datetime import datetime

session = SessionLocal()
rate = calculate_institution_win_rate(
    session,
    institution_name="특정기관명",
    reference_date=datetime.utcnow(),
    category="Servc",
)
print(rate)
```

---

## 완료 후 다음 단계

- TODO-5 까지 구현하면 `inst_hist_rate` 는 실제 기관 이력을 반영합니다.
- 이후 `src/ml/trainer.py` 의 학습 특징을 4개에서 확장할 수 있습니다.
- LightGBM/CatBoost 교체 및 K-Fold 교차 검증은 별도 작업으로 진행합니다.
