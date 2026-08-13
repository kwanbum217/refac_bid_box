# 낙찰가 예측 API P95 병목 감사 (2026-08-13)

> **작성일**: 2026-08-13
> **작성자**: Orca Dispatch ctx_2e4720d83066 / Task task_5c918f4b7f82
> **범위**: 읽기 전용 성능 감사. 벤치마크·학습·LLM/RAG 호출·코드 변경 없음
> **상태**: 진단 완료. 수정 미착수 (최소 수정 후보만 확정)
> **실측 출처**: warm sequential /predict 첫 요청 57ms 이후 11~14ms, concurrency=10 n=100 P50 166.2ms / P95 627.0ms, cold 포함 P95 1.93s

---

## 0. 결론부터

측정된 병목은 **단일 지점이 아니라 세 층위의 누적**입니다. 순차 웜에서도 11~14ms가
나오는 이유와, 동시성 10에서 P50 166.2ms / P95 627.0ms로 12~50배 붕괴하는 이유는
서로 다른 원인입니다.

| 순위 | 원인 | 영향 |
| --- | --- | --- |
| 1 | LightGBM/CatBoost 추론 스레드 미제한 (num_threads=None → 14코어 전부) | 순차 11~14ms의 상당분 + 동시성 시 스레드 폭주 (10 요청 × 14 스레드 = 140 스레드) |
| 2 | 요청당 특징 맵 3중 재구성 + 범주 dtype 변환 (GIL 바운드 Python/pandas) | 동시성 붕괴의 공동 원인. 순차 기준 3회 중복 계산 |
| 3 | 부팅 시 모델 이중 프리로드 (import 시 싱글톤 + lifespan 예열 재실행) | cold 포함 P95 1.93s의 직접 원인 후보 |

실운영 `/predict-price` 경로에는 여기에 DB 쿼리 3종(공고 PK, 기관 이력, 재발주 이력)
이 더해져, 분위 모델 지연 로드와 함께 실사용 꼬리 지연의 추가 후보입니다. 단,
측정된 벤치마크(`/predict`, category_code=Thng)에는 DB 쿼리가 하나도 없으므로
측정 수치 자체는 1~3번이 설명합니다.

---

## 1. 확정 사실 (증거 포함)

### 1.1 측정된 성능 (외부 실측, 재현 금지 상태)

| 구간 | 측정값 | 목표 |
| --- | ---: | ---: |
| warm sequential /predict 첫 요청 | 57ms | - |
| warm sequential /predict 이후 요청 | 11~14ms | - |
| concurrency=10, n=100 /predict | P50 166.2ms / P95 627.0ms | P95 100ms |
| cold 포함 (재시작 직후 구간 포함) | P95 1.93s | - |

순차 12ms 대비 동시성 10 P50 166.2ms는 **14배 증폭**, P95 627ms는 **52배 증폭**입니다.
단일 요청 지연보다 동시성 붕괴가 지배적입니다.

### 1.2 벤치마크가 실제로 태운 경로 (src/app/api/v1/predictions.py:200)

`scripts/benchmark_latency.py:206-218` 의 payload 는
`presumed_price / base_price / category_code="Thng"` 입니다. 이 입력이 태우는 경로는
다음과 같습니다.

| 단계 | 코드 위치 | 내용 |
| --- | --- | --- |
| sync 엔드포인트 | predictions.py:201 (`def`) | FastAPI/Starlette 스레드풀(AnyIO 기본 40)에서 실행. uvicorn 단일 워커 (docker inspect 확인) |
| 특징 1차 구축 | predictor.py:45 → features.py:424 `build_feature_dict` | `build_default_feature_map` 1회 (100+ 키, pandas/numpy 스칼라 연산) |
| 모델 선택 | model_registry.py:175 `_preferred_model_for_features` | category="Thng" → `quantum_leap_v25_pro` |
| 특징 2차 구축 | model_registry.py:885 `_prepare_full_frame` | `build_default_feature_map` 재호출 + DataFrame 1행 |
| 특징 3차 구축 | model_registry.py:298 `_prepare_input_frame` → features.py:355 `prepare_input_frame` | `build_default_feature_map` 재호출 + `apply_categorical_dtypes` (11개 범주 astype) |
| LGBM 추론 | model_registry.py:322 `JoblibModelWrapper.predict` | 단건 LGBM predict |

같은 특징 맵(100+ 키)을 **요청당 3회** 구축합니다. 이 payload 는 기관명·공고명이
없어 `lookup_institution_stats`(institution_history.py:411 빈 기관명 조기 반환)와
`lookup_repeat_history`(repeat_history.py:203 빈 키 조기 반환)가 모두 DB 쿼리 없이
기본값으로 끝납니다. **측정 구간에 DB 쿼리는 0건입니다.**

