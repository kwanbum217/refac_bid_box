# 공고 상세 웹 피드백 반영 (2026-11-17)

> 작성일: 2026-11-17
> 대상: `src/app/templates/bids/detail.html`
> 정본 사양: `.orca/capsules/task_fb_detail_20261117/capsule.yaml`

---

## 1. 요약

사용자 웹 피드백 5건을 공고 상세 화면에 반영했습니다. 화면 요소의 위치와 표시 방식만 바꾸었고, 추천 계산 API 계약과 서버 계산 로직은 바꾸지 않았습니다.

| 번호 | 요청 | 반영 |
| --- | --- | --- |
| 1 | 기초금액을 공고명 아래 좌측으로 이동 | 헤더 우측 정렬 블록을 없애고 공고명·기관·게시일 아래 좌측에 `text-2xl text-primary` 로 두었습니다. `bid.has_base_amount` 거짓 분기(`-`)는 유지합니다 |
| 2 | 분석 모델 블록 삭제 | `분석 모델` 라벨, `model-summary`, `model-fit`, `model-details`(선택·정보 패널 포함) 마크업과 모델 목록 요청·표시 스크립트를 지웠습니다 |
| 3 | 투찰가 추천 계산 블록을 카드 맨 아래로 이동 | 분석기 카드 본문의 마지막, 예측 결과와 근거 문단 다음으로 옮겼습니다. 2열 그리드는 없앴습니다 |
| 4 | 입찰 예상가를 가로 범위 그래프로 표시 | 예측 결과의 세 칸 위에 `price-range-chart` 를 두고 최저가~최상가 축에 AI 예측가·내 조건 추천가를 표식으로 찍었습니다 |
| 5 | 공고 기준 분석 카드의 적용 규칙 블록 삭제 | `적용 규칙` 제목과 `evaluation-rule`(규칙 ID·규칙명·판별 근거) 마크업, 표시 스크립트를 지웠습니다. `contract-regime-range` 와 `negotiation-distribution` 은 남깁니다 |

`일반용역 적격심사만 지원` 고정 문구는 `detail.html` 과 `src/app` 전체에 남아 있지 않습니다(커밋 `7e86ed19` 에서 이미 삭제, 이번에 시험으로 고정).

---

## 2. 상세 변경

### 2.1 기초금액

`src/app/templates/bids/detail.html:77` 부근

- 헤더 바깥 `flex ... justify-between` 래퍼를 없애고 좌측 블록 하나로 정리했습니다.
- 메타 줄(기관·게시일) 아래 `mt-4` 블록에 `기초금액` 라벨과 금액을 둡니다.
- 금액이 없으면 같은 자리에서 `-` 를 보여 줍니다.

### 2.2 분석 모델 블록 삭제

- 마크업: `분석 모델` 라벨, 두 열 그리드, `model-summary`, `model-fit`, `model-details`, `selected-model`, `model-info-panel`, `model-desc`, `model-tags`, `model-metrics` 를 제거했습니다.
- 스크립트: `loadModels`, `updateModelInfo`, `buildModelSummary`, `buildModelFit`, `buildModelDescription`, `renderModelTags`, `renderModelMetrics`, `modelTrainingDate`, `formatTrainingRows`, `formatFeatureList`, `labelCategory`, `modelCategoryLabels`, `modelCategoryText`, `modelVersionLabel`, `numericMetricValue`, `$('#selected-model').change` 처리기를 제거했습니다.
- 추천 요청 payload 는 `selected_model: null` 을 보냅니다. 서버는 `src/app/api/v1/predictions.py:618` 의 `payload.selected_model or _default_model_for_bid(bid)` 로 공고 분야 기본 모델을 고릅니다. `src/app/api/v1/evaluations.py:2477` 도 같은 요청을 그대로 위임합니다.
- 모델 목록 조회 결과는 다른 기능(지원 여부 판정 등)에 쓰이지 않아 요청 자체를 지웠습니다. 지원 여부는 서버가 렌더한 `prediction_supported` 값을 그대로 씁니다.

### 2.3 투찰가 추천 계산 이동

분석기 카드 본문(`p-6 space-y-6`) 순서는 다음과 같습니다.

1. 회원 정량 원자료 없음 안내
2. 계산 차단 안내
3. 예측 결과(범위 그래프, 세 칸, 내 조건 추천가, 경고, 근거 문단)
4. 투찰가 추천 계산(`recommend-status`, `recommend-loading`, `recommend-unavailable`)

요소 id 와 스크립트 동작은 바꾸지 않았습니다.

### 2.4 입찰 예상가 범위 그래프

- 마크업: `#price-range-chart` 안에 축(`#price-range-track`)과 표식 컨테이너(`#price-range-markers`)를 둡니다. 라이브러리 없이 `div` 와 `left` 백분율 절대 위치로 그립니다.
- 위치 계산: `priceRangePositions(min, optimal, max, member)` 순수 함수가 `0~100` 으로 자른 위치를 돌려줍니다.
  - 최저가·최상가가 있으면 축을 긋고 최저가 0%, 최상가 100%, AI 예측가·내 조건 추천가는 비율 위치에 둡니다.
  - 최저가와 최상가가 같으면 0 나누기 없이 표식이 가운데에 겹칩니다.
  - 최저가·최상가가 없으면 축 없이 AI 예측가 한 점만 가운데에 둡니다.
- 갱신 지점: 세 칸 숫자를 채우는 `renderRecommendAmounts` 에서 `renderPriceRangeChart(data, boundsReady)` 를 호출합니다. 재계산 경로가 하나이므로 숫자와 그래프가 어긋나지 않습니다.
- 기존 세 칸(`res-min-price`, `res-optimal-price`, `res-max-price`)과 금액 설명 팝업(`data-price-help`)은 그대로 둡니다.

