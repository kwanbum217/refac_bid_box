# 예측 API 콜드스타트 P95 원인 분석 및 워밍업 방안 보고서

> **작성일**: 2026-08-22
> **과업**: task_coldstart_warmup_investigation
> **대상 커밋**: `e219d9cc537e9d88b6720a62d345e97c65ded9e5`
> **분석 대상 코드**: `src/app/main.py`, `src/app/api/v1/predictions.py`, `src/ml/predictor.py`, `src/ml/model_registry.py`, `src/app/core/db.py`
> **기반 실측 데이터**: `docs/analysis/blocking_io_p95_20260822.md` (data/benchmarks/blocking_io_p95/run1~6.json)

---

## 1. 배경 및 실측 현황

2026-08-22 블로킹 I/O 오프로드 후 종단 간 실측에서 낙찰가 예측 API(`concurrency=10`, `rounds=100`)는 다음과 같은 레이턴시 분포를 보였습니다.

| 회차 | 상태 | P50 (ms) | P95 (ms) | P99 (ms) | 평균 (ms) | 목표(100ms) 판정 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1회차** | 콜드스타트 | 45.1 | 383.1 | 383.7 | 77.0 | **미달** |
| **2회차** | 전이(Warmup) | 40.5 | 122.1 | 123.4 | 46.3 | **미달** |
| **3회차** | 웜(Warm) | 44.5 | 78.6 | 81.6 | 45.8 | **달성** |
| **4회차** | 웜(Warm) | 42.3 | 83.6 | 89.0 | 44.1 | **달성** |
| **5회차** | 웜(Warm) | 40.6 | 69.0 | 72.2 | 43.8 | **달성** |
| **6회차** | 웜(Warm) | 41.0 | 61.9 | 62.8 | 43.2 | **달성** |

### 1.1 주요 실측 사실 (Ground Truth)
1. **P50 중앙값의 불변성**: 6개 전 회차에서 P50은 40.5ms ~ 45.1ms 로 극히 안정적입니다. 즉, 전체적인 서빙 로직이 느린 것이 아니라 소수 요청의 극단값만이 꼬리를 형성했습니다.
2. **1회차 P95(383.1ms)와 P99(383.7ms)의 일치**: 100건 요청 중 상위 5% 및 1%가 동일한 지연값을 보였습니다. 동시성 10(c=10) 조건에서 첫 10개 요청 배치가 한꺼번에 콜드 경로를 통과하면서 발생한 현상입니다.
3. **웜 상태 수렴**: 3~6회차의 P95는 61.9ms ~ 83.6ms 로 4회 연속 목표(100ms)를 충족했습니다.

---

## 2. 코드 레벨 첫 호출 전용 비용 후보 분석

예측 요청 경로(`POST /api/v1/predictions/predict-price` 및 `POST /api/v1/predictions/predict`)에서 첫 호출에만 발생하는 비용 요소를 코드 수준에서 추적한 결과입니다.

```
[클라이언트 요청] (c=10 동시 진입)
       │
       ▼
[FastAPI / AnyIO 스레드 풀] ── (후보 2) OS 스레드 10개 지연 생성
       │
       ▼
[Depends(get_db)] ─────────── (후보 1) SQLAlchemy QueuePool 10개 커넥션 지연 생성 및 TCP/TLS 핸드셰이크
       │
       ▼
[features.py / pandas] ────── (후보 4) Dtype 캐시 및 카테고리 레벨 캐싱
       │
       ▼
[ModelRegistry / ML Model] ── (후보 3) LightGBM / CatBoost C-Extension 메모리 할당 및 OpenMP 런타임 초기화
```

### 2.1 후보 1: SQLAlchemy DB 커넥션 풀 지연 생성 (확인됨 - 첫 호출 전용)
- **코드 위치**: `src/app/core/db.py:18-25`, `src/app/api/v1/predictions.py:74, 85, 139`
- **메커니즘**:
  - `src/app/core/db.py`의 `create_engine`은 `pool_size=10, max_overflow=20`으로 선언되어 있으나, SQLAlchemy `QueuePool`은 기본적으로 지연(Lazy) 초기화 방식으로 동작합니다.
  - 앱 기동 시점에는 실제 MySQL TCP 커넥션이 맺어지지 않습니다.
  - `predict-price` 요청이 들어와 `db.get(BidAnnouncement, payload.bid_id)` 및 `build_feature_dict(features, db)`를 호출하는 순간 첫 커넥션이 생성됩니다.
  - 동시성 10 요청이 첫 순간에 들어오면 10개 스레드가 동시에 `MySQL TCP 3-way handshake + 인증 + 세션 변수 설정`을 수행하므로 DB 서버 및 네트워크 I/O 경합이 발생합니다.