### 1.3 모델 실물 파라미터 (docker exec 읽기 전용 확인)

| 모델 | 파일 (컨테이너) | 크기 | 파라미터 |
| --- | --- | --- | --- |
| quantum_leap_v25_pro (Thng 기본, 벤치마크 대상) | model.bin | 3.66MB | LGBMRegressor, objective=huber, 600 trees, 63 leaves, 34 features, **num_threads=None** |
| quantum_leap_v25_pro 분위 | model_q10.bin / model_q90.bin | 3.57MB + 3.55MB | LGBMRegressor, **num_threads=None**. 지연 로드 |
| servc_institution_v1 (Servc 기본) | model.bin | 6.59MB | LGBMRegressor, objective=quantile, 261 trees, 255 leaves, **num_threads=None** |
| v25 | v25_lgbm_final.joblib / v25_cat_final.bin / model.bin | 0.76 + 0.27 + 0.05MB | LGBM 234 trees/31 leaves **num_threads=None**, CatBoost 234 iterations **thread_count=None** |
| v13_hybrid | model.bin | 37.3MB | joblib dict 번들 (LGBM 다수) |
| ssh_hist_premium | model.bin | 4.31MB | joblib dict 번들 |

- 컨테이너 CPU: **14코어**. `OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` 미설정.
- LightGBM 4.7.0, CatBoost 1.2.10. `num_threads=None` 은 LightGBM 기본값 0(OpenMP
  가용 코어 전부), CatBoost `thread_count=None` 도 전체 코어입니다.
- TensorFlow 미설치 (model_registry.py:38 방어 임포트, keras 모델 없음).
- 모델 로드 합계 약 **52.9MB** (3.66+6.59+4.31+37.3+0.76+0.27+0.05, 분위 모델 제외).

### 1.4 서버 구성

| 항목 | 값 |
| --- | --- |
| uvicorn | `python3 -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000` 단일 프로세스, `--workers` 없음 |
| 예측 엔드포인트 | 전부 sync `def` → AnyIO 스레드풀 (기본 40 스레드) |
| DB 엔진 | pool_size=10, max_overflow=20 (src/app/core/db.py:18) |
| 모델 프리로드 | 2회 실행됨 — ① `src/ml/predictor.py:76` 모듈 임포트 시 `SingletonPredictor.__init__` → `load_all_models()` 동기, ② `src/app/main.py:63` lifespan `_warm_predictor` → `asyncio.to_thread(load_all_models)` 재실행 |

### 1.5 DB 인덱스 현황 (predict-price 실운영 경로 관련, SHOW INDEX 확인)

| 쿼리 | 사용 인덱스 | 계획 |
| --- | --- | --- |
| 재발주 이력: `bid_results WHERE dminstt_nm=? AND category=? AND sucsf_bid_rate 50~120 ORDER BY rl_openg_dt DESC LIMIT 5000` | `bid_results_dminstt_nm_1b809760` (단일 컬럼) | **Using where; Using filesort**. `(dminstt_nm, category, rl_openg_dt)` 복합 인덱스 없음 |
| 기관 이력: `institution_win_rate_stats WHERE institution_name=? AND category=?` | `uq_inst_win_rate_scope` (복합 유니크) | const 조회, 저비용 |
| 공고: `bid_announcements WHERE id=?` | PRIMARY | 저비용 |

`bid_results` 340만 행, 기관별 Servc 이력 상위 3,200~4,765행. 재발주 쿼리는 기관
단위로 최대 5,000행을 filesort 로 읽어 들이고 파이썬 정규식(normalize_title)으로
매칭합니다(repeat_history.py:238). 대형 기관 요청에서 수십 ms 후보입니다.

---

## 2. 추론 (병목 원인 분석)

### 2.1 순차 웜 11~14ms 의 구성

벤치마크 경로에서 DB 쿼리가 없으므로 시간은 전부 Python/pandas 특징 구축과 LGBM
단건 추론에서 나옵니다. 구성원은 증거상 다음과 같습니다.

1. **LGBM 단건 predict 의 스레드 팀 오버헤드** (1.3절: num_threads=None → 14코어).
   단건(34 특징)에 14개 OpenMP 스레드 팀 생성·해체 비용은 스레드 풀 재사용이 없는
   반복 호출에서 밀리초 단위로 발생합니다. 600트리 huber 모델이므로 트리 순회
   자체는 수백 마이크로초입니다.
2. **특징 맵 3중 구축** (1.2절). 요청당 `build_default_feature_map` 3회, 각 회마다
   `pd.Timestamp` 변환, `np.sin/cos`, 100+ `_coerce_float`, `sem_0..31` 루프,
   `apply_categorical_dtypes` 의 DataFrame copy + 범주 astype. 순수 CPython + pandas
   스칼라 연산이라 순차에서는 수 ms.
