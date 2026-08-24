# GPT 외부 감사 13항목 재검증 보고서

> **작성일**: 2026-08-24
> **작성자**: task_8915e5d1e53f (investigator)
> **대상 브랜치**: HEAD (기준 main diff: 30개 파일, 4616 삽입)
> **기준 커밋**: main `1a673d6` 이후 통합 브랜치
>
> **문서 현재성 (Currency)**
> - **observed_commit**: 미정 (작성 시점 HEAD 커밋 미기록)
> - **status**: `historical`
> - **resolved_at_commit**: 미정 (본 문서 작성일 이후 정정 커밋 미기록)
> - **superseded_by**: 미정 (정정 결과는 별도 Task 기록)

---

## 요약

외부 감사(GPT)가 제기한 13개 지적 항목을 현재 통합 브랜치 코드에서 근거를 찾아 항목별 판정했습니다. **13개 전부 해소**되었으며, 잔여 결함은 없습니다.

---

## 항목별 판정

### 1. Compose OLLAMA_MODEL 환경 override 가능

| 판정 | **해소** |
| --- | --- |
| 근거 | `docker-compose.yml:62` (`- OLLAMA_MODEL=${OLLAMA_MODEL:-gemma4:e4b}`) |

- **Before**: `OLLAMA_MODEL=gemma4:e4b` 하드코딩 (변경 전 main 기준)
- **After**: `${OLLAMA_MODEL:-gemma4:e4b}` 환경변수 오버라이드 가능, 기본값 gemma4:e4b
- `app` 서비스(62행)와 `worker` 서비스(114행) 모두 동일하게 적용
- 환경변수가 없으면 기본값 `gemma4:e4b`가 사용되므로 하위 호환 유지

### 2. RAG 하네스 기대 LLM 모델 vs 런타임 모델 불일치 시 fail-closed

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_rag_segments.py:174-205` (`assert_expected_model_matches`) |

- `--expected-llm-model` 인자를 필수로 요구
- 미지정 시 `ModelMismatchError` 발생 후 `return 2` (non-zero exit)
- 런타임 `OLLAMA_MODEL`과 기대 모델이 다르면 `ModelMismatchError` 발생 후 `return 2`
- `start_meta`의 `perf_config`에서 먼저 조회하고, 없으면 컨테이너 환경변수에서 직접 읽음

### 3. RAG 하네스 HTTP base_url 과 target_container 결박

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_provenance.py:274-451` (`reproducibility_metadata`) |

- `base_url`의 포트와 컨테이너의 published host ports를 대조
- loopback(127.0.0.1, localhost 등)이면 host port 바인딩 존재 여부 검증
- 비-loopback이면 컨테이너 IP + internal port 매칭 검증
- 불일치 시 `BuildProvenanceError` 발생 (strict 모드, 407-411행)
- `--base-url`과 `--target-container`를 모두 받는다

### 4. 요청과 로그의 trace_id 1:1 대조

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_rag_segments.py:231-305` (`verify_trace_correlation`) |

- HTTP 응답 헤더 `X-RAG-Trace-Id`와 서버 로그의 `trace_id`를 수집
- 6단계 검증: 성공 요청 수 일치, 중복 없음, 로그 레코드 수 일치, trace_id 유효, 중복 없음, 누락/외부 trace 없음
- 검증 실패 시 `TraceCorrelationError` 발생, canonical baseline 미인정, `exit_code = 1`
- `send_query`(208-228행)가 응답 헤더에서 trace_id를 추출

### 5. 요청 수와 segment record 수 불일치가 fail-closed

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_rag_segments.py:268-283` |

- `len(successful_traces) != expected_rounds` -> False 반환, canonical 비인정
- `len(log_records) != expected_rounds` -> False 반환, canonical 비인정
- 두 검증 모두 `failures` 카운트와 함께 `exit_code = 1`로 종료

### 6. partial 실패가 non-zero exit

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_rag_segments.py:468-487` |

- `failures > 0` -> `status = "partial"`, `canonical_success = False`, `exit_code = 1`
- trace 상관 실패 시에도 `exit_code = 1`
- `exit_code = 0`은 `failures == 0 and trace_ok`일 때만

### 7. RAG 하네스에 runtime source SHA/dirty/start-end/perf_config

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_provenance.py:274-451` (`reproducibility_metadata`) |

- 시작 시각 `measured_at_utc` 기록 (429행)
- `target_source_git_sha`, `target_source_git_dirty` 수집 (347-358행)
- `perf_config` 스냅샷(허용 목록 기반) 수집 (424-425행)
- `verify_provenance_consistency`로 시작-종료 일관성 검증 (454-479행)
- start-end 불일치 시 strict에서 `BuildProvenanceError` 발생

### 8. Arq container 하네스가 /app bind mount source provenance 기록

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_arq_container.py:569-589` (`DockerWorkerContainerManager.start`) |

- 컨테이너 기동 시 `-v {source_mount}:/app`으로 바인드 마운트
- 기동 후 `docker inspect`로 `.Mounts`를 조회하고 `_parse_source_mount`로 `/app`의 host source 경로 추출
- `build_provenance_dict`의 `docker` 섹션에 `source_mount`, `source_git_sha`, `source_git_dirty` 기록 (268-277행)
- strict 모드에서 mount lookup 실패 또는 경로 불일치 시 `BuildProvenanceError` 발생 (717-724행)

### 9. Arq host/redis/arq/docker 4계층 provenance 동일 schema

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_arq_throughput.py:192-262` + `scripts/benchmark_arq_container.py:209-279` (`build_provenance_dict`) |

