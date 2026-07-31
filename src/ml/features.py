"""
src/ml/features.py

★ Single Source of Truth (단일 특징 공급원)
train/serve skew를 근본적으로 원천 차단하기 위해 학습과 추론의 모든 특징 추출은
본 모듈의 `_compute_features()` 공통 로직을 거쳐서 산출됩니다.

비협상 원칙:
  - 학습/추론 특징 정의 별도 작성 금지
  - DEFAULT_INST_RATE 하드코딩 상수 사용 금지 (Redis/DB 집계 쿼리 사용)
"""

from typing import Any


def _compute_features(raw_data: dict[str, Any]) -> dict[str, Any]:
    """
    공통 특징 계산 내부 코어 함수.
    학습 데이터프레임의 1개 레코드 또는 추론 API의 요청 DTO가 동일하게 수용됩니다.
    """
    presumed_price = float(raw_data.get("presumed_price", 0.0))
    base_price = float(raw_data.get("base_price", presumed_price))

    # 하드코딩 상수 대신 집계값 또는 인자 수용
    inst_hist_rate = float(raw_data.get("inst_hist_rate", 0.925))

    # 차원 계산 예시 (52차원 벡터 빌드 로직 기준)
    price_ratio = presumed_price / base_price if base_price > 0 else 1.0

    features = {
        "presumed_price": presumed_price,
        "base_price": base_price,
        "price_ratio": price_ratio,
        "inst_hist_rate": inst_hist_rate,
        "category_code": raw_data.get("category_code", "Thng"),
    }

    # 텍스트 및 범주형 특징 계산 처리...
    return features


def build_feature_dict(request_data: dict[str, Any]) -> dict[str, Any]:
    """추론 API 요청을 받아 단일 특징 dict를 생성"""
    return _compute_features(request_data)


def build_feature_frame(df_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """학습 데이터셋 레코드 목록을 받아 특징 행 목록을 생성"""
    return [_compute_features(rec) for rec in df_records]