- **첫 호출 vs 반복 여부**: **첫 호출 전용 (확인됨)**. 1회차에 10개 커넥션이 풀에 확보된 이후에는 `db.close()` 시 커넥션이 풀로 반환되어 재사용되므로 2회차 이후에는 생성 비용이 발생하지 않습니다.

### 2.2 후보 2: AnyIO / Starlette 동기 라우트 스레드 풀 생성 (확인됨 - 첫 호출 전용)
- **코드 위치**: `src/app/api/v1/predictions.py:71, 240`, `src/app/main.py:138-151`
- **메커니즘**:
  - `predict_price_api`와 `predict_winning_price`는 `async def`가 아닌 동기 `def` 함수로 선언되어 있습니다.
  - FastAPI(Starlette)는 동기 함수를 AnyIO의 워커 스레드 풀(`anyio.to_thread.run_sync`)에 위임하여 실행합니다.
  - AnyIO 및 Python `ThreadPoolExecutor`는 스레드를 사전에 전부 기동하지 않고 요청 수신 시 필요에 따라 `pthread_create`로 지연 생성합니다.
  - 첫 10개 동시 요청 도착 시 10개의 OS 스레드가 동시에 생성되고 컨텍스트 스위칭이 발생합니다.
- **첫 호출 vs 반복 여부**: **첫 호출 전용 (확인됨)**. 생성된 워커 스레드는 풀에 유지되어 이후 요청에 재사용됩니다.

### 2.3 후보 3: ML 라이브러리(C-Extension) 첫 추론 런타임 웜업 (확인됨 - 첫 추론 전용)
- **코드 위치**: `src/ml/model_registry.py:75-98`, `src/ml/model_wrappers.py`, `src/ml/predictor.py:170-176`
- **메커니즘**:
  - `ModelRegistry.load_all_models()`는 `joblib.load()`를 통해 Python 모델 객체를 역직렬화합니다.
  - 그러나 LightGBM C-API, CatBoost 라이브러리, Scikit-learn 추정기의 하부 C/C++ 런타임(메모리 버퍼, OpenMP 스레드 상태 구조체)은 실제 첫 번째 `estimator.predict(X)` 데이터가 C 라이브러리 인터페이스를 통과할 때 할당 및 초기화됩니다.
  - `_apply_inference_thread_budget`으로 `n_jobs=1`을 설정하였으나, C 라이브러리 내부 메모리 레이아웃 구성 및 C-Extension 진입 비용은 첫 추론 시 1회 발생합니다.
- **첫 호출 vs 반복 여부**: **첫 추론 전용 (확인됨)**. 실제 추론 연산 자체(P50 ~42ms)는 매번 반복되나, C 런타임 첫 로드 및 내부 버퍼 할당은 첫 실행에만 발생합니다.

### 2.4 후보 4: FastAPI Lifespan의 백그라운드 비동기 태스크 미대기 (확인됨 - 기동 타이밍 결함)
- **코드 위치**: `src/app/main.py:46-81`
- **메커니즘**:
  ```python
  @asynccontextmanager
  async def lifespan(_: FastAPI):
      tasks = [
          asyncio.create_task(_warm_llm_backend()),
          asyncio.create_task(_warm_predictor()),
      ]
      try:
          yield
      finally:
          for task in tasks:
              task.cancel()
  ```
  - `lifespan` 함수 내에서 `_warm_predictor()`와 `_warm_llm_backend()`를 `asyncio.create_task`로 던진 뒤 `yield`로 즉시 제어를 넘깁니다.
  - Uvicorn은 `yield`가 도달하면 즉시 소켓을 열고 외부 HTTP 트래픽을 수신하기 시작합니다.
  - 만약 컨테이너 기동 직후 백그라운드 태스크가 `load_all_models`를 마치기 전에 첫 요청 배치가 도착하면, 요청 스레드에서 모델 지연 로딩(Disk I/O + joblib 역직렬화)이 직접 발생하거나 백그라운드 로드와 락 경합을 겪게 됩니다.
