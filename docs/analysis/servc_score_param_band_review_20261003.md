> 검토 대상: 커밋 832b43b6 (git diff main...HEAD, 파일 8개)
> 검토 범위: 적격심사 B·k 금액 구간 선택 구현
> 작성일: 2026-10-03
> 판정: pass (차단 결함 없음)

---

# 적격심사 B·k 금액 구간 선택 독립 검토

## 1. 검토 대상 확인

- `git log --oneline main..HEAD` 출력은 `832b43b6 feat: 적격심사 B·k 구간 선택 구현` 1건입니다.
- `git diff main...HEAD --stat` 출력은 파일 8건입니다.
- 현재 브랜치는 `kwanbum217/score-param-band-review`이며 HEAD에 검토 대상 커밋을 포함합니다.

## 2. 직접 실행 요약

### 2.1 지정 3파일 시험

- 명령: `uv run pytest tests/test_score_param_band_selection.py tests/test_evaluations_api.py tests/test_evaluation_rules_pre.py -q`
- 결과 요약줄: `157 passed in 3.79s`
- `python3 scripts/validate_agent_rules.py --quiet` 결과: `검증 통과: 21/21 건`

### 2.2 경계값 직접 실행

- B 경계 (`src/app/services/evaluation_rules.py:534`의 `Decimal("500000000")`):
  - `POST_20260526_ATTACH_01`, 추정가격 `499999999` → `70`, 근거 `ESTIMATED_PRICE`
  - `POST_20260526_ATTACH_01`, 추정가격 `500000000` → `60`, 근거 `ESTIMATED_PRICE`
  - `POST_20260526_ATTACH_01`, 추정가격 `500000001` → `60`, 근거 `ESTIMATED_PRICE`
  - 정확히 `500000000`은 이상 쪽(`60`)에 배정됩니다.
- k 경계 (공고 연도별 고시금액):
  - `POST_20260526_ATTACH_05`, 2024년 `219999999` → `4`, 경계 `220000000`
  - `POST_20260526_ATTACH_05`, 2024년 `220000000` → `2`, 경계 `220000000`
  - `POST_20260526_ATTACH_05`, 2025년 `229999999` → `4`, 경계 `230000000`
  - `POST_20260526_ATTACH_05`, 2025년 `230000000` → `2`, 경계 `230000000`
  - 2024년과 2025년의 k 경계가 `220000000`과 `230000000`으로 다르게 적용됩니다.
  - 정확히 고시금액과 같은 값은 이상 쪽(`2`)에 배정됩니다.
- 충돌 시 낙찰방법명 우선:
  - `POST_20260526_ATTACH_01`, 추정가격 `500000000`, 낙찰방법명 `추정가격 5억원 미만 2억원 이상인 용역` → `70`, 근거 `METHOD_NAME`, 경고 1건(`낙찰방법명 구간과 추정가격의 B 판정이 달라 낙찰방법명을 적용했습니다.`)
- 결측 유지:
  - `POST_20260526_ATTACH_01`, 추정가격 `None` → `max_price_score None`
  - `POST_20260526_ATTACH_05`, 추정가격 `100000000`, 공고일 `None` → `multiplier None`
  - `POST_20260526_ATTACH_05`, 추정가격 `None`, 낙찰방법명 `고시금액 이상` → `multiplier 2` (방법명만으로 선택 가능)

## 3. 항목별 판정

| 항목 | 답 | 근거 요약 |
| --- | --- | --- |
| selection_rules_correct | yes | 순서·경계·충돌·presmpt 전용·ATTACH_17 제외를 코드와 실행으로 확인했습니다. |
| notice_amount_single_source | yes | 표 단일원천과 연도별 값, 학습 특징 불변을 실행으로 확인했습니다. |
| declarations_and_fixed_values | yes | 조건부 배치는 축 조건부 규칙에만 있고 단일값 불변과 동시 선언 거부를 확인했습니다. |
| api_and_changed_tests | yes | 사용자 입력 우선과 근거 응답, 수정된 기존 시험 7건의 전제 정합을 확인했습니다. |

### 3.1 selection_rules_correct: yes

