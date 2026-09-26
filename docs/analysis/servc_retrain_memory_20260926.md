# 용역 재학습 메모리 축소 실측

> **작성일**: 2026-09-26
> **작성자**: Orca builder 워커 (task_8401ae1a8696)
> **기준 브랜치**: `kwanbum217/orca-m1`
> **측정 대상**: `ModelTrainer.for_category("Servc").train_and_register(df)` (표본 926,708 행 x 28 컬럼)
> **변경 파일**: `src/ml/trainer.py`, `src/ml/conformal.py`, `tests/test_trainer_memory.py`

---

## 1. 한 줄 요약

용역 재학습의 최대 RSS 를 **9.93 GiB 에서 3.92 GiB 로 60.5% 줄였고**, 선택 모델과 홀드아웃·CV 지표는 소수점 넷째 자리까지 동일하게 유지됐습니다. 컨테이너 몫 11.7 GiB 기준 사용률이 33.5% 로 떨어져 OOM 여유가 충분해졌습니다.

---

## 2. 측정 방법

| 항목 | 방법 |
| --- | --- |
| 전체 최대 RSS | 계약 명령 `/usr/bin/time -l uv run python scripts/retrain_servc_from_parquet.py --category Servc` 의 `maximum resident set size`. 변경 전 1 회, 변경 후 1 회를 같은 parquet 으로 측정 |
| 단계별 메모리 | 임시 프로브(커밋하지 않음)로 학습 단계 함수를 래퍼로 감싸 단계 출입 시점의 `resource.getrusage(RUSAGE_SELF).ru_maxrss` 스냅샷을 남김. 변경 전·후 동일 프로브 사용 |
| 동등성 검증 | 임시 스크립트(커밋하지 않음)로 100,000 행 표본에서 이전 코드 경로(전체 일괄 특징 구축)와 새 코드 경로(청크)의 `df_feat` 를 `assert_frame_equal(check_exact=True, check_dtype=True)` 로 비트 비교 |
| 지표 동일성 | 학습이 만든 `metadata.json` 을 변경 전후로 보존해 `model_type`, `metrics`, `cv_metrics`, `candidate_cv_metrics`, `candidate_holdout_metrics` 를 파이썬 `==` 로 대조 |

프로브와 동등성 검증 스크립트는 측정 후 삭제했고 수치만 여기에 남깁니다.

---

## 3. 전체 최대 RSS 대조

| 구분 | 변경 전 | 변경 후 | 차이 |
| --- | ---: | ---: | ---: |
| maximum resident set size | 10,658,004,992 B | 4,203,495,424 B | -6,454,509,568 B |
| 환산 (GiB) | **9.93 GiB** | **3.92 GiB** | **-6.01 GiB (60.5%)** |
| 학습 소요 시간 | 535 초 | 541 초 | +6 초 |
| 선택 모델 | lightgbm | lightgbm | 동일 |
| 컨테이너 몫 11.7 GiB 대비 | 84.8% | **33.5%** | |

권장 목표인 7 GiB 이하를 초과 달성했습니다.

---

## 4. 단계별 메모리 (프로브 스냅샷, GiB)

| 단계 | 변경 전 피크 | 변경 후 피크 |
| --- | ---: | ---: |
| 프로브 시작 | 0.09 | 0.09 |
| parquet 로드 직후 | 1.02 | 0.95 |
| `attach_institution_history` 종료 | 2.90 | 1.74 |
| `attach_repeat_history` 종료 | 4.92 | 3.08 |
| 특징 프레임 구축 종료 | **8.36** | **3.08** |
| 범주 수준 수집·범주 dtype 적용 종료 | **9.69** | **3.08** |
| 학습 단계(폴드·홀드아웃·전량 재적합·분위·기준분포 저장) 종료 | 9.69 | 3.29 |

변경 전에는 **최대 피크가 데이터 준비 단계에서 이미 형성**되고 학습 단계는 그 위에서 유지됐습니다. 컨테이너에서 OOM(관측 12.26 GiB)에 닿은 것은 준비 단계 피크 위에 학습 단계의 할당이 얹힌 결과입니다.

---

## 5. 원인과 대응

