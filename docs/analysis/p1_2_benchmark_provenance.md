# 벤치마크 컨테이너 Provenance 분리 및 Strict JSON 직렬화 보고서 (P1-2)

> **작성일**: 2026-08-23
> **작업 ID**: `p1_2_benchmark_provenance`
> **관련 과업**: P1-2 (컨테이너 provenance 결합 분리), P2-3 (strict JSON 규약 정규화)
> **대상 파일**: [`scripts/benchmark_latency.py`](../../scripts/benchmark_latency.py), [`tests/test_benchmark_latency.py`](../../tests/test_benchmark_latency.py)

---

## 1. 개요 및 배경

기존 레이턴시 벤치마크 스크립트([`scripts/benchmark_latency.py`](../../scripts/benchmark_latency.py))는 재현성 메타데이터 수집 시 존재하지 않는 Docker Compose 서비스명(`backend`)을 조회하여 `docker_image_id`가 항상 `unknown`으로 기록되는 결함(P1-2)이 존재했습니다. 또한 원시 벤치마크 결과에 표본 부재 시 `NaN`이 잔존하여 표준 JSON 규약(`allow_nan=False`)을 위반하는 문제(P2-3)가 있었습니다.

본 작업에서는 Compose 서비스명을 실제 정의된 정본 서비스명인 `app`으로 정정하고, Harness Git SHA, Compose Image ID, Container ID, Target Container Image ID 3종+1종의 식별자를 명확히 분리 기록하며, 조회 실패 시 측정을 거부하는 `BuildProvenanceError`를 도입하고, `NaN` 부동소수점을 `null`로 정규화하는 엄격한 JSON 직렬화 체계를 구축했습니다.

---

## 2. 주요 변경 사항

| 구분 | 변경 전 | 변경 후 | 목적 및 효과 |
| --- | --- | --- | --- |
| Compose 서비스명 | `backend` (미존재) | `app` (정본 서비스명) | `docker compose images -q app` 정상 조회 |
| 식별자 분리 | `git_sha`, `docker_image_id` | `git_sha`, `docker_image_id`, `container_id`, `target_container_image_id` | Harness 실행 코드와 컨테이너 대상 이미지/인스턴스 식별자 3종 분리 |
| Provenance 검증 | 실패 시 `unknown` 묵인 | `BuildProvenanceError` 발생 및 측정 사전 거부 (`strict=True` 기본) | 미검증 환경의 벤치마크 실행 차단 |
| 강제 진행 옵션 | 없음 | `--allow-unknown-provenance` CLI 플래그 | 비정본/디버그 환경 실행 허용 분리 |
| 부동소수점 정규화 | 빈 표본 시 `float("nan")` 출력 | `sanitize_nan_to_none`으로 `None`(`null`) 정규화 | RFC 8259 표준 JSON 정합성 보장 |
| JSON 직렬화 | `json.dumps(allow_nan=True)` (기본값) | `dump_strict_json` (`allow_nan=False`) | `NaN` 잔존 시 직렬화 예외 발생 강제 |

---

## 3. Provenance 검증 및 직렬화 흐름

```mermaid
flowchart TD
    A[벤치마크 시작: scripts/benchmark_latency.py] --> B[reproducibility_metadata 호출]
    B --> C[git rev-parse HEAD: harness SHA]
    B --> D[docker compose images -q app: docker_image_id]
    B --> E[docker compose ps -q app: container_id]
    E --> F[docker inspect -f {{.Image}}: target_container_image_id]

    C & D & E & F --> G{strict 모드 및 unknown 여부}
    G -- unknown 존재 --> H[BuildProvenanceError 발생 / 측정 중단]
    G -- 전체 식별자 확인 --> I[서버 헬스체크 및 벤치마크 실행]

    I --> J[Samples 표본 수집 및 Percentile 계산]
    J --> K[Samples.as_dict: NaN을 None으로 변환]
    K --> L[build_evidence: sanitize_nan_to_none]
    L --> M[dump_strict_json: allow_nan=False]
    M --> N[RFC 8259 준수 strict JSON 저장]
```

---

## 4. 상세 구현 내용

### 4.1 BuildProvenanceError 및 식별자 3종 분리

[`scripts/benchmark_latency.py`](../../scripts/benchmark_latency.py)에 `BuildProvenanceError`를 정의하고 `reproducibility_metadata` 함수에서 다음 3종의 컨테이너/이미지 식별자를 분리 수집합니다:

1. `git_sha`: 벤치마크 실행 하네스 코드의 Git Commit SHA (`git rev-parse HEAD`)
2. `docker_image_id`: Compose `app` 서비스의 이미지 ID (`docker compose images -q app`)
3. `container_id`: 실행 중인 Compose `app` 컨테이너 ID (`docker compose ps -q app`)
4. `target_container_image_id`: 실행 컨테이너를 직접 inspect한 이미지 SHA (`docker inspect -f '{{.Image}}' <container_id>`)

`strict=True`(기본값)일 때 위 식별자 중 하나라도 `unknown`이거나 조회에 실패하면 `BuildProvenanceError`를 발생시키며, `main()` 진입 시점에 이를 사전 검증하여 부하 측정이 시작되기 전에 즉시 종료합니다.

### 4.2 Strict JSON 직렬화 및 NaN 정규화

- `Samples.as_dict()`: 표본이 없어 `percentile()`이 `NaN`을 반환하는 경우 `None`으로 변환.
- `sanitize_nan_to_none(obj)`: 중첩 딕셔너리, 리스트, 튜플을 재귀 탐색하여 `math.isnan()` 또는 `math.isinf()` 값을 `None`으로 치환.
- `dump_strict_json(data, **kwargs)`: `sanitize_nan_to_none` 적용 후 `json.dumps(..., allow_nan=False)`를 강제하여 strict JSON 문자열을 생성.

---

## 5. 검증 결과

### 5.1 단위 테스트 결과

[`tests/test_benchmark_latency.py`](../../tests/test_benchmark_latency.py)에 신규 검증 케이스를 추가하고 전체 통과를 확인했습니다:

```bash
$ uv run pytest tests/test_benchmark_latency.py -q
.................                                                        [100%]
17 passed, 1 warning in 0.06s
```

추가 및 갱신된 테스트 항목:
- `test_reproducibility_metadata_queries_app_service_and_inspect`: `app` 서비스 조회 및 inspect 호출 경로 검증
- `test_reproducibility_metadata_raises_build_provenance_error_on_unknown`: `docker_image_id`, `container_id`, `target_container_image_id` 미확인 시 `BuildProvenanceError` 발생 검증
- `test_strict_json_serialization_sanitizes_nan_to_null`: `NaN`/`Inf`의 `null` 변환 및 `allow_nan=False` 직렬화 검증
- `test_build_evidence_strict_provenance_and_nan_normalization`: `build_evidence` 연동 검증
- `test_reproducibility_metadata_marks_failed_docker_lookup_unknown`: `strict=False` 시 호환성 검증

### 5.2 불변식 및 데이터 무손실 검증

- 기존 원시 벤치마크 JSON 파일(`data/benchmarks/*.json`)에 대한 임의 수정이 없음을 확인했습니다 (`git diff` 변경 0건).
- 변경된 파일은 허용 목록([`scripts/benchmark_latency.py`](../../scripts/benchmark_latency.py), [`tests/test_benchmark_latency.py`](../../tests/test_benchmark_latency.py), [`docs/analysis/p1_2_benchmark_provenance.md`](p1_2_benchmark_provenance.md)) 3개로 한정됩니다.