- 순서: `src/app/services/evaluation_rules.py:538-550`의 `choose`는 조건부가 없으면 고정값을 돌려주고, 조건부가 있으면 낙찰방법명 유무를 먼저 보고 다음으로 추정가격을 보며 둘 다 없으면 `None`을 돌려줍니다. `src/app/services/evaluation_rules.py:552-555`에서 B와 k에 같은 순서로 적용합니다.
- 경계 이상 쪽: `src/app/services/evaluation_rules.py:541`의 `price >= boundary`가 `True`이면 조건부 두 번째 값(`60` 또는 `2`)을 고릅니다. 2.2절 실행에서 `500000000 → 60`, 고시금액과 동액 → `2`를 확인했습니다.
- 충돌: `src/app/services/evaluation_rules.py:543-547`에서 방법명과 추정가격 판정이 다르면 경고를 남기고 방법명을 적용합니다. 2.2절 실행에서 경고 1건과 `METHOD_NAME` 선택을 확인했습니다.
- 방법명 파서: `src/app/services/evaluation_rules.py:530-533`의 정규식은 `5억원`과 `미만·이상`, `고시금액`과 `미만·이상`을 찾습니다. `tests/test_score_param_band_selection.py:72-80`의 합성 구간명 시험이 통과합니다.
- presmpt 전용: `src/app/api/v1/evaluations.py:220`은 `bid.presmpt_prce`만 읽고 `base_amount`를 읽지 않습니다. `tests/test_score_param_band_selection.py:162-170`은 `presmpt_prce None` + `base_amount 100000000`에서 선택하지 않음을 확정합니다. `src/app/api/v1/evaluations.py:354-366`의 `base_amount` 대체는 정량평가 구간(`select_quant_band`, 호출 위치 `src/app/api/v1/evaluations.py:1393`) 전용이며 B·k 선택 경로가 아닙니다.
- ATTACH_17 제외: `src/app/services/evaluation_rules.py:478-491`에서 PRE 세대의 B 조건부는 `{1, 2, 3, 4, 5, 7, 9, 11, 15}`라서 `17`을 포함하지 않습니다. 직접 조회에서 `PRE ATTACH_17`의 `max_price_score_by_500m`은 `None`이고 `multiplier_by_notice`는 `(4, 2)`이며, `PRE ATTACH_16`은 `B 70` 고정과 조건부 k를 유지합니다. `POST ATTACH_12·13·14`는 B·k·T 모두 `None`입니다.
- 재현 가능한 결함이 없으므로 `yes`입니다.

### 3.2 notice_amount_single_source: yes

- 단일원천: `src/ml/notice_amount.py:3-13`에만 연도표와 `notice_amount_for_year`가 있습니다. `src/ml/features.py:17`과 `src/app/services/evaluation_rules.py:19`는 각각 표와 함수를 가져다 씁니다. `src`에서 `220_000_000`·`230_000_000` 리터럴을 검색하면 고시금액 정의는 `src/ml/notice_amount.py`에만 있고, `src/app/services/result_coverage.py:60`의 같은 숫자는 다른 용도의 임계값 상수입니다.
- 연도값: 직접 실행에서 `2023 220000000`, `2024 220000000`, `2025 230000000`, `2026 230000000`, 그 밖(`2021`, `2022`, `2027`) `220000000`을 확인했습니다.
- 학습 특징 불변: `src/ml/features.py:96-97`의 `_notice_amount_for`는 같은 표와 기본값을 그대로 쓰므로 연도별 결과가 `notice_amount_for_year`와 모두 같습니다. 직접 실행에서 `2021-2027` 전 구간 일치를 확인했습니다. `tests/test_score_param_band_selection.py:173-183`도 `2023·2024 220000000`, `2025·2026 230000000`, `2021 220000000`을 고정합니다.
- 재현 가능한 결함이 없으므로 `yes`입니다.

### 3.3 declarations_and_fixed_values: yes

- 조건부 배치: 전 세대 직접 조회에서 B 조건부 `(70, 60)`은 B 단일값이 `None`인 축 조건부 규칙에만 있고, k 조건부 `(4, 2)`는 k 단일값이 `None`인 축 조건부 규칙에만 있습니다. PRE 세대는 B `{1, 2, 3, 4, 5, 7, 9, 11, 15}`, k `{5, 15, 16, 17}`이며 POST 세대는 B `{1, 2, 3, 4, 5, 7, 9, 11}`, k `{5}`입니다(`src/app/services/evaluation_rules.py:484-491`).
- 단일값 불변: `git diff main...HEAD -- src/app/services/evaluation_rules.py`에서 `Decimal` 선언값 변경은 조건부 `(70, 60)`·`(4, 2)` 추가뿐이며 기존 단일값(`70`, `4`, `2`, `0.375`, `5`, `85`, `88`) 변경이 없습니다. 별표 9 두 세대의 문구만 수요기관 지정형으로 바뀌고 값은 `T 85` 그대로입니다.
- 일반 띠: `POST ATTACH_12·13·14`는 직접 조회에서 B·k·T 모두 `None`이며 조건부도 없습니다.
- 동시 선언 거부: `src/app/services/evaluation_rules.py:60-64`의 `__post_init__`에서 B 단일값과 조건부, k 단일값과 조건부의 동시 선언을 각각 거부합니다. `tests/test_score_param_band_selection.py:121-125`의 두 거부 시험이 통과합니다.
- 재현 가능한 결함이 없으므로 `yes`입니다.