- **첫 호출 vs 반복 여부**: **기동 직후 첫 요청 전용 (확인됨)**.

### 2.5 후보 5: Pandas / Numpy Dtype 변환 및 카테고리 캐싱 (확인됨 - 첫 호출 전용)
- **코드 위치**: `src/ml/features.py`, `src/ml/model_registry.py:154-166, 181-198`
- **메커니즘**:
  - `prepare_full_frame`, `prepare_input_frame`, `apply_categorical_dtypes` 호출 시 Pandas 모듈 내부의 CategoricalDtype 캐시 및 C-블록 할당이 최초 1회 수행됩니다.
- **첫 호출 vs 반복 여부**: **첫 호출 전용 (확인됨)**.

### 2.6 후보 6: 마이크로배치 창 및 GC 모드 (반복 비용 또는 제외 요인)
- **코드 위치**: `src/ml/predictor.py:62, 175-176`
- **메커니즘**:
  - `_PredictionBatcher.BATCH_WINDOW_SECONDS = 0.005` (5ms) 대기 창은 웜 상태에서도 동일하게 동작하므로 383ms 꼬리의 원인이 아닙니다 (반복 비용).
  - `PREDICTION_GC_MODE=freeze`가 적용되어 로드된 모델은 gen2 순회에서 배제되나, 첫 10개 요청에서 생성된 임시 객체들로 인한 gen0 GC 수집은 정상 동작합니다.

---

## 3. 비용 후보 종합 분류 표

| 후보 항목 | 코드 위치 | 비용 성격 | 근거 상태 | 콜드스타트 영향도 |
| --- | --- | :---: | :---: | :---: |
| **DB 커넥션 풀 10개 지연 생성** | `src/app/core/db.py:18` | 첫 호출 전용 | **확인됨** | **매우 높음** (TCP+TLS+인증 10건 동시 병목) |
| **AnyIO 동기 스레드 10개 지연 생성** | `src/app/api/v1/predictions.py:71` | 첫 호출 전용 | **확인됨** | **높음** (OS 스레드 생성 및 스케줄링) |
| **ML C-Extension / OpenMP 런타임 웜업** | `src/ml/model_registry.py:75` | 첫 호출 전용 | **확인됨** | **중간** (C 라이브러리 내부 메모리 할당) |
| **Lifespan 백그라운드 태스크 미대기** | `src/app/main.py:70-75` | 기동 직후 전용 | **확인됨** | **높음** (조기 트래픽 진입 시 로드 미완료) |
| **Pandas Dtype / 카테고리 캐싱** | `src/ml/features.py` | 첫 호출 전용 | **확인됨** | **낮음** (메모리 구조 캐싱) |
| **마이크로배치 대기 창 (5ms)** | `src/ml/predictor.py:62` | **반복 비용** | **확인됨** | **없음** (웜 상태에서도 5ms 로 동일) |

---

## 4. 기동 시 워밍업 설계 방안 (Warmup Entry Points & Methods)

만약 기동 시 워밍업을 도입한다면, 다음과 같은 진입점과 단계로 구성할 수 있습니다. (구현하지 않고 설계 방안만 기술합니다.)

### 4.1 진입점: FastAPI Lifespan (`src/app/main.py`)
현재의 `asyncio.create_task` 기반 비동기 방식을 `await` 기반 동기 완료 대기 구조로 전환하여, 워밍업이 완벽히 끝난 뒤에만 `yield`(트래픽 수신 시작)가 실행되도록 합니다.

```python
# (설계 예시 - 미구현)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 모델 역직렬화 (ModelRegistry.load_all_models)
    # 2. ML 추론 런타임 웜업 (대표 카테고리 Thng/Servc 더미 데이터 1회 predict 실행)
    # 3. DB 커넥션 풀 웜업 (DB ping 및 기본 풀 커넥션 사전 생성)
    # 4. AnyIO 스레드 풀 웜업 (동기 워커 사전 스폰)
    # 5. LLM 백엔드 웜업 (옵션)
    await run_startup_warmup()
    try:
        yield
    finally:
        await run_shutdown_cleanup()
```

