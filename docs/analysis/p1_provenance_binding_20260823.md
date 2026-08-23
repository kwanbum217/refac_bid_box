# P1 벤치마크 Provenance 결박 및 Fail-Closed 검증 보고서

> **작성일**: 2026-08-23
> **우선순위**: P1 (Critical Provenance Integrity)
> **대상 모듈**: `scripts/benchmark_latency.py`, `scripts/benchmark_sse_gate.py`, `tests/test_benchmark_latency.py`, `tests/test_benchmark_sse_gate.py`
> **상태**: 구현 및 검증 완료

---

## 1. 개요 및 배경

`docs/handoff/2026-08-22_post_1a45ad5_audit.md`에서 지적된 바와 같이, 기존 레이턴시 및 SSE 벤치마크 하네스는 다음과 같은 신뢰 경계(Provenance Boundary) 결함이 존재했습니다:

1. **`base_url`과 실제 Docker 컨테이너 identity 미결박**:
   - `scripts/benchmark_latency.py`는 `base_url`의 포트/호스트와 무관하게 고정적으로 Docker Compose `app` 서비스를 조회했습니다.
   - 이로 인해 로컬 프로세스(예: 비-컨테이너 Uvicorn)나 다른 포트/컨테이너를 대상으로 실행하더라도 Compose `app`의 provenance 메타데이터가 잘못 기록될 수 있는 허점이 존재했습니다.
2. **SSE 하네스의 존재하지 않는 `backend` 서비스 조회 잔존**:
   - `scripts/benchmark_sse_gate.py`가 존재하지 않는 Compose 서비스명인 `backend`를 조회하여 provenance가 비대칭적이거나 불완전했습니다.
3. **식별자 의미 혼동 방지 (Key Separation)**:
   - `container_id`, `docker_image_id`, `target_container_image_id`, `image_digest`가 명확히 분리되지 않아 빌드 이미지와 실행 컨테이너 이미지 간 구분이 모호했습니다.

본 작업에서는 HTTP `base_url`과 실제 Docker 컨테이너 포트 바인딩 및 실행 상태를 fail-closed로 엄격히 검증하고, 예측 및 SSE 하네스의 provenance 정책을 100% 통합 일원화했습니다.

---

## 2. 주요 변경 사항

### 2.1 HTTP `base_url` ↔ 컨테이너 포트 바인딩 Fail-Closed 결박

- `urllib.parse`를 통해 `base_url`의 호스트 및 포트를 추출.
- 대상 컨테이너의 `NetworkSettings.Ports` 및 `NetworkSettings.IPAddress`를 파싱하여 호스트 포트 및 컨테이너 내부 포트 목록 도출.
- 루프백 주소(`127.0.0.1`, `localhost`, `0.0.0.0`, `::1`) 대상 연결 시 요청 포트가 컨테이너의 발행 호스트 포트에 포함되는지 검증.
- 컨테이너 직접 IP 대상 연결 시 요청 IP 및 포트가 컨테이너 내부 네트워크 설정과 일치하는지 검증.
- 포트 불일치, 컨테이너 정지 상태(`State.Running != true`), 또는 미존재 컨테이너인 경우 strict 모드(`strict=True`, 기본값)에서 `BuildProvenanceError`를 발생시키고 측정 시작 전에 fail-closed(종료 코드 2)로 거부.

### 2.2 SSE 하네스 Provenance 정책 일원화 및 `backend` 조회 제거

- `scripts/benchmark_sse_gate.py`에서 기존 `backend` Compose 서비스 조회를 완전히 제거.
- `scripts.benchmark_latency`의 `reproducibility_metadata`와 `BuildProvenanceError`를 공유하여 예측 하네스와 100% 동일한 provenance 정책 및 CLI 옵션(`--target-service`, `--target-container`, `--allow-unknown-provenance`) 지원.

### 2.3 Evidence 키 명확 분리 (Key Separation)

`meta` 블록 내 식별자 키를 명확히 분리하여 데이터 보존 및 사후 감사 가능성을 극대화:

| 키 | 설명 | 예시 |
| --- | --- | --- |
| `git_sha` | 하네스 실행 시점의 Git Commit SHA | `44602698...` |
| `docker_image_id` | Compose 서비스 또는 타깃 컨테이너의 기준 이미지 식별자 | `sha256:app_image...` |
| `container_id` | 현재 실행 중인 대상 컨테이너 ID | `abcdef123456...` |
| `target_container_image_id` | 실행 컨테이너가 기반하고 있는 실제 이미지 ID | `sha256:target_container...` |
| `image_digest` | 레지스트리 RepoDigest (로컬 빌드의 경우 `none (local build)`) | `refac_bid_box-app@sha256:...` |
| `container_name` | 대상 컨테이너 명칭 | `refac_bid_box-app-1` |
| `service_name` | 대상 Compose 서비스 명칭 | `app` |
| `base_url` | 검증된 측정 대상 HTTP URL | `http://127.0.0.1:8000` |
| `bound_port` | 검증 및 결박된 HTTP 포트 | `8000` |
| `port_bindings` | 컨테이너의 포트 매핑 구조체 목록 | `[{"container_port": 8000, "host_ip": "0.0.0.0", "host_port": 8000}]` |

### 2.4 Strict JSON 유틸리티 단일화

- `scripts/_strict_json.py`의 `dump_strict_json`, `sanitize_nan_to_none`을 `benchmark_latency.py` 및 `benchmark_sse_gate.py` 전역에서 공용 모듈로 통일하여 중복 구현 제거.

---

## 3. 검증 결과

### 3.1 벤치마크 단위 및 통합 테스트

```bash
uv run pytest tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py -v
```
- **결과**: 29 passed in 0.08s
- 검증된 케이스:
  - Compose `app` 서비스 및 inspect 정상 조회
  - `base_url` 포트 불일치 시 `BuildProvenanceError` 발생 및 fail-closed 거부
  - 컨테이너 정지(`State.Running == false`) 시 fail-closed 거부
  - 명시적 `--target-container` 지정 시 해당 컨테이너 결박 및 digest 분리
  - 컨테이너 직접 IP(`172.18.0.x`) 바인딩 검증
  - SSE 하네스의 `app` 서비스 사용 및 포트 불일치 감지
  - `main()` 진입점에서 provenance 실패 시 종료 코드 2 반환
  - `--allow-unknown-provenance` 명시 시 비강제 완화 동작
  - 엄격한 RFC-8259 JSON 직렬화 및 NaN -> null 정규화

### 3.2 다중 에이전트 규칙 정합성 검증

```bash
python3 scripts/validate_agent_rules.py --quiet
```
- **결과**: 12/12 건 전량 PASS

### 3.3 무손실 및 불변 원칙 준수 확인

- 기존 `data/benchmarks/` 내 raw JSON 파일 수정 건수: 0건
- `docker-compose.yml`, DB 스키마, 모델 가중치 변경 건수: 0건
- 이모지 사용 건수: 0건
