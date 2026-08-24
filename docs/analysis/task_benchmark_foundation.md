# Task Analysis: Benchmark Foundation and Cross-Platform Provenance

> **작성일**: 2026-08-24
> **Task ID**: `task_058756205a79`
> **Role**: builder
> **목적**: `benchmark_latency`의 검증된 provenance 기능을 공통 `scripts/benchmark_provenance.py`로 추출하고, 기존 공개 동작을 보존하면서 Compose LLM 모델 override, effective Uvicorn worker 기록, 크로스플랫폼 host/Docker 계측을 fail-closed 테스트로 보강.

---

## 1. 개요 및 변경 배경

Phase 7 레이턴시 및 처리량 벤치마크 하네스는 실측 데이터의 신뢰성을 보장하기 위해 대상 Docker 컨테이너의 식별자(Container ID, Image ID, Image Digest, RepoDigest, 소스 마운트 경로, Git SHA, Git Dirty 상태 등)를 엄격히 검증하는 fail-closed provenance 체계를 갖추고 있습니다.

기존 구현에서 식별된 다음 4가지 핵심 과제를 해결하고 공통 기반 계층을 정립하였습니다:
1. **공통 재사용성 부재**: `benchmark_latency.py` 내부에 강결합되어 있던 provenance 및 호스트 부하 계측 로직을 공통 모듈 `scripts/benchmark_provenance.py`로 분리하여 타 벤치마크 도구들이 일관된 규약으로 재사용할 수 있도록 개선.
2. **Compose LLM 모델 하드코딩 해제**: `docker-compose.yml`의 `app` 및 `worker` 서비스에 `OLLAMA_MODEL=gemma4:e4b`로 고정되어 `.env` 및 환경변수 override가 무시되던 문제를 `${OLLAMA_MODEL:-gemma4:e4b}` 구문으로 수정.
3. **실효 Uvicorn 워커 수(effective_web_workers) 미기록 개선**: 컨테이너 환경변수 `WEB_CONCURRENCY`가 미설정된 경우에도 `Config.Cmd`의 실행 인자(`--workers` / `-w`)를 안전하게 파싱하여 실제 정수 워커 수와 판정 사유를 기록.
4. **크로스플랫폼 호환성 강화**: `os.getloadavg`를 지원하지 않는 Windows 및 Docker CLI가 가용하지 않은 환경에서 비정상 크래시 없이 안전하게 동작하도록 방어 로직 구축.

---

## 2. 주요 설계 및 구현 상세

### 2.1 공통 계층 추출 (`scripts/benchmark_provenance.py`)

다음 기능들이 `scripts/benchmark_provenance.py` 단일 모듈로 추출되었습니다:
- **BuildProvenanceError**: 빌드 및 컨테이너 provenance 조회 실패/불일치 시 발생하는 단일 예외.
- **PROVENANCE_IDENTITY_KEYS**: 측정 시작/종료 간 컨테이너 교체, 소스 수정(dirty), 이미지 변경 여부를 판정하는 불변 식별자 키 튜플.
- **PERF_CONFIG_ALLOWLIST**: 성능 영향 환경변수 허용 목록 (`WEB_CONCURRENCY`, `PREDICTION_GC_MODE`, `LATENCY_SEGMENT_LOGGING`, `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_TEMPERATURE`, `GEMINI_MODEL`). 비밀값(SECRET_KEY, DB_PASSWORD 등)은 철저히 제외.
- **reproducibility_metadata**: 대상 컨테이너/이미지/소스/포트 바인딩 결박을 fail-closed로 검증하고 전체 메타데이터를 반환.
- **verify_provenance_consistency**: 시작/종료 메타데이터 대조를 통해 측정 중 컨테이너/이미지/소스 변경 감지.
- **HostLoadMonitor / host_load_metadata / single_host_load_sample**: 5초 주기 백그라운드 모니터링 및 min/median/max 통계 산출.

### 2.2 하위 호환성 보장 (`scripts/benchmark_latency.py`)

기존 `scripts/benchmark_latency.py`는 `scripts.benchmark_provenance`의 모든 인터페이스를 re-export하며, 기존 테스트 및 호출 계약과의 100% 호환성을 유지합니다:
- `_command_output`, `single_host_load_sample` 등을 wrapper 형태로 제공하여 테스트 시 monkeypatch 주입이 공통 모듈 내부까지 정상 전파되도록 구성.
- 기존 CLI 인자, 옵션 플래그(`--allow-unknown-provenance`), JSON 출력 스키마 완벽 보존.

### 2.3 실효 Uvicorn 워커 수 파싱 (`_parse_effective_workers`)

`Config.Cmd`에서 실행 인자를 안전하게 해석합니다:
- **분리형**: `["uvicorn", "main:app", "--workers", "4"]`, `["-w", "2"]`, `"uvicorn ... --workers 3"` -> 정수 워커 반환 (`reason: null`)
- **등호형**: `["uvicorn", "main:app", "--workers=4"]`, `["-w=2"]`, `"uvicorn ... --workers=3"` -> 정수 워커 반환 (`reason: null`)
- **누락**: 워커 플래그 부재 시 -> `effective_web_workers: null`, `effective_web_workers_reason: "workers_flag_not_found"`
- **비정상**: 정수 변환 불가/인자 누락/문법 오류 시 -> `effective_web_workers: null`, 상세 사유 문자열 기록

### 2.4 크로스플랫폼 방어 로직

- **Windows os.getloadavg**: `getattr(os, "getloadavg", None)` 조회를 통해 함수 부재 시 `AttributeError` 없이 `None` 반환.
- **Subprocess 호출**: `OSError`(FileNotFoundError 포함) 및 `CalledProcessError` 발생 시 크래시 없이 `"unknown"`으로 안전 반환 (strict 모드에서는 fail-closed로 거부).

---

## 3. 검증 결과 요약

| 검증 항목 | 명령어 | 결과 |
| --- | --- | :---: |
| 공통 provenance 단위 테스트 | `uv run pytest tests/test_benchmark_provenance.py` | PASS (31 passed) |
| 레이턴시 하네스 회귀 테스트 | `uv run pytest tests/test_benchmark_latency.py` | PASS (40 passed) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | PASS (전량 통과) |
| Docker Compose 설정 유효성 | `docker compose config -q` | PASS |
| OLLAMA_MODEL override 동작 | `OLLAMA_MODEL=custom:test docker compose config` | PASS (app/worker 적용 확인) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | PASS (12/12) |

---

## 4. 결론 및 산출물

1. `scripts/benchmark_provenance.py` 신규 작성 완료
2. `docker-compose.yml` `OLLAMA_MODEL` override 적용 완료
3. `scripts/benchmark_latency.py` 공통 모듈 연동 및 re-export 호환 완료
4. `tests/test_benchmark_provenance.py` 신규 테스트 스위트 작성 완료
5. `tests/test_benchmark_latency.py` 크로스플랫폼 및 effective workers 정합성 업데이트 완료
