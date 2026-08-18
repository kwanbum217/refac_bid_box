import logging
import time
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)
latency_logger = logging.getLogger("uvicorn.error")

# model_registry.py 에서 로드 시점에 주입받는 런타임 종속성 (순환 import 방지)
ModelRegistry = None
_resolve_model_id = None
_preferred_model_for_features = None
_prepare_full_frame = None
_normalize_prediction_rate = None


class PriceDecisionMethod(StrEnum):
    MULTI = "복수예가"
    SINGLE = "단일예가"
    NON_PREARNG = "비예가"
    MISSING = "Missing"
    UNKNOWN = "Unknown"


def classify_price_decision_method(raw_data: dict) -> PriceDecisionMethod:
    """raw_data.prearngPrceDcsnMthdNm 기반으로 예가 유형을 분류한다.

    세 경로(API, 챗봇 도구, 기본 모델 선택)가 동일한 판정을 사용하도록
    이 함수 한 곳에서 판정한다.

    Args:
        raw_data: 공고 raw_data JSON 딕셔너리 또는 특징 딕셔너리.
            ``prearngPrceDcsnMthdNm`` 또는 ``prearng_mthd`` 키를 읽는다.

    Returns:
        PriceDecisionMethod

    판정 근거:
        - ``"복수예가"`` 가 포함되면 복수예가
        - ``"단일예가"`` 가 포함되면 단일예가
        - 명시적 비예가 (``"없음"``, ``"비예가"``) -> 비예가
        - 키 부재 또는 빈 문자열 -> Missing
        - 그 외 인식 불가 값 -> Unknown (로그에 원값 기록)

    제도적 근거:
        비예가 공고는 예정가격을 작성하지 않는 제도이므로 낙찰률(= 낙찰금액 /
        예정가격)의 분모가 존재하지 않는다. 따라서 낙찰률 기반 투찰가 산출이
        제도적으로 불가하다.
        원인 규명: docs/design/servc_nonprearng_population_cause_20260812.md
    """
    # raw_data JSON 키와 학습 프레임 키를 모두 지원한다.
    value = raw_data.get("prearngPrceDcsnMthdNm")
    if value is None:
        value = raw_data.get("prearng_mthd")

    if value is None:
        return PriceDecisionMethod.MISSING

    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            logger.warning("prearngPrceDcsnMthdNm 파싱 실패: type=%s", type(value).__name__)
            return PriceDecisionMethod.UNKNOWN

    normalized = value.strip()

    if not normalized:
        return PriceDecisionMethod.MISSING
    if normalized == "없음" or "비예가" in normalized:
        return PriceDecisionMethod.NON_PREARNG
    if "복수예가" in normalized:
        return PriceDecisionMethod.MULTI
    if "단일예가" in normalized:
        return PriceDecisionMethod.SINGLE

    # 인식 불가 값: 임의로 차단하지 않되 Unknown 으로 안전하게 분류한다.
    logger.warning("prearngPrceDcsnMthdNm 인식 불가 값 -> Unknown 으로 분류")
    return PriceDecisionMethod.UNKNOWN


@dataclass(frozen=True)
class PredictionOutcome:
    """점 추정과 그 값을 실제로 낸 모델을 함께 담습니다.

    후보 순회는 요청 모델이 실패해도 다른 모델로 답을 냅니다. 값만 돌려주면
    호출부는 어느 모델이 답했는지 알 수 없어 모델명, 예측 구간, 로그가 전부
    답하지 않은 모델을 가리키게 됩니다. 그 은폐를 막는 것이 이 타입입니다.
    """

    predicted_rate: float
    requested_model: str
    actual_model: str
    fallback_used: bool
    fallback_reason: str | None = None


def predict_interval(model_id, features_dict):
    """예측 구간 (하단%, 상단%, 명목 피복률) 을 돌려줍니다. 없으면 None 입니다.

    점 추정과 달리 구간은 선택 기능입니다. 구 모델은 분위 아티팩트가 없어
    None 이 나오며, 호출부는 그 경우 구간 없이 응답해야 합니다.
    """
    wrapper = ModelRegistry.get_model(_resolve_model_id(model_id))
    if wrapper is None or not hasattr(wrapper, "predict_interval"):
        return None
    try:
        bounds = wrapper.predict_interval(_prepare_full_frame(features_dict))
    except Exception as exc:
        logger.warning("구간 산출 실패 (%s): %s", model_id, exc)
        return None
    # 구간은 부가 정보입니다. 형태가 어긋나면 점 추정까지 막지 않고 조용히 뺍니다.
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        return None
    try:
        low, high = (_normalize_prediction_rate(value) * 100 for value in bounds)
        coverage = (wrapper.metadata.get("interval") or {}).get("target_coverage")
    except (TypeError, ValueError) as exc:
        logger.warning("구간 값이 비정상입니다 (%s): %s", model_id, exc)
        return None
    return low, high, float(coverage) if coverage is not None else None