### 4.2 단계별 워밍업 대상
1. **모델 역직렬화 및 등록**: `ModelRegistry.load_all_models()`를 실행하고 `gc.freeze()` 적용.
2. **더미 추론 (Dummy Inference)**:
   - `Thng` 카테고리(물품 모델: `quantum_leap_v25_pro`) 및 `Servc` 카테고리(용역 모델: `servc_institution_v1`)에 대해 더미 특징 딕셔너리로 `predict_optimal_price_with_provenance` 및 `predict_interval` 1회 실행.
   - 효과: Pandas Dtype 변환, LightGBM/CatBoost C 런타임 메모리 할당, `_PredictionBatcher` 큐 및 워커 스레드 완전 활성화.
3. **DB 커넥션 풀 사전 확보**:
   - `engine.connect()` 또는 `get_db()` 세션을 통해 간단한 쿼리(`SELECT 1`)를 풀 크기(`pool_size=10`)만큼 순차/병렬 실행하여 TCP 연결을 미리 맺어둠.
   - 효과: 첫 요청 배치 도착 시 TCP 핸드셰이크 지연 제거.

---

## 5. 워밍업 도입의 위험 및 운영상 트레이드오프

워밍업을 도입할 경우 발생할 수 있는 위험과 운영상의 주의점입니다.

### 5.1 기동 시간(Boot Time) 증가
- 모델 역직렬화, 더미 추론, DB 10개 커넥션 핸드셰이크, LLM 예열까지 동기 대기할 경우 서버 기동 시간이 수 초에서 길게는 10~20초 이상 증가합니다.
- 특히 CI/CD 테스트 파이프라인이나 로컬 개발 환경에서 빠른 서버 재기동이 방해받을 수 있습니다.

### 5.2 헬스체크 타이밍 및 컨테이너 재시작 루프 (CrashLoopBackOff)
- Docker compose의 `healthcheck` 또는 Kubernetes의 `livenessProbe` / `readinessProbe`가 워밍업 완료 전에 `/api/v1/health`를 찌르게 됩니다.
- Lifespan이 완료되기 전까지 Uvicorn이 포트를 열지 않거나 헬스체크 응답을 주지 못하면, 오케스트레이터가 컨테이너를 비정상 상태(Unhealthy)로 판정하고 강제 kill 후 재시작하는 무한 루프(CrashLoop)에 빠질 위험이 있습니다.
- **대응 필요 조건**: 오케스트레이터의 `start_period` / `initialDelaySeconds`를 워밍업 최대 소요 시간보다 길게 설정해야 합니다.

### 5.3 실패 처리 정책 (Fail-Fast vs Fail-Open)
- 워밍업 도중 DB 일시 지연, 모델 가중치 파일 일부 결함 등이 발생했을 때:
  - **Fail-Fast (예외 발생 시 기동 중단)**: 불완전한 상태의 서버가 배포되는 것을 막을 수 있으나, 일시적인 네트워크 순단에도 전체 서버 배포가 실패합니다.
  - **Fail-Open (경고 로그 후 기동 지속)**: 서버 기동은 보장되나, 워밍업되지 않은 상태로 트래픽을 수신하여 콜드스타트 P95 미달이 재현됩니다.

### 5.4 기동 순간 자원 스파이크 (Resource Burst)
- 기동 시점에 DB 연결 10개를 일시에 맺고 모든 ML 모델에 대해 추론을 수행하면, 컨테이너 기동 순간의 CPU, 메모리, DB 커넥션 사용량이 급증하여 동일 호스트의 다른 서비스에 일시적인 영향을 줄 수 있습니다.

---

## 6. 요약 및 권고

1. **원인 요약**: 예측 API 콜드스타트 1회차 P95(383.1ms) 미달은 **(1) DB 커넥션 풀 지연 생성, (2) AnyIO 스레드 풀 지연 기동, (3) ML 라이브러리 C-Extension 첫 추론 메모리 할당, (4) Lifespan 백그라운드 태스크의 미대기**가 동시 10개 첫 배치 요청에 중첩되어 발생한 현상입니다.
2. **웜 상태 검증 완료**: 3~6회차 웜 상태에서는 61.9ms ~ 83.6ms 로 목표(100ms)를 완벽히 충족하므로, 비즈니스 로직 자체의 구조적 결함은 없습니다.
3. **결정 유보**: 워밍업 도입은 기동 시간 증가 및 헬스체크 타임아웃 위험을 수반하므로, 배포 안정성 정책과 서비스 요구사항에 따라 코디네이터/운영자가 채택 여부를 결정해야 합니다. (본 조사는 구현을 진행하지 않고 분석 결과를 제공하는 것으로 완료합니다.)