3. FastAPI/httpx/Docker(macOS) 왕복 오버헤드 1~3ms.

### 2.2 동시성 10에서 14~52배 붕괴의 원인

1. **OpenMP 스레드 폭주(oversubscription)**: 동시 요청 10 × LGBM 스레드 팀 14 =
   논리 스레드 140개가 14코어에 몰립니다. context-switch 폭풍과 캐시 스래싱으로
   P50 166ms / P95 627ms 를 설명합니다.
2. **GIL 직렬화**: 특징 맵 3중 구축은 GIL 을 잡고 도는 Python/pandas 코드입니다.
   10개 스레드풀 스레드가 서로 GIL 을 뺏고 뺏기며, 순차 12ms 의 작업이 동시성
   10에서 P50 166ms 로 증폭되는 공동 원인입니다. LGBM 네이티브 추론은 GIL 을
   놓지만 준비·정리(pandas 프레임 구축, 결과 float 변환)는 GIL 안입니다.
3. 스레드풀 자체는 부족하지 않습니다 (기본 40, 요청 10).

### 2.3 cold 포함 P95 1.93s 의 원인 후보

1. **모델 이중 프리로드 경합** (1.4절): import 시점에 52.9MB 전체 로드가 끝난 뒤,
   lifespan `_warm_predictor` 가 **같은 `load_all_models` 를 한 번 더** 배경 스레드로
   실행합니다. uvicorn 은 lifespan yield 직후 요청을 받기 시작하므로, 재시작 직후
   첫 요청 구간은 두 번째 52.9MB 로드와 CPU/디스크/메모리를 경합합니다.
   v13_hybrid 37.3MB 단일 joblib 로드가 가장 큰 덩어리입니다.
2. 분위 모델(model_q10/q90)은 지연 로드라 첫 `/predict-price` 요청이 3.5MB × 2
   joblib 로드를 지불합니다 (벤치마크 `/predict` 경로와는 무관).

### 2.4 실운영 /predict-price 의 추가 꼬리 후보 (측정 범위 밖, 코드 증거)

1. 재발주 이력 쿼리: `dminstt_nm` 단일 인덱스 + filesort + 파이썬 5,000행 정규식
   매칭 (1.5절). 대형 기관에서 수십 ms.
2. 분위 모델 지연 로드 (첫 요청 한정 수백 ms 이상).
3. 특징 맵 3중 구축은 `/predict-price` 에도 동일하게 발생.

---

## 3. 최소 수정 후보 (의존성 추가 없음, 미착수)

수정 우선순위는 재측정 매트릭스(4절)로 검증하는 순서입니다. 각 후보는 1개의
측정 사실을 겨냥합니다.

### 후보 A: 추론 스레드 수 제한 (2.1-1, 2.2-1 겨냥)

| 항목 | 내용 |
| --- | --- |
| 방법 1 (권장) | 컨테이너 환경 변수 `OMP_NUM_THREADS=2` 추가 (docker-compose app 서비스). 코드 변경 없음. LightGBM/CatBoost 기본값(0)은 이 변수를 존중 |
| 방법 2 | 모델 로드 직후 `CatBoostRegressor.set_thread_count(2)` 호출. LGBM 은 `model.set_params(num_threads=2)` 후 `_Booster` 재구성 필요(직렬화된 booster 반영 여부 확인 필수) — 방법 1이 안전 |
| 위험 | 스레드 수 변경이 부동소수 합산 순서를 바꿀 수 있으나, 트리 합산은 순서 독립적이라 예측값 불변 가능성 높음. 승격 전 예측값 동등성 회귀(기존 응답 재현) 검증 필수 |
| 기대 | 단건 추론 오버헤드 감소(수 ms → sub-ms), 동시성 10에서 oversubscription 제거 |

### 후보 B: 요청당 특징 맵 1회 구축 (2.1-2, 2.2-2 겨냥)

| 항목 | 내용 |
| --- | --- |
| 내용 | `build_feature_dict` 결과(전체 맵)를 `predict_optimal_price_with_provenance` → `_prepare_full_frame` → `JoblibModelWrapper.predict` → `prepare_input_frame` 까지 재사용. 현재 3회 호출되는 `build_default_feature_map` 을 1회로 |
| 방법 | 이미 전체 맵인 dict 를 프레임으로 바로 변환하고, `prepare_input_frame` 의 defaults 재계산을 전달받은 값으로 대체. `announcement_feature_payload` 병합 위치(원본 키)는 유지 |
| 위험 | 낮음 (같은 함수, 같은 입력). 단 서로 다른 두 dict(요청 키 vs 전체 맵)의 병합 의미가 변하지 않도록 회귀 테스트 |
| 기대 | 순차 11~14ms 의 Python 부분 1/3 수준으로, GIL 점유 시간 감소 → 동시성 붕괴 완화 |

