# 공사·외자 투찰가 추천 차단 (2026-11-09)

> 작성일: 2026-11-09 | Task: `task_cnstwk_pred_guard_20261109`
> 결정: 사용자 A안 — 용역 집중 원칙 유지, 틀린 값 노출만 최소 조치로 차단

## 1. 배경과 원인

공사(Cnstwk)·외자(Frgcpt)는 `CATEGORY_DEFAULT_MODELS`(현재 Thng, Servc)에 전용 모델이 없는데도 후보 순회가 `v25` 로 대체해, 검증되지 않은 낙찰률·추천 금액이 화면·REST API·챗봇에 나갔다. `v25` 원시 출력은 -0.9~2.0 범위로 낙찰률 비율이 아니며, `_normalize_prediction_rate` 가 `DEFAULT_RATIO_MIN 0.75` / `DEFAULT_RATIO_MAX 1.05`(`src/ml/model_registry.py:68~69`)로 잘라 75%/105% 를 만든다. 원본 bid_box 와 같은 코드라 리팩터링 회귀는 아니고, 학습 코드가 없어 출력 척도의 기원은 확인할 수 없다.

## 2. 역검증 수치

출처: 코디네이터 실측 2026-11-09. 운영 DB 공사 낙찰 400건, `rl_openg_dt >= 2026-07-01`. 실제 낙찰률 평균 90.821, 표준편차 2.498.

| 방식 | MAE |
| --- | --- |
| v25 | 13.843 (예측의 93% 가 0.75/1.05 경계값, 상관 0.087) |
| v13_hybrid | 2.307 |
| ssh_hist_premium | 4.316 |
| quantum_leap_v25_pro | 2.180 |
| 단순 평균 예측 | 1.252 |
| 낙찰하한율 + 0.2 | 0.774 |

기존 모델 중 공사에 쓸 수 있는 것이 없고, 다른 모델로 바꾸는 것도 하지 않는다.

## 3. 변경 내용

- `src/ml/prediction_api.py`: `predict_optimal_price_with_provenance` 가 `CATEGORY_DEFAULT_MODELS` 에 없는 분야를 `UnsupportedPredictionCategoryError` 로 거부한다(후보 순회·특징 계산 전). 대체 후보에서 `v25` 를 빼고 `v13_hybrid` 는 유지했으며, 안내 문구는 `UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE` 한 곳에 둔다.
- `src/ml/model_registry.py`: 공용 판정 `prediction_supported_for_category` 추가.
- `src/app/services/bid_queries.py`: 상세 문맥에 `prediction_supported`·안내 문구 전달.
- `src/app/api/v1/predictions.py`: predict-price 와 특징 직접 입력 예측 모두 422 로 거부.
- `src/app/api/v1/evaluations.py`: 추천 경로가 422 를 안내 문구로 전달(5xx 없음).
- `src/app/services/tools/bid_prediction_tool.py`: 챗봇 도구가 예외 없이 안내를 반환.
- `src/tasks/automation_steps.py`: 표본이 미지원 분야면 partial_success 로 남김.
- `src/app/templates/bids/detail.html`: AI 투찰 금액 분석기에 추천 UI 대신 안내를 렌더.

## 4. 고친 기존 시험

| 시험 | 이유 |
| --- | --- |
| `test_ui_ssr.py::test_prediction_form_replaced_by_notice_without_model` | 공사 상세의 추천 카드 단언을 안내 렌더로 교체 |
| `test_ui_ssr.py::test_prediction_unavailable_notice_without_amount` | 외자는 모델 부재 안내가 우선이므로 렌더 단언 교체 |
| `test_prediction_provenance.py` 대체 기대 4건 | `v25` 제거로 `FALLBACK` 상수를 `v13_hybrid` 로 변경 |
| `test_nonprearranged_routing.py::test_tool_provenance_actual_model_on_fallback` | 같은 이유로 `FALLBACK` 상수를 `v13_hybrid` 로 변경 |

용역(Servc) 경로 보존은 `test_ui_ssr.py::test_prediction_form_enabled_for_supported_category` 로 고정했다.

## 5. 남은 과제

공사·외자 전용 모델은 용역 집중 원칙에 따라 보류한다. 재개 시 공사 낙찰률 실측 분포와 낙찰하한율+0.2 기준선(MAE 0.774)을 먼저 넘는지 확인해야 한다.
