# P1 예측 계측 준비 완료 보고 (실제 P95 미측정)

## 작업 결과 요약
* `/predict` 및 `/predict-price` 엔드포인트에 예측 의미를 보존하는 wall/thread_cpu/model 구간 최소 계측을 기계 파싱 가능한 형태(`endpoint=..., wall_ms=..., thread_cpu_ms=..., model_wall_ms=..., model_thread_cpu_ms=...`)로 구현 완료했습니다.
* 출력 동등성(200 성공 및 응답값 검증) 및 계측 형식 검증을 위한 단위 테스트(`tests/test_predict_instrumentation.py`)를 작성했으며 `app.dependency_overrides` 의존성 복구가 테스트 간 고립을 완벽히 보장하도록 강화했습니다.
* 본 작업은 실제 운영 모델의 P95 벤치마크 및 100ms 병목 개선을 위한 사전 **계측 로직 준비 단계**이며, 아직 **실제 P95 벤치마크는 미측정** 상태입니다. 해당 단계는 코디네이터 지침에 따라 병합 후 주 저장소에서 별도 수행해야 합니다.

## 커밋 역할 구분
본 작업 트리(kwanbum217/p1-predict-p95)에서의 커밋들은 다음의 역할을 갖습니다:
1. **`26d5c73`**: 예측 동등성을 보존하는 기초 계측 로직 삽입 및 1차 단위 테스트 도입
2. **`c16cf67`**: `pytest` 구동 시 계측 조건부 거짓 양성 단언문 제거 및 `app.dependency_overrides` 원복 구문(fixture) 적용
3. **새 SHA (본 변경사항)**: 다중 스레드 환경에서 정확한 CPU 시간 계측을 위해 `process_time`을 `thread_time`으로 교체하고 로그 포맷을 기계가 파싱 가능한 구조(`key=value` 형태의 4개 수치 인자)로 통일

## 벤치마크 및 판정
* 실제 운영 모델 파일이 필요한 P95 벤치마크 실행과 100ms 목표 달성을 위한 추가 병목 최적화(채택/기각 판정)는 **병합 후 코디네이터가 수행하도록 위임**(deferred_to_coordinator)합니다.

## 세부 정보
* **변경 파일**: `src/app/api/v1/predictions.py`, `tests/test_predict_instrumentation.py`, `docs/handoff/2026-08-13_p1_predict_instrumentation.md`
* **테스트 경로**: `tests/test_predict_instrumentation.py`
* **벤치마크 원시 경로**: `deferred_to_coordinator`
* **채택/기각 판정**: `deferred_to_coordinator`
