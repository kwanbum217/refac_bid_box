# 벤치마크 Start/End Provenance 결박 및 대상 교체 무효화(Fail-Closed) 보고서

> **작성일**: 2026-08-23
> **우선순위**: P2 (Provenance Integrity & Invalidation)
> **대상 모듈**: `scripts/benchmark_latency.py`, `scripts/benchmark_sse_gate.py`, `tests/test_benchmark_latency.py`, `tests/test_benchmark_sse_gate.py`
> **상태**: 구현 및 검증 완료

---

## 1. 개요 및 배경

기존 P1 provenance 결박 작업(`docs/analysis/p1_provenance_binding_20260823.md`)을 통해 측정 시작 시점의 `base_url`과 Docker 컨테이너 identity/포트 바인딩 결박은 완료되었습니다. 그러나 장시간 소요되는 벤치마크 측정 도중 대상 컨테이너가 재기동되거나 이미지가 교체되는 경우, 측정 시작 시점과 다른 대상을 측정하고도 정상 통과로 판정될 수 있는 신뢰 경계(Provenance Boundary) 허점이 존재했습니다.

본 작업에서는 측정의 **시작(start)**과 **종료(end)** 시점 양쪽의 provenance identity를 기록하고, 측정 중 대상 컨테이너 또는 이미지가 교체되었을 때 strict 모드에서 측정을 즉시 무효화(`BuildProvenanceError` 발생 및 종료 코드 2)하는 **Fail-Closed** 검증 메커니즘을 구현하고 회귀 테스트로 검증했습니다.

---

## 2. 주요 구현 내용

### 2.1 Identity 일관성 검증 함수 (`verify_provenance_consistency`)

`scripts/benchmark_latency.py`에 시작과 종료 시점의 provenance identity를 대조 검증하는 공용 함수를 구현했습니다:

- **검증 대상 키 (`PROVENANCE_IDENTITY_KEYS`)**:
  - `container_id`: 실행 중인 대상 컨테이너 ID
  - `target_container_image_id`: 실행 컨테이너가 기반한 이미지 식별자
  - `docker_image_id`: Compose 서비스 또는 대상 이미지 식별자
  - `image_digest`: 이미지 레지스트리 RepoDigest
  - `git_sha`: 하네스 실행 시점의 커밋 SHA
  - `container_name`: 컨테이너 명칭
  - `service_name`: Compose 서비스 명칭

- **동작 방식**:
  - 각 키에 대해 시작 값과 종료 값을 비교.
  - 불일치 발생 시:
    - `strict=True` (기본값): `BuildProvenanceError("Target container/image provenance changed during benchmark measurement: ...")` 발생.
    - `strict=False`: `False` 반환.

### 2.2 레이턴시 벤치마크 (`scripts/benchmark_latency.py`) 적용

1. **`main()` 생명주기 검증**:
   - 측정 시작 전 `start_meta = reproducibility_metadata(...)` 수집.
   - 벤치마크 측정(예측, SSE, 단발 질의) 진행.
   - 측정 완료 후 `end_meta = reproducibility_metadata(...)` 수집.
   - `verify_provenance_consistency(start_meta, end_meta, strict=strict_provenance)` 호출.
   - 교체 감지 시 에러 메시지 출력 후 종료 코드 2 반환 (fail-closed, 산출물 파일 저장 차단).
2. **`build_evidence()` 산출물 보존**:
   - `meta` 블록 내 `start_provenance`, `end_provenance`, `provenance_consistent: True` 필드를 영구 기록.
   - `start_meta`와 `end_meta` 불일치 시 `build_evidence()` 단계에서도 fail-closed 예외 발생.

### 2.3 SSE 게이트 하네스 (`scripts/benchmark_sse_gate.py`) 적용

1. **`main()` 생명주기 검증**:
   - 측정 시작 전 `start_meta = reproducibility_metadata(...)` 수집.
   - 게이트 측정(`run_benchmark`) 진행.
   - 측정 완료 후 `end_meta = reproducibility_metadata(...)` 수집 및 `verify_provenance_consistency` 검증.
   - 컨테이너 교체 감지 시 종료 코드 2 반환 및 산출물 파일 생성 차단.
2. **산출물 JSON 메타데이터 보존**:
   - `payload["meta"]`에 `start_provenance`, `end_provenance`, `provenance_consistent: True` 필드 보존.

---

## 3. 검증 결과

### 3.1 벤치마크 및 무효화 회귀 테스트

```bash
uv run pytest tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py -v
```

- **결과**: 37 passed in 10.11s
- **핵심 검증 항목**:
  1. `test_verify_provenance_consistency_success`: 시작/종료 메타데이터 동일 시 검증 통과.
  2. `test_verify_provenance_consistency_detects_container_id_swap`: 컨테이너 ID 변경 시 strict 모드에서 `BuildProvenanceError` 발생 및 non-strict에서 `False` 반환.
  3. `test_verify_provenance_consistency_detects_image_swap`: `target_container_image_id`, `docker_image_id`, `image_digest` 변경 시 `BuildProvenanceError` 발생.
  4. `test_verify_provenance_consistency_detects_git_sha_change`: `git_sha` 변경 시 `BuildProvenanceError` 발생.
  5. `test_build_evidence_stores_start_and_end_provenance`: `build_evidence` 내 `start_provenance`/`end_provenance` 기록 및 불일치 시 예외 발생.
  6. `test_benchmark_latency_main_fails_when_container_swapped_during_measurement`: 측정 도중 컨테이너가 교체되면 `main()`이 종료 코드 2로 즉시 실패하고 파일 저장을 차단함(fail-closed).
  7. `test_benchmark_sse_gate_main_fails_when_container_swapped_during_measurement`: SSE 게이트 측정 중 컨테이너 교체 시 종료 코드 2 반환 및 fail-closed 검증.
  8. `test_benchmark_sse_gate_output_records_start_and_end_provenance`: SSE 게이트 성공 시 결과 JSON에 시작/종료 provenance가 완벽히 기록됨을 검증.

### 3.2 전체 테스트 스위트 및 규칙 검증

```bash
uv run pytest tests/ -q -m 'not data_assets'
python3 scripts/validate_agent_rules.py --quiet
```

- `pytest`: 1790 passed, 6 skipped, 3 deselected, 292 warnings in 64.68s
- `validate_agent_rules`: 12/12 건 전량 PASS

---

## 4. 결론 및 산출물 정합성

| 요구사항 | 구현 상태 | 확인 근거 |
| --- | --- | --- |
| 시작/종료 시점 컨테이너/이미지 provenance 기록 | 완료 | `start_provenance`, `end_provenance` 메타 필드 보존 |
| 측정 중 대상 교체 시 strict 무효화 (Fail-Closed) | 완료 | `verify_provenance_consistency` 및 main() 종료 코드 2 |
| 교차 무효화 회귀 테스트 추가 및 통과 | 완료 | 8건 신규 테스트 추가 (총 37건 pass) |
| 기존 원시 증거 및 Docker Compose 파일 불변 유지 | 완료 | `data/benchmarks/`, `docker-compose.yml` 무변경 |