def predict_optimal_price_with_provenance(
    model_id, features_dict, full_map=None
) -> PredictionOutcome:
    """점 추정과 실제 사용 모델을 함께 돌려줍니다.

    응답의 모델명과 예측 구간은 반드시 `actual_model` 을 기준으로 계산해야
    합니다. 요청 모델을 그대로 쓰면 점 추정과 구간이 서로 다른 모델에서 나옵니다.

    full_map 은 호출부가 이미 구축한 전체 특징 맵입니다. 넘기면 후보 순회
    전체가 같은 맵을 재사용해 요청당 구축 횟수가 1회로 줄어듭니다.
    """
    requested_id = _resolve_model_id(model_id or _preferred_model_for_features(features_dict))
    preferred_id = _preferred_model_for_features(features_dict)
    candidate_ids = []
    for candidate in (requested_id, preferred_id, "v25", "v13_hybrid"):
        if candidate not in candidate_ids:
            candidate_ids.append(candidate)

    last_error = None
    failures: list[str] = []
    for candidate_id in candidate_ids:
        wrapper = ModelRegistry.get_model(candidate_id)
        if not wrapper:
            failures.append(f"{candidate_id}: 미등록")
            continue

        try:
            call_start = time.perf_counter()
            call_cpu_start = time.thread_time()
            custom_df = wrapper.run_preprocess(features_dict)
            df = (
                custom_df
                if custom_df is not None
                else _prepare_full_frame(features_dict, full_map=full_map)
            )
            raw_prediction = wrapper.predict(df)
            call_wall_ms = (time.perf_counter() - call_start) * 1000.0
            call_cpu_ms = (time.thread_time() - call_cpu_start) * 1000.0
            latency_logger.info(
                "model_call=model_id=%s, status=success, wall_ms=%.2f, thread_cpu_ms=%.2f",
                candidate_id,
                call_wall_ms,
                call_cpu_ms,
            )
            predicted_rate = float(_normalize_prediction_rate(raw_prediction))
        except Exception as exc:
            call_wall_ms = (time.perf_counter() - call_start) * 1000.0
            call_cpu_ms = (time.thread_time() - call_cpu_start) * 1000.0
            latency_logger.info(
                "model_call=model_id=%s, status=error, wall_ms=%.2f, thread_cpu_ms=%.2f, error_type=%s",
                candidate_id,
                call_wall_ms,
                call_cpu_ms,
                type(exc).__name__,
            )
            last_error = exc
            failures.append(f"{candidate_id}: {type(exc).__name__}: {exc}")
            logger.warning("모델 '%s' 추론 실패: %s", candidate_id, exc)
            continue

        fallback_used = candidate_id != requested_id
        fallback_reason = "; ".join(failures) if fallback_used else None
        if fallback_used:
            logger.warning(
                "요청 모델 '%s' 대신 '%s' 로 예측했습니다. 사유: %s",
                requested_id,
                candidate_id,
                fallback_reason,
            )
        return PredictionOutcome(
            predicted_rate=predicted_rate,
            requested_model=requested_id,
            actual_model=candidate_id,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    if last_error:
        raise last_error
    raise ValueError(f"모델 '{requested_id}'을 찾을 수 없습니다. (후보: {'; '.join(failures)})")


def predict_optimal_price(model_id, features_dict, full_map=None):
    """점 추정만 돌려주는 기존 계약입니다.

    출처가 필요한 호출부는 `predict_optimal_price_with_provenance` 를 쓰십시오.
    이 얇은 래퍼를 남기는 이유는 float 를 그대로 pandas 프레임이나 문자열
    포매팅에 넣는 호출부가 여럿 있어, 반환형을 바꾸면 그쪽 동작이 조용히
    달라질 수 있기 때문입니다. full_map 은 provenance 로 그대로 전달됩니다.
    """
    return predict_optimal_price_with_provenance(
        model_id, features_dict, full_map=full_map
    ).predicted_rate


def predict_optimal_price_batch(model_id, features_dicts, full_maps=None):
    """동일한 Joblib 모델에 대한 요청 묶음을 한 번에 추론합니다.

    이 함수는 predictor 의 짧은 마이크로배치 전용입니다. 모델 호출이
    배치를 지원하지 않거나 요청 모델이 서로 다르면 호출부가 기존 단건
    provenance 경로로 되돌아가므로 fallback 의미와 응답 계약을 바꾸지 않습니다.
    """
    if not features_dicts:
        return []
    requested_ids = [
        _resolve_model_id(model_id or _preferred_model_for_features(item))
        for item in features_dicts
    ]
    if len(set(requested_ids)) != 1:
        raise ValueError("배치 요청의 모델 식별자가 서로 다릅니다.")
    requested_id = requested_ids[0]
    preferred_ids = [_preferred_model_for_features(item) for item in features_dicts]
    if len(set(preferred_ids)) != 1 or preferred_ids[0] != requested_id:
        raise ValueError("배치 요청의 기본 모델이 서로 다릅니다.")
    wrapper = ModelRegistry.get_model(requested_id)
    if wrapper is None or not hasattr(wrapper, "predict_batch"):
        raise ValueError(f"모델 '{requested_id}'이 배치 추론을 지원하지 않습니다.")
    maps = full_maps or [None] * len(features_dicts)
    frames = [
        _prepare_full_frame(features, full_map=full_map)
        for features, full_map in zip(features_dicts, maps, strict=True)
    ]
    call_start = time.perf_counter()
    call_cpu_start = time.thread_time()
    raw_predictions = wrapper.predict_batch(frames)
    latency_logger.info(
        "model_call=model_id=%s, status=success, batch_size=%d, wall_ms=%.2f, thread_cpu_ms=%.2f",
        requested_id,
        len(frames),
        (time.perf_counter() - call_start) * 1000.0,
        (time.thread_time() - call_cpu_start) * 1000.0,
    )
    return [
        PredictionOutcome(
            predicted_rate=float(_normalize_prediction_rate(raw_prediction)),
            requested_model=requested_id,
            actual_model=requested_id,
            fallback_used=False,
            fallback_reason=None,
        )
        for raw_prediction in raw_predictions
    ]
