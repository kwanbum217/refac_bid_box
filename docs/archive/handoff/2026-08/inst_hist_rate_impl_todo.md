> **작성일**: 2026-08-02
> **갱신일**: 2026-08-05
> **버전**: v0.2.0
> **상태**: 구현 완료. 학습·추론 경로에 연결됨. 잔여 TODO 없음

# 기관별 낙찰률 이력(inst_hist_rate) 구현 기록

## 배경

`inst_hist_rate` 는 낙찰률 예측의 실질 신호입니다. 이 값 하나만으로 용역 773,045 행에서 R2 0.33 이 나오며, 모델에 넣으면 전체 R2 가 0.026 에서 0.358 로, RMSE 는 4.61 에서 3.75 로 개선됩니다(2026-08-02 실측).

이 문서는 원래 `DEFAULT_INST_RATE(0.925)` 상수를 실제 기관 이력으로 대체하기 위한 TODO 목록이었습니다. 구현이 끝났으므로 결정 사항과 근거를 남기는 기록으로 전환합니다.

---

## 구현 결과 요약

| 원 TODO | 구현 위치 | 결정 내용 |
| --- | --- | --- |
| TODO-1 기본값 | `src/ml/institution_history.py:38` `_default_institution_rate` | 카테고리별 실측 평균. Thng 0.9132 / Servc 0.9011 / Cnstwk 0.8859 / 그 외 0.9001 |
| TODO-2 기관명 | `src/ml/institution_history.py:66` `_resolve_institution_name` | 수요기관(`dminstt_nm`) 우선, `order_institution`·`ntce_instt_nm` 순 폴백. 연속 공백 정규화, 플레이스홀더("각 수요기관", "조달청" 등) 제외 |
| TODO-3 카테고리 | `src/ml/institution_history.py:85` `_resolve_category` | 동일 카테고리 필터. 집계 표 키가 (기관명, 카테고리) 이며 표본 부족 시 카테고리 기본값 |
| TODO-4 기준 시점 | `src/ml/institution_history.py:91` `_resolve_reference_date` | 개찰일(`openg_dt`) 우선, 입찰마감일·공고일 순 폴백. 기준 시점 이전 결과만 사용 |
| TODO-5 DB 쿼리 | `src/ml/institution_history.py:112` `calculate_institution_win_rate` | 1년 윈도우, 최소 표본 5건, 낙찰률 0 초과 100 미만 이상치 제외, 퍼센트 → 비율 변환 |

---

## 성능 제약 해소

원 문서는 행당 2쿼리(COUNT + AVG) 기준 150ms/행, 용역 773,045 행이면 약 32시간이라는 제약을 남겼습니다. 경로를 둘로 나눠 해소했습니다.

| 경로 | 함수 | 방식 | 실측 |
| --- | --- | --- | --- |
| 학습 | `attach_institution_history` | pandas 로 프레임 전체를 한 번에. 개찰일 정렬 후 `shift(1).expanding().mean()` | 773,045 행 3.2초 |
| 추론 | `lookup_institution_history` | 사전 집계 표 `institution_win_rate_stats` 를 유니크 키로 조회. 표에 없을 때만 실시간 집계로 폴백 | 조회 1회 |

사전 집계 표는 `rebuild_institution_stats`(`src/ml/institution_history.py:251`)가 통째로 다시 만들며, `src/tasks/scheduled_tasks.py:84` 에서 주기 실행됩니다.

---

## 미래 정보 누수 방지

학습·추론 양쪽 모두 **기준 시점 이전의 낙찰 결과만** 사용합니다.

- 학습: `shift(1)` 로 자기 자신과 미래 행을 제외한 뒤 누적 평균. 정렬은 안정 정렬(mergesort)이라 개찰일 동률 행의 원래 순서가 유지되고, 날짜 파싱 실패 행은 맨 앞에 두어 뒤쪽 행의 이력을 오염시키지 않습니다.
- 추론: `rl_openg_dt < reference_date` 조건으로 기준일 이후 결과를 배제합니다.

학습에서 미래를 보면 검증 지표가 부풀고, 운영에는 존재하지 않는 정보라 실제 성능이 무너집니다.

---

## 윈도우·표본 기준

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 조회 윈도우 | 365일 (추론 실시간 집계) | 용역 재발주 주기 중앙값 358일 |
| 최소 표본 수 | 5건 | 표본 한둘의 평균은 잡음이라 오히려 성능을 떨어뜨림. 미만이면 카테고리 기본값 |
| 이상치 제외(추론) | 0 초과 100 미만 | 명백한 데이터 오류값 배제 |
| 이상치 제외(학습·집계) | 50.0 ~ 120.0 | `VALID_RATE_MIN` / `VALID_RATE_MAX`. 학습 프레임과 집계 표가 같은 기준 |

---

## train/serve 단일화 (AGENTS.md 6항)

정의는 하나이고 경로만 둘입니다. 양쪽 모두 "기준 시점 이전 같은 기관·카테고리의 낙찰률 평균" 입니다.

| 지점 | 파일 | 내용 |
| --- | --- | --- |
| 학습 주입 | `src/ml/trainer.py:523` | `attach_institution_history(df_raw)` 를 `build_feature_frame` 앞에서 호출 |
| 특징 산출 | `src/ml/features.py:223` | 프레임에 값이 있으면 사용, 없으면 `lookup_institution_history` 로 조회 |
| 표본 수 | `src/ml/features.py:237` | `lookup_institution_sample_count` 로 조회. 폴백이 없던 동안 서빙이 항상 0 을 넘기던 결함을 2026-08-05 에 수정 |
| 추론 진입 | `src/ml/predictor.py` `predict(session=...)` | session 을 빼면 상수로 떨어지므로 호출부가 반드시 전달 |
| API | `src/app/api/v1/predictions.py:170` | `predictor.predict(payload.model_dump(), session=db)` |

`features.py:221` 은 `or` 대신 `is None` 검사를 씁니다. `or` 를 쓰면 값 0.0 이 falsy 로 걸려 조회로 새어 나갑니다.

---

## 검증

| 대상 | 위치 |
| --- | --- |
| 단위 테스트 | `tests/test_institution_history.py` — 기본값, 기관명 해석, 기준일 경계, 미래 결과 제외, 이상치 제외, 학습 주입 여부(`test_training_path_injects_real_history`), 추론 session 전달(`test_serving_path_receives_session`), 행 순서 보존 |
| 학습·추론 값 대조 | `scripts/verify_asof_history_parity.py` |
| 특징 전반 대조 | `scripts/audit_feature_parity_values.py`, `docs/design/servc_feature_parity_20260805.md` |

원 문서가 현재 상태를 고정한다고 적었던 `test_production_feature_path_still_uses_constant` 와 `test_train_and_serve_use_the_same_session_policy` 는 연결 작업과 함께 위 두 테스트로 교체되었습니다.

---

## 후속 작업 상태

- 학습 특징 확장, LightGBM/CatBoost 교체, K-Fold 교차 검증: 완료(`850c830`).
- 용역 모델 성능 고도화는 별도 작업으로 계속 진행 중입니다.
