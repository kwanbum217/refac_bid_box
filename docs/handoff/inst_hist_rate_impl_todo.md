> **작성일**: 2026-08-02
> **버전**: v0.1.0
> **상태**: 뼈대 작성 완료, 담당자 구현 대기

# 기관별 낙찰률 이력(inst_hist_rate) 구현 TODO

## 배경

현재 `src/ml/features.py` 는 `inst_hist_rate` 가 입력되지 않으면 `DEFAULT_INST_RATE(0.925)` 를 상수로 사용합니다. 용역 모델 성능을 올리려면 이 값을 실제 기관별 낙찰률 이력으로 계산해야 합니다.

이 문서는 `src/ml/institution_history.py` 의 TODO-1~TODO-5 를 20~40줄 단위로 나누어 담당자가 직접 구현할 수 있도록 안내합니다.

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