### 3.4 api_and_changed_tests: yes

- 선택 결과 사용: `src/app/api/v1/evaluations.py:220-234`의 `_score_table`은 `resolve_score_params` 결과를 선언값으로 쓰고, `src/app/api/v1/evaluations.py:243-254`에서 사용자 입력이 있으면 선언값 대신 사용자 값을 쓰고 다르면 덮어쓰기로 기록합니다. `tests/test_score_param_band_selection.py:145-159`는 선언 `70`에 사용자 `65`가 이기고 덮어쓰기 3건을 기록함을 확정합니다.
- 근거 응답: `src/app/api/v1/evaluations.py:271-301`은 선택값과 `max_price_score_basis`·`multiplier_basis`를 함께 싣고, `src/app/api/v1/evaluations.py:304-330`은 고정값·방법명·추정가격 비교문을 만듭니다. 직접 실행에서 고정값은 `규칙 고정값`, 방법명은 `낙찰방법명 구간 표기 → 70`, 추정가격은 `추정가격 400,000,000 < 500,000,000 → 70` 형식을 확인했습니다. `src/app/schemas/evaluations.py:336-347`에 두 근거 필드가 있습니다. 차단 응답(`src/app/api/v1/evaluations.py:944-973`)과 성공 응답(`src/app/api/v1/evaluations.py:1185-1249`) 모두 선택 경고와 근거를 전달합니다.
- 수정된 기존 시험의 정당성:
  - `test_registry_confirmed_k_and_t_fill_missing_user_fields`: 기본 공고(방법명 `5억원 미만`, 추정가격 `500000000`, 2026년)의 `ATTACH_01`은 B 조건부·k `5` 고정·T `85`이므로 B `70` 선택은 축 조건부 해소입니다. `max_price_score None → 70` 변경은 정당합니다.
  - `test_resolved_score_table_keeps_scenarios_and_floor_amounts`: 같은 공고에서 B 해소로 차단에서 성공으로 바뀝니다. 시나리오 점수·역산·보완 판정이 함께 계산되는 변경은 정당합니다.
  - `test_method_name_resolves_conditional_b_without_user_input`: 같은 공고의 방법명 `5억원 미만`으로 B `70`을 고릅니다. 이전 차단 전제(`max_price_score` 결측)는 해소되었으므로 정당합니다.
  - `test_pre_20230501_facility_uses_method_name_for_conditional_b`: 2023 세대 `ATTACH_01`도 B 조건부이므로 2023년 공고일과 같은 방법명으로 B `70`을 고르는 변경은 정당합니다.
  - `test_method_name_resolves_conditional_b_and_fixed_k`: 학술 `ATTACH_07`은 B 조건부·k `2` 고정이므로 방법명 `5억원 미만 고시금액 이상`으로 B `70`을 고르는 변경은 정당합니다.
  - `test_prediction_price_api_is_not_called_without_score_table`: 기본 공고가 해소되므로 `presmpt_prce None`을 두어 차단 경로를 유지합니다. `base_amount 500000000`이 남아도 선택하지 않으므로 presmpt 전용 규칙도 함께 검증합니다.
  - `test_snapshot_save_failure_does_not_block_response`: 같은 이유로 `presmpt_prce None`을 두어 차단 경로를 유지합니다. 변경은 차단 전제를 보존하므로 정당합니다.
- 재현 가능한 결함이 없으므로 `yes`입니다.

## 4. 차단 결함

- 없습니다.

## 5. 비차단 제안

- `src/app/services/evaluation_rules.py:82`의 주석이 고시금액 출처를 이전 위치(`src/ml/features.py:34-37`)로 적고 있습니다. 표가 `src/ml/notice_amount.py`로 moved 되었으므로 주석만 최신화하면 됩니다. 동작 변경이 필요하지 않습니다.
- `src/app/api/v1/evaluations.py:355`의 `_bid_estimated_price` 설명이 `5억원 구간 판정용`으로 적혀 있어 B 선택과 혼동할 수 있습니다. 해당 함수는 정량평가 구간 선택 전용이므로 설명에 용도를 한정하면 됩니다. 동작 변경이 필요하지 않습니다.