### 후보 C: 모델 프리로드 단일화 (2.3-1 겨냥)

| 항목 | 내용 |
| --- | --- |
| 내용 | import 시 `SingletonPredictor()` 로드와 lifespan `_warm_predictor` 로드 중 하나로 통일. 예: `_warm_predictor` 진입 시 `ModelRegistry.available_models()` 가 비었을 때만 로드 (available_models 는 os.listdir 이라 저비용) |
| 위험 | 낮음. 단 import 시 로드를 제거하면 첫 요청이 로드 비용을 지불하므로, 로드 시점은 재시작 직후 첫 요청 지연과 부팅 시간 트레이드오프로 결정 |
| 기대 | cold 포함 P95 1.93s 의 주 원인(부팅 직후 이중 로드 경합) 제거 |

### 후보 D: /predict-price 첫 요청 분위 모델 프리로드 (2.3-2 겨냥, 선택)

| 항목 | 내용 |
| --- | --- |
| 내용 | `_load_quantile_models` 지연 로드를 프리로드(부팅 후 1회)로 변경하거나 유지하되, 첫 `/predict-price` 요청 지연을 재측정으로 확인 |
| 위험 | 부팅 로드량 증가(7.1MB). 요청 빈도가 낮으면 지연 로드 유지가 유리 |
| 기대 | 첫 `/predict-price` 요청의 꼬리 제거 |

### 후보 E: 재발주 이력 쿼리 인덱스 (2.4-1 겨냥, 담당자 확인 필요)

| 항목 | 내용 |
| --- | --- |
| 내용 | `bid_results` 에 `(dminstt_nm, category, rl_openg_dt)` 복합 인덱스 추가 또는 `(dminstt_nm, rl_openg_dt)` |
| 위험 | 스키마 변경(DDL)은 AGENTS.md 5항(기존 테이블·컬럼명·타입 변경 금지)의 직접 대상은 아니나 되돌리기 어려운 변경이므로 담당자 사전 확인 필요. 본 감사에서는 후보로만 기록 |
| 기대 | filesort 제거. 대형 기관 요청 꼬리 수십 ms 감소 |

---

## 4. 재측정 매트릭스 (수정 후 검증 절차)

모든 수정은 **수정 전 기준선 → 후보 적용 → 같은 명령 재측정**으로 3회 반복하며,
각 셀은 별도 실행입니다. 벤치마크는 `scripts/benchmark_latency.py` 와 동일한
payload(`category_code="Thng"`)를 쓰되 `--predict-concurrency` 를 조정합니다.

| concurrency | 경로 | 상태 | n | 목표 P95 | 비고 |
| ---: | --- | --- | ---: | ---: | --- |
| 1 | /predict (Thng) | warm | 100 | 100ms | 후보 A·B 적용 후 순차 11~14ms 가 몇 ms 로 내려가는지 |
| 1 | /predict (Thng) | cold (재시작 직후) | 100 | 기준선 1.93s 대비 감소 | 후보 C 검증. 재시작 직후 즉시 실행 |
| 2 | /predict (Thng) | warm | 100 | 100ms | 1→2 에서 증폭률 관찰 |
| 4 | /predict (Thng) | warm | 100 | 100ms | 4 동시성에서 oversubscription 시작 여부 |
| 10 | /predict (Thng) | warm | 100 | 100ms | 현재 P50 166.2ms / P95 627.0ms 기준선과 직접 비교 |
| 10 | /predict-price (Servc 실공고, bid_id 순회) | warm | 100 | 100ms | DB 쿼리 3종 + 분위 모델 포함 실사용 궤적. 후보 D·E 검증 |

판정 기준:

| 판정 | 조건 |
| --- | --- |
| 목표 달성 | warm concurrency 10 P95 <= 100ms, 오류 0건 |
| 후보 채택 | A→B→C 순으로 1개씩 적용, 각 단계 P95 감소 + 예측값 동등성 회귀 통과 |
| 기각 | P95 미감소 또는 예측값 동등성 회귀 실패 (수치로 기록) |

cold 측정은 `docker compose restart app` 직후 30초 안에 시작하며, warm 은 cold
측정 종료 후 2분 이상 경과 뒤 실행합니다.

---

## 5. 금지 및 유의 (이 감사의 범위)

- 본 감사는 읽기 전용입니다. 위 후보 중 어느 것도 이 문서와 함께 적용하지 않았습니다.
- 예측값 동등성 회귀 없이 후보 A 를 승격하면 안 됩니다 (부동소수 합산 순서).
- 재발주 이력 인덱스(후보 E)는 담당자 확인 전 실행 금지.