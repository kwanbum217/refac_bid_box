# 과업 수행 보고서: 예측 API 콜드스타트 P95 원인 조사 및 워밍업 방안 정리

> **작성일**: 2026-08-22
> **Task ID**: `task_coldstart_warmup_investigation`
> **역할**: Investigator
> **상태**: 완료 (Succeeded)
> **산출물**: `docs/analysis/predict_coldstart_analysis.md`

---

## 1. 과업 개요 및 목적

- **목적**: 2026-08-22 실측에서 확인된 예측 API 콜드스타트(1회차 P95 383.1ms, 2회차 122.1ms, 웜 3~6회차 61.9~83.6ms)의 원인을 코드 레벨에서 확인하고, 기동 시 워밍업 진입점 설계 및 관련 운영 위험을 정리합니다.
- **제약 사항 준수**:
  - 코드 변경 0건 유지 (읽기 전용 조사).
  - 재측정 미수행, Docker 구동 배제.
  - 워밍업 도입 여부는 결정하지 않고 중립 분석 제공.

---

## 2. 조사 결과 요약

### 2.1 코드 레벨 콜드스타트 비용 후보
1. **SQLAlchemy DB 커넥션 풀 지연 생성 (`src/app/core/db.py:18`)**:
   - `create_engine`은 커넥션을 사전 생성하지 않으며, 동시성 10(c=10) 요청이 첫 순간 진입할 때 10개 DB 커넥션(TCP 3-way handshake + MySQL 인증)이 동시 생성되어 I/O 및 락 병목 유발. (첫 호출 전용 - 확인됨)
2. **FastAPI/AnyIO 동기 엔드포인트 스레드 풀 지연 생성 (`src/app/api/v1/predictions.py:71`)**:
   - 동기 라우트 실행을 위한 10개의 워커 OS 스레드가 첫 요청 시 지연 생성됨. (첫 호출 전용 - 확인됨)
3. **ML 라이브러리 C-Extension / OpenMP 런타임 웜업 (`src/ml/model_registry.py:75`)**:
   - LightGBM/CatBoost 라이브러리의 C 런타임 내부 버퍼 및 스레드 구조체는 첫 번째 `estimator.predict(X)` 통과 시 할당됨. (첫 추론 전용 - 확인됨)
4. **FastAPI Lifespan 백그라운드 태스크 미대기 (`src/app/main.py:70-75`)**:
   - `_warm_predictor()`가 `asyncio.create_task`로 실행되고 즉시 `yield`하므로, 모델 로드 완료 전에 트래픽이 유입될 가능성 존재. (기동 직후 전용 - 확인됨)

### 2.2 워밍업 설계 진입점 및 방안
- **진입점**: `src/app/main.py`의 `lifespan` 컨텍스트 매니저.
- **방안**: `create_task` 대신 `await`로 동기 대기하고, (1) 모델 역직렬화, (2) 카테고리별 더미 추론(Dummy Inference), (3) DB 커넥션 풀 사전 연결(DB Ping/Select 1)을 수행한 뒤 트래픽을 수신하도록 구성.

### 2.3 워밍업 도입 시 위험
1. **기동 시간(Boot time) 증가**: 수 초 ~ 수십 초 기동 지연 발생.
2. **헬스체크 타이밍 충돌 및 CrashLoopBackOff**: 오케스트레이터의 헬스체크 타임아웃으로 인한 컨테이너 강제 재시작 루프 위험.
3. **실패 처리 정책 딜레마 (Fail-Fast vs Fail-Open)**: 일시적 장애 시 배포 전면 차단 vs 콜드스타트 재발.
4. **기동 순간 자원 스파이크**: 일시적인 CPU, 메모리, DB 커넥션 점유 급증.

---

## 3. 규칙 및 정합성 검증

- **규칙 검증**: `scripts/validate_agent_rules.py` 검증 수행 완료.
- **코드 무변경 확인**: `git status` 상 소스 코드 수정 없음 (문서 2건 신규 작성).