| 원인 (변경 전 프로브 근거) | 대응 | 위치 |
| --- | --- | --- |
| `to_dict(orient="records")` 행 dict 와 특징 dict 가 92 만 행 통째로 만들어져 `df_feat` 와 동시 존재 (피크 +3.44 GiB, 5.20 → 8.36 GiB) | 행 단위 특징 구축을 50,000 행 청크로 분할. `build_feature_frame` 은 행별로 독립적이라 결과가 같고 행 dict 동시 상주분이 5.4% 로 제한됨 | `trainer.py` `_build_feature_frame_chunked` |
| `collect_category_levels` 의 열별 문자열 사본과 `pd.DataFrame(features_list)` 생성이 겹침 (피크 +1.33 GiB, 8.36 → 9.69 GiB) | 범주 수준 수집도 청크 union 으로 분할. 청크 수준 집합의 합과 정렬은 전체 수집 목록과 같음 | `trainer.py` `_collect_category_levels_chunked` |
| 후보 모델 객체(ridge/lightgbm/catboost)가 `candidates` 에 학습 종료 후에도 남아 재적합·분위 학습까지 동시 상주 | 후보는 홀드아웃 평가 직후 반납하고 조기 종료가 고른 트리 수(`best_iteration`)만 보존. `_refit_on_full` 이 `selected` 대신 `best_iteration` 을 받도록 변경 | `trainer.py` 후보 루프 |
| 폴드 모델이 다음 폴드 재할당 시점까지 잔존 | 지표 수집 직후 `del` | `trainer.py` `_cross_validate_model` |
| 보정용 분위 모델이 배율 산정 후 잔존 | `del` | `conformal.py` `_train_quantile_models` |
| 정답과 정렬 기준을 특징 프레임 구축 이후에 꺼내 임시 참조 중첩 | 특징 구축 전에 선추출 | `trainer.py` `train_and_register` |

캡슐 금지 항목(float32 강제 변환, 표본 축소, 후보 제거, 하이퍼파라미터 변경, `features.py` 수정)은 사용하지 않았습니다. `src/ml/features.py` 는 전혀 바꾸지 않았습니다.

---

## 6. 지표 동일성 대조표

| 항목 | 변경 전 | 변경 후 | 판정 |
| --- | --- | --- | --- |
| `model_type` | lightgbm | lightgbm | 동일 |
| `metrics` | rmse 2.701 / mape 1.394 / r2 0.6832 | rmse 2.701 / mape 1.394 / r2 0.6832 | **동일** |
| `cv_metrics` | `avg_mape` 1.2755 포함 전체 | 동일 | **동일** |
| `candidate_cv_metrics` | 3 모델 전체 | 동일 | **동일** |
| `candidate_holdout_metrics` | 3 모델 전체 | 동일 | **동일** |
| `hyperparams` | Servc lightgbm 리프 255 | 동일 | 동일 |
| `category_levels` | 전체 | 동일 | 동일 |
| `interval` | 전체 | 동일 | 동일 |
| 폴드별 R2 (콘솔 출력) | `[0.5419, 0.6351, 0.6652, 0.67]` | `[0.5419, 0.6351, 0.6652, 0.67]` | 동일 |

100,000 행 표본의 임시 비교에서도 새 청크 경로의 `df_feat` 가 이전 일괄 경로와 dtype 포함 비트 동일했습니다.

---

## 7. 회귀 테스트와 검증

`tests/test_trainer_memory.py` 를 추가했습니다. 전량 재적합이 시작되는 시점에 후보·폴드 모델 객체가 이미 반납됨(`weakref` 추적), 청크 특징 프레임이 전체 일괄과 dtype 포함 동일함, 정답 없는 입력의 폴백 표본 수, 빈 입력과 청크 경계 행 수를 고정합니다.

| 검증 | 명령 | 결과 |
| --- | --- | --- |
| 관련 테스트 | `uv run pytest tests/test_trainer_memory.py tests/test_psi_drift_wiring.py tests/test_trainer_split.py tests/test_retrain_pipeline_e2e.py tests/test_retrain_category_guard.py -q` | 57 passed |
| 타입 검사 | `uv run mypy src` | no issues (109 files) |
| 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | 21/21 통과 |

---

## 8. 남은 원인

| 항목 | 내용 |
| --- | --- |
| `attach_institution_history` / `attach_repeat_history` 내부 | `df.copy()` 2 회와 정렬·그룹 중간 프레임이 남은 피크(3.08 GiB)의 지배 요인. 두 모듈은 이 Task 의 수정 범위 밖이며 attach 방식은 프레임 전체 정의라 청크로 쪼갤 수 없다 |
| 호출자 참조 | 스크립트 경로에서는 `main` 이 원본 parquet 프레임을 끝까지 붙잡아 원본이 학습 내내 잔존. 파이썬 참조 구조상 학습기가 해제할 수 없고, Docker worker 경로(`retrain_task`)에서 데이터셋 구축 호출부 설계로 함께 다뤄야 한다 |
| attach 단계 프로브 간 차이 | attach 두 단계는 변경이 없는 영역인데 프로브 간 내부 증가분(+3.90 GiB → +2.12 GiB)이 달랐다. allocator·시스템 상태 노이즈로 해석하며 계약 증명은 정본 명령의 전후 수치로 한다 |