### 2.5 적용 규칙 블록 삭제

- `적용 규칙` 제목과 `evaluation-rule` 블록을 지웠습니다.
- 스크립트의 `$('#evaluation-rule')` 표시·숨김 처리와 규칙 ID·규칙명·판별 근거를 채우던 분기를 지웠습니다.
- `contract-regime-range`(예정가격 변동 범위)와 `negotiation-distribution`(과거 낙찰률 실측 분포)은 남겼습니다.

---

## 3. 시험

### 3.1 추가

| 파일 | 내용 |
| --- | --- |
| `tests/test_bid_detail_feedback_20261117.py` | 헤더 좌측 기초금액(금액 있음·없음), 모델 블록 삭제, 추천 계산 블록 순서, 범위 그래프 마크업·갱신 경로, 규칙 블록 삭제, 고정 문구 부재, `priceRangePositions` 경계 4건 |

`priceRangePositions` 경계 시험은 템플릿에서 함수를 그대로 떼어 node 로 실행합니다. node 가 없는 환경에서는 건너뛰도록 두었습니다(이 워크트리와 CI 프런트 단계에는 node 22 가 있습니다).

### 3.2 고친 기존 시험

| 파일 | 고친 시험 | 이유 |
| --- | --- | --- |
| `tests/test_bid_detail_model_card_ui.py` | 파일 전체 재작성(`test_model_card_is_removed`, `test_model_loading_script_is_removed`, `test_server_chooses_default_model`, `test_default_view_excludes_developer_details`) | 모델 카드 자체가 삭제되어 기존 6건이 지운 요소를 단언했습니다. 삭제 상태를 고정하는 회귀로 바꿨습니다 |
| `tests/test_evaluation_ui.py` | `test_rule_display_section_removed`(기존 `test_rule_display_section`), `test_ai_prediction_section_reused_for_three_amounts`, `test_schema_fields_covered` | 규칙 표시 요소와 `selected-model` 이 사라졌습니다. 스키마 필드 검사는 그대로 두고 템플릿 표시 요소 검사에서 규칙 3건만 뺐습니다 |
| `tests/test_ui_ssr.py` | `test_bid_detail_places_base_amount_below_notice_name` 추가 | 기초금액이 헤더 좌측 블록 안에 있는지 확인 |
| `tests/test_bid_detail_recommend_ui.py` | `test_detail_shows_price_range_chart` 추가 | 범위 그래프 위치와 갱신 경로 확인 |
| `tests/test_predictions_api.py` | `test_predict_price_treats_explicit_null_selected_model_as_default` 추가 | 화면이 보내는 `selected_model: null` 이 분야 기본 모델로 처리되는지 확인 |
| `tests/test_evaluations_api.py` | `test_analyze_passes_null_selected_model_through` 추가 | 분석 API 가 null 모델을 그대로 위임하는지 확인 |

### 3.3 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_bid_detail_feedback_20261117.py tests/test_bid_detail_recommend_ui.py tests/test_ui_ssr.py tests/test_evaluations_api.py tests/test_predictions_api.py -q` | 148 passed, 1 skipped |
| `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `npm run build:css` | `src/app/static/css/tailwind.css` 재생성, 두 번 실행해도 동일 |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |

---

## 4. 변경 파일

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `src/app/templates/bids/detail.html` | 수정 | 피드백 5건 반영 |
| `src/app/static/css/tailwind.css` | 재생성 | 새 유틸리티(`mx-4`, `top-6` 등) 반영 |
| `tests/test_bid_detail_feedback_20261117.py` | 추가 | 이번 피드백 전용 회귀 시험 |
| `tests/test_bid_detail_recommend_ui.py` | 수정 | 범위 그래프 시험 추가 |
| `tests/test_ui_ssr.py` | 수정 | 헤더 좌측 기초금액 시험 추가 |
| `tests/test_predictions_api.py` | 수정 | `selected_model: null` 기본 모델 처리 시험 추가 |
| `tests/test_evaluations_api.py` | 수정 | null 모델 위임 시험 추가 |
| `tests/test_bid_detail_model_card_ui.py` | 수정(범위 밖 승인) | 삭제된 모델 카드를 단언하던 6건을 삭제 상태 고정 회귀로 교체 |
| `tests/test_evaluation_ui.py` | 수정(범위 밖 승인) | 규칙 표시 블록 단언을 삭제 상태 확인으로 교체, `selected-model` 단언 제거 |
| `docs/analysis/web_feedback_detail_20261117.md` | 추가 | 이 보고서 |

---

## 5. 주의 사항

- `tests/test_bid_detail_model_card_ui.py` 와 `tests/test_evaluation_ui.py` 는 당초 `allowed_write_files` 밖이었습니다. 지운 요소를 단언해 전량 시험이 9건 실패하므로 코디네이터 승인을 받아 `allowed_write_files` 에 추가한 뒤 고쳤습니다. 수정은 지운 모델 카드·적용 규칙 단언을 새 구조에 맞게 바꾸는 최소 범위이며, `contract-regime-range`, `negotiation-distribution`, 차단 안내, 경고 목록, 하한율 표시처럼 남겨야 할 요소를 검사하는 단언은 그대로 두었습니다.
- `npm ci` 는 이 환경의 `omit=dev` 설정 때문에 dev 의존성을 설치하지 않습니다. CSS 빌드는 `npm ci --include=dev` 로 도구를 설치한 뒤 실행했습니다.
- 운영 Docker·DB·Redis 는 건드리지 않았고 브라우저 확인은 하지 않았습니다.