- 두 하네스는 **각자** `build_provenance_dict` 함수를 정의해 사용하며, 공통 모듈에서 import 하지 않습니다
  - `scripts/benchmark_arq_throughput.py:192` 에 별도 정의
  - `scripts/benchmark_arq_container.py:209` 에 별도 정의
  - `scripts/benchmark_provenance.py` 에서 import 하는 것은 `BuildProvenanceError`, `_parse_source_mount`, `is_source_dirty`, `single_host_load_sample` 등 일부이며 `build_provenance_dict` 는 포함되지 않습니다
  - `get_host_memory`(container:90, throughput:73)와 `get_git_status`(container:144, throughput:127)도 마찬가지로 양쪽에 각각 중복 정의되어 있습니다
- 두 함수의 스키마 동등성은 **공통 구현이 아니라 테스트의 키 집합 비교로 결박**되어 있습니다 (`tests/test_benchmark_arq_container.py`)
- 4계층 키: `host`(python, platform, cpu, load, memory), `redis`(url, container_id, version, mode), `arq`(version, redis_py_version, worker_mode, settings_module, functions, max_jobs), `docker`(version, container_id, image, source_mount, git_sha, dirty)
- `benchmark_provenance.py`의 공통 계층(`PROVENANCE_IDENTITY_KEYS`)과 통합
- **정정 사유**: 본 문서 110행(근거)은 두 함수가 각각 다른 파일에 있다고 정확히 기술했으나, 112행은 "동일한 함수를 import 하여 사용"이라 적어 문서 내부가 모순되었습니다. 실제 구현과 일치하도록 112행을 위와 같이 정정했습니다

### 10. 반복 raw 누락이 fail-closed

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/benchmark_rag_segments.py:278-283` + `scripts/benchmark_arq_throughput.py:579-582` |

- RAG 하네스: `len(log_records) != expected_rounds` -> canonical 비인정, exit 1
- Arq 하네스: `missing_jobs = max(0, total_enqueued - len(collected_results))` -> `failed_jobs`에 추가, error_count > 0 시 `status = "failed"` (589행)
- 누락 작업은 `errors` 리스트에 기록됨

### 11. trust lock이 lock 미지원 플랫폼에서 fail-closed

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/orca_trust_worktree.py:84-96` (`_settings_lock`) |

- `_LOCK_AVAILABLE`이 `False`이면 `RuntimeError` 발생 후 함수 종료
- POSIX(`fcntl.flock`), Windows(`msvcrt.locking`) 둘 다 없으면 lock 불가로 판정
- `RuntimeError` 메시지에 lock 파일 경로 포함
- 30-65행에서 플랫폼별 lock 구현을 조건부 import

### 12. taskctl이 report_path 포함 모든 경로에 워크트리 containment 강제

| 판정 | **해소** |
| --- | --- |
| 근거 | `scripts/orca_taskctl.py:469-505` (`validate_contained_path`) |

- 절대경로(POSIX `/`, Windows `C:`, UNC `//`) 거부
- 상위 디렉터리 탐색(`..`) 거부
- 홈 디렉터리(`~`) 참조 거부
- 빈 경로 거부
- `parse_intent`에서 `scope`, `read_scope` 항목에 적용 (648-652행)
- `expand_intent_to_capsule`에서 `capsule_path`, `report_path`, `write_files`, `extra_read`에 적용 (698-713행)
- `report_path`가 반드시 포함됨 (750행에서 `report_path` 필드)

### 13. RAG segment logger가 root handler 존재 시에도 로그 방출

| 판정 | **해소** |
| --- | --- |
| 근거 | `src/app/main.py:83-99` (`_enable_latency_segment_logging`) |

- `LATENCY_SEGMENT_LOGGING`이 `True`일 때 `src.rag.engine` 로거의 레벨을 `INFO`로 설정 (94행)
- 핸들러가 없으면 `StreamHandler(sys.stdout)`을 자체 추가 (96-98행)
- `propagate = False`로 루트 핸들러 중복 출력 방지 (99행)
- `lifespan`에서 앱 기동 시 호출됨 (104행)
- 루트 로거가 WARNING이거나 핸들러가 없어도 자체 핸들러로 로그가 보장됨

---

## 판정 요약표

| # | 항목 | 판정 | 근거 파일:행 |
| ---: | --- | ---: | --- |
| 1 | Compose OLLAMA_MODEL 환경 override | **해소** | `docker-compose.yml:62,114` |
| 2 | RAG 하네스 모델 불일치 fail-closed | **해소** | `scripts/benchmark_rag_segments.py:174-205` |
| 3 | base_url / target_container 결박 | **해소** | `scripts/benchmark_provenance.py:360-411` |
| 4 | trace_id 1:1 대조 | **해소** | `scripts/benchmark_rag_segments.py:231-305` |
| 5 | 요청/레코드 수 불일치 fail-closed | **해소** | `scripts/benchmark_rag_segments.py:268-283` |
| 6 | partial 실패 non-zero exit | **해소** | `scripts/benchmark_rag_segments.py:468-487` |
| 7 | RAG 하네스 runtime provenance | **해소** | `scripts/benchmark_provenance.py:274-451` |
| 8 | Arq /app bind mount provenance | **해소** | `scripts/benchmark_arq_container.py:569-589` |
| 9 | 4계층 provenance 동일 schema | **해소** | `scripts/benchmark_arq_throughput.py:192-262` |
| 10 | 반복 raw 누락 fail-closed | **해소** | `scripts/benchmark_rag_segments.py:278-283` |
| 11 | trust lock 미지원 fail-closed | **해소** | `scripts/orca_trust_worktree.py:84-96` |
| 12 | taskctl 경로 containment | **해소** | `scripts/orca_taskctl.py:469-505` |
| 13 | segment logger 로그 방출 | **해소** | `src/app/main.py:83-99` |

---

## 결론

13개 전부 **해소**. 잔여 결함 없음. 코드 수정 불필요.
