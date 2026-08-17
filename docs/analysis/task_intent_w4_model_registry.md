# task_intent_w4_model_registry 분석 및 완료 보고서

> **작성일**: 2026-08-17  
> **태스크 ID**: task_31bc1beffc01 / task_intent_w4_model_registry  
> **런 ID**: run_b9c762c9f2b6  
> **디스패치 ID**: ctx_22c1429ac62a  

---

## 1. 개요

`src/ml/model_registry.py` (종전 1,091줄)를 동작 보존 원칙에 따라 기계적으로 분할하였습니다.
서빙 및 추론 경로의 18개 참조 파일과 기존 테스트의 `ModelRegistry` 패치 대상을 100% 보존하면서, 3개 모듈로 책임을 분리하고 상호 순환 참조(Circular Import)를 원천 차단했습니다.

---

## 2. 분할 내역 및 심볼 매핑

### 2.1 신규 모듈: `src/ml/model_wrappers.py` (514줄)
- **이동 클래스**:
  - `BaseModelWrapper`
  - `JoblibModelWrapper`
  - `KerasModelWrapper`
  - `V13HybridWrapper`
  - `EnsembleV25Wrapper`
  - `QuantumLeapRuleWrapper`
  - `HistPremiumEnsembleWrapper`
- **의존성 주입**: `_coerce_float`, `_apply_inference_thread_budget`, `_prepare_input_frame`을 `model_registry.py` 로드 시점에 주입받아 순환 import 제거.

### 2.2 신규 모듈: `src/ml/prediction_api.py` (266줄)
- **이동 심볼**:
  - `PriceDecisionMethod`
  - `classify_price_decision_method`
  - `PredictionOutcome`
  - `predict_interval`
  - `predict_optimal_price_with_provenance`
  - `predict_optimal_price`
  - `predict_optimal_price_batch`
- **의존성 주입**: `ModelRegistry`, `_resolve_model_id`, `_preferred_model_for_features`, `_prepare_full_frame`, `_normalize_prediction_rate`를 주입받아 순환 import 제거.

### 2.3 원본 모듈: `src/ml/model_registry.py` (400줄)
- **유지 항목**:
  - `ModelRegistry` 클래스 (테스트 patch 타깃 및 중앙 레지스트리)
  - 모듈 상수: `MODEL_FILES_ROOT`, `CATEGORY_DEFAULT_MODELS`, `MODEL_ALIASES`, `DEFAULT_RATIO_MIN`, `DEFAULT_RATIO_MAX`, `PROJECT_ROOT`
  - 헬퍼 함수: `_coerce_float`, `_apply_inference_thread_budget`, `_load_champion_metrics`, `_prepare_input_frame`, `_normalize_prediction_rate`, `_prepare_features`, `_prepare_full_frame`, `_resolve_model_id`, `_preferred_model_for_features`
- **재수출**: 분할된 모든 심볼을 원본에서 re-export하여 기존 import 경로 100% 보존.

---

## 3. 검증 결과

| 항목 | 기준 | 결과 | 상태 |
| --- | --- | --- | --- |
| 원본 모듈 줄 수 | <= 600줄 | 400줄 | 통과 |
| model_wrappers 줄 수 | <= 550줄 | 514줄 | 통과 |
| prediction_api 줄 수 | <= 550줄 | 266줄 | 통과 |
| 전체 테스트 | pytest 전량 통과 | 1,346 passed, 6 skipped | 통과 |
| 분할 전용 테스트 | symbol identity & AST | 8 passed (0.03s) | 통과 |
| 린터 검사 | ruff check . | 0 errors | 통과 |
| 규칙 정합성 | validate_agent_rules.py | 12/12 passed | 통과 |
| 순환 import 여부 | AST 파싱 검사 | model_registry 역참조 0건 | 통과 |
| 기존 테스트 수정 여부 | git diff --name-only | 기존 test 파일 수정 0건 | 통과 |
